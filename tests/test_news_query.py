from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.plugins.data.news import NewsDataPlugin


@pytest.mark.parametrize("cursor", [
    {}, {"published_at": "2026-01-01T00:00:00"},
    {"published_at": "bad", "news_id": 1},
    {"published_at": "2026-01-01T00:00:00+08:00", "news_id": 1},
    {"published_at": "2026-01-01T00:00:00", "news_id": True},
    {"published_at": "2026-01-01T00:00:00", "news_id": -1},
])
async def test_news_query_rejects_invalid_cursors_before_sql(cursor):
    query = NewsDataPlugin()
    query.mysql = SimpleNamespace(read=AsyncMock())
    with pytest.raises(ValueError, match="游标"):
        await query.list_news(before=cursor)
    query.mysql.read.assert_not_awaited()


@pytest.mark.parametrize("kwargs", [
    {"search": 1}, {"search": "x" * 101}, {"limit": 0}, {"limit": 201},
    {"important": 1}, {"include_total": 1},
])
async def test_news_query_rejects_invalid_bounds(kwargs):
    query = NewsDataPlugin()
    query.mysql = SimpleNamespace(read=AsyncMock())
    with pytest.raises(ValueError, match="参数"):
        await query.list_news(**kwargs)
    query.mysql.read.assert_not_awaited()
