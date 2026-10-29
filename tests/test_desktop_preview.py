"""Task previews stay on formal reads and reject cross-task/capability injection."""

import inspect
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.desktop_bridge.preview import read
from empire.desktop_bridge.preview_catalog import views


def test_every_task_has_registered_formal_preview():
    manager = build_manager(load_config())
    for task in manager.entries["collection.control"].plugin.definitions:
        entries = views(task)
        assert entries, task
        assert len({v.id for v in entries}) == len(entries)
        for v in entries:
            assert v.capability in manager.providers, (task, v.capability)
            service = manager.entries[manager.providers[v.capability]].plugin
            assert inspect.iscoroutinefunction(getattr(service, v.method)), (task, v.method)


async def test_all_preview_adapters_match_formal_signatures():
    manager = build_manager(load_config())
    calls = []

    def get(cap):
        real = manager.entries[manager.providers[cap]].plugin

        class Service:
            def __getattr__(self, name):
                async def call(**kwargs):
                    inspect.signature(getattr(real, name)).bind(**kwargs)
                    calls.append((cap, name, kwargs))
                    return []

                return call

        return Service()

    registry = SimpleNamespace(get=get)
    for task in manager.entries["collection.control"].plugin.definitions:
        for v in views(task):
            fields = {
                k: val
                for k, val in {"security": "000001.SZ", "theme_id": "1"}.items()
                if k in v.filters
            }
            await read(registry, task, v.id, fields)
    assert calls


async def test_preview_cannot_cross_task_or_execute_methods():
    registry = SimpleNamespace(get=lambda _: pytest.fail("must reject before lookup"))
    with pytest.raises(ValueError):
        await read(registry, "ths-income", "balance", {})
    with pytest.raises(ValueError):
        await read(registry, "ths-income", "income", {"sql": "DELETE"})
    assert (await read(registry, "ths-yuanhang-prices", "prices", {}))["required"]


async def test_precision_and_pagination():
    method = AsyncMock(
        return_value={
            "rows": [{"value": Decimal("123456789.012345"), "day": date(2026, 10, 29)}],
            "next": ["2026-10-29", "key"],
        }
    )
    registry = SimpleNamespace(get=lambda _: SimpleNamespace(browse=method))
    result = await read(registry, "ths-holders", "top_holders", {}, ["prior", "key"])
    assert result["rows"][0] == {"value": "123456789.012345", "day": "2026-10-29"}
    assert result["next"] == ["2026-10-29", "key"]
    assert method.call_args.kwargs["after"] == ["prior", "key"]
    assert method.call_args.kwargs["limit"] == 50
