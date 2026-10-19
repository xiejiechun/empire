"""Business-owned suspensions.contract."""
import calendar
import hashlib
import json
import re
from datetime import date, datetime, timedelta

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import CHINA

FINGERPRINT_NAMESPACE = "suspensions"


FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)


FIRST_DATE = date(2004, 12, 27)


EVENT_FIELDS = {
    "market", "code", "name", "suspended_at", "resumed_at",
    "suspension_type", "source_note", "reason",
}


def event_identity(row):
    return "|".join((row["market"], row["code"], row["suspended_at"],
                     row["resumed_at"] or "unknown", record_key(row)))


def record_key(row):
    note, reason = row["source_note"], row["reason"]
    value = f"{len(note)}:{note}{len(reason)}:{reason}"
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint_identity(row):
    dates = hashlib.sha256(json.dumps(row['source_dates'], separators=(',', ':')).encode()).hexdigest()
    return event_identity(row) + '|dates:' + dates


def resume_key(row):
    return datetime.fromisoformat(row['resumed_at']).replace(tzinfo=None) if row['resumed_at'] else datetime(1000, 1, 1)


def coverage_identity(start, end):
    return f"coverage:{start}:{end}"


def _source_datetime(value, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError("停复牌时间字段无效")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=CHINA)
    except ValueError:
        raise ValueError("停复牌时间须为 YYYY-MM-DD HH:MM") from None
    return parsed.isoformat(timespec="minutes")


def classify_suspension(note, suspended_at, resumed_at):
    if not isinstance(note, str) or len(note) > 100:
        raise ValueError("停牌说明类型无效或过长")
    note = note.strip()
    start = datetime.fromisoformat(suspended_at)
    end = datetime.fromisoformat(resumed_at) if resumed_at else None
    partial = bool(re.search(r"小时|分钟|半天|半日|上午|下午|盘中", note))
    full = bool(re.search(r"停牌\s*(?:[一二三四五六七八九十\d]+\s*天|一天)|今起停牌|继续停牌|全天停牌", note))
    if end and end.date() == start.date():
        # TDX historical labels may say "停牌1天" for an explicit one-hour
        # interval. Preserve the label, but classify by the supplied times.
        return "intraday"
    if partial:
        return "intraday"
    if full or end is None or end.date() > start.date():
        return "full_day"
    raise ValueError("无法判断全天停牌或盘中临停")


def source_security(row):
    market = {0: "SZ", 1: "SH", 2: "BJ"}.get(row["sc"])
    if market is None or not isinstance(row["code"], str) or not re.fullmatch(r"\d{6}", row["code"]):
        raise ValueError("停复牌市场或证券代码无效")
    is_a_share = (market == "SZ" and row["code"].startswith(("0", "3"))) or (
        market == "SH" and row["code"].startswith("6")) or (
        market == "BJ" and row["code"].startswith(("4", "8", "920")))
    return market, is_a_share


def normalize_source_row(row):
    if not isinstance(row, dict) or set(row) != {"sc", "code", "name", "fprq", "sj", "sjcontent", "tprq"}:
        raise ValueError("通达信停复牌字段结构无效")
    market, is_a_share = source_security(row)
    if not is_a_share or market == "BJ":
        return None
    if not isinstance(row["name"], str) or not row["name"].strip() or len(row["name"]) > 100:
        raise ValueError("停复牌证券简称无效")
    reason = "" if row["sjcontent"] is None else row["sjcontent"]
    if not isinstance(reason, str) or len(reason) > 500:
        raise ValueError("停牌原因无效")
    suspended = _source_datetime(row["tprq"])
    resumed = _source_datetime(row["fprq"], nullable=True)
    if resumed and datetime.fromisoformat(resumed) < datetime.fromisoformat(suspended):
        raise ValueError("复牌时间早于停牌时间")
    # Optional historical description: preserve absence as an empty string,
    # not the literal "None" or an invented duration/resumption time.
    note = "" if row["sj"] is None else row["sj"]
    if not isinstance(note, str):
        raise ValueError("停牌说明类型无效")
    note = note.strip()
    return {
        "market": market,
        "code": row["code"],
        "name": row["name"].strip(),
        "suspended_at": suspended,
        "resumed_at": resumed,
        "suspension_type": classify_suspension(note, suspended, resumed),
        "source_note": note,
        "reason": reason.strip(),
    }


def _dates(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first < FIRST_DATE or last < first:
        raise ValueError("停复牌采集日期范围无效")
    return [(first + timedelta(days=index)).isoformat() for index in range((last - first).days + 1)]


def validate_period(start, end, checked_dates, rows):
    expected = _dates(start, end)
    if checked_dates != expected:
        raise ValueError("停复牌批次日期缺失、重复或乱序")
    if not isinstance(rows, list):
        raise ValueError("停复牌事件必须是列表")
    clean, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != EVENT_FIELDS | {'source_dates'}:
            raise ValueError("停复牌事件仅允许规范业务字段")
        dates = row['source_dates']
        if (not isinstance(dates, list) or not dates
                or any(not isinstance(day, str) or day not in expected for day in dates)
                or dates != sorted(set(dates))):
            raise ValueError('停复牌来源日期须有序、唯一且在已检查范围内')
        normalized = normalize_source_row({
            "sc": 0 if row["market"] == "SZ" else 1 if row["market"] == "SH" else row["market"],
            "code": row["code"], "name": row["name"], "fprq": (
                datetime.fromisoformat(row["resumed_at"]).strftime("%Y-%m-%d %H:%M")
                if row["resumed_at"] else None),
            "sj": row["source_note"], "sjcontent": row["reason"],
            "tprq": datetime.fromisoformat(row["suspended_at"]).strftime("%Y-%m-%d %H:%M"),
        })
        if normalized != {key: row[key] for key in EVENT_FIELDS}:
            raise ValueError("停复牌事件未按规范格式提交")
        identity = event_identity(row)
        if identity in seen:
            raise ValueError("停复牌业务键重复")
        seen.add(identity)
        clean.append(dict(row))
    clean.sort(key=lambda item: (item["suspended_at"], item["market"], item["code"],
                                 item["resumed_at"] or "", record_key(item)))
    return clean


def periods_between(start, end):
    if start > end:
        return []
    result = []
    current = start
    while current <= end:
        month_end = current.replace(day=calendar.monthrange(current.year, current.month)[1])
        period_end = min(month_end, end)
        result.append({"period": current.strftime("%Y-%m"), "start_date": current.isoformat(),
                       "end_date": period_end.isoformat()})
        current = period_end + timedelta(days=1)
    return result
