"""Durable settings and download-owner lifecycle, without external services."""
import asyncio
import copy
from types import SimpleNamespace

import httpx
import pytest

from empire.contracts.download import FilePolicy, MiB, ResponsePolicy
from empire.contracts.download_settings import (
    DEFAULTS,
    FIELDS,
    LEGACY_KEYS,
    PROFILE_FIELDS,
    local_download_options,
    validate_settings,
)
from empire.plugins.infra import download_settings as settings_module
from empire.plugins.infra import http as http_module
from empire.plugins.infra.download_settings import DownloadSettingsPlugin
from empire.plugins.infra.http import HttpPlugin, HttpService
from empire.plugins.infra.response_reader import DownloadLimitError, ManagedResponse


class Permits:
    async def eval(self, *args):
        return 0


@pytest.fixture
def stored_context(monkeypatch):
    database = SimpleNamespace(payloads={}, writes=0, failure=None, entered=None, release=None)

    class Store:
        def __init__(self, mysql, namespace):
            assert mysql is database and namespace == "empire:test-settings"

        async def load(self, kind):
            return copy.deepcopy(database.payloads.get(kind, {}))

        async def save(self, kind, key, values):
            if database.entered is not None:
                database.entered.set()
                await database.release.wait()
            if database.failure:
                raise database.failure
            category = database.payloads.setdefault(kind, {})
            if category.get(key) != values:
                category[key] = copy.deepcopy(values)
                database.writes += 1

    monkeypatch.setattr(settings_module, "SettingsStore", Store)
    monkeypatch.setattr(http_module, "SettingsStore", Store)
    services = {"mysql.store": database,
                "redis.store": SimpleNamespace(prefix="empire:test-settings", client=Permits()),
                "collection.records": None, "proxy.pool": None}
    return database, services, SimpleNamespace(get=services.__getitem__)


def test_valid_defaults_are_copied_and_buffer_formula_is_enforced():
    values = validate_settings(DEFAULTS)
    assert values == DEFAULTS and values is not DEFAULTS
    values["buffer_budget_bytes"] = 13 * MiB
    assert validate_settings(values) == values
    values["buffer_budget_bytes"] = 12 * MiB
    with pytest.raises(ValueError, match="共享缓冲至少需要 13 MiB"):
        validate_settings(values)


@pytest.mark.parametrize("values", [None, [], {}, {**DEFAULTS, "unexpected": 1},
    {key: value for key, value in DEFAULTS.items() if key != "file_concurrency"}])
def test_schema_rejects_missing_or_extra_fields(values):
    with pytest.raises(ValueError, match="字段"):
        validate_settings(values)


@pytest.mark.parametrize("field", FIELDS, ids=lambda field: field.key)
@pytest.mark.parametrize("invalid", [True, False, 1.5, "4", None])
def test_every_setting_requires_an_exact_integer(field, invalid):
    with pytest.raises(ValueError):
        validate_settings({**DEFAULTS, field.key: invalid})


@pytest.mark.parametrize("field", FIELDS, ids=lambda field: field.key)
def test_every_setting_has_finite_bounds_and_explicit_units(field):
    for invalid in (field.minimum - 1, field.maximum + 1):
        with pytest.raises(ValueError):
            validate_settings({**DEFAULTS, field.key: invalid})
    if field.scale > 1:
        with pytest.raises(ValueError):
            validate_settings({**DEFAULTS, field.key: field.default + 1})


def test_directory_quota_must_fit_a_single_file():
    with pytest.raises(ValueError, match="不能小于单文件"):
        validate_settings({**DEFAULTS, "download_quota_bytes": 128 * MiB})


def test_toml_has_only_one_machine_local_option():
    assert local_download_options({"download_directory": "D:/downloads"}) == {
        "download_directory": "D:/downloads"}
    assert local_download_options({}) == {}
    for key in LEGACY_KEYS | {"stock_response_bytes", "unknown"}:
        with pytest.raises(ValueError, match="显式迁移"):
            local_download_options({key: 1})


