"""Five-percent complete securities through the shared proxy and archive path."""

import asyncio
import hashlib
import json
import math
import random
import sys
from datetime import datetime
from decimal import Decimal

import source_verification as verification
from PySide6.QtCore import QCoreApplication

from empire.core.time import CHINA
from empire.features.margin.contract import PROJECT, digest
from empire.features.margin.source import URL, parse
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def prepare(selection, args, report):
    pool = selection["pool"]
    fixed = sorted(set(selection["fixed"]))
    size = max(1, math.ceil(len(pool) * 0.05))
    by_code = {s["unified_code"]: s for s in pool}
    remainder = sorted(set(by_code) - set(fixed))
    sampled = random.Random(args.seed).sample(remainder, max(0, size - len(fixed)))
    selection.update(
        selected=[by_code[c] for c in sorted(fixed + sampled)],
        random=sampled,
        random_count=len(sampled),
        target_ratio=0.05,
        actual_ratio=(len(fixed) + len(sampled)) / len(pool),
        algorithm="fixed regressions first; random.Random(seed).sample sorted remainder to ceil(pool*0.05)",
    )
    report["sample_policy"] = (
        "2026-10-27 five-percent complete securities; supersedes legacy sample_30 metadata"
    )


async def verify_scope(manager, selection, args, report):
    await manager.start("collector.tdx_margin")
    c, q = manager.registry.get("collector.tdx_margin"), manager.registry.get("margin.query")
    codes = [s["unified_code"] for s in selection["selected"]]
    by_code = {code[:6]: code for code in codes}
    expected, routes = {}, {}
    result = report["results"][PROJECT] = dict(
        pipeline_verified=False, routes=routes, responses=[], stocks={}
    )
    original = c.http.request

    async def request(method, url, **kwargs):
        response = await original(method, url, **kwargs)
        try:
            verification.require(method == "POST" and url == URL, "请求来源改变")
            params = json.loads(kwargs["content"])["Params"]
            code = by_code[params[2]]
            verification.require(params[-1] == "10000", "每页参数不是10000")
            rows = parse(
                json.loads(response.content, parse_float=Decimal),
                datetime.now(CHINA).date().isoformat(),
            )
            expected[code] = rows
            result["responses"].append(
                dict(
                    code=code,
                    count=len(rows),
                    bytes=len(response.content),
                    sha256=hashlib.sha256(response.content).hexdigest(),
                    first=rows[-1][0] if rows else None,
                    last=rows[0][0] if rows else None,
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
            fresh=True, codes=codes, baseline_revision=await c.checkpoint_revision()
        )
        verification.require(cursor["phase"] == "complete", "未完成整轮归档")
        verification.require(set(expected) == set(codes), "证券集合不完整")
        for code in codes:
            actual = await q.history(code)
            verification.require(actual == expected[code], "正式查询与来源集合或内容不同：" + code)
            dates, after = [], None
            while True:
                page = await q.browse(code=code, after=after)
                dates.extend(r["trade_date"] for r in page["rows"])
                after = page["next"]
                if after is None:
                    break
                verification.require(len(dates) <= 10000, "浏览分页循环")
            verification.require(dates == [r[0] for r in actual], "正式分页日期集合不等")
            checks = {}
            for req in ("financing", "short_lending"):
                evidence = await q.preparation_check(
                    req, {"codes": [code[:6]], "purpose": "analysis"}
                )
                verification.require(
                    all(e.status == "pass" or not e.blocking for e in evidence),
                    "数据准备必需项失败",
                )
                checks[req] = [dict(criterion=e.criterion, status=e.status) for e in evidence]
            result["stocks"][code] = dict(count=len(actual), digest=digest(actual), checks=checks)
            print(
                json.dumps(
                    dict(
                        verified=code,
                        rows=len(actual),
                        completed=len(result["stocks"]),
                        total=len(codes),
                    )
                ),
                flush=True,
            )
        store = manager.registry.get("redis.store")
        verification.require(await store.client.xlen(store.stream) == 0, "本轮未清队")
        result.update(
            pipeline_verified=True,
            strict_proxy_verified=verification.strict_proxy(routes, len(codes)),
            acceptance_complete=True,
            pending=0,
            logical_requests=len(result["responses"]),
            transferred_body_bytes=sum(r["bytes"] for r in result["responses"]),
        )
    finally:
        c.http.request = original
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


if __name__ == "__main__":
    args = verification.parser(__doc__).parse_args()
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    action = (
        verification.recover(args)
        if args.cleanup_only
        else verification.verify(
            args,
            verify_scope,
            subject="margin",
            fixed_codes=("688256.SH", "000001.SZ"),
            minimum_random=0,
            require_proxy=True,
            prepare_scope=prepare,
        )
    )
    passed = asyncio.run(action)
    print("PASS" if passed else "FAIL", flush=True)
    raise SystemExit(0 if passed else 1)
