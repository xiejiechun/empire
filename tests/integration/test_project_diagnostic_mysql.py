"""Trace real PyMySQL SELECTs, including probes hidden from SQLAlchemy events."""
import os

import pymysql.connections
import pytest
from sqlalchemy import text

from empire.core.config import load_config
from empire.diagnostics.readonly import Budget, DiagnosticLimit, Limits, ReadOnlyMySQL

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='explicit isolated integration run required')]


@pytest.fixture
def wire_selects(monkeypatch):
    observed = []
    original = pymysql.connections.Connection.query

    def query(connection, statement, *args, **kwargs):
        value = statement.decode() if isinstance(statement, bytes) else statement
        if value.lstrip().upper().startswith('SELECT'):
            observed.append(value)
        return original(connection, statement, *args, **kwargs)

    monkeypatch.setattr(pymysql.connections.Connection, 'query', query)
    return observed


async def scalar(mysql):
    def read():
        with mysql.read_engine.connect() as conn:
            return conn.execute(text('SELECT 1 LIMIT 1')).scalar_one()
    return await mysql.read(read)


async def test_cold_and_warm_driver_queries_stay_inside_ten_selects(wire_selects):
    mysql = ReadOnlyMySQL(load_config()['mysql'], Budget(Limits()))
    try:
        assert await scalar(mysql) == 1
        assert len(wire_selects) == 6  # five actual cold probes plus the requested query
        assert mysql.budget.used['sql'] == 6
        assert await scalar(mysql) == 1
        assert len(wire_selects) == mysql.budget.used['sql'] == 7
        for _ in range(3):
            assert await scalar(mysql) == 1
        assert len(wire_selects) == mysql.budget.used['sql'] == 10
        with pytest.raises(DiagnosticLimit, match='次数'):
            await scalar(mysql)
        assert len(wire_selects) == 10
    finally:
        mysql.close()
    assert mysql.cleanup_status()['complete']


async def test_insufficient_probe_budget_refuses_before_connection(monkeypatch, wire_selects):
    attempted = []
    original = pymysql.connections.Connection.connect

    def connect(connection, *args, **kwargs):
        attempted.append(True)
        return original(connection, *args, **kwargs)

    monkeypatch.setattr(pymysql.connections.Connection, 'connect', connect)
    mysql = ReadOnlyMySQL(load_config()['mysql'], Budget(Limits(sql=4)))
    try:
        with pytest.raises(DiagnosticLimit, match='次数'):
            await scalar(mysql)
        assert not attempted and not wire_selects
        assert mysql.budget.used['sql'] == 0
    finally:
        mysql.close()


async def test_second_physical_connection_cannot_hide_probes(wire_selects):
    mysql = ReadOnlyMySQL(load_config()['mysql'], Budget(Limits()))
    try:
        assert await scalar(mysql) == 1
        assert len(wire_selects) == 6
        mysql.read_engine.dispose()
        with pytest.raises(DiagnosticLimit, match='次数'):
            await scalar(mysql)
        assert len(wire_selects) == 6
        assert mysql.budget.used['sql'] == 6
    finally:
        mysql.close()
