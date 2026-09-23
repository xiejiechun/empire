import json

from sqlalchemy import inspect, text

from empire.contracts.plugin import PluginManifest
from empire.plugins.datasets.trade_calendar import (
    FIRST_DATE,
    month_dates,
    month_start,
    months_between,
)


class CalendarDataPlugin:
    manifest = PluginManifest("data.trade_calendar", "A 股交易日历查询",
        requires=("mysql.store", "redis.store"), provides=("calendar.query",),
        description="按月查看交易/休市日期，检查历史完整性与归档进度")

    def __init__(self, source="cninfo", job_key="cninfo-calendar-v1"):
        self.source, self.job_key = source, job_key
        self.mysql = self.redis = None

    async def start(self, context):
        self.mysql, self.redis = context.get("mysql.store"), context.get("redis.store")
        await self.mysql.read(self._validate)
        return {"calendar.query": self}

    def _validate(self):
        with self.mysql.engine.connect() as conn:
            schema = inspect(conn)
            if "trade_calendar" not in schema.get_table_names():
                raise RuntimeError("缺少 trade_calendar 业务表，请显式建表；启动不会自动改库")
            if not {"source", "trade_date", "is_trade", "updated_at"} <= {
                    column["name"] for column in schema.get_columns("trade_calendar")}:
                raise RuntimeError("trade_calendar 字段不完整")
            if (schema.get_pk_constraint("trade_calendar")["constrained_columns"] != ["source", "trade_date"]
                    or schema.get_table_options("trade_calendar").get("mysql_engine", "").lower() != "innodb"):
                raise RuntimeError("trade_calendar 必须有来源/日期主键并使用 InnoDB")

    async def plan(self, today, fresh=False):
        current = today.strftime("%Y-%m")
        end = f"{today.year + 1:04d}-12"
        months = months_between(FIRST_DATE.strftime("%Y-%m"), end)
        counts = await self.mysql.read(self._coverage)
        selected = [month for month in months if fresh or month >= current
                    or counts.get(month, 0) != len(month_dates(month))]
        return {"months": selected, "maintenance_start": current, "end_month": end,
                "expected_count": sum(len(month_dates(month)) for month in selected)}

    def _coverage(self):
        with self.mysql.engine.connect() as conn:
            return dict(conn.execute(text("""
                SELECT DATE_FORMAT(trade_date,'%Y-%m'),COUNT(*) FROM trade_calendar
                WHERE source=:source GROUP BY DATE_FORMAT(trade_date,'%Y-%m')
            """), {"source": self.source}).all())

    async def page_status(self, batch_id, page):
        raw = await self.redis.client.get(f"{self.redis.prefix}:archive:progress:{self.job_key}")
        value = json.loads(raw) if raw else {}
        if value.get("batch_id") == batch_id and (value.get("status") == "invalid" or value.get("page", 0) >= page):
            return value
        return None

    async def month(self, month):
        month_start(month)
        return await self.mysql.read(self._month, month)

    def _month(self, month):
        dates = month_dates(month)
        if not dates:
            raise ValueError("日历起点为 1990-12-19")
        with self.mysql.engine.connect() as conn:
            data = conn.execute(text("""
                SELECT trade_date,is_trade,updated_at FROM trade_calendar
                WHERE source=:source AND trade_date BETWEEN :start AND :end ORDER BY trade_date
            """), {"source": self.source, "start": dates[0], "end": dates[-1]}).mappings()
            rows = [{"trade_date": row["trade_date"].isoformat(), "is_trade": bool(row["is_trade"]),
                     "updated_at": row["updated_at"].isoformat()} for row in data]
        return {"month": month, "rows": rows, "expected_count": len(dates), "complete": len(rows) == len(dates)}

    async def stop(self):
        self.mysql = self.redis = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
