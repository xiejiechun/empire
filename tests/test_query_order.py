"""Adversarial all-result ordering, independent of desktop/current-page order."""

import pytest
from sqlalchemy import create_engine, text

from empire.plugins.infra.query_order import column_fields, ordered_page


@pytest.fixture
def connection():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE item (id INTEGER PRIMARY KEY, amount BIGINT, category TEXT)'))
        # Insertion order disagrees with both sort directions; ties span pages.
        conn.execute(text('INSERT INTO item VALUES (:id,:amount,:category)'), [
            dict(id=i, amount=None if i % 7 == 0 else 9007199254740992 + i % 5,
                 category='选中' if i % 3 else '排除') for i in range(1, 112)
        ])
        yield conn
    engine.dispose()


def page(conn, direction, after=None, category='选中', limit=13):
    return ordered_page(
        conn, 'SELECT * FROM item WHERE category=:category', {'category': category},
        order={'field': 'amount', 'direction': direction}, fields=column_fields(('amount', 'id')),
        identity=('id',), after=after, limit=limit,
    )


@pytest.mark.parametrize('direction', ['asc', 'desc'])
def test_whole_filtered_set_ties_nulls_and_large_integers(connection, direction):
    rows, cursor = [], None
    while True:
        batch, cursor = page(connection, direction, cursor)
        assert len(batch) <= 13
        rows.extend(batch)
        if cursor is None:
            break
    source = [dict(r) for r in connection.execute(text(
        "SELECT * FROM item WHERE category='选中'"
    )).mappings()]
    expected = sorted(source, key=lambda r: (
        r['amount'] is None,
        (r['amount'] or 0) * (1 if direction == 'asc' else -1), r['id'],
    ))
    assert rows == expected
    assert len({r['id'] for r in rows}) == len(rows) == 74
    assert all('__order_value' not in r for r in rows)


def test_cursor_rejects_changed_filter_or_order(connection):
    _, cursor = page(connection, 'asc')
    for direction, category in [('desc', '选中'), ('asc', '排除')]:
        with pytest.raises(ValueError, match='游标'):
            page(connection, direction, cursor, category)


def test_computed_values_are_sorted_before_limit(connection):
    rows, _ = ordered_page(
        connection, 'SELECT id, amount, -id AS computed FROM item', {},
        order={'field': 'computed', 'direction': 'asc'}, fields=column_fields(('computed',)),
        identity=('id',), limit=2,
    )
    assert [r['id'] for r in rows] == [111, 110]


@pytest.mark.parametrize('order', [
    {'field': 'amount;DROP TABLE item', 'direction': 'asc'},
    {'field': 'amount', 'direction': 'desc LIMIT 1'},
    {'field': 'amount', 'direction': 'asc', 'sql': '1'},
])
def test_sort_is_a_closed_contract(connection, order):
    with pytest.raises(ValueError, match='排序字段'):
        ordered_page(connection, 'SELECT * FROM item', {}, order=order,
                     fields=column_fields(('amount',)), identity=('id',))
