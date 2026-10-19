"""Read the explicit SQL ownership resource without importing concrete features."""
import json
import re
from pathlib import Path
from types import MappingProxyType
from typing import TypedDict, cast

from empire.core.config import resource_root

_FIELDS = frozenset({'schema', 'fixed_sources', 'tables', 'dataset_tables',
                     'dataset_table_groups', 'primary_keys', 'source_overrides',
                     'required_columns', 'primary_key_exemptions'})
_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]*')


class BusinessSchema(TypedDict):
    schema: int
    fixed_sources: dict[str, str]
    tables: list[str]
    dataset_tables: dict[str, str]
    dataset_table_groups: dict[str, list[str]]
    primary_keys: dict[str, list[str]]
    source_overrides: dict[str, list[str]]
    required_columns: dict[str, list[str]]
    primary_key_exemptions: list[str]


def _require(value: object, message: str) -> None:
    if not value:
        raise ValueError('业务结构归属登记无效：' + message)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result, '重复 JSON 字段 ' + key)
        result[key] = value
    return result


def _names(raw: object, label: str, *, identifiers: bool = True) -> None:
    _require(isinstance(raw, list) and bool(raw), label + ' 须为非空有序列表')
    value = cast(list[object], raw)
    _require(all(isinstance(item, str) and bool(item) for item in value), label + ' 名称无效')
    _require(len(value) == len(set(value)), label + ' 名称重复')
    if identifiers:
        _require(all(_IDENTIFIER.fullmatch(cast(str, item)) for item in value), label + ' SQL 标识无效')


def validate_business_schema(raw: object) -> BusinessSchema:
    """Validate resource structure; SQL shapes and active datasets are checked by the gate."""
    _require(isinstance(raw, dict) and set(raw) == _FIELDS, '顶层字段不匹配')
    value = cast(BusinessSchema, raw)
    _require(type(value['schema']) is int and value['schema'] == 1, '不支持的资源版本')
    _names(value['tables'], 'tables')
    _names(value['primary_key_exemptions'], 'primary_key_exemptions')
    for field in _FIELDS - {'schema', 'tables', 'primary_key_exemptions'}:
        _require(isinstance(cast(dict[str, object], raw)[field], dict), field + ' 须为对象')
    for field in ('fixed_sources', 'dataset_tables', 'dataset_table_groups', 'primary_keys'):
        _require(bool(cast(dict[str, object], raw)[field]), field + ' 不得为空')
    fixed, datasets, groups = value['fixed_sources'], value['dataset_tables'], value['dataset_table_groups']
    _require(set(fixed) <= set(value['tables']), '固定来源表未登记维护清单')
    _require(all(isinstance(table, str) and _IDENTIFIER.fullmatch(table) and isinstance(source, str) and bool(source)
                 for table, source in fixed.items()), '固定来源无效')
    _require(list(datasets) == list(groups), '数据集与表组的集合或顺序不匹配')
    for dataset, tables in groups.items():
        _require(isinstance(dataset, str) and bool(dataset) and len(dataset) <= 200, '数据集标识无效')
        _names(tables, dataset)
        _require(datasets[dataset] == tables[0], dataset + ' 主表须为表组首项')
    known = set(value['tables']) | {table for tables in groups.values() for table in tables}
    primary, exempt = set(value['primary_keys']), set(value['primary_key_exemptions'])
    _require(not primary & exempt and primary | exempt == known, '主键登记及明确例外未完整覆盖业务表')
    for field, mapping in (('primary_keys', value['primary_keys']), ('required_columns', value['required_columns'])):
        for table, columns in mapping.items():
            _require(table in known, field + ' 使用未登记表 ' + table)
            _names(columns, field + '.' + table)
    _require(set(fixed) <= set(value['primary_keys']), '固定来源表缺少主键登记')
    _require(set(value['required_columns']) <= set(value['primary_keys']), '附加必需列缺少主键登记')
    for table, sources in value['source_overrides'].items():
        _require(table in fixed, '来源例外使用未登记固定来源表 ' + table)
        _names(sources, 'source_overrides.' + table, identifiers=False)
        _require(fixed[table] in sources, '来源例外未包含正式来源 ' + table)
    return value


def read_business_schema(path: Path) -> BusinessSchema:
    """Read one explicit resource; no fallback, discovery, SQL or runtime mutation."""
    return validate_business_schema(json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object))


_SCHEMA = read_business_schema(resource_root() / 'sql/business-schema.json')
FIXED_SOURCES = MappingProxyType(_SCHEMA['fixed_sources'])
TABLES = tuple(_SCHEMA['tables'])
DATASET_TABLES = _SCHEMA['dataset_tables']
DATASET_TABLE_GROUPS = {dataset: tuple(tables) for dataset, tables in _SCHEMA['dataset_table_groups'].items()}
PRIMARY_KEYS = _SCHEMA['primary_keys']
SOURCE_OVERRIDES = {table: tuple(sources) for table, sources in _SCHEMA['source_overrides'].items()}
REQUIRED_COLUMNS = {table: tuple(columns) for table, columns in _SCHEMA['required_columns'].items()}


def dataset_tables(dataset: str) -> tuple[str, ...]:
    return DATASET_TABLE_GROUPS[dataset]


def require_dataset_source(dataset: str, source: str) -> None:
    table = DATASET_TABLES.get(dataset)
    if table and table in FIXED_SOURCES:
        require_fixed_source(table, source)


def schema_contract(table: str, *columns: str) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    required = set(PRIMARY_KEYS[table]) | set(columns)
    required.update(REQUIRED_COLUMNS.get(table, ()))
    return {table: required}, {table: PRIMARY_KEYS[table]}


def require_fixed_source(table: str, source: str) -> None:
    if source in SOURCE_OVERRIDES.get(table, ()):
        return
    expected = FIXED_SOURCES[table]
    if source != expected:
        raise ValueError(f'{table} 固定来源不匹配；正式归属为 {expected}')
