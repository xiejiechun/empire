import json
from unittest.mock import MagicMock

import pytest

from empire.plugins.infra.collection_state_unit import read_unit, save_unit, unit_path


def test_path_rejects_untrusted_source():
    assert unit_path('SZ:000001') == '$.units."SZ:000001"'
    with pytest.raises(ValueError):
        unit_path('SZ:000001".other')


def test_bounded_read_checks_owner_and_does_not_select_entire_payload():
    conn = MagicMock()
    row = dict(source='ths', dataset='ths_income', contract_version='1', progress=None,
               manifest=None, unit=json.dumps({'dates': ['2025-12-31']}))
    conn.execute.return_value.mappings.return_value.first.return_value = row
    previous, exists = read_unit(conn, 'test', 'ths-income', 'ths', 'SZ:000001')
    assert exists and previous['units'] == {'SZ:000001': {'dates': ['2025-12-31']}}
    sql = str(conn.execute.call_args.args[0])
    assert 'JSON_EXTRACT' in sql and 'FOR UPDATE' in sql
    assert 'SELECT source,payload' not in sql
    with pytest.raises(ValueError, match='来源'):
        read_unit(conn, 'test', 'ths-income', 'wrong', 'SZ:000001')


def test_partial_update_does_not_send_other_security():
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 'OBJECT'
    previous = {'contract_version': 1, 'units': {'SH:600001': {'dates': ['2024-12-31']}}}
    changed = {'contract_version': 1, 'units': {'SH:600001': {'dates': ['2025-12-31']}}}
    save_unit(conn, 'test', 'p', 'ths', 'ths_income', 'SH:600001', changed, previous, True)
    sql, params = conn.execute.call_args.args
    assert 'JSON_SET' in str(sql) and 'payload=:payload' not in str(sql)
    assert params['p0'] == '$.units."SH:600001"'
    assert '2024-12-31' not in json.dumps(params, default=str)


def test_unchanged_state_has_no_dml():
    conn = MagicMock()
    save_unit(conn, 'test', 'p', 'ths', 'ths_income', 'manifest', {}, {}, True)
    conn.execute.assert_not_called()


def test_disallowed_cross_unit_update_rejected():
    with pytest.raises(ValueError, match='其他证券'):
        save_unit(MagicMock(), 'test', 'p', 'ths', 'ths_income', 'SH:600001',
                  {'units': {'SZ:000001': {}}}, {}, True)
