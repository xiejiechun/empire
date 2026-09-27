"""One SQL-confirmed state per project; called only on an archive cache miss."""
import json
from datetime import UTC, datetime

from sqlalchemy import text

from empire.core.time import mysql_time


def read_state(connection, namespace, project_id, source, *, lock=False):
    row = connection.execute(text("""
        SELECT source,payload FROM collection_state
        WHERE namespace=:namespace AND project_id=:project_id
    """ + (" FOR UPDATE" if lock else "")),
        {"namespace": namespace, "project_id": project_id}).mappings().first()
    if not row:
        return {}
    if row["source"] != source:
        raise ValueError("采集项目的来源与已归档状态不一致")
    return json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]


def save_state(connection, namespace, project_id, source, dataset, payload, previous):
    if payload == previous:
        return
    connection.execute(text("""
        INSERT INTO collection_state(namespace,project_id,source,dataset,payload,updated_at)
        VALUES(:namespace,:project_id,:source,:dataset,:payload,:updated_at)
        ON DUPLICATE KEY UPDATE dataset=VALUES(dataset),payload=VALUES(payload),updated_at=VALUES(updated_at)
    """), {"namespace": namespace, "project_id": project_id, "source": source, "dataset": dataset,
            "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "updated_at": mysql_time(datetime.now(UTC))})


def confirmed_page(envelope, data, previous):
    value = {"batch_id": envelope.batch_id, "page": data["page"], "status": "complete",
             "row_count": data["row_count"], "error_text": "",
             "observed_at": envelope.observed_at.isoformat(timespec="microseconds")}
    old = previous.get("progress", {})
    if old.get("observed_at", "") > value["observed_at"]:
        return old
    if old.get("batch_id") == value["batch_id"] and old.get("page", 0) > value["page"]:
        return old
    return value


class CollectionState:
    def __init__(self, mysql, namespace):
        self.mysql, self.namespace = mysql, namespace

    def read(self, source, project_id):
        with self.mysql.engine.connect() as connection:
            return read_state(connection, self.namespace, project_id, source)

    async def page_status(self, redis, source, job_key, project_id, batch_id, page):
        raw = await redis.client.get(f"{redis.prefix}:archive:progress:{job_key}")
        value = json.loads(raw) if raw else (
            await self.mysql.control(self.read, source, project_id)).get("progress", {})
        if value.get("batch_id") == batch_id and (
                value.get("status") == "invalid" or value.get("page", 0) >= page):
            return value
        return None

    def writer(self, catalog, full_data):
        def archive(connection, envelope, data):
            project = catalog.project_id(envelope)
            previous = read_state(connection, self.namespace, project, envelope.source, lock=True)
            outcome = catalog.write(connection, envelope, {**data, "archive_state": previous})
            # Rejected versions cannot advance either persisted progress or publication.
            if outcome["confirmed"] or not data.get("rows"):
                payload = catalog.archive_state(envelope, full_data, outcome, previous)
                save_state(connection, self.namespace, project, envelope.source,
                           catalog.fingerprint_plan(envelope, data)[0], payload, previous)
            return outcome
        return archive
