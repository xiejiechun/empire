"""Lifecycle helpers for TDX capital-action complete-security units."""
import asyncio
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

import httpx

from empire.contracts.data import make_envelope
from empire.core.time import CHINA
from empire.features.capital_actions.contract import SCHEMA_VERSIONS, chain, digest, unit_key
from empire.features.capital_actions.fields import TdxSourceError
from empire.features.capital_actions.recovery import recent_plans, retain_failure
from empire.features.capital_actions.source import complete_response
from empire.features.capital_actions.source_protocol import PAGE_URL
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
)


async def collect_units(collector, *, fresh=False, baseline_revision=0):
    c = collector
    stage = 'plan'
    try:
        state = await c.ingest.checkpoint(c.job_key)
        cursor = state['cursor']
        if cursor and c.kind == 'dividends' and cursor.get('schema_version') != SCHEMA_VERSIONS[c.kind]:
            raise ValueError('分红业务键契约已更新，请先执行 migrate_dividend_identity.py 显式维护')
        if cursor and c.kind == 'additional_issues' and cursor.get('schema_version') != SCHEMA_VERSIONS[c.kind]:
            raise ValueError('增发详情状态契约已更新，请先执行 migrate_issue_availability.py 显式维护')
        progressed = state['revision'] > baseline_revision
        previous_refresh = cursor.get('detail_refresh_day')
        previous_source_hash = cursor.get('source_hash')
        refresh_all = False
        refresh_cutoff = None
        if progressed and cursor.get('phase') == 'complete':
            return result(cursor)
        if fresh and not progressed or cursor.get('phase') == 'complete':
            cursor = {}
        if cursor.get('phase') != 'awaiting_archive':
            if c.kind == 'dividends':
                from empire.features.capital_actions.dividend_history import collect_history
                units, observed, source_hash = await collect_history(c, force_history=bool(fresh and not progressed))
            else:
                async def download_list(_, *, reservation):
                    return await complete_response(c, c.kind, reservation=reservation, defer=True)
                async with prefetch_units(c, [None], download_list, url=PAGE_URL,
                        domains=("tdx.com.cn",), item_name='响应') as reads:
                    async for _, read in reads:
                        rows, observed = await read.resolve()
                units = {}
                for row in rows:
                    units.setdefault(unit_key(row), []).append(row)
                source_hash = digest(rows)
            keys = sorted(units)
            aliases = {}
            if c.kind == 'additional_issues':
                for group in units.values():
                    for row in group:
                        aliases.setdefault(row['data']['source_id'], set()).add(row['code'])
            if cursor and cursor['source_hash'] != source_hash:
                # The current source has passed complete-set validation. Start a
                # new batch, retaining old queued data and SQL version guards.
                # Commit its frontier only together with valid business data.
                refresh_all = cursor.get('detail_refresh_all', False)
                if refresh_all:
                    refresh_cutoff = cursor.get('detail_refresh_cutoff', cursor['started_at'])
                c.stats['scope_replans'] = c.stats.get('scope_replans', 0) + 1
                c.stats['scope_change'] = '来源集合或股票池变化，自动重建本轮范围'
                cursor = {}
                previous_refresh = None
            if not cursor:
                cursor = dict(phase='fetch', batch_id=uuid4().hex, index=0, pages=0, collected=0,
                              source_hash=source_hash, scope_hash=digest(keys), units=len(keys),
                              rolling=digest([]), started_at=datetime.now(UTC).isoformat(),
                              schema_version=SCHEMA_VERSIONS[c.kind])
                if previous_source_hash and previous_source_hash != source_hash:
                    cursor['scope_changed'] = True
                if c.kind == 'additional_issues':
                    cursor['detail_refresh_all'] = refresh_all or bool(fresh and not progressed)
                    cursor['detail_refresh_cutoff'] = refresh_cutoff or observed.isoformat(timespec='microseconds')
                    today = datetime.now(CHINA).date().isoformat()
                    cursor['detail_refresh_day'] = today
                    cursor['detail_refresh_recent'] = previous_refresh != today
            reusable, previous = {}, {}
            if c.kind == 'additional_issues':
                from empire.features.capital_actions.issue_source import (
                    previous_details,
                    reusable_details,
                )
                c.stats.update(details_reused=0, details_requested=0, details_unavailable=0)
                force = cursor.get('detail_refresh_all', False)
                explicit_fresh = bool(fresh and not progressed)
                candidates = await c.query.issue_detail_candidates()
                previous = previous_details(candidates)
                if cursor['index'] < len(keys) and not (force and explicit_fresh):
                    selected = (await c.query.verified_issue_candidates(candidates,
                        cursor.get('detail_refresh_cutoff', cursor['started_at']))) if force else candidates
                    reusable = reusable_details(selected, [row for group in units.values() for row in group])
                    if not force:
                        reusable = {ident: value for ident, value in reusable.items()
                                    if value.get('availability') != 'unavailable'}
                    if not force and cursor.get('detail_refresh_recent', False):
                        recent = recent_plans([row for group in units.values() for row in group],
                                              datetime.fromisoformat(cursor['started_at']).astimezone(CHINA).date())
                        reusable = {ident: value for ident, value in reusable.items() if ident not in recent}
            failures = []
            first_error = None
            consecutive_failures = 0
            queued_records = cursor['collected']
            c.stats.update(failed_units=0, queued_records=queued_records,
                           continuous_collected=cursor['collected'], processed_units=cursor['index'])
            if c.kind != 'dividends':
                c.stats['expected_count'] = sum(len(group) for group in units.values())
            async def download_unit(unit, *, reservation):
                return units[unit], observed
            if c.kind == 'additional_issues':
                from empire.features.capital_actions.issue_prefetch import issue_units
                downloads = issue_units(c, keys, units, aliases, reusable, previous, observed, first=cursor['index'])
            else:
                downloads = prefetch_units(c, keys, download_unit, url=PAGE_URL,
                                           domains=('tdx.com.cn',), first=cursor['index'], item_name='证券')
            async with downloads as reads:
                async for index, read in reads:
                    unit = keys[index]
                    c.stats.update(status='collecting', current_security=unit, collected=queued_records,
                                   continuous_collected=cursor['collected'],
                                   pages=cursor['pages'], total_units=len(keys), error='')
                    stage = 'source_validation'
                    try:
                        rows, unit_observed = await read.resolve()
                    except (ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
                        if not isinstance(exc, httpx.HTTPError) and not hasattr(exc, 'diagnostic_recorded'):
                            raise  # Local resource/configuration errors are not a missing source security.
                        await retain_failure(c, exc, unit)
                        failures.append(unit)
                        c.stats['processed_units'] = index + 1
                        first_error = first_error or exc
                        # Several missing source records are not evidence that the
                        # whole endpoint is unreachable. Keep the real gaps open.
                        record_unavailable = isinstance(exc, TdxSourceError) and exc.source_error_code == -1005
                        consecutive_failures = 0 if record_unavailable else consecutive_failures + 1
                        if consecutive_failures >= 5:
                            break
                        continue
                    consecutive_failures = 0
                    next_cursor = {**cursor, 'index': index + 1, 'pages': cursor['pages'] + 1,
                                   'collected': cursor['collected'] + len(rows),
                                   'rolling': chain(cursor['rolling'], unit, rows)}
                    stage = 'queue_publish'
                    if failures:
                        # Independent successful units are useful, but cannot advance
                        # the continuous frontier or contribute to its manifest.
                        side_cursor = {**cursor, 'batch_id': uuid4().hex, 'pages': 1}
                        state = await publish(c, state, side_cursor, unit, rows, None, unit_observed,
                                              checkpoint_cursor=cursor)
                    else:
                        state = await publish(c, state, next_cursor, unit, rows, None, unit_observed)
                    cursor = state['cursor']
                    queued_records += len(rows)
                    c.stats.update(collected=queued_records, queued_records=queued_records,
                                   continuous_collected=cursor['collected'], processed_units=index + 1)
            if failures:
                first_error.diagnostic_recorded = True
                raise first_error
            manifest = {'units': cursor['units'], 'count': cursor['collected'],
                        'scope_hash': cursor['scope_hash'], 'digest': cursor['rolling']}
            next_cursor = {**cursor, 'pages': cursor['pages'] + 1, 'phase': 'awaiting_archive'}
            state = await publish(c, state, next_cursor, 'manifest', [], manifest, datetime.now(UTC))
            cursor = state['cursor']
        stage = 'archive_confirmation'
        c.stats.update(status='awaiting_archive', pages=cursor['pages'], collected=cursor['collected'])
        await wait_for_archive(partial(c.confirmation.page_status, c.source, c.job_key,
                                      c.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
        cursor = {**cursor, 'phase': 'complete'}
        await c.ingest.advance_checkpoint(job_key=c.job_key, expected_revision=state['revision'], cursor=cursor)
        c.stats.update(status='complete', error='')
        return result(cursor)
    except asyncio.CancelledError:
        c.stats['status'] = 'paused'
        raise
    except Exception as exc:
        c.stats.update(status='error', error=c.records.sanitize_text(exc))
        await record_error_safely(c.records, c.stats, c.project_id, exc, stage=stage,
            unavailable_message='错误记录暂未写入 Redis；已入队断点保留',
            fields={'request_url': PAGE_URL})
        raise


async def publish(c, state, cursor, unit, rows, manifest, observed, checkpoint_cursor=None):
    payload = {'page': cursor['pages'], 'unit': unit, 'rows': rows, 'manifest': manifest}
    if c.kind == 'dividends' and unit != 'manifest':
        payload['history_discovered_at'] = c.history_discoveries[unit]
    envelope = make_envelope(source=c.source, dataset=c.kind + '.unit', business_key=unit,
        schema_version=SCHEMA_VERSIONS[c.kind],
        job_key=c.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
        payload=payload)
    envelope = envelope.model_copy(update={'observed_at': observed, 'source_url': PAGE_URL})
    return await publish_with_capacity(c.ingest, c.stats, [envelope], job_key=c.job_key,
                                      expected_revision=state['revision'],
                                      cursor=cursor if checkpoint_cursor is None else checkpoint_cursor)


def result(cursor):
    return {k: cursor[k] for k in ('batch_id', 'pages', 'collected', 'units')}
