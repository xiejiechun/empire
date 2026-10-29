import asyncio
import io
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from empire.core.redaction import Redactor
from empire.desktop_bridge.protocol import MAX_FRAME, encode_frame, read_frame
from empire.desktop_bridge.schemas import Policy, Request, SiteValues
from empire.desktop_bridge.server import Server
from empire.plugins.collection.management_query import event_page, task_page


@pytest.mark.asyncio
async def test_task_details_remain_available_when_archive_service_is_disabled():
    from unittest.mock import AsyncMock

    from empire.core.manager import Registry
    from empire.desktop_bridge.operations import execute

    registry = Registry()
    registry.values['collection.control'] = SimpleNamespace(
        definitions={'test-task': object()},
        workspace=AsyncMock(return_value={'jobs': [{'id': 'test-task'}], 'history': []}))
    result = await execute(SimpleNamespace(manager=SimpleNamespace(registry=registry)),
                           'task.read', {'ident': 'test-task'})
    assert result['id'] == 'test-task'
    assert result['archive_metrics'] is None


def test_frame_unicode_partial_and_oversized():
    value = {'id': 'one', 'result': '采集进度'}
    class Partial(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 2))
    assert read_frame(Partial(encode_frame(value))) == value
    assert read_frame(io.BytesIO()) is None
    for invalid in (b'print pollution\n', b'Content-Length: 10\r\n\r\n{}',
                    f'Content-Length: {MAX_FRAME+1}\r\n\r\n'.encode()):
        with pytest.raises(ValueError):
            read_frame(io.BytesIO(invalid))
    with pytest.raises(ValueError):
        encode_frame({'result': 'x' * MAX_FRAME})


def test_strict_schema_blocks_coercion_and_unknown_fields():
    good = dict(enabled=True, mode='interval', interval_seconds=2592000, daily_time='18:30',
                request_retries=100, use_proxy=True, proxy_fallback=True)
    assert Policy.model_validate(good).request_retries == 100
    for key, value in [('enabled', 1), ('request_retries', 101), ('interval_seconds', 0),
                       ('daily_time', '25:00'), ('password', 'never-return-this')]:
        with pytest.raises(ValidationError):
            Policy.model_validate({**good, key: value})
    with pytest.raises(ValidationError):
        Request.model_validate({'id': 'one', 'operation': 'health.read', 'shell': 'anything'})
    with pytest.raises(ValidationError):
        SiteValues.model_validate(dict(scaling_mode='auto', proxy_interval_ms=1,
                                       min_interval_ms=100, total_interval_ms=100,
                                       max_concurrency=0, max_rps=101))


def test_catalog_uses_actual_ids_and_pages_without_collector_health():
    specs = {str(i): SimpleNamespace(id=str(i), name=f'任务{i:03}', source_name='平台',
                                    rate_group='ths', category='财务', description='') for i in range(105)}
    jobs = {ident: dict(policy={'enabled': True}, last_status='complete', active=None) for ident in specs}
    jobs['0']['policy']['archived'] = True
    control = SimpleNamespace(definitions=specs, state={'jobs': jobs})
    page = task_page(control, limit=100)
    tail = task_page(control, offset=100)
    assert page['total'] == 104
    assert len(page['rows']) == 100 and len(tail['rows']) == 4
    assert {r['id'] for r in page['rows']} & {r['id'] for r in tail['rows']} == set()
    assert task_page(control, archived=True)['rows'][0]['id'] == '0'
    assert task_page(control, query='任务104')['rows'][0]['id'] == '104'


def test_task_list_progress_for_all_visible_active_tasks_only():
    calls = []
    specs = {str(i): SimpleNamespace(id=str(i), name=str(i), source_name='平台',
             rate_group='ths', category='行情', description='', capability=str(i)) for i in range(3)}
    jobs = {key: dict(policy={'enabled': True}, active={'run_id': key}) for key in specs}
    def optional(key):
        calls.append(key)
        return SimpleNamespace(health=lambda: dict(completed_units=29, total_units=100,
                                                   status='running', secret='excluded'))
    control = SimpleNamespace(definitions=specs, state={'jobs': jobs},
                              context=SimpleNamespace(optional=optional))
    rows = task_page(control, limit=2)['rows']
    assert calls == ['0', '1']
    assert all(row['progress']['completed_units'] == 29 for row in rows)
    assert all('secret' not in row['progress'] for row in rows)


@pytest.fixture
def bridge(monkeypatch):
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever)
    thread.start()
    calls = []
    async def execute(runtime, operation, params):
        calls.append((operation, params))
        if params.get('ident') == 'slow':
            await asyncio.sleep(.15)
        return {'message': 'ok'}
    monkeypatch.setattr('empire.desktop_bridge.server.execute', execute)
    runtime = SimpleNamespace(loop=loop, redactor=Redactor(()))
    output = io.BytesIO()
    server = Server(runtime, io.BytesIO(), output)
    yield server, calls, output
    for future, _ in list(server.pending.values()):
        future.result(timeout=2)
    loop.call_soon_threadsafe(loop.stop)
    thread.join()
    loop.close()


