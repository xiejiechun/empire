"""Retirement must not silently read orphaned quote tables."""

from types import SimpleNamespace
from unittest.mock import Mock

from empire.features.capital_actions.dividend_yield import calculate_yield


async def test_retired_quote_provider_has_no_sql_fallback():
    mysql = Mock()
    value = await calculate_yield(SimpleNamespace(mysql=mysql), {})
    assert value["state"] == "数据阻断"
    assert not mysql.mock_calls
