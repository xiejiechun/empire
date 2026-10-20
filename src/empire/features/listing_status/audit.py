"""Audit requested months against the canonical SQL set, including empty dates."""
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.preparation import CheckEvidence
from empire.core.time import CHINA
from empire.features.listing_status.contract import (
    COLUMNS,
    FIRST,
    bounds,
    content,
    digest,
    months,
    valid_proof,
    validate_rows,
)
from empire.features.listing_status.dataset import TABLE


async def check(plugin, scope):
    today = datetime.now(CHINA).date()
    start = max(FIRST, date.fromisoformat(scope.start) if scope.start else FIRST)
    end = date.fromisoformat(scope.end) if scope.end else today
    expected = [m for m in months(end) if m >= start.strftime('%Y-%m')] if end >= start else []
    state = await plugin.state()
    proofs = state.get('months', {})
    # A requested slice still audits the whole confirmed last-month snapshot.
    last_end = proofs.get(end.strftime('%Y-%m'), {}).get('end', end.isoformat())
    try:
        read_end = min(today, max(end, date.fromisoformat(last_end)))
    except (ValueError, TypeError):
        read_end = end
    def read():
        with plugin.mysql.read_engine.connect() as conn:
            rows = conn.execute(text(f'SELECT {",".join(COLUMNS)} FROM {TABLE} '
                'WHERE event_date BETWEEN :start AND :end ORDER BY event_date,unified_code,event_type,record_key '
                'LIMIT 50001'), dict(start=max(FIRST, start.replace(day=1)), end=read_end)).all()
            return [[r[0].isoformat(), *r[1:]] for r in rows]
    values = await plugin.mysql.read(read)
    groups = defaultdict(list)
    for r in values:
        groups[r[0][:7]].append(r)
    complete, issues = len(values) < 50001 and bool(expected), []
    for month in expected:
        p, rows = proofs.get(month, {}), groups[month]
        try:
            proof_end = date.fromisoformat(p['end'])
            a, b = bounds(month, proof_end)
            valid = (valid_proof(p, month, proof_end) and b >= bounds(month, end)[1]
                     and validate_rows(rows, a, b) == rows
                     and p['digest'] == digest(content(rows, p['source_counts']))
                     and len(rows) == p['row_count'])
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            complete = False
            issues.append(month)
    latest_month = expected[-1] if expected else today.strftime('%Y-%m')
    latest = proofs.get(latest_month, {})
    fresh = False
    if complete and latest and valid_proof(latest, latest_month, date.fromisoformat(latest['end'])):
        try:
            observed = await plugin.latest_observed(latest_month, latest)
            fresh = timedelta(0) <= datetime.now(UTC) - observed <= timedelta(days=3)
        except (ValueError, TypeError):
            pass
    selected = [r for r in values if scope.includes(r[0]) and (not scope.codes or r[1][:6] in scope.codes)]
    def ev(key, ok, message):
        return CheckEvidence(key, 'pass' if ok else 'fail', message)
    detail = f'{len(expected)}个月；范围内{len(selected)}事件；缺失或集合不符月份{len(issues)}：' + '、'.join(issues[:8])
    return (
        ev('fields', complete, '证券、来源日期、三类事件与来源字段已核验；说明可空；' + detail),
        ev('keys', complete, '完整来源身份含并列说明，不按当前股票目录过滤；' + detail),
        ev('coverage', complete, '有效空日期与未核验分开，SQL内容摘要匹配月证明；' + detail),
        ev('quality', complete, '暂停、恢复、终止分别保存，不按简称判定退市；' + detail),
        ev('freshness', fresh, '声明范围末月核验完整，SQL或匹配可信摘要核验在三天内'),
        ev('temporal', complete, '来源日历日期用于事件查阅；无最后交易日、公告可用日或完整重新上市记录；不推断永久退市'),
    )
