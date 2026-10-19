"""Check static module ownership and recorded dependency debt without importing Empire.

This is an import-graph contract, not a call graph or a runtime isolation proof.
Imports inside functions and TYPE_CHECKING blocks are included conservatively.
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

READ_ROLES = {'query', 'ui', 'shared_ui', 'dataset', 'dataset_registry',
              'diagnostic', 'diagnostic_internal'}
EXECUTION_ROLES = {'collector', 'source_adapter', 'collector_support'}
ROLES = READ_ROLES | EXECUTION_ROLES | {
    'contract', 'parser', 'api', 'composition', 'kernel', 'infrastructure', 'package',
    'shared_ui', 'management', 'pipeline',
}


@dataclass(frozen=True)
class Module:
    name: str
    path: Path
    package: bool
    tree: ast.Module


@dataclass(frozen=True)
class Import:
    source: str
    target: str
    names: tuple[str, ...]
    line: int


def read_modules(root: Path) -> dict[str, Module]:
    result = {}
    for path in sorted((root / 'src' / 'empire').rglob('*.py')):
        parts = list(path.relative_to(root / 'src').with_suffix('').parts)
        package = parts[-1] == '__init__'
        if package:
            parts.pop()
        name = '.'.join(parts)
        if name in result:
            raise ValueError(f'Duplicate module and package: {name}')
        result[name] = Module(name, path, package, ast.parse(path.read_text('utf-8-sig')))
    if not result:
        raise ValueError('No Python modules found under src/empire')
    return result


def import_edges(modules: dict[str, Module]) -> tuple[list[Import], list[str]]:
    """Resolve ``from . import submodule`` as well as ordinary imported symbols."""
    edges, errors = [], []
    for module in modules.values():
        importlib_names, builtin_names = {'importlib'}, {'builtins'}
        import_functions, builtin_functions = set(), {'__import__'}
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Import):
                importlib_names.update(alias.asname or alias.name for alias in node.names
                                       if alias.name == 'importlib')
                builtin_names.update(alias.asname or alias.name for alias in node.names
                                     if alias.name == 'builtins')
            elif isinstance(node, ast.ImportFrom) and node.module == 'importlib':
                import_functions.update(alias.asname or alias.name for alias in node.names
                                        if alias.name == 'import_module')
            elif isinstance(node, ast.ImportFrom) and node.module == 'builtins':
                builtin_functions.update(alias.asname or alias.name for alias in node.names
                                         if alias.name == '__import__')
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'empire' or alias.name.startswith('empire.'):
                        edges.append(Import(module.name, alias.name, ('<module>',), node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = module.name.split('.') if module.package else module.name.split('.')[:-1]
                    if node.level > len(package):
                        errors.append(f'{module.name}:{node.lineno}: relative import escapes package')
                        continue
                    base = '.'.join(package[:len(package) - node.level + 1])
                    target = base + ('.' + node.module if node.module else '')
                else:
                    target = node.module or ''
                if target != 'empire' and not target.startswith('empire.'):
                    continue
                symbols = []
                for alias in node.names:
                    candidate = target + '.' + alias.name
                    if candidate in modules:
                        edges.append(Import(module.name, candidate, ('<module>',), node.lineno))
                    else:
                        symbols.append(alias.name)
                if symbols:
                    edges.append(Import(module.name, target, tuple(sorted(symbols)), node.lineno))
            elif isinstance(node, ast.Call):
                function = node.func
                builtin_call = (isinstance(function, ast.Name) and function.id in builtin_functions
                                or isinstance(function, ast.Attribute) and function.attr == '__import__'
                                and isinstance(function.value, ast.Name)
                                and function.value.id in builtin_names)
                dynamic = (builtin_call
                           or isinstance(function, ast.Name) and function.id in import_functions
                           or isinstance(function, ast.Attribute) and function.attr == 'import_module'
                           and isinstance(function.value, ast.Name)
                           and function.value.id in importlib_names)
                if not dynamic:
                    continue
                value = node.args[0] if node.args else next(
                    (kw.value for kw in node.keywords if kw.arg == 'name'), None)
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    errors.append(f'{module.name}:{node.lineno}: unresolved dynamic import; '
                                  'use a statically declared internal import')
                    continue
                target = value.value
                if target.startswith('.'):
                    errors.append(f'{module.name}:{node.lineno}: relative dynamic import '
                                  'is unsupported; use an ordinary relative import')
                elif target == 'empire' or target.startswith('empire.'):
                    if builtin_call and (len(node.args) > 1 or
                                         any(kw.arg != 'name' for kw in node.keywords)):
                        errors.append(f'{module.name}:{node.lineno}: dynamic __import__ '
                                      'with fromlist/context/level is unsupported; use a static import')
                    edges.append(Import(module.name, target, ('<module>',), node.lineno))
    for edge in edges:
        if edge.target not in modules:
            errors.append(f'{edge.source}:{edge.line}: unknown internal module {edge.target}')
        if '*' in edge.names:
            errors.append(f'{edge.source}:{edge.line}: wildcard internal import hides API ownership')
    return edges, errors


def module_metadata(modules: dict[str, Module], policy: dict) -> tuple[dict, list[str]]:
    metadata, errors = {}, []
    declared = {}
    owners = policy.get('owners', {})
    for group in policy.get('module_groups', []):
        for name in group['modules']:
            if name in declared:
                errors.append(f'Duplicate ownership declaration: {name}')
            declared[name] = {k: v for k, v in group.items() if k != 'modules'}
    for name, module in modules.items():
        record = declared.get(name)
        if record is None:
            for layout in policy.get('feature_layouts', []):
                prefix = layout['prefix']
                if name != prefix and not name.startswith(prefix + '.'):
                    continue
                suffix = name[len(prefix):].lstrip('.')
                role = layout['roles'].get(suffix.split('.')[0])
                if module.package and (not suffix or role is None and not module.tree.body):
                    role = 'package'
                if role:
                    record = dict(owner=layout['owner'], role=role,
                                  reason='Feature layout: ' + layout['reason'])
                break
        if record is None:
            errors.append(f'Unclassified module: {name}')
            continue
        if record.get('owner') not in owners or record.get('role') not in ROLES:
            errors.append(f'Invalid owner/role for {name}')
            continue
        if not record.get('reason', '').strip():
            errors.append(f'Missing responsibility reason: {name}')
        metadata[name] = record
    return metadata, errors


def strongly_connected(modules: dict[str, Module], edges: list[Import]) -> list[list[str]]:
    """Tarjan SCCs; exact edges within an SCC are the cycle-debt unit."""
    graph = defaultdict(set)
    for edge in edges:
        if edge.target in modules:
            graph[edge.source].add(edge.target)
    numbers, low, stack, active, components = {}, {}, [], set(), []

    def visit(name):
        numbers[name] = low[name] = len(numbers)
        stack.append(name)
        active.add(name)
        for target in sorted(graph[name]):
            if target not in numbers:
                visit(target)
                low[name] = min(low[name], low[target])
            elif target in active:
                low[name] = min(low[name], numbers[target])
        if low[name] == numbers[name]:
            group = []
            while True:
                target = stack.pop()
                active.remove(target)
                group.append(target)
                if target == name:
                    break
            if len(group) > 1 or name in graph[name]:
                components.append(sorted(group))

    for name in sorted(modules):
        if name not in numbers:
            visit(name)
    return sorted(components)


def finding_key(value: dict) -> tuple:
    return value['rule'], value['source'], value['target']


def analyze(root: Path, policy: dict) -> dict:
    if policy.get('schema') != 1:
        raise ValueError('Unsupported architecture contract schema')
    modules = read_modules(root)
    metadata, errors = module_metadata(modules, policy)
    edges, import_errors = import_edges(modules)
    errors.extend(import_errors)
    findings = {}

    def add(rule, edge, reason):
        value = dict(rule=rule, source=edge.source, target=edge.target,
                     names=list(edge.names), line=edge.line, reason=reason)
        key = finding_key(value)
        if key in findings:
            value['names'] = sorted(set(value['names']) | set(findings[key]['names']))
            value['line'] = min(value['line'], findings[key]['line'])
        findings[key] = value

    for edge in edges:
        source, target = metadata.get(edge.source), metadata.get(edge.target)
        if source is None or target is None:
            continue
        if source['role'] in READ_ROLES:
            if target['role'] in EXECUTION_ROLES:
                add('reader_to_execution', edge,
                    f"{source['role']} imports {target['role']}: {target['reason']}")
            elif target.get('legacy_collector_location'):
                add('misplaced_source_contract', edge,
                    f"{target['role']} is source-local, not execution: {target['reason']}")
        different = source['owner'] != target['owner']
        business_target = policy['owners'][target['owner']]['kind'] == 'business'
        public_module = target['role'] in {'contract', 'api', 'package'}
        public_symbols = set(target.get('public_symbols', []))
        private_symbol = any(name.startswith('_') for name in edge.names)
        explicitly_public = set(edge.names) <= public_symbols
        if (different and business_target
                and source['role'] not in {'composition', 'dataset_registry'}
                and (private_symbol or not public_module and not explicitly_public)):
            add('cross_business_private', edge,
                f"{source['owner']} imports private {target['owner']} {target['role']}")
    components = strongly_connected(modules, edges)
    component_of = {name: index for index, group in enumerate(components) for name in group}
    for edge in edges:
        if edge.source in component_of and component_of.get(edge.target) == component_of[edge.source]:
            add('module_cycle', edge, 'Static import cycle; includes deferred/type-only imports')
    baseline = {}
    for item in policy.get('debt', []):
        key = finding_key(item)
        if key in baseline or not item.get('reason', '').strip():
            errors.append(f'Duplicate or unexplained debt: {key}')
        baseline[key] = item
    new, existing, retired = [], [], []
    for key, value in sorted(findings.items()):
        permitted = set(baseline.get(key, {}).get('names', []))
        added = set(value['names']) - permitted
        kept = set(value['names']) & permitted
        if added:
            new.append(dict(value, names=sorted(added)))
        if kept:
            existing.append(dict(value, names=sorted(kept)))
    for key, value in sorted(baseline.items()):
        removed = set(value['names']) - set(findings.get(key, {}).get('names', []))
        if removed:
            retired.append(dict(value, names=sorted(removed)))
    return dict(schema=1, passed=not errors and not new, modules=len(modules),
                imports=len(edges), errors=sorted(errors), new_debt=new,
                existing_debt=existing,
                retired_debt=retired, cycles=components,
                module_ownership=metadata,
                dependencies=[dict(source=edge.source, target=edge.target,
                                   names=list(edge.names), line=edge.line) for edge in edges],
                limitations=policy.get('limitations', []))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'report'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    policy_path = args.policy or root / 'docs' / 'architecture-contract.json'
    if args.output and args.output.resolve() == policy_path.resolve():
        print('FAIL architecture contract: report cannot overwrite its reviewed policy')
        return 1
    try:
        policy = json.loads(policy_path.read_text('utf-8'))
        report = analyze(root, policy)
    except (OSError, ValueError, SyntaxError, KeyError) as exc:
        print(f'FAIL architecture contract: {exc}')
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    if args.action == 'report' and not args.output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    state = 'PASS' if report['passed'] else 'FAIL'
    print(f"{state} architecture: {report['modules']} modules, {report['imports']} imports, "
          f"{len(report['existing_debt'])} existing debt, {len(report['new_debt'])} new debt, "
          f"{len(report['retired_debt'])} retired debt")
    for error in report['errors']:
        print(error)
    for debt in report['new_debt']:
        print(f"{debt['rule']}: {debt['source']}:{debt['line']} -> {debt['target']} "
              f"({', '.join(debt['names'])})")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
