"""Real filesystem/process counterexamples for the single publication path."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import release
from scripts.release_identity import (
    assert_inputs,
    input_inventory,
    owned,
    tree_inventory,
    write_json,
)
from scripts.release_lock import ReleaseLock
from scripts.release_publish import Publication, recover_pending


def installed(tmp_path):
    old = tmp_path / 'dist/Empire'
    old.mkdir(parents=True)
    (old / 'Empire.exe').write_bytes(b'previous executable')
    (old / 'config.toml').write_bytes(b'private config\r\n')
    run = tmp_path / 'build/releases/test-run'
    run.mkdir(parents=True)
    publication = Publication(tmp_path, run)
    publication.stage.mkdir(parents=True)
    (publication.stage / 'Empire.exe').write_bytes(b'candidate executable')
    return publication


@pytest.mark.parametrize('name', ['src/app.py', 'src/icon.ico', 'src/rules.json',
                                'tests/test_x.py', 'scripts/build.py', 'sql/schema.sql',
                                'docs/guide.md', 'docs/documentation-coverage.json',
                                'config/app.example.toml', 'requirements.lock', 'Empire.spec',
                                'verify-release.ps1'])
def test_input_manifest_detects_all_declared_input_classes(tmp_path, name):
    file = tmp_path / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b'initial')
    baseline = input_inventory(tmp_path)
    file.write_bytes(b'edited')
    with pytest.raises(RuntimeError, match='inputs changed'):
        assert_inputs(tmp_path, baseline)
    file.unlink()
    with pytest.raises(RuntimeError, match='inputs changed'):
        assert_inputs(tmp_path, baseline)


def test_new_input_detected_but_private_config_generated_outputs_are_excluded(tmp_path):
    baseline = input_inventory(tmp_path)
    for name in ('config.toml', 'config/local.toml', 'build/generated/evidence.json',
                 'dist/Empire/config.toml', '.build.lock'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'private or generated')
    assert_inputs(tmp_path, baseline)
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/new.py').write_text('new', encoding='utf-8')
    with pytest.raises(RuntimeError, match='src/new.py'):
        assert_inputs(tmp_path, baseline)


def test_second_owner_rejected_and_cancel_releases_only_own_handle(tmp_path):
    with pytest.raises(KeyboardInterrupt), ReleaseLock(tmp_path):
        with pytest.raises(RuntimeError, match='owns the workspace'):
            with ReleaseLock(tmp_path):
                pass
        raise KeyboardInterrupt
    assert (tmp_path / '.build.lock').exists()
    with ReleaseLock(tmp_path):
        pass


@pytest.mark.parametrize('explicit_stdio', [False, True])
def test_child_retains_ownership_when_parent_lock_scope_exits(tmp_path, explicit_stdio):
    stop = tmp_path / 'stop'
    code = (
        "import os,sys,time; from pathlib import Path\n"
        "p=Path(sys.argv[1]); deadline=time.monotonic()+15\n"
        "if sys.argv[2]=='1': os.write(1,b'child stdout|'); os.write(2,b'child stderr|')\n"
        "while not p.exists() and time.monotonic()<deadline: time.sleep(.02)\n"
    )
    stdio = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                 stderr=subprocess.STDOUT, bufsize=0) if explicit_stdio else {}
    with ReleaseLock(tmp_path) as lock:
        child = subprocess.Popen([sys.executable, '-c', code, str(stop), str(int(explicit_stdio))],
                                 **stdio, **lock.child_options())
    try:
        with pytest.raises(RuntimeError, match='owns the workspace'):
            with ReleaseLock(tmp_path):
                pass
    finally:
        stop.touch()
        output, _ = child.communicate(timeout=20)
    if explicit_stdio:
        assert output == b'child stdout|child stderr|'
    assert child.returncode == 0
    with ReleaseLock(tmp_path):
        pass


@pytest.mark.parametrize('explicit_stdio', [False, True])
def test_abrupt_parent_exit_cannot_release_live_child_ownership(tmp_path, explicit_stdio):
    code = r'''
import os,subprocess,sys
from pathlib import Path
from scripts.release_lock import ReleaseLock
explicit = sys.argv[2] == '1'
child = (
    "import os,sys,time; from pathlib import Path\n"
    "p=Path(sys.argv[1]); end=time.monotonic()+15\n"
    "if sys.argv[2]=='1': os.write(1,b'child stdout|'); os.write(2,b'child stderr|')\n"
    "while not p.exists() and time.monotonic()<end: time.sleep(.02)\n"
)
stdio = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
             stderr=subprocess.STDOUT, bufsize=0) if explicit else {}
with ReleaseLock(Path(sys.argv[1])) as lock:
    process = subprocess.Popen(
        [sys.executable,'-c',child,str(Path(sys.argv[1])/'stop'),sys.argv[2]],
        **stdio, **lock.child_options())
    if explicit:
        expected = b'child stdout|child stderr|'
        received = b''
        while len(received) < len(expected):
            chunk = process.stdout.read(len(expected) - len(received))
            if not chunk:
                raise RuntimeError('Child output ended before both stream markers')
            received += chunk
        if received != expected:
            raise RuntimeError('Child output markers differ')
        (Path(sys.argv[1]) / 'child-output.bin').write_bytes(received)
    os._exit(0)
'''
    subprocess.run([sys.executable, '-c', code, str(tmp_path), str(int(explicit_stdio))],
                   check=True, timeout=20, cwd=Path(__file__).resolve().parents[1])
    if explicit_stdio:
        assert (tmp_path / 'child-output.bin').read_bytes() == b'child stdout|child stderr|'
    try:
        with pytest.raises(RuntimeError, match='owns the workspace'):
            with ReleaseLock(tmp_path):
                pass
    finally:
        (tmp_path / 'stop').touch()
    deadline = time.monotonic() + 5
    while True:
        try:
            with ReleaseLock(tmp_path):
                break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.02)


def test_successful_publication_preserves_config_and_retains_previous_bundle(tmp_path):
    p = installed(tmp_path)
    previous = tree_inventory(p.target)
    candidate = tree_inventory(p.stage)
    result = p.publish({'source_sha256': 'input', 'portable_package': candidate}, lambda: None)
    assert result['passed'] and result['state'] == 'committed'
    assert tree_inventory(p.backup) == previous
    assert (p.target / 'config.toml').read_bytes() == b'private config\r\n'
    assert (p.target / 'Empire.exe').read_bytes() == b'candidate executable'
    assert 'config.toml' not in result['portable_package']['files']
    recover_pending(tmp_path)
    assert (p.target / 'Empire.exe').read_bytes() == b'candidate executable'


@pytest.mark.parametrize('old_shortcut', [True, False])
def test_shortcut_is_switched_and_rolled_back_with_bundle(tmp_path, old_shortcut):
    p = installed(tmp_path)
    if old_shortcut:
        p.shortcut.write_bytes(b'old shortcut')
    p.shortcut_stage.write_bytes(b'new shortcut')
    old = tree_inventory(p.target)
    calls = 0

    def interrupt():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        p.publish({}, interrupt)
    assert tree_inventory(p.target) == old
    if old_shortcut:
        assert p.shortcut.read_bytes() == b'old shortcut'
    else:
        assert not p.shortcut.exists()
    assert p.shortcut_rejected.read_bytes() == b'new shortcut'


@pytest.mark.parametrize('failure', ['before', 'second_rename', 'after', 'cancel'])
def test_switch_failures_restore_original_program_and_config(tmp_path, monkeypatch, failure):
    p = installed(tmp_path)
    previous = tree_inventory(p.target)
    calls = 0
    rename = os.rename

    def injected_rename(source, target):
        if source == p.stage and failure == 'second_rename':
            raise PermissionError('target occupied')
        return rename(source, target)

    def check():
        nonlocal calls
        calls += 1
        if failure == 'before' or (calls == 2 and failure == 'after'):
            raise RuntimeError('source changed')
        if calls == 2 and failure == 'cancel':
            raise KeyboardInterrupt

    monkeypatch.setattr(os, 'rename', injected_rename)
    with pytest.raises((RuntimeError, PermissionError, KeyboardInterrupt)):
        p.publish({}, check)
    assert tree_inventory(p.target) == previous
    if p.journal.exists():
        assert json.loads(p.journal.read_text())['passed'] is False


def test_config_copy_failure_does_not_modify_installed_bundle(tmp_path, monkeypatch):
    p = installed(tmp_path)
    previous = tree_inventory(p.target)
    original = Path.open

    def denied(path, *args, **kwargs):
        if path == p.stage / 'config.toml' and args == ('xb',):
            raise PermissionError('configuration not writable')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', denied)
    with pytest.raises(PermissionError):
        p.publish({}, lambda: None)
    assert tree_inventory(p.target) == previous
    assert not p.journal.exists()


@pytest.mark.parametrize('crash_after', [1, 2])
def test_process_crash_between_directory_moves_is_recovered(tmp_path, crash_after):
    p = installed(tmp_path)
    previous = tree_inventory(p.target)
    script = '''
import os,sys
from pathlib import Path
from scripts.release_publish import Publication
p=Publication(Path(sys.argv[1]), Path(sys.argv[2]))
original=os.rename
count=0
def rename(a,b):
    global count
    original(a,b)
    count+=1
    if count==int(sys.argv[3]): os._exit(73)
os.rename=rename
p.publish({}, lambda:None)
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), str(p.run), str(crash_after)],
                            cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 73
    recover_pending(tmp_path)
    assert tree_inventory(p.target) == previous
    assert json.loads(p.journal.read_text())['state'] == 'rolled_back'


def test_recovery_refuses_unknown_target_and_external_run(tmp_path):
    p = installed(tmp_path)
    with pytest.raises(RuntimeError, match='escaped'):
        Publication(tmp_path, tmp_path.parent / 'outside')
    write_json(p.journal, dict(schema=1, run_id=p.run.name, state='switching', passed=False,
                              previous_sha256='missing', candidate_sha256='candidate'))
    before = tree_inventory(p.target)
    with pytest.raises(RuntimeError, match='changed'):
        p.recover()
    assert tree_inventory(p.target) == before


def test_owned_normalizes_parent_segments_without_unbounded_ancestry_walk(tmp_path):
    root = tmp_path / 'build/releases'
    path = tmp_path / 'build/other/../releases/run'
    assert owned(root, path) == root / 'run'


@pytest.mark.skipif(os.name != 'nt', reason='Windows directory junction safety')
def test_owned_rejects_junction_hidden_before_parent_segment(tmp_path):
    target = tmp_path / 'nested/target'
    target.mkdir(parents=True)
    link = tmp_path / 'linked'
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    command = f'New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} | Out-Null'
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                   check=True, capture_output=True)
    with pytest.raises(RuntimeError, match='links or junctions'):
        owned(tmp_path, link / '../destination')


def test_late_interrupt_after_durable_commit_is_not_a_failure(tmp_path, monkeypatch):
    from scripts import release_publish

    p = installed(tmp_path)
    writer = release_publish.write_json

    def interrupt_after_write(path, value):
        writer(path, value)
        if value.get('state') == 'committed':
            raise KeyboardInterrupt

    monkeypatch.setattr(release_publish, 'write_json', interrupt_after_write)
    result = p.publish({}, lambda: None)
    assert result['passed'] and result['state'] == 'committed'
    assert (p.target / 'Empire.exe').read_bytes() == b'candidate executable'


def test_shortcut_failure_restores_bundle_even_when_external_shortcut_changed(tmp_path):
    p = installed(tmp_path)
    p.shortcut.write_bytes(b'original link')
    p.shortcut_stage.write_bytes(b'candidate link')
    old = tree_inventory(p.target)

    def change():
        p.shortcut.write_bytes(b'external modification')

    with pytest.raises(RuntimeError, match='changed'):
        p.publish({}, change)
    assert tree_inventory(p.target) == old
    assert p.shortcut.read_bytes() == b'external modification'


def test_identical_old_and_candidate_before_switch_is_safe_to_recover(tmp_path):
    p = installed(tmp_path)
    digest = tree_inventory(p.target)['sha256']
    write_json(p.journal, dict(schema=1, run_id=p.run.name, state='switching', passed=False,
                              previous_sha256=digest, candidate_sha256=digest))
    p.recover()
    assert tree_inventory(p.target)['sha256'] == digest


def test_candidate_edit_after_smoke_is_rejected_before_config_or_target_changes(tmp_path):
    p = installed(tmp_path)
    old = tree_inventory(p.target)
    verified = tree_inventory(p.stage)['sha256']
    (p.stage / 'Empire.exe').write_bytes(b'unverified change')
    with pytest.raises(RuntimeError, match='after portable smoke'):
        p.publish({}, lambda: None, expected_package=verified)
    assert tree_inventory(p.target) == old
    assert not (p.stage / 'config.toml').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows executable handle sharing semantics')
def test_real_windows_occupied_executable_does_not_replace_original(tmp_path):
    import ctypes
    from ctypes import wintypes

    p = installed(tmp_path)
    old = tree_inventory(p.target)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(p.target / 'Empire.exe'), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value
    try:
        with pytest.raises(PermissionError):
            p.publish({}, lambda: None)
    finally:
        kernel.CloseHandle(handle)
    assert tree_inventory(p.target) == old


def test_runner_detects_real_child_edit_and_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(release.Runner, 'git', lambda self, *args: '0' * 40)
    run = tmp_path / 'build/releases/runner'
    run.mkdir(parents=True)
    (tmp_path / 'src').mkdir()
    path = tmp_path / 'src/input.py'
    path.write_text('before', encoding='utf-8')
    with ReleaseLock(tmp_path) as lock:
        runner = release.Runner(tmp_path, lock, run)
        with pytest.raises(RuntimeError, match='exit 7'):
            runner.command([sys.executable, '-c', 'raise SystemExit(7)'])
        with pytest.raises(RuntimeError, match='inputs changed'):
            runner.command([sys.executable, '-c',
                            'import sys; from pathlib import Path; Path(sys.argv[1]).write_text("after")', path])


def test_edit_then_restore_bytes_still_invalidates_this_release(tmp_path, monkeypatch):
    monkeypatch.setattr(release.Runner, 'git', lambda self, *args: '0' * 40)
    run = tmp_path / 'build/releases/runner'
    run.mkdir(parents=True)
    path = tmp_path / 'module.py'
    path.write_text('before', encoding='utf-8')
    with ReleaseLock(tmp_path) as lock:
        runner = release.Runner(tmp_path, lock, run)
        original = path.read_bytes()
        path.write_bytes(b'intermediate code')
        path.write_bytes(original)
        assert input_inventory(tmp_path) == runner.inputs
        with pytest.raises(RuntimeError, match='restored bytes'):
            runner.check()


@pytest.mark.parametrize('stage', ['verify', 'package', 'portable_smoke'])
def test_gate_stage_failure_never_replaces_installed_program(tmp_path, monkeypatch, stage):
    p = installed(tmp_path)
    previous = tree_inventory(p.target)
    monkeypatch.setattr(release, 'require_stopped', lambda *args: None)
    monkeypatch.setattr(release.Runner, 'git', lambda self, *args: '0' * 40)

    def run_stage(name):
        def action(runner, *args):
            with pytest.raises(RuntimeError, match='owns the workspace'):
                with ReleaseLock(tmp_path):
                    pass
            if stage == name:
                raise RuntimeError('injected ' + name + ' failure')
            if name == 'verify':
                return tmp_path / 'dependency.json', tmp_path / 'capacity.json'
            return {}
        return action

    for name in ('verify', 'package', 'portable_smoke'):
        monkeypatch.setattr(release, name, run_stage(name))
    with pytest.raises(RuntimeError, match='injected'):
        release.release(tmp_path)
    assert tree_inventory(p.target) == previous
    assert not (tmp_path / 'build/release-report.json').exists()


def test_gate_uses_durable_commit_if_interrupted_after_publish_returns(tmp_path, monkeypatch):
    installed(tmp_path)
    monkeypatch.setattr(release, 'require_stopped', lambda *args: None)
    monkeypatch.setattr(release, 'prepare_shortcut', lambda *args: None)
    monkeypatch.setattr(release.Runner, 'git', lambda self, *args: '0' * 40)
    monkeypatch.setattr(release, 'verify', lambda runner: (tmp_path / 'dependency', tmp_path / 'capacity'))

    def packaged(runner, publication, dependency):
        publication.stage.mkdir(parents=True)
        (publication.stage / 'Empire.exe').write_bytes(b'committed candidate')
        return {'commit': runner.commit}

    monkeypatch.setattr(release, 'package', packaged)
    monkeypatch.setattr(release, 'portable_smoke', lambda runner, publication:
                        {'package': tree_inventory(publication.stage)})
    publish = Publication.publish

    def interrupted(self, *args, **kwargs):
        publish(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(Publication, 'publish', interrupted)
    release.release(tmp_path)
    report = json.loads((tmp_path / 'build/release-report.json').read_text())
    assert report['passed'] and report['state'] == 'committed'
    assert not (tmp_path / 'build/releases' / report['run_id'] / 'failure.json').exists()
    assert (tmp_path / 'dist/Empire/Empire.exe').read_bytes() == b'committed candidate'
