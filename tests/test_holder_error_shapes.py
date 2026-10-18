"""Actual source counterexamples: large notices, missing exit ratios, tied ranks."""
import copy

import pytest

from empire.contracts.holders import validate
from empire.plugins.collectors.ths_holders_source import parse
from tests.test_ths_holders import STOCK, source


@pytest.mark.parametrize('code', ['002672', '002594', '000002'])
def test_combined_ah_caption_preserves_basis_and_complete_members(code):
    stock = {**STOCK, 'code': code, 'unified_code': code + '.SZ'}
    body = source(code=code).replace('累计持有：', '累计持有A、H流通股：').replace('累计占总股本比', '累计占A、H流通股比')
    report = parse(body, 'float_holders', stock)[0]
    assert report['ratio_basis'] == 'A、H流通股'
    assert report['total_quantity'] == '1000000'
    assert len(report['members']) == 11
    assert report['quality_flags'] == 0
    with pytest.raises(ValueError, match='汇总缺失'):
        parse(body.replace('累计持有A、H流通股', '未知栏目'), 'float_holders', stock)
    with pytest.raises(ValueError, match='不同集合'):
        parse(body.replace('股东1</td>', '股东0</td>'), 'float_holders', stock)


def large_notice():
    body = source(count=159)
    body = body.replace('<caption>前十大累计持有：<em>100.00万股</em>，累计占总股本比：<em>10.00%</em></caption>',
                        '<caption>主要股东持股变动公告</caption>')
    old = '<tr class="gray"><td>退出人</td><td>5.00万</td><td>退出</td><td>0.50%</td><td></td><td></td><td></td></tr>'
    exits = ''.join(old.replace('退出人', '退出人' + str(i)).replace('0.50%', '--') for i in range(149))
    # Only stock notices are enlarged; bond totals remain independently valid.
    start = body.index('<div id="bondholder">')
    return body[:start].replace(old, exits) + source()[source().index('<div id="bondholder">'):]


@pytest.mark.parametrize('kind', ['top_holders', 'float_holders'])
def test_large_notice_and_exit_unknowns_preserve_every_identity(kind):
    report = parse(large_notice(), kind, STOCK)[0]
    assert len(report['members']) == 308
    assert len({(m['member_group'], m['holder_name']) for m in report['members']}) == 308
    assert all(m['ratio'] is None for m in report['members'] if m['member_group'] == 'exited')
    bad = copy.deepcopy(report)
    bad['members'][0]['ratio'] = None
    with pytest.raises(ValueError):
        validate(kind, STOCK['unified_code'], [bad])
    bad = copy.deepcopy(report)
    bad['members'][1]['holder_name'] = bad['members'][0]['holder_name']
    with pytest.raises(ValueError, match='不同集合'):
        validate(kind, STOCK['unified_code'], [bad])
    bad = copy.deepcopy(report)
    for i in range(160, 202):
        bad['members'].insert(i-1, {**bad['members'][0], 'seq': i, 'holder_name': 'extra' + str(i)})
    with pytest.raises(ValueError, match='名单数量无效'):
        validate(kind, STOCK['unified_code'], [bad])


def test_bond_parallel_ranks_and_rank_eleven_are_independent_of_row_identity():
    body = source().replace('<td>2</td><td>股东1', '<td>1</td><td>股东1')
    row = parse(body, 'bond_holders', STOCK)[0]
    assert [m['seq'] for m in row['members'][:2]] == [1, 2]
    assert [m['source_rank'] for m in row['members'][:2]] == [1, 1]
    row['members'] = [row['members'][0]]
    row['members'][0]['source_rank'] = 11
    row.update(total_quantity='100000', total_ratio='1')
    assert validate('bond_holders', STOCK['unified_code'], [row])
    row['members'][0]['source_rank'] = 10000
    with pytest.raises(ValueError, match='来源排名无效'):
        validate('bond_holders', STOCK['unified_code'], [row])


def test_total_rounding_does_not_relax_member_ratio_or_summary_equality():
    row = parse(source(), 'bond_holders', STOCK)[0]
    row['total_ratio'] = '100.01'
    for i, m in enumerate(row['members'][:10]):
        m['ratio'] = '10.01' if i == 0 else '10'
    assert validate('bond_holders', STOCK['unified_code'], [row])
    bad = copy.deepcopy(row)
    bad['total_ratio'] = '100.06'
    with pytest.raises(ValueError, match='舍入上界'):
        validate('bond_holders', STOCK['unified_code'], [bad])
    bad = copy.deepcopy(row)
    bad['members'][0]['ratio'] = '100.01'
    with pytest.raises(ValueError, match='超出范围'):
        validate('bond_holders', STOCK['unified_code'], [bad])
    bad = copy.deepcopy(row)
    bad['total_quantity'] = '2000000'
    with pytest.raises(ValueError, match='数量合计'):
        validate('bond_holders', STOCK['unified_code'], [bad])


def test_periodic_source_can_list_more_than_twenty_with_independent_totals():
    body = source(count=84).replace('100.00万股', '840.00万股').replace('<em>10.00%</em>', '<em>84.00%</em>')
    row = parse(body, 'top_holders', STOCK)[0]
    assert len(row['members']) == 85 and row['total_ratio'] == '84'
    bad = copy.deepcopy(row)
    bad['total_quantity'] = '1000000'
    with pytest.raises(ValueError, match='数量合计'):
        validate('top_holders', STOCK['unified_code'], [bad])


def test_missing_sections_require_complete_source_profile_and_valid_top_reports():
    body = source()
    start = body.index('<div id="flowholder">')
    body = body[:start] + '<div id="holdernum"></div><div id="holdlevel"></div></html>'
    assert parse(body, 'float_holders', STOCK) == []
    assert parse(body, 'bond_holders', STOCK) == []
    for damaged in (body.replace('id="holdlevel"', 'id="wrong"'), body.replace('股东1','股东0'), body.replace('10.00万','未知单位')):
        with pytest.raises(ValueError):
            parse(damaged, 'float_holders', STOCK)
