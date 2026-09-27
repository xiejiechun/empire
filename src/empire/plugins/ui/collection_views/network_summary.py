"""Explain actual task capability without promising an unmeasured duration."""

WAIT_LABELS = {
    "global": "全局并行额度", "site": "网站并行额度", "egress": "出口许可",
    "rate": "网站频控",
}
PHASE_LABELS = {
    "network": "等待当前请求返回", "ordered": "按页序校验发布 / 等待前页",
    "buffer": "等待首份共享缓冲额度", "idle": "当前无预取",
}


def running_download_summary(job):
    """Runtime windows contain pending and ready pages, not only active requests."""
    progress = job.get("progress", {})
    if not job.get("active") or "download_concurrency" not in progress:
        return "尚无本轮下载窗口数据；窗口还受任务缓冲预算与剩余页数限制。"
    text = (f"本轮综合预取窗口 {progress['download_concurrency']} 页 · "
            f"待处理 {progress.get('download_pending_pages', 0)} 页"
            f"（其中已下载待按序处理 {progress.get('download_ready_pages', 0)} 页）")
    if "download_buffer_capacity" in progress:
        text += f" · 总缓冲理论可容本类 {progress['download_buffer_capacity']} 页"
    failed = progress.get("download_failed_pages", 0)
    if failed:
        text += f"\n已返回失败页 {failed} 页（按页序处理，不越过前页推进断点）"
    reason = progress.get("download_wait_reason", "idle")
    if reason in PHASE_LABELS:
        text += f"\n当前阶段：{PHASE_LABELS[reason]}"
    if progress.get("download_buffer_limited"):
        text += "\n预取暂受共享缓冲限制；已提交的页面继续下载及按序处理"
    waits = job.get("network_capacity", {}).get("waiting_reasons", {})
    waiting = [f"{WAIT_LABELS[key]} {count}" for key, count in waits.items()
               if key in WAIT_LABELS and count > 0]
    if waiting:
        text += "\n共享请求等待数：" + "、".join(waiting)
    return text


def network_summary(job):
    policy, limits = job["policy"], job.get("network_capacity", {})
    if not policy.get("use_proxy"):
        return "已保存：本机直连 · 逐页采集"
    healthy = limits.get("healthy_egresses", limits.get("healthy_proxies", 0))
    slots = max(0, min(healthy, limits.get("effective_concurrency", 0)))
    if not healthy:
        return "代理暂不可用 · " + ("允许自动直连" if policy.get("proxy_fallback", True) else "等待代理恢复")
    if not job.get("parallel_downloads"):
        return f"健康出口 IP {healthy} 个 · 此任务有前后依赖，按顺序请求并轮换出口"
    return (f"健康出口 IP {healthy} 个 · 网站可分配上限 {slots} 个请求（所有任务共享）\n"
            f"{running_download_summary(job)}\n"
            "预取窗口不等于实际在途请求。实际速度受网站许可、响应时间和待下载页数影响；"
            "同一 IP 的设备不重复计算容量。")
