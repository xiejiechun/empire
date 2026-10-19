"""Page-owned cancellable reads and explicit report exports."""
import json
import time
from concurrent.futures import CancelledError
from dataclasses import asdict, is_dataclass
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from empire.core.redaction import redact


class PreparationActions:
    def reload(self, all_items=False):
        self.needs_check = True
        self.operation = 'report'
        self.scan_all = all_items
        self.tick()

    def scan_inventory(self):
        if self.future is not None:
            return
        self.operation = 'inventory'
        self.needs_check = True
        self.tabs.setCurrentWidget(self.inventory_view)
        self.tick()

    def cancel_scan(self):
        self.needs_check = False
        self.query_scope.cancel_all()
        self.future = self.snapshot_future = None
        self.set_busy(False)
        self.summary.setText('检查已取消；已显示结果仅为部分证据，未检查项目不能算完成。')

    def mark_draft(self):
        if self.report:
            self.summary.setText('用途或范围已修改，尚未重新检查。下方保留上次范围的结果，请点击“检查本次用途”。')
            self.research_summary.setText('下方结论仍属于上次报告范围；研究条件与详情中保留原范围。')

    def draft_changed(self):
        try:
            request = self.scope_bar.request()
            request['scan'] = self.active_request['scan']
            return request != self.active_request
        except (ValueError, TypeError):
            return True

    def set_busy(self, busy):
        for button in (self.refresh_button, self.full_button, self.inventory_button):
            button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def export_report(self):
        if not self.report and not self.inventory_view.report:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出数据准备报告', '数据准备检查.json', 'JSON (*.json)')
        if path:
            try:
                payload = dict(report=self.report, inventory=self.inventory_view.report,
                               note='报告绑定其记录范围与时间；库存不代表完整性，样例不代表缺口总量。')
                Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                    default=lambda v: asdict(v) if is_dataclass(v) else str(v)), encoding='utf-8')
                self.summary.setText('报告已导出：' + path)
            except OSError as exc:
                self.summary.setText('导出失败：' + redact(exc, self.shell.cfg))

    def tick(self):
        if getattr(self.shell, 'shutting_down', False):
            self.query_scope.close()
            self.timer.stop()
            return
        if self.future is not None and self.future.done():
            future, self.future = self.future, None
            self.set_busy(False)
            self.query_scope.cancel('preparation_snapshot')
            self.snapshot_future = None
            try:
                result = self.query_scope.result('preparation', future)
                if self.operation == 'inventory':
                    self.inventory_view.render(result)
                    self.summary.setText('MySQL 库存盘点结束；完整性和用途请分别检查。')
                else:
                    self.render(result)
                    if self.draft_changed():
                        self.mark_draft()
            except CancelledError:
                self.summary.setText('检查已取消；未完成项目保持未核验。')
            except Exception as exc:
                self.summary.setText(self.query_scope.failure_message(
                    'preparation', '本次检查未完成', redact(exc, self.shell.cfg), stale=bool(self.entries)))
        if self.snapshot_future is not None and self.snapshot_future.done():
            future, self.snapshot_future = self.snapshot_future, None
            try:
                result = self.query_scope.result('preparation_snapshot', future)
                if result is not None and self.future is not None:
                    if self.operation == 'inventory':
                        self.inventory_view.render(result)
                    else:
                        self.render(result)
                        if self.draft_changed():
                            self.mark_draft()
            except Exception:
                pass  # The owned main query reports failure; keep prior progress.
        if (self.isVisible() and self.future is not None and self.operation != 'overview'
                and self.snapshot_future is None and time.monotonic() - self.last_snapshot >= 1):
            self.last_snapshot = time.monotonic()
            method, args = ('inventory_snapshot', ()) if self.operation == 'inventory' else ('snapshot', (self.active_request,))
            self.snapshot_future = self.query_scope.invoke('preparation_snapshot', self.shell.runtime,
                                                           'preparation.query', method, *args)
        if self.isVisible() and self.future is None and self.needs_check:
            self.needs_check = False
            try:
                request = self.scope_bar.request()
            except ValueError as exc:
                self.summary.setText(str(exc))
                return
            if self.scan_all:
                request['scan'] = 'all'
            self.active_request = request
            self.set_busy(True)
            self.summary.setText('正在读取库存概览……' if self.operation == 'overview' else
                                 '检查进行中；全池深检可能耗时数分钟，可取消。只读检查不会启动采集。')
            args = (True,) if self.operation == 'inventory' else (request, True) if self.operation == 'report' else (request,)
            self.future = self.query_scope.invoke('preparation', self.shell.runtime, 'preparation.query', self.operation, *args)
