"""One complete official BSE mapping table, not inferred numeric aliases."""
import re
from datetime import date
from html.parser import HTMLParser

URL = 'https://www.bse.cn/service/code_mapping.html'
HEADER = ['序号', '证券简称', '上市日期', '旧代码', '新代码']
NOTE = '由全国股转系统原精选层平移进入北交所的上市公司'
LIMIT = 1000


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.rows, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            if self.rows is not None:
                raise ValueError('北交所映射表出现嵌套表格')
            self.rows = []
        elif self.rows is not None and tag == 'tr':
            self.row = []
        elif self.row is not None and tag in ('td', 'th'):
            self.cell = ''

    def handle_data(self, text):
        if self.cell is not None:
            self.cell += text

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == 'table' and self.rows is not None:
            self.tables.append(self.rows)
            self.rows = None


def validate(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= LIMIT:
        raise ValueError('北交所映射数量超限或为空')
    legacy, current = set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'legacy_code', 'unified_code', 'name', 'listing_date'}:
            raise ValueError('北交所映射字段改变')
        old, new = row['legacy_code'], row['unified_code']
        if not isinstance(old, str) or not re.fullmatch('[48][0-9]{5}', old):
            raise ValueError('北交所旧代码无效')
        if not isinstance(new, str) or not re.fullmatch(r'920[0-9]{3}\.BJ', new):
            raise ValueError('北交所新代码无效')
        if old in legacy or new in current:
            raise ValueError('北交所映射业务集合重复或冲突')
        legacy.add(old)
        current.add(new)
        if not isinstance(row['name'], str) or not 1 <= len(row['name']) <= 100 or row['name'] != row['name'].strip():
            raise ValueError('北交所证券名称无效')
        listed = date.fromisoformat(row['listing_date'])
        if listed.isoformat() != row['listing_date'] or not date(2000, 1, 1) <= listed <= date(2024, 4, 21):
            raise ValueError('北交所存量换码上市日期无效')


def parse(body):
    parser = TableParser()
    parser.feed(body.decode('utf8'))
    tables = [table for table in parser.tables if table and table[0] == HEADER]
    if len(tables) != 1 or parser.rows is not None:
        raise ValueError('北交所映射表头缺失、重复或响应不完整')
    table = tables[0]
    if len(table[-1]) != 1 or NOTE not in table[-1][0]:
        raise ValueError('北交所映射表末尾口径证明缺失')
    rows = []
    for seq, cells in enumerate(table[1:-1], 1):
        if len(cells) != 5 or cells[0] != str(seq):
            raise ValueError('北交所映射来源序号缺失、重复或乱序')
        parts = cells[2].split('/')
        if len(parts) != 3:
            raise ValueError('北交所映射日期格式改变')
        listed = date(*(int(value) for value in parts)).isoformat()
        rows.append(dict(legacy_code=cells[3], unified_code=cells[4] + '.BJ', name=cells[1], listing_date=listed))
    validate(rows)
    return sorted(rows, key=lambda row: row['legacy_code'])
