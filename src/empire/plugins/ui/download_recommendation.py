"""Explain and apply a capacity recommendation to the unsaved resource draft."""
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from empire.contracts.download import MiB, ResponsePolicy
from empire.contracts.download_settings import recommended_settings
from empire.plugins.ui.common import hint


class DownloadRecommendation(QWidget):
    def __init__(self, fields):
        super().__init__()
        self.fields = fields
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preview = hint()
        layout.addWidget(self.preview)
        self.button = QPushButton("填入推荐值")
        self.button.setToolTip("只调整规划设备数、全局并行上限与共享缓冲；保存并重启后生效")
        self.button.clicked.connect(self.apply)
        layout.addWidget(self.button)
        layout.addWidget(hint("推荐值不会提高单响应或文件上限，也不会更改网站频控、任务代理开关。"
                              "填入后仍需点击“保存设置”，再正常重启软件。"))

    def refresh(self):
        values = self.fields.values()
        try:
            result = recommended_settings(values["planned_exit_devices"], values)
        except ValueError as exc:
            self.preview.setText(f"暂不能推荐：{exc}")
            self.button.setEnabled(False)
            return
        self.button.setEnabled(True)
        reservation = ResponsePolicy(max_body_bytes=values["stock_response_bytes"]).reservation_bytes
        self.preview.setText(
            f"{result['planned_exit_devices']:,} 台规划推荐：全局并行上限 "
            f"{result['max_parallel_downloads']:,}，共享缓冲 {result['buffer_budget_bytes'] // MiB:,} MiB。\n"
            f"当前草稿缓冲按股票每页预留 {reservation / MiB:g} MiB，理论可容纳 "
            f"{values['buffer_budget_bytes'] // reservation:,} 页（未扣除其他任务占用）。"
            "这是资源预算，不是进程总内存，也不是实际并发或吞吐保证。")

    def apply(self):
        values = self.fields.values()
        try:
            result = recommended_settings(values["planned_exit_devices"], values)
        except ValueError:
            self.refresh()
            return
        self.fields.load(result)
        self.fields.changed.emit()
        self.fields.recommendation_applied.emit(result["planned_exit_devices"])
