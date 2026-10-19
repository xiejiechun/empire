"""Exercise public PowerShell dispatch and source-bound evidence in private roots."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from empire.core.preparation_release import source_digest


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell release entry points are Windows-only')
@pytest.mark.parametrize('entry', ['build.ps1', 'verify-release.ps1'])
@pytest.mark.parametrize('recover', [False, True])
def test_both_public_entrypoints_dispatch_once_and_propagate_failure(tmp_path, entry, recover):
    root = Path(__file__).resolve().parents[1]
    for name in ('build.ps1', 'verify-release.ps1'):
        shutil.copyfile(root / name, tmp_path / name)
    interpreter = tmp_path / '.venv/Scripts/python.exe'
    interpreter.parent.mkdir(parents=True)
    shutil.copyfile(sys.executable, interpreter)
    shutil.copyfile(root / '.venv/pyvenv.cfg', tmp_path / '.venv/pyvenv.cfg')
    script = tmp_path / 'scripts/release.py'
    script.parent.mkdir()
    script.write_text(
        'import sys; from pathlib import Path\n'
        'p=Path(__file__).parents[1]/"invocations.txt"\n'
        'with p.open("a") as f: f.write(str(sys.argv[1:])+"\\n")\n'
        'raise SystemExit(7)\n', encoding='utf-8')
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(tmp_path / entry)]
    if recover:
        command.append('-Recover')
    result = subprocess.run(command, cwd=tmp_path.parent, capture_output=True, text=True)
    assert result.returncode != 0
    calls = (tmp_path / 'invocations.txt').read_text().splitlines()
    assert calls == ["['--recover']" if recover else '[]']


@pytest.mark.parametrize('damage', ['missing', 'stale', 'failed', 'malformed', 'failure_case'])
def test_package_evidence_is_fail_closed_with_real_script_execution(tmp_path, damage):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / 'scripts/preparation_evidence.py'
    script.parent.mkdir()
    shutil.copyfile(root / 'scripts/preparation_evidence.py', script)
    for name in ('requirements.lock', 'pyproject.toml', 'Empire.spec', 'build.ps1', 'verify-release.ps1'):
        (tmp_path / name).write_text('fixture', encoding='utf-8')
    target = tmp_path / 'build/generated/preparation-release.json'
    target.parent.mkdir(parents=True)
    value = dict(schema=1, passed=True, checked_at='now', source_sha256=source_digest(tmp_path),
                 cases=[dict(module='tests.fixture', name='test_ok', status='passed')])
    if damage == 'stale':
        value['source_sha256'] = '0' * 64
    if damage == 'failed':
        value['passed'] = False
    if damage == 'malformed':
        value['cases'] = ['broken']
    if damage == 'failure_case':
        value['cases'][0]['status'] = 'failure'
    if damage != 'missing':
        target.write_text(json.dumps(value), encoding='utf-8')
    result = subprocess.run([sys.executable, str(script), 'package'], capture_output=True, text=True)
    assert result.returncode != 0
    assert json.loads(target.read_text())['passed'] is False


def test_preparation_digest_covers_runtime_resources_not_development_notes_or_credentials(tmp_path):
    for name in ('requirements.lock', 'pyproject.toml', 'Empire.spec', 'build.ps1', 'verify-release.ps1'):
        (tmp_path / name).write_text('fixture', encoding='utf-8')
    baseline = source_digest(tmp_path)
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/plan.md').write_text('development only', encoding='utf-8')
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/local.toml').write_text('private', encoding='utf-8')
    (tmp_path / 'config.toml').write_text('private', encoding='utf-8')
    assert source_digest(tmp_path) == baseline
    (tmp_path / 'src').mkdir()
    for name in ('rules.json', 'help.md', 'icon.ico'):
        (tmp_path / 'src' / name).write_text('runtime resource', encoding='utf-8')
        updated = source_digest(tmp_path)
        assert updated != baseline
        baseline = updated


@pytest.mark.skipif(os.name != 'nt', reason='Windows shortcut COM contract')
def test_shortcut_generation_preserves_correct_existing_link_and_repairs_wrong_target(tmp_path):
    root = Path(__file__).resolve().parents[1]
    target, existing = tmp_path / 'dist/Empire/Empire.exe', tmp_path / 'Empire.lnk'
    candidate = tmp_path / 'candidate.lnk'
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
               str(root / 'scripts/release_shortcut.ps1'), '-Candidate', str(candidate),
               '-Existing', str(existing), '-Target', str(target), '-WorkingDirectory', str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    assert candidate.is_file() and not existing.exists()
    candidate.rename(existing)
    original = existing.read_bytes()
    subprocess.run(command, check=True, capture_output=True)
    assert not candidate.exists() and existing.read_bytes() == original
    changed = command.copy()
    changed[changed.index('-Target') + 1] = str(tmp_path / 'different/Empire.exe')
    subprocess.run(changed, check=True, capture_output=True)
    assert candidate.is_file() and existing.read_bytes() == original
