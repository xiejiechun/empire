"""MySQL-only bounded browsing and independent source-output preparation checks."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from functools import partial

from sqlalchemy import text

from empire.contracts.business_schema import schema_contract
from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.features.hot_list.contract import (
    CONTRACT,
    DATASET,
    JOB,
    PROJECT,
    TABLES,
    day,
    digest,
    security,
    validate_detail,
)
from empire.features.hot_list.dataset import HotListDataset, read_detail, read_details
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class HotListDataPlugin:
    manifest = PluginManifest(
        "data.hot_list",
        "龙虎榜查询",
        requires=("mysql.store",),
        provides=("hot_list.query",),
        description="有界日期列表、原因席位与集合校验",
    )

    def __init__(self, namespace="empire", archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}
        self.mapping, self.mysql, self.context = HotListDataset(), None, None
        self.preparation = tuple(
            PreparationContribution(
                req,
                "hot_list.query",
                "通达信",
                PROJECT,
                JOB,
                DATASET,
                "collector.tdx_hot_list",
                ("tests/test_tdx_hot_list.py", "tests/test_hot_list_lifecycle.py"),
                ("tests/integration/test_hot_list_archive.py",),
                method="check_" + req,
                scoped=True,
                response_group=DATASET,
            )
            for req in ("hot_list_summary", "hot_list")
        )
        for req in ("hot_list_summary", "hot_list"):
            setattr(self, "check_" + req, partial(self.preparation_check, req))

    async def start(self, context):
        self.mysql, self.context = context.get("mysql.store"), context
        for table in TABLES:
            from empire.plugins.infra.schema_manifest import manifest

            await self.mysql.require_schema(
                *schema_contract(table, *manifest()["tables"][table]["columns"])
            )
        return {"hot_list.query": self}

    async def securities(self, codes=None):
        if codes is not None:
            if (
                not isinstance(codes, (list, tuple))
                or not 1 <= len(codes) <= 30000
                or len(set(codes)) != len(codes)
            ):
                raise ValueError("龙虎榜指定股票池无效")
            return sorted(security(c) for c in codes)

        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT unified_code FROM stock UNION SELECT DISTINCT unified_code FROM hot_list_day ORDER BY unified_code LIMIT 30001"
                        )
                    )
                    .scalars()
                    .all()
                )
                if not rows or len(rows) > 30000:
                    raise ValueError("龙虎榜股票池为空或超限")
                return [security(c) for c in rows]

        return await self.mysql.read(read)

    async def day_heads(self, code):
        security(code)

        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT list_date,detail_status,content_hash FROM hot_list_day WHERE unified_code=:code ORDER BY list_date DESC LIMIT 20001"
                        ),
                        dict(code=code),
                    )
                    .mappings()
                    .all()
                )
                if len(rows) > 20000:
                    raise ValueError("龙虎榜证券历史日期超限")
                return {r["list_date"].isoformat(): dict(r) for r in rows}

        return await self.mysql.read(read)

    async def state(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return read_state(conn, self.namespace, PROJECT, "tdx")

        return await self.mysql.read(read)

    async def browse(self, code="", start="", end="", after=None, limit=200):
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"(?:\d{0,6}|\d{6}\.(SH|SZ|BJ))", code)
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise ValueError("龙虎榜查询证券或分页大小无效")
        scope = PreparationScope.parse(dict(start=start, end=end))
        clauses, args = ["TRUE"], dict(limit=limit + 1)
        if code:
            clauses.append("unified_code LIKE :code")
            args["code"] = code if "." in code else code + "%"
        for key, bound, op in (("start", scope.start, ">="), ("end", scope.end, "<=")):
            if bound:
                clauses.append("list_date" + op + ":" + key)
                args[key] = bound
        if after is not None:
            if not isinstance(after, (list, tuple)) or len(after) != 2:
                raise ValueError("龙虎榜游标无效")
            day(after[0])
            security(after[1])
            clauses.append("(list_date,unified_code)<(:last_day,:last_code)")
            args.update(last_day=after[0], last_code=after[1])

        def read():
            with self.mysql.read_engine.connect() as conn:
                values = [
                    dict(r)
                    for r in conn.execute(
                        text(
                            "SELECT unified_code,list_date,directory_listed,detail_status,reason_count,seat_count FROM hot_list_day WHERE "
                            + " AND ".join(clauses)
                            + " ORDER BY list_date DESC,unified_code DESC LIMIT :limit"
                        ),
                        args,
                    ).mappings()
                ]
                for r in values:
                    r["list_date"] = r["list_date"].isoformat()
                rows = values[:limit]
                return dict(
                    rows=rows,
                    next=[rows[-1]["list_date"], rows[-1]["unified_code"]]
                    if len(values) > limit
                    else None,
                )

        return await self.mysql.read(read)

    async def detail(self, code, stamp):
        security(code)
        day(stamp)

        def read():
            with self.mysql.read_engine.begin() as conn:
                return read_detail(conn, code, stamp)

        return await self.mysql.read(read)

    def audit(self, scope, seats):
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, PROJECT, "tdx")
            proofs = state.get("units", {})
            codes = [c for c in proofs if not scope.codes or c[:6] in scope.codes]
            if len(codes) > 30000:
                raise ValueError("龙虎榜范围证券超限")
            valid = bool(codes) and state.get("contract_version") == CONTRACT
            if not scope.codes:
                pool = (
                    conn.execute(text("SELECT unified_code FROM stock LIMIT 30001")).scalars().all()
                )
                valid &= bool(pool) and len(pool) <= 30000 and set(pool) <= set(codes)
            if scope.codes:
                valid &= all(
                    any(c == wanted or c[:6] == wanted for c in codes) for wanted in scope.codes
                )
            checked, missing, selected = 0, 0, 0
            for code in codes:
                proof = proofs[code]
                heads = (
                    conn.execute(
                        text(
                            "SELECT list_date,detail_status,content_hash,reason_count,seat_count FROM hot_list_day WHERE unified_code=:code AND directory_listed=1 ORDER BY list_date DESC LIMIT 20001"
                        ),
                        dict(code=code),
                    )
                    .mappings()
                    .all()
                )
                dates = [r["list_date"].isoformat() for r in heads]
                valid &= (
                    len(dates) <= 20000
                    and proof.get("directory_hash") == digest(dates)
                    and proof.get("count") == len(dates)
                    and proof.get("complete", False)
                )
                selected_heads = [h for h in heads if scope.includes(h["list_date"].isoformat())]
                checked += len(selected_heads)
                if checked > 2000:
                    raise ValueError("龙虎榜详细审计超过2000日期，请缩小证券或日期范围")
                for offset in range(0, len(selected_heads), 20):
                    batch = selected_heads[offset : offset + 20]
                    details = read_details(conn, code, [h["list_date"].isoformat() for h in batch])
                    for head in batch:
                        stamp = head["list_date"].isoformat()
                        data = details[stamp]
                        content = dict(
                            reasons=data["reasons"],
                            seats=data["seats"],
                            auxiliary=data["auxiliary"],
                            status=data["detail_status"],
                        )
                        try:
                            validate_detail(content)
                            valid &= (
                                digest(content) == head["content_hash"]
                                and len(data["reasons"]) == head["reason_count"]
                                and len(data["seats"]) == head["seat_count"]
                            )
                        except (ValueError, TypeError, KeyError):
                            valid = False
                        missing += (
                            int(
                                data["detail_status"] != "present"
                                or any(
                                    r["buy_amount" if r["side"] == "B" else "sell_amount"] is None
                                    for r in data["seats"]
                                )
                            )
                            if seats
                            else int(
                                not data["reasons"]
                                or any(
                                    r[k] is None
                                    for r in data["reasons"]
                                    for k in ("volume", "turnover", "close_price", "change_pct")
                                )
                            )
                        )
                        selected += len(data["seats"] if seats else data["reasons"])
            return dict(
                valid=bool(valid),
                count=selected,
                missing=missing,
                proofs={c: proofs[c] for c in codes},
            )

    async def preparation_check(self, requirement="hot_list", request=None):
        scope = PreparationScope.parse(request)
        try:
            result = await self.mysql.read(self.audit, scope, requirement == "hot_list")
        except (ValueError, TypeError, KeyError) as exc:
            return tuple(
                CheckEvidence(k, "fail", str(exc))
                for k in ("fields", "keys", "coverage", "quality", "freshness", "temporal")
            )
        valid, complete = result["valid"], result["valid"] and not result["missing"]
        now, fresh = datetime.now(UTC), True
        proofs = result["proofs"]
        stamps = {c: p.get("observed_at", "") for c, p in proofs.items()}
        store = self.context.optional("redis.store") if self.context else None
        if valid and store:
            try:
                cache = FingerprintCache(
                    store, self.archive_settings, lambda _: self.mapping.FINGERPRINT_VERSION
                )
                cached = await asyncio.wait_for(
                    cache.peek(
                        self.mapping.FINGERPRINT_NAMESPACE,
                        "tdx",
                        ["finish:" + c + ":" for c in proofs],
                    ),
                    3,
                )
                for code, proof in proofs.items():
                    entry = cached.get("finish:" + code + ":", {})
                    expected = digest(
                        dict(directory_hash=proof["directory_hash"], count=proof["count"])
                    )
                    version = self.mapping.FINGERPRINT_VERSION.key(entry["version"], now=now)[0]
                    if (
                        entry["hash"] == expected
                        and version.isoformat(timespec="microseconds") >= stamps[code]
                    ):
                        stamps[code] = version.isoformat()
            except Exception:
                pass
        for stamp in stamps.values():
            try:
                fresh &= timedelta(0) <= now - datetime.fromisoformat(stamp) <= timedelta(days=3)
            except (ValueError, TypeError):
                fresh = False

        def check(key, ok, message):
            return CheckEvidence(key, "pass" if ok else "fail", message)

        return (
            check(
                "fields",
                complete,
                f"核验{result['count']}条；必需来源明细缺失日期{result['missing']}",
            ),
            check("keys", valid, "核对日期集合、原因与方向排名、正文SHA256；同名机构不合并"),
            check("coverage", valid, "来源日期目录与SQL集合绑定；待采日期不能被最大日期掩盖"),
            check("quality", complete, "NULL与零分别保留；单日与多日榜不重复相加"),
            check("freshness", valid and fresh, "SQL或匹配可信摘要的完整证券证明不超过3天"),
            CheckEvidence(
                "temporal",
                "fail",
                "来源缺公布时刻和完整历史版本，不支持盘中或严格历史信号回放",
                blocking=scope.purpose != "analysis",
            ),
        )

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ready" if self.mysql else "stopped"}
