from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.plugins.datasets.trade_calendar import (
    FIRST_DATE,
    month_dates,
    month_start,
    months_between,
)


class CalendarDataPlugin:
    manifest = PluginManifest("data.trade_calendar", "A 股交易日历查询",
        requires=("mysql.store",), provides=("calendar.query", "calendar.schema"),
        description="按月查看交易/休市日期，检查历史完整性与归档进度")

    def __init__(self, source="cninfo", job_key="cninfo-calendar-v1", project_id="cninfo-calendar"):
        self.source, self.job_key, self.project_id = source, job_key, project_id
        self.mysql = None

    async def start(self, context):
        self.mysql = context.get("mysql.store")
        await self.mysql.require_schema({"trade_calendar": {
            "source", "trade_date", "is_trade", "updated_at",
        }}, {"trade_calendar": ["source", "trade_date"]})
        return {"calendar.query": self, "calendar.schema": self}

    async def plan(self, today, fresh=False):
        current = today.strftime("%Y-%m")
        end = f"{today.year + 1:04d}-12"
        months = months_between(FIRST_DATE.strftime("%Y-%m"), end)
        counts = await self.mysql.control(self._coverage)
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

    async def month(self, month):
        month_start(month)
        return await self.mysql.read(self._month, month)

    def _month(self, month):
        dates = month_dates(month)
        if not dates:
            raise ValueError("日历起点为 1990-12-19")
        with self.mysql.read_engine.connect() as conn:
            data = conn.execute(text("""
                SELECT trade_date,is_trade,updated_at FROM trade_calendar
                WHERE source=:source AND trade_date BETWEEN :start AND :end ORDER BY trade_date
            """), {"source": self.source, "start": dates[0], "end": dates[-1]}).mappings()
            rows = [{"trade_date": row["trade_date"].isoformat(), "is_trade": bool(row["is_trade"]),
                     "updated_at": row["updated_at"].isoformat()} for row in data]
        return {"month": month, "rows": rows, "expected_count": len(dates), "complete": len(rows) == len(dates)}

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
