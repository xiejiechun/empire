"""Presentation of review results; no queries or source execution."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView

from empire.features.market_review.model import theme_window
from empire.plugins.ui.common import rows, table
from empire.plugins.ui.series_chart import SeriesChart

METRICS = [('up', '涨停'), ('opened', '炸板'), ('down', '跌停'), ('sealed', '封板率'),
           ('chain', '连续≥2板'), ('height', '最高连续板'), ('first_promotion', '1进2率'),
           ('promotion', '连板晋级率')]


def value(v, percent=False):
    return '—' if v is None else f'{v:.1f}%' if percent else str(v)


def chart():
    return SeriesChart([
        dict(title='涨停 · 炸板 · 跌停', fields=[(1, '涨停'), (2, '炸板'), (3, '跌停')], gap=None, zero=True),
        dict(title='最高连续涨停高度', fields=[(4, '板数')], bars=True, zero=True),
    ])


def build_tables(tabs):
    specs = {
        'ladder': ('当日连板梯队', ['证券', '名称', '连续板数', '来源N天M板', '涨跌幅/%']),
        'timeline': ('最高板时间线', ['日期', '最高板', '并列最高证券', '状态']),
        'rotation': ('题材轮动', ['排名']),
        'heat': ('近10交易日热度', ['题材', '热度合计']),
        'full': ('完整统计', ['日期', *[label for _, label in METRICS], '状态']),
    }
    result = {}
    for key, (title, labels) in specs.items():
        widget = table(labels)
        widget.setMinimumHeight(260)
        tabs.addTab(widget, title)
        result[key] = widget
    result['rotation'].cellClicked.connect(lambda r, c: highlight(result['rotation'], r, c))
    return result


def highlight(widget, row, col):
    cell = widget.item(row, col)
    identity = cell.data(Qt.ItemDataRole.UserRole) if cell else None
    if identity is None:
        return
    identity = None if getattr(widget, 'highlighted', None) == identity else identity
    widget.highlighted = identity
    for r in range(widget.rowCount()):
        for c in range(widget.columnCount()):
            item = widget.item(r, c)
            if item:
                item.setBackground(QColor('#dcecff') if identity and
                    item.data(Qt.ItemDataRole.UserRole) == identity else QColor())


def render(tables, graph, data, selected):
    visible = [r for r in data['days'] if r['day'] <= selected]
    current = next((r for r in visible if r['day'] == selected), None)
    graph.set_series([(str(r['day']), r['up'], r['opened'], r['down'], r['height']) for r in visible],
                     '无已查询交易日；缺数据不会填0')
    ladder = current['rows'] if current else []
    rows(tables['ladder'], [[r['unified_code'], r['name'], value(r['streak']), r['high_days'],
                            value(r['change_rate'])] for r in ladder],
         keys=[r['unified_code'] for r in ladder])
    rows(tables['timeline'], [[str(r['day']), value(r['height']),
        ' / '.join(s['name'] + ' ' + s['unified_code'] for s in r['leaders']) or '—', r['note']]
        for r in reversed(visible)], keys=[str(r['day']) for r in reversed(visible)])
    tables['timeline'].setColumnWidth(2, 420)
    rows(tables['full'], [[str(r['day']), *[value(r[k], k in ('sealed', 'first_promotion', 'promotion'))
        for k, _ in METRICS], r['note']] for r in reversed(visible)],
        keys=[str(r['day']) for r in reversed(visible)])
    render_rotation(tables['rotation'], data['themes'], [r['day'] for r in visible])
    heat, count = theme_window(data['themes'], [r['day'] for r in visible])
    rows(tables['heat'], [[r['name'], str(r['heat'])] for r in heat], keys=[r['theme_id'] for r in heat])
    return current, count


def render_rotation(widget, theme_days, days):
    days = list(reversed(days))
    widget.setColumnCount(len(days) + 1)
    widget.setHorizontalHeaderLabels(['排名', *map(str, days)])
    widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    columns = []
    for day in days:
        ranked = sorted((r for r in theme_days.get(day, []) if r['parent_id'] is None
                         and r['rank_no'] is not None), key=lambda r: (r['rank_no'], r['theme_id']))[:10]
        columns.append(ranked)
    rows(widget, [[str(i + 1), *[items[i]['name'] if i < len(items) else
        '未采集' if not theme_days.get(day) else '—' for day, items in zip(days, columns)]]
        for i in range(10)], keys=[str(i) for i in range(10)])
    widget.highlighted = None
    for c, items in enumerate(columns, 1):
        for r in range(10):
            item = widget.item(r, c)
            item.setData(Qt.ItemDataRole.UserRole, items[r]['theme_id'] if r < len(items) else None)
            item.setBackground(QColor())
            item.setToolTip(str(days[c - 1]) + ' · ' + item.text())
