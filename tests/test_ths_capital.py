"""Business counterexamples for every capital page section, without saved HTML."""
import copy
from datetime import date

import pytest

from empire.contracts.ths_capital import CURRENCIES, SECTIONS, TABLES, numeric, validate
from empire.plugins.collectors.holder_html import Document
from empire.plugins.collectors.ths_capital_source import HEADERS, parse

STOCK = dict(code='601139', unified_code='601139.SH', name='样本公司')


def cells(values, tag='td'):
    return '<tr>' + ''.join('<' + tag + '>' + str(v) + '</' + tag + '>' for v in values) + '</tr>'


def table(kind, values):
    return '<table><thead>' + cells(HEADERS[kind], 'th') + '</thead><tbody>' + ''.join(cells(v) for v in values) + '</tbody></table>'


def labelled(values, css='capital'):
    return '<table class="' + css + '">' + ''.join(cells(['<span>' + key + '：</span>' + value]) for key, value in values) + '</table>'


def box(ident, title, body):
    return '<div class="m_box" id="' + ident + '"><h2>' + title + '</h2>' + body + '</div>'


def source(*, quantity='100万股', duplicate=False):
    funding = table('capital_funding', [('2025-01-01', '首发A股', '2025-01-03', '1.25亿', '-', '-', '0%')])
    project = ('2025-01-01', '项目一', '1.00亿', '0.00', '3.5', '-2%', '-',
               '<a class="progressView" content="项目完整&lt;br&gt;简介">展开</a>')
    projects = table('capital_project', [project, project] if duplicate else [project])
    acquisition = labelled([('公告日期', '2025-01-04'), ('交易金额', '500万美元'), ('交易进度', '进行中'),
        ('交易标的', '目标一'), ('买方', '甲'), ('卖方', '乙'), ('交易概述', '初始交易')])
    transfer = labelled([('公告日期', '2025-01-06'), ('交易金额', '--'), ('转让比例', '3.2 %'), ('出让方', '乙'),
        ('交易标的', '目标二'), ('受让方', '甲'), ('交易简介', '<div class="rp_tipbox"><table><thead><tr><th>交易简介详情：</th></tr></thead><tbody><tr><td>完整转让详情</td></tr></tbody></table></div>'),
        ('交易影响', '持股关系发生变化')])
    related = labelled([('公告日期', '2025-01-07'), ('交易金额', '5500.00万澳大利亚元'), ('支付方式', '现金'),
        ('交易方', '关联方一'), ('交易方式', '预计年度额度'), ('关联关系', '同一控制人'), ('交易简介', '非实际已发生金额')])
    summary = table('capital_equity_summary', [('其他', '2', '2万', '1万', '-1万(估)', '--'), ('合计', '2', '2万', '1万', '-1万', '--')])
    positions = '<table><thead>' + cells(HEADERS['capital_equity_position'], 'th') + '</thead><tbody><tr><th rowspan="2">A股</th><td>标的一</td><td>其他</td><td>100万(估)</td><td>1%</td><td>-1万</td></tr><tr><td>标的二</td><td>其他</td><td>-<td>未公布%</td><td>0.00</td></tr></tbody></table>'
    investment = '<a class="fdates" targ="fher_1">2025-06-30</a><div class="m_tab_content" id="fher_1">' + summary + positions + '</div>'
    ipo = table('capital_ipo', [('参股企业', '1.17', '420.33', '已通过发审会', '软件业', '-0.32')])
    original = [('质押公告日期', '2025-01-02'), ('原始质押股数', quantity), ('预计质押期限', '2025-01-01至2027-01-01'),
        ('出质人', '股东甲'), ('质权人', '机构乙'), ('质押相关说明', '原事件说明'),
        ('解押公告日期', '2025-03-01'), ('本次解押股数', '30万股'), ('实际解押日期', '2025-02-28'), ('解押相关说明', '第一次部分解除'),
        ('解押公告日期', '2025-04-01'), ('本次解押股数', '50万股'), ('实际解押日期', '2025-03-31'), ('解押相关说明', '第二次部分解除')]
    freeze = '<div id="ml_006">' + labelled(original, '') + '</div><div id="ml_007"><p class="no_tip">近2年内上市公司无股份冻结情况的公告。</p></div>'
    return '<html><body><input id="stockCode" value="601139">' + ''.join([
        box('raise', '募集资金来源', funding), box('progress', '项目投资', projects), box('asset', '收购兼并', acquisition),
        box('invest', '股权投资', investment), box('ipo', '参股IPO', ipo),
        box('transfer', '股权转让', transfer + transfer.replace('目标二', '目标三')),
        box('connect', '关联交易', related), box('freeze', '质押解冻', freeze)]) + '<!-- F10 Content End --></body></html>'


