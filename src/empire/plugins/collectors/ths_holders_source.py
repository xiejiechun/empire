"""One HTML response contains every displayed period for each holder section."""
import re
from datetime import date
from decimal import Decimal

from empire.contracts.holders import (
    KINDS,
    digest,
    number,
    quality_flags,
    quantity,
    validate,
    validate_gaps,
)
from empire.plugins.collectors.holder_html import Document, Node


def one(nodes, label):
    if len(nodes) != 1:
        raise ValueError('持有人页面缺少或重复' + label)
    return nodes[0]


def cells(row):
    return [n for n in row.children if isinstance(n, Node) and n.tag in ('th', 'td')]


def change(cell):
    value = cell.text()
    if value in ('不变', '未变'):
        return '0', 'unchanged'
    if value in ('新进', '新增'):
        return None, 'new'
    if value == '退出':
        return None, 'exited'
    if value in ('', '--', '-', '—'):
        return None, 'unknown'
    amount = Decimal(quantity(value, unit='股')[0])
    if cell.find(css='down') or cell.find(css='downcolor'):
        amount = -abs(amount)
    return number(format(amount, 'f'), signed=True), 'numeric'


def parse_table(kind, security, name, period, table, *, today=None):
    header = [n.text() for n in one(table.find('thead'), '表头').find('th')]
    expected = (['序号', '持有人名称', '持有数量(万张)', '持有比例(%)'] if kind == 'bond_holders' else
        ['机构或基金名称', '持有数量(股)', '持股变化(股)',
         '占流通股比例' if kind == 'float_holders' else '占总股本比例',
         '变动比例' if kind == 'float_holders' else '实际增减持', '股份类型', '持股详情'])
    base_header = [h for h in header if h != '质押占其直接持股比']
    if base_header != expected or len(set(header)) != len(header):
        raise ValueError('持有人表头或单位发生变化：' + str(header))
    indexes = {h: i for i, h in enumerate(header)}
    caption = one(table.find('caption'), '数量汇总')
    notice = caption.text() == '主要股东持股变动公告'
    summary = caption.find('em')
    if not notice:
        # A source dash can lack <em>; identify the two caption slots by labels.
        summary_match = re.search(r'累计持有(?:A、H流通股)?[：:]\s*(.+?)[，,]\s*累计(?:占.+?比|持有比例)[：:]\s*([^，, ]+)', caption.text())
        if not summary_match:
            raise ValueError('持有人来源汇总缺失：' + caption.text()[:300])
        summary = [summary_match[1].strip(), summary_match[2].strip()]
    unit = '张' if kind == 'bond_holders' else '股'
    missing = ('-', '--', '—', '')
    total = (None, None, None) if notice or summary[0] in missing else quantity(summary[0], scale=10000 if kind == 'bond_holders' else 1, unit=unit)
    basis = re.search(r'累计占(.+?)比', caption.text())
    report = dict(kind=kind, unified_code=security, instrument_key=digest(name), instrument_name=name,
        report_type='change_notice' if notice else 'periodic',
        report_date=period, total_quantity=total[0], total_quantity_scale=total[1],
        total_quantity_decimals=total[2], total_ratio=None if notice or summary[1] in missing else number(summary[1].rstrip('%'), ratio=True, total=True),
        ratio_basis='债券持有比例' if kind == 'bond_holders' else (header[3] if notice else basis[1] if basis else ''), members=[])
    group, counters = 'current', {'current': 0, 'exited': 0}
    bodies = [n for n in table.find('tbody') if n.find('tr')]
    if not bodies:
        raise ValueError('持有人名单缺失')
    for tr in [tr for body in bodies for tr in body.find('tr')]:
        cs = cells(tr)
        if 'm_th' in tr.attrs.get('class', '').split():
            if group == 'exited' or len(cs) != 1 or '退出前十大' not in cs[0].text():
                raise ValueError('退出名单分界无效')
            group = 'exited'
            continue
        if len(cs) != len(header):
            raise ValueError('持有人行列数量不符')
        if ('gray' in tr.attrs.get('class', '').split()) != (group == 'exited'):
            raise ValueError('退出名单归属不符')
        counters[group] += 1
        bond = kind == 'bond_holders'
        holder = cs[1] if bond else cs[0]
        source_quantity = cs[2 if bond else 1].text()
        q = ((None, None, None) if source_quantity in missing else
             quantity(source_quantity, scale=10000 if bond else 1, unit=unit))
        linked = [a.attrs['orgid'] for a in holder.find('a') if a.attrs.get('orgid')]
        amount, label = (None, None) if bond else change(cs[2])
        pledge = cs[indexes['质押占其直接持股比']].text() if '质押占其直接持股比' in indexes else None
        pledge_pct = number(pledge.rstrip('%'), ratio=True) if pledge and pledge.endswith('%') else None
        if pledge not in (None, '', '无质押', '-', '--') and pledge_pct is None:
            raise ValueError('质押信息结构无效')
        report['members'].append(dict(member_group=group, seq=counters[group],
            source_rank=int(cs[0].text()) if bond else None,
            holder_name=holder.text(), holder_id=linked[0] if linked else None, quantity=q[0],
            quantity_scale=q[1], quantity_decimals=q[2], ratio=None if cs[3].text() in missing else number(cs[3].text().rstrip('%'), ratio=True),
            change_quantity=amount, change_label=label,
            actual_change=cs[indexes[expected[4]]].text() or None if not bond else None,
            share_type=cs[indexes['股份类型']].text() or None if not bond else None,
            pledge_ratio=pledge_pct, pledge_status=pledge or None))
    report['quality_flags'] = quality_flags(report, today=today)
    return report


