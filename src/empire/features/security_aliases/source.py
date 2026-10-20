"""One complete official BSE mapping table, not inferred numeric aliases."""
from datetime import date
from html.parser import HTMLParser

from empire.features.security_aliases.contract import validate

HEADER = ['序号', '证券简称', '上市日期', '旧代码', '新代码']
NOTE = '由全国股转系统原精选层平移进入北交所的上市公司'


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
