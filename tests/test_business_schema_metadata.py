"""SQL ownership resource safety and behavior at its actual consumers."""
import copy
import importlib.util
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from empire.contracts import business_schema as schema
from scripts.documentation_contract import product_sources, reachable_sources
from scripts.documentation_storage import storage_snapshots
from scripts.verify_database_design import verify_ownership

ROOT = Path(__file__).resolve().parents[1]


def metadata():
    return json.loads((ROOT / 'sql/business-schema.json').read_text(encoding='utf-8'))


def write_metadata(root, value):
    path = root / 'sql/business-schema.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_maintenance_inventory_and_child_table_keep_distinct_meaning():
    assert isinstance(schema.FIXED_SOURCES, MappingProxyType)
    assert isinstance(schema.TABLES, tuple)
    assert all(isinstance(group, tuple) for group in schema.DATASET_TABLE_GROUPS.values())
    assert all(isinstance(keys, list) for keys in schema.PRIMARY_KEYS.values())
    assert 'suspension_source_date' not in schema.TABLES
    assert 'suspension_source_date' not in schema.FIXED_SOURCES
    assert schema.dataset_tables('suspensions.period') == ('suspension_event', 'suspension_source_date')
    assert schema.PRIMARY_KEYS['suspension_source_date'] == [
        'source_date', 'unified_code', 'suspended_at', 'resume_key', 'record_key']
    assert schema.TABLES[-3:] == ('finance_news', 'collection_state', 'app_setting')
    assert metadata()['primary_key_exemptions'] == ['finance_news', 'collection_state', 'app_setting']


def test_source_checks_preserve_shared_stock_and_unrestricted_news():
    for source in ('sina', 'ths'):
        schema.require_fixed_source('stock', source)
        schema.require_dataset_source('stock.universe.page', source)
    schema.require_dataset_source('news.flash.page', 'another')
    schema.require_dataset_source('unregistered.dataset', 'another')
    with pytest.raises(ValueError, match='stock 固定来源不匹配；正式归属为 sina'):
        schema.require_fixed_source('stock', 'another')
    with pytest.raises(ValueError, match='固定来源'):
        schema.require_dataset_source('calendar.month', 'sina')
    with pytest.raises(KeyError):
        schema.require_fixed_source('unregistered_table', 'sina')


@pytest.mark.parametrize('table', ['dividend_plan', 'additional_issue', 'rights_issue'])
def test_capital_queries_still_require_security_and_preserve_primary_order(table):
    columns, keys = schema.schema_contract(table, 'event_date')
    assert columns == {table: {'record_key', 'unified_code', 'event_date'}}
    assert keys[table] is schema.PRIMARY_KEYS[table]


@pytest.mark.parametrize('damage', [
    'field', 'version', 'duplicate_table', 'missing_group', 'wrong_head',
    'missing_primary', 'missing_child_primary', 'overlapping_exemption', 'unknown_exemption',
    'unknown_override', 'exclude_primary_source', 'required_without_primary',
])
def test_malformed_ownership_rejected_before_consumers(damage):
    value = metadata()
    if damage == 'field':
        value['ignored_extra'] = True
    elif damage == 'version':
        value['schema'] = True
    elif damage == 'duplicate_table':
        value['tables'].append(value['tables'][0])
    elif damage == 'missing_group':
        value['dataset_table_groups'].pop('holders.reports')
    elif damage == 'wrong_head':
        value['dataset_table_groups']['holders.reports'].reverse()
    elif damage == 'missing_primary':
        value['primary_keys'].pop('holder_report')
    elif damage == 'missing_child_primary':
        value['primary_keys'].pop('suspension_source_date')
    elif damage == 'overlapping_exemption':
        value['primary_key_exemptions'].append('stock')
    elif damage == 'unknown_exemption':
        value['primary_key_exemptions'].append('unknown_table')
    elif damage == 'unknown_override':
        value['source_overrides']['unknown'] = ['source']
    elif damage == 'exclude_primary_source':
        value['source_overrides']['stock'] = ['ths']
    elif damage == 'required_without_primary':
        value['required_columns']['finance_news'] = ['source']
    with pytest.raises(ValueError, match='业务结构归属登记无效'):
        schema.validate_business_schema(value)


def test_missing_or_duplicate_resource_never_falls_back(tmp_path):
    with pytest.raises(FileNotFoundError):
        schema.read_business_schema(tmp_path / 'not-published.json')
    path = tmp_path / 'duplicates.json'
    path.write_text('{"schema":1,"schema":1}', encoding='utf-8')
    with pytest.raises(ValueError, match='重复 JSON 字段'):
        schema.read_business_schema(path)


