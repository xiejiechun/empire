"""One complete market (ceil(4*5%)) through proxy, Redis, archive and formal SQL query."""

import asyncio
import hashlib
import json
import sys
from decimal import Decimal

import source_verification as verification
from PySide6.QtCore import QCoreApplication

from empire.features.market_margin.contract import PROJECT, digest
from empire.features.market_margin.source import URL, parse
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def prepare(selection, args, report):
    selection.update(
        market_pool=["99", "3", "2", "4"],
        selected_markets=["99"],
        seed=None,
        sample_ratio=0.25,
        policy="ceil(4*0.05)=1 complete market; fixed combined-market boundary",
    )


async def verify_scope(manager, selection, args, report):
    await manager.start("collector.ths_market_margin")
    c, q = (
        manager.registry.get("collector.ths_market_margin"),
        manager.registry.get("market_margin.query"),
    )
    original, expected, routes, responses = c.http.request, {}, {}, []

    async def request(method, url, **kw):
        response = await original(method, url, **kw)
        try:
            verification.require(
                method == "GET" and url == URL.format(code="99"), "样本超出声明市场"
            )
            rows = parse(json.loads(response.content, parse_float=Decimal), "2200-01-01", "99")
            expected["99"] = rows
            responses.append(
                dict(
                    market="99",
                    rows=len(rows),
                    first=rows[0][0],
                    last=rows[-1][0],
                    bytes=len(response.content),
                    sha256=hashlib.sha256(response.content).hexdigest(),
                    digest=digest(rows),
                )
            )
            return response
        except BaseException:
            response.close()
            raise

    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(routes)
    c.http.request = request
    try:
        result = await c.execute(
            markets=["99"], fresh=True, baseline_revision=await c.checkpoint_revision()
        )
        verification.require(result["phase"] == "complete", "本轮未完成")
        rows = await q.history("99")
        verification.require(rows == expected["99"], "完整日期或数值与来源不等")
        days, cursor = [], None
        while True:
            page = await q.browse(search="99", after=cursor)
            days.extend(r["trade_date"] for r in page["rows"])
            cursor = page["next"]
            if cursor is None:
                break
        verification.require(days == list(reversed([r[0] for r in rows])), "正式分页日期集合错误")
        store = manager.registry.get("redis.store")
        verification.require(await store.client.xlen(store.stream) == 0, "成功后消息未清队")
        report["results"][PROJECT] = dict(
            pipeline_verified=True,
            acceptance_complete=True,
            pending=0,
            strict_proxy_verified=verification.strict_proxy(routes, 1),
            routes=routes,
            responses=responses,
            untested_markets=["3", "2", "4"],
            business_rows=len(rows),
        )
    finally:
        c.http.request = original
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])


if __name__ == "__main__":
    args = verification.parser(__doc__).parse_args()
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    action = (
        verification.recover(args)
        if args.cleanup_only
        else verification.verify(
            args,
            verify_scope,
            subject="market_margin",
            non_stock_scope=dict(
                unit="complete market", reason="four complete fixed market series", fixed=[]
            ),
            prepare_scope=prepare,
        )
    )
    passed = asyncio.run(action)
    print("PASS" if passed else "FAIL")
    raise SystemExit(0 if passed else 1)
