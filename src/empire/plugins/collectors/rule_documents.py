"""Bounded official-document decoding; source text never executes as code."""
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from pypdf import PdfReader, apply_configuration

MAX_TEXT_BYTES = 512 * 1024
MAX_CLAUSE_CHARS = 4000
MAX_CLAUSES = 500
WORD = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
CLAUSE = re.compile(r'^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)(?![\d.])\s*(.*)$')


def compact(value):
    return re.sub(r'\s+', '', value)


def bounded_text(value):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > MAX_TEXT_BYTES:
        raise ValueError('规则正文为空或超过解码文本上限')
    return value


class RuleHtml(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links = [], []
        self.hidden, self.anchor = 0, None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'tr', 'div', 'li', 'h1', 'h2', 'br'):
            self.parts.append('\n')
        if tag == 'a':
            self.anchor = [dict(attrs).get('href', ''), '']

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)
            if self.anchor is not None:
                self.anchor[1] += value

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'a' and self.anchor is not None:
            self.links.append(tuple(self.anchor))
            self.anchor = None
        if tag in ('p', 'tr', 'div', 'li', 'h1', 'h2'):
            self.parts.append('\n')


def html_document(body):
    if not isinstance(body, bytes) or len(body) > 2 * MAX_TEXT_BYTES:
        raise ValueError('规则HTML响应类型或大小无效')
    match = re.search(br'charset=["\x27]?([a-zA-Z0-9_-]+)', body[:5000])
    encoding = match[1].decode() if match else 'utf-8'
    if encoding.lower() not in ('utf-8', 'utf8', 'gbk', 'gb2312', 'gb18030'):
        raise ValueError('规则HTML字符集不支持')
    parser = RuleHtml()
    parser.feed(body.decode(encoding, errors='strict'))
    return bounded_text(''.join(parser.parts)), parser.links


def docx_document(body):
    if not isinstance(body, bytes) or not body.startswith(b'PK'):
        raise ValueError('规则DOCX签名无效；网站校验页不能作为正文')
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if len(names) > 128 or names.count('word/document.xml') != 1:
            raise ValueError('规则DOCX成员或正文身份无效')
        info = archive.getinfo('word/document.xml')
        # Decode only the document body; never expand ZIP members to disk.
        if info.file_size > 4 * MAX_TEXT_BYTES or info.flag_bits & 1:
            raise ValueError('规则DOCX正文解压上限或加密状态无效')
        xml = archive.read(info)
    if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise ValueError('规则DOCX禁止外部实体')
    root = ElementTree.fromstring(xml)
    return bounded_text('\n'.join(''.join(t.text or '' for t in p.iter(WORD + 't'))
                                  for p in root.iter(WORD + 'p')))


def pdf_document(body):
    # Context-local decoder limits also apply to fonts and nested streams.
    with apply_configuration(
        maximum_declared_stream_length=2 * MAX_TEXT_BYTES,
        array_based_stream_maximum_output_length=4 * MAX_TEXT_BYTES,
        zlib_maximum_output_length=4 * MAX_TEXT_BYTES,
        lzw_maximum_output_length=4 * MAX_TEXT_BYTES,
        run_length_maximum_output_length=4 * MAX_TEXT_BYTES,
        brotli_maximum_output_length=4 * MAX_TEXT_BYTES,
        jbig2_maximum_output_length=4 * MAX_TEXT_BYTES,
        image_maximum_buffer_size=4 * MAX_TEXT_BYTES,
        stream_decoding_work_maximum_length=8 * MAX_TEXT_BYTES,
        page_tree_maximum_entries=160, page_tree_maximum_depth=16,
        xform_maximum_invocations_per_extraction=100, jbig2dec_binary=None,
    ):
        return _pdf_text(body)


def _pdf_text(body):
    if not isinstance(body, bytes) or not body.startswith(b'%PDF-'):
        raise ValueError('规则PDF签名无效；网站校验页不能作为正文')
    reader = PdfReader(io.BytesIO(body), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 80:
        raise ValueError('规则PDF加密或页数无效')
    parts, used = [], 0
    for page in reader.pages:
        # Bound decompressed content before text extraction too.
        content = page.get_contents()
        if content is not None and len(content.get_data()) > 4 * MAX_TEXT_BYTES:
            raise ValueError('规则PDF单页解压正文超过上限')
        value = page.extract_text() or ''
        used += len(value.encode())
        if used > MAX_TEXT_BYTES:
            raise ValueError('规则PDF解码文本超过上限')
        parts.append(re.sub(r'^\s*[—－-]\s*\d+\s*[—－-]\s*$', '', value, flags=re.M))
    return bounded_text('\n'.join(parts))


def numbered_clauses(value):
    """Only line-leading clause headings count; in-text references do not."""
    clauses, current, parts = {}, None, []
    def finish():
        if current is not None:
            text = compact(''.join(parts))
            if not text or len(text) > MAX_CLAUSE_CHARS or current in clauses:
                raise ValueError('规则条款重复、为空或超过上限')
            clauses[current] = text
    for line in bounded_text(value).splitlines():
        match = CLAUSE.match(line.strip())
        if match:
            finish()
            current, parts = match[1], [match[2]]
            if len(clauses) >= MAX_CLAUSES:
                raise ValueError('规则条款集合超过上限')
        elif current is not None:
            parts.append(line)
    finish()
    if not clauses:
        raise ValueError('规则正文未找到条款')
    return clauses


def official_url(base, value, domains):
    url = urljoin(base, value)
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
            or not any(parsed.hostname == d or (parsed.hostname or '').endswith('.' + d)
                       for d in domains) or len(url) > 1000):
        raise ValueError('规则链接不属于声明的官方来源')
    return url


@dataclass(frozen=True)
class RuleDocument:
    issuer: str
    title: str
    url: str
    published: str
    effective: str
    body_hash: str
    clauses: dict

    @classmethod
    def decode(cls, *, issuer, title, url, published, effective, body, format):
        for stamp in (published, effective):
            if date.fromisoformat(stamp).isoformat() != stamp:
                raise ValueError('规则日期格式无效')
        if effective < published:
            raise ValueError('规则生效日早于公布日，须单独核实溯及条款')
        decode = {'docx': docx_document, 'pdf': pdf_document}.get(format)
        if decode is None:
            raise ValueError('规则附件格式不支持')
        return cls(issuer, title, url, published, effective, hashlib.sha256(body).hexdigest(),
                   numbered_clauses(decode(body)))

    def require(self, key, *fragments):
        clause = self.clauses.get(key, '')
        if not clause or any(compact(fragment) not in clause for fragment in fragments):
            raise ValueError(f'{self.issuer}规则{key}缺少必需内容，不能沿用旧参数')
        return clause
