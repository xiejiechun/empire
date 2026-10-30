"""Bounded adapters for registered task previews; never accept SQL/capability names."""

import hashlib
import json
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
    from .preview_presentation import presentation

    now = datetime.now(CHINA)
    defaults = {"day": now.date().isoformat(), "month": now.strftime("%Y-%m")}
    return [dict(id=v.id, filters=v.filters,
                 defaults={key: defaults[key] for key in v.filters if key in defaults},
                 **presentation(ident, v)) for v in views(ident)]


async def read(registry, ident, view, filters, cursor=None, order=None):
    spec = next((v for v in views(ident) if v.id == view), None)
    if spec is None:
        raise ValueError("该任务未登记此数据预览")
    if set(filters) - set(spec.filters):
        raise ValueError("预览筛选字段不属于当前数据")
    if any(not isinstance(v, str) or len(v) > 200 for v in filters.values()):
        raise ValueError("预览筛选值必须是有界文本")
    q = {k: v.strip() for k, v in filters.items() if v.strip()}
    if ident == 'tdx-unlock-industries':
        for key in ('start', 'end'):
            if key in q and len(q[key]) == 7:
                q[key] += '-01'
    now = datetime.now(CHINA)
    for key in ("start", "end", "day"):
        if key in q:
            date.fromisoformat(q[key])
    if q.get("start") and q.get("end") and q["start"] > q["end"]:
        raise ValueError("开始日期不能晚于结束日期")
    required = set(spec.filters) if spec.hidden else set(spec.filters) & {"security", "theme_id"}
    if required - set(q):
        return dict(
            rows=[],
            next=None,
            message="请填写"
            + ("完整证券代码，例如 000001.SZ" if "security" in required else "题材编号" if "theme_id" in required else "记录身份；请从列表选择记录"),
            required=True,
        )
    if "security" in q:
        from empire.contracts.security import split_unified_code

        split_unified_code(q["security"])
    sort_signature = None
    if order is not None:
        from .preview_presentation import presentation
        allowed = {f['key'] for f in presentation(ident, spec)['columns']}
        if (spec.hidden or spec.mode in ('month', 'reason') or not isinstance(order, dict)
                or set(order) != {'field', 'direction'} or order['field'] not in allowed
                or order['direction'] not in ('asc', 'desc')):
            raise ValueError('当前预览排序字段或方向无效')
        sort_signature = hashlib.sha256(json.dumps(
            [ident, view, q, order], sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest()
        if cursor is not None:
            if (not isinstance(cursor, dict) or set(cursor) != {'preview', 'position'}
                    or cursor['preview'] != sort_signature):
                raise ValueError('排序或筛选已变化，请返回第一页')
            cursor = cursor['position']
    service = registry.get(spec.capability)
    method = getattr(service, spec.method)
    mode = spec.mode
    offset = (cursor or 0) if order is None else 0
    if mode in ("offset", "list") and (type(offset) is not int or not 0 <= offset <= 100000):
        raise ValueError("分页位置无效")
    kwargs = {**q, **spec.fixed}
    if mode == "detail":
        if ident == "tdx-hot-list":
            kwargs = dict(code=q["security"], stamp=q["day"])
        elif ident == "ths-listings":
            kwargs = dict(security=q["security"])
        elif ident == "tdx-unlocks":
            kwargs = dict(group=q["record_key"])
        elif ident == "eastmoney-repurchases":
            kwargs = dict(plan_id=q["plan_id"])
        else:
            kwargs = {**spec.fixed, "key": q["record_key"]}
    elif mode == "history":
        kwargs = dict(security=q["security"])
    elif mode == "directory":
        kwargs.update(after=cursor or "", limit=50)
    elif mode == "cursor":
        kwargs.update(after=cursor, limit=50)
    elif mode in ("offset", "list"):
        kwargs.update(offset=offset, limit=50)
    elif mode == "news":
        if q.get("important", "") not in ("", "true"):
            raise ValueError("新闻重要性筛选值无效")
        kwargs["important"] = q.get("important") == "true"
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
    if spec.hidden and cursor is not None:
        raise ValueError("单条详情不接受分页游标")
    if order is not None:
        kwargs['order'] = order
        if mode in ('offset', 'list'):
            kwargs.pop('offset', None)
            kwargs['after'] = cursor
    data = await method(**kwargs)
    if ident == "ths-capital" and spec.hidden and data:
        parent = next(v for v in views(ident) if v.id == spec.parent)
        if data.get("section") != parent.fixed["section"]:
            raise ValueError("记录不属于当前资本运作栏目")
    if mode in ("reason", "detail") and not isinstance(data, list):
        data = {"rows": [data] if data else []}
    if isinstance(data, list):
        data = {"rows": data}
    data = data or {"rows": []}
    rows = data.get("rows", data.get("points", []))
    rows = [dict(row) for row in rows]
    for row in rows:
        if ident in ("tdx-dividends", "tdx-additional-issues", "tdx-rights-issues"):
            row.update(row.get("data", {}))
        if "unified_code" not in row and row.get("market") in ("SH", "SZ", "BJ") and row.get("code"):
            row["unified_code"] = row["code"] + "." + row["market"]
    context = {k: data[k] for k in ("head", "coverage", "month", "expected_count", "complete",
                                   "industry_count", "publication", "snapshot", "at", "source_total", "unavailable_count", "incomplete_count") if k in data}
    next_cursor = data.get("next", data.get("next_cursor"))
    if mode in ("offset", "list") and order is None:
        next_cursor = (
            offset + len(rows)
            if len(rows) == 50 and (data.get("total") is None or offset + len(rows) < data["total"])
            else None
        )
    if order is not None and next_cursor is not None:
        next_cursor = dict(preview=sort_signature, position=next_cursor)
    return wire(
        dict(
            rows=rows,
            context=context,
            next=next_cursor,
            total=data.get("total"),
            message=data.get("message", ""),
            notice="无记录不代表已完成该范围采集。",
            storage="Redis 盘中快照" if mode == "live" else "已归档数据",
        )
    )