def parse(body, kind, stock, today=None, *, gaps=None):
    try:
        return parse_sections(body, kind, stock, today=today, gaps=gaps)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        message = str(exc)
        category = ('required_quantity_missing' if message.startswith('持有数量或单位无效：') and message.split('：')[-1] in ('-', '--', '—', '') else
                    'report_date_invalid' if '报告日期' in message else
                    'instrument_identity_invalid' if '标的身份' in message else 'source_structure_invalid')
        exc.holder_metadata = {'kind': kind, **getattr(exc, 'holder_metadata', {}), 'error_type': category,
                               'requested_kind': kind, 'unified_code': stock['unified_code']}
        raise


def parse_sections(body, kind, stock, today=None, *, gaps=None):
    source = body.decode('gb18030') if isinstance(body, bytes) else body
    if '</html>' not in source.lower():
        raise ValueError('持有人响应截断或验证页')
    root = Document(source).root
    identity = one([n for n in root.find('input') if n.attrs.get('id') == 'stockCode'], '股票代码')
    if identity.attrs.get('value') != stock['code']:
        raise ValueError('持有人响应股票身份不符')
    sections = [n for n in root.find('div') if n.attrs.get('id') == KINDS[kind][1]]
    if not sections and kind in ('float_holders', 'bond_holders'):
        ids = {n.attrs.get('id') for n in root.find('div')}
        # Newly published stock pages can omit the whole float/bond section.
        # Their complete profile still contains the shareholder-count block,
        # the top-holder reports and the following concentration block.
        complete_profile = {'holdernum', 'tenholder', 'holdlevel'} <= ids
        established_profile = kind == 'bond_holders' and {'flowholder', 'tenholder'} <= ids
        if root.find('a', KINDS[kind][2]) or re.search(r'id\s*=\s*[\'"]' + KINDS[kind][1] + r'[\'"]', source) or not (complete_profile or established_profile):
            raise ValueError('持有人栏目缺失但来源结构不能证明未提供')
        # A missing required top-holder report is not an empty availability state.
        if complete_profile:
            parse(body, 'top_holders', stock, today=today)
        return []
    section = one(sections, '业务栏目')
    tabs = section.find('a', KINDS[kind][2])
    if len(tabs) > 100:
        raise ValueError('持有人报告窗口超限')
    if not tabs:
        if section.find('table') or not re.search(r'暂无(?:相关)?数据|无相关数据', section.text()):
            raise ValueError('持有人栏目空但无有效来源证明')
        return []
    panels = [n for n in section.find('div') if 'm_tab_content2' in n.attrs.get('class', '').split()]
    if {n.attrs.get('id') for n in panels} != {a.attrs.get('targ') for a in tabs} or len(panels) != len(tabs):
        raise ValueError('报告期标签与正文集合不符')
    security = stock['unified_code']
    reports = []
    for tab in tabs:
        panel = one([n for n in panels if n.attrs.get('id') == tab.attrs.get('targ')], '报告期正文')
        name = security
        if kind == 'bond_holders':
            # Find the nearest business block containing this panel and its bond name.
            blocks = [n for n in section.find('div', 'bd') if panel in n.find('div')]
            block = one(blocks, '债券业务块')
            name_node = one(block.find('div', 'sec'), '债券名称')
            name = one(name_node.find('span'), '债券名称正文').text()
        try:
            report = parse_table(kind, security, name, tab.text(), one(panel.find('table'), '报告表格'),
                                 today=today or date.today())
            unidentified = kind == 'bond_holders' and name == '' and gaps is not None
            validate(kind, security, [report], today=today or date.today(), allow_unidentified=unidentified)
        except (ValueError, TypeError, KeyError) as exc:
            exc.holder_metadata = dict(report_date=tab.text(), instrument_name=name)
            raise
        if unidentified:
            gaps.append(dict(kind=kind, report_date=tab.text(), source_panel=tab.attrs['targ'],
                             reason='instrument_name_missing'))
            validate_gaps(gaps)
        else:
            reports.append(report)
    reports.sort(key=lambda r: (r['report_date'], r['instrument_key'], r['report_type']))
    return validate(kind, security, reports, today=today or date.today())