def request(server, ident='one', operation='collection.pause', op_id='cmd', task='task'):
    return dict(id=ident, operation=operation, session_id=server.session,
                operation_id=op_id, params={'ident': task})


def wait_complete(server):
    deadline = time.monotonic() + 2
    while server.pending and time.monotonic() < deadline:
        time.sleep(.01)
    assert not server.pending


def test_command_dedup_and_mismatched_payload(bridge):
    server, calls, output = bridge
    server.accept(request(server, task='slow'))
    server.accept(request(server, ident='two', task='slow'))
    wait_complete(server)
    server.accept(request(server, ident='three', task='slow'))
    assert len(calls) == 1
    with pytest.raises(ValueError, match='different parameters'):
        server.accept(request(server, ident='four', task='different'))
    output.seek(0)
    messages = []
    while (msg := read_frame(output)) is not None:
        messages.append(msg)
    assert {m['id'] for m in messages} == {'one', 'two', 'three'}
    assert next(m for m in messages if m['id'] == 'three')['result'] == {'message': 'ok'}


def test_cancel_does_not_cancel_mutation_or_allow_arbitrary_methods(bridge):
    server, calls, _ = bridge
    server.accept(request(server, task='slow'))
    server.accept(dict(id='cancel', operation='request.cancel', session_id=server.session,
                       params={'request_id': 'one'}))
    wait_complete(server)
    assert server.commands['cmd']['result'] == {'message': 'ok'}
    with pytest.raises(ValueError, match='Unknown operation'):
        server.accept(request(server, operation='mysql.execute'))
    with pytest.raises(ValueError, match='Session mismatch'):
        server.accept({**request(server), 'session_id': 'old'})
    assert len(calls) == 1


def test_receipts_never_evicted_and_replayed(bridge):
    server, calls, _ = bridge
    server.commands.update({str(i): {} for i in range(1024)})
    server.accept(request(server))
    assert not calls and not server.pending


def test_shutdown_waits_for_commands_then_runtime(bridge):
    server, calls, _ = bridge
    order = []
    server.runtime.command = lambda action: completed(order, action)
    server.runtime.thread = SimpleNamespace(join=lambda: order.append('joined'))
    server.source = io.BytesIO(encode_frame(request(server, task='slow')) + encode_frame(dict(
        id='close', operation='desktop.shutdown', session_id=server.session)))
    server.serve()
    assert len(calls) == 1
    assert order == ['shutdown', 'joined']
    assert server.commands['cmd']['done']


def completed(order, action):
    order.append(action)
    future = Future()
    future.set_result(None)
    return future


async def test_events_never_guess_membership_from_equal_timestamps():
    control = SimpleNamespace(definitions={'task': object()}, state={
        'jobs': {'task': {'active': None}},
        'history': [{'task_id': 'task', 'run_id': 'round', 'started_at': 100, 'finished_at': 200,
                     'status': 'complete'}]})
    class Records:
        async def list_archives(self, project):
            return [{'id': 'archive', 'finished_at': 200, 'snapshot_id': 'batch', 'status': 'success'}]

        async def list_error_summaries(self, project, offset, limit):
            return {'rows': [{'id': 'error', 'created_at': 200, 'stage': 'download', 'error': 'failure'}], 'total': 1}
    result = await event_page(control, Records(), ident='task', run_id='round')
    assert len(result['rows']) == 1
    assert result['rows'][0]['stage'] == 'collection'
    assert result['unlinked_count'] == 2
    unlinked = await event_page(control, Records(), ident='task', run_id='round', unlinked=True)
    assert {r['stage'] for r in unlinked['rows']} == {'archives', 'errors'}
    archives = await event_page(control, Records(), ident='task', stage='archives')
    assert [r['record_id'] for r in archives['rows']] == ['archive']
    assert archives['rows'][0]['run_id'] is None


async def test_adapter_dispatches_saved_policy_and_original_run_paths():
    from empire.desktop_bridge.operations import execute
    calls = []
    class Control:
        definitions = {'task': object()}

        async def configure(self, **params):
            calls.append(('configure', params))
            return 'MySQL已保存，Redis同步失败'

        async def run(self, **params):
            calls.append(('run', params))
            return 'actual-run-id'

        async def pause(self, **params):
            calls.append(('pause', params))

    control = Control()
    runtime = SimpleNamespace(manager=SimpleNamespace(registry=SimpleNamespace(get=lambda _: control)))
    result = await execute(runtime, 'collection.policy.save', {'ident': 'task', 'policy': {'enabled': True}})
    assert result['message'] == 'MySQL已保存，Redis同步失败'
    result = await execute(runtime, 'collection.run', {'ident': 'task', 'fresh': True})
    assert result['run_id'] == 'actual-run-id'
    assert calls == [('configure', {'ident': 'task', 'policy': {'enabled': True}}),
                     ('run', {'ident': 'task', 'fresh': True})]
    with pytest.raises(ValueError, match='Unknown collection task'):
        await execute(runtime, 'collection.pause', {'ident': 'fake'})
