"""One complete current industry set per round; partial downloads are never published."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_industry_source import (
    BASE,
    members_url,
    parse_catalog,
    parse_members,
)
from empire.plugins.collectors.ths_session import ThsSession
from empire.plugins.datasets.industries import JOB, PROJECT, validate


class ThsIndustryCollector:
    manifest = PluginManifest('collector.ths_industries', '同花顺当前行业',
        requires=('http.fetch', 'ingest.publish', 'industries.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.ths_industries',), description='当前行业目录及完整成分集合；不保存变化历史')

    def __init__(self):
        self.source, self.project_id, self.job_key = 'ths', PROJECT, JOB
        self.session = None
        self.request_retries = 2
        self.stats = {'status': 'stopped', 'collected': 0}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_industries': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, url, parser):
        await wait_for_capacity(self.ingest, self.stats)
        if self.session is None:
            self.session = ThsSession()
        response = await self.http.request('GET', url, headers=self.session.headers(BASE),
            allowed_domains=('10jqka.com.cn',), project_id=self.project_id,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries)
        try:
            return parser(response.content.decode('gb18030'))
        except (ValueError, TypeError, KeyError) as exc:
            body = response.content
            exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id,
                exc, stage='source_validation', unavailable_message='行业错误样本暂未写入 Redis',
                fields={'request_url': url, 'status_code': response.status_code, 'raw_body': body[:65536],
                        'observed_bytes': len(body), 'body_sha256': hashlib.sha256(body).hexdigest()})
            raise
        finally:
            response.close()

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'source_validation'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete':
                return cursor
            # Fresh never abandons a successfully queued complete set awaiting SQL.
            if cursor.get('phase') != 'awaiting_archive':
                observed, batch = datetime.now(UTC), uuid4().hex
                self.stats.update(status='collecting', collected=0, pages=0, error='')
                industries = await self.fetch(BASE, parse_catalog)
                self.stats['total_units'] = len(industries)
                count, requests = 0, 1
                for index, industry in enumerate(industries):
                    self.stats.update(current_security=industry['name'], completed_units=index)
                    members = await self.fetch(members_url(industry['code']),
                        partial(parse_members, industry=industry['code']))
                    count += len(members)
                    if count > 15000:
                        raise ValueError('行业全量成员超过声明边界')
                    requests += 1
                    self.stats.update(collected=count, pages=requests, completed_units=index + 1)
                    industry['members'] = members
                validate(industries)
                stage = 'queue_publish'
                envelope = make_envelope(source=self.source, dataset='industry.snapshot', business_key='current',
                    job_key=self.job_key, batch_id=batch, run_id=batch, payload={'page': 1, 'industries': industries})
                envelope = envelope.model_copy(update={'observed_at': observed, 'source_url': BASE,
                                                       'available_at': None})
                cursor = dict(phase='awaiting_archive', batch_id=batch, pages=1, collected=count,
                              industries=len(industries), requests=requests)
                state = await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=self.job_key,
                    expected_revision=state['revision'], cursor=cursor)
                cursor = state['cursor']
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'])
            await wait_for_archive(partial(self.confirmation.page_status, self.source, self.job_key,
                self.project_id, cursor['batch_id'], 1), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=self.job_key,
                expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
                                      unavailable_message='行业错误记录暂不可用；不发布半份集合')
            raise

    async def stop(self):
        self.session = None
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
