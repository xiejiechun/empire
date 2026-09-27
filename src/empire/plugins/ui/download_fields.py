"""Download settings editor; schema and validation belong to the shared contract."""
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from empire.contracts.download_settings import DEVICE_TIERS, FIELDS
from empire.plugins.ui.common import hint
from empire.plugins.ui.download_recommendation import DownloadRecommendation

GROUP_HINTS = {
    "出口容量": "设备数量用于推荐资源预算，不代表已连接设备或独立出口 IP。"
                "新增出口自动参与分配；同一个出口 IP 仍共享网站访问规则。",
    "内存响应": "股票、新闻、日历等小型响应在内存中处理。单响应限制同时约束传输及解压后的字节数；"
                "共享缓冲预算覆盖所有任务与预取页，不代表软件总内存。1 MiB = 1024 KiB。",
    "文件下载": "PDF、年报等大文件流式写入临时文件，不按文件大小占用内存。"
                "每个下载缓冲预留 256 KiB，校验完成后发布；这里不会新增公告采集任务。",
}


def display_value(field, value):
    return f"{value // field.scale:,} {field.unit}"


class DownloadFields(QWidget):
    changed = Signal()
    recommendation_applied = Signal(int)

    def __init__(self):
        super().__init__()
        self.inputs, self.states = {}, {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        for group_name in dict.fromkeys(field.group for field in FIELDS):
            group = QGroupBox(group_name)
            form = QFormLayout(group)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setVerticalSpacing(14)
            form.addRow(hint(GROUP_HINTS[group_name]))
            for field in (item for item in FIELDS if item.group == group_name):
                editor = QWidget()
                editor.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
                editor_layout = QVBoxLayout(editor)
                editor_layout.setContentsMargins(0, 0, 0, 0)
                editor_layout.setSpacing(4)
                value_row = QHBoxLayout()
                spin = QComboBox() if field.key == "planned_exit_devices" else QSpinBox()
                spin.setObjectName(field.key)
                if isinstance(spin, QComboBox):
                    for count in DEVICE_TIERS:
                        spin.addItem(f"{count:,} 台", count)
                    spin.setCurrentIndex(spin.findData(field.default))
                    spin.currentIndexChanged.connect(lambda _index: self.changed.emit())
                else:
                    spin.setRange(field.minimum // field.scale, field.maximum // field.scale)
                    spin.setValue(field.default // field.scale)
                    spin.setSuffix(" " + field.unit)
                    spin.valueChanged.connect(lambda _value: self.changed.emit())
                spin.setMinimumWidth(145)
                spin.setMaximumWidth(200)
                spin.setAccessibleName(field.title)
                spin.setToolTip(f"范围 {display_value(field, field.minimum)} ～ "
                                f"{display_value(field, field.maximum)}")
                self.inputs[field.key] = spin
                value_row.addWidget(spin)
                value_row.addStretch()
                editor_layout.addLayout(value_row)
                state = hint("正在读取当前与已保存设置……")
                state.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
                self.states[field.key] = state
                editor_layout.addWidget(state)
                label = QLabel(field.title)
                label.setWordWrap(True)
                label.setMinimumWidth(150)
                label.setBuddy(spin)
                form.addRow(label, editor)
            if any(field.key == "planned_exit_devices" and field.group == group_name for field in FIELDS):
                self.recommendation = DownloadRecommendation(self)
                form.addRow(self.recommendation)
            layout.addWidget(group)
        layout.addStretch()
        self.changed.connect(self.recommendation.refresh)
        self.recommendation.refresh()

    def values(self):
        return {field.key: (self.inputs[field.key].currentData() if field.key == "planned_exit_devices"
                           else self.inputs[field.key].value() * field.scale) for field in FIELDS}

    def load(self, values):
        for field in FIELDS:
            with QSignalBlocker(self.inputs[field.key]):
                if field.key == "planned_exit_devices":
                    self.inputs[field.key].setCurrentIndex(self.inputs[field.key].findData(values[field.key]))
                else:
                    self.inputs[field.key].setValue(values[field.key] // field.scale)
        self.recommendation.refresh()

    def show_state(self, saved, active, *, stale=False):
        for field in FIELDS:
            current = (display_value(field, active[field.key]) if active is not None
                       else "HTTP 服务未启动")
            suffix = (" · 待重启生效" if not stale and active is not None
                      and saved[field.key] != active[field.key] else "")
            current_label = "上次读取的生效值" if stale else "当前生效"
            saved_label = "上次读取的已保存值" if stale else "已保存"
            self.states[field.key].setText(
                f"{current_label}：{current}\n{saved_label}：{display_value(field, saved[field.key])}{suffix}")
