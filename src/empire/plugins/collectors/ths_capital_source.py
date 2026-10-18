"""Complete response parsing, including hidden details, periods and releases."""
import re
from datetime import date

from empire.contracts.ths_capital import (
    CURRENCIES,
    FUTURE_ANNOUNCEMENT,
    MISSING,
    SECTIONS,
    SPECS,
    TABLES,
    identify,
    numeric,
    validate,
)
from empire.plugins.collectors.holder_html import Document, Node

HEADERS = {
    'capital_funding': ['公告日期', '发行类别', '发行起始日期', '实际募集资金净额(元)', '剩余募集资金截止时间', '剩余募集资金(元)', '募集资金使用率'],
    'capital_project': ['公告日期', '项目名称', '承诺使用募集资金(元)', '已投入募集资金(元)', '建设期(年)', '税后收益率', '预测年新增净利润(元)', '项目简介'],
    'capital_equity_summary': ['投资类型', '所持个数', '累计初始投资额(元)', '累计期末面值(元)', '截止本季度盈亏(元)', '业绩影响'],
    'capital_equity_position': ['分类', '所持对象', '投资类型', '持股数量(股)', '持股比例', '综合盈亏(元)'],
    'capital_ipo': ['所持IPO对象', '持股占比(%)', '初始投资成本(万)', '审核进度', '所持对象所属行业', '所持对象最新每股收益(元)'],
}


def one(nodes, label):
    if len(nodes) != 1:
        raise ValueError('资本运作缺少或重复' + label)
    return nodes[0]


def nullable(value):
    return None if value.strip() in MISSING else value.strip()


def day(value):
    value = nullable(value)
    if value is not None and date.fromisoformat(value).isoformat() != value:
        raise ValueError('资本运作日期格式无效')
    return value


def row_cells(row):
    return [c for c in row.children if isinstance(c, Node) and c.tag in ('th', 'td')]


def table_rows(node):
    result = []
    for child in node.children:
        if isinstance(child, Node) and child.tag != 'table':
            if child.tag == 'tr':
                result.append(child)
            else:
                result.extend(table_rows(child))
    return result


def tabular(table, kind):
    header = one(table.find('thead'), '表头')
    if [c.text() for c in header.find('th')] != HEADERS[kind]:
        raise ValueError('资本运作表头/单位变化：' + header.text())
    body = one(table.find('tbody'), '表体')
    rows, category, remaining = [], None, 0
    for tr in table_rows(body):
        cells = row_cells(tr)
        if kind == 'capital_equity_position':
            if cells and cells[0].tag == 'th':
                if remaining:
                    raise ValueError('投资分类rowspan交叉')
                category = cells[0]
                remaining = int(category.attrs.get('rowspan', '1'))
                cells = cells[1:]
            if category is None or remaining < 1:
                raise ValueError('投资持仓缺少分类跨度')
            cells = [category, *cells]
            remaining -= 1
        if len(cells) != len(HEADERS[kind]):
            raise ValueError('资本运作行宽/明细缺失：' + tr.text()[:100])
        rows.append(cells)
    if remaining:
        raise ValueError('投资分类明细被截断')
    return rows


def fresh(table, unit, section, event_date=None):
    return dict(unified_code=unit, section=section, event_date=event_date,
                **{key: False if kind == 'bool' else None for key, (_, kind) in SPECS[table].items()})


def labels(table):
    values = []
    for tr in table_rows(table):
        for td in row_cells(tr):
            spans = [c for c in td.children if isinstance(c, Node) and c.tag == 'span']
            if not spans:
                # Transfer's description sits in a wrapping div.
                spans = td.find('span')
            if not spans:
                raise ValueError('资本运作明细单元缺少字段标签')
            label = spans[0].text().rstrip('：:')
            value = td.text()
            prefix = spans[0].text()
            if not value.startswith(prefix):
                raise ValueError('资本运作标签与正文不符')
            value = value[len(prefix):].strip()
            if label == '交易简介' and td.find(css='rp_tipbox'):
                detail = one(td.find(css='rp_tipbox'), '交易详情')
                value = one(detail.find('tbody'), '交易详情正文').text()
            values.append((label, value))
    return values


