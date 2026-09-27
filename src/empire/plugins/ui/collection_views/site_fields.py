"""Website capacity editor; automatic scaling and explicit fixed-rate policies."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QSpinBox, QWidget

from empire.plugins.ui.common import accessible, hint


def rate_values(site):
    interval = site.get("min_interval_ms", 2000)
    return {"min_interval_ms": interval, "proxy_interval_ms": site.get("proxy_interval_ms", interval),
            "total_interval_ms": site.get("total_interval_ms", min(500, interval)),
            "max_concurrency": site.get("max_concurrency", 1),
            "scaling_mode": site.get("scaling_mode", "fixed"), "max_rps": site.get("max_rps", 0)}


class SiteRateFields(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.loading = False
        self.form = QFormLayout(self)
        self.mode = QComboBox()
        accessible(self.mode, "网站访问策略")
        self.mode.addItem("按出口 IP 独立限速（推荐）", "auto")
        self.mode.addItem("固定限速", "fixed")
        self.form.addRow("访问策略", self.mode)
        self.inputs = {}
        for name, title in (("proxy_interval_ms", "每个出口 IP 访问本站的最短间隔"),
                            ("min_interval_ms", "本机直连请求间隔"),
                            ("total_interval_ms", "网站固定请求间隔"),
                            ("max_concurrency", "网站最多同时请求"),
                            ("max_rps", "网站每秒最多请求")):
            field = QSpinBox()
            accessible(field, title)
            if name == "max_concurrency":
                field.setRange(0, 1024)
                field.setSpecialValueText("跟随全局下载上限")
                field.setSuffix(" 个")
            elif name == "max_rps":
                field.setRange(0, 100)
                field.setSpecialValueText("不额外限制")
                field.setSuffix(" 次 / 秒")
            else:
                field.setRange(100, 60000)
                field.setSuffix(" 毫秒")
                field.setSingleStep(100)
            field.valueChanged.connect(self.changed)
            self.inputs[name] = field
            self.form.addRow(title, field)
        self.advanced = QCheckBox("查看容量上限与直连设置")
        self.advanced.toggled.connect(self.update_visibility)
        self.form.addRow(self.advanced)
        self.policy_note = hint()
        self.form.addRow(self.policy_note)
        self.form.addRow(hint("同一出口 IP 下的多个代理共享间隔，且同时最多一个请求。\n"
                             "新增出口 IP 自动参与；HTTP 429 会暂停整个网站组。"))
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.changed.connect(self.update_note)
        self.load(rate_values({}))

    def mode_changed(self):
        if not self.loading and self.mode.currentData() == "auto" and self.inputs["max_concurrency"].value() == 1:
            self.inputs["max_concurrency"].setValue(0)
        self.update_visibility()
        self.changed.emit()

    def update_note(self):
        if self.mode.currentData() == "auto":
            ceiling = self.inputs["max_rps"].value()
            cap = f"，另设全站每秒 {ceiling} 次保护" if ceiling else "，不设置全站频率上限"
            concurrency = self.inputs["max_concurrency"].value()
            limit = f"最多 {concurrency} 个同时请求" if concurrency else "并行数跟随全局下载上限"
            self.policy_note.setText(f"当前草稿：按出口 IP 自动扩展，{limit}"
                                     f"{cap}；每出口间隔 {self.inputs['proxy_interval_ms'].value() / 1000:g} 秒，保存后生效。")
        else:
            self.policy_note.setText("固定模式保留原合计间隔；代理增加不会自动提高此上限。")

    def update_visibility(self):
        automatic = self.mode.currentData() == "auto"
        advanced = self.advanced.isChecked()
        self.form.setRowVisible(self.inputs["total_interval_ms"], not automatic)
        self.form.setRowVisible(self.inputs["max_rps"], automatic and advanced)
        for name in ("min_interval_ms", "max_concurrency"):
            self.form.setRowVisible(self.inputs[name], not automatic or advanced)
        self.advanced.setVisible(automatic)

    def values(self):
        return {"scaling_mode": self.mode.currentData(),
                **{name: field.value() for name, field in self.inputs.items()}}

    def load(self, values):
        self.loading = True
        self.mode.setCurrentIndex(self.mode.findData(values["scaling_mode"]))
        for name, field in self.inputs.items():
            field.setValue(values[name])
        self.loading = False
        self.update_visibility()
        self.update_note()