async def test_save_publishes_only_after_commit_and_snapshot_is_detached(stored_context):
    database, _, context = stored_context
    plugin = DownloadSettingsPlugin()
    await plugin.start(context)
    plugin.activate(DEFAULTS)
    database.entered, database.release = asyncio.Event(), asyncio.Event()
    changed = {**DEFAULTS, "buffer_budget_bytes": 96 * MiB}
    task = asyncio.create_task(plugin.save(changed))
    await database.entered.wait()
    assert (await plugin.snapshot())["saved"] == DEFAULTS
    database.release.set()
    saved = await task
    assert saved == {"saved": changed, "active": DEFAULTS, "pending_restart": True}
    changed["buffer_budget_bytes"] = 128 * MiB
    saved["active"]["buffer_budget_bytes"] = MiB
    assert plugin.saved["buffer_budget_bytes"] == 96 * MiB
    assert plugin.active == DEFAULTS
    await plugin.stop()


async def test_failed_save_preserves_saved_and_active_values(stored_context):
    database, _, context = stored_context
    plugin = DownloadSettingsPlugin()
    await plugin.start(context)
    plugin.activate(DEFAULTS)
    database.failure = RuntimeError("SQL unavailable")
    with pytest.raises(RuntimeError, match="SQL unavailable"):
        await plugin.save({**DEFAULTS, "buffer_budget_bytes": 96 * MiB})
    assert await plugin.snapshot() == {"saved": DEFAULTS, "active": DEFAULTS, "pending_restart": False}
    assert database.writes == 0
    await plugin.stop()


async def test_save_without_service_and_invalid_values_never_reach_storage(stored_context):
    database, _, context = stored_context
    plugin = DownloadSettingsPlugin()
    with pytest.raises(RuntimeError, match="未运行"):
        await plugin.save(DEFAULTS)
    await plugin.start(context)
    with pytest.raises(ValueError):
        await plugin.save({**DEFAULTS, "file_concurrency": True})
    assert database.writes == 0
    await plugin.stop()


async def test_http_keeps_inflight_budget_until_normal_restart(stored_context, tmp_path):
    _, services, context = stored_context
    settings = DownloadSettingsPlugin()
    await settings.start(context)
    services["download.settings"] = settings
    plugin = HttpPlugin({}, {"download_directory": str(tmp_path)})
    await plugin.start(context)
    service = plugin.service
    original_budget, original_storage = service.buffer_budget, service.storage
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, content=b"{}")

    await service.client.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    task = asyncio.create_task(service.request("GET", "https://example.test/",
        allowed_domains=("example.test",), policy=service.response_policy("stocks")))
    try:
        await entered.wait()
        reserved = service.buffer_budget.used
        changed = {**DEFAULTS, "buffer_budget_bytes": 96 * MiB,
                   "planned_exit_devices": 300, "max_parallel_downloads": 384,
                   "stock_response_bytes": 2 * MiB, "news_response_bytes": 8 * MiB,
                   "calendar_response_bytes": MiB, "generic_response_bytes": 3 * MiB,
                   "file_response_bytes": 128 * MiB, "download_quota_bytes": 1024 * MiB,
                   "disk_free_margin_bytes": 64 * MiB, "file_concurrency": 2}
        await settings.save(changed)
        assert service.buffer_budget is original_budget and service.storage is original_storage
        assert service.buffer_budget.used == reserved > 0
        assert service.buffer_budget.limit == DEFAULTS["buffer_budget_bytes"]
        assert service.response_policy("stocks").max_body_bytes == MiB
        assert service.resource_values["max_parallel_downloads"] == 128
        assert (await settings.snapshot())["pending_restart"] is True
        release.set()
        response = await task
        assert response.content == b"{}" and service.buffer_budget.used == reserved
        await plugin.stop()
        assert service.closed and service.buffer_budget.used == 0
        assert (await settings.snapshot())["active"] is None
        await plugin.start(context)
        restarted = plugin.service
        assert restarted is not service and restarted.buffer_budget.limit == 96 * MiB
        assert restarted.storage.quota == 1024 * MiB
        assert restarted.storage.min_free == 64 * MiB and restarted.storage.concurrency == 2
        assert restarted.resource_values["planned_exit_devices"] == 300
        assert restarted.resource_values["max_parallel_downloads"] == 384
        for profile, key in PROFILE_FIELDS.items():
            assert restarted.response_policy(profile).max_body_bytes == changed[key]
            assert restarted.response_policy(profile).max_wire_bytes == changed[key]
        assert restarted.file_policy(filename="report.pdf").max_body_bytes == 128 * MiB
        assert (await settings.snapshot())["pending_restart"] is False
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await plugin.stop()
        await settings.stop()


