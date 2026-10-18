"""Official protocol counterexamples and typed rule contract regressions."""
import copy
import io
import json

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from empire.contracts.rule_review import EXPECTED
from empire.contracts.trading_rules import KINDS, validate
from empire.plugins.collectors.rule_bse import BJ_FILE, BJ_LIST, BJ_NOTICE, BJ_RESUMED
from empire.plugins.collectors.rule_bse import directory as bj_directory
from empire.plugins.collectors.rule_sources import (
    FEE_ANNOUNCEMENT,
    SH_DEFERRED,
    SH_FILE,
    SH_LIST,
    SH_NOTICE,
    SZ_FILE,
    SZ_LIST,
    SZ_NOTICE,
    TAX_HALF,
    TAX_LAW,
    TAX_RATE,
    decode_source,
    exchange_parameters,
    sh_directory,
    stamp_parameters,
    sz_directory,
    transfer_parameters,
)
from tests.rule_bse_samples import CLAUSES as BJ_CLAUSES
from tests.rule_samples import CLAUSES
from tests.test_rule_documents import docx


def tiny_pdf(lines):
    """Minimal Unicode text PDF; no source PDF is copied into tests."""
    text = '\n'.join(lines)
    chars = sorted(set(text) - {'\n'})
    codes = {c: i + 1 for i, c in enumerate(chars)}
    cmap = ('/CIDInit /ProcSet findresource begin 12 dict begin begincmap '
        '/CIDSystemInfo << /Registry (Test) /Ordering (Unicode) /Supplement 0 >> def '
        '/CMapName /Test def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange '
        + str(len(chars)) + ' beginbfchar ' + ' '.join(f'<{codes[c]:04X}> <{c.encode("utf-16-be").hex()}>' for c in chars)
        + ' endbfchar endcmap CMapName currentdict /CMap defineresource pop end end').encode()
    writer = PdfWriter()
    page = writer.add_blank_page(1000, 2000)
    unicode = DecodedStreamObject()
    unicode.set_data(cmap)
    descendant = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/CIDFontType2'), NameObject('/BaseFont'): NameObject('/Test'), NameObject('/DW'): NumberObject(500), NameObject('/CIDSystemInfo'): DictionaryObject({NameObject('/Registry'): NameObject('/Test'), NameObject('/Ordering'): NameObject('/Unicode'), NameObject('/Supplement'): NumberObject(0)})})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type0'), NameObject('/BaseFont'): NameObject('/Test'), NameObject('/Encoding'): NameObject('/Identity-H'), NameObject('/DescendantFonts'): ArrayObject([writer._add_object(descendant)]), NameObject('/ToUnicode'): writer._add_object(unicode)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    commands = 'BT /F1 10 Tf 12 TL 10 1900 Td ' + ' T* '.join('<' + ''.join(f'{codes[c]:04X}' for c in line) + '> Tj' for line in lines) + ' ET'
    stream = DecodedStreamObject()
    stream.set_data(commands.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def responses():
    citations = {key: value for kind in CLAUSES.values() for key, value in kind.items()}
    docs = {}
    for url, encoder in [(SH_FILE, docx), (SZ_FILE, tiny_pdf)]:
        values = {key.rsplit('#', 1)[1]: value for key, value in citations.items() if key.startswith(url + '#')}
        docs[url] = encoder([key + ' ' + value for key, value in sorted(values.items())] + (['3.7.1 投资者可以通过盘后固定价格交易方式买卖A股。'] if url == SH_FILE else []))
    docs[SH_LIST] = ('2026-04-24 @memo@ /sse/lawandrules/c/c_20260424_10816492.shtml @memo@ 上海证券交易所交易规则（2026年修订） @doc@').encode()
    docs[SZ_LIST] = json.dumps(dict(totalSize=1, currentPage=1, pageSize=20, data=[dict(id='620190', doctitle='关于发布《深圳证券交易所交易规则（2026年修订）》的通知')])).encode()
    docs[SH_NOTICE] = ('<p>上海证券交易所交易规则 2026年7月6日 上证发〔2026〕41号 现行有效</p>' + f'<a href="{SH_FILE}">附件1</a><a href="{SH_DEFERRED}">暂缓附件</a>').encode()
    docs[SZ_NOTICE] = ('<p>深圳证券交易所交易规则 2026年7月6日 深证上〔2026〕551号</p>' + f'<a href="{SZ_FILE}">附件</a>').encode()
    docs[SH_DEFERRED] = docx(['暂缓实施3.6.2、3.6.3、3.6.4、3.6.9、3.6.10'])
    docs[BJ_FILE] = docx([key + ' ' + value for key, value in sorted(BJ_CLAUSES.items())])
    docs[BJ_LIST] = ('null(' + json.dumps([dict(result=True, data=dict(number=0, lastPage=True, totalElements=2,
        content=[dict(infoId=200028217, nodeId=1304, title='关于发布《北京证券交易所交易规则》的公告',
                      fileUrl=BJ_FILE.removeprefix('https://www.bse.cn')),
                 dict(infoId=200029608, nodeId=1304, title='关于实施《北京证券交易所交易规则》相关条款的公告')]))]) + ')').encode()
    docs[BJ_NOTICE] = '北证公告〔2026〕17号 2026年7月6日 第3.6.5条第二款和第三款、第3.7.1条至第3.7.10条、第4.5.1条至第4.5.4条 另行通知 现行有效'.encode()
    docs[BJ_RESUMED] = ('北证公告〔2026〕43号 2026-10-16 第4.5.1条至第4.5.4条 已于2026年8月31日起实施。'
        '第3.6.5条第二款和第三款关于无价格涨跌幅限制股票的大宗交易申报价格范围的规定，自2026年10月26日起正式实施。现行有效').encode()
    refs = CLAUSES['stamp_duty']
    third, fifth = refs[TAX_LAW + '#第三条'], refs[TAX_LAW + '#第五条']
    docs[TAX_LAW] = ('<h1>中华人民共和国印花税法</h1><p>第三条' + third + '第四条略。第五条' + fifth + '第六条略。</p>').encode()
    docs[TAX_RATE] = ('<h1>证券交易的印花税税率是多少</h1><p>' + refs[TAX_RATE + '#法定税率'] + '</p>').encode()
    docs[TAX_HALF] = ('<h1>关于减半征收证券交易印花税的公告</h1><p>' + refs[TAX_HALF + '#减半征收'] + '</p>').encode()
    docs[FEE_ANNOUNCEMENT] = ('<h1>中国结算：4月29日起股票交易过户费总体下调50%</h1><p>' + CLAUSES['transfer_fee'][FEE_ANNOUNCEMENT + '#2022费率调整'] + '</p>').encode()
    return docs


def sample(kind):
    docs = responses()
    if kind == 'stamp_duty':
        return stamp_parameters(*(decode_source(url, docs[url]) for url in (TAX_LAW, TAX_RATE, TAX_HALF)))
    if kind == 'transfer_fee':
        return transfer_parameters(decode_source(FEE_ANNOUNCEMENT, docs[FEE_ANNOUNCEMENT])).result()
    return exchange_parameters(kind, *(decode_source(url, docs[url]) for url in (SH_FILE, SZ_FILE, BJ_FILE)))


@pytest.mark.parametrize('kind', KINDS)
def test_minimal_source_to_parameter_contract(kind):
    p = sample(kind)
    assert len(p['rows']) == len(EXPECTED[kind])
    assert validate(kind, p['rows'], p['citations'])


def test_same_count_missing_quote_wrong_rate_and_missing_parameter():
    p = sample('limit_rules')
    for mutate in [lambda v: v['rows'].__setitem__(0, v['rows'][1]),
                   lambda v: v['citations'].pop(),
                   lambda v: v['rows'][0].__setitem__('number_value', '10'),
                   lambda v: v['citations'][0].__setitem__('excerpt', '伪造旧规则')]:
        bad = copy.deepcopy(p)
        mutate(bad)
        with pytest.raises(ValueError):
            validate('limit_rules', bad['rows'], bad['citations'])


def test_directory_new_version_duplicate_and_incomplete_are_rejected():
    docs = responses()
    sh_directory(docs[SH_LIST])
    sz_directory(docs[SZ_LIST])
    with pytest.raises(ValueError):
        sh_directory(docs[SH_LIST].replace(b'2026-04-24', b'2027-04-24'))
    data = json.loads(docs[SZ_LIST])
    data['data'] *= 2
    data['totalSize'] = 2
    with pytest.raises(ValueError, match='重复'):
        sz_directory(json.dumps(data).encode())
    data['data'] = data['data'][:1]
    with pytest.raises(ValueError, match='完整'):
        sz_directory(json.dumps(data).encode())


def test_new_rule_text_fails_review_instead_of_reusing_old_constants():
    docs = responses()
    parsed = decode_source(SH_FILE, docs[SH_FILE])
    parsed.clauses['3.3.13'] += '新增未审核例外。'
    with pytest.raises(ValueError, match='重新审核'):
        exchange_parameters('limit_rules', parsed, decode_source(SZ_FILE, docs[SZ_FILE]), decode_source(BJ_FILE, docs[BJ_FILE]))


def test_beijing_complete_directory_and_deferred_after_hours():
    docs = responses()
    for url in (BJ_LIST, BJ_NOTICE, BJ_RESUMED):
        assert decode_source(url, docs[url])
    raw = json.loads(docs[BJ_LIST][5:-1])
    raw[0]['data']['lastPage'] = False
    with pytest.raises(ValueError, match='完整'):
        bj_directory(('null(' + json.dumps(raw) + ')').encode())
    raw[0]['data']['lastPage'] = True
    raw[0]['data']['content'][1]['infoId'] = 200028217
    with pytest.raises(ValueError, match='重复'):
        bj_directory(('null(' + json.dumps(raw) + ')').encode())
    assert {r['parameter_key'] for r in sample('sessions')['rows'] if r['market'] == 'BJ'} == {
        'open_auction', 'continuous_am', 'continuous_pm', 'close_auction'}
    assert next(r for r in sample('limit_rules')['rows'] if r['market'] == 'BJ' and r['parameter_key'] == 'limit_ratio')['number_value'] == '0.30'
    with pytest.raises(ValueError, match='暂缓'):
        decode_source(BJ_RESUMED, docs[BJ_RESUMED] + b'3.7.1')


@pytest.mark.parametrize('old,new', [('2026年10月26日', '2026年10月19日'),
    ('第3.6.5条第二款和第三款', '第3.6.5条全部条款'), ('43号', '34号')])
def test_beijing_resumption_date_and_scope_require_review(old, new):
    body = responses()[BJ_RESUMED].decode().replace(old, new).encode()
    with pytest.raises(ValueError, match='重新审核'):
        decode_source(BJ_RESUMED, body)


def test_beijing_old_resumption_directory_is_not_current():
    body = responses()[BJ_LIST].replace(b'200029608', b'200029142')
    with pytest.raises(ValueError, match='重新审核'):
        bj_directory(body)


def test_percentage_display_preserves_magnitude():
    from empire.plugins.ui.trading_rules import display_value
    for raw, expected in [('0.10', '10'), ('0.20', '20'), ('0.0005', '0.05'), ('0.00001', '0.001'), ('0', '0'), ('1', '100')]:
        assert display_value(dict(number_value=raw, unit='ratio'), 'number_value') == expected


def test_replaced_sse_attachments_cannot_pass_notice_contract():
    current = responses()[SH_NOTICE]
    assert decode_source(SH_NOTICE, current) is True
    for replacement in (
        current.replace(SH_FILE.encode(), b'https://www.sse.com.cn/old-rule.docx'),
        current.replace(SH_DEFERRED.encode(), b'https://www.sse.com.cn/old-deferred.docx'),
    ):
        with pytest.raises(ValueError, match='必要附件集合不符'):
            decode_source(SH_NOTICE, replacement)
