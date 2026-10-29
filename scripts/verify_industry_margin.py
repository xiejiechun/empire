"""Five-percent complete source dates through shared proxy and formal archive/query."""

import asyncio
import hashlib
import json
import math
import random
import sys
from decimal import Decimal

import source_verification as verification
from PySide6.QtCore import QCoreApplication

from empire.features.industry_margin.contract import PROJECT, START, dates, digest
from empire.features.industry_margin.source import URL, parse
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def prepare(selection, args, report):
    pool = dates(START, args.through)
    fixed = sorted(set([START, "2016-01-02", "2016-01-04", args.through]))
    verification.require(set(fixed) <= set(pool), "日期范围不能包含未声明固定样本")
    size = max(1, math.ceil(len(pool) * 0.05))
    remainder = sorted(set(pool) - set(fixed))
    sampled = random.Random(args.date_seed).sample(remainder, max(0, size - len(fixed)))
    selection.update(
        date_pool_count=len(pool),
        date_pool_digest=digest(pool),
        date_seed=args.date_seed,
        selected_dates=sorted(fixed + sampled),
        fixed_dates=fixed,
        random_dates=sampled,
        actual_ratio=(len(fixed) + len(sampled)) / len(pool),
        start=START,
        through=args.through,
    )
    report["sample_policy"] = "2026-10-27 five-percent complete calendar-date industry snapshots"


async def verify_scope(manager, selection, args, report):
    await manager.start("collector.tdx_industry_margin")
    c, q = (
        manager.registry.get("collector.tdx_industry_margin"),
        manager.registry.get("industry_margin.query"),
    )
    chosen = selection["selected_dates"]
    expected, routes = {}, {}
    result = report["results"][PROJECT] = dict(
        pipeline_verified=False, routes=routes, responses=[], dates={}
    )
    original = c.http.request

    async def request(method, url, **kwargs):
        response = await original(method, url, **kwargs)
        try:
            verification.require(method == "POST" and url == URL, "来源请求路径改变")
            params = json.loads(kwargs["content"])["Params"]
            if params[0] == "1":
                compact = params[1]
                stamp = compact[:4] + "-" + compact[4:6] + "-" + compact[6:]
                verification.require(
                    stamp in chosen and stamp not in expected, "样本日期重复或超出范围"
                )
                rows = parse(json.loads(response.content, parse_float=Decimal))
                expected[stamp] = rows
                result["responses"].append(
                    dict(
                        date=stamp,
                        count=len(rows),
                        bytes=len(response.content),
                        sha256=hashlib.sha256(response.content).hexdigest(),
                        business_digest=digest(rows),
                    )
                )
            else:
                result["latest_date"] = parse(response.json(), latest=True)
                result["latest_response_body_bytes"] = len(response.content)
            return response
        except BaseException:
            response.close()
            raise

    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(routes)
    c.http.request = request
    try:
        cursor = await c.execute(
            fresh=True,
            start=START,
            end=args.through,
            sample_dates=chosen,
            baseline_revision=await c.checkpoint_revision(),
        )
        verification.require(cursor["phase"] == "complete", "整轮未完成归档")
        verification.require(set(expected) == set(chosen), "日期集合不完整")
        for stamp in chosen:
            actual = await q.history(stamp)
            verification.require(actual == expected[stamp], "正式查询与来源内容不一致：" + stamp)
            names, after = [], None
            while True:
                page = await q.browse(start=stamp, end=stamp, after=after, limit=17)
                names.extend(r["industry_name"] for r in page["rows"])
                after = page["next"]
                if after is None:
                    break
                verification.require(len(names) <= 256, "正式分页循环")
            verification.require(
                set(names) == {r[0] for r in actual} and len(names) == len(actual),
                "分页行业集合不符",
            )
            checks = await q.preparation_check(dict(start=stamp, end=stamp, purpose="analysis"))
            source_quality = any(v is None or Decimal(v) < 0 for row in actual for v in row[1:])
            verification.require(
                all(
                    e.status == "pass"
                    or not e.blocking
                    or (source_quality and e.criterion in ("quality", "fields"))
                    for e in checks
                ),
                "数据准备失败：" + stamp,
            )
            verification.require(
                next(e for e in checks if e.criterion == "quality").status
                == ("fail" if source_quality else "pass"),
                "来源质量未准确标注：" + stamp,
            )
            result["dates"][stamp] = dict(
                count=len(actual),
                digest=digest(actual),
                checks=[dict(criterion=e.criterion, status=e.status) for e in checks],
            )
        store = manager.registry.get("redis.store")
        verification.require(await store.client.xlen(store.stream) == 0, "本轮未成功清队")
        result.update(
            pipeline_verified=True,
            acceptance_complete=True,
            pending=0,
            logical_requests=len(chosen) + 1,
            transferred_body_bytes=sum(r["bytes"] for r in result["responses"])
            + result["latest_response_body_bytes"],
            rows=sum(len(r) for r in expected.values()),
            strict_proxy_verified=verification.strict_proxy(routes, len(chosen) + 1),
        )
    finally:
        c.http.request = original
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


if __name__ == "__main__":
    parser = verification.parser(__doc__)
    parser.add_argument("--through", required=True)
    parser.add_argument("--date-seed", type=int, default=20261030)
    args = parser.parse_args()
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    action = (
        verification.recover(args)
        if args.cleanup_only
        else verification.verify(
            args,
            verify_scope,
            subject="industry_margin",
            non_stock_scope=dict(
                unit="complete calendar date",
                reason="source returns a whole industry snapshot for one requested date",
                fixed=[],
            ),
            prepare_scope=prepare,
        )
    )
    passed = asyncio.run(action)
    print("PASS" if passed else "FAIL", flush=True)
    raise SystemExit(0 if passed else 1)
