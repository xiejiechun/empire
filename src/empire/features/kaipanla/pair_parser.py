"""Business-owned pair_parser; moved declarations retain existing behavior."""
import math
import re

from empire.features.kaipanla.alias_contract import validate_proof
from empire.features.kaipanla.source_protocol import TREND_TIMES, SourceError


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
        raise SourceError(f'开盘啦 {kind} 请求未成功（errcode={error[:40]}），不能确认空日期',
                          category='source_request', details={'interface_code': error[:40]})
    source_code = payload.get('code')
    proof = None
    if source_code != code:
        proof = (aliases or {}).get(source_code)
        if proof is None:
            raise SourceError('开盘啦返回证券与请求不一致，缺少已核实代码映射')
        validate_proof(proof, code, source_code)
    if str(payload.get('day')) != day.strftime('%Y%m%d'):
        raise SourceError('开盘啦返回证券或日期与请求不一致')
    field, width = ('trend', 5) if kind == 'trend' else ('bid', 4)
    rows = payload.get(field)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise SourceError('开盘啦点位为空或超过声明边界；不能证明完整')
    if all(isinstance(r, list) and len(r) == width and r[1] == 0 and r[3] == 0 for r in rows):
        raise SourceError('开盘啦返回全零价格/量占位点，未取得有效行情；不能推断停牌或空日', category='placeholder')
    number(payload.get('preclose_px'), '昨收', positive=True)
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
        missing = sorted(set(TREND_TIMES) - {r[0] for r in rows})
        raise SourceError('开盘啦分时分钟键集合不完整或重复', category='minute_gap',
                          details={'point_count': len(rows), 'missing_minutes': missing[:20]})
    # This is optional source metadata, not the business date or version guard.
    # Zero/missing means unknown; never manufacture an epoch or reject valid prices.
    source_time = payload.get('time')
    if source_time is not None and not (type(source_time) is int and source_time == 0):
        number(source_time, '来源时间', integer=True, positive=True)
    # No source count/sequence metadata exists for bid. A structurally valid full
    # response preserves all points, but cannot prove upstream tick completeness.
    return dict(code=code, source_code=source_code, alias=proof, day=day.isoformat(), source_time=source_time,
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
