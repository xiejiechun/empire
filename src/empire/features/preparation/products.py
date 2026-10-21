"""Concrete outputs inside the existing readiness report; no parallel preparation."""
from empire.contracts.preparation_scope import PreparationScope
from empire.core.redaction import redact
from empire.features.capital_actions.distribution_text import distribution_text

PLANNED = (
    ('dividend_yield', '股息率', 'P2未实施，需要价格及明确计算口径。'),
    ('holding_cash', '持仓到账现金 / 现金收益', '缺持仓资格、支付日及税费契约，功能未实现。'),
    ('repurchase_cash', '期间回购支出汇总', 'P3以后；当前累计不是期间现金流，功能未实现。'),
    ('dilution', '稀释计算', 'P4未实施，需同口径股本、实际发行及注销事实。'),
)


def initial_products():
    return [dict(id='nominal_dividends', title='已实施名义每股派息', state='未检查',
                 detail='指定证券及起止日期后检查；独立于价格和回购。'),
            *[dict(id=key, title=title, state='功能未实现', detail=detail) for key, title, detail in PLANNED]]


def bind_products(report, products):
    report['products'] = products
    for row in report['rows']:
        if row['id'] == 'dividends':
            row['products'] = products


async def attach_products(report, context, request):
    products = initial_products()
    scope = PreparationScope.parse(request)
    row = next(r for r in report['rows'] if r['id'] == 'dividends')
    if row.get('required', True) and scope.codes and scope.start and scope.end:
        service = context.optional('dividends.query')
        if service:
            try:
                products[0] = await service.distribution_summary(request)
            except Exception as exc:
                products[0].update(state='数据阻断', detail=redact(exc, {'mysql': getattr(context.optional('mysql.store'), 'settings', {})}))
        else:
            products[0].update(state='数据阻断', detail='分红查询未运行；不能将缺查询当作空范围。')
    bind_products(report, products)


def products_text(products):
    return '\n\n'.join(distribution_text(p) if 'securities' in p else
        f"{p['title']} · {p['state']}\n{p.get('detail', '')}" for p in products)
