import copy
import json
from pathlib import Path

import pytest

from scripts.schema_evidence_scope import objects, verify

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence(tmp_path):
    (tmp_path / 'sql').mkdir()
    for name in ('schema.sql', 'schema-contract.json', 'business-schema.json'):
        (tmp_path / 'sql' / name).write_bytes((ROOT / 'sql' / name).read_bytes())
    shape = json.loads((tmp_path / 'sql/schema-contract.json').read_text('utf-8'))
    owner = json.loads((tmp_path / 'sql/business-schema.json').read_text('utf-8'))
    frozen = objects((tmp_path / 'sql/schema.sql').read_text('utf-8'), shape, owner, ['theme_daily'])
    return tmp_path, {'schema_objects': frozen}


def test_unchanged_owned_objects_ignore_unrelated_additive_ddl(evidence):
    root, value = evidence
    verify(root, value, ['theme_daily'])
    path = root / 'sql/schema.sql'
    path.write_text(path.read_text('utf-8') + '\nCREATE TABLE IF NOT EXISTS unrelated (id INT);', encoding='utf-8')
    verify(root, value, ['theme_daily'])
    with pytest.raises(ValueError, match='cover'):
        verify(root, value, ['theme_stock'])


@pytest.mark.parametrize('kind', ['ddl', 'shape', 'owner', 'dataset', 'required', 'exemption'])
def test_changed_business_fact_invalidates_measurement(evidence, kind):
    root, value = evidence
    if kind == 'ddl':
        path = root / 'sql/schema.sql'
        path.write_text(path.read_text('utf-8').replace('change_rate DOUBLE NOT NULL', 'change_rate FLOAT NOT NULL'), encoding='utf-8')
    else:
        path = root / ('sql/schema-contract.json' if kind == 'shape' else 'sql/business-schema.json')
        data = json.loads(path.read_text('utf-8'))
        if kind == 'shape':
            data['tables']['theme_daily']['columns']['change_rate']['nullable'] = True
        elif kind == 'owner':
            data['fixed_sources']['theme_daily'] = 'other'
        elif kind == 'dataset':
            data['dataset_table_groups']['kaipanla.themes.day'].append('theme_detail')
        elif kind == 'required':
            data['required_columns']['theme_daily'].remove('change_rate')
        else:
            data['primary_key_exemptions'].append('theme_daily')
        path.write_text(json.dumps(data), encoding='utf-8')
    frozen = copy.deepcopy(value)
    with pytest.raises(ValueError, match='remeasurement'):
        verify(root, value, ['theme_daily'])
    assert value == frozen