def test_complete_details_foreign_currency_estimates_and_partial_releases():
    result = parse(source().encode('gb18030'), STOCK, date(2026, 10, 16))
    rows = result['rows']
    assert rows['capital_project'][0]['description'] == '项目完整 简介'
    transfers = [r for r in rows['capital_transaction'] if r['section'] == 'transfer']
    assert len(transfers) == 2 and {r['target'] for r in transfers} == {'目标二', '目标三'}
    assert all(r['description'] == '完整转让详情' and r['impact'] == '持股关系发生变化' for r in transfers)
    assert {r['currency'] for r in rows['capital_transaction'] if r['amount']} == {'美元', '澳大利亚元'}
    assert rows['capital_ipo'][0]['initial_amount'] == '4203300'
    assert len(rows['capital_release']) == 2
    assert all(r['parent_key'] == rows['capital_encumbrance'][0]['record_key'] for r in rows['capital_release'])
    assert {r['quantity'] for r in rows['capital_release']} == {'300000', '500000'}
    assert rows['capital_funding'][0]['balance_amount'] is None
    assert any(r['quantity_estimated'] for r in rows['capital_equity_position'])
    assert any(r['quantity'] is None and r['ratio'] is None for r in rows['capital_equity_position'])
    assert result['availability']['freeze'].startswith('近2年')


@pytest.mark.parametrize('currency', CURRENCIES)
@pytest.mark.parametrize('magnitude,amount', [('', '6'), ('万', '60000'), ('亿', '600000000'), ('万亿', '6000000000000')])
def test_transaction_currency_and_amount_use_same_vocabulary(currency, magnitude, amount):
    expected = parse(source().encode('gb18030'), STOCK)
    actual = parse(source().replace('500万美元', '6.00' + magnitude + currency).encode('gb18030'), STOCK)
    before = next(r for r in expected['rows']['capital_transaction'] if r['section'] == 'asset')
    after = next(r for r in actual['rows']['capital_transaction'] if r['section'] == 'asset')
    assert after == {**before, 'amount': amount, 'currency': currency}
    expected['rows']['capital_transaction'] = [after if r['section'] == 'asset' else r
                                                for r in expected['rows']['capital_transaction']]
    expected['rows']['capital_transaction'].sort(key=lambda r: r['record_key'])
    assert actual == expected


@pytest.mark.parametrize('value', ['31.08亿未知克朗', '31.08亿挪威克朗美元', '31.08亿挪威克朗/人民币',
    '6万亿越南盾人民币', '6万万越南盾', '6亿亿越南盾', '6万亿亿越南盾'])
def test_unknown_or_combined_currency_does_not_default_to_rmb(value):
    with pytest.raises(ValueError, match='单位/数值未知'):
        parse(source().replace('500万美元', value).encode('gb18030'), STOCK)


