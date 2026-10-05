"""Reversible typed mapping; float masks preserve existing canonical JSON hashes."""
import json
from datetime import date, timedelta

from empire.contracts.market_storage import (
    BOOK_EXTRAS,
    EXTRAS,
    LAYOUT_VERSION,
    QUOTE_FIELDS,
    SERIES,
    numeric_values,
    restore_values,
)
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS
from empire.plugins.datasets.intraday import digest


def wire(value):
    result = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(result.encode()) > 16384:
        raise ValueError('业务扩展超过16KiB')
    return result


def obj(value):
    return json.loads(value) if isinstance(value, str) else value


def clock(value, seconds=False):
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        h, rest = divmod(total, 3600)
        m, s = divmod(rest, 60)
        return f'{h:02}:{m:02}' + (f':{s:02}' if seconds else '')
    return str(value)[:8 if seconds else 5]


def key_set(row):
    field = PRODUCTS[row['kind']].field
    if field:
        return digest([[i, p[0]] for i, p in enumerate(row['data'][field])])
    return digest([s + str(i) for s in ('b', 's') for i in range(1, 11)])


def encode(row, checksum, observed):
    kind, data = row['kind'], row['data']
    params = dict(unified_code=row['code'] + '.' + row['market'], trade_date=date.fromisoformat(row['trade_date']))
    head = dict(**params, kind=kind, source_code=row['source_code'],
        listing_date=date.fromisoformat(row['lifecycle']['listing_date']),
        listing_source=row['lifecycle']['listing_source'], market_start=date.fromisoformat(row['lifecycle']['market_start']),
        identity_extra=wire(row['aliases']), source_metadata=wire(row['metadata']),
        content_hash=checksum, version_observed_at=observed, contract_version=LAYOUT_VERSION,
        key_set_hash=key_set(row), point_count=1 if kind == 'quote' else len(data[PRODUCTS[kind].field]))
    facts = {}
    if kind in SERIES:
        table, columns = SERIES[kind]
        field = PRODUCTS[kind].field
        if set(data) - {field} - EXTRAS[kind]:
            raise ValueError('来源附加字段未经存储契约登记')
        head['product_extra'] = wire({k: v for k, v in data.items() if k != field})
        if kind == 'trades':
            from empire.plugins.datasets.trade_blocks import pack
            records = pack(data[field], params)
        else:
            records = []
            for i, point in enumerate(data[field]):
                values, mask = numeric_values(point[1:])
                records.append(dict(**params, seq=i, source_time=point[0], float_mask=mask,
                                    **dict(zip(columns, values, strict=True))))
        facts[table] = records
    else:
        if set(data) - {'real', 'weituo'} - EXTRAS[kind] or set(data['real']) - set(QUOTE_FIELDS):
            raise ValueError('盘口字段未经存储契约登记')
        levels = {s + str(i) for s in ('b', 's') for i in range(1, 11)}
        if set(data['weituo']) - levels - BOOK_EXTRAS:
            raise ValueError('盘口附加字段未经存储契约登记')
        head['product_extra'] = wire({'fields': {k: v for k, v in data.items() if k not in ('real', 'weituo')},
            'book': {k: v for k, v in data['weituo'].items() if k not in levels}})
        present = [k in data['real'] for k in QUOTE_FIELDS]
        supplied = [data['real'].get(k) for k in QUOTE_FIELDS]
        numbers, mask = numeric_values([v if v is not None else 0 for v in supplied])
        facts['stock_daily_quote'] = [dict(**params, float_mask=mask,
            present_mask=sum(1 << i for i, yes in enumerate(present) if yes),
            **{k: v if value is not None else None for k, v, value in zip(QUOTE_FIELDS, numbers, supplied, strict=True)})]
        facts['stock_daily_quote_level'] = []
        for side in ('b', 's'):
            for level in range(1, 11):
                values, mask = numeric_values(data['weituo'][side + str(level)])
                facts['stock_daily_quote_level'].append(dict(**params, side=side, level=level,
                    price=values[0], source_volume=values[1], float_mask=mask))
    return head, facts


def decode(head, facts):
    kind = head['kind']
    extra = obj(head['product_extra'])
    if kind in SERIES:
        table, columns = SERIES[kind]
        records = facts[table]
        if kind == 'trades':
            from empire.plugins.datasets.trade_blocks import unpack
            if [b['block_seq'] for b in records] != list(range((head['point_count']+199)//200)):
                raise ValueError('分笔块序号集合不完整')
            if any(b['point_count'] != min(200, head['point_count']-b['first_seq']) for b in records):
                raise ValueError('分笔块点数与证券日序号边界不一致')
            points = [p for block in records for p in unpack(block)]
            if len(points) != head['point_count']:
                raise ValueError('分笔点位集合不完整')
        else:
            points = [[clock(r['source_time']),
                       *restore_values([r[c] for c in columns], r['float_mask'])] for r in records]
            if [r['seq'] for r in records] != list(range(head['point_count'])):
                raise ValueError('来源序号集合不完整')
        data = {**extra, PRODUCTS[kind].field: points}
    else:
        q = facts['stock_daily_quote']
        if len(q) != 1:
            raise ValueError('日行情摘要缺失或重复')
        q = q[0]
        values = restore_values([q[k] if q[k] is not None else 0 for k in QUOTE_FIELDS], q['float_mask'])
        real = {k: v if q[k] is not None else None
                for i, (k, v) in enumerate(zip(QUOTE_FIELDS, values, strict=True)) if q['present_mask'] & (1 << i)}
        book = {r['side'] + str(r['level']): restore_values([r['price'], r['source_volume']], r['float_mask'])
                for r in facts['stock_daily_quote_level']}
        if set(book) != {s + str(i) for s in ('b', 's') for i in range(1, 11)}:
            raise ValueError('盘口档位集合不完整')
        data = {**extra['fields'], 'real': real, 'weituo': {**extra['book'], **book}}
    return dict(kind=kind, code=head['unified_code'][:6], market=head['unified_code'][-2:],
        trade_date=head['trade_date'].isoformat(), source_code=head['source_code'],
        aliases=obj(head['identity_extra']), data=data,
        lifecycle={k: head[k].isoformat() if k != 'listing_source' else head[k]
                   for k in ('listing_date', 'listing_source', 'market_start')}, metadata=obj(head['source_metadata']))
