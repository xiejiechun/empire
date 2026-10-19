"""Reject performance conclusions with changed workload, evidence, or unsafe targets."""
import copy
import json
import math
import socket
from datetime import date
from pathlib import Path

import pytest

from scripts import architecture_benchmark as bench
from scripts.architecture_benchmark_data import digest, fixtures, validate_settings


@pytest.fixture
def protocol():
    return json.loads(bench.PROTOCOL.read_text('utf-8'))


def report(protocol, value=10):
    return dict(schema=1, passed=True, cleanup=True, measured_at_utc='2026-10-19T00:00:00+00:00',
                protocol_sha256='protocol', harness_sha256='harness', source_sha256='source',
                requirements_sha256='requirements', machine={'cpu': 'test'}, dependencies={'test': '1'},
                fixture_sha256='fixture', ddl_sha256='ddl', mysql={'version': 'test'},
                limits=protocol['limits'], correctness={name: 'fixed' for name in protocol['metrics']},
                metrics={name: bench.summarize([value] * (
                    protocol['cold_process'] if name == 'cold_declarations' else protocol['warm'])['repetitions'])
                    for name in protocol['metrics']})


def test_threshold_uses_larger_relative_or_absolute_limit_for_both_statistics(protocol):
    baseline = report(protocol)
    current = copy.deepcopy(baseline)
    for name in protocol['metrics']:
        category = ('cold' if name == 'cold_declarations' else 'assembly' if name == 'assembly'
                    else 'ui' if name.endswith('_ui') else 'query')
        limit = max(12.5, 10 + protocol['acceptance']['absolute_noise_ms'][category])
        count = len(current['metrics'][name]['samples_ms'])
        current['metrics'][name] = bench.summarize([limit] * count)
    assert bench.compare(baseline, current, protocol)['passed']
    current['metrics']['news_first'] = bench.summarize([12.501] * protocol['warm']['repetitions'])
    outcome = bench.compare(baseline, current, protocol)
    assert not outcome['passed']
    assert not outcome['incomparable']
    assert not outcome['checks']['news_first.p95_ms']['passed']


@pytest.mark.parametrize('field', ['protocol_sha256', 'harness_sha256', 'machine', 'dependencies',
    'requirements_sha256', 'fixture_sha256', 'ddl_sha256', 'mysql', 'correctness'])
def test_changed_environment_or_output_cannot_be_a_performance_pass(protocol, field):
    baseline = report(protocol)
    current = copy.deepcopy(baseline)
    current[field] = 'changed'
    result = bench.compare(baseline, current, protocol)
    assert not result['passed'] and field in result['incomparable']


@pytest.mark.parametrize('damage', ['nan', 'infinity', 'boolean', 'negative', 'missing_sample',
                                   'tampered_stat', 'missing_metric', 'missing_correctness',
                                   'unclean', 'failed', 'missing_environment', 'malformed_metrics'])
def test_invalid_report_is_rejected_before_thresholds(protocol, damage):
    baseline = report(protocol)
    current = copy.deepcopy(baseline)
    metric = current['metrics']['news_first']
    if damage in ('nan', 'infinity', 'boolean', 'negative'):
        metric['samples_ms'][0] = {'nan': math.nan, 'infinity': math.inf,
                                  'boolean': True, 'negative': -1}[damage]
    elif damage == 'missing_sample':
        metric['samples_ms'].pop()
    elif damage == 'tampered_stat':
        metric['p95_ms'] = 0
    elif damage == 'missing_metric':
        current['metrics'].pop('assembly')
    elif damage == 'missing_correctness':
        current['correctness'].pop('assembly')
    elif damage == 'unclean':
        current['cleanup'] = False
    elif damage == 'failed':
        current['passed'] = False
    elif damage == 'missing_environment':
        current.pop('machine')
    else:
        current['metrics'] = []
    result = bench.compare(baseline, current, protocol)
    assert not result['passed'] and result['incomparable'] and not result['checks']


