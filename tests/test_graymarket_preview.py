from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empire.desktop_bridge.preview import catalog, read
from empire.features.graymarket import intraday_query
from empire.features.graymarket.query import GraymarketDataPlugin


@pytest.fixture
def snapshot(monkeypatch):
    rows = [[f"{i:06}.SZ", "测试", str(i), "2", str(i + 2), "0.01", "10", "0.02", "094500", i]
            for i in range(1, 202)]
    method = AsyncMock(return_value=dict(rows=rows, version="1793756700000000",
        started="2026-11-04T09:45:00+08:00", finished="2026-11-04T09:46:00+08:00"))
    monkeypatch.setattr(intraday_query, "IntradayStore", lambda _: SimpleNamespace(read=method))
    return method


async def live(code="", cursor=None):
    return await intraday_query.browse_live(SimpleNamespace(optional=lambda _: object()),
        (3, "graymarket", "", "2026-11-04", "", ""), cursor, None, code)


def test_today_live_is_default_and_financial_formats_are_explicit():
    current, archive = catalog("eastmoney-graymarket")
    assert current["id"] == "live" and current["defaults"]["day"]
    assert current["today_filter"] == "day"
    assert current["default_order"] == dict(field="dark_flow", direction="desc")
    assert current["renderer"] == "fundflow"
    assert archive["id"] == "records"
    assert next(f for f in archive["filter_specs"] if f["key"] == "start")["label"] == "交易日期从"
    columns = {c["key"]: c for c in current["columns"]}
    assert columns["dark_flow"]["format"] == "money"
    assert columns["change_ratio"]["format"] == "percent"


async def test_snapshot_counts_default_sort_and_fixed_pagination(snapshot):
    first = await live()
    assert first["total"] == first["source_total"] == 201
    assert first["rows"][0]["unified_code"] == "000201.SZ"
    assert len(first["rows"]) == 200
    assert first["snapshot"]["finished"] == "2026-11-04T09:46:00+08:00"
    second = await live(cursor=first["next"])
    assert len(second["rows"]) == 1 and second["next"] is None
    snapshot.assert_awaited_with("2026-11-04", version=first["snapshot"]["version"])


async def test_code_filter_before_pagination_and_cursor_binding(snapshot):
    exact = await live("000001.sz")
    assert exact["total"] == 1 and exact["source_total"] == 201
    assert exact["rows"][0]["unified_code"] == "000001.SZ"
    prefix = await live("0001")
    assert prefix["total"] == 100 and prefix["next"] is None
    first = await live()
    with pytest.raises(ValueError, match="游标"):
        await live("0001", first["next"])
    with pytest.raises(ValueError, match="代码"):
        await live("000%")


async def test_no_snapshot_is_distinct_from_no_matching_security(snapshot):
    unmatched = await live("999999")
    assert unmatched["rows"] == [] and unmatched["snapshot"]["available"]
    assert unmatched["total"] == 0 and unmatched["source_total"] == 201
    snapshot.return_value = None
    missing = await live()
    assert not missing["snapshot"]["available"] and "2026-11-04" in missing["message"]
    assert "total" not in missing


async def test_bridge_forwards_code_and_snapshot_context(snapshot):
    async def method(filters, after, code, order):
        return await intraday_query.browse_live(SimpleNamespace(optional=lambda _: object()), filters, after, order, code)
    result = await read(SimpleNamespace(get=lambda _: SimpleNamespace(browse_live=method)),
        "eastmoney-graymarket", "live", dict(day="2026-11-04", code="000001"),
        order=dict(field="dark_flow", direction="desc"))
    assert result["storage"] == "Redis 盘中快照"
    assert result["total"] == 1 and result["context"]["source_total"] == 201
    assert result["context"]["snapshot"]["available"]


async def test_archive_code_prefix_is_parameterized():
    connection = MagicMock()
    connection.execute.return_value.mappings.return_value = []
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    async def run(callback):
        return callback()
    plugin = GraymarketDataPlugin()
    plugin.mysql = SimpleNamespace(read=run, read_engine=engine)
    assert (await plugin.browse(code="0001"))["rows"] == []
    statement, args = connection.execute.call_args.args
    assert "LIKE :code" in str(statement) and args["code"] == "0001%"
