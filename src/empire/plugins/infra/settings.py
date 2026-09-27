"""Durable user settings; scheduling cursors and request permits stay in Redis."""
import json

from sqlalchemy import text


class SettingsStore:
    def __init__(self, mysql, namespace):
        self.mysql, self.namespace = mysql, namespace

    async def load(self, kind):
        return await self.mysql.control(self._load, kind)

    def _load(self, kind):
        with self.mysql.engine.connect() as conn:
            rows = conn.execute(text("SELECT setting_key, payload FROM app_setting "
                "WHERE namespace=:namespace AND kind=:kind"),
                {"namespace": self.namespace, "kind": kind})
            return {key: json.loads(value) if isinstance(value, str) else value for key, value in rows}

    async def save(self, kind, key, value):
        await self.mysql.control(self._save, kind, key, value)

    def _save(self, kind, key, value):
        with self.mysql.engine.begin() as conn:
            self.save_in_transaction(conn, kind, key, value)

    def save_in_transaction(self, conn, kind, key, value):
        """One setting writer, also usable by explicit multi-setting maintenance."""
        params = {"namespace": self.namespace, "kind": kind, "key": key,
                  "payload": json.dumps(value, ensure_ascii=False, sort_keys=True)}
        old = conn.execute(text("SELECT payload FROM app_setting WHERE namespace=:namespace "
            "AND kind=:kind AND setting_key=:key FOR UPDATE"), params).scalar_one_or_none()
        if old is not None and (json.loads(old) if isinstance(old, str) else old) == value:
            return False
        if old is None:
            conn.execute(text("INSERT INTO app_setting (namespace,kind,setting_key,payload) "
                "VALUES (:namespace,:kind,:key,:payload)"), params)
        else:
            conn.execute(text("UPDATE app_setting SET payload=:payload, updated_at=CURRENT_TIMESTAMP(6) "
                "WHERE namespace=:namespace AND kind=:kind AND setting_key=:key"), params)
        return True
