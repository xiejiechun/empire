"""Explicit, validated data-page navigation and session back action."""
from empire.contracts.ui import NavigationContext
from empire.plugins.ui.common import hint


def security_context(context):
    if context.index_code:
        raise ValueError('此页面用于股票，请从指数目录查看指数')
    if not context.unified_code:
        raise ValueError('请选择股票；导航没有提供证券身份')
    return context.unified_code[:6], context.unified_code[-2:]


def navigate_security(shell, target, security, *, day='', event_key=''):
    return shell.navigate(target, NavigationContext(unified_code=security, day=day,
                                                     event_key=event_key))


def result_identity(code, market='', start='', end=''):
    return f'{code or "全部证券"}{"." + market if market else ""}' + (
        f' · {start or "不限起点"}～{end or "不限终点"}' if start or end else '')


def data_note(layout, text):
    label = hint(text)
    layout.addWidget(label)
    return label
