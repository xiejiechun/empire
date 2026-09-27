"""Read-only proxy directory and routing counters; credentials are never displayed."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.core.redaction import redact
from empire.plugins.ui.common import hint, rows, table
from empire.plugins.ui.plugin import UiPlugin
from empire.plugins.ui.queries import QueryScope


class ProxyPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell, self.queries = shell, {}
        self.query_scope = QueryScope(self)
        layout = QVBoxLayout(self)
        title = QLabel("采集出口")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(hint("采集任务决定使用本机、代理优先或仅代理；站点访问规则按出口 IP 限制访问节奏。"
                              "代理目录由 RouterProxy 管理，Empire 只读取并展示无凭据入口地址。"))
        self.summary = hint("正在读取在线目录……")
        layout.addWidget(self.summary)
        layout.addWidget(QLabel("在线代理明细 · 在线目录由 RouterProxy 维护"))
        self.devices = table(["设备", "代理入口", "出口 IP", "协议", "状态", "正在请求", "请求数"])
        layout.addWidget(self.devices, 3)
        layout.addWidget(QLabel("站点请求统计"))
        self.routes = table(["网站", "使用中 / 可用并发", "最近10秒请求/秒", "代理请求", "回退直连"])
        layout.addWidget(self.routes, 1)
        layout.addWidget(hint("计数为本次 HTTP 插件运行期间的请求尝试数（含重试）。"
                              "设备编号不保证公网 IP 独立；同一出口的设备共享站点访问间隔。"
                              "不展示代理账号、密码或完整连接串。"))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        if getattr(self.shell, "shutting_down", False):
            self.query_scope.close()
            self.timer.stop()
            return
        for key, future in list(self.queries.items()):
            if not future.done():
                continue
            del self.queries[key]
            try:
                data = self.query_scope.result(key, future)
                if key == "pool":
                    protocols = {}
                    for entry in data["devices"]:
                        protocols[entry["protocol"]] = protocols.get(entry["protocol"], 0) + 1
                    protocol_text = " · ".join(f"{name} {count}" for name, count in sorted(protocols.items()))
                    self.summary.setText(data["error"] or
                        f"在线设备 {data['online']} 台 · 独立出口 IP {data['online_egresses']} 个" +
                        (f" · {protocol_text}" if protocol_text else "") +
                        f" · 等待出口 {data['waiting']} 个请求 · 无效目录项 {data['invalid']} 条")
                    rows(self.devices, [[e["code"], e["proxy_address"],
                         e["exit_ip"] or "未提供", e["protocol"],
                         "请求失败冷却" if e["cooldown_seconds"] else "目录在线",
                         e["busy"], e["requests"]] for e in data["devices"]],
                         keys=[e["code"] for e in data["devices"]])
                else:
                    rows(self.routes, [[g["name"],
                        f"{g.get('active_requests', 0)} / {g.get('effective_concurrency', 1)}",
                        g.get("recent_rps", 0), g.get("proxy_requests", 0),
                        g.get("fallback_requests", 0)] for g in data])
            except Exception as exc:
                stale = self.devices.rowCount() > 0 if key == "pool" else self.routes.rowCount() > 0
                self.summary.setText(self.query_scope.failure_message(
                    key, "代理或 HTTP 服务读取失败", redact(exc, self.shell.cfg), stale=stale,
                ))
        if self.isVisible():
            for key, cap, method in (("pool", "proxy.pool", "snapshot"),
                                     ("http", "http.fetch", "settings")):
                if key not in self.queries:
                    self.queries[key] = self.query_scope.invoke(
                        key, self.shell.runtime, cap, method)


class ProxyUiPlugin(UiPlugin):
    manifest = PluginManifest("ui.proxies", "采集出口界面", provides=("ui.pages.proxies",),
                              autostart=True, description="代理上下线、隔离与直连回退统计")

    def create_pages(self):
        return (PageContribution("proxies", "采集出口", ProxyPage, "采集管理", 3,
                                 "代理出口状态和代理/直连请求统计", cache_policy="lru"),)
