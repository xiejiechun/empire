"""Private real-source checks for complete-market names and ST event collectors."""

import asyncio
import hashlib
import importlib
import json
import sys

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def components(family):
    require(family in ("name_changes", "st_events"), "未知事件来源范围")
    return tuple(
        importlib.import_module("empire.features." + family + "." + name)
        for name in ("contract", "source", "dataset")
    )


async def full_query(query, contract):
    rows, after, seen = [], None, set()
    while True:
        page = await query.list_events(after=after, limit=200)
        rows.extend([[r[k] for k in contract.COLUMNS] for r in page["rows"]])
        require(len(rows) < contract.CAPACITY, "正式分页查询超容量")
        after = page["next"]
        if after is None:
            break
        key = tuple(after)
        require(key not in seen, "正式查询分页游标重复")
        seen.add(key)
    return sorted(rows, key=contract.identity)


def check_sets(expected, normalized, snapshot, paged, contract):
    for values in (normalized, snapshot, paged):
        require(values == expected, "来源、规范化、SQL快照或正式分页查询完整集合内容不同")
    return contract.digest(expected)


async def verify_scope(manager, selection, args, report):
    family = args.event_family
    contract, source, dataset = components(family)
    for kind in contract.KINDS:
        ident = (
            "collector.tdx_st_" + kind
            if family == "st_events"
            else "collector.tdx_" + kind + "_renames"
        )
        await manager.start(ident)
        collector = manager.entries[ident].plugin
        query = manager.registry.get(
            ("st." if family == "st_events" else "names.") + kind + ".query"
        )
        http, ingest = collector.http, collector.ingest
        original_request, original_publish = http.request, ingest.publish_page
        captured, normalized, routes = [], {}, {}
        result = report["results"][contract.project(kind)] = dict(
            pipeline_verified=False, routes=routes
        )

        async def observed_request(method, url, **kwargs):
            response = await original_request(method, url, **kwargs)
            try:
                require(method == "POST" and url == source.URL, "来源请求偏离已审核协议")
                parameters = json.loads(kwargs["content"])["Params"]
                require(parameters[0] == contract.KINDS[kind][2], "来源栏目参数不一致")
                value = parameters[2]
                through = value[:4] + "-" + value[4:6] + "-" + value[6:]
                groups, count = source.parse(kind, response.json(), through)
                captured.append(
                    dict(
                        groups=groups,
                        count=count,
                        through=through,
                        bytes=len(response.content),
                        sha256=hashlib.sha256(response.content).hexdigest(),
                    )
                )
                return response
            except BaseException:
                response.close()
                raise

        async def observed_publish(envelopes, **kwargs):
            require(len(captured) == 1, "来源完整响应证据缺失或发生重复请求")
            mapping = (
                dataset.StDataset(kind) if family == "st_events" else dataset.NameDataset(kind)
            )
            for envelope in envelopes:
                data = mapping.normalize(envelope)
                require(
                    data["rows"] == captured[0]["groups"][data["market"]],
                    "来源与实际发布规范集合不同",
                )
                require(data["market"] not in normalized, "市场重复发布")
                normalized[data["market"]] = data["rows"]
            require(set(normalized) == set(contract.MARKETS), "实际发布市场不完整")
            return await original_publish(envelopes, **kwargs)

        tokens = (
            USE_PROXY.set(True),
            PROXY_FALLBACK.set(not args.proxy_only),
            ROUTE_COUNTS.set(routes),
        )
        http.request, ingest.publish_page = observed_request, observed_publish
        try:
            baseline = await collector.checkpoint_revision()
            outcome = await collector.execute(baseline_revision=baseline)
            require(outcome["phase"] == "complete" and len(captured) == 1, "真实来源整轮未完成")
        finally:
            http.request, ingest.publish_page = original_request, original_publish
            ROUTE_COUNTS.reset(tokens[2])
            PROXY_FALLBACK.reset(tokens[1])
            USE_PROXY.reset(tokens[0])
        snapshot, state = await query.mysql.read(query.snapshot)
        expected = sorted(
            [r for m in contract.MARKETS for r in captured[0]["groups"][m]], key=contract.identity
        )
        canonical = sorted(
            [r for m in contract.MARKETS for r in normalized[m]], key=contract.identity
        )
        paged = await full_query(query, contract)
        content_digest = check_sets(expected, canonical, snapshot, paged, contract)
        require(set(state.get("markets", {})) == set(contract.MARKETS), "SQL三市场证明不完整")
        for market in contract.MARKETS:
            proof = state["markets"][market]
            values = captured[0]["groups"][market]
            require(
                proof["digest"] == contract.digest(values)
                and proof["row_count"] == len(values)
                and proof["source_count"] == sum(r[4] for r in values),
                "SQL证明与来源集合不同",
            )
        store, archive = manager.registry.get("redis.store"), manager.registry.get("archive.worker")
        pending = await store.client.xlen(store.stream)
        require(
            pending == 0
            and not archive.blocked
            and not archive.blocked_projects
            and not archive.isolated,
            "本轮待归档或隔离非空",
        )
        checks = await query.preparation_check()
        result.update(
            pipeline_verified=True,
            acceptance_complete=True,
            strict_proxy_verified=strict_proxy(routes, 1),
            source_url=source.URL,
            source_page=source.PAGE,
            source_count=captured[0]["count"],
            response_bytes=captured[0]["bytes"],
            response_sha256=captured[0]["sha256"],
            through=captured[0]["through"],
            source_query_equal=True,
            source_set_digest=content_digest,
            sql_set_digest=contract.digest(snapshot),
            sql_count=len(snapshot),
            pending=pending,
            markets={
                m: dict(
                    rows=len(captured[0]["groups"][m]),
                    digest=contract.digest(captured[0]["groups"][m]),
                )
                for m in contract.MARKETS
            },
            date_min=min((r[1] for r in expected), default=None),
            date_max=max((r[1] for r in expected), default=None),
            preparation=[
                dict(
                    criterion=x.criterion, status=x.status, blocking=x.blocking, measured=x.measured
                )
                for x in checks
            ],
            limitation="完整来源栏目一次响应，包括历史旧代码与合法空市场；不裁定来源未公布历史、完整名称链或每日风险状态，不写生产库",
        )


def main(family, argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, event_family=family)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(
        verification.recover(args)
        if args.cleanup_only
        else verification.verify(
            args,
            verify_scope,
            subject=family,
            require_proxy=True,
            non_stock_scope=dict(
                unit="each_kind_complete_market_response",
                reason="每栏目一次全市场完整历史响应；SH/SZ/BJ含空市场均核对完整集合，非按股票请求，不能以当前名单过滤历史",
                fixed=[],
            ),
        )
    )
    print(("CLEANUP COMPLETE" if args.cleanup_only else "PASS") if passed else "FAIL", flush=True)
    return 0 if passed else 1
