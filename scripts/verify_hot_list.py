"""Random thirty stocks plus fixed regressions, complete source-available histories."""

import asyncio
import hashlib
import json
import sys
from decimal import Decimal

import httpx
import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.features.hot_list.contract import PROJECT, digest
from empire.features.hot_list.source import URL, parse_detail, parse_directory
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


async def verify_scope(manager, selection, args, report):
    await manager.start("collector.tdx_hot_list")
    collector = manager.registry.get("collector.tdx_hot_list")
    query = manager.registry.get("hot_list.query")
    http, ingest = collector.http, collector.ingest
    original_request, original_publish = http.request, ingest.publish_page
    directories, details, normalized, routes = {}, {}, {}, {}
    codes = [s["unified_code"] for s in selection["selected"]]
    by_code = {c[:6]: c for c in codes}
    result = report["results"][PROJECT] = dict(
        pipeline_verified=False, routes=routes, responses=[], stocks={}
    )

    async def request(method, url, **kwargs):
        response = await original_request(method, url, **kwargs)
        try:
            require(method == "POST" and url == URL, "来源协议改变")
            params = json.loads(kwargs["content"])["Params"]
            code = by_code[params[1]]
            body = json.loads(response.content, parse_float=Decimal)
            if params[0] == "0":
                from datetime import datetime

                from empire.core.time import CHINA

                values = parse_directory(body, code, datetime.now(CHINA).date().isoformat())
                require(code not in directories or directories[code] == values, "恢复目录已经改变")
                directories[code] = values
                print(
                    json.dumps(
                        dict(
                            directory_stock=code,
                            dates=len(values),
                            requests=len(result["responses"]) + 1,
                        )
                    ),
                    flush=True,
                )
            else:
                key = (code, params[2])
                require(
                    key not in normalized and params[2] in directories[code],
                    "已入队详情重复或目录关联丢失",
                )
                details[key] = parse_detail(body)
            result["responses"].append(
                dict(
                    params=params,
                    bytes=len(response.content),
                    sha256=hashlib.sha256(response.content).hexdigest(),
                )
            )
            return response
        except BaseException:
            response.close()
            raise

    async def publish(envelopes, **kwargs):
        for e in envelopes:
            value = query.mapping.normalize(e)
            if value["mode"] == "directory":
                require(value["value"]["dates"] == directories[value["code"]], "目录规范化集合不等")
            if value["mode"] == "detail":
                key = value["code"], value["date"]
                require(
                    key not in normalized and value["value"] == details[key], "来源与规范明细不等"
                )
                normalized[key] = digest(value["value"])
        return await original_publish(envelopes, **kwargs)

    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(routes)
    http.request, ingest.publish_page = request, publish
    try:
        baseline = await collector.checkpoint_revision()
        result["network_interruptions"] = []
        for attempt in range(4):
            try:
                cursor = await collector.execute(
                    fresh=attempt == 0, codes=codes, baseline_revision=baseline
                )
                break
            except httpx.TransportError as exc:
                records = getattr(collector, "records", None)
                errors = await records.list_error_summaries(PROJECT, limit=100) if records else {}
                result["network_interruptions"].append(
                    dict(
                        attempt=attempt + 1,
                        error=type(exc).__name__,
                        error_records=errors.get("rows", []),
                    )
                )
                if attempt == 3:
                    raise
                print(
                    json.dumps(dict(resume_after_network_failure=attempt + 1, wait_seconds=45)),
                    flush=True,
                )
                await asyncio.sleep(45)
        require(cursor["phase"] == "complete", "整轮未完成归档确认")
        require(set(directories) == set(codes), "证券集合不完整")
        require(
            set(details)
            == set(normalized)
            == {(c, d) for c, dates in directories.items() for d in dates},
            "完整历史详情集合不同",
        )
        for code in codes:
            heads = await query.day_heads(code)
            require(set(heads) == set(directories[code]), "SQL日期目录不同")
            statuses = {}
            for stamp in directories[code]:
                data = await query.detail(code, stamp)
                content = dict(
                    reasons=data["reasons"],
                    seats=data["seats"],
                    auxiliary=data["auxiliary"],
                    status=data["detail_status"],
                )
                require(digest(content) == normalized[code, stamp], "正式查询与来源完整内容不同")
                statuses[stamp] = data["detail_status"]
            pages, after = [], None
            while True:
                page = await query.browse(code=code, after=after)
                pages.extend(r["list_date"] for r in page["rows"])
                after = page["next"]
                if after is None:
                    break
                require(len(pages) <= 20000, "浏览分页循环")
            require(pages == directories[code], "正式浏览集合不同")
            checks = await query.preparation_check(
                request=dict(codes=[code[:6]], purpose="analysis")
            )
            result["stocks"][code] = dict(
                dates=len(heads),
                directory_sha256=digest(directories[code]),
                statuses=statuses,
                checks=[
                    dict(criterion=e.criterion, status=e.status, measured=e.measured)
                    for e in checks
                ],
                complete=True,
            )
            print(
                json.dumps(
                    dict(
                        verified_stock=code,
                        dates=len(heads),
                        requests=len(result["responses"]),
                        routes=routes,
                    )
                ),
                flush=True,
            )
        store = manager.registry.get("redis.store")
        pending = await store.client.xlen(store.stream)
        require(pending == 0, "仍有待归档")
        # Exercise the real incremental planner after initial SQL archival.
        # The expectation below is independent of the collector's helper.
        from datetime import date

        before = {code: await query.day_heads(code) for code in codes}
        initial_responses = len(result["responses"])
        initial_details = len(details)
        directories.clear()
        details.clear()
        normalized.clear()
        cursor = await collector.execute(
            codes=codes, baseline_revision=await collector.checkpoint_revision()
        )
        require(cursor["phase"] == "complete", "增量未完成")
        current = date.fromisoformat(cursor["through"])
        expected = set()
        for code, dates in directories.items():
            for stamp in dates:
                status = before[code].get(stamp, {}).get("detail_status")
                age = (current - date.fromisoformat(stamp)).days
                if status not in {"present", "partial", "source_empty"} or age < 7:
                    expected.add((code, stamp))
                    continue
                period = 7 if age < 90 else 30 if status != "present" else None
                if period:
                    value = hashlib.sha256((code + ":" + stamp).encode()).hexdigest()
                    if int(value, 16) % period == current.toordinal() % period:
                        expected.add((code, stamp))
        require(set(directories) == set(codes), "增量证券目录集合不完整")
        require(set(details) == set(normalized) == expected, "增量请求/入队集合与分层规则不符")
        for (code, stamp), source in details.items():
            actual = await query.detail(code, stamp)
            require(actual["detail_status"] == source["status"], "增量来源状态不一致")
            if source["status"] != "source_empty":
                require(actual["reasons"] == source["reasons"], "增量原因内容不一致")
                require(actual["seats"] == source["seats"], "增量席位内容不一致")
        pending = await store.client.xlen(store.stream)
        require(pending == 0, "增量仍有待归档")
        result["incremental"] = dict(
            passed=True,
            through=cursor["through"],
            directories=len(directories),
            initial_details=initial_details,
            selected_details=len(expected),
            responses=len(result["responses"]) - initial_responses,
            selected_keys_sha256=digest(sorted(expected)),
            pending_stream=pending,
        )
        result.update(
            pipeline_verified=True,
            pending_stream=pending,
            random_samples_complete=True,
            strict_proxy_verified=strict_proxy(routes, len(result["responses"])),
        )
        report["scope"] = (
            "随机30只及固定601139.SH、000001.SZ全部来源日期；独立库与命名空间，不是生产全市场覆盖"
        )
    finally:
        if hasattr(collector, "records"):
            try:
                result["final_error_records"] = (
                    await collector.records.list_error_summaries(PROJECT, limit=100)
                )["rows"]
            except Exception as exc:
                result["error_summary_failure"] = type(exc).__name__
        http.request, ingest.publish_page = original_request, original_publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


def main():
    args = verification.parser(__doc__).parse_args()
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    action = (
        verification.recover(args)
        if args.cleanup_only
        else verification.verify(
            args,
            verify_scope,
            subject="hot-list",
            fixed_codes=("601139.SH", "000001.SZ"),
            minimum_random=30,
            require_proxy=True,
        )
    )
    passed = asyncio.run(action)
    print("PASS" if passed else "FAIL", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
