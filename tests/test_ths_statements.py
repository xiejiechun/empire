import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.collectors.ths_statements import ThsStatementCollector
from empire.plugins.datasets.financial_statements import (
    KINDS,
    REQUIRED,
    amount,
    parse,
    validate_rows,
)
from tests.prefetch_source import prefetch_http

STOCK = dict(market='SH', code='601139', name='深圳燃气')


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('day', ['2014-07-31', '2014-07-15', '1989-12-31'])
def test_nonquarter_report_date_preserved(kind, day):
    body = source(kind)
    matrix = json.loads(body['flashData'])
    matrix['report'][0] = [day, '1988-12-31']
    body['flashData'] = json.dumps(matrix)
    rows = parse(kind, body, STOCK)
    assert [r['report_date'] for r in rows] == [day, '1988-12-31']
    assert validate_rows(kind, 'SH:601139', rows) == rows


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('day', [None, 20140731, '20140731', '2014-7-31',
                                '2014-02-30', '0999-12-31', '2099-07-31'])
def test_invalid_dates_rejected_at_source_and_archive(kind, day):
    body = source(kind)
    rows = parse(kind, body, STOCK)
    rows[0]['report_date'] = day
    with pytest.raises(ValueError, match='报告期'):
        validate_rows(kind, 'SH:601139', rows)
    matrix = json.loads(body['flashData'])
    matrix['report'][0][0] = day
    body['flashData'] = json.dumps(matrix)
    with pytest.raises(ValueError, match='报告期'):
        parse(kind, body, STOCK)


def source(kind, value='1.00亿'):
    fields = list(REQUIRED[kind])
    values = [value] * len(fields)
    if kind == 'balance':
        values = ['3.00亿', '2.00亿', '1.00亿']
    return {'flashData': json.dumps({'title': ['科目\\时间'] + [[f, '元', 2, False, True] for f in fields],
        'report': [['2025-12-31', '2025-09-30']] + [[v, v] for v in values]})}


def large_source(kind):
    matrix = json.loads(source(kind)['flashData'])
    dates = [f'{2025 - i // 4}-{("12-31", "09-30", "06-30", "03-31")[i % 4]}' for i in range(120)]
    matrix['report'] = [dates] + [[v[0]] * len(dates) for v in matrix['report'][1:]]
    for i in range(100):
        matrix['title'].append([f'完整来源科目名称{i:03}' * 4, '元', 2, False, True])
        matrix['report'].append(['1.23亿'] * len(dates))
    return {'flashData': json.dumps(matrix)}


@pytest.mark.parametrize('kind', KINDS)
def test_large_statement_matrix_roundtrip_and_size(kind):
    from empire.plugins.datasets.financial_wire import pack_rows, unpack_rows
    rows = parse(kind, large_source(kind), STOCK)
    packed = pack_rows(rows)
    assert unpack_rows(packed) == rows
    assert len(json.dumps(rows, ensure_ascii=False).encode()) > 524288
    assert len(json.dumps(packed, ensure_ascii=False).encode()) < 524288 - 2000


@pytest.mark.parametrize('problem', ['duplicate_column', 'missing_value', 'bad_precision', 'extra_meta'])
def test_matrix_wire_never_silently_drops_fields(problem):
    from empire.plugins.datasets.financial_wire import pack_rows, unpack_rows
    matrix = pack_rows(parse('income', source('income'), STOCK))
    if problem == 'duplicate_column':
        matrix['columns'][1] = matrix['columns'][0]
    elif problem == 'missing_value':
        matrix['reports'][0][1].pop()
    elif problem == 'bad_precision':
        matrix['reports'][0][1][0] = ['100']
    else:
        matrix['common']['unknown'] = 1
    with pytest.raises(ValueError):
        unpack_rows(matrix)


@pytest.mark.parametrize('kind', KINDS)
def test_complete_matrix_and_precision(kind):
    rows = parse(kind, source(kind), STOCK)
    assert len(rows) == 2
    assert validate_rows(kind, 'SH:601139', rows) == rows
    assert rows[0]['announcement_date'] is None
    assert amount('1.23亿') == {'value': '123000000', 'resolution': '1000000'}
    assert amount(False) is None and amount('--') is None
    assert amount('0')['value'] == '0'


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('missing', [False, '--', ''])
def test_source_missing_amount_is_unknown_and_quality_fails(kind, missing):
    from empire.plugins.datasets.financial_quality import quality_issues
    body = source(kind)
    matrix = json.loads(body['flashData'])
    matrix['report'][1][0] = missing
    body['flashData'] = json.dumps(matrix)
    rows = parse(kind, body, STOCK)
    assert len(rows) == 2 and rows[0]['fields'][REQUIRED[kind][0]] is None
    assert any(i['criterion'] == 'fields' for i in quality_issues(kind, rows[0]))
    assert not quality_issues(kind, rows[1])


def test_real_balance_contradiction_is_preserved_and_explained():
    from empire.plugins.datasets.financial_quality import quality_issues
    body = source('balance')
    matrix = json.loads(body['flashData'])
    matrix['report'] = [['2024-03-31']] + [[v] for v in ['4.61亿', '1.73亿', '5.73亿']]
    body['flashData'] = json.dumps(matrix)
    rows = parse('balance', body, dict(market='BJ', code='920748', name='路桥信息'))
    assert rows[0]['fields'][REQUIRED['balance'][2]]['value'] == '573000000'
    issue, = quality_issues('balance', rows[0])
    assert issue['criterion'] == 'quality' and '285000000' in issue['message']


