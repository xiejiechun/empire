"""Safety bounds and offline schema design gate counterexamples."""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from empire.contracts.market_storage import number
from empire.plugins.datasets.kaipanla_products import digest
from empire.plugins.datasets.market_mapping import decode, encode
from empire.plugins.datasets.trade_blocks import unpack
from scripts.verify_database_design import verify
from tests.test_kaipanla_products import business_row


def test_exact_numeric_range_and_unknown_fields():
    assert number(1.001) == Decimal('1.001')
    for value in (float('inf'), 10**18, 1e-13):
        with pytest.raises(ValueError):
            number(value)
    row = business_row('quote')
    row['data']['real']['unknown'] = 1
    with pytest.raises(ValueError, match='未经'):
        encode(row, '', None)


def test_binary_same_second_float_masks_and_corrupt_block():
    from datetime import datetime
    row = business_row('trades')
    row['data']['fb'][0][1] = 10.0
    row['data']['fb'][0][4] = -0.0
    head, facts = encode(row, digest(row), datetime.now())
    actual = decode(head, facts)
    assert actual == row and digest(actual) == digest(row)
    block = facts['stock_intraday_trade_block'][0]
    assert len(unpack(block)) == 2
    with pytest.raises(ValueError):
        unpack({**block, 'body': block['body'][:-1]})


def test_equal_total_with_wrong_internal_block_boundary_is_rejected():
    from datetime import datetime

    from empire.plugins.datasets.trade_blocks import pack
    row = business_row('trades')
    point = row['data']['fb'][0]
    row['data']['fb'] = [list(point) for _ in range(300)]
    row['data'].update(Count=300, total=300)
    head, facts = encode(row, digest(row), datetime.now())
    params = {k: head[k] for k in ('unified_code', 'trade_date')}
    first = pack(row['data']['fb'][:100], params)[0]
    second = pack(row['data']['fb'][100:], params)[0]
    second.update(block_seq=1, first_seq=200, last_seq=399)
    facts['stock_intraday_trade_block'] = [first, second]
    with pytest.raises(ValueError, match='边界'):
        decode(head, facts)


def test_missing_design_and_changed_ddl_fail_offline_gate(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for relative in ('sql/schema.sql', 'sql/schema-contract.json', 'docs/database-design-cards.json'):
        target = tmp_path/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root/relative).read_bytes())
    manifest = json.loads((tmp_path/'docs/database-design-cards.json').read_text('utf-8'))
    manifest['datasets'].pop('kaipanla.trades.day')
    (tmp_path/'docs/database-design-cards.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='设计卡'):
        verify(tmp_path)
    (tmp_path/'sql/schema.sql').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='DDL'):
        verify(tmp_path)


def test_quote_optional_presence_zero_and_book_extras_roundtrip():
    from datetime import datetime
    row = copy.deepcopy(business_row('quote'))
    row['data']['weituo']['avg_bidpx'] = 0.0
    row['data']['real']['vol_ratio'] = 0
    head, facts = encode(row, digest(row), datetime.now())
    actual = decode(head, facts)
    assert digest(actual) == digest(row)
    assert 'jtPeRate' not in actual['data']['real']


def test_optional_null_zero_and_absence_are_distinct():
    from datetime import datetime

    from empire.plugins.datasets.kaipanla_products import validate
    for value in (None, 0, 0.0):
        row = business_row('quote')
        row['data']['real']['pe_rate'] = value
        validate(row)
        head, facts = encode(row, digest(row), datetime.now())
        actual = decode(head, facts)
        assert digest(actual) == digest(row) and actual['data']['real']['pe_rate'] == value
        assert 'jtPeRate' not in actual['data']['real']
    row['data']['real']['last_px'] = None
    with pytest.raises(ValueError):
        validate(row)


@pytest.mark.parametrize('failure', ['stale', 'over_budget'])
def test_capacity_evidence_is_bound_and_enforced(tmp_path, failure):
    root = Path(__file__).resolve().parents[1]
    cards = json.loads((root/'docs/database-design-cards.json').read_text('utf-8'))
    evidence_path = cards['datasets']['kaipanla.trades.day']['capacity']['evidence']
    evidence = json.loads((root/evidence_path).read_text('utf-8'))
    paths = {'sql/schema.sql', 'sql/schema-contract.json', 'docs/database-design-cards.json', evidence_path, *evidence['bindings']}
    for card in cards['datasets'].values():
        paths.update([card['dictionary'], *card['tests']])
        if card['capacity']['status'] == 'measured':
            path = card['capacity']['evidence']
            measured = json.loads((root/path).read_text('utf-8'))
            paths.update([path, *measured['bindings']])
    for path in paths:
        target = tmp_path/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root/path).read_bytes())
    assert verify(tmp_path)['tables'] == 55
    if failure == 'stale':
        (tmp_path/'src/empire/plugins/datasets/trade_blocks.py').write_text('changed', encoding='utf-8')
        pattern = '证据已过期'
    else:
        metric = next(key for key in evidence['limits'] if 'page_p95_ms' in key)
        evidence['measurements'][metric] = evidence['limits'][metric] * 10
        (tmp_path/evidence_path).write_text(json.dumps(evidence), encoding='utf-8')
        pattern = '容量预算超限'
    with pytest.raises(ValueError, match=pattern):
        verify(tmp_path)


def test_unregistered_actual_dataset_cannot_bypass_design_gate(monkeypatch):
    from types import SimpleNamespace

    import scripts.verify_database_design as gate
    actual = gate.DatasetPlugin().datasets
    monkeypatch.setattr(gate, 'DatasetPlugin', lambda: SimpleNamespace(datasets={**actual, 'new.unregistered': object()}))
    with pytest.raises(ValueError, match='正式数据贡献'):
        gate.verify(Path(__file__).resolve().parents[1])