def test_freeze_and_actual_release_are_separate_from_forecast():
    frozen = labelled([('冻结公告日期', '2025-05-01'), ('原始冻结股数', '200万股'),
        ('预计冻结期限', '2025-04-30至2028-04-29'), ('股东', '股东丙'), ('执行冻结机构', '法院甲'),
        ('冻结相关说明', '轮候冻结'), ('解冻公告日期', '2025-06-01'), ('本次解冻股数', '20万股'),
        ('实际解冻日期', '2025-05-30'), ('解冻相关说明', '部分解冻')], '')
    body = source().replace('<p class="no_tip">近2年内上市公司无股份冻结情况的公告。</p>', frozen)
    rows = parse(body.encode('gb18030'), STOCK)['rows']
    parent = next(r for r in rows['capital_encumbrance'] if r['section'] == 'freeze')
    release = next(r for r in rows['capital_release'] if r['section'] == 'freeze')
    assert release['parent_key'] == parent['record_key']
    assert parent['end_date'] == '2028-04-29' and release['actual_date'] == '2025-05-30'
    assert parent['quantity'] == '2000000' and release['quantity'] == '200000'
    assert rows['capital_encumbrance'] == sorted(rows['capital_encumbrance'], key=lambda r: r['record_key'])


def test_unknown_transaction_table_cannot_become_empty():
    with pytest.raises(ValueError, match='交易事件表'):
        parse(source().replace('class="capital"', 'class="unknown"', 1).encode('gb18030'), STOCK)


@pytest.mark.parametrize('code', ['600663.SH', '601139.SH'])
def test_undisclosed_ipo_object_preserves_disclosed_status_and_multiplicity(code):
    row = cells(['--', '--', '--', '发行失败', '--', '--'])
    body = source().replace(cells(['参股企业', '1.17', '420.33', '已通过发审会', '软件业', '-0.32']), row + row)
    body = body.replace('value="601139"', 'value="' + code[:6] + '"')
    rows = parse(body.encode('gb18030'), dict(STOCK, code=code[:6], unified_code=code))['rows']['capital_ipo']
    assert len(rows) == len({r['record_key'] for r in rows}) == 2
    assert all(r['target'] is None and r['status'] == '发行失败' and r['initial_amount'] is None for r in rows)


@pytest.mark.parametrize('bad', ['missing_column', 'missing_status'])
def test_undisclosed_ipo_object_does_not_hide_broken_or_empty_row(bad):
    body = source().replace('参股企业', '--')
    body = body.replace('<td>--</td><td>1.17', '<td>1.17') if bad == 'missing_column' else body.replace('已通过发审会', '--')
    with pytest.raises(ValueError):
        parse(body.encode('gb18030'), STOCK)


@pytest.mark.parametrize('code', ['688510.SH', '601139.SH'])
def test_source_future_announcement_is_retained_and_explicitly_flagged(code):
    from empire.contracts.ths_capital import FUTURE_ANNOUNCEMENT
    body = source().replace('value="601139"', 'value="' + code[:6] + '"')
    body = body.replace('2025-01-01', '2026-10-19').replace('2025-01-03', '2026-10-21')
    result = parse(body.encode('gb18030'), dict(STOCK, code=code[:6], unified_code=code), date(2026, 10, 18))
    assert result['rows']['capital_funding'][0]['event_date'] == '2026-10-19'
    assert result['rows']['capital_funding'][0]['issue_start'] == '2026-10-21'
    assert result['availability']['raise_'] == FUTURE_ANNOUNCEMENT
    assert result['availability']['progress'] == FUTURE_ANNOUNCEMENT
    result['availability']['raise_'] = 'available'
    with pytest.raises(ValueError, match='日期无效/超前'):
        validate(code, **result, today=date(2026, 10, 18))


def test_future_report_period_is_rejected_even_with_announcement_flag():
    from empire.contracts.ths_capital import FUTURE_ANNOUNCEMENT
    result = parse(source().encode('gb18030'), STOCK)
    result['availability']['invest'] = FUTURE_ANNOUNCEMENT
    result['rows']['capital_equity_position'][0]['event_date'] = '2026-12-31'
    with pytest.raises(ValueError, match='日期无效/超前'):
        validate(STOCK['unified_code'], **result, today=date(2026, 10, 18))