def test_statement_page_explains_missing_source_amount(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.financial_statements import StatementPage
    app = QApplication.instance() or QApplication([])
    page = StatementPage(SimpleNamespace(shutting_down=False), 'income')
    try:
        body = source('income')
        matrix = json.loads(body['flashData'])
        matrix['report'][1][0] = False
        body['flashData'] = json.dumps(matrix)
        page.records = parse('income', body, STOCK)
        page.render_matrix()
        index = next(i for i, entry in enumerate(page.matrix.entries) if entry[0] == '*营业总收入')
        page.matrix.values.setCurrentCell(index, 0)
        page.show_detail()
        assert '来源未提供核心金额' in page.detail.toPlainText()
        assert page.matrix.subjects.horizontalHeaderItem(0).text() == '科目 / 年度'
        assert page.matrix.values.item(index, 0).text() == '—'
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('problem', ['same_count_wrong_set', 'truncated', 'missing_field', 'empty', 'unit', 'future'])
def test_bad_matrix_rejected(kind, problem):
    body = source(kind)
    f = json.loads(body['flashData'])
    if problem == 'same_count_wrong_set':
        f['report'][0][1] = f['report'][0][0]
    elif problem == 'truncated':
        f['report'][-1].pop()
    elif problem == 'missing_field':
        f['title'].pop()
        f['report'].pop()
    elif problem == 'empty':
        f['report'] = [[] for _ in f['report']]
    elif problem == 'unit':
        f['title'][1][1] = '美元'
    else:
        f['report'][0][0] = '2099-12-31'
    body['flashData'] = json.dumps(f)
    with pytest.raises(ValueError):
        parse(kind, body, STOCK)


@pytest.mark.parametrize('kind', KINDS)
async def test_one_request_response_closed_shared_transport(kind):
    c = ThsStatementCollector(kind)
    response = httpx.Response(200, json=source(kind))
    c.http = prefetch_http(request=AsyncMock(return_value=response), response_policy=lambda x: x)
    c.ingest = SimpleNamespace(capacity=AsyncMock(return_value={'can_collect': True}))
    c.records = SimpleNamespace(sanitize_text=str)
    # Only transport capacity is stubbed; normal source fetch remains the implementation.
    from unittest.mock import patch
    with patch('empire.plugins.collectors.ths_statements.wait_for_capacity', AsyncMock()):
        rows, _, url = await c.fetch(STOCK)
    assert len(rows) == 2 and c.http.request.await_count == 1 and response.is_closed
    assert url.endswith(KINDS[kind][1] + '.json')
    assert c.http.request.call_args.kwargs['allowed_domains'] == ('10jqka.com.cn',)


def test_independent_plugin_dataset_registration():
    manager = build_manager(copy.deepcopy(load_config()))
    catalog = manager.entries['dataset.astock'].plugin
    for kind in KINDS:
        assert 'collector.ths_' + kind in manager.entries
        assert 'data.' + kind in manager.entries
        assert 'ui.' + kind in manager.entries
        assert catalog.datasets[kind + '.statement'].projects == {'ths-' + kind + '-v1': 'ths-' + kind}
        assert catalog.datasets[kind + '.statement'].schema_version == 2


def test_retired_financial_wire_schema_is_not_silently_consumed():
    from empire.contracts.data import UnsupportedSchema, make_envelope
    manager = build_manager(copy.deepcopy(load_config()))
    catalog = manager.entries['dataset.astock'].plugin
    event = make_envelope(source='ths', dataset='income.statement', business_key='SH:601139',
        job_key='ths-income-v1', run_id='test', batch_id='test', schema_version=1,
        payload={'page': 1, 'unit': 'SH:601139', 'rows': parse('income', source('income'), STOCK), 'manifest': None})
    assert catalog.schema_owner(event) == 'ths-income'
    with pytest.raises(UnsupportedSchema):
        catalog.mapping(event)


@pytest.mark.parametrize('kind,field', [('income', '少数股东损益'),
                                     ('cashflow', '四、汇率变动对现金及现金等价物的影响')])
def test_statement_arithmetic_retained_but_flagged(kind, field):
    body = source(kind)
    f = json.loads(body['flashData'])
    f['title'].append([field, '元', 2, False, True])
    f['report'].append(['1.00亿', '1.00亿'])
    body['flashData'] = json.dumps(f)
    from empire.plugins.datasets.financial_quality import quality_issues
    rows = parse(kind, body, STOCK)
    assert any(i['criterion'] == 'quality' for i in quality_issues(kind, rows[0]))


def test_statement_matrix_preserves_union_and_source_sections(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.statement_matrix import StatementMatrix, subject_layout
    app = QApplication.instance() or QApplication([])
    records = parse('income', source('income'), STOCK)
    records[0]['fields']['未知新增科目'] = {'value': '-1234567.89', 'resolution': '0.01'}
    records[0]['report_date'] = '2025-12-31'
    records[1]['report_date'] = '2025-06-30'
    records[1]['fields']['*营业总收入'] = None
    layout = subject_layout('income', records)
    assert {x[0] for x in layout if x[3]} == set().union(*(r['fields'] for r in records))
    assert any(x[0] == '报表核心指标' and not x[3] for x in layout)
    widget = StatementMatrix()
    try:
        widget.render('income', records)
        assert len(widget.reports) == 2
        row = next(i for i, x in enumerate(widget.entries) if x[0] == '未知新增科目')
        assert widget.values.item(row, 0).text() == '-123.46'
        assert widget.values.item(row, 1).text() == '—'
        assert '-1234567.89' in widget.values.item(row, 0).toolTip()
        widget.values.setCurrentCell(row, 0)
        widget.render('income', records, annual=True, divisor=1)
        assert [r['report_date'] for r in widget.reports] == ['2025-12-31']
        assert widget.values.item(row, 0).text() == '-1,234,567.89'
        widget.render('income', [])
        assert widget.values.rowCount() == 0 and widget.values.columnCount() == 0
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
