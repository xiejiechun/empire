"""A stale configuration cannot bypass the test-owned SQL boundary."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from empire.plugins.infra.mysql_store import make_engine

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1' or not os.environ.get('EMPIRE_TEST_MYSQL_SETTINGS'),
    reason='Explicit private MySQL instance required')]


def test_unowned_database_is_rejected_before_statement_execution():
    settings=json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text(encoding='utf-8'))
    engine=make_engine(settings)
    try:
        with engine.connect() as conn, pytest.raises(RuntimeError,match='test-owned'):
            conn.execute(text('SELECT 1'))
    finally:
        engine.dispose()
