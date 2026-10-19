"""Capacity harness counterexamples; fakes never connect to SQL or sources."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import capacity_session as module

PRODUCTION = '11111111-1111-1111-1111-111111111111'
PRIVATE = '22222222-2222-2222-2222-222222222222'
KINDS = ('trend', 'auction', 'volume', 'trades', 'entrust', 'large_order', 'quote')


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one(self):
        return self.value


@pytest.fixture
def fake_service(monkeypatch):
    state = SimpleNamespace(uuid=PRIVATE, events=[], fail=set(), lock_owner=42, creates=0, drops=0)

    def action(label):
        state.events.append(label)
        if label in state.fail:
            raise RuntimeError(label)

    class SourceConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            action('source_connection_close')

        def exec_driver_sql(self, statement):
            assert statement == 'SELECT @@server_uuid'
            return Result(PRODUCTION)

    class AdminConnection:
        def exec_driver_sql(self, statement):
            if statement.startswith('SELECT @@server_uuid AS'):
                return Result(dict(server_uuid=state.uuid, server_port=14499, version='8.4-test',
                                   innodb_flush_log_at_trx_commit=1, sync_binlog=7, log_bin=0))
            if statement.startswith('CREATE DATABASE'):
                action('create')
                state.creates += 1
                return Result(None)
            if statement.startswith('DROP DATABASE'):
                action('drop')
                state.drops += 1
                return Result(None)
            raise AssertionError(statement)

        def execute(self, statement, params):
            statement = str(statement)
            assert params['name'].startswith('empire_capacity_')
            if statement.startswith('SELECT GET_LOCK'):
                action('lock')
                return Result(1)
            if statement.startswith('SELECT @@server_uuid,IS_USED_LOCK'):
                return Result((state.uuid, state.lock_owner, 42))
            if statement.startswith('SELECT RELEASE_LOCK'):
                action('release')
                return Result(1)
            if statement.startswith('SELECT COUNT(*) FROM information_schema.schemata'):
                return Result(0)
            raise AssertionError(statement)

        def rollback(self):
            action('rollback')

        def close(self):
            action('admin_connection_close')

    class Engine:
        def __init__(self, kind):
            self.kind = kind

        def connect(self):
            return SourceConnection() if self.kind == 'source' else AdminConnection()

        def dispose(self):
            action(self.kind + '_dispose')

    def factory(settings, **_):
        kind = 'source' if settings.get('database') == 'production' else 'admin' if settings.get('database') is None else 'business'
        action(kind + '_engine')
        return Engine(kind)

    monkeypatch.setattr(module, 'make_engine', factory)
    monkeypatch.setattr(module.event, 'listen', lambda *_: action('listen'))
    return state


def session(tmp_path, **kwargs):
    return module.CapacitySession({'host': 'localhost', 'port': 3307, 'database': 'production'},
        {'host': 'different-alias', 'port': 13348, 'database': 'ignored-existing'},
        root=tmp_path, subject='holders', **kwargs)


def test_same_server_alias_is_rejected_before_create(tmp_path, fake_service):
    fake_service.uuid = PRODUCTION
    run = session(tmp_path)
    with pytest.raises(ValueError, match='server_uuid'):
        with run:
            pytest.fail('same server accepted')
    assert fake_service.creates == fake_service.drops == 0
    report = json.loads(run.output.read_text('utf-8'))
    assert report['passed'] is False
    assert 'admin_connection_close' in fake_service.events
    assert 'source_dispose' in fake_service.events


@pytest.mark.parametrize('subject', ['indices', 'index-prices'])
def test_e2_subjects_keep_identity_and_cleanup_guards(tmp_path, fake_service, subject):
    run = module.CapacitySession({'database': 'production'}, {'port': 13348},
                                 root=tmp_path, subject=subject)
    fake_service.uuid = PRODUCTION
    with pytest.raises(ValueError, match='server_uuid'):
        with run:
            pytest.fail('same server accepted')
    assert fake_service.creates == fake_service.drops == 0
    assert not json.loads(run.output.read_text('utf-8'))['passed']


@pytest.mark.parametrize('identity', [None, '', 'None', 'unknown'])
def test_unverifiable_server_rejected(tmp_path, fake_service, identity):
    fake_service.uuid = identity
    with pytest.raises(ValueError, match='server_uuid'):
        with session(tmp_path):
            pytest.fail('invalid identity accepted')
    assert fake_service.creates == 0


def test_report_uses_observed_parameters_after_cleanup(tmp_path, fake_service, monkeypatch):
    run = session(tmp_path)
    original = run.write_report

    def save_after_cleanup():
        assert fake_service.events[-1] == 'source_dispose'
        assert fake_service.drops == 1
        original()

    monkeypatch.setattr(run, 'write_report', save_after_cleanup)
    with run:
        run.measurements_complete = True
        assert not run.output.exists()
    report = json.loads(run.output.read_text('utf-8'))
    assert report['passed'] is True and all(report['cleanup'].values())
    assert report['measurement_service']['server_port'] == 14499
    assert report['measurement_service']['client_port'] == 13348
    assert report['measurement_service']['innodb_flush_log_at_trx_commit'] == 1
    assert report['measurement_service']['sync_binlog'] == 7
    assert report['checked_at'] >= report['started_at']
    assert 'password' not in run.output.read_text('utf-8')


def test_primary_failure_survives_independent_cleanup_failures(tmp_path, fake_service):
    fake_service.fail.update({'business_dispose', 'drop', 'admin_connection_close'})
    run = session(tmp_path)
    original = LookupError('measurement-specific-failure')
    with pytest.raises(LookupError) as caught:
        with run:
            raise original
    assert caught.value is original
    assert len(original.__notes__) == 3
    assert {'drop', 'release', 'admin_connection_close', 'admin_dispose', 'source_dispose'} <= set(fake_service.events)
    report = json.loads(run.output.read_text('utf-8'))
    assert not report['passed']
    assert report['errors'][0] == {'stage': 'measurement', 'type': 'LookupError'}
    assert report['cleanup']['sql'] is False
    assert report['cleanup']['source_engine'] is True


def test_cleanup_failure_cannot_produce_success(tmp_path, fake_service):
    fake_service.fail.add('drop')
    run = session(tmp_path)
    with pytest.raises(BaseExceptionGroup, match='no PASS'):
        with run:
            run.measurements_complete = True
    assert not json.loads(run.output.read_text('utf-8'))['passed']


def test_incomplete_measurement_cannot_produce_success(tmp_path, fake_service):
    run = session(tmp_path)
    with pytest.raises(BaseExceptionGroup, match='no PASS'):
        with run:
            pass
    assert not json.loads(run.output.read_text('utf-8'))['passed']
    assert fake_service.drops == 1


def test_interrupt_keeps_original_and_attempts_cleanup(tmp_path, fake_service):
    run = session(tmp_path)
    original = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as caught:
        with run:
            raise original
    assert caught.value is original
    assert fake_service.drops == 1
    assert not json.loads(run.output.read_text('utf-8'))['passed']


def test_drop_requires_same_server_and_lock_owner(tmp_path, fake_service):
    run = session(tmp_path)
    with pytest.raises(BaseExceptionGroup, match='no PASS'):
        with run:
            run.measurements_complete = True
            fake_service.lock_owner = 99
    assert fake_service.drops == 0
    assert 'source_dispose' in fake_service.events


def test_unknown_create_outcome_is_retained(tmp_path, fake_service):
    fake_service.fail.add('create')
    run = session(tmp_path)
    with pytest.raises(RuntimeError, match='create'):
        with run:
            pytest.fail('failed create entered')
    assert fake_service.drops == 0
    report = json.loads(run.output.read_text('utf-8'))
    assert report['cleanup']['sql'] is False and not report['passed']


def test_existing_report_rejected_before_sql(tmp_path, fake_service):
    output = tmp_path / 'historical.json'
    output.write_text('historical', 'utf-8')
    with pytest.raises(FileExistsError):
        session(tmp_path, output=output)
    assert fake_service.events == []
    assert output.read_text('utf-8') == 'historical'


def test_report_failure_preserves_measurement_exception(tmp_path, fake_service, monkeypatch):
    run = session(tmp_path)
    monkeypatch.setattr(run, 'write_report', Mock(side_effect=OSError('disk unavailable')))
    original = ValueError('measurement failure')
    with pytest.raises(ValueError) as caught:
        with run:
            raise original
    assert caught.value is original
    assert 'OSError' in original.__notes__[0]
    assert fake_service.drops == 1


def test_failed_report_flush_does_not_publish_pass(tmp_path, fake_service, monkeypatch):
    run = session(tmp_path)
    monkeypatch.setattr(module.os, 'fsync', Mock(side_effect=OSError('flush failed')))
    with pytest.raises(BaseExceptionGroup, match='no PASS'):
        with run:
            run.measurements_complete = True
    assert not run.output.exists()
    assert fake_service.drops == 1


def test_report_publication_never_replaces_racing_output(tmp_path, fake_service):
    run = session(tmp_path)
    with pytest.raises(BaseExceptionGroup, match='no PASS'):
        with run:
            run.measurements_complete = True
            run.output.parent.mkdir(parents=True, exist_ok=True)
            run.output.write_text('another owner', 'utf-8')
    assert run.output.read_text('utf-8') == 'another owner'
    assert fake_service.drops == 1


def test_reconnected_business_engine_must_keep_identity(tmp_path):
    run = session(tmp_path)
    run.identity['server_uuid'] = PRIVATE
    cursor = Mock()
    cursor.fetchone.return_value = (PRODUCTION, run.database)
    connection = Mock(cursor=Mock(return_value=cursor))
    with pytest.raises(ValueError, match='实例或数据库'):
        run.check_connection(connection, None, None)
    cursor.close.assert_called_once()


@pytest.mark.parametrize('observed', [(), KINDS[:-1], (*KINDS[:-1], KINDS[0])])
def test_preview_missing_or_duplicate_kind_is_unaccepted(observed):
    with pytest.raises(ValueError, match='未验收'):
        module.require_sample_kinds([({'kind': kind}, None) for kind in observed], KINDS)


def test_preview_seven_declared_kinds():
    module.require_sample_kinds([({'kind': kind}, None) for kind in KINDS], KINDS)


@pytest.mark.parametrize('during_cleanup', [False, True])
def test_input_change_during_measurement_or_cleanup_never_passes(tmp_path, fake_service, monkeypatch, during_cleanup):
    source = tmp_path / 'measurement.py'
    source.write_text('original', encoding='utf-8')
    run = session(tmp_path, input_paths=('measurement.py',))
    original_cleanup = run.cleanup

    def changed_cleanup():
        result = original_cleanup()
        source.write_text('changed', encoding='utf-8')
        return result

    if during_cleanup:
        monkeypatch.setattr(run, 'cleanup', changed_cleanup)
    with pytest.raises(BaseExceptionGroup, match='no PASS'):
        with run:
            run.report['bindings'] = dict(run.frozen_inputs)
            run.measurements_complete = True
            if not during_cleanup:
                source.write_text('changed', encoding='utf-8')
    report = json.loads(run.output.read_text('utf-8'))
    assert not report['passed'] and report['input_identity_verified'] is False
    assert report['cleanup']['sql'] is True and fake_service.drops == 1


def test_report_bindings_must_match_inputs_frozen_before_measurement(tmp_path, fake_service):
    (tmp_path / 'measurement.py').write_text('original', encoding='utf-8')
    run = session(tmp_path, input_paths=('measurement.py',))
    with pytest.raises(BaseExceptionGroup, match='no PASS'):
        with run:
            run.report['bindings'] = {'measurement.py': '0' * 64}
            run.measurements_complete = True
    assert not json.loads(run.output.read_text('utf-8'))['passed']
    assert fake_service.drops == 1
