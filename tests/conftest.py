"""Keep existing transport/archival fixtures focused on a single dividend period."""
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def bounded_dividend_period_fixture(request, monkeypatch):
    if request.module.__name__.split('.')[-1] in {
        'test_capital_lifecycle', 'test_capital_recovery', 'test_capital_archive',
    }:
        monkeypatch.setattr('empire.features.capital_actions.dividend_history.report_periods',
                            AsyncMock(return_value=['2025-12-31']))
