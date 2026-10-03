"""TDX Shanghai/Shenzhen A-share suspension events and contiguous coverage."""
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import CHINA, mysql_time
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {"suspensions.period"}
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


def normalize(envelope):
    payload = envelope.raw_payload
    if set(payload) != {"page", "period", "start_date", "end_date", "checked_dates", "rows"}:
        raise ValueError("停复牌批次字段无效")
    page = payload["page"]
    if type(page) is not int or not 1 <= page <= 10000:
        raise ValueError("停复牌批次序号无效")
    if not isinstance(payload["period"], str) or not re.fullmatch(r"\d{4}-\d{2}", payload["period"]):
        raise ValueError("停复牌月份无效")
    if not all(isinstance(payload[key], str) for key in ("start_date", "end_date")):
        raise ValueError("停复牌批次日期无效")
    if payload["start_date"][:7] != payload["period"] or payload["end_date"][:7] != payload["period"]:
        raise ValueError("停复牌批次必须位于声明的单一自然月")
    if not isinstance(payload["checked_dates"], list):
        raise ValueError("停复牌已检查日期无效")
    rows = validate_period(payload["start_date"], payload["end_date"], payload["checked_dates"], payload["rows"])
    return {**payload, "rows": rows, "row_count": len(rows),
            "coverage_key": coverage_identity(payload["start_date"], payload["end_date"])}


def canonical_payload(envelope, normalized):
    return {key: normalized[key] for key in (
        "page", "period", "start_date", "end_date", "checked_dates", "rows")}


def _db_content(row):
    return {
        "market": row["market"], "code": row["code"], "name": row["name"],
        "suspended_at": row["suspended_at"].replace(tzinfo=CHINA).isoformat(timespec="minutes"),
        "resumed_at": (row["resumed_at"].replace(tzinfo=CHINA).isoformat(timespec="minutes")
                       if row["resumed_at"] else None),
        "suspension_type": row["suspension_type"], "source_note": row["source_note"],
        "reason": row["reason"],
    }


def write(connection, envelope, data):
    rows = data["rows"]
    observed = mysql_time(envelope.observed_at)
    confirmed, inserts, updates = [], [], []
    for row in rows:
        params = {"source": envelope.source, "market": row["market"], "code": row["code"],
                  "resume_key": resume_key(row), "record_key": record_key(row),
                  "suspended_at": datetime.fromisoformat(row["suspended_at"]).replace(tzinfo=None)}
        old = connection.execute(text("""
            SELECT market,code,name,suspended_at,resumed_at,suspension_type,source_note,reason,version_observed_at,
                   source_dates
            FROM suspension_event WHERE source=:source AND market=:market
              AND code=:code AND suspended_at=:suspended_at AND resume_key=:resume_key
              AND record_key=:record_key FOR UPDATE
        """), params).mappings().first()
        identity = fingerprint_identity(row)
        value = {**params, "name": row["name"],
                 "resumed_at": (datetime.fromisoformat(row["resumed_at"]).replace(tzinfo=None)
                                if row["resumed_at"] else None),
                 "suspension_type": row["suspension_type"], "source_note": row["source_note"],
                 "reason": row["reason"], "version_observed_at": observed,
                 'source_dates': json.dumps(row['source_dates'])}
        if old is None:
            inserts.append(value)
            confirmed.append(identity)
        else:
            prior_dates = old['source_dates'] or []
            if isinstance(prior_dates, str):
                prior_dates = json.loads(prior_dates)
            merged_dates = sorted(set(prior_dates) | set(row['source_dates']))
            same = _db_content(old) == {key: row[key] for key in EVENT_FIELDS}
            stale = old['version_observed_at'] > observed
            value['source_dates'] = json.dumps(merged_dates)
            if stale or same:
                for key in ('name', 'resumed_at', 'suspension_type', 'source_note', 'reason',
                            'version_observed_at'):
                    value[key] = old[key]
            if merged_dates != prior_dates or (not same and not stale):
                updates.append(value)
            if same or not stale:
                confirmed.append(identity)
    if inserts:
        connection.execute(text("""
            INSERT INTO suspension_event
              (source,market,code,name,suspended_at,resumed_at,resume_key,record_key,
               suspension_type,source_note,reason,version_observed_at,source_dates)
            VALUES
              (:source,:market,:code,:name,:suspended_at,:resumed_at,:resume_key,:record_key,
               :suspension_type,:source_note,:reason,:version_observed_at,:source_dates)
        """), inserts)
    if updates:
        connection.execute(text("""
            UPDATE suspension_event SET name=:name,resumed_at=:resumed_at,
              suspension_type=:suspension_type,source_note=:source_note,reason=:reason,
              version_observed_at=:version_observed_at,source_dates=:source_dates
            WHERE source=:source AND market=:market AND code=:code AND suspended_at=:suspended_at
              AND resume_key=:resume_key AND record_key=:record_key
        """), updates)

    coverage_key = data["coverage_key"]
    if data.get("confirm_coverage"):
        previous = data["archive_state"].get("coverage", {})
        prior = date.fromisoformat(previous["through"]) if previous.get("through") else None
        start = date.fromisoformat(data["start_date"])
        if prior is None and start != FIRST_DATE:
            raise ValueError("停复牌初始覆盖必须从 2004-12-27 开始")
        if prior is not None and start > prior + timedelta(days=1):
            raise ValueError("停复牌覆盖存在日期缺口")
        confirmed.append(coverage_key)
    return {"status": "complete", "row_count": data["row_count"],
            "written_count": len(inserts) + len(updates), "confirmed": confirmed}


def fingerprint_plan(envelope, data):
    version = [envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")]
    plan = {fingerprint_identity(row): (row, version) for row in data["rows"]}
    plan[data["coverage_key"]] = ({"checked_dates": data["checked_dates"]}, version)
    return FINGERPRINT_NAMESPACE, plan


def fingerprint_subset(data, identities):
    coverage = data["coverage_key"] in identities
    return {**data, "rows": [row for row in data["rows"] if fingerprint_identity(row) in identities],
            "confirm_coverage": coverage}


def archive_state(envelope, data, outcome, previous):
    coverage = dict(previous.get("coverage", {}))
    if data["coverage_key"] in outcome["confirmed"]:
        end = data["end_date"]
        if not coverage.get("through") or end >= coverage["through"]:
            coverage = {"from": FIRST_DATE.isoformat(),
                        "through": max(end, coverage.get("through", end)),
                        "confirmed_at": envelope.observed_at.isoformat(timespec="microseconds")}
    return {"record_identity": "source-record-v3", "source_calendar_version": 1, "collection_integrity_version": 2,
            "progress": confirmed_page(envelope, data, previous), "coverage": coverage}
