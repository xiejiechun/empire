"""Five-percent complete trading days through shared proxy and isolated formal archive."""

import asyncio
import math
import random
import sys
from datetime import date, datetime

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.graymarket.contract import PROJECT, START, digest
from empire.features.graymarket.query import calendar_dates
from empire.features.graymarket.source import URL, DayAssembly, decode
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def prepare(selection, args, report):
    cfg = load_config(args.pool_config)
    engine = make_engine(cfg["mysql"])
    try:
        with engine.connect() as conn:
            pool = calendar_dates(conn, START, args.through)
            identities = {
                r[0].split('.')[0]: r[0]
                for r in conn.execute(text("SELECT unified_code FROM stock"))
            }
            calendar = [
                (r[0].isoformat(), int(r[1]))
                for r in conn.execute(
                    text(
                        "SELECT trade_date,is_trade FROM trade_calendar WHERE trade_date BETWEEN :a AND :b ORDER BY trade_date"
                    ),
                    dict(a=START, b=args.through),
                )
            ]
    finally:
        engine.dispose()
    fixed = sorted({pool[-1], *(["2026-05-21"] if "2026-05-21" in pool else [])})
    size = max(1, math.ceil(len(pool) * 0.05))
    chosen = sorted(fixed + random.Random(20261103).sample([d for d in pool if d not in fixed], max(0, size - len(fixed))))
    selection.update(
        date_pool_count=len(pool),
        date_pool_digest=digest(pool),
        selected_dates=chosen,
        fixed_dates=fixed,
        date_seed=20261103,
        actual_ratio=len(chosen) / len(pool),
        calendar=calendar,
        identities=identities,
    )
    report["sample_policy"] = (
        "ceil(5% of authoritative trading days); latest complete pagination counterexample fixed"
    )


async def verify_scope(manager, selection, args, report):
    await manager.start("collector.eastmoney_graymarket")
    c, q = (
        manager.registry.get("collector.eastmoney_graymarket"),
        manager.registry.get("graymarket.query"),
    )
    with q.mysql.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES(:d,:v,NOW())"),
            [dict(d=d, v=v) for d, v in selection.pop("calendar")],
        )
    expected, routes = {}, {}
    result = report["results"][PROJECT] = dict(
        pipeline_verified=False, routes=routes, responses=[], dates={}
    )
    original = c.http.request
    active_dates = set(selection["selected_dates"])

    async def request(method, url, **kw):
        response = await original(method, url, **kw)
        try:
            verification.require(method == "GET" and url == URL, "Unexpected source request")
            p = kw["params"]
            requested = date.fromisoformat(p["date"]).isoformat() if p["date"] else None
            page = decode(
                response.content,
                page=p["StartPage"],
                requested=requested,
                through=datetime.now(CHINA).date().isoformat(),
            )
            if requested is None and page.date not in selection["selected_dates"]:
                result["discovery"] = dict(date=page.date, rows=len(page.rows), bytes=len(response.content))
                return response
            verification.require(page.date in active_dates, "Source date outside sample")
            if page.number == 1:
                verification.require(page.date not in expected, "Duplicate first page")
                expected[page.date] = DayAssembly(page)
            else:
                expected[page.date].add(page)
            result["responses"].append(
                dict(
                    date=page.date,
                    page=page.number,
                    rows=len(page.rows),
                    bytes=len(response.content),
                )
            )
            return response
        except BaseException:
            response.close()
            raise

    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(routes)
    c.http.request = request
    try:
        cursor = await c.execute(
            start=START,
            end=args.through,
            sample_dates=selection["selected_dates"],
            fresh=True,
            baseline_revision=await c.checkpoint_revision(),
        )
        verification.require(cursor["phase"] == "complete", "Whole round incomplete")
        verification.require(
            set(expected) == set(selection["selected_dates"]), "Missing sample dates"
        )
        for stamp, assembly in expected.items():
            rows = assembly.finish()
            verification.require(
                all(selection['identities'].get(r[0].split('.')[0], r[0]) == r[0] for r in rows),
                "Source market mapping differs from current formal security identities",
            )
            verification.require(
                await q.history(stamp) == rows, "SQL keys/content differ from source"
            )
            checks = await q.preparation_check(dict(start=stamp, end=stamp, purpose="analysis"))
            verification.require(
                all(e.status == "pass" or not e.blocking for e in checks), "Preparation failed"
            )
            result["dates"][stamp] = dict(rows=len(rows), digest=digest(rows))
        selection.pop('identities')
        store = manager.registry.get("redis.store")
        verification.require(
            await store.client.xlen(store.stream) == 0, "Archive did not clear whole round"
        )
        if args.intraday:
            from empire.features.graymarket.intraday import collect_live, session_phase

            now = datetime.now(CHINA)
            verification.require(session_phase(now, 1) == "live", "Intraday acceptance must run in a live session")
            live_date = now.date().isoformat()
            active_dates.add(live_date)
            before = await c.ingest.checkpoint(c.job_key)
            writes = []
            def track(conn, cursor, sql, parameters, context, executemany):
                if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                    writes.append(sql.split()[0])
            event.listen(q.mysql.engine, "before_cursor_execute", track)
            try:
                live_result = await collect_live(c, now)
            finally:
                event.remove(q.mysql.engine, "before_cursor_execute", track)
            snapshot = await c.live_store.read(live_date)
            verification.require(snapshot is not None and snapshot["rows"] == expected[live_date].finish(),
                                 "Redis snapshot differs from complete source collection")
            page = await q.browse_live((3, "graymarket", "", live_date, "", ""))
            verification.require(len(page["rows"]) == 200 and page["next"], "Live formal preview missing")
            verification.require(not writes and await c.ingest.checkpoint(c.job_key) == before,
                                 "Live sampling wrote SQL or changed daily checkpoint")
            verification.require(await store.client.xlen(store.stream) == 0, "Live sample enqueued archive data")
            result["intraday"] = dict(**live_result, source_content_verified=True,
                formal_preview_verified=True, sql_dml=0, daily_checkpoint_unchanged=True,
                date=live_date, digest=digest(snapshot["rows"]))
        verification.require(
            verification.strict_proxy(routes, len(result["responses"])), "Proxy path not verified"
        )
        result.update(
            pipeline_verified=True,
            strict_proxy_verified=True,
            acceptance_complete=True,
            pending=0,
            logical_requests=len(result["responses"]),
            bytes=sum(r["bytes"] for r in result["responses"]),
        )
    finally:
        c.http.request = original
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])


if __name__ == "__main__":
    parser = verification.parser(__doc__)
    parser.add_argument("--through", required=True)
    parser.add_argument("--intraday", action="store_true", help="Also verify one complete live Redis-only sample during a trading session")
    args = parser.parse_args()
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(
        verification.verify(
            args,
            verify_scope,
            subject="graymarket",
            require_proxy=True,
            non_stock_scope=dict(
                unit="complete trading day", reason="Whole daily stock ranking pages", fixed=[]
            ),
            prepare_scope=prepare,
        )
    )
    raise SystemExit(0 if passed else 1)
