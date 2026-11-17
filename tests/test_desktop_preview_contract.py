"""Business presentation, drill-down and lossless preview contracts."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.desktop_bridge.preview import catalog, read
from empire.features.suspensions.query import SuspensionDataPlugin


def test_every_installed_project_has_business_presentation_and_resolvable_navigation():
    manager = build_manager(load_config("config/app.example.toml"))
    projects = manager.entries["collection.control"].plugin.definitions
    renderers = set()
    for project in projects:
        specs = {v["id"]: v for v in catalog(project)}
        assert any(not v["hidden"] for v in specs.values()), project
        for spec in specs.values():
            assert spec["columns"] and spec["description"] and spec["identity"], project
            assert spec["title"] not in ("已归档数据", "事件与方案", "报告期数据")
            assert len({c["key"] for c in spec["columns"]}) == len(spec["columns"])
            assert {f["key"] for f in spec["filter_specs"]} == set(spec["filters"])
            renderers.add(spec["renderer"])
            if spec.get("detailView"):
                target = specs[spec["detailView"]]
                assert set(spec["detailFilters"]) <= set(target["filters"])
            if spec["hidden"]:
                assert spec["parent"] in specs
                assert all(f["required"] for f in spec["filter_specs"])
    assert len(projects) == 62
    assert {"sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav"} <= projects.keys()
    assert {"ths-yuanhang-etfs", "ths-yuanhang-etf-prices", "ths-yuanhang-etf-latest"} <= projects.keys()
    assert {'ths-fx-live', 'ths-fx-daily'} <= projects.keys()
    assert "eastmoney-graymarket" in projects
    assert "tdx-industry-margin" in projects
    assert {"statement", "calendar", "hotlist", "holdings", "pool", "rules", "news"} <= renderers


def test_date_filters_and_amount_units_follow_business_meaning():
    cases = {"tdx-suspensions": "来源日历日", "tdx-holder-count": "统计日期",
             "tdx-shareholder-changes": "变动结束日", "tdx-earnings-forecast": "报告期",
             "tdx-unlocks": "解禁日", "ths-yuanhang-index-prices": "交易日期", "tdx-industry-margin": "统计日期"}
    for project, label in cases.items():
        spec = catalog(project)[0]
        assert next(f for f in spec["filter_specs"] if f["key"] == "start")["label"] == label + "从"
    holder = {c["key"]: c for c in catalog("tdx-holder-count")[0]["columns"]}
    assert holder["average_float"]["unit"] == "股/户"
    margin = {c["key"]: c for c in catalog("tdx-margin")[0]["columns"]}
    assert margin["financing_balance"]["unit"] == "万元"
    assert margin["lending_balance"]["unit"] == "万股"
    assert "statement_layouts" in catalog("ths-income")[0]
    assert any(c["key"] == "source_dates" for c in catalog("tdx-suspensions")[0]["columns"])


async def test_detail_is_lazy_and_does_not_load_every_list_row():
    browse = AsyncMock(return_value={"rows": [{"report_key": "a" * 64}], "next": None})
    detail = AsyncMock(return_value={"members": [{"holder_name": "甲", "quantity": None}], "kind": "top_holders"})
    registry = SimpleNamespace(get=lambda _: SimpleNamespace(browse=browse, detail=detail))
    await read(registry, "ths-holders", "top_holders", {})
    detail.assert_not_awaited()
    result = await read(registry, "ths-holders", "top_holders:detail", {"record_key": "a" * 64})
    detail.assert_awaited_once_with(key="a" * 64)
    assert result["rows"][0]["members"][0]["quantity"] is None


async def test_capital_detail_cannot_cross_declared_section():
    detail = AsyncMock(return_value={"section": "connect", "description": "其他栏目"})
    registry = SimpleNamespace(get=lambda _: SimpleNamespace(detail=detail))
    with pytest.raises(ValueError, match="不属于当前"):
        await read(registry, "ths-capital", "capital_transaction:asset:detail", {"record_key": "a" * 64})


async def test_calendar_and_theme_context_are_not_discarded():
    month = AsyncMock(return_value={"rows": [{"trade_date": "2026-10-01", "is_trade": False}],
                                   "month": "2026-10", "expected_count": 31, "complete": False})
    registry = SimpleNamespace(get=lambda _: SimpleNamespace(month=month))
    result = await read(registry, "cninfo-calendar", "calendar", {"month": "2026-10"})
    assert result["context"] == dict(month="2026-10", expected_count=31, complete=False)
    head = {"name": "机器人", "brief": "题材摘要", "introduction": "完整介绍"}
    detail = AsyncMock(return_value={"rows": [], "head": head})
    result = await read(SimpleNamespace(get=lambda _: SimpleNamespace(detail_page=detail)),
                        "kaipanla-theme-details", "details", {"theme_id": "1"})
    assert result["context"]["head"] == head


async def test_nested_action_and_security_identity_remain_lossless():
    action = dict(market="SZ", code="000001", name="测试", data={"cash_per_share": "0.123456789", "detail": None})
    method = AsyncMock(return_value=[action])
    result = await read(SimpleNamespace(get=lambda _: SimpleNamespace(list_events=method)),
                        "tdx-dividends", "dividends", {})
    assert result["rows"][0]["unified_code"] == "000001.SZ"
    assert result["rows"][0]["cash_per_share"] == "0.123456789"
    assert result["rows"][0]["data"] == action["data"]


async def test_hidden_detail_requires_selected_identity_and_rejects_cursor():
    method = AsyncMock(return_value={})
    registry = SimpleNamespace(get=lambda _: SimpleNamespace(detail=method))
    assert (await read(registry, "tdx-hot-list", "records:detail", {}))["required"]
    method.assert_not_awaited()
    with pytest.raises(ValueError, match="不接受分页"):
        await read(registry, "tdx-hot-list", "records:detail", {"security": "000001.SZ", "day": "2026-10-29"}, "next")
    method.assert_not_awaited()


def test_suspension_source_dates_use_paged_identity_and_not_effective_day():
    stopped = datetime(2004, 12, 27, 9, 30)
    head = dict(unified_code="000001.SZ", resume_key="unknown", record_key="a" * 64,
                market="SZ", code="000001", name="测试", suspended_at=stopped,
                resumed_at=None, suspension_type="full_day", source_note="来源", reason="原因")
    source = [{**head, "source_date": date(2005, 1, 1)}, {**head, "source_date": date(2005, 1, 2)}]
    connection = MagicMock()
    connection.execute.side_effect = [SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [head])),
                                      SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: source))]
    plugin = SuspensionDataPlugin()
    plugin.mysql = SimpleNamespace(read_engine=SimpleNamespace(connect=MagicMock()))
    plugin.mysql.read_engine.connect.return_value.__enter__.return_value = connection
    rows = plugin._list_events("", "", date(2005, 1, 1), date(2005, 1, 2), 50, 0, "suspended_at", "desc")
    assert rows[0]["source_dates"] == ["2005-01-01", "2005-01-02"]
    assert rows[0]["suspended_at"].startswith("2004-12-27")
    assert "resume_key" not in rows[0]
    assert connection.execute.call_count == 2
    parameters = connection.execute.call_args.args[1]
    assert parameters["identities"] == [("000001.SZ", stopped, "unknown", "a" * 64)]
    assert parameters["end"] == date(2005, 1, 3)
