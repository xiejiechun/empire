"""Bounded formal daily queries and actual yearly content audits."""

import asyncio
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.security import index_code
from empire.features.index_prices.contract import (
    JOB,
    PROJECT,
    day,
    price_relation_valid,
    validate_rows,
    volume_amount_valid,
)
from empire.features.index_prices.dataset import (
    FINGERPRINT_NAMESPACE,
    FINGERPRINT_VERSION,
    KEYS,
    TABLES,
    sql_rows,
)
from empire.features.indices.contract import digest
from empire.plugins.infra.collection_state import read_state
from empire.plugins.pipeline.fingerprints import FingerprintCache


class IndexPriceDataPlugin:
    manifest = PluginManifest(
        "data.index_prices",
        "指数日行情查询",
        requires=("mysql.store",),
        provides=("index.prices.query",),
        description="年度覆盖证明及结构化日行情",
    )
    preparation = (
        PreparationContribution(
            "index_prices",
            "index.prices.query",
            "同花顺",
            PROJECT,
            JOB,
            "index.price.year",
            "collector.ths_index_prices",
            ("tests/test_ths_index_prices.py",),
            ("tests/integration/test_index_price_archive.py",),
            scoped=True,
            cache_revision=4,
        ),
    )

    def __init__(self, namespace="empire", archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}

    async def start(self, context):
        self.context, self.mysql = context, context.get("mysql.store")
        await self.mysql.require_schema(TABLES, KEYS)
        return {"index.prices.query": self}

    async def catalog(self, codes=None):
        if codes is not None:
            if not isinstance(codes, (list, tuple)) or not 1 <= len(codes) <= 1000:
                raise ValueError("指数采集范围无效")
            for code in codes:
                index_code(code)

        def read():
            with self.mysql.read_engine.connect() as conn:
                result = [
                    dict(r)
                    for r in conn.execute(
                        text(
                            "SELECT index_code AS code,name FROM stock_index ORDER BY index_code LIMIT 1001"
                        )
                    ).mappings()
                ]
                if len(result) > 1000:
                    raise ValueError("指数目录超过1000项")
                if codes is not None:
                    if set(codes) - {r["code"] for r in result}:
                        raise ValueError("指定指数不在正式同花顺目录中")
                    result = [r for r in result if r["code"] in codes]
                return result

        return await self.mysql.read(read)

    async def year_heads(self, code):
        index_code(code)

        def read():
            with self.mysql.read_engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT quote_year,source_count,complete,last_date FROM index_price_year "
                            "WHERE index_code=:code ORDER BY quote_year LIMIT 41"
                        ),
                        dict(code=code),
                    )
                    .mappings()
                    .all()
                )
                if len(rows) > 40:
                    raise ValueError("指数年度超过范围")
                return {
                    str(r["quote_year"]): dict(
                        source_count=r["source_count"],
                        complete=bool(r["complete"]),
                        last_date=r["last_date"].isoformat(),
                    )
                    for r in rows
                }

        return await self.mysql.read(read)

    async def browse(self, code="", start="", end="", after=None, limit=200):
        if code:
            index_code(code)
        for value in (start, end):
            if value:
                day(value)
        if start and end and start > end or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("指数行情查询范围无效")
        params, conditions = dict(limit=limit + 1), []
        for field, value, sql in [
            ("code", code, "p.index_code=:code"),
            ("start", start, "p.trade_date>=:start"),
            ("end", end, "p.trade_date<=:end"),
        ]:
            if value:
                params[field] = value
                conditions.append(sql)
        if after is not None:
            if not isinstance(after, (list, tuple)) or len(after) != 2:
                raise ValueError("指数行情分页游标无效")
            params.update(cursor_date=day(after[0]), cursor_code=index_code(after[1]))
            conditions.append(
                "(p.trade_date>:cursor_date OR (p.trade_date=:cursor_date AND p.index_code>:cursor_code))"
            )

        def read():
            with self.mysql.read_engine.connect() as conn:
                where = " WHERE " + " AND ".join(conditions) if conditions else ""
                access = "PRIMARY" if code else "ix_index_price_date"
                values = (
                    conn.execute(
                        text(
                            "SELECT p.*,i.name FROM index_daily_price p FORCE INDEX ("
                            + access
                            + ") LEFT JOIN stock_index i "
                            "ON i.index_code=p.index_code"
                            + where
                            + " ORDER BY p.trade_date,p.index_code LIMIT :limit"
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
                rows = [dict(r) for r in values[:limit]]
                for row in rows:
                    row["price_relation_valid"] = price_relation_valid(
                        [row[k] for k in ("open", "high", "low", "close")]
                    )
                    row["volume_amount_valid"] = volume_amount_valid([row["volume"], row["amount"]])
                return dict(
                    rows=rows,
                    next=[rows[-1]["trade_date"].isoformat(), rows[-1]["index_code"]]
                    if len(values) > limit
                    else None,
                )

        return await self.mysql.read(read)

    async def chart_series(self, code, start, end):
        index_code(code)
        lower, upper = date.fromisoformat(day(start)), date.fromisoformat(day(end))
        if lower > upper or (upper-lower).days > 14640:
            raise ValueError('图表范围必须有起止日期，最多40年')
        def read():
            with self.mysql.read_engine.begin() as conn:
                data = [dict(r) for r in conn.execute(text('SELECT p.*,i.name FROM index_daily_price p '
                    'LEFT JOIN stock_index i ON i.index_code=p.index_code WHERE p.index_code=:code '
                    'AND p.trade_date BETWEEN :start AND :end ORDER BY p.trade_date LIMIT 15001'),
                    dict(code=code, start=lower, end=upper)).mappings()]
                if len(data) > 15000:
                    raise ValueError('指数图表记录超过15000日，拒绝截断')
                for row in data:
                    row['price_relation_valid'] = price_relation_valid([row[k] for k in ('open', 'high', 'low', 'close')])
                    row['volume_amount_valid'] = volume_amount_valid([row['volume'], row['amount']])
                return dict(rows=data, index_code=code, start=start, end=end)
        return await self.mysql.read(read)

    def audit(self, scope):
        with self.mysql.read_engine.begin() as conn:
            state = read_state(conn, self.namespace, PROJECT, "ths")
            codes = (
                list(scope.index_codes)
                if scope.index_codes
                else [
                    r[0]
                    for r in conn.execute(
                        text("SELECT index_code FROM stock_index ORDER BY index_code LIMIT 1001")
                    )
                ]
            )
            if not codes or len(codes) > 1000:
                return False, 0, [], ["未找到指数目录或所选指数"], [], 0, 0, 0, 0
            problems, unavailable, stamps, identities, total = [], [], [], [], 0
            missing, anomalies, missing_amount, quantity_anomalies = 0, 0, 0, 0
            for code in codes:
                status = state.get("indices", {}).get(code)
                if not status:
                    problems.append(code + "未核实行情接口")
                    continue
                identity = code + ":status"
                stamps.append(
                    (state.get("versions", {}).get(identity, ""), digest(dict(code=code, **status)))
                )
                identities.append(identity)
                if not status["available"]:
                    unavailable.append(code)
                    continue
                snapshot = status["snapshot"]
                for y, count in snapshot["years"].items():
                    if (scope.start and int(y) < int(scope.start[:4])) or (
                        scope.end and int(y) > int(scope.end[:4])
                    ):
                        continue
                    head = (
                        conn.execute(
                            text(
                                "SELECT * FROM index_price_year WHERE index_code=:code AND quote_year=:year"
                            ),
                            dict(code=code, year=int(y)),
                        )
                        .mappings()
                        .first()
                    )
                    rows = sql_rows(conn, code, int(y))
                    validate_rows(rows, int(y))
                    if (
                        not head
                        or not head["complete"]
                        or head["source_count"] != count
                        or len(rows) != count
                        or head["content_hash"] != digest(rows)
                        or head["row_count"] != len(rows)
                        or str(head["first_date"]) != rows[0][0]
                        or str(head["last_date"]) != rows[-1][0]
                    ):
                        problems.append(code + ":" + y + "年度内容或完整证明不一致")
                    total += sum(scope.includes(r[0]) for r in rows)
                    missing += sum(scope.includes(r[0]) and any(v is None for v in r[1:4]) for r in rows)
                    anomalous = [r[0] for r in rows if scope.includes(r[0])
                                 and not price_relation_valid(r[1:5])]
                    anomalies += len(anomalous)
                    missing_amount += sum(scope.includes(r[0]) and r[6] is None for r in rows)
                    quantity_anomalies += sum(scope.includes(r[0]) and not volume_amount_valid(r[5:7]) for r in rows)
            return (
                not problems and total > 0,
                total,
                unavailable,
                problems[:20],
                list(zip(identities, stamps, strict=True)),
                missing,
                anomalies,
                missing_amount,
                quantity_anomalies,
            )

    async def preparation_check(self, request=None):
        scope = PreparationScope.parse(request)
        try:
            complete, total, unavailable, problems, versions, missing, anomalies, missing_amount, quantity_anomalies = await self.mysql.read(
                self.audit, scope
            )
            valid = True
        except (ValueError, KeyError, TypeError) as exc:
            complete, total, unavailable, versions, valid, problems, missing, anomalies, missing_amount, quantity_anomalies = (
                False,
                0,
                [],
                [],
                False,
                [str(exc)],
                0,
                0,
                0,
                0,
            )
        now, fresh = datetime.now(UTC), bool(versions)
        store = self.context.optional("redis.store")
        if store and versions:
            try:
                cache = FingerprintCache(
                    store, self.archive_settings, lambda _: FINGERPRINT_VERSION
                )
                cached = await asyncio.wait_for(
                    cache.peek(FINGERPRINT_NAMESPACE, "ths", [k for k, _ in versions]), 3
                )
            except Exception:
                cached = {}
        else:
            cached = {}
        for identity, (observed, expected_hash) in versions:
            try:
                stamp = FINGERPRINT_VERSION.key([observed], now=now)[0]
                # Cache may extend freshness only when content equals the SQL-confirmed status contract.
                value = cached.get(identity)
                if value and value["hash"] == expected_hash:
                    stamp = max(stamp, FINGERPRINT_VERSION.key(value["version"], now=now)[0])
                fresh &= timedelta(0) <= now - stamp <= timedelta(days=3)
            except (ValueError, TypeError, KeyError):
                fresh = False
        summary = f"范围内{total}条指数日线；接口不可用{len(unavailable)}项。" + "；".join(problems)

        def evidence(key, ok, note):
            return CheckEvidence(key, "pass" if ok else "fail", note)

        result = [
            evidence("fields", valid and total > 0, summary),
            evidence("keys", valid, "按指数及日期唯一，年度键与内容摘要核验"),
            evidence("coverage", complete, summary),
            evidence(
                "quality", valid and total > 0 and anomalies == 0,
                f"{anomalies}条价格关系异常，保留来源原值，受影响日期不用于依赖四价的策略；"
                f"已核验精度及收盘量额；{missing}条来源缺少开盘/最高/最低价，保存NULL。"
                + ("可用于收盘收益分析；依赖缺失价格的策略不可用。" if missing else "来源价格字段齐全。")
                + f"{missing_amount}条来源缺少成交额，保存NULL；不影响收盘收益分析，依赖成交额的分析或策略不可用。"
                + f"{quantity_anomalies}条量额异常（负成交量或负成交额），保留原值；不影响收盘收益分析，依赖量额的分析或策略不可用。"
            ),
            evidence("freshness", fresh, "接口最近成功核验不超过3天；完整性另由年度正文核验"),
            evidence("temporal", True, "仅收盘后日线；不提供历史版本回放或量额统一口径"),
        ]
        if unavailable or scope.purpose == "historical_signal":
            result[-1] = CheckEvidence(
                "temporal",
                "fail",
                summary + "部分接口不可用；当前来源修订版不保证过去可知版本，量额保留来源口径",
                blocking=scope.purpose != "analysis",
            )
        return tuple(result)

    async def stop(self):
        self.mysql = self.context = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