def test_explicit_unknown_release_quantity_keeps_event_parent_and_dates():
    rows = parse(source().replace('30万股', '--').encode('gb18030'), STOCK)['rows']
    unknown = next(r for r in rows['capital_release'] if r['event_date'] == '2025-03-01')
    assert unknown['quantity'] is None and unknown['actual_date'] == '2025-02-28'
    assert unknown['parent_key'] == rows['capital_encumbrance'][0]['record_key']
    assert len(rows['capital_release']) == 2
    assert rows['capital_encumbrance'][0]['quantity'] == '1000000'


def encumbrance_source(section, quantity='--'):
    body = source(quantity=quantity)
    if section == 'freeze':
        for before, after in [('ml_006', 'ml_007'), ('ml_007"><p', 'ml_006"><p'),
                ('质押', '冻结'), ('出质人', '股东'), ('质权人', '执行冻结机构'), ('解押', '解冻')]:
            body = body.replace(before, after)
        body = body.replace('<h2>冻结解冻</h2>', '<h2>质押解冻</h2>')
    return body


@pytest.mark.parametrize('section', ['pledge', 'freeze'])
@pytest.mark.parametrize('code', ['601139.SH', '002219.SZ'])
def test_explicit_unknown_original_quantity_preserves_linkage_and_multiplicity(section, code):
    body = encumbrance_source(section).replace('value="601139"', 'value="' + code[:6] + '"')
    rows = parse(body.encode('gb18030'), dict(STOCK, code=code[:6], unified_code=code))['rows']
    parent = rows['capital_encumbrance'][0]
    assert parent['quantity'] is None and parent['section'] == section
    assert len(rows['capital_release']) == 2
    assert all(r['parent_key'] == parent['record_key'] for r in rows['capital_release'])
    assert {r['quantity'] for r in rows['capital_release']} == {'300000', '500000'}


@pytest.mark.parametrize('section', ['pledge', 'freeze'])
@pytest.mark.parametrize('bad', ['missing_label', 'missing_date', 'missing_holder', 'malformed_quantity'])
def test_unknown_original_quantity_does_not_allow_missing_structure(section, bad):
    body = encumbrance_source(section)
    label = '原始质押股数' if section == 'pledge' else '原始冻结股数'
    if bad == 'missing_label':
        body = body.replace('<tr><td><span>' + label + '：</span>--</td></tr>', '')
    elif bad == 'missing_date':
        body = body.replace('2025-01-02', '--')
    elif bad == 'missing_holder':
        body = body.replace('股东甲', '--')
    else:
        body = body.replace(label + '：</span>--', label + '：</span>未知股')
    with pytest.raises(ValueError):
        parse(body.encode('gb18030'), STOCK)


def test_missing_release_quantity_label_is_not_source_unknown():
    body = source().replace('<tr><td><span>本次解押股数：</span>30万股</td></tr>', '')
    with pytest.raises(ValueError, match='股数字段标签'):
        parse(body.encode('gb18030'), STOCK)


def test_release_announcement_still_required_when_quantity_unknown():
    body = source().replace('30万股', '--').replace('2025-03-01', '--')
    with pytest.raises(ValueError, match='公告日期缺失'):
        parse(body.encode('gb18030'), STOCK)


def test_duplicate_source_rows_preserve_multiplicity_not_just_count():
    result = parse(source(duplicate=True).encode('gb18030'), STOCK)
    projects = result['rows']['capital_project']
    assert len(projects) == len({r['record_key'] for r in projects}) == 2
    changed = parse(source(duplicate=True).replace('项目一', '项目二', 1).encode('gb18030'), STOCK)
    assert {r['record_key'] for r in changed['rows']['capital_project']} != {r['record_key'] for r in projects}