def simple(table, target, unit, section):
    result = []
    for cells in tabular(table, target):
        texts = [c.text() for c in cells]
        row = fresh(target, unit, section)
        if target in ('capital_funding', 'capital_project'):
            row['event_date'] = day(texts[0])
            texts = texts[1:]
        keys = list(SPECS[target])
        if target == 'capital_funding':
            for k, v in zip(keys, texts, strict=True):
                row[k] = day(v) if k in ('issue_start', 'balance_date') else nullable(v) if k == 'issue_type' else numeric(v)
        elif target == 'capital_project':
            for k, v in zip(keys, texts, strict=True):
                row[k] = nullable(v) if k in ('project_name', 'description') else numeric(v)
            links = cells[-1].find('a')
            if links:
                link = one(links, '项目简介')
                if 'content' not in link.attrs:
                    raise ValueError('项目简介展开内容缺失')
                row['description'] = nullable(Document(re.sub(r'<br\s*/?>', ' ', link.attrs['content'], flags=re.I)).root.text())
        elif target == 'capital_ipo':
            for k, v in zip(keys, texts, strict=True):
                row[k] = nullable(v) if k in ('target', 'status', 'industry') else numeric(v, scale=10000 if k == 'initial_amount' else 1)
        result.append(row)
    return result


def investments(box, unit, rows):
    tabs = box.find('a', css='fdates')
    periods = {a.attrs.get('targ'): day(a.text()) for a in tabs}
    contents = box.find(css='m_tab_content')
    if len(periods) != len(tabs) or set(periods) != {c.attrs.get('id') for c in contents} or not periods:
        raise ValueError('股权投资期间/明细集合不符')
    for content in contents:
        stamp = periods[content.attrs['id']]
        if stamp is None:
            raise ValueError('投资报告期缺失')
        tables = content.find('table')
        if len(tables) != 2:
            raise ValueError('股权投资汇总/持仓表缺失')
        for target, table in zip(('capital_equity_summary', 'capital_equity_position'), tables, strict=True):
            for cells in tabular(table, target):
                row = fresh(target, unit, 'invest', stamp)
                keys = [k for k in SPECS[target] if not k.endswith('_estimated')]
                for k, cell in zip(keys, cells, strict=True):
                    value = cell.text()
                    kind = SPECS[target][k][1]
                    row[k] = numeric(value) if kind == 'num' else int(value) if kind == 'int' else nullable(value)
                    if k + '_estimated' in row:
                        row[k + '_estimated'] = '(估)' in value or '（估）' in value
                rows[target].append(row)


def transactions(box, unit, section):
    mapping = dict(公告日期='event_date', 交易标的='target', 买方='buyer', 受让方='buyer', 卖方='seller', 出让方='seller',
        交易方='counterparty', 交易金额='amount', 交易进度='status', 转让比例='transfer_ratio', 支付方式='payment',
        交易方式='method', 关联关系='relationship', 交易概述='description', 交易简介='description', 交易影响='impact')
    result = []
    tables = box.find('table', css='capital')
    # Nested detail tables belong to an event; unknown outer tables cannot
    # silently become an empty transaction set.
    def outer_tables(node):
        return [table for child in node.children if isinstance(child, Node)
                for table in ([child] if child.tag == 'table' else outer_tables(child))]
    if not tables or set(tables) != set(outer_tables(box)):
        raise ValueError('交易事件表结构变化/缺失')
    for table in tables:
        row, seen = fresh('capital_transaction', unit, section), set()
        for label, value in labels(table):
            if label not in mapping or mapping[label] in seen:
                raise ValueError('交易字段变化/重复：' + label)
            key = mapping[label]
            seen.add(key)
            row[key] = day(value) if key == 'event_date' else numeric(value) if key in ('amount', 'transfer_ratio') else nullable(value)
            if key == 'amount' and row[key] is not None:
                row['currency'] = next((c for c in CURRENCIES if c in value), '人民币')
        if not {'event_date', 'amount', 'description'} <= seen or row['event_date'] is None:
            raise ValueError('交易公告/金额/详情结构缺失')
        result.append(row)
    return result


