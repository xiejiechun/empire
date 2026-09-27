"""The shared, unit-explicit schema for durable download resource settings."""
from dataclasses import dataclass

from empire.contracts.download import (
    CALENDAR_RESPONSE,
    NEWS_RESPONSE,
    STOCK_RESPONSE,
    MiB,
    ResponsePolicy,
)

MAX_PARALLEL_DOWNLOADS = 1024
DEVICE_TIERS = tuple(range(100, 1001, 100))


@dataclass(frozen=True)
class ResourceField:
    key: str
    title: str
    unit: str
    scale: int
    minimum: int
    maximum: int
    default: int
    group: str


FIELDS = (
    ResourceField("planned_exit_devices", "规划出口设备数", "台", 1,
                  100, 1000, 100, "出口容量"),
    ResourceField("max_parallel_downloads", "全局最多同时下载", "个", 1,
                  1, MAX_PARALLEL_DOWNLOADS, 128, "出口容量"),
    ResourceField("buffer_budget_bytes", "所有任务共享缓冲预算", "MiB", MiB,
                  MiB, 4096 * MiB, 512 * MiB, "内存响应"),
    ResourceField("stock_response_bytes", "股票单响应上限", "KiB", 1024,
                  1024, 1024 * MiB, STOCK_RESPONSE.max_body_bytes, "内存响应"),
    ResourceField("news_response_bytes", "新闻单响应上限", "KiB", 1024,
                  1024, 1024 * MiB, NEWS_RESPONSE.max_body_bytes, "内存响应"),
    ResourceField("calendar_response_bytes", "日历单响应上限", "KiB", 1024,
                  1024, 1024 * MiB, CALENDAR_RESPONSE.max_body_bytes, "内存响应"),
    ResourceField("generic_response_bytes", "通用单响应上限", "KiB", 1024,
                  1024, 1024 * MiB, ResponsePolicy().max_body_bytes, "内存响应"),
    ResourceField("file_response_bytes", "单文件大小上限", "MiB", MiB,
                  MiB, 1024 * MiB, 256 * MiB, "文件下载"),
    ResourceField("download_quota_bytes", "下载目录总配额", "MiB", MiB,
                  MiB, 1024 * 1024 * MiB, 2048 * MiB, "文件下载"),
    ResourceField("disk_free_margin_bytes", "磁盘保留空间", "MiB", MiB,
                  0, 1024 * 1024 * MiB, 128 * MiB, "文件下载"),
    ResourceField("file_concurrency", "文件同时下载数", "个", 1,
                  1, 64, 4, "文件下载"),
)
DEFAULTS = {field.key: field.default for field in FIELDS}
LEGACY_KEYS = frozenset(("buffer_budget_bytes", "download_quota_bytes", "disk_free_margin_bytes", "file_concurrency"))
PROFILE_FIELDS = {"stocks": "stock_response_bytes", "news": "news_response_bytes",
                  "calendar": "calendar_response_bytes", "generic": "generic_response_bytes"}


def validate_settings(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError("下载资源设置字段不完整或含未知字段；旧配置请先通过 "
                         "scripts/migrate_download_capacity.py 显式迁移")
    for field in FIELDS:
        value = values[field.key]
        if (type(value) is not int or not field.minimum <= value <= field.maximum
                or value % field.scale):
            raise ValueError(f"{field.title}须为 {field.minimum // field.scale}～"
                             f"{field.maximum // field.scale} {field.unit} 的整数")
    validate_device_count(values["planned_exit_devices"])
    largest = max(values[key] for key in PROFILE_FIELDS.values())
    needed = ResponsePolicy(max_body_bytes=largest).reservation_bytes
    if values["buffer_budget_bytes"] < needed:
        raise ValueError(f"共享缓冲至少需要 {(needed + MiB - 1) // MiB} MiB"
                         "（最大单响应的 3 倍 + 256 KiB 工作区）")
    if values["file_response_bytes"] > values["download_quota_bytes"]:
        raise ValueError("下载目录总配额不能小于单文件大小上限")
    return dict(values)


def validate_device_count(device_count):
    if type(device_count) is not int or device_count not in DEVICE_TIERS:
        raise ValueError("出口设备规划请选择 100～1000 台，每 100 台一档")
    return device_count


def recommended_settings(device_count, current=None):
    """Capacity planning only; never loosens response, disk or website limits.

    Stocks currently own the only independent-page collector. Budget a whole
    stock window plus 20% headroom (or the other serial profiles/file buffers,
    whichever is larger), rounding to 256 MiB. This is a reservation envelope,
    not eagerly allocated RAM, and not a guarantee of available host memory.
    """
    validate_device_count(device_count)
    values = dict(DEFAULTS if current is None else current)
    if set(values) != set(DEFAULTS):
        raise ValueError("推荐需要完整的当前下载设置")
    window = min(MAX_PARALLEL_DOWNLOADS, ((device_count + 127) // 128) * 128)
    stock = ResponsePolicy(max_body_bytes=values["stock_response_bytes"]).reservation_bytes
    other = sum(ResponsePolicy(max_body_bytes=values[key]).reservation_bytes
                for profile, key in PROFILE_FIELDS.items() if profile != "stocks")
    other += values["file_concurrency"] * 256 * 1024
    needed = max((window * stock * 6 + 4) // 5, window * stock + other)
    block = 256 * MiB
    buffer = ((needed + block - 1) // block) * block
    if buffer > 4096 * MiB:
        raise ValueError("按当前股票单响应上限生成的推荐缓冲超过 4096 MiB；"
                         "请核实单响应上限，或手动设置较低并行窗口")
    values.update(planned_exit_devices=device_count, max_parallel_downloads=window,
                  buffer_budget_bytes=buffer)
    return validate_settings(values)


def local_download_options(values):
    """Numeric settings have one authority: MySQL, never layered TOML overrides."""
    if not isinstance(values, dict) or set(values) - {"download_directory"}:
        raise ValueError("[http] 仅保留 download_directory；旧下载额度请通过 "
                         "scripts/migrate_download_settings.py 显式迁移，再在下载资源页面管理")
    return dict(values)
