"""Offline per-object dictionary coverage, derived from DDL and key constructors."""
import ast
import hashlib
import json
import re

from empire.contracts.business_schema import read_business_schema

SECTIONS = ("用途与归属", "结构与身份", "读写与关联", "保留与恢复", "维护与相关说明")


def mysql_objects(root):
    sql = (root / 'sql/schema.sql').read_text(encoding='utf-8')
    result = {}
    for name, body in re.findall(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\) ENGINE', sql, re.S):
        columns, rules = {}, []
        for line in body.splitlines():
            line = line.strip().rstrip(',')
            match = re.match(r'`?(\w+)`?\s+(.*)', line)
            if not match:
                continue
            if match[1] in ('PRIMARY', 'KEY', 'INDEX', 'CONSTRAINT', 'UNIQUE', 'FOREIGN'):
                rules.append(line)
            else:
                columns[match[1]] = match[2]
        result[name] = {'columns': columns, 'rules': rules}
    return result


def redis_constructors(root):
    """Scan namespace keys, external router keys, and derived key suffixes.

    This is static syntax coverage, not Redis data discovery. New construction
    styles still require explicit registration and developer review.
    """
    result = {}
    for path in sorted((root / 'src/empire').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.FormattedValue):
                first = ast.unparse(node.values[0].value)
                is_namespace = (first == 'prefix' or first.endswith('.prefix')) and (
                    len(node.values) > 1 and isinstance(node.values[1], ast.Constant)
                    and isinstance(node.values[1].value, str) and node.values[1].value.startswith(':'))
                is_derived = first == 'key' and any(isinstance(v, ast.Constant)
                    and isinstance(v.value, str) and v.value.startswith(':') for v in node.values[1:])
                if is_namespace or is_derived:
                    found.add(ast.unparse(node))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                if (isinstance(node.left, ast.Name) and node.left.id == 'key'
                        and isinstance(node.right, ast.Constant)
                        and isinstance(node.right.value, str) and node.right.value.startswith(':')):
                    found.add(ast.unparse(node))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith('router:proxies:'):
                    found.add(repr(node.value))
        if found:
            result[path.relative_to(root).as_posix()] = sorted(found)
    return result


def _normal(value):
    return ' '.join(value.split())


def verify_storage(root, coverage, articles):
    storage = coverage.get('storage', {})
    tables = mysql_objects(root)
    entries = storage.get('mysql', {})
    if set(entries) != set(tables):
        raise RuntimeError('MySQL 逐表说明登记不一致：' + str(sorted(set(entries) ^ set(tables))))
    used = set()
    for kind in ('mysql', 'redis'):
        for ident, entry in storage.get(kind, {}).items():
            title = entry['topic']
            article = articles.get(title)
            if (not article or article.category != '数据库参考'
                    or article.group != ('MySQL' if kind == 'mysql' else 'Redis') or title in used):
                raise RuntimeError(f'数据库对象必须有独立说明：{kind}:{ident}')
            used.add(title)
            for section in SECTIONS:
                if f'## {section}\n' not in article.body:
                    raise RuntimeError(f'数据库说明缺少 {section}：{title}')
            if not entry.get('sources') or any(not (root / p).is_file() for p in entry['sources']):
                raise RuntimeError(f'数据库对象缺少实际读写归属：{kind}:{ident}')
            if kind == 'mysql':
                rows = {m[1]: _normal(m[2]) for m in re.finditer(
                    r'^\| `([^`]+)` \| `([^`]+)` \| .+ \|$', article.body, re.M)}
                if rows != {k: _normal(v) for k, v in tables[ident]['columns'].items()}:
                    raise RuntimeError(f'MySQL 字段字典与 DDL 不一致：{ident}')
                for rule in tables[ident]['rules']:
                    if f'`{rule}`' not in article.body:
                        raise RuntimeError(f'MySQL 主键、索引或约束说明未同步：{ident}: {rule}')
            else:
                if not entry.get('patterns') or any(f'`{p}`' not in article.body for p in entry['patterns']):
                    raise RuntimeError(f'Redis 键模板缺少逐项说明：{ident}')
    if not storage.get('redis'):
        raise RuntimeError('缺少 Redis 逐键说明')
    declared = storage.get('redis_constructors', {})
    if redis_constructors(root) != {p: sorted(items) for p, items in declared.items()}:
        raise RuntimeError('Redis 键构造发生变化，须核对新增、修改、退役键及逐项说明登记')
    for path, items in declared.items():
        for expression, identities in items.items():
            if not identities or any(ident not in storage['redis'] or
                    path not in storage['redis'][ident]['sources'] for ident in identities):
                raise RuntimeError(f'Redis 键构造缺少逐项归属：{path}: {expression}')
    return storage


def storage_snapshots(root, storage, articles, reachable_sources):
    result = {}
    tables = mysql_objects(root)
    ownership = read_business_schema(root / 'sql/business-schema.json')
    for kind in ('mysql', 'redis'):
        for ident, entry in storage[kind].items():
            article = articles[entry['topic']]
            sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                       for name in entry['sources']}
            modules = [name.removeprefix('src/').removesuffix('.py').replace('/', '.')
                       for name in entry['sources']]
            sources.update(reachable_sources(root, modules))
            if kind == 'mysql':
                sources[f'sql/schema.sql#{ident}'] = hashlib.sha256(repr(tables[ident]).encode()).hexdigest()
                owned = {field: ownership[field].get(ident) for field in
                         ('fixed_sources', 'primary_keys', 'source_overrides', 'required_columns')}
                owned['maintenance_position'] = ownership['tables'].index(ident) if ident in ownership['tables'] else None
                owned['primary_key_exempt'] = ident in ownership['primary_key_exemptions']
                owned['datasets'] = {dataset: group for dataset, group in
                                     ownership['dataset_table_groups'].items() if ident in group}
                sources[f'sql/business-schema.json#{ident}'] = hashlib.sha256(
                    json.dumps(owned, sort_keys=True).encode()).hexdigest()
            result[f'{kind}:{ident}'] = {
                'sources': sources,
                'content_sha256': hashlib.sha256((article.title + article.summary + article.body).encode()).hexdigest(),
            }
    return result
