"""Business-owned suspensions.query."""
import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.business_schema import require_fixed_source, schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.core.time import CHINA
from empire.features.suspensions.contract import FIRST_DATE, periods_between
from empire.plugins.infra.collection_state import read_state


class SuspensionDataPlugin:
    preparation = (PreparationContribution(
        "suspensions", "suspensions.query", "通达信", "tdx-suspensions",
        "tdx-suspensions-v1", "suspensions.period", "collector.tdx_suspensions",
        ("tests/test_tdx_suspensions.py", "tests/test_all_collector_prefetch.py"), ("tests/integration/test_suspension_archive.py", "tests/integration/test_prefetch_pipeline.py"), cache_revision=2),)

    manifest = PluginManifest(
        "data.suspensions", "沪深 A 股历史停复牌查询",
        requires=("mysql.store",), provides=("suspensions.query", "suspensions.schema"),
        description="查询通达信停复牌事件、生成连续日期补采计划并检查准备状态",
    )

    def __init__(self, source="tdx", job_key="tdx-suspensions-v1",
                 project_id="tdx-suspensions", namespace="empire", archive_settings=None):
        self.source, self.job_key, self.project_id = source, job_key, project_id
        self.namespace, self.mysql = namespace, None
        self.context, self.archive_settings = None, archive_settings or {}

    async def start(self, context):
        self.context = context
        self.mysql = context.get("mysql.store")
        require_fixed_source('suspension_event', self.source)
        await self.mysql.require_schema(*schema_contract('suspension_event', 'name','resumed_at','source_dates_known','suspension_type','source_note','reason','version_observed_at'))
        await self.mysql.require_schema(*schema_contract('suspension_source_date'))
        state = await self.mysql.control(self._state)
        if state.get('identity_migration_pending') or (state and (
                state.get('source_calendar_version') != 1 or state.get('collection_integrity_version') != 2)):
            raise RuntimeError('停复牌身份迁移未完成，请重新运行显式维护入口')
        return {"suspensions.query": self, "suspensions.schema": self}

    def _state(self):
        with self.mysql.engine.connect() as conn:
            return read_state(conn, self.namespace, self.project_id, self.source)

    async def plan(self, today, fresh=False):
        if not isinstance(today, date) or today < FIRST_DATE:
            raise ValueError("停复牌采集截止日期无效")
        state = await self.mysql.control(self._state)
        coverage = state.get("coverage", {})
        through = date.fromisoformat(coverage["through"]) if coverage.get("through") else None
        if through and (through < FIRST_DATE or through > today):
            raise ValueError("停复牌 SQL 连续覆盖上界无效")
        start = FIRST_DATE if fresh or through is None else through
        periods = periods_between(start, today)
        return {"periods": periods, "start_date": start.isoformat(), "end_date": today.isoformat(),
                "expected_days": (today - start).days + 1,
                "coverage_through": through.isoformat() if through else None}

    async def list_events(self, market="", code="", start=None, end=None, limit=200, offset=0,
                          sort_by="suspended_at", direction="desc"):
        if market not in ("", "SH", "SZ") or (code and (not code.isdigit() or len(code) > 6)):
            raise ValueError("停复牌查询市场或代码无效")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("停复牌查询条数须为 1～500")
        if type(offset) is not int or offset < 0:
            raise ValueError("停复牌查询偏移须为非负整数")
        if sort_by not in ("code", "name", "market", "suspended_at", "resumed_at",
                           "suspension_type", "source_note", "reason") or direction not in ("asc", "desc"):
            raise ValueError("停复牌排序字段或方向无效")
        first = date.fromisoformat(start) if start else FIRST_DATE
        last = date.fromisoformat(end) if end else datetime.now(CHINA).date()
        if first < FIRST_DATE or last < first:
            raise ValueError("停复牌查询日期范围无效")
        return await self.mysql.read(self._list_events, market, code, first, last, limit, offset,
                                     sort_by, direction)

    def _list_events(self, market, code, start, end, limit, offset, sort_by, direction):
        filters = ["TRUE"]
        params = {"source": self.source, "start": start,
                  "end": end + timedelta(days=1), "day": start.isoformat(),
                  "limit": limit, "offset": offset}
        if market:
            filters.append("RIGHT(s.unified_code,2)=:market")
            params["market"] = market
        if code:
            filters.append("s.unified_code LIKE :code")
            params["code"] = code + "%"
        with self.mysql.read_engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT RIGHT(s.unified_code,2) AS market,LEFT(s.unified_code,6) AS code,name,suspended_at,resumed_at,suspension_type,source_note,reason
                FROM suspension_event s JOIN (
                    SELECT DISTINCT unified_code,suspended_at,resume_key,record_key
                    FROM suspension_source_date FORCE INDEX(PRIMARY)
                    WHERE source_date>=:start AND source_date<:end
                ) d USING (unified_code,suspended_at,resume_key,record_key)
                WHERE {' AND '.join(filters)}
                ORDER BY {sort_by} {direction},suspended_at DESC,market,code,resume_key,record_key
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()
        return [{key: value.isoformat() if hasattr(value, "isoformat") else value
                 for key, value in row.items()} for row in rows]

    async def calendar_coverage(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                state = read_state(conn, self.namespace, self.project_id, self.source)
                return state.get('coverage', {})
        coverage = await self.mysql.read(read)
        from empire.features.suspensions.coverage import confirmed_coverage
        store = self.context.optional('redis.store') if self.context else None
        return await confirmed_coverage(coverage, store, self.archive_settings, datetime.now(CHINA))

    async def source_month(self, month, market='', code=''):
        year, number = map(int, month.split('-'))
        lower, upper = date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])
        if market not in ('', 'SH', 'SZ') or code and (not code.isascii() or not code.isdigit() or len(code) > 6):
            raise ValueError('来源月历证券条件无效')
        def read():
            with self.mysql.read_engine.begin() as conn:
                state = read_state(conn, self.namespace, self.project_id, self.source)
                clauses = ['source_date BETWEEN :lower AND :upper']
                if market:
                    clauses.append('RIGHT(unified_code,2)=:market')
                if code:
                    clauses.append('unified_code LIKE :code')
                counts = conn.execute(text('SELECT source_date,COUNT(*) AS count FROM suspension_source_date WHERE '
                    + ' AND '.join(clauses) + ' GROUP BY source_date ORDER BY source_date LIMIT 31'),
                    dict(lower=lower, upper=upper, market=market, code=code+'%')).mappings()
                return dict(month=month, counts={r['source_date'].isoformat(): r['count'] for r in counts},
                            coverage=state.get('coverage', {}))
        return await self.mysql.read(read)

    async def preparation_check(self):
        from empire.features.suspensions.audit import check_suspensions
        coverage = await self.calendar_coverage()
        return await self.mysql.read(check_suspensions, self, coverage)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