def test_percentile_and_result_repeatability_are_not_best_sample_selection():
    summary = bench.summarize([1, 2, 3, 4, 5])
    assert summary['median_ms'] == 3 and summary['p95_ms'] == 4.8
    items = iter([{'id': 1}, {'id': 2}])
    with pytest.raises(RuntimeError, match='output changed'):
        bench.sample(lambda: next(items), {'warmup': 1, 'repetitions': 1})


def test_fixture_is_deterministic_valid_and_uses_tied_news_sort_keys(protocol):
    from empire.features.holders.contract import digest as holder_digest
    from empire.features.holders.contract import report_key, validate

    protocol['fixture'].update(news_rows=60, holder_securities=2, holder_periods=2)
    rows = fixtures(protocol)
    assert digest(rows) == digest(fixtures(protocol))
    assert len(rows['news']) == 60 and len(rows['reports']) == 12 and len(rows['members']) == 144
    assert rows['news'][1]['published_at'] == rows['news'][2]['published_at']
    assert sum(row['is_important'] and '产业' in row['title'] for row in rows['news']) == 2
    for head, (key, row) in zip(rows['heads'], rows['reports'], strict=True):
        validate(row['kind'], row['unified_code'], [row], today=date(2026, 1, 1))
        assert key == report_key(row) and head['content_hash'] == holder_digest(row)


@pytest.mark.parametrize('host,port', [('127.0.0.1', 3307), ('127.0.0.1', 3306),
    ('127.0.0.1', '13348'), ('example.invalid', 13348), ('localhost', 13348)])
def test_production_remote_and_ambiguous_settings_are_rejected_before_connect(protocol, host, port):
    with pytest.raises(ValueError, match='isolated loopback'):
        validate_settings(bench.ROOT, dict(host=host, port=port), protocol)


def test_datadir_must_be_within_workspace_build(protocol):
    protocol['mysql']['datadir_relative'] = '../production'
    with pytest.raises(ValueError, match='workspace build'):
        validate_settings(bench.ROOT, dict(host='127.0.0.1', port=13348), protocol)


@pytest.mark.parametrize('method', ['connect', 'connect_ex'])
def test_network_guard_rejects_every_unregistered_destination_and_restores(method):
    original = getattr(socket.socket, method)
    with socket.socket() as sock, bench.restricted_network(13348):
        with pytest.raises(RuntimeError, match='outside its isolated MySQL'):
            getattr(sock, method)(('127.0.0.1', 3307))
        with pytest.raises(RuntimeError, match='outside its isolated MySQL'):
            getattr(sock, method)(('example.invalid', 443))
    assert getattr(socket.socket, method) is original


def test_freeze_validates_current_inputs_and_never_overwrites(tmp_path, monkeypatch, protocol):
    current = report(protocol)
    current.update(protocol_sha256=bench.file_hash(bench.PROTOCOL),
                   harness_sha256=digest({name: bench.file_hash(bench.ROOT / name) for name in bench.HARNESS}))
    monkeypatch.setattr(bench, 'source_identity', lambda root: 'source')
    path, target = tmp_path / 'report.json', tmp_path / 'baseline.json'
    path.write_text(json.dumps(current), encoding='utf-8')
    args = ['freeze', '--report', str(path), '--output', str(target)]
    assert bench.main(args) == 0
    with pytest.raises(FileExistsError):
        bench.main(args)
    saved = target.read_bytes()
    current['protocol_sha256'] = 'stale'
    path.write_text(json.dumps(current), encoding='utf-8')
    with pytest.raises(ValueError, match='protocol identity'):
        bench.main(args)
    assert target.read_bytes() == saved


def test_changed_protocol_cannot_be_used_to_relax_frozen_thresholds(protocol):
    baseline = report(protocol)
    result = bench.compare(baseline, baseline, protocol, 'different protocol')
    assert not result['passed'] and 'baseline.protocol identity' in result['incomparable']


def test_measurement_outputs_cannot_escape_build():
    with pytest.raises(SystemExit):
        bench.main(['measure', '--test-settings', str(Path('ignored.json')),
                    '--output', str(bench.ROOT / 'report.json')])
