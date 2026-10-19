"""The extracted readers retain the caller connection and dataset protocol."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from empire.contracts.dataset import DatasetContribution
from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.stocks import dataset as stocks
from empire.features.stocks.api import current_directory
from empire.plugins.datasets.astock import DatasetPlugin


class Connection:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def execute(self, statement, parameters):
        self.calls.append((str(statement), parameters))
        return self

    def mappings(self):
        return self

    def all(self):
        return self.records


def test_stock_dataset_keeps_aggregate_reader_with_the_callers_connection():
    connection = Connection([
        {'source': 'sina', 'payload': {'version': '2026-10-01', 'publication': {'row_count': 6000}}},
        {'source': 'ths', 'payload': {'version': '2026-10-02', 'publication': {'row_count': 6001}}},
    ])
    catalog = DatasetPlugin((DatasetContribution(stocks, 'aggregate',
        {'sina-universe-v1': 'sina-stocks', 'ths-universe-v1': 'ths-stocks'},
        stale_outcome='superseded'),))
    envelope = SimpleNamespace(dataset='stock.universe.complete', schema_version=1)

    result = catalog.aggregate_current(connection, envelope, 'consumer-namespace')

    assert result['source'] == 'ths' and result['publication']['row_count'] == 6001
    assert len(connection.calls) == 1
    assert connection.calls[0][1] == {'namespace': 'consumer-namespace'}
    assert 'FOR UPDATE' not in connection.calls[0][0]


@pytest.mark.parametrize('lock', [False, True])
def test_stock_public_reader_leaves_lock_choice_to_the_transaction_owner(lock):
    connection = Connection([])
    assert current_directory(connection, 'consumer-namespace', lock=lock) == {}
    assert len(connection.calls) == 1
    assert ('FOR UPDATE' in connection.calls[0][0]) is lock


def test_calendar_reader_uses_existing_connection_and_returns_unknown_for_a_gap():
    connection = Connection([
        {'trade_date': date(2026, 10, 16), 'is_trade': 1},
        {'trade_date': date(2026, 10, 18), 'is_trade': 0},
    ])
    cutoff, note = read_trade_day_cutoff(connection, datetime(2026, 10, 18, 10, tzinfo=CHINA))
    assert cutoff is None and '2026-10-17' in note
    assert len(connection.calls) == 1
    assert connection.calls[0][1]['end'] == date(2026, 10, 18)
