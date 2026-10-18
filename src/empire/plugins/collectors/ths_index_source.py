"""Complete source catalogue and streaming complete member response validation."""
import re
from html.parser import HTMLParser

from empire.contracts.indices import INDEX_LIMIT, MEMBER_LIMIT, index_code, label, security_code
from empire.plugins.collectors.ths_industry_source import Document, one


def parse_catalog(source):
    if '</html>' not in source.lower():
        raise ValueError('指数目录响应截断')
    root = Document(source).root
    groups = one(root.find(css='cate_inner'), '指数目录').find(css='cate_group')
    result, seen = [], set()
    for group in groups:
        category = label(one(group.find(css='cate_letter'), '目录分组').text(), 40)
        anchors = one(group.find(css='cate_items'), '目录成员').find('a')
        if not anchors:
            raise ValueError('指数目录分组为空')
        for anchor in anchors:
            match = re.fullmatch(r'https?://q\.10jqka\.com\.cn/zs/detail/code/([0-9A-Z]{6})/',
                                 anchor.attrs.get('href', ''))
            if not match or match[1] in seen:
                raise ValueError('指数目录链接无效或编号重复')
            seen.add(match[1])
            result.append(dict(code=index_code(match[1]), name=label(anchor.text()), group=category))
    if not 1 <= len(result) <= INDEX_LIMIT:
        raise ValueError('指数目录为空或超过上限')
    return sorted(result, key=lambda row: row['code'])


class MemberParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.table = self.body = self.row = self.cell = self.pager = False
        self.tables = self.closed = self.pagers = self.identities = self.bases = 0
        self.identity = self.base = None
        self.cells, self.links, self.rows, self.parts, self.anchors = [], [], [], [], []
        self.unavailable = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        css = attrs.get('class', '').split()
        if tag == 'table' and 'm-table' in css:
            self.tables += 1
            self.table = True
        elif tag == 'tbody' and self.table:
            self.body = True
        elif tag == 'tr' and self.body:
            if self.row:
                raise ValueError('指数成员行未闭合')
            self.row, self.cells, self.links = True, [], []
        elif tag == 'td' and self.row:
            if self.cell:
                raise ValueError('指数成员字段未闭合')
            self.cell, self.parts, self.anchors = True, [], []
            self.colspan = attrs.get('colspan')
        elif tag == 'a' and self.cell:
            self.anchors.append(attrs.get('href', ''))
        elif tag == 'div' and 'm-pager' in css:
            self.pagers += 1
            self.pager = True
        elif self.pager:
            raise ValueError('指数完整响应仍有分页')
        elif tag == 'input' and attrs.get('id') == 'requestQuery':
            self.identities += 1
            self.identity = attrs.get('value')
        elif tag == 'input' and attrs.get('id') == 'baseUrl':
            self.bases += 1
            self.base = attrs.get('value')

    def handle_data(self, data):
        if self.cell:
            self.parts.append(data)
        if self.pager and data.strip():
            raise ValueError('指数完整响应仍有分页')

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell:
            self.cells.append(''.join(self.parts).strip())
            self.links.append(self.anchors)
            self.cell = False
        elif tag == 'tr' and self.row:
            if self.cell:
                raise ValueError('指数成员字段截断')
            if self.cells == ['暂无成份股数据'] and self.colspan == '14' and not self.rows and not self.unavailable:
                self.unavailable = True
            else:
                if self.unavailable or len(self.cells) != 14 or self.cells[0] != str(len(self.rows) + 1):
                    raise ValueError('指数成员字段或连续序号无效')
                code, name = security_code(self.cells[1]), label(self.cells[2])
                for links in self.links[1:3]:
                    if len(links) != 1 or not re.fullmatch(
                            r'https?://stockpage\.10jqka\.com\.cn/' + code + '/?', links[0]):
                        raise ValueError('指数证券链接与编号不一致')
                if self.rows and code <= self.rows[-1][0]:
                    raise ValueError('指数成员重复或未严格排序')
                self.rows.append([code, name])
                if len(self.rows) >= MEMBER_LIMIT:
                    raise ValueError('指数成员达到请求上限，无法证明完整')
            self.row = False
        elif tag == 'tbody' and self.body:
            if self.row:
                raise ValueError('指数成员正文截断')
            self.body = False
        elif tag == 'table' and self.table:
            self.closed += 1
            self.table = False
        elif tag == 'div' and self.pager:
            self.pager = False


def parse_members(source, code):
    if 'upass.10jqka.com.cn/login' in source:
        raise ValueError('同花顺要求登录；不能读取指数成员')
    parser = MemberParser()
    parser.feed(source)
    parser.close()
    if (parser.tables != 1 or parser.closed != 1 or parser.body or parser.row or parser.cell
            or parser.pagers != 1 or parser.pager or parser.identities != 1 or parser.bases != 1
            or parser.identity != 'code/' + index_code(code) or parser.base != 'zs/detail'
            or not (parser.rows or parser.unavailable)):
        raise ValueError('指数响应缺少完整单页或请求身份证明')
    return dict(available=not parser.unavailable, members=parser.rows)
