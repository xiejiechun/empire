"""The single full verification/build sequence used by both public entry points."""
import importlib.metadata
import json
import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.release_identity import owned, sha256, tree_inventory, write_json


def verify(runner):
    root, run, py = runner.root, runner.run_directory, runner.python
    dependency = root / 'build' / 'dependency-report.json'
    runner.command([py, root / 'scripts/verify_release_environment.py'])
    runner.command([py, root / 'scripts/audit_dependencies.py', '--output', dependency])
    runner.evidence[dependency.relative_to(root).as_posix()] = sha256(dependency)
    runner.command([py, root / 'scripts/verify_documentation.py'])
    runner.command([py, root / 'scripts/verify_database_design.py'])
    runner.command([py, root / 'scripts/architecture_contract.py', 'check'])
    runner.command([py, root / 'scripts/assembly_contract.py', 'check', '--baseline',
                    root / 'docs/evidence/assembly-baseline-2026-10-19.json'])
    runner.command([py, '-m', 'ruff', 'check', 'src', 'tests', 'scripts'])
    runner.command([py, '-m', 'mypy'])
    runner.command([py, '-m', 'pip', 'check'])
    runner.command(['git', '-C', root, '-c', 'core.whitespace=cr-at-eol', 'diff', '--check'])
    runner.command([py, root / 'scripts/preparation_evidence.py', 'begin'])
    runner.command([py, '-m', 'pytest', '-q', '--tb=short', '-rs',
                    '--basetemp', run / 'pytest', '--junitxml', root / 'build/release-tests.xml'],
                   env={'EMPIRE_INTEGRATION': '1'})
    runner.evidence['build/release-tests.xml'] = sha256(root / 'build/release-tests.xml')
    runner.command([py, root / 'scripts/preparation_evidence.py', 'finish'])
    runner.evidence['build/generated/preparation-release.json'] = sha256(
        root / 'build/generated/preparation-release.json')
    capacity = run / 'capacity-report.json'
    runner.command([py, root / 'scripts/measure_capacity.py', '--quick', '--output', capacity])
    if not json.loads(capacity.read_text(encoding='utf-8'))['passed']:
        raise RuntimeError('Isolated capacity evidence did not pass')
    runner.evidence[capacity.relative_to(root).as_posix()] = sha256(capacity)
    for scale in ('1', '1.25', '1.5', '2'):
        runner.command([py, root / 'scripts/verify_foundation_ui.py'],
                       env={'QT_SCALE_FACTOR': scale})
    runner.command([py, root / 'scripts/preparation_evidence.py', 'package'])
    return dependency, capacity


def package(runner, publication, dependency):
    root, run = runner.root, runner.run_directory
    from empire import __version__
    dependencies = json.loads(dependency.read_text(encoding='utf-8'))
    requirements = sha256(root / 'requirements.lock')
    if dependencies['requirements_sha256'] != requirements:
        raise RuntimeError('Dependency evidence does not match requirements.lock')
    manifest = dict(version=__version__, commit=runner.commit, dirty=runner.dirty,
                    source_sha256=runner.inputs['sha256'], release_id=run.name,
                    requirements_sha256=requirements,
                    dependency_count=dependencies['component_count'],
                    dependency_report_sha256=sha256(dependency),
                    built_at_utc=datetime.now(UTC).isoformat(), python=platform.python_version(),
                    pyinstaller=importlib.metadata.version('pyinstaller'))
    if not manifest['python'].startswith('3.12.') or manifest['pyinstaller'] != '6.22.3':
        raise RuntimeError('Release requires Python 3.12.x and PyInstaller 6.22.3')
    manifest_path = root / 'build/generated/build_manifest.json'
    write_json(manifest_path, manifest)
    runner.evidence[manifest_path.relative_to(root).as_posix()] = sha256(manifest_path)
    system = os.environ.get('SystemRoot', r'C:\Windows')
    clean_path = os.pathsep.join((str(root / '.venv/Scripts'), sys.base_prefix,
                                 system + r'\System32', system, system + r'\System32\Wbem'))
    runner.command([runner.python, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', publication.stage.parent, '--workpath', run / 'pyinstaller',
                    root / 'Empire.spec'], env={'PATH': clean_path})
    if not (publication.stage / 'Empire.exe').is_file():
        raise RuntimeError('PyInstaller did not produce the staged executable')
    if (publication.stage / 'config.toml').exists():
        raise RuntimeError('Packager unexpectedly included a real program configuration')
    for name in ('preparation-release.json', 'build_manifest.json', 'dependency-report.json'):
        expected = (dependency if name == 'dependency-report.json' else root / 'build/generated' / name)
        embedded = publication.stage / '_internal/empire' / name
        if not embedded.is_file() or sha256(embedded) != sha256(expected):
            raise RuntimeError('Packaged release evidence differs from verified outputs: ' + name)
    return manifest


def portable_smoke(runner, publication):
    run, stage = runner.run_directory, publication.stage
    executable, config = stage / 'Empire.exe', stage / 'config.toml'
    image = run / 'release-smoke.png'
    working = run / 'different working directory'
    working.mkdir()
    env = {'QT_QPA_PLATFORM': 'offscreen', 'LOCALAPPDATA': str(run / '用户 数据')}
    runner.command([executable, 'package-smoke', '--screenshot', image], cwd=working, env=env)
    if not image.is_file():
        raise RuntimeError('Packaged smoke did not create its screenshot')
    runner.command([executable, 'check-config'], cwd=working, env=env, expected=1)
    if not config.is_file():
        raise RuntimeError('First run did not prepare the program-local config')
    runner.command([executable, 'check-config'], cwd=working, env=env)
    # Only the disposable template made in our unique staged bundle is removed.
    config.unlink()
    if (working / 'config.toml').exists():
        raise RuntimeError('Packaged configuration incorrectly depends on the working directory')
    runner.evidence[image.relative_to(runner.root).as_posix()] = sha256(image)
    return dict(chinese_space_path=True, packaged_smoke=True, first_run_prepared_config=True,
                config_recheck=True, different_working_directory=True,
                screenshot=str(image), screenshot_sha256=sha256(image),
                package=tree_inventory(stage))


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


def prepare_shortcut(runner):
    root, run = runner.root, runner.run_directory
    runner.command(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                    root / 'scripts/release_shortcut.ps1', '-Candidate', run / 'Empire.lnk',
                    '-Existing', root / 'Empire.lnk', '-Target', root / 'dist/Empire/Empire.exe',
                    '-WorkingDirectory', root])
