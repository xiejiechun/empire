"""Business-owned suspensions.dataset."""
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import require_fixed_source
from empire.contracts.security import unified_code
from empire.core.time import CHINA, mysql_time
from empire.features.suspensions.contract import (
    EVENT_FIELDS,
    FINGERPRINT_NAMESPACE,
    FIRST_DATE,
    coverage_identity,
    fingerprint_identity,
    record_key,
    resume_key,
    validate_period,
)
from empire.features.suspensions.contract import FINGERPRINT_VERSION as FINGERPRINT_VERSION
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {"suspensions.period"}


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
    require_fixed_source('suspension_event', envelope.source)
    observed = mysql_time(envelope.observed_at)
    confirmed, written = [], 0
    key_filter = ('unified_code=:unified_code AND suspended_at=:suspended_at '
                  'AND resume_key=:resume_key AND record_key=:record_key')
    for row in data['rows']:
        params = dict(unified_code=unified_code(row['market'], row['code']),
                      suspended_at=datetime.fromisoformat(row['suspended_at']).replace(tzinfo=None),
                      resume_key=resume_key(row), record_key=record_key(row))
        old = connection.execute(text('SELECT *,RIGHT(unified_code,2) AS market,'
            'LEFT(unified_code,6) AS code FROM suspension_event WHERE ' + key_filter +
            ' FOR UPDATE'), params).mappings().first()
        prior_dates = {r[0].isoformat() for r in connection.execute(text(
            'SELECT source_date FROM suspension_source_date WHERE ' + key_filter), params)}
        incoming_dates = set(row['source_dates'])
        value = {**params, **{k: row[k] for k in ('name', 'suspension_type', 'source_note', 'reason')},
                 'resumed_at': datetime.fromisoformat(row['resumed_at']).replace(tzinfo=None) if row['resumed_at'] else None,
                 'observed': observed}
        same = old is not None and _db_content(old) == {k: row[k] for k in EVENT_FIELDS}
        stale = old is not None and old['version_observed_at'] > observed
        if old is None:
            connection.execute(text('INSERT INTO suspension_event '
                '(unified_code,name,suspended_at,resumed_at,resume_key,record_key,suspension_type,'
                'source_note,reason,version_observed_at,source_dates_known) VALUES '
                '(:unified_code,:name,:suspended_at,:resumed_at,:resume_key,:record_key,:suspension_type,'
                ':source_note,:reason,:observed,TRUE)'), value)
            written += 1
        elif not same and not stale:
            connection.execute(text('UPDATE suspension_event SET name=:name,resumed_at=:resumed_at,'
                'suspension_type=:suspension_type,source_note=:source_note,reason=:reason,'
                'version_observed_at=:observed,source_dates_known=TRUE WHERE ' + key_filter), value)
            written += 1
        elif not old['source_dates_known']:
            connection.execute(text('UPDATE suspension_event SET source_dates_known=TRUE WHERE ' + key_filter), params)
            written += 1
        added = sorted(incoming_dates - prior_dates)
        if added:
            connection.execute(text('INSERT INTO suspension_source_date '
                '(source_date,unified_code,suspended_at,resume_key,record_key) '
                'VALUES(:source_date,:unified_code,:suspended_at,:resume_key,:record_key)'),
                [{**params, 'source_date': date.fromisoformat(day)} for day in added])
            written += len(added)
        if same or not stale:
            confirmed.append(fingerprint_identity(row))

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
            "written_count": written, "confirmed": confirmed}


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
