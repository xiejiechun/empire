"""Offline release gate: reviewed DDL, dataset ownership, design cards and JSON roles."""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from empire.contracts.business_schema import DATASET_TABLE_GROUPS, PRIMARY_KEYS
from empire.features.builtin import dataset_contributions
from empire.plugins.datasets.astock import DatasetPlugin

LEGACY_BASELINES = frozenset({
    'stock.universe.start', 'stock.universe.page', 'stock.universe.complete', 'industry.snapshot',
    'income.statement', 'balance.statement', 'cashflow.statement', 'dividends.unit',
    'additional_issues.unit', 'rights_issues.unit', 'calendar.month', 'suspensions.period', 'news.flash.page',
})  # Approved pre-existing contracts, not an escape hatch for future datasets.


def verify_scoped_ddl(evidence, schema, tables):
    statements = {m[1]: m[0] for m in re.finditer(
        r'CREATE TABLE IF NOT EXISTS (\w+)\s*\([\s\S]*?;', schema.replace('\r\n', '\n'))}
    for table in tables:
        actual = hashlib.sha256(statements[table].encode()).hexdigest()
        if evidence.get('ddl_scopes', {}).get(table) != actual:
            raise ValueError(f'已测量业务表DDL变化，须重新测量：{table}')


def verify(root):
    schema = (root/'sql/schema.sql').read_bytes()
    manifest = json.loads((root/'sql/schema-contract.json').read_text('utf-8'))
    if manifest['schema_sha256'] != hashlib.sha256(schema).hexdigest():
        raise ValueError('DDL已变化，须显式审阅并更新类型/索引/约束契约')
    tables = set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', schema.decode()))
    if tables != set(manifest['tables']):
        raise ValueError('DDL与结构契约表集合不一致')
    if set(DatasetPlugin(dataset_contributions({
            'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}})).datasets) != set(DATASET_TABLE_GROUPS):
        raise ValueError('正式数据贡献与业务表归属登记不一致')
    owned = {table for group in DATASET_TABLE_GROUPS.values() for table in group}
    if tables != owned | {'app_setting', 'collection_state'}:
        raise ValueError('业务表必须登记实际数据集归属；配置/状态表单独登记')
    for table, keys in PRIMARY_KEYS.items():
        if manifest['tables'][table]['primary'] != keys:
            raise ValueError(f'{table} 主键与公共业务身份登记不一致')
    designs = json.loads((root/'docs/database-design-cards.json').read_text('utf-8'))
    if set(designs['datasets']) != set(DATASET_TABLE_GROUPS):
        raise ValueError('数据集设计卡缺失或包含已退役项目')
    required = {'tables', 'grain', 'identity', 'dictionary', 'queries', 'capacity', 'integrity', 'lifecycle', 'delivery', 'tests'}
    for dataset, card in designs['datasets'].items():
        if set(card) != required or any(not v for v in card.values()):
            raise ValueError(f'{dataset} 存储设计卡不完整')
        if tuple(card['tables']) != DATASET_TABLE_GROUPS[dataset] or not set(card['tables']) <= tables:
            raise ValueError(f'{dataset} 多表归属与设计卡不匹配')
        for path in (card['dictionary'], *card['tests']):
            if not (root/path).is_file():
                raise ValueError(f'{dataset} 字典或专项测试不存在：{path}')
        capacity = card['capacity']
        if capacity.get('status') not in ('measured', 'legacy_baseline'):
            raise ValueError(f'{dataset} 缺少容量验收状态')
        if capacity['status'] == 'legacy_baseline' and dataset not in LEGACY_BASELINES:
            raise ValueError(f'{dataset} 新数据集不能冒充历史容量基线')
        if capacity['status'] == 'measured':
            evidence = json.loads((root/capacity['evidence']).read_text('utf-8'))
            if 'sql/schema.sql' not in evidence['bindings']:
                # Existing measurements may bind an archived DDL, but must still
                # prove every table used by this dataset unchanged in current SQL.
                verify_scoped_ddl(evidence, schema.decode(), card['tables'])
            for path, checksum in evidence['bindings'].items():
                if hashlib.sha256((root/path).read_bytes()).hexdigest() != checksum:
                    raise ValueError(f'{dataset} 容量证据已过期：{path}')
            for key, maximum in evidence['limits'].items():
                if evidence['measurements'][key] > maximum:
                    raise ValueError(f'{dataset} 容量预算超限：{key}')
            if not evidence['conditions'] or not evidence['reviewed_tradeoffs']:
                raise ValueError(f'{dataset} 缺少容量条件与取舍说明')
    json_fields = {table+'.'+name for table, shape in manifest['tables'].items()
                   for name, col in shape['columns'].items() if col['type'] == 'json'}
    if set(designs['json_roles']) != json_fields:
        raise ValueError('JSON字段必须精确登记用途、上限及字段策略')
    for field, role in designs['json_roles'].items():
        if set(role) != {'purpose', 'limit', 'policy'} or any(not v for v in role.values()):
            raise ValueError(f'{field} JSON契约不完整')
    return {'tables': len(tables), 'datasets': len(designs['datasets']), 'json_fields': len(json_fields)}


if __name__ == '__main__':
    print('PASS database design gate', verify(Path(__file__).resolve().parents[1]))
