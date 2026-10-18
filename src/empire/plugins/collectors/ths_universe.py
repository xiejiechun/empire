"""One HTTP response, ordered queue chunks and one complete current directory."""
import asyncio
import hashlib
import json
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
from empire.plugins.collectors.ths_session import ThsDirectorySession
from empire.plugins.collectors.ths_universe_source import URL, parse_directory


class ThsUniverseCollector:
    manifest = PluginManifest('collector.ths_universe', '同花顺 A 股股票列表',
        requires=('http.fetch', 'ingest.publish', 'stocks.schema', 'archive.confirmation', 'collection.records'),
        provides=('collector.ths_universe',), description='一次完整单页响应，核验沪深北代码及名称')

    def __init__(self):
        self.project_id, self.job_key = 'ths-stocks', 'ths-universe-v1'
        self.request_retries = 2
        self.stats = {'status': 'stopped', 'collected': 0}
        self.session = ThsDirectorySession()

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_universe': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self):
        await wait_for_capacity(self.ingest, self.stats)
        response = await self.http.request('GET', URL, allowed_domains=('10jqka.com.cn',),
            project_id=self.project_id, max_retries=self.request_retries,
            policy=self.http.response_policy('stocks'),
            headers=self.session.headers('https://q.10jqka.com.cn/'))
        try:
            return parse_directory(response.content.decode('gb18030'))
        except (ValueError, UnicodeError) as exc:
            await record_error_safely(self.records, self.stats, self.project_id, exc,
                stage='source_validation', unavailable_message='股票错误样本暂未写入Redis',
                fields={'request_url': URL, 'status_code': response.status_code,
                        'raw_body': response.content[:65536], 'observed_bytes': len(response.content),
                        'body_sha256': hashlib.sha256(response.content).hexdigest()})
            exc.diagnostic_recorded = True
            raise
        finally:
            response.close()

    async def execute(self, *, fresh=False, baseline_revision=0):
        reservation = None
        try:
            self.stats.update(status='running', error='')
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if fresh or not (cursor.get('phase') == 'complete' and state['revision'] > baseline_revision):
                rows = await self.fetch()
                digest = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                                   separators=(',', ':')).encode()).hexdigest()
                if fresh or not cursor or cursor.get('phase') == 'complete' or cursor.get('digest') != digest:
                    cursor = {'snapshot_id': uuid4().hex, 'started_at': datetime.now(UTC).isoformat(),
                        'expected_count': len(rows), 'page_size': 80, 'node': 'hs_a', 'digest': digest,
                        'phase': 'pages', 'next_page': 1, 'collected': 0}
                pages = (len(rows) + 79) // 80
                reservation = await self.ingest.reserve_batch(self.job_key, pages - cursor['next_page'] + 2)
                for page in range(cursor['next_page'], pages + 1):
                    chunk = rows[(page - 1) * 80:page * 80]
                    updated = {**cursor, 'next_page': page + 1, 'collected': min(page * 80, len(rows))}
                    state = await self.publish(state, updated, 'page', {'page': page, 'rows': chunk}, str(page), reservation)
                    cursor = updated
                cursor = {**cursor, 'phase': 'complete'}
                await self.publish(state, cursor, 'complete', {'pages': pages, 'collected': len(rows),
                    'count_after': len(rows), 'terminal_rows': []}, 'complete', reservation)
            result = {key: cursor[key] for key in ('snapshot_id', 'collected', 'expected_count')}
            self.stats.update(status='awaiting_archive', **result)
            await wait_for_archive(partial(self.confirmation.stock_status, 'ths', self.job_key,
                                          self.project_id, cursor['snapshot_id']), retry_seconds=2)
            self.stats.update(status='complete', error='')
            return result
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            if not getattr(exc, 'diagnostic_recorded', False):
                await record_error_safely(self.records, self.stats, self.project_id, exc,
                    stage='collection', unavailable_message='股票错误记录暂未写入Redis')
            raise
        finally:
            if reservation is not None:
                await asyncio.shield(reservation.release())

    async def publish(self, state, cursor, kind, extra, suffix, reservation):
        common = {key: cursor[key] for key in ('snapshot_id', 'started_at', 'expected_count', 'page_size', 'node')}
        event = make_envelope(source='ths', dataset='stock.universe.' + kind,
            business_key=cursor['snapshot_id'] + ':' + suffix, job_key=self.job_key,
            run_id=cursor['snapshot_id'], batch_id=cursor['snapshot_id'], payload={**common, **extra})
        event = event.model_copy(update={'source_url': URL})
        result = await publish_with_capacity(self.ingest, self.stats, [event], job_key=self.job_key,
            expected_revision=state['revision'], cursor=cursor, reservation=reservation,
            error_text=self.records.sanitize_text)
        self.stats.update(collected=cursor['collected'], expected_count=cursor['expected_count'])
        return result

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
