"""Isolated MySQL tests of exact values, lossless relations and scoped updates."""
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.features.themes.history_model import decimal_text, digest
from empire.features.themes.repository import read_daily, read_detail, replace_daily, replace_detail
from empire.features.themes.storage_contract import binary32
from empire.plugins.infra.mysql_store import make_engine
from tests.test_theme_storage_contract import mapped

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private MySQL opt-in')]


@pytest.fixture
def storage():
    engine = make_engine(load_config()['mysql'])
    dml = []
    def capture(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and 'theme_' in statement:
            dml.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        yield engine, dml
    finally:
        engine.dispose()


def test_detail_repeat_multireason_revision_removal_and_transaction_rollback(storage):
    engine, dml = storage
    data, stamp = mapped(), datetime.now(UTC)
    relation = deepcopy(data['relations'][0])
    relation.update(reason='同分类同证券第二条理由', first_shelved_at=1703489300)
    relation['relation_id'] = digest({k: v for k, v in relation.items() if k not in ('relation_id', 'occurrences')})
    data['relations'].append(relation)
    data['relations'].sort(key=lambda r: r['relation_id'])
    with engine.begin() as conn:
        assert replace_detail(conn, data, stamp) == 5
    with engine.begin() as conn:
        head, actual = read_detail(conn, '148')
        assert actual == data and head['content_sha256'] == digest(data)
        before = len(dml)
        assert replace_detail(conn, data, stamp + timedelta(minutes=3)) == 0
        assert len(dml) == before
    revised = deepcopy(data)
    revised['relations'][0]['occurrences'] = 2
    with engine.begin() as conn:
        assert replace_detail(conn, revised, stamp + timedelta(minutes=6)) == 2
    with pytest.raises(RuntimeError, match='rollback'):
        with engine.begin() as conn:
            replace_detail(conn, data, stamp + timedelta(minutes=9))
            raise RuntimeError('rollback')
    with engine.connect() as conn:
        assert read_detail(conn, '148')[1] == revised
    revised['relations'].pop()
    with engine.begin() as conn:
        assert replace_detail(conn, revised, stamp + timedelta(minutes=12)) == 2
        assert read_detail(conn, '148')[1] == revised


def test_daily_float_roundtrip_same_count_different_keys_and_day_retention(storage):
    engine, dml = storage
    stamp = datetime.now(UTC)
    def row(key, number):
        return dict(theme_id=key, source_theme_id=key, concept_id=None, name='题材' + key,
                    parent_id=None, new_flag=0, rank_no=1, display_order=0, hot_score='34200',
                    change_rate=decimal_text(Decimal.from_float(binary32(number)), 149, 12), limit_up_count=1)
    # DOUBLE retains every binary32 value, including the smallest subnormal.
    rows = [row('1', 1.9396617412567139), row('2', 1.401298464324817e-45)]
    with engine.begin() as conn:
        assert replace_daily(conn, '2026-10-23', rows, stamp) == 2
        assert read_daily(conn, '2026-10-23')[1] == rows
        before = len(dml)
        assert replace_daily(conn, '2026-10-23', rows, stamp + timedelta(minutes=3)) == 0
        assert len(dml) == before
        changed = [rows[0], row('3', -1.125)]
        assert replace_daily(conn, '2026-10-23', changed, stamp) == 2
        assert read_daily(conn, '2026-10-23')[1] == changed
        assert replace_daily(conn, '2026-10-24', rows, stamp) == 2
        assert conn.execute(text('SELECT COUNT(*) FROM theme_daily')).scalar_one() == 4