async def test_active_values_are_retained_until_http_closure_succeeds(stored_context, monkeypatch):
    _, services, context = stored_context
    settings = DownloadSettingsPlugin()
    await settings.start(context)
    services["download.settings"] = settings
    plugin = HttpPlugin({})
    await plugin.start(context)
    original_close = plugin.service.close
    entered, release = asyncio.Event(), asyncio.Event()

    async def close():
        entered.set()
        await release.wait()
        await original_close()

    monkeypatch.setattr(plugin.service, "close", close)
    stop = asyncio.create_task(plugin.stop())
    await entered.wait()
    assert (await settings.snapshot())["active"] == DEFAULTS
    release.set()
    await stop
    assert (await settings.snapshot())["active"] is None
    await settings.stop()


async def test_configured_generic_limit_applies_without_explicit_policy():
    service = HttpService(Permits(), "test", {}, resources={"generic_response_bytes": 1024},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 1025)))
    try:
        with pytest.raises(DownloadLimitError):
            await service.request("GET", "https://example.test/", allowed_domains=("example.test",))
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


@pytest.mark.parametrize("body_limit,wire_limit,expected_body,expected_wire", [
    (8 * MiB, 4 * MiB, 2 * MiB, 2 * MiB),
    (512 * 1024, 1024 * 1024, 512 * 1024, 1024 * 1024),
])
async def test_file_ceiling_clamps_both_limits_without_enlarging_explicit_contract(
        body_limit, wire_limit, expected_body, expected_wire, monkeypatch, tmp_path):
    service = HttpService(Permits(), "test", {}, resources={
        "file_response_bytes": 2 * MiB, "download_directory": str(tmp_path)})
    received = []

    async def request(method, url, *, policy, **kwargs):
        received.append(policy)
        return ManagedResponse(httpx.Response(200, request=httpx.Request(method, url)), b"",
                               artifact={"path": "not-a-real-file"})

    monkeypatch.setattr(service, "_request", request)
    try:
        await service.request("GET", "https://example.test/file", policy=FilePolicy(
            max_body_bytes=body_limit, max_wire_bytes=wire_limit, filename="report.pdf", signature=b"%PDF-"))
        assert received[0].max_body_bytes == expected_body
        assert received[0].max_wire_bytes == expected_wire
        assert received[0].signature == b"%PDF-"
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_plugin_reloads_saved_settings_without_redis_values(stored_context):
    database, _, context = stored_context
    first = DownloadSettingsPlugin()
    await first.start(context)
    changed = {**DEFAULTS, "buffer_budget_bytes": 128 * MiB}
    await first.save(changed)
    await first.stop()
    second = DownloadSettingsPlugin()
    await second.start(context)
    assert await second.snapshot() == {"saved": changed, "active": None, "pending_restart": False}
    assert database.writes == 1
    await second.stop()


async def test_invalid_stored_configuration_is_not_silently_reset(stored_context):
    database, _, context = stored_context
    database.payloads["download"] = {"global": {**DEFAULTS, "file_concurrency": True}}
    plugin = DownloadSettingsPlugin()
    with pytest.raises(ValueError):
        await plugin.start(context)
    assert database.writes == 0
    await plugin.stop()


def test_response_policy_formula_is_independent_from_file_size():
    assert ResponsePolicy(max_body_bytes=4 * MiB).reservation_bytes == 12 * MiB + 256 * 1024
    assert FilePolicy(max_body_bytes=1024 * MiB).reservation_bytes == 256 * 1024
