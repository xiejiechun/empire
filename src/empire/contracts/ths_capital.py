"""Typed source facts for the complete capital.html response; no business JSON."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal

PROJECT, JOB, DATASET = 'ths-capital', 'ths-capital-v1', 'ths.capital.security'
SECTIONS = dict(raise_='募集资金来源', progress='项目投资', asset='收购兼并', invest='股权投资',
                ipo='参股IPO', transfer='股权转让', connect='关联交易', pledge='股份质押', freeze='股份冻结')
# field -> (display label, wire/SQL type). All numbers use DECIMAL(28,6).
SPECS = {
    'capital_funding': dict(issue_type=('发行类别', 's100'), issue_start=('发行起始日期', 'date'),
        net_amount=('实际募集资金净额(元)', 'num'), balance_date=('剩余募集资金截止时间', 'date'),
        balance_amount=('剩余募集资金(元)', 'num'), usage_ratio=('募集资金使用率', 'num')),
    'capital_project': dict(project_name=('项目名称', 's1000'), committed_amount=('承诺使用募集资金(元)', 'num'),
        invested_amount=('已投入募集资金(元)', 'num'), duration_years=('建设期(年)', 'num'),
        return_ratio=('税后收益率', 'num'), predicted_profit=('预测年新增净利润(元)', 'num'),
        description=('项目简介', 'text')),
    'capital_transaction': dict(target=('交易标的', 's2000'), buyer=('买方/受让方', 's4000'),
        seller=('卖方/出让方', 's4000'), counterparty=('交易方', 's4000'), amount=('交易金额', 'num'),
        currency=('金额币种', 's40'), status=('交易进度', 's100'), transfer_ratio=('转让比例', 'num'),
        payment=('支付方式', 's200'), method=('交易方式', 's2000'), relationship=('关联关系', 's2000'),
        description=('交易概述/简介', 'text'), impact=('交易影响', 'text')),
    'capital_equity_summary': dict(investment_type=('投资类型', 's200'), holding_count=('所持个数', 'int'),
        initial_amount=('累计初始投资额(元)', 'num'), final_amount=('累计期末面值(元)', 'num'),
        profit=('截止本季度盈亏(元)', 'num'), profit_estimated=('盈亏为估算', 'bool'), impact=('业绩影响', 's1000')),
    'capital_equity_position': dict(category=('分类', 's100'), target=('所持对象', 's1000'),
        investment_type=('投资类型', 's200'), quantity=('持股数量(股)', 'num'),
        quantity_estimated=('数量为估算', 'bool'), ratio=('持股比例', 'num'), profit=('综合盈亏(元)', 'num')),
    'capital_ipo': dict(target=('所持IPO对象', 's1000'), ratio=('持股占比(%)', 'num'),
        initial_amount=('初始投资成本(元)', 'num'), status=('审核进度', 's200'),
        industry=('所持对象所属行业', 's500'), eps=('所持对象最新每股收益(元)', 'num')),
    'capital_encumbrance': dict(holder=('股东/出质人', 's1000'), institution=('质权人/执行冻结机构', 's2000'),
        quantity=('原始股数', 'num'), start_date=('预计期限起始日', 'date'), end_date=('预计期限截止日', 'date'),
        description=('质押/冻结相关说明', 'text')),
    'capital_release': dict(parent_key=('原事件键', 'key'), quantity=('本次解除股数', 'num'),
        actual_date=('实际解除日期', 'date'), description=('解除相关说明', 'text')),
}
TABLES = tuple(SPECS)
REQUIREMENTS = dict(raise_='capital_funding', progress='capital_projects', asset='capital_acquisitions',
                    invest='equity_investments', ipo='ipo_investments', transfer='equity_transfers',
                    connect='related_transactions', pledge='pledge', freeze='freeze')
ANCHORS = dict(capital_funding=('issue_type', 'issue_start'), capital_project=('project_name',),
    capital_transaction=('target', 'buyer', 'seller', 'counterparty', 'method'),
    capital_equity_summary=('investment_type',), capital_equity_position=('category', 'target', 'investment_type'),
    capital_ipo=('target',), capital_encumbrance=('holder', 'institution', 'start_date', 'quantity'),
    capital_release=('parent_key', 'actual_date', 'quantity'))
TABLE_SECTIONS = dict(capital_funding=('raise_',), capital_project=('progress',),
    capital_transaction=('asset', 'transfer', 'connect'), capital_equity_summary=('invest',),
    capital_equity_position=('invest',), capital_ipo=('ipo',), capital_encumbrance=('pledge', 'freeze'),
    capital_release=('pledge', 'freeze'))
BASE = dict(record_key=('记录键', 'key'), unified_code=('股票', 'security'), section=('栏目', 's20'),
            event_date=('公告日/报告期', 'date'))
MISSING = {'', '-', '--', '—', '暂无数据', '未公布', '未公布%'}
FUTURE_ANNOUNCEMENT = 'available;source_announcement_after_observation'
# Explicit denomination vocabulary, shared by parsing and attribution. Keep the
# source denomination, including aliases; do not infer a currency or convert FX.
# Longest first also makes attribution unambiguous for overlapping names.
CURRENCIES = tuple(sorted((
    '人民币', '美元', '港元', '港币', '澳门元', '澳门币', '新台币', '台币',
    '欧元', '英镑', '瑞士法郎', '瑞郎', '日元', '日圆', '韩元', '韩币',
    '加拿大元', '加元', '澳大利亚元', '澳元', '新西兰元', '纽元', '新加坡元', '新加坡币',
    '泰铢', '越南盾', '印度尼西亚卢比', '印尼卢比', '印尼盾',
    '马来西亚林吉特', '林吉特', '马来西亚令吉', '令吉', '文莱元', '文莱林吉特', '菲律宾比索',
    '印度卢比', '巴基斯坦卢比', '斯里兰卡卢比', '尼泊尔卢比', '孟加拉塔卡',
    '缅甸元', '缅元', '柬埔寨瑞尔', '老挝基普', '蒙古图格里克', '哈萨克斯坦坚戈',
    '俄罗斯卢布', '卢布', '瑞典克朗', '挪威克朗', '丹麦克朗', '冰岛克朗', '捷克克朗',
    '波兰兹罗提', '匈牙利福林', '罗马尼亚列伊', '保加利亚列弗', '塞尔维亚第纳尔',
    '乌克兰格里夫纳', '土耳其里拉', '以色列新谢克尔', '以色列谢克尔',
    '沙特阿拉伯里亚尔', '沙特里亚尔', '卡塔尔里亚尔', '阿联酋迪拉姆',
    '科威特第纳尔', '巴林第纳尔', '阿曼里亚尔', '约旦第纳尔',
    '埃及镑', '摩洛哥迪拉姆', '突尼斯第纳尔', '南非兰特', '肯尼亚先令',
    '坦桑尼亚先令', '乌干达先令', '尼日利亚奈拉', '加纳塞地', '埃塞俄比亚比尔',
    '毛里求斯卢比', '赞比亚克瓦查', '克瓦查', '西非法郎', '中非法郎',
    '巴西雷亚尔', '墨西哥比索', '阿根廷比索', '智利比索', '哥伦比亚比索',
    '秘鲁索尔', '乌拉圭比索', '巴拉圭瓜拉尼', '玻利维亚诺', '巴拿马巴波亚',
    '哥斯达黎加科朗', '多米尼加比索', '牙买加元', '特立尼达和多巴哥元',
    '东加勒比元', '斐济元', '巴布亚新几内亚基那', '太平洋法郎',
), key=len, reverse=True))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r'-?\d+(?:\.\d{1,6})?', value):
        raise ValueError('资本运作数值格式/精度无效')
    d = Decimal(value)
    if abs(d) >= Decimal(10) ** 22:
        raise ValueError('资本运作数值超界')
    return '0' if d.is_zero() else format(d.normalize(), 'f')


def numeric(value, *, scale=1):
    value = value.strip().replace(',', '').replace(' ', '').replace('(估)', '').replace('（估）', '')
    if value in MISSING or value in {'-%', '--%', '—%'}:
        return None
    currencies = '|'.join(map(re.escape, CURRENCIES))
    match = re.fullmatch(r'(-?\d+(?:\.\d{1,6})?)(万亿|亿|万)?(?:' + currencies + r')?(?:元|股|%)?', value)
    if not match:
        raise ValueError('资本运作单位/数值未知：' + value[:100])
    return number(format(Decimal(match[1]) * {'万': 10000, '亿': 100000000, '万亿': 1000000000000}.get(match[2], scale), 'f'))


def fields(table):
    return {**BASE, **SPECS[table]}


def identify(table, rows):
    """Source duplicates retain multiplicity, independent of HTML row ordering."""
    groups = {}
    for row in rows:
        anchor = [row.get(k) for k in ('unified_code', 'section', 'event_date', *ANCHORS[table])]
        groups.setdefault(digest([table, anchor]), []).append(row)
    result = []
    for anchor, group in sorted(groups.items()):
        for ordinal, row in enumerate(sorted(group, key=digest), 1):
            result.append({**row, 'record_key': digest([anchor, ordinal])})
    return sorted(result, key=lambda r: r['record_key'])


def validate(unit, rows, availability, *, today=None):
    if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', unit) or set(rows) != set(TABLES) or set(availability) != set(SECTIONS):
        raise ValueError('资本运作证券/表/栏目集合无效')
    if sum(map(len, rows.values())) > 10000:
        raise ValueError('资本运作单证券事实超过10000条')
    parents = {r['record_key']: r for r in rows['capital_encumbrance']}
    release_counts = {}
    for table, records in rows.items():
        if not isinstance(records, list) or len({r['record_key'] for r in records}) != len(records):
            raise ValueError('资本运作重复业务键或行集合无效')
        for row in records:
            if set(row) != set(fields(table)) or row['unified_code'] != unit or row['section'] not in TABLE_SECTIONS[table]:
                raise ValueError('资本运作字段/归属无效')
            for key in ANCHORS[table]:
                # A complete holding row may explicitly leave its object undisclosed.
                # Period/category/type and multiplicity still identify the source fact.
                if table == 'capital_equity_position' and key == 'target':
                    continue
                if table == 'capital_ipo' and key == 'target' and row['status']:
                    continue
                if key in ('project_name', 'investment_type', 'category', 'target', 'holder', 'parent_key') and not row[key] and table != 'capital_transaction':
                    raise ValueError(f'资本运作业务主体缺失：{table}.{key}')
            for key, (_, kind) in fields(table).items():
                value = row[key]
                if value is None:
                    if key in ('record_key', 'unified_code', 'section') or kind in ('key', 'bool'):
                        raise ValueError('资本运作必需字段缺失')
                    continue
                if kind == 'date':
                    stamp = date.fromisoformat(value)
                    if stamp.isoformat() != value:
                        raise ValueError('资本运作日期无效/超前')
                    if key == 'event_date' and today and stamp > today and (
                            table in ('capital_equity_summary', 'capital_equity_position') or
                            availability[row['section']] != FUTURE_ANNOUNCEMENT):
                        raise ValueError('资本运作日期无效/超前')
                elif kind == 'num':
                    if number(value) != value:
                        raise ValueError('资本运作数值未规范化')
                elif kind == 'bool':
                    if type(value) is not bool:
                        raise ValueError('资本运作估算标志无效')
                elif kind == 'int':
                    if type(value) is not int or not 0 <= value <= 1000000:
                        raise ValueError('资本运作个数无效')
                elif not isinstance(value, str) or (kind == 'key' and not re.fullmatch('[0-9a-f]{64}', value)) or (
                        kind.startswith('s') and kind != 'security' and len(value) > int(kind[1:])) or (
                        kind == 'text' and len(value.encode()) > 60000):
                    raise ValueError('资本运作文本/身份超限')
            if table == 'capital_release':
                parent = parents.get(row['parent_key'])
                if not parent or parent['section'] != row['section']:
                    raise ValueError('解除记录缺少原事件或归属不一致')
                release_counts[row['parent_key']] = release_counts.get(row['parent_key'], 0) + 1
                if release_counts[row['parent_key']] > 1000 or row['event_date'] is None:
                    raise ValueError('解除明细公告日期缺失或条数超限')
            if 'quantity' in row and row['quantity'] is not None and Decimal(row['quantity']) < 0:
                raise ValueError('资本运作股数不能为负')
    for key, value in availability.items():
        if not isinstance(value, str) or not 1 <= len(value) <= 300:
            raise ValueError('资本运作栏目可用性缺失')
