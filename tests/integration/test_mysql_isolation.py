"""Real MySQL, UUID-scoped settings only; never alter production business rows."""
import asyncio
import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import text

from empire.core.config import load_config
from empire.plugins.infra.mysql_store import MySQLPlugin
from empire.plugins.infra.settings import SettingsStore

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly")]


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.fixture
async def database():
    mysql = MySQLPlugin(load_config()["mysql"])
    namespace = "empire:test:sql-isolation:" + uuid4().hex
    await mysql.start(None)
    try:
        yield mysql, SettingsStore(mysql, namespace)
    finally:
        def cleanup():
            with mysql.engine.begin() as conn:
                conn.execute(text("DELETE FROM app_setting WHERE namespace=:namespace"),
                             {"namespace": namespace})
        await mysql.control(cleanup)
        await mysql.stop()


async def test_slow_browsing_cannot_exhaust_write_connections(database):
    mysql, settings = database

    def slow_read():
        with mysql.read_engine.connect() as conn:
            return conn.execute(text("SELECT SLEEP(2)")).scalar_one()

    reads = [asyncio.create_task(mysql.read(slow_read)) for _ in range(2)]
    try:
        await until(lambda: mysql.read_engine.pool.checkedout() == 2)
        async with asyncio.timeout(1):
            await settings.save("test", "config", {"saved": True})
            assert await settings.load("test") == {"config": {"saved": True}}
            result = await mysql.archive([{"writer": lambda conn, envelope, normalized:
                settings.save_in_transaction(conn, "test", "archive", {"committed": True}),
                "envelope": None, "normalized": None}])
            assert result == [True]
        assert not any(task.done() for task in reads)
    finally:
        await asyncio.gather(*reads)


async def test_cancelled_transaction_finishes_and_failed_transaction_rolls_back(database):
    mysql, settings = database
    entered, release = threading.Event(), threading.Event()

    def writer(conn, envelope, normalized):
        settings.save_in_transaction(conn, "test", "committed", {"value": 1})
        entered.set()
        assert release.wait(5)

    task = asyncio.create_task(mysql.archive([
        {"writer": writer, "envelope": None, "normalized": None}]))
    try:
        await until(entered.is_set)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await settings.load("test") == {"committed": {"value": 1}}

        def fail(conn, envelope, normalized):
            settings.save_in_transaction(conn, "test", "rolled-back", {"value": 2})
            raise ValueError("injected transaction failure")

        with pytest.raises(ValueError, match="injected"):
            await mysql.archive([{"writer": fail, "envelope": None, "normalized": None}])
        assert await settings.load("test") == {"committed": {"value": 1}}
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
