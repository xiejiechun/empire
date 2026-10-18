"""Rule-document regressions use minimal documents, never successful source dumps."""
import io
import zipfile

import pytest
from pypdf import PdfWriter

from empire.plugins.collectors.rule_documents import (
    MAX_TEXT_BYTES,
    RuleDocument,
    docx_document,
    html_document,
    numbered_clauses,
    official_url,
    pdf_document,
)


def docx(lines, *, duplicate=False):
    output = io.BytesIO()
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>' + ''.join('<w:p><w:r><w:t>' + s + '</w:t></w:r></w:p>' for s in lines)
           + '</w:body></w:document>').encode()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', xml)
        if duplicate:
            with pytest.warns(UserWarning):
                archive.writestr('word/document.xml', xml)
    return output.getvalue()


def test_clause_references_do_not_overwrite_real_headings():
    clauses = numbered_clauses(docx_document(docx([
        '交易规则目录', '3.3.13 本所涨跌幅比例10%。',
        '对第3.3.13条规定的股票适用。', '6.6 科创板涨跌幅比例20%。'])))
    assert set(clauses) == {'3.3.13', '6.6'}
    assert clauses['3.3.13'] == '本所涨跌幅比例10%。对第3.3.13条规定的股票适用。'
    assert clauses['6.6'] == '科创板涨跌幅比例20%。'


def test_duplicate_a_replaces_b_is_rejected_even_same_count():
    with pytest.raises(ValueError, match='重复'):
        numbered_clauses('3.3.8 买入100股\n3.3.8 买入100股')
    document = RuleDocument.decode(issuer='交易所', title='交易规则',
        url='https://example.org/rules.docx', published='2026-04-24', effective='2026-07-06',
        body=docx(['3.3.8 买入100股', '3.3.11 A股价格0.01元人民币']), format='docx')
    assert len(document.body_hash) == 64
    assert document.require('3.3.8', '100股') == '买入100股'
    with pytest.raises(ValueError, match='必需'):
        document.require('3.3.13', '10%')
    with pytest.raises(ValueError, match='必需'):
        document.require('3.3.11', '美元')


@pytest.mark.parametrize('body', [b'<script>challenge()</script>', b'', b'not a document'])
def test_challenge_and_invalid_signatures_are_not_business_data(body):
    for decode in (docx_document, pdf_document):
        with pytest.raises(ValueError, match='签名'):
            decode(body)


def test_docx_duplicate_oversize_and_xml_entities():
    with pytest.raises(ValueError, match='成员'):
        docx_document(docx(['3.3.8 100股'], duplicate=True))
    with pytest.raises(ValueError, match='文本上限'):
        docx_document(docx(['3.3.8 ' + '汉' * MAX_TEXT_BYTES]))
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', b'<!DOCTYPE test [<!ENTITY x "boom">]><x>&x;</x>')
    with pytest.raises(ValueError, match='实体'):
        docx_document(output.getvalue())


def test_html_excludes_scripts_and_keeps_actual_links():
    body = '<meta charset="utf-8"><script>假规则</script><p>交易规则</p><a href="rules.docx">附件1</a>'.encode()
    text, links = html_document(body)
    assert '假规则' not in text and '交易规则' in text
    assert links == [('rules.docx', '附件1')]
    assert official_url('https://www.sse.com.cn/a/', '/b/rules.docx', ('sse.com.cn',)) == 'https://www.sse.com.cn/b/rules.docx'


@pytest.mark.parametrize('url', ['https://sse.com.cn.evil.test/a', 'javascript:alert(1)',
    'https://user:secret@www.sse.com.cn/a', '//evil.test/a'])
def test_download_links_cannot_escape_official_domains(url):
    with pytest.raises(ValueError, match='来源'):
        official_url('https://www.sse.com.cn/', url, ('sse.com.cn',))


def test_pdf_page_limit_and_empty_text():
    writer = PdfWriter()
    for _ in range(81):
        writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match='页数'):
        pdf_document(output.getvalue())


def test_clauses_are_bounded_and_dates_are_not_guessed():
    with pytest.raises(ValueError, match='上限'):
        numbered_clauses('3.3.8 ' + 'x' * 4001)
    with pytest.raises(ValueError, match='生效'):
        RuleDocument.decode(issuer='交易所', title='规则', url='https://example.org',
            published='2026-07-07', effective='2026-07-06', body=b'', format='docx')


def test_pdf_compressed_stream_limit_is_enforced_and_restored():
    from pypdf.errors import LimitReachedError
    from pypdf.generic import DecodedStreamObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b" " * (4 * MAX_TEXT_BYTES + 1))
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(LimitReachedError):
        pdf_document(output.getvalue())
    # The rule decoder context must not leak its stricter limit to other readers.
    from pypdf import PdfReader
    assert len(PdfReader(io.BytesIO(output.getvalue())).pages[0].get_contents().get_data()) == 4 * MAX_TEXT_BYTES + 1
