"""Plan development regression from declared ownership; never replace a full release."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.architecture_contract import import_edges, module_metadata, read_modules

TEST_FIELDS = ('source_tests', 'archive_tests', 'rule_tests', 'integration_tests')
UI_GUARDS = ('tests/test_ui_architecture.py', 'tests/test_desktop_runtime.py',
             'tests/test_desktop_interaction.py')


def local_path(root: Path, value: str) -> Path:
    """A report input cannot read arbitrary filesystem paths or private config."""
    relative = PurePosixPath(value)
    if (not value or '\\' in value or ':' in value or relative.is_absolute()
            or '..' in relative.parts or relative.as_posix() != value
            or value in {'config.toml', 'config/local.toml'}):
        raise ValueError('Expected a canonical, non-private repository path: ' + value)
    target = root / value
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes repository: ' + value)
    current = target
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise ValueError('Linked paths are not impact inputs: ' + value)
        current = current.parent
    return target


def closure(seeds, reverse):
    found, pending = set(seeds), deque(sorted(seeds))
    while pending:
        for consumer in sorted(reverse.get(pending.popleft(), ())):
            if consumer not in found:
                found.add(consumer)
                pending.append(consumer)
    return found


def auxiliary_modules(root):
    """Read tests/scripts without importing fixtures or maintenance executables."""
    result = {}
    for folder in ('tests', 'scripts'):
        for path in sorted((root / folder).rglob('*.py')):
            parts = list(path.relative_to(root).with_suffix('').parts)
            if parts[-1] == '__init__':
                parts.pop()
            result['.'.join(parts)] = path
    return result


def auxiliary_dependencies(root, sources, auxiliary):
    known = set(sources) | set(auxiliary)
    reverse, uncertain = defaultdict(set), {}
    for name, path in auxiliary.items():
        try:
            tree = ast.parse(path.read_text('utf-8-sig'))
        except (OSError, SyntaxError, UnicodeError) as exc:
            uncertain[name] = type(exc).__name__
            continue
        nodes = list(ast.walk(tree))
        if any((isinstance(node, ast.Import)
                and any(item.name.split('.')[0] in {'importlib', 'builtins', 'runpy'} for item in node.names))
               or (isinstance(node, ast.ImportFrom)
                   and (node.module or '').split('.')[0] in {'importlib', 'builtins', 'runpy'})
               or (isinstance(node, ast.Name) and node.id == '__builtins__') for node in nodes):
            # Track use of the loader infrastructure, not only the final call
            # spelling: assignments/getattr can hide the called function name.
            uncertain[name] = 'dynamic loader infrastructure needs conservative regression'
        for node in nodes:
            targets = []
            if isinstance(node, ast.Import):
                targets = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    package = name.split('.') if path.name == '__init__.py' else name.split('.')[:-1]
                    if node.level > len(package):
                        uncertain[name] = 'relative import escapes package'
                        continue
                    base = '.'.join(package[:len(package) - node.level + 1]) + ('.' + base if base else '')
                targets = [base, *(base + '.' + item.name for item in node.names)]
            elif isinstance(node, ast.Call):
                function = node.func
                # Include aliased and otherwise unknown reflection conservatively.
                attr = function.id if isinstance(function, ast.Name) else getattr(function, 'attr', '')
                if (attr in {'import_module', '__import__', 'exec_module',
                            'load_module', 'spec_from_file_location', 'module_from_spec',
                            'run_path', 'run_module'} or isinstance(function, ast.Name)
                        and attr in {'exec', 'eval'}):
                    uncertain[name] = 'dynamic execution/import needs conservative regression'
            for target in targets:
                while target:
                    if target in known:
                        reverse[target].add(name)
                        # Python executes parent __init__ files as well.
                        parent = target.rpartition('.')[0]
                        while parent:
                            if parent in known:
                                reverse[parent].add(name)
                            parent = parent.rpartition('.')[0]
                        break
                    target = target.rpartition('.')[0]
    return reverse, uncertain


def declaration_tests(root, assembly, metadata, owners):
    selected, items, errors = set(), [], []
    bindings = assembly['bindings']
    for key, groups in bindings['tests'].items():
        plugin_id = key.split(':', 1)[0]
        module = bindings['plugins'].get(plugin_id, {}).get('module')
        owner = metadata.get(module, {}).get('owner')
        if owner not in owners:
            continue
        registration = assembly['semantic']['preparation'].get(key)
        if registration is None:
            errors.append('Preparation declaration has no semantics: ' + key)
            continue
        paths = []
        for field, values in groups.items():
            if field not in TEST_FIELDS or not isinstance(values, list) or not values:
                errors.append('Missing/unknown declared regression: ' + key + ':' + field)
                continue
            for value in values:
                path = local_path(root, value)
                if not value.startswith('tests/') or not path.is_file() or path.suffix != '.py':
                    errors.append('Missing declared regression file: ' + value)
                selected.add(value)
                paths.append(value)
        if not paths:
            errors.append('No declared tests: ' + key)
        items.append(dict(id=key, owner=owner, requirement=registration['requirement'],
                          project=registration['project_id'], tests=sorted(set(paths))))
    return selected, items, errors


def test_result(value, path, unavailable):
    if unavailable:
        return dict(path=path, status='not_verified', reason=unavailable)
    module = path.removesuffix('.py').replace('/', '.')
    cases = [case for case in value.get('cases', [])
             if case['module'] == module or case['module'].startswith(module + '.')]
    if not cases:
        return dict(path=path, status='not_verified', reason='No executed cases in current evidence')
    counts = {status: sum(case['status'] == status for case in cases)
              for status in ('passed', 'skipped', 'failure', 'error')}
    status = 'passed' if counts['passed'] == len(cases) else 'not_passed'
    return dict(path=path, status=status, cases=counts, checked_at=value['checked_at'])


def _report(root, changed, policy, assembly, *, evidence=None, evidence_error='No current execution evidence'):
    root = root.resolve()
    if policy.get('schema') != 1 or assembly.get('schema') != 1:
        raise ValueError('Unsupported ownership/assembly schema')
    changes = sorted(set(changed))
    if not changes:
        raise ValueError('At least one explicit changed path is required')
    modules = read_modules(root)
    metadata, errors = module_metadata(modules, policy)
    source_edges, graph_errors = import_edges(modules)
    errors.extend(graph_errors)
    # Static import_edges resolves ordinary/literal imports. Aliased reflection,
    # runpy and indirect loaders cannot establish a finite product dependency.
    _, source_uncertain = auxiliary_dependencies(root, modules,
        {name: module.path for name, module in modules.items()})
    if source_uncertain:
        errors.extend('Unresolved product loader: ' + name for name in source_uncertain)
    reverse = defaultdict(set)
    for edge in source_edges:
        reverse[edge.target].add(edge.source)
        parent = edge.target.rpartition('.')[0]
        while parent:
            if parent in modules:
                reverse[parent].add(edge.source)
            parent = parent.rpartition('.')[0]
    auxiliary = auxiliary_modules(root)
    extra, uncertain = auxiliary_dependencies(root, modules, auxiliary)
    for target, consumers in extra.items():
        reverse[target].update(consumers)
    for binding in assembly['bindings']['plugins'].values():
        if binding['module'] not in metadata:
            errors.append('Unclassified contribution provider: ' + binding['module'])
    by_path = {module.path.relative_to(root).as_posix(): name for name, module in modules.items()}
    by_path.update({path.relative_to(root).as_posix(): name for name, path in auxiliary.items()})
    all_tests = {path.relative_to(root).as_posix() for path in auxiliary.values()
                 if path.name.startswith('test_') and path.parts[len(root.parts)] == 'tests'}
    reasons, seeds, selected = [], set(), set()
    for value in changes:
        path = local_path(root, value)
        if not path.is_file():
            reasons.append('Deleted or missing input: ' + value)
        elif value not in by_path:
            reasons.append('Non-Python or unclassified input: ' + value)
        else:
            name = by_path[value]
            seeds.add(name)
            if value.startswith('scripts/'):
                reasons.append('Maintenance/build tool changed: ' + value)
            if name in metadata:
                item = metadata[name]
                if (policy['owners'][item['owner']]['kind'] != 'business'
                        or item['role'] in {'contract', 'api', 'composition', 'dataset_registry'}):
                    reasons.append('Shared/public declaration changed: ' + value)
            if path.name == 'conftest.py':
                selected.update(test for test in all_tests if local_path(root, test).is_relative_to(path.parent))
    impacted = closure(seeds, reverse)
    # An affected business owns its complete regression, including UI and SQL paths.
    # Composition modules do not cause unrelated business bundles to be selected.
    while True:
        owners = {metadata[name]['owner'] for name in impacted if name in metadata
                  and policy['owners'][metadata[name]['owner']]['kind'] == 'business'}
        owned_modules = {name for name, item in metadata.items() if item['owner'] in owners}
        expanded = impacted | closure(owned_modules, reverse)
        if expanded == impacted:
            break
        impacted = expanded
    selected.update(path for path, name in by_path.items() if name in impacted and path in all_tests)
    declared, contributions, declaration_errors = declaration_tests(root, assembly, metadata, owners)
    selected.update(declared)
    errors.extend(declaration_errors)
    if any(metadata.get(name, {}).get('role') == 'ui' for name in owned_modules):
        for path in UI_GUARDS:
            if path not in all_tests:
                errors.append('Missing shared UI lifecycle regression: ' + path)
            else:
                selected.add(path)
    # Reflection in a test/helper is not proof that it is unrelated to this change.
    conservative = closure(set(uncertain), reverse)
    selected.update(path for path, name in by_path.items() if name in conservative and path in all_tests)
    # Tests with no repository imports may inspect source/resources directly.
    known_consumers = {consumer for consumers in reverse.values() for consumer in consumers}
    selected.update(path for path, name in by_path.items() if path in all_tests and name not in known_consumers)
    if errors:
        reasons.append('Incomplete ownership/dependency/registration evidence')
    if not selected:
        reasons.append('No confidently selected regression')
    if reasons:
        selected = all_tests | declared
        owners = {key for key, value in policy['owners'].items() if value['kind'] == 'business'}
        all_declared, contributions, more_errors = declaration_tests(root, assembly, metadata, owners)
        selected.update(all_declared)
        errors.extend(more_errors)
    checks = [test_result(evidence or {}, path, evidence_error) for path in sorted(selected)]
    return dict(schema=1, purpose='development_feedback_only', changed=changes,
                mode='full' if reasons else 'selected', full_reasons=sorted(set(reasons)),
                errors=sorted(set(errors)), affected_businesses=sorted(owners),
                impacted_modules=sorted(impacted), contributions=contributions,
                selected_tests=sorted(selected), execution_evidence=checks,
                selection_status='review_required' if errors else 'ready',
                verification_status='not_complete',
                live_validation=dict(status='not_assessed', references=[],
                    rule='Apply collector-development-guide to source, execution, contract or recovery changes; '
                         'pure moves still need scoped end-to-end evidence. Random 30 applies only to stock-grained work.'),
                desktop_validation='not_assessed', official_release='full_gate_required',
                conservative_tests=sorted(name for name in conservative if name.startswith('tests.')),
                limitations=['Static dependency graph is not a call graph.',
                    'Historical evidence references do not attest current source.',
                    'Skipped, absent, failed or stale cases are never passing evidence.',
                    'This command starts no tests, collectors, services, migrations or desktop.'])


def report(root, changed, policy, assembly, *, evidence=None, evidence_error='No current execution evidence'):
    changes = list(changed)
    # Validate paths before fallback: malformed metadata never authorizes reading
    # a private or external input. A fallback selects every extant test file.
    for name in changes:
        local_path(root, name)
    try:
        return _report(root, changes, policy, assembly, evidence=evidence, evidence_error=evidence_error)
    except (KeyError, TypeError, AttributeError, ValueError, SyntaxError) as exc:
        selected = sorted(path.relative_to(root).as_posix()
                          for path in (root / 'tests').rglob('test_*.py') if path.is_file())
        return dict(schema=1, purpose='development_feedback_only', changed=sorted(set(changes)),
                    mode='full', full_reasons=['Malformed ownership, dependency or assembly evidence'],
                    errors=[type(exc).__name__ + ': metadata/dependency review required'],
                    affected_businesses=[], impacted_modules=[], contributions=[], selected_tests=selected,
                    execution_evidence=[dict(path=path, status='not_verified', reason='Untrusted metadata')
                                        for path in selected],
                    selection_status='review_required', verification_status='not_complete',
                    live_validation=dict(status='not_assessed', references=[]),
                    desktop_validation='not_assessed', official_release='full_gate_required',
                    conservative_tests=[], limitations=['Malformed metadata cannot establish a safe subset.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--changed', action='append', required=True, help='Repeat with repository-relative paths')
    parser.add_argument('--live-evidence', action='append', default=[], help='Historical evidence reference only')
    parser.add_argument('--output', required=True, help='New JSON under build/')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    from empire.core.preparation_release import load_evidence
    from scripts.assembly_contract import snapshot
    from scripts.release_identity import input_inventory

    try:
        target = local_path(root, args.output)
        if not args.output.startswith('build/') or target.exists() or target.suffix != '.json':
            raise ValueError('Output must be a new JSON report under build/')
        before = input_inventory(root)
        policy = json.loads((root / 'docs/architecture-contract.json').read_text('utf-8'))
        evidence, unavailable = load_evidence(root)
        value = report(root, args.changed, policy, snapshot(root), evidence=evidence,
                       evidence_error=unavailable)
        for reference in args.live_evidence:
            path = local_path(root, reference)
            if not (reference.startswith('docs/evidence/') or reference.startswith('build/')) or not path.is_file():
                raise ValueError('Expected an existing local evidence record')
            if path.suffix not in {'.json', '.md'} or path.stat().st_size > 1024 * 1024:
                raise ValueError('Evidence references must be bounded JSON/Markdown records')
            value['live_validation']['references'].append(dict(path=reference,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), status='historical_reference_only'))
        if before != input_inventory(root):
            raise ValueError('Source changed while calculating impact; rerun')
        value['source_sha256'] = before['sha256']
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, SyntaxError) as exc:
        print('Impact report unavailable: ' + str(exc), file=sys.stderr)
        return 1
    print(f"{value['mode']}: {len(value['selected_tests'])} test files; "
          'no tests or live validation executed; full release remains required')
    return 1 if value['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
