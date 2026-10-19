"""Streaming identity-only parser for the complete THS stock directory response."""
import json
import re
from html.parser import HTMLParser

from empire.features.industries.contract import market
from empire.features.stocks.dataset import normalize_row

URL = 'https://q.10jqka.com.cn/index/index/board/all/field/zdf/order/desc/page/1/size/10000/ajax/1/'
REQUEST = {'board': 'all', 'field': 'zdf', 'order': 'desc', 'page': '1', 'size': '10000', 'ajax': '1'}


class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.table = self.body = self.row = self.cell = self.pager = False
        self.cells, self.links, self.rows, self.codes = [], [], [], set()
        self.text, self.anchors = [], []
        self.tables = self.closed = self.pagers = self.requests = 0
        self.request = self.base = None

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
                raise ValueError('同花顺股票行未闭合')
            self.row, self.cells, self.links = True, [], []
        elif tag == 'td' and self.row:
            if self.cell:
                raise ValueError('同花顺股票字段未闭合')
            self.cell, self.text, self.anchors = True, [], []
        elif tag == 'a' and self.cell:
            self.anchors.append(attrs.get('href'))
        elif tag == 'div' and 'm-pager' in css:
            self.pagers += 1
            self.pager = True
        elif self.pager:
            raise ValueError('同花顺完整响应仍有分页')
        elif tag == 'input' and attrs.get('id') == 'request':
            self.requests += 1
            self.request = json.loads(attrs.get('value', ''))
        elif tag == 'input' and attrs.get('id') == 'baseUrl':
            self.base = attrs.get('value')

    def handle_data(self, data):
        if self.cell:
            self.text.append(data)
        if self.pager and data.strip():
            raise ValueError('同花顺完整响应仍有分页')

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell:
            self.cells.append(''.join(self.text).strip())
            self.links.append(self.anchors)
            self.cell = False
        elif tag == 'tr' and self.row:
            if self.cell or len(self.cells) != 14 or self.cells[0] != str(len(self.rows) + 1):
                raise ValueError('同花顺股票字段或连续序号无效')
            code, label = self.cells[1:3]
            venue = market(code)
            for anchors in self.links[1:3]:
                if len(anchors) != 1 or not re.fullmatch(r'https?://stockpage\.10jqka\.com\.cn/' + code + '/?', anchors[0] or ''):
                    raise ValueError('同花顺证券链接与代码不一致')
            if code in self.codes or len(self.rows) >= 9999:
                raise ValueError('同花顺股票身份重复或达到请求上限')
            self.codes.add(code)
            self.rows.append(normalize_row({'code': code, 'symbol': venue.lower() + code, 'name': label}))
            self.row = False
        elif tag == 'tbody' and self.body:
            if self.row:
                raise ValueError('同花顺股票响应截断')
            self.body = False
        elif tag == 'table' and self.table:
            self.closed += 1
            self.table = False
        elif tag == 'div' and self.pager:
            self.pager = False


def parse_directory(source):
    parser = DirectoryParser()
    parser.feed(source)
    parser.close()
    if (parser.tables != 1 or parser.closed != 1 or parser.body or parser.row or parser.cell
            or parser.pagers != 1 or parser.pager or parser.requests != 1
            or parser.request != REQUEST or parser.base != 'index/index' or not parser.rows):
        raise ValueError('同花顺股票响应缺少完整单页或请求身份证明')
    return sorted(parser.rows, key=lambda row: row['source_symbol'], reverse=True)
