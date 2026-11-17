"""Fixed-version pagination of complete volatile source snapshots."""
import re
from datetime import datetime
from decimal import Decimal

from empire.core.time import CHINA
from empire.features.graymarket.contract import FIELDS, day
from empire.features.graymarket.intraday_store import IntradayStore


def code_filter(code):
    code = code.strip().upper()
    if code and not re.fullmatch(r"(?:[0-9]{1,6}|[0-9]{6}\.(?:SH|SZ|BJ))", code):
        raise ValueError("请输入1至6位代码前缀或完整证券代码，例如000001.SZ")
    return code


async def browse_live(context, filters, after, order, code=""):
    stamp = day(filters[3])
    code = code_filter(code)
    redis = context.optional("redis.store")
    if redis is None:
        raise ValueError("Redis不可用，不能以日终数据代替盘中快照")
    order = order or dict(field="dark_flow", direction="desc")
    fields = ("trade_date", "unified_code", *FIELDS)
    if (not isinstance(order, dict) or set(order) != {"field", "direction"}
        or order["field"] not in fields or order["direction"] not in ("asc", "desc")):
        raise ValueError("盘中排序无效")
    version, offset = None, 0
    if after is not None:
        if (not isinstance(after, dict) or set(after) != {"version", "date", "order", "offset", "code"}
            or after["date"] != stamp or after["order"] != order or after["code"] != code
            or type(after["offset"]) is not int or not 0 <= after["offset"] <= 10000):
            raise ValueError("盘中游标不属于当前日期或排序")
        version, offset = after["version"], after["offset"]
    result = await IntradayStore(redis).read(stamp, version=version)
    if result is None:
        if after is not None:
            raise ValueError("分页快照已过期或淘汰，请返回第一页")
        return dict(rows=[], next=None, snapshot=dict(date=stamp, available=False),
                    message=f"{stamp}尚无可读取的完整盘中快照。交易日09:25起采样；请查看运行与记录是否已成功，或稍后刷新。历史日可切换已归档日榜；无快照不表示当天没有资金流。")
    rows = [dict(zip(("unified_code", *FIELDS), r, strict=True), trade_date=stamp) for r in result["rows"]]
    source_total = len(rows)
    rows = [r for r in rows if r["unified_code"].startswith(code)]
    field = order["field"]
    numeric = (*FIELDS[1:7], "source_rank")
    rows.sort(key=lambda r: (Decimal(str(r[field])) if field in numeric else r[field], r["unified_code"]),
              reverse=order["direction"] == "desc")
    following = dict(version=result["version"], date=stamp, order=order, code=code, offset=offset + 200)
    times = [datetime.fromisoformat(result[k]).astimezone(CHINA).isoformat(timespec="seconds")
             for k in ("started", "finished")]
    return dict(rows=rows[offset:offset + 200], next=following if offset + 200 < len(rows) else None,
        total=len(rows), source_total=source_total,
        snapshot=dict(date=stamp, available=True, started=times[0], finished=times[1],
                      version=result["version"]),
        message="盘中数据仅存Redis；多页采样不代表同一瞬间。翻页保持当前快照，点击刷新最新读取新快照。"
                "最多保留72小时，容量不足会提前淘汰。")
