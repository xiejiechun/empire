"""Source semantics: independent totals, comparison joins and complete business keys."""
import copy
import json
from decimal import Decimal

import pytest

from empire.bootstrap import build_manager
from empire.contracts.tdx_performance import (
    FIELDS,
    KINDS,
    SOURCE_COLUMNS,
    convert,
    digest,
    identity,
    pack,
    project,
    quarterly_plan,
    unpack,
)
from empire.plugins.collectors.tdx_performance_source import parse, parse_directory, request_body
from empire.plugins.datasets.tdx_performance import PerformanceDataset

PERIOD = '2026-06-30'


def source(kind, period=PERIOD, security='', revised=False, empty=False):
    records = []
    for code, market in (('000001', 0), ('600000', 1)):
        if security and code != security[:6]:
            continue
        base = dict(code=code, sc=market, name='名称', cur='2026-10-12', days=9999)
        for src, _, shape in FIELDS[kind]:
            base[src] = period if shape.startswith('date') else '10.25' if shape == 'decimal' else 10 if shape == 'integer?' else '原值'
        if kind == 'holder_count':
            base.update(sc=str(market), sT002=period)
        elif kind == 'earnings_disclosure':
            base.update(T003='2026-08-01', T004=None, T005=None, T006=None, T007='2026-08-01')
        else:
            base['T002' if kind != 'earnings_report' else 'T007'] = '2026-08-01'
        if kind == 'earnings_quick':
            base.update(T001='company' + code, rq='2026-08-01', T006='071001', T007='033003', T005='033003')
        if revised:
            base['name'] = '修订名称'
        records.append(base)
        if kind == 'earnings_quick':
            records.append({**base, 'T006': '071002', 'pT008': '20.5'})
    if empty:
        records = []
    cols = list(SOURCE_COLUMNS[kind])
    meta_cols = (['stype', 'bgq', 'page'] if kind == 'earnings_forecast' else ['sbgq', 'page'] if kind == 'earnings_quick' else
                 ['page', 'nflag'] if kind == 'holder_count' else ['sbgq', 'page', 'nflag'])
    meta = (['0', period, 1] if kind == 'earnings_forecast' else [period, 1] if kind == 'earnings_quick' else
            [1, 0] if kind == 'holder_count' else [period, 1, 0])
    def result(columns, rows):
        return dict(ColName=columns, Content=rows, Count=len(rows))
    count = len({r['T001'] for r in records}) if kind == 'earnings_quick' else len(records)
    return dict(ErrorCode=0, ResultSets=[result(cols, [[r[k] for k in cols] for r in records]),
        result(meta_cols, [meta]), result(['count'], [[count]])])


def directory(kind):
    cols = ['bgq', 'rq'] if kind == 'earnings_forecast' else ['bgq']
    return dict(ErrorCode=0, ResultSets=[dict(ColName=cols, Count=1,
        Content=[[PERIOD, '2026-10-12']] if len(cols) == 2 else [[PERIOD]]),
        dict(ColName=['stype', 'param1'], Count=1, Content=[[KINDS[kind][2], '']])])


@pytest.mark.parametrize('kind', KINDS)
def test_exact_10000_and_original_units(kind):
    params = json.loads(request_body(kind, PERIOD))['Params']
    assert params[-3:] == ['1', '1', '10000']
    assert params == (['0', '', '1', '1', '10000'] if kind == 'holder_count' else
                     [PERIOD, '', '1', '1', '10000'] if kind == 'earnings_quick' else
                     ['0', PERIOD, '', '1', '1', '10000'])
    rows, count = parse(kind, source(kind), None if kind == 'holder_count' else PERIOD)
    assert count == 2
    assert len(rows) == (4 if kind == 'earnings_quick' else 2)
    assert {r['unified_code'] for r in rows} == {'000001.SZ', '600000.SH'}
    if kind == 'holder_count':
        assert rows[0]['holders'] == 10 and rows[0]['top_shares'] == '10.25'
    if kind == 'earnings_quick':
        assert {r['profit_basis'] for r in rows} == {'071001', '071002'}
    if kind == 'earnings_disclosure':
        assert all('days' not in r and 'cur' not in r for r in rows)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('fault', ['same_count_wrong_set', 'total', 'missing_set', 'columns', 'metadata', 'row_count', 'market', 'date', 'number', 'capacity'])
