"""Business-owned parser; moved declarations retain existing behavior."""
import math
import re

from empire.features.kaipanla.alias_contract import validate_proof
from empire.features.kaipanla.contract import PRODUCTS
from empire.features.kaipanla.pair_parser import parse_response
from empire.features.kaipanla.source_protocol import ACTION, TREND_TIMES, SourceError


def finite(value):
    if type(value) in (int, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and finite(v) for k, v in value.items())
    return value is None or isinstance(value, (str, bool))


def parse(payload, code, day, kind, aliases=None):
    item = PRODUCTS[kind]
    if not finite(payload):
        raise SourceError('来源包含非有限数值')
    if kind in ACTION:
        part = parse_response(payload, code, day, kind, aliases)
        return dict(code=code, trade_date=day.isoformat(), kind=kind,
            source_code=part['source_code'], aliases=aliases or {},
            metadata={k: payload[k] for k in ('time', 'time2', 'ts') if k in payload},
            data={item.field: part['points'], 'preclose_px': part['preclose_px']})
    if not isinstance(payload, dict) or str(payload.get('errcode')) != '0':
        raise SourceError('开盘啦接口未成功，不能证明空日', category='source_request')
    if str(payload.get('day', payload.get('Day'))).replace('-', '') != day.strftime('%Y%m%d'):
        raise SourceError('来源日期错配')
    # FenBi2 omits the security echo: association is the frozen request identity,
    # not a fabricated source identity. Other responses must echo a code.
    source_code = payload.get('code')
    if source_code is None and kind != 'trades':
        raise SourceError('来源缺少证券关联')
    if source_code is not None and source_code != code:
        proof = (aliases or {}).get(source_code)
        if not proof:
            raise SourceError('来源代码错配且缺少交易所映射证明')
        validate_proof(proof, code, source_code)
    if not finite(payload):
        raise SourceError('来源包含非有限数值')
    if kind == 'quote':
        real, book = payload.get('real'), payload.get('weituo')
        if not isinstance(real, dict) or not isinstance(book, dict):
            raise SourceError('缺少行情或买卖档位')
        for key in ('last_px', 'open_px', 'high_px', 'low_px', 'total_amount', 'total_turnover'):
            if type(real.get(key)) not in (int, float) or real[key] < 0:
                raise SourceError('盘口行情必需字段无效：' + key)
        if real['last_px'] <= 0 or real['high_px'] < real['low_px']:
            raise SourceError('盘口价格占位或日高低价错误')
        for side in ('b', 's'):
            for i in range(1, 11):
                level = book.get(side + str(i))
                if (not isinstance(level, list) or len(level) != 2
                        or any(type(v) not in (int, float) or v < 0 for v in level)):
                    raise SourceError('盘口档位价量结构无效')
            prices = [book[side + str(i)][0] for i in range(1, 11) if book[side + str(i)][0] > 0]
            if prices != sorted(prices, reverse=side == 'b'):
                raise SourceError('买卖档位价格顺序错误')
        data = {k: v for k, v in payload.items() if k not in
                ('errcode', 'ttag', 'ts', 'time', 'time2', 'day', 'code')}
    else:
        rows = payload.get(item.field)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100000:
            raise SourceError('来源序列为空或超过单日上限')
        if any(not isinstance(r, list) or len(r) != item.width for r in rows):
            raise SourceError('来源序列字段结构改变')
        clocks = [r[0] for r in rows]
        pattern = r'(?:[01][0-9]|2[0-3]):[0-5][0-9]' + (r':[0-5][0-9]' if kind == 'trades' else '')
        if any(not isinstance(t, str) or not re.fullmatch(pattern, t) for t in clocks):
            raise SourceError('来源时间标签无效')
        if clocks != sorted(clocks):
            raise SourceError('来源时间乱序')
        if kind != 'trades' and tuple(clocks) != TREND_TIMES:
            raise SourceError('分钟键集合缺失、重复或跨时段', category='minute_gap')
        if any(type(v) not in (int, float) for r in rows for v in r[1:]):
            raise SourceError('来源序列数值类型无效')
        if kind != 'large_order' and any(v < 0 for r in rows for v in r[1:]):
            raise SourceError('来源量价出现负值')
        if kind == 'trades' and any(type(payload.get(k)) is not int or payload[k] != len(rows)
                                    for k in ('Count', 'total')):
            raise SourceError('分笔总数不符或响应截断')
        data = {k: v for k, v in payload.items() if k not in
                ('errcode', 'ttag', 'time', 'time2', 'day', 'Day', 'code')}
    return dict(code=code, trade_date=day.isoformat(), kind=kind,
                source_code=source_code, aliases=aliases or {}, data=data,
                metadata={k: payload[k] for k in ('time', 'time2', 'ts') if k in payload})
