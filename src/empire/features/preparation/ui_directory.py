"""Directory presentation; classifications do not decide business acceptance."""
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from empire.plugins.ui.common import accessible

VIEWS = (('本次必需输入', 'required'), ('缺口清单', 'gaps'), ('全部项目', ''),
         ('来源集合已完成', 'completed'), ('来源集合未完成 / 未核验', 'unfinished'),
         ('已接入采集', 'available'), ('计算与核对', 'processing'), ('能力规划', 'planned'))


def work_view(entry):
    if not entry['registered']:
        return 'planned'
    return 'available' if entry['kind'] == '采集' else 'processing'


def matches_view(entry, view):
    if view == 'required':
        return entry.get('required', True)
    if view == 'gaps':
        return entry.get('required', True) and not entry['assessment']['usable']
    if view in ('completed', 'unfinished'):
        return entry['kind'] == '采集' and ((entry['assessment']['integrity'] == '通过') == (view == 'completed'))
    return not view or work_view(entry) == view


class PreparationDirectoryBar(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel('查看')
        self.view = accessible(QComboBox(), '数据准备视图')
        for title, value in VIEWS:
            self.view.addItem(title, value)
        label.setBuddy(self.view)
        layout.addWidget(label)
        layout.addWidget(self.view)
        self.count = QLabel('等待检查结果')
        layout.addWidget(self.count, 1)

    def render(self, entries, visible):
        counts = {key: sum(work_view(e) == key for e in entries)
                  for _, key in VIEWS if key}
        self.count.setText(f"显示 {visible} / {len(entries)} 项 · 已接入采集 {counts['available']} 项 · "
                           f"已接入计算与核对 {counts['processing']} 项 · 待建设 {counts['planned']} 项")
        self.count.setWordWrap(True)
