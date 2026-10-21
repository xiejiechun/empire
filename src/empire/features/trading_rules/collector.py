"""Seven independent jobs; validate full scoped rule sets before atomic publication."""
import asyncio
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.features.trading_rules.contract import KINDS, SOURCE, VERSION, project
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
)


class RuleCollector:
    def __init__(self, kind):
        self.kind, self.source = kind, SOURCE
        self.project_id, self.job_key = project(kind), project(kind) + '-v1'
        capability = 'collector.rules_' + kind
        self.manifest = PluginManifest(capability, KINDS[kind] + '采集', requires=(
            'rules.source', 'ingest.publish', 'rules.' + kind + '.query', 'archive.confirmation', 'collection.records'),
            provides=(capability,), description='已审核官方文件及完整参数集合，生效日期保留')
        self.stats = dict(status='stopped', collected=0, record_name='条规则参数', unit_name='组官方规则', total_units=1, completed_units=0)
        self.request_retries = 2
        self.last_source = None

    async def start(self, context):
        self.sources, self.ingest = context.get('rules.source'), context.get('ingest.publish')
        self.http = self.sources.http
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {self.manifest.provides[0]: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'source_validation'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete' and cursor.get('contract') == VERSION:
                return cursor
            if cursor.get('phase') == 'awaiting_archive' and cursor.get('contract') != VERSION:
                raise ValueError('旧规则断点须显式维护，不能跳过待归档消息')
            if cursor.get('phase') != 'awaiting_archive':
                observed, batch = datetime.now(UTC), uuid4().hex
                self.stats.update(status='collecting', collected=0, completed_units=0, error='')
                p = await self.sources.collect(self)
                self.last_source = p
                event = make_envelope(source=SOURCE, dataset='rules.' + self.kind + '.complete',
                    business_key=self.kind, job_key=self.job_key, batch_id=batch, run_id=batch,
                    schema_version=VERSION, payload=p).model_copy(update={'observed_at': observed})
                cursor = dict(phase='awaiting_archive', batch_id=batch, pages=1, collected=len(p['rows']),
                    contract=VERSION, record_name='条规则参数', unit_name='组官方规则', total_units=1, completed_units=1)
                stage = 'queue_publish'
                state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=self.job_key,
                    expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'], completed_units=1)
            await wait_for_archive(partial(self.confirmation.page_status, SOURCE, self.job_key, self.project_id,
                cursor['batch_id'], 1), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
                unavailable_message='规则错误记录暂不可用；失败未跳过')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
