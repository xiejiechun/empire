"""Anonymous historical source protocol; never reads account/session configuration."""
import hashlib
import json
import math
import re
from datetime import date
from functools import partial
from secrets import choice
from uuid import uuid4

from empire.plugins.collectors.kaipanla_alias import resolve, validate_proof
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity

URL = 'https://apphis.longhuvip.com/w1/api/index.php'
DOMAIN = 'longhuvip.com'
MODELS = ('PGBM10', 'SM-G9910', 'M2102K1C')
ACTION = {'trend': 'GetStockTrend', 'auction': 'GetStockBid'}
TREND_TIMES = tuple(
    f'{minute // 60:02d}:{minute % 60:02d}'
    for minute in (*range(570, 691), *range(781, 901))
)


class SourceError(ValueError):
    """An unsuccessful/ambiguous response must not advance collection coverage."""


def request_options(code, day, kind):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('开盘啦证券代码必须为六位数字')
    if not isinstance(day, date) or day < date(2021, 1, 1):
        raise ValueError('开盘啦历史范围从 2021-01-01 开始')
    if kind not in ACTION:
        raise ValueError('开盘啦请求类型无效')
    # Called by the shared downloader on every transport attempt, including retries.
    return dict(data=dict(c='StockL2History', a=ACTION[kind], StockID=code,
        Day=day.isoformat(), apiv='w44', PhoneOSNew='1', PhoneOS='1',
        DeviceID=str(uuid4()), VerSion='5.23.0.4'), headers={
        'User-Agent': f'Dalvik/2.1.0 (Linux; U; Android 12; {choice(MODELS)} Build/SP1A.210812.016)'})


def number(value, label, *, integer=False, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or (positive and value <= 0)
            or (integer and type(value) is not int)):
        raise SourceError(f'开盘啦 {label} 无效')
    return value


def parse_response(payload, code, day, kind, aliases=None):
    if not isinstance(payload, dict) or str(payload.get('errcode')) != '0':
        error = str(payload.get('errcode', 'missing')) if isinstance(payload, dict) else 'structure'
        # Error codes are diagnostics, never evidence of holidays, suspension or pre-listing.
        raise SourceError(f'开盘啦 {kind} 请求未成功（errcode={error[:40]}），不能确认空日期')
    source_code = payload.get('code')
    proof = None
    if source_code != code:
        proof = (aliases or {}).get(source_code)
        if proof is None:
            raise SourceError('开盘啦返回证券与请求不一致，缺少已核实代码映射')
        validate_proof(proof, code, source_code)
    if str(payload.get('day')) != day.strftime('%Y%m%d'):
        raise SourceError('开盘啦返回证券或日期与请求不一致')
    number(payload.get('time'), '来源时间', integer=True, positive=True)
    number(payload.get('preclose_px'), '昨收', positive=True)
    field, width = ('trend', 5) if kind == 'trend' else ('bid', 4)
    rows = payload.get(field)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise SourceError('开盘啦点位为空或超过声明边界；不能证明完整')
    previous = ''
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise SourceError('开盘啦点位字段结构无效')
        clock = row[0]
        if not isinstance(clock, str) or not re.fullmatch(r'[0-9]{2}:[0-9]{2}', clock):
            raise SourceError('开盘啦点位时间无效')
        if clock < previous:
            raise SourceError('开盘啦点位顺序错误')
        previous = clock
        number(row[1], '价格', positive=True)
        number(row[3], '来源量', integer=True)
        if kind == 'trend':
            number(row[2], '均价', positive=True)
            number(row[4], '来源标记', integer=True)
        else:
            number(row[2], '来源标记', integer=True)
            if not '09:15' <= clock <= '09:25':
                raise SourceError('开盘啦开盘竞价点位超出时间范围')
    if kind == 'trend' and tuple(row[0] for row in rows) != TREND_TIMES:
        raise SourceError('开盘啦分时分钟键集合不完整或重复')
    # No source count/sequence metadata exists for bid. A structurally valid full
    # response preserves all points, but cannot prove upstream tick completeness.
    return dict(code=code, source_code=source_code, alias=proof, day=day.isoformat(), source_time=payload['time'],
                preclose_px=payload['preclose_px'], points=[list(row) for row in rows])


def combine_day(trend, auction):
    if (trend['code'], trend['day'], trend['preclose_px']) != (
            auction['code'], auction['day'], auction['preclose_px']):
        raise SourceError('开盘啦分时与竞价证券、日期或昨收冲突')
    return dict(code=trend['code'], trade_date=trend['day'], preclose_px=trend['preclose_px'],
                trend=trend['points'], auction=auction['points'],
                source_times=[trend['source_time'], auction['source_time']],
                source_codes=[trend['source_code'], auction['source_code']],
                aliases={p['source_code']: p['alias'] for p in (trend, auction) if p['alias']})


async def fetch_part(collector, code, day, kind, market=None, listed=None):
    """Use Empire's shared routing, retries, rate limits and byte reservations."""
    await wait_for_capacity(collector.ingest, collector.stats)
    request_options(code, day, kind)  # Validate before requesting resource admission.
    response = await collector.http.request('POST', URL,
        attempt_options=partial(request_options, code, day, kind), max_redirects=0,
        allowed_domains=(DOMAIN,), project_id=collector.project_id,
        policy=collector.http.response_policy('generic'), max_retries=collector.request_retries)
    body = response.content
    diagnostic = dict(request_url=URL, status_code=response.status_code,
                      raw_body=body[:65536], observed_bytes=len(body),
                      body_sha256=hashlib.sha256(body).hexdigest(),
                      metadata=dict(code=code, day=day.isoformat(), kind=kind))
    try:
        payload = json.loads(body)
        source_code = payload.get('code') if isinstance(payload, dict) else None
        aliases = {}
        if (source_code != code and market == 'BJ' and listed
                and isinstance(source_code, str) and re.fullmatch(r'[48][0-9]{5}', source_code)):
            # Validate and consume this body before taking another HTTP reservation.
            # Otherwise the minimum legal single-response budget would deadlock
            # while awaiting an alias lookup with the first response still held.
            parsed = parse_response({**payload, 'code': code}, code, day, kind)
            response.close()
            del body, payload
            proof = await resolve(collector, code, source_code, listed)
            return {**parsed, 'source_code': source_code, 'alias': proof}
        return parse_response(payload, code, day, kind, aliases)
    except (ValueError, TypeError, KeyError) as exc:
        if not getattr(exc, 'diagnostic_recorded', False):
            exc.diagnostic_recorded = await record_error_safely(
                collector.records, collector.stats, collector.project_id, exc,
                stage='source_validation', unavailable_message='开盘啦错误样本暂未写入 Redis', fields=diagnostic)
        raise
    finally:
        response.close()


async def fetch_day(collector, code, day, market=None, listed=None):
    trend = await fetch_part(collector, code, day, 'trend', market, listed)
    auction = await fetch_part(collector, code, day, 'auction', market, listed)
    return combine_day(trend, auction)
