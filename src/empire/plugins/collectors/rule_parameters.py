"""Reviewed interpretation of the 2026 Shanghai/Shenzhen auction rules."""
from empire.contracts.trading_rules import citation_identity, identity, payload


class Parameters:
    def __init__(self, kind):
        self.kind, self.rows, self.citations = kind, [], {}

    def add(self, doc, clause, market, board, parameter, explanation, *, fragments=(),
            number=None, unit='text', condition='ordinary', start=None, end=None, until=None):
        excerpt = doc.require(clause, *fragments)
        citation = dict(issuer=doc.issuer, title=doc.title, source_url=doc.url,
            published_date=doc.published, document_hash=doc.body_hash, clause_key=clause, excerpt=excerpt)
        citation['citation_key'] = citation_identity(citation)
        self.citations[citation['citation_key']] = citation
        row = dict(kind=self.kind, market=market, board=board, condition_key=condition,
            parameter_key=parameter, effective_start=doc.effective, effective_end=until,
            number_value=number, text_value=explanation, start_time=start, end_time=end,
            unit=unit, citation_key=citation['citation_key'])
        row['record_key'] = identity(row)
        self.rows.append(row)

    def result(self):
        return payload(self.kind, self.rows, list(self.citations.values()))


def exchange_parameters(kind, sh, sz, bj):
    p = Parameters(kind)
    for market, doc in [('SH', sh), ('SZ', sz)]:
        boards = ('MAIN', 'STAR') if market == 'SH' else ('MAIN', 'CHINEXT')
        if kind == 'limit_rules':
            for board in boards:
                special = board != 'MAIN'
                clause = '6.6' if board == 'STAR' else '3.3.13'
                ratio = '0.20' if special else '0.10'
                p.add(doc, clause, market, board, 'limit_ratio', '普通交易日涨跌幅比例；豁免情形见单独记录',
                    number=ratio, unit='ratio', fragments=('20%' if special else '10%',))
                exc = clause if market == 'SH' else '3.3.15'
                p.add(doc, exc, market, board, 'exemptions', '首次上市前5个交易日、退市整理首日等豁免；完整适用情形以引用条款为准',
                    condition='exemptions', fragments=('前5个交易日' if market == 'SH' else '前五个交易日', '退市整理'))
                rounding = '3.3.17' if market == 'SH' else '3.3.19'
                p.add(doc, rounding, market, board, 'rounding', '按最小价格变动单位四舍五入；极低价格处理见原文',
                    fragments=('四舍五入', '最小变动单位'))
        elif kind == 'settlement_rules':
            for board in boards:
                p.add(doc, '3.1.4', market, board, 'resale_constraint',
                    '买入证券在交收前不得卖出，回转交易品种除外；本条未给出数值交收日，不自动换算T+1',
                    fragments=('在交收前不得卖出', '回转交易'))
        elif kind == 'tick_rules':
            for board in boards:
                p.add(doc, '3.3.11', market, board, 'price_tick', 'A股人民币最小申报价格变动单位',
                    fragments=('A股', '0.01'), number='0.01', unit='CNY')
        elif kind == 'lot_rules':
            p.add(doc, '3.3.8', market, 'MAIN', 'buy_minimum', '主板买入最低100股',
                fragments=('买入', '100股', '整数倍'), number='100', unit='shares')
            p.add(doc, '3.3.8', market, 'MAIN', 'buy_increment', '买入按100股整数倍申报',
                fragments=('100股', '整数倍'), number='100', unit='shares')
            p.add(doc, '3.3.8', market, 'MAIN', 'odd_lot', '卖出余额不足100股须一次性申报卖出',
                fragments=('不足100股', '一次性'))
            if market == 'SH':
                p.add(doc, '6.7', market, 'STAR', 'star_orders',
                    '科创板买卖最低200股；限价最高10万、市价最高5万；余额不足200股一次卖出；本条不明确增量',
                    fragments=('200股', '10万股', '5万股', '一次性'), number='200', unit='shares')
            else:
                for parameter, explanation, number in [('buy_minimum', '创业板买入最低100股', '100'),
                        ('buy_increment', '创业板买入按100股整数倍申报', '100')]:
                    p.add(doc, '3.3.8', market, 'CHINEXT', parameter, explanation,
                        fragments=('100股', '整数倍'), number=number, unit='shares')
                p.add(doc, '3.3.8', market, 'CHINEXT', 'odd_lot', '卖出余额不足100股须一次卖出', fragments=('不足100股', '一次性'))
                p.add(doc, '3.3.9', market, 'CHINEXT', 'maximum', '创业板限价不超30万股、市价不超15万股', fragments=('30万股', '15万股'))
        elif kind == 'sessions':
            key = '2.4.2' if market == 'SH' else '2.3.2'
            for board in boards:
                for parameter, start, end in [('open_auction', '09:15:00', '09:25:00'),
                        ('continuous_am', '09:30:00', '11:30:00'), ('continuous_pm', '13:00:00', '14:57:00'),
                        ('close_auction', '14:57:00', '15:00:00')]:
                    p.add(doc, key, market, board, parameter, '正常交易日竞价时段；停复牌例外须结合事件',
                        fragments=('9:15', '9:25', '14:57', '15:00'), start=start, end=end, unit='Asia/Shanghai')
            p.add(doc, '3.7.2' if market == 'SH' else '3.6.3', market, boards[1], 'after_hours',
                '盘后固定价格交易；15:00仍停牌的证券不参与，成交方式另行约束',
                fragments=('15:05', '15:30'), start='15:05:00', end='15:30:00', unit='Asia/Shanghai')
            if market == 'SH':
                doc.require('3.7.1', 'A股')
                p.add(doc, '3.7.2', market, 'MAIN', 'after_hours', '盘后固定价格交易；15:00仍停牌的证券不参与',
                    fragments=('15:05', '15:30'), start='15:05:00', end='15:30:00', unit='Asia/Shanghai')
        else:
            raise ValueError('非交易所规则项目')
    if kind == 'limit_rules':
        p.add(bj, '3.3.11', 'BJ', 'ALL', 'limit_ratio', '北交所普通交易日涨跌幅30%',
            fragments=('30%',), number='0.30', unit='ratio')
        p.add(bj, '3.3.12', 'BJ', 'ALL', 'exemptions', '公开发行上市首日、退市整理首日等豁免；增发除外',
            condition='exemptions', fragments=('上市交易首日', '退市整理期首日', '增发'))
    elif kind == 'settlement_rules':
        p.add(bj, '3.1.4', 'BJ', 'ALL', 'resale_constraint', '买入当日不得卖出；回转交易除外',
            fragments=('买入当日不得卖出', '回转交易'))
    elif kind == 'lot_rules':
        p.add(bj, '3.3.8', 'BJ', 'ALL', 'buy_minimum', '北交所买卖最低100股；本条未单列递增数量',
            fragments=('不低于100股',), number='100', unit='shares')
        p.add(bj, '3.3.8', 'BJ', 'ALL', 'odd_lot', '卖出余额不足100股须一次性申报卖出', fragments=('不足100股', '一次性'))
        p.add(bj, '3.3.9', 'BJ', 'ALL', 'maximum', '北交所竞价单笔最多100万股',
            fragments=('100万股',), number='1000000', unit='shares')
    elif kind == 'tick_rules':
        p.add(bj, '3.3.10', 'BJ', 'ALL', 'price_tick', '北交所股票最小申报价格变动单位',
            fragments=('0.01元人民币',), number='0.01', unit='CNY')
    elif kind == 'sessions':
        for parameter, start, end in [('open_auction', '09:15:00', '09:25:00'),
                ('continuous_am', '09:30:00', '11:30:00'), ('continuous_pm', '13:00:00', '14:57:00'),
                ('close_auction', '14:57:00', '15:00:00')]:
            p.add(bj, '2.3.2', 'BJ', 'ALL', parameter, '北交所普通竞价时段；暂缓盘后交易不列为可用时段',
                fragments=('9:15', '9:25', '14:57', '15:00'), start=start, end=end, unit='Asia/Shanghai')
    return p.result()
