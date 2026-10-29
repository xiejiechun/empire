"""Bounded adapters for registered task previews; never accept SQL/capability names."""

from datetime import date, datetime
from decimal import Decimal

from empire.core.time import CHINA

from .preview_catalog import views


def wire(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    return value


def catalog(ident):
    now = datetime.now(CHINA)
    defaults = {"day": now.date().isoformat(), "month": now.strftime("%Y-%m")}
    return [
        dict(
            id=v.id,
            title=v.title,
            filters=v.filters,
            defaults={key: defaults[key] for key in v.filters if key in defaults},
        )
        for v in views(ident)
    ]


async def read(registry, ident, view, filters, cursor=None):
    spec = next((v for v in views(ident) if v.id == view), None)
    if spec is None:
        raise ValueError("该任务未登记此数据预览")
    if set(filters) - set(spec.filters):
        raise ValueError("预览筛选字段不属于当前数据")
    q = {k: v.strip() for k, v in filters.items() if v.strip()}
    now = datetime.now(CHINA)
    for key in ("start", "end", "day"):
        if key in q:
            date.fromisoformat(q[key])
    if q.get("start") and q.get("end") and q["start"] > q["end"]:
        raise ValueError("开始日期不能晚于结束日期")
    required = set(spec.filters) & {"security", "theme_id"}
    if required - set(q):
        return dict(
            rows=[],
            next=None,
            message="请填写"
            + ("完整证券代码，例如 000001.SZ" if "security" in required else "题材编号"),
            required=True,
        )
    if "security" in q:
        from empire.contracts.security import split_unified_code

        split_unified_code(q["security"])
    service = registry.get(spec.capability)
    method = getattr(service, spec.method)
    mode = spec.mode
    offset = cursor or 0
    if mode in ("offset", "list") and (type(offset) is not int or not 0 <= offset <= 100000):
        raise ValueError("分页位置无效")
    kwargs = {**q, **spec.fixed}
    if mode == "cursor":
        kwargs.update(after=cursor, limit=50)
    elif mode in ("offset", "list"):
        kwargs.update(offset=offset, limit=50)
    elif mode == "news":
        kwargs.update(before=cursor, limit=50, include_total=False)
    elif mode == "month":
        kwargs = {"month": q.get("month", now.strftime("%Y-%m"))}
    elif mode in ("day", "pool"):
        kwargs.update(day=q.get("day", now.date().isoformat()), after=cursor or "", limit=50)
    elif mode == "theme":
        kwargs.update(after=cursor or "", limit=50)
    elif mode == "security":
        kwargs.update(code=kwargs.pop("security"), after=cursor, limit=50)
    elif mode == "reason":
        kwargs = dict(day=q.get("day", now.date().isoformat()), code=q["security"])
    elif mode == "live":
        kwargs = dict(
            filters=(3, spec.fixed["pool"], "", q.get("day", now.date().isoformat()), "", ""),
            after=cursor,
        )
    data = await method(**kwargs)
    if mode == "reason":
        data = {"rows": [data] if data else []}
    if isinstance(data, list):
        data = {"rows": data}
    data = data or {"rows": []}
    rows = data.get("rows", data.get("points", []))
    next_cursor = data.get("next", data.get("next_cursor"))
    if mode in ("offset", "list"):
        next_cursor = (
            offset + len(rows)
            if len(rows) == 50 and (data.get("total") is None or offset + len(rows) < data["total"])
            else None
        )
    return wire(
        dict(
            rows=rows,
            next=next_cursor,
            total=data.get("total"),
            message=data.get("message", ""),
            notice="无记录不代表已完成该范围采集。",
            storage="Redis 盘中快照" if mode == "live" else "已归档数据",
        )
    )