@pytest.mark.parametrize('transform', [lambda s:s[:-7], lambda s:s.replace('value="601139"', 'value="600000"'),
    lambda s:s.replace('持股数量(股)', '持股数量(万股)'), lambda s:s.replace('rowspan="2"', 'rowspan="3"'),
    lambda s:s.replace('fher_1">2025-06-30', 'fher_2">2025-06-30'),
    lambda s:s.replace('content="项目完整&lt;br&gt;简介"', ''),
    lambda s:s.replace('2025-06-30', '2029-06-30'), lambda s:s.replace('id="raise"', 'id="unknown"')])
def test_invalid_unit_never_becomes_empty(transform):
    with pytest.raises(ValueError):
        parse(transform(source()).encode('gb18030'), STOCK, date(2026, 10, 16))


def test_nested_table_does_not_close_outer_row_or_lose_sibling_table():
    tree = Document('<table><tr><td>外<table><tr><td>内</td></tr></table></td></tr><tr><td>后续</td></tr></table><table><tr><td>第二事件</td></tr></table>').root
    assert len(tree.find('table')) == 3
    assert '后续' in tree.find('table')[0].text() and '第二事件' in tree.find('table')[-1].text()


def test_typed_message_missing_parent_and_extra_fields_rejected():
    result = parse(source().encode('gb18030'), STOCK)
    bad = copy.deepcopy(result)
    bad['rows']['capital_encumbrance'] = []
    with pytest.raises(ValueError, match='缺少原事件'):
        validate(STOCK['unified_code'], **bad)
    bad = copy.deepcopy(result)
    bad['rows']['capital_project'][0]['raw_html'] = '<table>'
    with pytest.raises(ValueError, match='字段'):
        validate(STOCK['unified_code'], **bad)
    assert set(result['rows']) == set(TABLES) and set(result['availability']) == set(SECTIONS)


@pytest.mark.parametrize('value,expected', [('29.80亿', '2980000000'), ('-1.55亿', '-155000000'), ('0.00', '0'), ('-0.00万', '0'), ('--', None),
    ('--%', None), ('- %', None), ('—%', None), ('未公布%', None), ('0%', '0'), ('12.50%', '12.5')])
def test_number_units(value, expected):
    assert numeric(value) == expected


@pytest.mark.parametrize('value,expected', [('1.234567万亿', '1234567000000'),
    ('-0.5万亿元', '-500000000000'), ('6.00万亿越南盾', '6000000000000'),
    ('1584.42万马来西亚林吉特', '15844200'), ('1559.49亿印度尼西亚卢比', '155949000000')])
def test_trillion_scale_is_explicit_and_overrides_header_scale(value, expected):
    assert numeric(value, scale=10000) == expected


def test_trillion_scale_keeps_sql_range_limit():
    with pytest.raises(ValueError, match='超界'):
        numeric('10000000000万亿越南盾')


def test_overlapping_currency_names_preserve_source_denomination():
    assert len(CURRENCIES) == len(set(CURRENCIES))
    for name in ('马来西亚林吉特', '文莱林吉特', '俄罗斯卢布'):
        actual = parse(source().replace('500万美元', '150.00万' + name).encode('gb18030'), STOCK)
        row = next(r for r in actual['rows']['capital_transaction'] if r['section'] == 'asset')
        assert row['amount'] == '1500000' and row['currency'] == name


@pytest.mark.parametrize('code,unit', [('000559', '000559.SZ'), ('601139', '601139.SH')])
def test_thai_baht_is_supported_in_all_transaction_sections(code, unit):
    body = source().replace('601139', code).replace('500万美元', '5.54亿泰铢')
    body = body.replace('5500.00万澳大利亚元', '5.54亿泰铢').replace('交易金额：</span>--', '交易金额：</span>5.54亿泰铢')
    rows = parse(body.encode('gb18030'), dict(code=code, unified_code=unit))['rows']['capital_transaction']
    assert {r['section'] for r in rows} == {'asset', 'transfer', 'connect'}
    assert all(r['amount'] == '554000000' and r['currency'] == '泰铢' for r in rows)


