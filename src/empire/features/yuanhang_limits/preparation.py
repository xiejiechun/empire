"""Scope-explicit source-set audits, independent of collector completion labels."""
import json
from datetime import datetime, timedelta

from sqlalchemy import text

from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.yuanhang_limits.contract import POOLS, SOURCE, dataset, job, project
from empire.features.yuanhang_limits.model import digest
from empire.features.yuanhang_limits.planning import calendar_dates
from empire.features.yuanhang_limits.repository import decode_member
from empire.features.yuanhang_limits.storage import pool_payload, pool_proof, reason_payload

CONTRIBUTIONS = tuple(PreparationContribution('yuanhang_' + kind, 'yuanhang.limits.query',
    '同花顺远航版', project(kind), job(kind), dataset(kind), 'collector.yuanhang_limits_' + kind,
    ('tests/test_yuanhang_limits_source.py', 'tests/test_yuanhang_limits_planning.py'),
    ('tests/integration/test_yuanhang_limits_archive.py',), method='check_' + kind, scoped=True)
    for kind in [*POOLS, 'reason'])


async def check(query, kind, request=None):
    scope = PreparationScope.parse(request)
    now = datetime.now(CHINA)
    def dates(conn):
        cutoff, message = read_trade_day_cutoff(conn, now)
        if cutoff is None:
            raise ValueError(message)
        end = scope.end or cutoff.date().isoformat()
        start = scope.start or (cutoff.date() - timedelta(days=7)).isoformat()
        if end > cutoff.date().isoformat():
            raise ValueError('检查范围包含尚未结束的交易日')
        rows = list(conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
            'WHERE trade_date BETWEEN :first AND :last ORDER BY trade_date'), dict(first=start, last=end)))
        from datetime import date
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if len(rows) != (last - first).days + 1 or any(r[0] != first + timedelta(days=i) or r[1] not in (0, 1)
                                                      for i, r in enumerate(rows)):
            raise ValueError('检查范围内正式日历缺日或无效')
        all_rows = [(r[0].isoformat(), r[1]) for r in conn.execute(text('SELECT trade_date,is_trade '
            "FROM trade_calendar WHERE trade_date BETWEEN '1990-12-19' AND :last ORDER BY trade_date"),
            dict(last=cutoff.date()))]
        trades = calendar_dates(all_rows, cutoff.date().isoformat())
        raw = conn.execute(text("SELECT JSON_EXTRACT(payload,'$.versions') FROM collection_state "
            'WHERE namespace=:ns AND project_id=:project AND source=:source'),
            dict(ns=query.namespace, project=project(kind), source=SOURCE)).scalar_one_or_none()
        versions = json.loads(raw) if isinstance(raw, str) else raw or {}
        return [r[0].isoformat() for r in rows if r[1]], start, end, trades, versions
    days, start, end, trades, versions = await query.read(dates)
    rank = len(trades) - 1
    expected_checks = {day: (trades[-1] if i >= len(trades) - 5 else trades[max(i, rank - ((rank - i) % 20))])
                       for i, day in enumerate(trades)}
    missing, invalid, overdue, count, latest = [], [], [], 0, None

    def checked_at(value):
        if not value:
            return ''
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value.replace(tzinfo=CHINA)
        if stamp.tzinfo is None or stamp.astimezone(CHINA) > now:
            return ''
        return stamp.astimezone(CHINA).date().isoformat()
    # Three complete dates per bounded SQL range. This never projects the entire
    # historical body into a planning query or treats counts as set equality.
    for offset in range(0, len(days), 3):
        chunk = days[offset:offset + 3]
        def snapshot(conn):
            params = dict(first=chunk[0], last=chunk[-1], pool=kind, ns=query.namespace,
                          project=project(kind), source=SOURCE)
            if kind != 'reason':
                heads = [dict(r) for r in conn.execute(text('SELECT * FROM yuanhang_limit_pool '
                    'WHERE pool_type=:pool AND trade_date BETWEEN :first AND :last'), params).mappings()]
                members = [dict(r) for r in conn.execute(text('SELECT * FROM yuanhang_limit_member '
                    'WHERE pool_type=:pool AND trade_date BETWEEN :first AND :last '
                    'ORDER BY trade_date,unified_code LIMIT 30001'), params).mappings()]
                if len(members) > 30000:
                    raise ValueError('准备检查成员范围超限')
                return heads, members, None
            keys = list(conn.execute(text('SELECT DISTINCT trade_date,unified_code FROM yuanhang_limit_member '
                'WHERE trade_date BETWEEN :first AND :last ORDER BY trade_date,unified_code LIMIT 30001'), params))
            records = [dict(r) for r in conn.execute(text('''SELECT r.*,
                JSON_UNQUOTE(JSON_EXTRACT(s.payload,CONCAT('$.units."',r.unified_code,
                    '".versions."',DATE_FORMAT(r.trade_date,'%Y-%m-%d'),'"'))) AS verified
                FROM yuanhang_limit_reason r LEFT JOIN collection_state s
                ON s.namespace=:ns AND s.project_id=:project AND s.source=:source
                WHERE r.trade_date BETWEEN :first AND :last
                ORDER BY r.trade_date,r.unified_code LIMIT 30001'''), params).mappings()]
            if max(len(keys), len(records)) > 30000:
                raise ValueError('准备检查原因范围超限')
            heads = list(conn.execute(text('SELECT trade_date,pool_type,contract_version FROM yuanhang_limit_pool '
                'WHERE trade_date BETWEEN :first AND :last'), params))
            return keys, records, heads
        left, right, input_heads = await query.read(snapshot)
        if kind != 'reason':
            heads = {r['trade_date'].isoformat(): r for r in left}
            proofs = await query.cache_proofs(kind, [day + ':' + kind for day in heads])
            grouped = {day: [] for day in chunk}
            for row in right:
                grouped[row['trade_date'].isoformat()].append(decode_member(row))
            for day in chunk:
                head = heads.get(day)
                if head is None:
                    missing.append(day)
                    continue
                unit = dict(trade_date=day, pool_type=kind, filter=head['filter_text'],
                            source_total=head['source_total'], rows=grouped[day])
                try:
                    proof = pool_proof(pool_payload(unit))
                    if any(head[k] != v for k, v in proof.items()):
                        raise ValueError('集合或内容证明不一致')
                except ValueError:
                    invalid.append(day)
                count += len(grouped[day])
                checked = max(checked_at(versions.get(day)), checked_at(head['observed_at']))
                cache = proofs.get(day + ':' + kind)
                if cache and cache['hash'] == head['content_sha256']:
                    checked = max(checked, checked_at(cache['version'][0]))
                if checked < expected_checks[day]:
                    overdue.append(day)
                if latest is None or day > latest[0]:
                    latest = day, head['observed_at']
        else:
            known = {(r[0].isoformat(), r[1]) for r in input_heads if r[2] == 1}
            missing.extend(day + ':缺少原因适用证券集合' for day in chunk
                           if any((day, pool) not in known for pool in POOLS))
            # Input membership must have the same content-bound proof as a pool
            # audit. Five header rows alone cannot prove the reason universe.
            for day in chunk:
                for pool in POOLS:
                    if (day, pool) not in known:
                        continue
                    try:
                        audit = await query.audit_pool(day, pool)
                        if not audit['complete']:
                            invalid.append(day + ':' + pool + ':原因输入集合无效')
                    except ValueError:
                        invalid.append(day + ':' + pool + ':原因输入内容无效')
            expected = {(r[0].isoformat(), r[1]) for r in left if not scope.codes or r[1][:6] in scope.codes}
            actual = {(r['trade_date'].isoformat(), r['unified_code']): r for r in right}
            identities = [day + ':' + code for day, code in expected & actual.keys()]
            proofs = {}
            for first in range(0, len(identities), 256):
                proofs.update(await query.cache_proofs('reason', identities[first:first + 256]))
            missing.extend(str(k) for k in expected - actual.keys())
            for key in expected & actual.keys():
                row = actual[key]
                unit = {k: row[k] for k in ('unified_code', 'name', 'reason_text', 'reason_kind', 'availability')}
                unit['trade_date'] = key[0]
                try:
                    if digest(reason_payload(unit)) != row['content_sha256']:
                        raise ValueError('原因内容证明不符')
                except ValueError:
                    invalid.append(str(key))
                count += 1
                checked = max(checked_at(row['verified']), checked_at(row['observed_at']))
                cache = proofs.get(key[0] + ':' + key[1])
                if cache and cache['hash'] == row['content_sha256']:
                    checked = max(checked, checked_at(cache['version'][0]))
                if checked < expected_checks[key[0]]:
                    overdue.append(str(key))
                if latest is None or key[0] > latest[0]:
                    latest = key[0], row['observed_at']
    valid = bool(days) and not missing and not invalid
    label = f'{start}～{end}，{len(days)}个交易日，{count}条；缺口{len(missing)}，无效{len(invalid)}'
    status = 'pass' if valid else 'fail'
    freshness = 'pass' if valid and not overdue else 'fail'
    temporal = 'fail' if scope.purpose == 'historical_signal' and kind == 'reason' else 'pass'
    return [CheckEvidence(k, status, label) for k in ('fields', 'keys', 'coverage', 'quality')] + [
        CheckEvidence('freshness', freshness, f'统一SQL核验状态及内容匹配的有效缓存证据；到期未核验{len(overdue)}个单元'),
        CheckEvidence('temporal', temporal, '日终快照仅用于下一可交易日；原因没有可靠公布时间，不能回放历史原因选股。')]
