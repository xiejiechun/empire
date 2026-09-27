
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from empire.desktop.theme import PAGE_SPACING
from empire.plugins.ui.common import Pager, accessible, bind_find, hint, rows, table

from .base import CollectionView
from .site_fields import SiteRateFields, rate_values


class SitesPage(CollectionView):
    section = "sites"
    def _sites_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(PAGE_SPACING)
        self.site_search = QLineEdit()
        self.site_search.setPlaceholderText("搜索网站组或域名")
        self.site_search.setClearButtonEnabled(True)
        self.site_search.setMaxLength(100)
        accessible(self.site_search, "搜索网站组", "输入网站组或域名；按 Ctrl+F 可回到此处。")
        bind_find(page, self.site_search)
        self.site_search.textChanged.connect(self.filters_changed)
        layout.addWidget(self.site_search)
        self.sites = table(["网站组", "共享的域名范围", "访问策略", "可分配请求上限"])
        self.sites.setAccessibleName("网站访问规则列表")
        self.sites.setMinimumHeight(160)
        self.sites.itemSelectionChanged.connect(self.select_site)
        layout.addWidget(self.sites, 1)
        self.site_pager = Pager()
        self.site_pager.changed.connect(self.change_page)
        layout.addWidget(self.site_pager)
        group = QGroupBox("网站组设置")
        form = QFormLayout(group)
        form.setVerticalSpacing(14)
        self.site_scope = hint("请选择网站组")
        form.addRow(self.site_scope)
        self.rate_fields = SiteRateFields()
        self.site_interval = self.rate_fields.inputs["min_interval_ms"]
        self.rate_fields.changed.connect(self.site_edited)
        form.addRow(self.rate_fields)
        save_row = QHBoxLayout()
        self.site_save = QPushButton("保存站点访问规则")
        self.site_save.setObjectName("primary")
        self.site_save.clicked.connect(self.save_site)
        save_shortcut = QShortcut(QKeySequence.StandardKey.Save, page)
        save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        save_shortcut.activated.connect(self.site_save.click)
        page._save_shortcut = save_shortcut
        self.site_reset = QPushButton("撤销修改")
        self.site_reset.clicked.connect(self.reset_site)
        self.buttons.extend([self.site_save, self.site_reset])
        save_row.addWidget(self.site_save)
        save_row.addWidget(self.site_reset)
        save_row.addStretch()
        self.site_feedback = hint()
        self.site_feedback.setAccessibleName("网站访问规则保存状态")
        editor = QScrollArea()
        editor.setWidgetResizable(True)
        editor.setFrameShape(QScrollArea.Shape.NoFrame)
        editor.setMinimumHeight(180)
        editor.setWidget(group)
        layout.addWidget(editor, 1)
        layout.addWidget(self.site_feedback)
        layout.addLayout(save_row)
        layout.addWidget(hint("配置保存到 MySQL，重启电脑后保留；影响该组的后续请求，已有 HTTP 429 冷却仍保留。\n"
                              "代理在线状态与直连回退统计在“采集出口”查看。"))
        return page

    def select_site(self):
        if not self.data or not 0 <= self.sites.currentRow() < len(self.data["sites"]):
            return
        site = self.data["sites"][self.sites.currentRow()]
        self.site_baselines[site["name"]] = rate_values(site)
        if self.site_loaded != site["name"] or site["name"] not in self.site_drafts:
            changed = self.site_loaded != site["name"]
            self.site_loaded = site["name"]
            self._loading = True
            self.rate_fields.load(self.site_drafts.get(site["name"], rate_values(site)))
            self._loading = False
            if changed:
                self.site_feedback.setText("有未保存修改" if site["name"] in self.site_drafts else "")
        domains = "、".join(f"{d} 及其子域名" for d in site["domains"])
        names = "、".join(site.get("task_names", [j["name"] for j in self.data["jobs"] if j["rate_group"] == site["name"]]))
        if site.get("task_count", 0) > 5:
            names += f" 等 {site['task_count']} 个任务（在任务列表按来源筛选查看）"
        self.site_scope.setText(f"当前网站组：{site['name']}\n共享范围：{domains}\n"
                                f"关联任务：{names or '尚无已注册任务'}\n"
                                f"可分配出口 IP {site.get('healthy_egresses', 0)} 个 · "
                                f"网站可分配上限 {site.get('effective_concurrency', site['max_concurrency'])} 个请求 · "
                                f"全局下载上限 {site.get('global_concurrency_limit', '—')} 个（所有网站共享）\n"
                                f"理论容量 {site.get('rate_ceiling_rps', '—')} 次/秒 · "
                                f"最近 10 秒实测 {site.get('recent_rps', 0):g} 次/秒\n"
                                "容量不代表正在下载数量；还受共享缓冲、剩余分页和其他任务占用影响。")
        self._update_buttons()

    def site_edited(self):
        if self._loading or not self.site_loaded:
            return
        value = self.rate_fields.values()
        saving = bool(self.action_context and self.action_context[0] == "configure_site"
                      and self.action_context[1][0] == self.site_loaded)
        if saving or value != self.site_baselines.get(self.site_loaded):
            self.site_drafts[self.site_loaded] = value
            self.site_feedback.setText("有未保存修改，当前请求仍使用已保存的间隔")
        else:
            self.site_drafts.pop(self.site_loaded, None)
            self.site_feedback.setText("与已保存设置一致")
        self._update_buttons()

    def reset_site(self):
        if self.site_loaded in self.site_baselines:
            self.site_drafts.pop(self.site_loaded, None)
            self._loading = True
            self.rate_fields.load(self.site_baselines[self.site_loaded])
            self._loading = False
            self.site_feedback.setText("已撤销未保存修改")
            self._update_buttons()

    def save_site(self):
        if self.site_loaded:
            self.submit("configure_site", self.site_loaded, self.rate_fields.values())


    build_view = _sites_page

    def render_content(self):
        sites = self.data["sites"]
        if not sites:
            self.site_loaded = None
            self.site_scope.setText("没有匹配的网站组")
        site_index = next((i for i, site in enumerate(sites) if site["name"] == self.site_loaded), 0)
        self.sites.blockSignals(True)
        rows(self.sites, [[s["name"], ", ".join(f"*.{d}" for d in s["domains"]),
                          "自动扩展" if s.get("scaling_mode") == "auto" else "固定限速",
                          s.get("effective_concurrency", s["max_concurrency"])] for s in sites])
        if sites:
            self.sites.selectRow(site_index)
        self.sites.blockSignals(False)
        self.select_site()

    @property
    def pager(self):
        return self.site_pager

    def _update_buttons(self):
        ready = self.data is not None and self.action is None
        self.site_save.setEnabled(bool(ready and self.site_loaded in self.site_drafts))
        self.site_reset.setEnabled(bool(ready and self.site_loaded in self.site_drafts))

    def initialize_state(self):
        self.site_loaded = None
        self.site_drafts, self.site_baselines = {}, {}

    def _query_args(self):
        return ("sites", self.site_search.text(), "", "", "", self.offset, 25)

    def summary_text(self):
        return f"{self.data.get('total', len(self.data['sites']))} 个匹配网站组 · 设置保存后立即作用于后续请求"

    def action_feedback(self, method):
        return self.site_feedback

    def apply_action_result(self, method, args, text):
        if method == "configure_site":
            name, policy = args
            self.site_baselines[name] = policy
            if self.data:
                for site in self.data["sites"]:
                    if site["name"] == name:
                        site.update(policy)
            current = self.rate_fields.values() if self.site_loaded == name else self.site_drafts.get(name, policy)
            if current == policy:
                self.site_drafts.pop(name, None)
            else:
                self.site_drafts[name] = current
            if name in self.site_drafts:
                text += "；之后的修改尚未保存"
        return text
