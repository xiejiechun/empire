import json
from unittest.mock import MagicMock

import pytest

from scripts import release_test_preflight as preflight


def test_private_settings_required_and_port_checked(tmp_path):
    with pytest.raises(ValueError, match='EMPIRE_TEST_MYSQL_SETTINGS'):
        preflight.settings(None)
    path = tmp_path / 'test.json'
    for port in (3307, 13361, '13348'):
        path.write_text(json.dumps({'port': port}))
        with pytest.raises(ValueError, match='13348'):
            preflight.settings(path)
    path.write_text(json.dumps({'port': 13348}))
    assert preflight.settings(path)['connect_timeout'] == 5


def engines(monkeypatch, same=False, failure=False):
    source, target = MagicMock(), MagicMock()
    source.connect.return_value.__enter__.return_value.exec_driver_sql.return_value.scalar_one.return_value = 'production'
    conn = target.connect.return_value.execution_options.return_value.__enter__.return_value
    statements = []

    def execute(sql):
        statements.append(sql)
        result = MagicMock()
        result.one.return_value = ('production' if same else 'private', 13348)
        result.scalar_one.return_value = 1
        if failure and sql.startswith('INSERT'):
            raise RuntimeError('injected')
        return result

    conn.exec_driver_sql.side_effect = execute
    monkeypatch.setattr(preflight, 'make_engine', MagicMock(side_effect=[source, target]))
    return statements, source, target


def test_same_server_rejected_before_any_write(monkeypatch):
    statements, source, target = engines(monkeypatch, same=True)
    with pytest.raises(ValueError, match='identity'):
        preflight.sql_check({}, {})
    assert all(sql.startswith('SELECT') for sql in statements)
    source.dispose.assert_called_once()
    target.dispose.assert_called_once()


@pytest.mark.parametrize('failure', [False, True])
def test_own_probe_database_cleaned_even_on_failure(monkeypatch, failure):
    statements, _, _ = engines(monkeypatch, failure=failure)
    if failure:
        with pytest.raises(RuntimeError, match='injected'):
            preflight.sql_check({}, {})
    else:
        preflight.sql_check({}, {})
    assert statements[-1].startswith('DROP DATABASE `empire_preflight_')
    assert statements[-1].removeprefix('DROP DATABASE ') == statements[1].removeprefix('CREATE DATABASE ')