def test_module_initialization_requires_resource_at_the_declared_root(tmp_path, monkeypatch):
    from empire.core import config

    monkeypatch.setattr(config, 'resource_root', lambda: tmp_path)
    spec = importlib.util.spec_from_file_location('isolated_schema_resource_check', schema.__file__)
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(FileNotFoundError):
        spec.loader.exec_module(module)
    path = write_metadata(tmp_path, metadata())
    path.write_text('{broken json', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        spec.loader.exec_module(module)


@pytest.mark.parametrize('damage', ['invalid_table', 'invalid_column', 'duplicate_column', 'dataset_order'])
def test_invalid_identifiers_columns_and_dataset_order_rejected(damage):
    value = metadata()
    if damage == 'invalid_table':
        value['tables'].append('unsafe;DROP')
    elif damage == 'invalid_column':
        value['primary_keys']['stock'] = ['unified_code DESC']
    elif damage == 'duplicate_column':
        value['primary_keys']['stock'].append('unified_code')
    else:
        value['dataset_table_groups'] = dict(reversed(list(value['dataset_table_groups'].items())))
    with pytest.raises(ValueError, match='业务结构归属登记无效'):
        schema.validate_business_schema(value)


@pytest.mark.parametrize('damage', ['missing_dataset', 'unknown_table', 'wrong_key', 'missing_column', 'legacy_source'])
def test_design_gate_checks_resource_against_real_ddl_and_active_datasets(tmp_path, damage):
    value = metadata()
    shapes = json.loads((ROOT / 'sql/schema-contract.json').read_text(encoding='utf-8'))['tables']
    active = set(value['dataset_table_groups'])
    if damage == 'missing_dataset':
        active.add('unregistered.dataset')
        message = '正式数据贡献'
    elif damage == 'unknown_table':
        value['dataset_table_groups']['suspensions.period'].append('unknown_table')
        value['primary_keys']['unknown_table'] = ['id']
        message = '业务表必须登记'
    elif damage == 'wrong_key':
        value['primary_keys']['holder_member'].reverse()
        message = '主键'
    elif damage == 'missing_column':
        value['required_columns']['dividend_plan'].append('unknown_column')
        message = '附加必需字段'
    else:
        shapes['stock']['columns']['source'] = {'type': 'varchar(20)'}
        message = '旧 source 列'
    write_metadata(tmp_path, value)
    with pytest.raises(ValueError, match=message):
        verify_ownership(tmp_path, shapes, active)


def test_design_gate_uses_explicit_root_and_keeps_full_physical_table_set(tmp_path):
    value = metadata()
    write_metadata(tmp_path, value)
    shapes = json.loads((ROOT / 'sql/schema-contract.json').read_text(encoding='utf-8'))['tables']
    assert len(shapes) == 55 and len(value['tables']) == 54
    assert verify_ownership(tmp_path, shapes, value['dataset_table_groups']) == value


def test_feature_documentation_reachability_includes_sql_resource(tmp_path):
    module = tmp_path / 'src/empire/contracts/business_schema.py'
    module.parent.mkdir(parents=True)
    module.write_text('# Static documentation dependency fixture\n', encoding='utf-8')
    path = write_metadata(tmp_path, metadata())
    first = reachable_sources(tmp_path, ['empire.contracts.business_schema'])
    changed = metadata()
    changed['fixed_sources']['stock'] = 'ths'
    write_metadata(tmp_path, changed)
    second = reachable_sources(tmp_path, ['empire.contracts.business_schema'])
    assert set(first) == {'src/empire/contracts/business_schema.py', path.relative_to(tmp_path).as_posix()}
    assert first['sql/business-schema.json'] != second['sql/business-schema.json']


def test_sql_json_change_invalidates_global_documentation_identity(tmp_path):
    for name in ('src/empire/plugins/collection/rules.json', 'config/app.example.toml', 'Empire.spec'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('', encoding='utf-8')
    write_metadata(tmp_path, metadata())
    first = product_sources(tmp_path)
    changed = metadata()
    changed['fixed_sources']['stock'] = 'ths'
    write_metadata(tmp_path, changed)
    assert first['sql/business-schema.json'] != product_sources(tmp_path)['sql/business-schema.json']


@pytest.mark.parametrize('change', ['source', 'maintenance_order', 'primary_exemption'])
def test_table_documentation_snapshot_tracks_source_ownership_changes(tmp_path, change):
    write_metadata(tmp_path, metadata())
    (tmp_path / 'sql/schema.sql').write_text(
        'CREATE TABLE IF NOT EXISTS stock (\n unified_code VARCHAR(9),\n PRIMARY KEY (unified_code)\n) ENGINE', encoding='utf-8')
    source = tmp_path / 'src/empire/query.py'
    source.parent.mkdir(parents=True)
    source.write_text('# mock query dependency\n', encoding='utf-8')
    storage = {'mysql': {'stock': {'topic': 'stock', 'sources': ['src/empire/query.py']}}, 'redis': {}}
    articles = {'stock': SimpleNamespace(title='stock', summary='stock meaning', body='stock body')}
    first = storage_snapshots(tmp_path, storage, articles, lambda *_: {})
    changed = copy.deepcopy(metadata())
    if change == 'source':
        changed['fixed_sources']['stock'] = 'ths'
    elif change == 'maintenance_order':
        changed['tables'].reverse()
    else:
        changed['fixed_sources'].pop('stock')
        changed['source_overrides'].pop('stock')
        changed['primary_keys'].pop('stock')
        changed['primary_key_exemptions'].append('stock')
    write_metadata(tmp_path, changed)
    second = storage_snapshots(tmp_path, storage, articles, lambda *_: {})
    key = 'sql/business-schema.json#stock'
    assert first['mysql:stock']['sources'][key] != second['mysql:stock']['sources'][key]
