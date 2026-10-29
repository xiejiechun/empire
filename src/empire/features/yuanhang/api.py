"""Validated native inputs inside the caller's existing read-only SQL snapshot."""
from datetime import UTC, date

from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.yuanhang.repository import read_heads, read_rows
from empire.sources.yuanhang_coverage import audit_financial
from empire.sources.yuanhang_history import price_quality
from empire.sources.yuanhang_payload import CONTRACT, digest


def price_inputs(conn, code, lower, upper):
    heads = conn.execute(text('SELECT * FROM yuanhang_price_year WHERE unified_code=:code '
        'ORDER BY quote_year LIMIT 151'), dict(code=code)).mappings().all()
    if not heads or len(heads) > 150:
        raise ValueError('远航版日线年度证明缺失或超限，请先初始化')
    first = heads[0]['quote_year']
    selected = [h for h in heads if max(first, lower.year) <= h['quote_year'] <= upper.year]
    if [h['quote_year'] for h in selected] != list(range(max(first, lower.year), upper.year + 1)):
        raise ValueError('远航版日线缺少连续年度证明，请补齐采集')
    prices, observed = [], []
    for h in selected:
        rows = read_rows(conn, code, 'prices', year=h['quote_year'])
        expected = dict(contract_version=CONTRACT, source_count=len(rows), row_count=len(rows),
            first_date=date.fromisoformat(rows[0][0]) if rows else None,
            last_date=date.fromisoformat(rows[-1][0]) if rows else None,
            key_hash=digest([r[0] for r in rows]), content_hash=digest(rows))
        if any(h[k] != v for k, v in expected.items()):
            raise ValueError('远航版日线正文与年度集合/内容证明不匹配')
        observed.append(h['version_observed_at'].replace(tzinfo=CHINA).astimezone(UTC))
        if any(price_quality(*r[1:5]) for r in rows if lower.isoformat() <= r[0] <= upper.isoformat()):
            raise ValueError('所选范围远航版来源OHLC关系异常；原值保留，请在历史行情页查看质量标记')
        prices.extend(dict(date=r[0], **dict(zip(('open', 'high', 'low', 'close'), r[1:5], strict=True)))
                      for r in rows if lower.isoformat() <= r[0] <= upper.isoformat())
    if not prices:
        raise ValueError('所选范围没有已归档的远航版日线')
    return prices, observed


def financial_inputs(conn, code):
    heads = read_heads(conn, code)
    if set(heads) != {'actions', 'capital'}:
        raise ValueError('远航版权息与股本联合证明尚未建立')
    payload = dict(contract=CONTRACT, code=code, native_market=heads['actions']['native_market'],
        actions=read_rows(conn, code, 'actions'), capital=read_rows(conn, code, 'capital'))
    problems = audit_financial(payload, payload['actions'], payload['capital'], heads)
    if problems:
        raise ValueError('远航版权息/股本正文与联合来源证明不匹配：' + ','.join(problems))
    observed = [h['version_observed_at'].replace(tzinfo=CHINA).astimezone(UTC) for h in heads.values()]
    return payload['actions'], observed
