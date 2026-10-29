"""The single full verification/build sequence used by both public entry points."""
import json
import shutil
from pathlib import Path

from scripts.release_identity import owned, sha256


def verify(runner):
    root, run, py = runner.root, runner.run_directory, runner.python
    dependency = root / 'build' / 'dependency-report.json'
    runner.command([py, root / 'scripts/verify_release_environment.py'])
    runner.command([py, root / 'scripts/audit_dependencies.py', '--output', dependency])
    runner.evidence[dependency.relative_to(root).as_posix()] = sha256(dependency)
    help_report = run / 'help-report.json'
    runner.command([py, root / 'scripts/documentation_build.py', 'check', '--report', help_report])
    runner.evidence[help_report.relative_to(root).as_posix()] = sha256(help_report)
    runner.command([py, root / 'scripts/verify_documentation.py'])
    runner.command([py, root / 'scripts/verify_database_design.py'])
    runner.command([py, root / 'scripts/architecture_contract.py', 'check'])
    runner.command([py, root / 'scripts/assembly_contract.py', 'check', '--baseline',
                    root / 'docs/evidence/assembly-baseline-2026-10-19.json',
                    '--mapping', root / 'docs/assembly-migrations.json',
                    '--feature-changes', root / 'docs/assembly-feature-changes.json',
                    '--order-baseline', root / 'docs/evidence/assembly-order-baseline-2026-10-19.json'])
    runner.command([py, '-m', 'ruff', 'check', 'src', 'tests', 'scripts'])
    runner.command([py, '-m', 'mypy'])
    runner.command([py, '-m', 'pip', 'check'])
    runner.command(['git', '-C', root, '-c', 'core.whitespace=cr-at-eol', 'diff', '--check'])
    test_files, scope_args = [], []
    if getattr(runner, 'test_plan', None):
        plan = Path(runner.test_plan).resolve()
        runner.evidence[plan.relative_to(root).as_posix()] = sha256(plan)
        scope = run / 'test-scope.json'
        runner.command([py, root / 'scripts/release_test_plan.py', '--plan', plan, '--output', scope])
        runner.evidence[scope.relative_to(root).as_posix()] = sha256(scope)
        test_files = json.loads(scope.read_text(encoding='utf-8'))['files']
        scope_args = ['--test-scope', scope]
    runner.command([py, root / 'scripts/preparation_evidence.py', 'begin'])
    runner.command([py, '-m', 'pytest', *test_files, '-q', '--tb=short', '-rs',
                    '--basetemp', run / 'pytest', '--junitxml', root / 'build/release-tests.xml'],
                   env={'EMPIRE_INTEGRATION': '1'})
    runner.evidence['build/release-tests.xml'] = sha256(root / 'build/release-tests.xml')
    runner.command([py, root / 'scripts/preparation_evidence.py', 'finish', *scope_args])
    runner.evidence['build/generated/preparation-release.json'] = sha256(
        root / 'build/generated/preparation-release.json')
    capacity = run / 'capacity-report.json'
    runner.command([py, root / 'scripts/measure_capacity.py', '--quick', '--output', capacity])
    if not json.loads(capacity.read_text(encoding='utf-8'))['passed']:
        raise RuntimeError('Isolated capacity evidence did not pass')
    runner.evidence[capacity.relative_to(root).as_posix()] = sha256(capacity)
    runner.command(['npm.cmd', '--prefix', str(root / 'desktop'), 'run', 'build'])
    runner.command(['npm.cmd', '--prefix', str(root / 'desktop'), 'run', 'test:transport'])
    return dependency, capacity


def retain_evidence(runner):
    runner.check()
    folder = owned(runner.run_directory, runner.run_directory / 'evidence')
    folder.mkdir()
    result = {}
    for name, digest in runner.evidence.items():
        target = owned(folder, folder / Path(name).name)
        if target.exists():
            raise RuntimeError('Duplicate release evidence filename')
        shutil.copyfile(runner.root / name, target)
        if sha256(target) != digest:
            raise RuntimeError('Release evidence changed while retaining it: ' + name)
        result[name] = dict(path=str(target), sha256=digest)
    runner.check()
    return result
