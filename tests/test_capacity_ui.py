"""Capacity UI distinguishes resource plans from measured request activity."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.collection_views.network_summary import network_summary  # noqa: E402
from empire.plugins.ui.collection_views.site_fields import SiteRateFields, rate_values  # noqa: E402


def test_site_capacity_can_follow_global_and_auto_switch_preserves_frequency():
    app = QApplication.instance() or QApplication([])
    fields = SiteRateFields()
    original = rate_values({"proxy_interval_ms": 3000, "min_interval_ms": 4000})
    fields.load(original)
    fields.mode.setCurrentIndex(fields.mode.findData("auto"))
    values = fields.values()
    assert values["max_concurrency"] == 0
    assert values["proxy_interval_ms"] == 3000
    assert values["min_interval_ms"] == 4000
    assert values["max_rps"] == original["max_rps"]
    assert "跟随全局下载上限" in fields.policy_note.text()
    fields.inputs["max_concurrency"].setValue(1024)
    assert fields.values()["max_concurrency"] == 1024
    fields.load(original | {"max_concurrency": 12})
    fields.mode.setCurrentIndex(fields.mode.findData("auto"))
    assert fields.values()["max_concurrency"] == 12
    fields.deleteLater()
    app.processEvents()


def test_task_summary_does_not_misrepresent_site_capacity_as_active_downloads():
    job = {"policy": {"use_proxy": True}, "parallel_downloads": True,
           "network_capacity": {"healthy_egresses": 100, "effective_concurrency": 100}}
    text = network_summary(job)
    assert "网站可分配上限 100" in text
    assert "尚无本轮下载窗口数据" in text
    assert "本任务最多同时下载" not in text
    job.update(active=True, progress={"download_concurrency": 19, "download_pending_pages": 17,
                                     "download_ready_pages": 16, "download_buffer_capacity": 19,
                                     "download_wait_reason": "buffer"})
    job["network_capacity"]["waiting_reasons"] = {"global": 2, "rate": 3, "site": 0}
    text = network_summary(job)
    assert "综合预取窗口 19 页" in text
    assert "待处理 17 页" in text
    assert "已下载待按序处理 16 页" in text
    assert "当前阶段：等待首份共享缓冲额度" in text
    assert "全局并行额度 2" in text and "网站频控 3" in text
    assert "网站并行额度 0" not in text


def test_task_summary_ignores_old_window_for_finished_run_and_handles_ordered_wait():
    job = {"policy": {"use_proxy": True}, "parallel_downloads": True,
           "active": False, "network_capacity": {"healthy_egresses": 100, "effective_concurrency": 100},
           "progress": {"download_concurrency": 128, "download_wait_reason": "ordered"}}
    assert "综合预取窗口 128" not in network_summary(job)
    job["active"] = True
    assert "当前阶段：按页序校验发布 / 等待前页" in network_summary(job)


def test_normal_request_phase_and_budget_limit_are_separate_from_failed_pages():
    job = {"policy": {"use_proxy": True}, "parallel_downloads": True,
           "active": True, "network_capacity": {"healthy_egresses": 100, "effective_concurrency": 100},
           "progress": {"download_concurrency": 20, "download_pending_pages": 20,
                        "download_ready_pages": 0, "download_failed_pages": 0,
                        "download_wait_reason": "network", "download_buffer_limited": False}}
    text = network_summary(job)
    assert "当前阶段：等待当前请求返回" in text
    assert "共享缓冲限制" not in text and "失败页" not in text and "瓶颈" not in text
    job["progress"].update(download_buffer_limited=True, download_failed_pages=2, download_ready_pages=3)
    text = network_summary(job)
    assert "当前阶段：等待当前请求返回" in text
    assert "预取暂受共享缓冲限制" in text
    assert "已下载待按序处理 3 页" in text
    assert "已返回失败页 2 页" in text
