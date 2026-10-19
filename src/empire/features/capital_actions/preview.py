"""Human-readable capital plans, precise per-share conversions and source-date roles."""
from decimal import Decimal

from empire.features.capital_actions.words import LABELS
from empire.plugins.ui.preview_cards import card, fields, text


def per_ten(value):
    return '未知' if value is None else format(Decimal(str(value))*10, 'f')


def summary(kind, record):
    data = record['data']
    if kind == 'dividends':
        return (f'每10股派 {per_ten(data.get("cash_per_share"))} 元，'
                f'送 {per_ten(data.get("bonus_per_share"))} 股，转增 {per_ten(data.get("transfer_per_share"))} 股')
    if kind == 'rights_issues':
        return f'每10股配 {per_ten(data.get("rights_per_share"))} 股 · 配股价 {data.get("rights_price") if data.get("rights_price") is not None else "未知"} 元'
    return f'{data.get("issue_method") or "发行方式未知"} · 发行价 {data.get("issue_price") if data.get("issue_price") is not None else "未知"} 元'


def plan_cards(kind, records):
    return ''.join(card(r['name'] + ' ' + r['code'] + '.' + r['market'],
        '<p><b>' + text(summary(kind, r)) + '</b></p><p>来源进度：' + text(r['data'].get('status'))
        + f'</p><p><a href="record:{i}">查看方案与关键日期</a></p>',
        (r['event_date'] or '来源日期未提供') + ' · ' + (r['data'].get('report_date') or ''))
        for i, r in enumerate(records)) or '<p>暂无匹配的已归档方案；不代表来源没有方案。</p>'


def plan_profile(kind, record):
    data = record['data']
    warning = ''
    detail = data.get('detail')
    if kind == 'additional_issues':
        if detail and detail.get('availability') == 'unavailable':
            warning = '<p><b>来源本次暂无可用详情；下面保留的详情为历史参考。</b></p>'
            extra = detail.get('last_available') or {}
        else:
            extra = detail or {}
            if not detail:
                warning = '<p>增发详情尚未补齐，请查看采集任务。</p>'
        data = {**data, **extra}
    date_keys = ('report_date', 'announcement_date', 'record_date', 'ex_date', 'issue_date',
                 'public_issue_date', 'private_issue_date', 'payment_start', 'payment_end', 'listing_date')
    dates = [(LABELS[k], data[k]) for k in date_keys if k in data]
    groups = [('关键日期（缺失日期为未知，不据日期经过判断完成）', dates),
        ('方案数值与说明', [(LABELS.get(k, k), v) for k, v in data.items()
            if k not in date_keys and k not in ('detail', 'source_id', 'availability', 'last_available', 'source_error_code')])]
    body = warning + '<p><b>' + text(summary(kind, record)) + '</b></p>'
    if kind == 'dividends':
        body += '<p>每10股为每股原值精确换算；税收口径：' + text(data.get('tax_basis')) + '</p>'
    if kind == 'rights_issues':
        body += '<p>缴款区间：' + text(data.get('payment_start')) + ' → ' + text(data.get('payment_end')) + '</p>'
    for title, values in groups:
        body += '<h3>' + text(title) + '</h3>' + fields(values)
    return card(record['name'] + ' · ' + record['code'] + '.' + record['market'], body,
                '来源方案，日期与进度以来源字段为准')
