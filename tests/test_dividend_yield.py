"""Retired quote provider blocks calculation before accessing business storage."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from empire.features.capital_actions.dividend_yield import calculate_yield


@pytest.mark.asyncio
async def test_missing_price_provider_does_not_query_deleted_tables():
    plugin = SimpleNamespace(mysql=Mock())
    result = await calculate_yield(plugin, {})
    assert result["state"] == "数据阻断"
    assert "已移除" in result["problem"]
    assert result["securities"] == []
    assert plugin.mysql.mock_calls == []
    from empire.features.capital_actions.distribution_text import distribution_text

    assert '已移除' in distribution_text(result)