def encumbrances(box, unit, section, rows):
    root = one([n for n in box.find() if n.attrs.get('id') == ('ml_006' if section == 'pledge' else 'ml_007')], '质押/冻结子栏目')
    tables = root.find('table')
    if not tables:
        tip = one(root.find(css='no_tip'), '质押/冻结空提示').text()
        if not ('无' in tip or '暂无' in tip):
            raise ValueError('质押/冻结空提示未知')
        return tip
    parent_groups = []
    for table in tables:
        row = fresh('capital_encumbrance', unit, section)
        releases, current, seen = [], None, set()
        for label, value in labels(table):
            if label in ('解押公告日期', '解冻公告日期'):
                current = fresh('capital_release', unit, section, day(value))
                releases.append(current)
                continue
            mapping = {'质押公告日期': 'event_date', '冻结公告日期': 'event_date',
                '原始质押股数': 'quantity', '原始冻结股数': 'quantity', '出质人': 'holder', '股东': 'holder',
                '质权人': 'institution', '执行冻结机构': 'institution', '质押相关说明': 'description', '冻结相关说明': 'description',
                '本次解押股数': 'quantity', '本次解冻股数': 'quantity', '实际解押日期': 'actual_date', '实际解冻日期': 'actual_date',
                '解押相关说明': 'description', '解冻相关说明': 'description'}
            if label in ('预计质押期限', '预计冻结期限'):
                parts = value.split('至')
                if len(parts) != 2:
                    raise ValueError('质押/冻结预计期限格式变化')
                row['start_date'], row['end_date'] = map(day, parts)
            elif label in mapping:
                dest = current if label.startswith(('本次', '实际', '解押相关', '解冻相关')) else row
                if dest is None:
                    raise ValueError('解除字段缺少公告关联')
                key = mapping[label]
                token = (id(dest), key)
                if token in seen:
                    raise ValueError('质押/冻结字段重复')
                seen.add(token)
                dest[key] = day(value) if key in ('event_date', 'actual_date') else numeric(value) if key == 'quantity' else nullable(value)
            else:
                raise ValueError('质押/冻结字段变化：' + label)
        if row['event_date'] is None or not row['holder'] or (id(row), 'quantity') not in seen:
            raise ValueError('原事件公告/主体/数量缺失')
        if any((id(child), 'quantity') not in seen for child in releases):
            raise ValueError('解除明细缺少股数字段标签')
        parent_groups.append((row, releases))
    # Include release content when sorting ambiguous parallel source records.
    ordered = sorted(parent_groups, key=lambda pair: (str(pair[0]), str(pair[1])))
    parents = identify('capital_encumbrance', [p for p, _ in ordered])
    buckets = {}
    for parent in parents:
        buckets.setdefault(tuple((k, v) for k, v in parent.items() if k != 'record_key'), []).append(parent)
    for raw, children in ordered:
        parent = buckets[tuple(raw.items())].pop(0)
        rows['capital_encumbrance'].append(parent)
        for child in children:
            child['parent_key'] = parent['record_key']
            rows['capital_release'].append(child)
    return 'available'


def parse(body, stock, today=None):
    source = body.decode('gb18030')
    if not re.search(r'</html\s*>\s*$', source, re.I) or 'F10 Content End' not in source:
        raise ValueError('资本运作响应不完整')
    root = Document(source).root
    codes = [n.attrs.get('value') for n in root.find('input') if n.attrs.get('id') == 'stockCode']
    if codes != [stock['code']]:
        raise ValueError('资本运作页面证券身份不符')
    boxes = root.find(css='m_box')
    unknown = [b.attrs.get('id') for b in boxes if b.find('h2') and b.attrs.get('id') not in {'raise', 'progress', 'asset', 'invest', 'ipo', 'transfer', 'connect', 'freeze'}]
    if unknown:
        raise ValueError('资本运作新增未知栏目：' + str(unknown))
    rows, availability = {t: [] for t in TABLES}, {}
    for section, title in SECTIONS.items():
        ident = 'raise' if section == 'raise_' else 'freeze' if section == 'pledge' else section
        found = [b for b in boxes if b.attrs.get('id') == ident]
        if not found:
            if ident in ('raise', 'progress', 'invest'):
                raise ValueError('资本运作基础栏目缺失：' + ident)
            availability[section] = 'source_not_provided'
            continue
        box = one(found, title)
        if one(box.find('h2'), '栏目标题').text() != ('质押解冻' if section in ('pledge', 'freeze') else title):
            raise ValueError('资本运作栏目标题变化')
        if section in ('pledge', 'freeze'):
            availability[section] = encumbrances(box, stock['unified_code'], section, rows)
            continue
        if not box.find('table'):
            tips = box.find(css='no_tip')
            tip = one(tips, '栏目空提示').text() if tips else box.text().removeprefix(title).strip()
            if '暂无' not in tip and '无' not in tip:
                raise ValueError('资本运作未知空状态')
            availability[section] = tip
            continue
        availability[section] = 'available'
        if section in ('raise_', 'progress', 'ipo'):
            target = {'raise_': 'capital_funding', 'progress': 'capital_project', 'ipo': 'capital_ipo'}[section]
            rows[target] = simple(one(box.find('table'), '栏目表格'), target, stock['unified_code'], section)
        elif section == 'invest':
            investments(box, stock['unified_code'], rows)
        else:
            rows['capital_transaction'].extend(transactions(box, stock['unified_code'], section))
    for table in TABLES:
        if table != 'capital_encumbrance':
            rows[table] = identify(table, rows[table])
        else:
            rows[table].sort(key=lambda row: row['record_key'])
    if today:
        for table, records in rows.items():
            if table not in ('capital_equity_summary', 'capital_equity_position'):
                for row in records:
                    if row['event_date'] and date.fromisoformat(row['event_date']) > today:
                        availability[row['section']] = FUTURE_ANNOUNCEMENT
    validate(stock['unified_code'], rows, availability, today=today)
    return dict(rows=rows, availability=availability)