def test_protocol_faults_rejected(kind, fault):
    body = source(kind)
    content, cols = body['ResultSets'][0]['Content'], body['ResultSets'][0]['ColName']
    if fault == 'same_count_wrong_set':
        content[1] = copy.deepcopy(content[0])
    elif fault == 'total':
        body['ResultSets'][2]['Content'][0][0] += 1
    elif fault == 'capacity':
        body['ResultSets'][2]['Content'][0][0] = 10000
    elif fault == 'missing_set':
        body['ResultSets'].pop()
    elif fault == 'columns':
        cols[0] = 'unknown'
    elif fault == 'metadata':
        body['ResultSets'][1]['Content'][0][-1] = 3
    elif fault == 'row_count':
        body['ResultSets'][0]['Count'] += 1
    else:
        field = 'sc' if fault == 'market' else FIELDS[kind][0][0] if fault == 'date' else FIELDS[kind][-1][0]
        content[0][cols.index(field)] = 9 if fault == 'market' else 12 if fault == 'date' else {'bad': 1}
    with pytest.raises((ValueError, TypeError, KeyError)):
        parse(kind, body, None if kind == 'holder_count' else PERIOD)


@pytest.mark.parametrize('kind', KINDS)
def test_valid_empty_and_optional_unknown(kind):
    rows, count = parse(kind, source(kind, empty=True), None if kind == 'holder_count' else PERIOD)
    assert rows == [] and count == 0
    body = source(kind)
    raw = body['ResultSets'][0]
    for index, col in enumerate(raw['ColName']):
        shape = next((typ for src, _, typ in FIELDS[kind] if src == col), '')
        if shape.endswith('?') or shape == 'decimal':
            for row in raw['Content']:
                row[index] = None
    rows, _ = parse(kind, body, None if kind == 'holder_count' else PERIOD)
    assert rows


def test_directory_is_not_history_and_decimal_precision():
    for kind in set(KINDS) - {'holder_count'}:
        assert parse_directory(kind, directory(kind)) == [PERIOD]
    periods = quarterly_plan('2026-12-31')
    assert periods[0] == '1980-03-31' and periods[-1] == '2026-12-31' and len(periods) == 188
    for value in (float('nan'), Decimal('1e21'), '1.000000001', True):
        with pytest.raises(ValueError):
            convert(value, 'decimal')
    assert convert(0, 'decimal') == '0' and convert(None, 'decimal') is None


def test_independent_registration_and_payload_roundtrip():
    from empire.core.config import load_config
    cfg = load_config()
    manager = build_manager(cfg)
    for kind in KINDS:
        assert 'collector.tdx_' + kind in manager.entries
        assert manager.entries['collector.tdx_' + kind].plugin.project_id == project(kind)
        assert len(PerformanceDataset(kind).DATASETS) == 1
        rows, _ = parse(kind, source(kind), None if kind == 'holder_count' else PERIOD)
        assert digest(pack(kind, rows))
        assert len({identity(kind, r) for r in rows}) == len(rows)


@pytest.mark.parametrize('kind', KINDS)
def test_future_actual_date_rejected_but_future_scheduled_allowed(kind):
    from datetime import UTC, datetime

    from empire.contracts.data import make_envelope
    rows, _ = parse(kind, source(kind), None if kind == 'holder_count' else PERIOD)
    row = next(r for r in rows if r['unified_code'] == '000001.SZ')
    field = ('statistics_date' if kind == 'holder_count' else
             'actual_date' if kind == 'earnings_disclosure' else 'announcement_date')
    row[field] = '2026-10-13'
    unit = '000001.SZ' if kind == 'holder_count' else PERIOD + '|SZ'
    payload = dict(page=1, unit=unit, rows=pack(kind, [row]), manifest=None)
    env = make_envelope(source='tdx', dataset=kind+'.tdx_unit', business_key=unit,
                        job_key=project(kind)+'-v1', run_id='test', batch_id='test', payload=payload)
    env = env.model_copy(update={'observed_at': datetime(2026, 10, 12, 15, tzinfo=UTC)})
    if kind in ('earnings_forecast', 'earnings_quick', 'earnings_report'):
        # All three endpoints publish rows with tomorrow's declared notice date.
        assert PerformanceDataset(kind).normalize(env)['row_count'] == 1
    else:
        with pytest.raises(ValueError, match='超过采集时点'):
            PerformanceDataset(kind).normalize(env)
    row[field] = '2026-10-12'
    if kind == 'earnings_disclosure':
        row['changed_3'] = '2027-01-01'
    env = env.model_copy(update={'raw_payload': dict(payload, rows=pack(kind, [row]))})
    assert PerformanceDataset(kind).normalize(env)['row_count'] == 1


def test_quick_compression_preserves_rows_and_rejects_broken_or_unbounded_stream():
    rows, _ = parse('earnings_quick', source('earnings_quick'), PERIOD)
    packed = pack('earnings_quick', rows)
    assert unpack('earnings_quick', packed) == rows
    for changed in ({'bytes': 8*1024**2+1}, {'bytes': 1}, {'count': 0}, {'body': 'broken!'}, {'codec': 'future'}):
        with pytest.raises(ValueError):
            unpack('earnings_quick', {**packed, **changed})