@pytest.mark.parametrize('code,unit', [('000513', '000513.SZ'), ('601139', '601139.SH')])
def test_trillion_currency_applies_to_every_transaction_section_and_security(code, unit):
    body = source().replace('601139', code).replace('500万美元', '6.00万亿越南盾')
    body = body.replace('5500.00万澳大利亚元', '6.00万亿越南盾').replace('交易金额：</span>--', '交易金额：</span>6.00万亿越南盾')
    rows = parse(body.encode('gb18030'), dict(code=code, unified_code=unit))['rows']['capital_transaction']
    assert {r['section'] for r in rows} == {'asset', 'transfer', 'connect'}
    assert all(r['amount'] == '6000000000000' and r['currency'] == '越南盾' for r in rows)


@pytest.mark.parametrize('placeholder', ['--%', '-%', '—%'])
def test_missing_percentage_retains_investment_record_and_other_facts(placeholder):
    expected = parse(source().encode('gb18030'), STOCK)
    actual = parse(source().replace('未公布%', placeholder).encode('gb18030'), STOCK)
    assert actual == expected
    missing = [r for r in actual['rows']['capital_equity_position'] if r['target'] == '标的二']
    assert len(missing) == 1 and missing[0]['ratio'] is None and missing[0]['profit'] == '0'


@pytest.mark.parametrize('value', ['--%%', '未知%', '12.5%%', '--万元'])
def test_invalid_numeric_text_is_not_a_missing_percentage(value):
    with pytest.raises(ValueError, match='单位/数值未知'):
        numeric(value)


@pytest.mark.parametrize('missing', ['未公布', '--', '—', ''])
@pytest.mark.parametrize('code,unit', [('601139', '601139.SH'), ('000156', '000156.SZ')])
def test_undisclosed_holding_object_preserves_complete_row(missing, code, unit):
    body = source().replace('601139', code).replace('标的一', missing)
    rows = parse(body.encode('gb18030'), dict(code=code, unified_code=unit))['rows']
    unknown = next(r for r in rows['capital_equity_position'] if r['target'] is None)
    assert unknown['category'] == 'A股' and unknown['investment_type'] == '其他'
    assert unknown['event_date'] == '2025-06-30'
    assert unknown['quantity'] == '1000000' and unknown['profit'] == '-10000'
    assert len(rows['capital_equity_position']) == 2


def test_undisclosed_holdings_keep_multiplicity_and_order_independent_keys():
    row = '<tr><td>未公布</td><td>其他</td><td>0</td><td>--%</td><td>-1万</td></tr>'
    def page(extra):
        return source().replace('rowspan="2"', 'rowspan="4"').replace('<tr><td>标的二', extra + '<tr><td>标的二')
    a = parse(page(row + row).encode('gb18030'), STOCK)['rows']['capital_equity_position']
    assert len(a) == 4 and len({r['record_key'] for r in a}) == 4
    assert len([r for r in a if r['target'] is None]) == 2
    b = parse(page(row + row.replace('-1万', '-2万')).encode('gb18030'), STOCK)
    c = parse(page(row.replace('-1万', '-2万') + row).encode('gb18030'), STOCK)
    assert b == c


@pytest.mark.parametrize('before,after,error', [
    ('<td>标的一</td>', '', '行宽'),
    ('rowspan="2">A股', 'rowspan="2">未公布', '业务主体缺失'),
    ('<td>标的一</td><td>其他</td>', '<td>未公布</td><td>--</td>', '业务主体缺失'),
    ('项目一', '未公布', '业务主体缺失'),
])
def test_unknown_holding_object_does_not_relax_other_subjects_or_structure(before, after, error):
    with pytest.raises(ValueError, match=error):
        parse(source().replace(before, after).encode('gb18030'), STOCK)
