"""Cross-pool unique reason work; no current-universe filter or duplicate owners."""
import json
from datetime import UTC, datetime

from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.yuanhang_limits.contract import SOURCE, project
from empire.features.yuanhang_limits.planning import calendar_dates


async def reason_plan(query, *, force=False, exclude=(), through=None, scan_after=None, scope='all'):
    if scope not in ('all', 'recent', 'backfill'):
        raise ValueError('原因规划范围无效')
    now = datetime.now(CHINA)
    def calendar(conn):
        cutoff, message = read_trade_day_cutoff(conn, now)
        if cutoff is None:
            raise ValueError(message)
        endpoint = min(cutoff.date().isoformat(), through) if through else cutoff.date().isoformat()
        rows = [(r[0].isoformat(), r[1]) for r in conn.execute(text('SELECT trade_date,is_trade '
            'FROM trade_calendar WHERE trade_date BETWEEN :first AND :last ORDER BY trade_date'),
            dict(first='1990-12-19', last=endpoint))]
        if not rows or rows[0][0] != '1990-12-19':
            raise ValueError('原因全历史规划缺少正式日历')
        return endpoint, calendar_dates(rows, endpoint)
    cutoff, days = await query.read(calendar)
    expected = {day: (cutoff if i >= len(days) - 10 else day)
                for i, day in enumerate(days)}
    # This is a bounded calendar relation, not serialized business history.
    dates = json.dumps([dict(day=day, priority=int(i < len(days) - 10), expected=expected[day],
        expected_utc=datetime.fromisoformat(expected[day]).replace(tzinfo=CHINA).astimezone(UTC).isoformat(timespec='microseconds'))
        for i, day in enumerate(days)])
    marker = tuple(scan_after) if scan_after else (1, '1900-01-01', '') if scope == 'backfill' else (0, '9999-12-31', '')
    if len(marker) != 3 or marker[0] not in (0, 1):
        raise ValueError('原因规划游标无效')
    units = []
    while len(units) < 256:
        first = days[max(0, len(days) - 10)] if marker[0] == 0 else days[0]
        last = cutoff if marker[0] == 0 else days[-11] if len(days) > 10 else None
        if last is None:
            break

        def candidates(conn):
            # Each ordered input contributes at most 512 keys. The first 512 of
            # their union cannot contain a key beyond either input's first 512.
            # Push date/key and SQL freshness predicates before materialization.
            version = "JSON_UNQUOTE(JSON_EXTRACT(s.payload,CONCAT('$.units.\"',r.unified_code, '\".versions.\"',DATE_FORMAT(r.trade_date,'%Y-%m-%d'),'\"')))"
            due = f"(:force OR r.content_sha256 IS NULL OR r.observed_at>:now_local OR (r.observed_at<d.expected AND ({version} IS NULL OR {version}<d.expected_utc OR {version}>:now_utc)))"
            if marker[0] == 1 and not force:
                due = 'r.content_sha256 IS NULL'
            comparison = '<' if marker[0] == 0 else '>'
            direction = 'DESC' if marker[0] == 0 else 'ASC'
            scope = f"m.trade_date BETWEEN :first AND :last AND (m.trade_date{comparison}:day OR (m.trade_date=:day AND m.unified_code>:code))"
            branch = 'SELECT /*+ NO_BNL(d) */ DISTINCT m.trade_date,m.unified_code FROM {table} m '
            branch += 'STRAIGHT_JOIN dates d ON d.day=m.trade_date LEFT JOIN yuanhang_limit_reason r '
            branch += 'ON r.trade_date=m.trade_date AND r.unified_code=m.unified_code LEFT JOIN state s ON TRUE '
            branch += 'WHERE ' + scope + ' AND ' + due + f' ORDER BY m.trade_date {direction},m.unified_code LIMIT 512'
            sql = "WITH dates AS (SELECT day,MAX(expected) AS expected,MAX(expected_utc) AS expected_utc FROM JSON_TABLE(:dates,'$[*]' COLUMNS(day DATE PATH '$.day', expected DATE PATH '$.expected',expected_utc VARCHAR(40) PATH '$.expected_utc')) d GROUP BY day), "
            sql += 'state AS (SELECT payload FROM collection_state WHERE namespace=:namespace AND project_id=:project AND source=:source), '
            sql += 'member_keys AS (' + branch.format(table='yuanhang_limit_member') + '), '
            reason_branch = 'SELECT /*+ NO_BNL(d) */ m.trade_date,m.unified_code FROM yuanhang_limit_reason m FORCE INDEX (ix_yuanhang_reason_planning) '
            reason_branch += 'STRAIGHT_JOIN dates d ON d.day=m.trade_date LEFT JOIN state s ON TRUE '
            reason_branch += 'WHERE ' + scope + ' AND ' + due.replace('r.', 'm.')
            reason_branch += f' ORDER BY m.trade_date {direction},m.unified_code LIMIT 512'
            sql += 'reason_keys AS (' + reason_branch + ') '
            sql += 'SELECT c.trade_date,c.unified_code,:priority AS priority,r.content_sha256,r.observed_at,' + version + ' AS verified '
            sql += 'FROM (SELECT * FROM member_keys UNION SELECT * FROM reason_keys) c '
            sql += 'LEFT JOIN yuanhang_limit_reason r ON r.trade_date=c.trade_date AND r.unified_code=c.unified_code '
            sql += f'LEFT JOIN state s ON TRUE ORDER BY c.trade_date {direction},c.unified_code LIMIT 512'
            return [dict(r) for r in conn.execute(text(sql), dict(dates=dates, namespace=query.namespace,
                project=project('reason'), source=SOURCE, priority=marker[0], day=marker[1], code=marker[2],
                first=first, last=last, force=force, now_local=now.replace(tzinfo=None),
                now_utc=now.astimezone(UTC).isoformat(timespec='microseconds'))).mappings()]
        records = await query.read(candidates)
        if not records:
            if marker[0] == 0 and scope != 'recent':
                marker = (1, '1900-01-01', '')
                continue
            break
        identities = [r['trade_date'].isoformat() + ':' + r['unified_code'] for r in records]
        proofs = await query.cache_proofs('reason', identities)
        for record, identity in zip(records, identities):
            day, code = record['trade_date'].isoformat(), record['unified_code']
            if (day, code) in exclude:
                continue
            verified = record['verified']
            if record['observed_at'] and record['observed_at'].replace(tzinfo=CHINA) > now:
                raise ValueError('原因SQL业务观测时刻超前')
            if verified:
                stamp = datetime.fromisoformat(verified)
                if stamp.tzinfo is None or stamp.astimezone(CHINA) > now:
                    raise ValueError('原因SQL核验版本无效或超前')
            checked = (datetime.fromisoformat(verified).astimezone(CHINA).date().isoformat()
                       if verified else record['observed_at'].date().isoformat() if record['observed_at'] else '')
            proof = proofs.get(identity)
            if proof and proof['hash'] == record['content_sha256']:
                stamp = datetime.fromisoformat(proof['version'][0]).astimezone(CHINA)
                if stamp <= now:
                    checked = max(checked, stamp.date().isoformat())
            if force or record['content_sha256'] is None or marker[0] == 0 and checked < expected[day]:
                units.append([day, code])
                if len(units) == 256:
                    return dict(units=units, cutoff=cutoff, remaining=None,
                                scan_after=[record['priority'], day, code])
        final = records[-1]
        marker = (final['priority'], final['trade_date'].isoformat(), final['unified_code'])
        if len(records) < 512:
            if marker[0] == 0 and scope != 'recent':
                marker = (1, '1900-01-01', '')
                continue
            break
    return dict(units=units, cutoff=cutoff, remaining=0)
