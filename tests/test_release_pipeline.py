"""Real filesystem/process counterexamples for the single publication path."""
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
)
from scripts.release_lock import ReleaseLock


@pytest.mark.parametrize('name', ['src/app.py', 'src/icon.ico', 'src/rules.json',
                                'tests/test_x.py', 'scripts/build.py', 'sql/schema.sql',
                                'docs/guide.md', 'docs/documentation-coverage.json',
                                'config/app.example.toml', 'requirements.lock', 'desktop/package.json',
                                'verify-release.ps1', '.gitattributes',
                                'src/empire/documentation/help-index.json',
                                'src/empire/features/news/docs/help/overview.md',
                                'src/empire/plugins/ui/storage_reference.md'])
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
