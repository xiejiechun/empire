"""One authoritative bounded pool read; only invalidated disconnects replay."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pymysql
import pytest
from sqlalchemy.exc import OperationalError

from empire.features.hot_list.query import HotListDataPlugin


def failure(code=2013, invalidated=True):
    return OperationalError("SELECT pool", {}, pymysql.err.OperationalError(code, "injected"),
                            connection_invalidated=invalidated)


def query(outcomes):
    q = HotListDataPlugin()
    engine = MagicMock()
    connections = []

    def connect():
        conn = MagicMock()
        conn.__enter__.return_value = conn
        result = outcomes[len(connections)]
        connections.append(conn)
        # Model loss while reading the result, not just connection checkout.
        if isinstance(result, BaseException):
            conn.execute.return_value.scalars.return_value.all.side_effect = result
        else:
            conn.execute.return_value.scalars.return_value.all.return_value = result
        return conn

    async def read(fn):
        return fn()

    engine.connect.side_effect = connect
    q.mysql = SimpleNamespace(read_engine=engine, read=read)
    return q, connections


@pytest.mark.parametrize("first", [None, 2006, 2013])
async def test_pool_normal_once_or_disconnect_once(first):
    codes = ["000001.SZ", "600001.SH", "920117.BJ"]
    q, connections = query(([failure(first)] if first else []) + [codes])
    assert await q.securities() == codes
    assert len(connections) == (2 if first else 1)
    for conn in connections:
        sql = str(conn.execute.call_args.args[0])
        assert "FORCE INDEX (ix_date)" in sql and "LIMIT 30001" in sql
        assert "ORDER BY unified_code" in sql and "UNION" in sql
        conn.__exit__.assert_called_once()
    if first:
        assert connections[0] is not connections[1]


@pytest.mark.parametrize("first,second,attempts", [
    (failure(), failure(), 2),
    (failure(invalidated=False), None, 1),
    (failure(1045), None, 1),
    (failure(1064), None, 1),
    (failure(1205), None, 1),
    (failure(3024), None, 1),
])
async def test_pool_replay_is_bounded_and_error_specific(first, second, attempts):
    q, connections = query([first, second])
    with pytest.raises(OperationalError) as caught:
        await q.securities()
    assert caught.value is (second if attempts == 2 else first)
    assert len(connections) == attempts
    assert all(c.__exit__.call_count == 1 for c in connections)


@pytest.mark.parametrize("rows", [[], ["bad"], ["000001.SZ"] * 30001])
async def test_invalid_pool_cannot_retry_into_a_partial_success(rows):
    q, connections = query([rows, ["000001.SZ"]])
    with pytest.raises(ValueError):
        await q.securities()
    assert len(connections) == 1


async def test_explicit_scope_needs_no_database():
    q, connections = query([])
    assert await q.securities(["600001.SH", "000001.SZ"]) == ["000001.SZ", "600001.SH"]
    for codes in ([], ["000001.SZ", "000001.SZ"], ["invalid"]):
        with pytest.raises(ValueError):
            await q.securities(codes)
    assert not connections
