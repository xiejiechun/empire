"""Bounded list/detail tasks; only shared ingest advances queued checkpoints."""
import asyncio
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.themes.catalog_mapping import history_rows
from empire.features.themes.catalog_source import fetch_catalog
from empire.features.themes.detail_source import DOMAIN, URL, fetch_detail
from empire.features.themes.guest_material import load_material
from empire.features.themes.identity_source import resolve_identity
from empire.features.themes.storage_contract import (
    DETAIL_DATASET,
    DETAIL_JOB,
    DETAIL_PROJECT,
    LIST_DATASET,
    LIST_JOB,
    LIST_PROJECT,
    map_detail,
)
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class ThemeCollector:
    def __init__(self, kind, material_settings=None):
        self.kind, self.material_settings = kind, material_settings
        detail = kind == 'detail'
        self.project_id = DETAIL_PROJECT if detail else LIST_PROJECT
        self.job_key = DETAIL_JOB if detail else LIST_JOB
        self.dataset = DETAIL_DATASET if detail else LIST_DATASET
        self.capability = 'collector.theme_' + kind
        self.manifest = PluginManifest(self.capability, '开盘啦题材' + ('详情' if detail else '列表'),
            requires=('http.fetch', 'ingest.publish', 'archive.confirmation', 'collection.records', 'themes.query'),
            provides=(self.capability,))
        self.stats = dict(status='stopped', collected=0, requests=0, record_name='条题材', unit_name='个题材')
        self.request_retries = 1
        self.material = None
        self.identity_lock = asyncio.Lock()

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.records = context.get('themes.query'), context.get('collection.records')
        self.confirmation = context.get('archive.confirmation')
        self.stats['status'] = 'idle'
        return {self.capability: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    def envelope(self, cursor, key, payload, *, observed=None):
        event = make_envelope(source='kaipanla', dataset=self.dataset, business_key=key,
            job_key=self.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
            schema_version=1, payload={'page': cursor['page'] + 1, **payload})
        return event.model_copy(update={'source_url': URL, 'available_at': None,
                                        **({'observed_at': observed} if observed else {})})

    async def fetch(self, theme_id, *, reservation=None):
        await wait_for_capacity(self.ingest, self.stats)
        result = await fetch_detail(self.http, theme_id, project_id=self.project_id,
                                    max_retries=self.request_retries, reservation=reservation)
        self.stats['requests'] += 1
        for stock in result['stocks']:
            code = stock['source_stock_id']
            if code not in self.identities:
                async with self.identity_lock:
                    if code not in self.identities:
                        self.identities[code] = await resolve_identity(self.http, code, project_id=self.project_id,
                                                                       reservation=reservation)
                        self.stats['requests'] += 1
        return map_detail(result, self.identities.values())

    async def execute(self, *, fresh=False, baseline_revision=0):
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete':
                return cursor
            if cursor and cursor.get('contract') != 1:
                raise ValueError('题材旧断点须显式维护')
            self.stats.update(status='collecting', error='')
            if cursor.get('phase') != 'awaiting_archive':
                if self.kind == 'list':
                    state, cursor = await self.collect_list(state, cursor)
                else:
                    state, cursor = await self.collect_details(state, cursor, fresh=fresh)
            if cursor.get('phase') == 'awaiting_archive':
                self.stats['status'] = 'awaiting_archive'
                await wait_for_archive(partial(self.confirmation.page_status, 'kaipanla', self.job_key,
                    self.project_id, cursor['batch_id'], cursor['page']), retry_seconds=1)
                cursor = {**cursor, 'phase': 'complete'}
                await self.ingest.advance_checkpoint(job_key=self.job_key,
                    expected_revision=state['revision'], cursor=cursor)
            self.stats['status'] = 'complete'
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc,
                stage='theme_collection', unavailable_message='题材错误记录暂不可用')
            raise

    async def collect_list(self, state, previous):
        await wait_for_capacity(self.ingest, self.stats)
        if self.material is None:
            self.material = load_material(self.material_settings)
        rows = history_rows(await fetch_catalog(self.http, self.material))
        observed, batch = datetime.now(UTC), uuid4().hex
        self.stats['requests'] += 1
        local = observed.astimezone(CHINA)
        slot = local.strftime('%Y-%m-%dT%H') + ('-close' if local.hour == 15 and local.minute >= 10 else '')
        # History and archive are different uses. A valid sample remains visible
        # if enqueue fails; only shared publish may advance the SQL checkpoint.
        await self.query.history.append(rows, observed_at=observed, round_id=batch)
        cursor = dict(contract=1, phase='complete', batch_id=batch, page=0,
                      collected=len(rows), last_slot=previous.get('last_slot'))
        self.stats['collected'] = len(rows)
        if cursor['last_slot'] == slot:
            state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                expected_revision=state['revision'], cursor=cursor)
            return state, cursor
        event = self.envelope(cursor, local.date().isoformat(),
                              {'day': local.date().isoformat(), 'rows': rows}, observed=observed)
        cursor.update(phase='awaiting_archive', page=1, last_slot=slot)
        state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=self.job_key,
                                             expected_revision=state['revision'], cursor=cursor)
        return state, cursor

    async def collect_details(self, state, cursor, *, fresh):
        if cursor.get('phase') != 'fetch':
            current = await self.query.current()
            if current is None:
                raise ValueError('请先完成当日题材列表采样，再采集详情')
            plan = (await self.query.detail_plan(current['rows'], fresh=fresh))[:32]
            cursor = dict(contract=1, phase='fetch', plan=plan, page=0, collected=0, batch_id=uuid4().hex)
        plan = cursor['plan']
        if (not isinstance(plan, list) or len(plan) > 32 or len(set(plan)) != len(plan)
                or type(cursor['page']) is not int or not 0 <= cursor['page'] <= len(plan)):
            raise ValueError('题材详情断点计划损坏')
        self.identities = await self.query.identities()
        async with prefetch_units(self, plan[cursor['page']:], self.fetch,
                url=URL, domains=(DOMAIN,), item_name='题材详情') as reads:
            async for _, response in reads:
                detail = await response.resolve()
                event = self.envelope(cursor, detail['theme_id'], {'detail': detail})
                cursor = {**cursor, 'page': cursor['page'] + 1, 'collected': cursor['collected'] + 1}
                if cursor['page'] == len(plan):
                    cursor['phase'] = 'awaiting_archive'
                state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=self.job_key,
                    expected_revision=state['revision'], cursor=cursor)
                self.stats.update(collected=cursor['collected'], completed_units=cursor['page'], total_units=len(plan))
        if not plan:
            cursor['phase'] = 'complete'
            state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                expected_revision=state['revision'], cursor=cursor)
        return state, cursor

    async def stop(self):
        self.material = None
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
