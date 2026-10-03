from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from empire.contracts.business_schema import DATASET_TABLES, FIXED_SOURCES, require_dataset_source
from empire.plugins.datasets import industries, intraday, stocks, suspensions, trade_calendar
from empire.plugins.datasets.capital_archive import CapitalDataset
from empire.plugins.datasets.financial_archive import FinancialDataset


@pytest.mark.parametrize('dataset,table', DATASET_TABLES.items())
def test_wrong_source_cannot_enter_fixed_dataset(dataset,table):
    require_dataset_source(dataset,FIXED_SOURCES[table])
    with pytest.raises(ValueError,match='固定来源'):
        require_dataset_source(dataset,'another')


@pytest.mark.parametrize('mapping', [stocks,industries,intraday,suspensions,trade_calendar,
                                    CapitalDataset('dividends'),FinancialDataset('income')])
def test_direct_sql_writer_rejects_wrong_source_before_sql(mapping):
    conn=MagicMock()
    envelope=SimpleNamespace(source='another',observed_at=datetime.now(UTC))
    with pytest.raises(ValueError,match='固定来源'):
        mapping.write(conn,envelope,{})
    conn.execute.assert_not_called()


def test_news_keeps_independent_source_namespace():
    require_dataset_source('news.page','sina')
    require_dataset_source('news.page','another')
