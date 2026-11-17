"""Small task-owned publication/auth helpers; shared infrastructure owns I/O."""
import asyncio
from datetime import datetime
from functools import partial

import httpx

from empire.contracts.data import make_envelope
from empire.contracts.request_cost import add_cost
from empire.contracts.request_retry import retry_delay
from empire.features.yuanhang.node_selection import select_node
from empire.features.yuanhang_etf.contract import PROJECTS
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.infra.sensitive_request import SensitiveRequestError
from empire.sources.yuanhang_auth import AuthenticationError, IdleConnectionError


class Publisher:
    def __init__(self, dataset):
        self.dataset, self.project_id = dataset, PROJECTS[dataset]
        self.source, self.job_key = 'ths_yuanhang', self.project_id + '-v1'
        self.stats = dict(status='stopped', collected=0)
        self.request_retries = 2
        self.selected_codes = None

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.records, self.confirmation = context.get('collection.records'), context.get('archive.confirmation')
        self.query = context.get(self.query_capability)
        self.identity = context.optional('yuanhang.identity')
        self.stats['status'] = 'idle'
        return {self.capability: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def publish(self, state, cursor, identity, payload, *, observed=None, source_url=''):
        page = cursor['pages'] + 1
        cursor = {**cursor, 'pages': page, 'collected': cursor['collected'] + len(payload.get('rows', payload.get('members', payload.get('catalog', []))))}
        envelope = make_envelope(source=self.source, dataset=self.dataset, business_key=identity,
            job_key=self.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'], payload=dict(page=page, **payload))
        envelope = envelope.model_copy(update=dict(observed_at=observed or datetime.fromisoformat(cursor['observed_at']),
            source_url=source_url, available_at=None))
        state = await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=self.job_key,
            expected_revision=state['revision'], cursor=cursor)
        self.stats.update(collected=cursor['collected'], pages=page)
        return state, cursor

    async def finish(self, state, cursor):
        cursor = {**cursor, 'phase': 'awaiting_archive'}
        state = await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
        self.stats['status'] = 'awaiting_archive'
        if cursor['pages']:
            await wait_for_archive(partial(self.confirmation.page_status, self.source, self.job_key,
                self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
        cursor = {**cursor, 'phase': 'complete'}
        await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
        self.stats.update(status='complete', error='')
        return cursor

    async def authenticated(self, operation, *, reservation=None):
        from empire.plugins.infra.routing import USE_PROXY
        if not USE_PROXY.get():
            raise ValueError('远航原生ETF需要启用代理并绑定已有节点身份')
        failures, preferred, previous = {}, None, None
        for attempt in range(self.request_retries + 1):
            node = await select_node(self.identity, preferred, failures, last_error=previous)
            session = await self.identity.login(node, project_id=self.project_id)
            try:
                for renewal in range(2):
                    try:
                        await wait_for_capacity(self.ingest, self.stats)
                        result = await operation(session, reservation=reservation)
                        self.identity.sessions.confirm(node, session)
                        return result
                    except AuthenticationError as exc:
                        if renewal or exc.stage != 'native-login' or exc.code is None:
                            if renewal:
                                self.identity.sessions.reject(node, session)
                            raise
                        session = await self.identity.login(node, project_id=self.project_id, rejected=session)
            except IdleConnectionError:
                if attempt >= self.request_retries:
                    raise
                preferred = node
                add_cost('retries')
                await asyncio.sleep(retry_delay(attempt + 1))
            except (httpx.TransportError, SensitiveRequestError, TimeoutError) as exc:
                if attempt >= self.request_retries or isinstance(exc, SensitiveRequestError) and not exc.retryable_transport:
                    raise
                failures[node] = failures.get(node, 0) + 1
                preferred, previous = node, exc
                add_cost('retries')
                await asyncio.sleep(retry_delay(attempt + 1))

    async def report_failure(self, exc, stage):
        self.stats.update(status='error', error=self.records.sanitize_text(exc))
        await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
            unavailable_message='ETF错误记录暂不可用；保留已入队断点')

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
