"""One release owner verifies, stages, smokes and safely publishes Empire."""
import argparse
import codecs
import os
import subprocess
import sys
import uuid
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_identity import (
    assert_inputs,
    input_inventory,
    input_stats,
    owned,
    sha256,
    write_json,
)
from scripts.release_lock import ReleaseLock
from scripts.release_steps import retain_evidence, verify

OUTPUT_CHUNK_BYTES = 64 * 1024


def _write_output(stream, value):
    if stream.write(value) != len(value):
        raise OSError('Release output write was incomplete')
    stream.flush()


def _stop_owned_child(child, primary):
    if child.poll() is not None:
        child.wait()
        return
    for action in ('terminate', 'kill'):
        try:
            getattr(child, action)()
            child.wait(timeout=5)
            return
        except BaseException as cleanup:
            primary.add_note(f'Owned child {child.pid} {action}/wait failed: {cleanup}')
            if child.poll() is not None:
                child.wait()
                return
    primary.add_note(f'Owned child {child.pid} may remain active; its inherited release lock is retained')


def _close_output(resources, primary):
    original = primary
    for resource in resources:
        if resource is None:
            continue
        try:
            resource.close()
        except BaseException as cleanup:
            if primary is None:
                primary = cleanup
            else:
                primary.add_note(f'Release output cleanup failed: {cleanup}')
    if original is None and primary is not None:
        raise primary


def _stream_command(args, *, cwd, env, lock, log):
    output = log.open('xb', buffering=0)
    child = primary = None
    try:
        # WindowsConsoleIO accepts UTF-8 characters, not arbitrary partial bytes.
        # A redirected binary sink keeps the exact bytes; real consoles get text.
        console = getattr(sys.stdout, 'isatty', lambda: False)()
        binary = None if console else getattr(sys.stdout, 'buffer', None)
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        # Redirected Python otherwise chooses the Windows ANSI code page.
        # This protocol also applies when the caller inherited a legacy override.
        child = subprocess.Popen(args, cwd=cwd, env={**env, 'PYTHONIOENCODING': 'utf-8'},
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, bufsize=0,
                                 **lock.child_options())
        assert child.stdout is not None
        while chunk := child.stdout.read(OUTPUT_CHUNK_BYTES):
            _write_output(output, chunk)
            if binary is not None:
                _write_output(binary, chunk)
            else:
                value = decoder.decode(chunk)
                if value:
                    _write_output(sys.stdout, value)
        if binary is None:
            value = decoder.decode(b'', final=True)
            if value:
                _write_output(sys.stdout, value)
        return child.wait()
    except BaseException as exc:
        primary = exc
        exc.add_note(f'Step output is incomplete; partial bytes are retained at {log}')
        if child is not None:
            try:
                _stop_owned_child(child, exc)
            except BaseException as cleanup:
                exc.add_note(f'Owned child cleanup failed: {cleanup}')
        raise
    finally:
        _close_output((child.stdout if child is not None else None, output), primary)


class Runner:
    def __init__(self, root, lock, run):
        self.root, self.lock, self.run_directory = root, lock, run
        self.python = root / '.venv/Scripts/python.exe'
        self.commit = self.git('rev-parse', 'HEAD')
        if len(self.commit) != 40 or any(c not in '0123456789abcdef' for c in self.commit):
            raise RuntimeError('A Git commit is required to identify the release')
        self.dirty = bool(self.git('status', '--porcelain'))
        self.inputs = input_inventory(root)
        self.input_stats = input_stats(root, self.inputs)
        self.evidence = {}
        self.step_number = 0
        write_json(run / 'inputs.json', dict(self.inputs, commit=self.commit, dirty=self.dirty,
                                            local_stat_guard=self.input_stats,
                                            private_config='excluded', generated_outputs='excluded'))

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True,
                                       **self.lock.child_options()).strip()

    def check(self):
        assert_inputs(self.root, self.inputs)
        stats = input_stats(self.root, self.inputs)
        if stats != self.input_stats:
            changed = [name for name in stats if stats[name] != self.input_stats[name]]
            raise RuntimeError('Release inputs were edited, including restored bytes: ' + ', '.join(changed[:12]))
        if self.git('rev-parse', 'HEAD') != self.commit:
            raise RuntimeError('Git HEAD changed during the release')
        for name, digest in self.evidence.items():
            if sha256(self.root / name) != digest:
                raise RuntimeError('Generated release evidence changed: ' + name)

    def command(self, args, *, cwd=None, env=None, expected=0):
        self.check()
        print('Release step: ' + ' '.join(str(v) for v in args), flush=True)
        self.step_number += 1
        folder = owned(self.run_directory, self.run_directory / 'steps')
        folder.mkdir(exist_ok=True)
        log = owned(folder, folder / f'step-{self.step_number:03d}.log')
        status = log.with_suffix('.json')
        # A partial/failed output stream never becomes completed release evidence.
        write_json(status, dict(log=log.name, output_complete=False, returncode=None))
        returncode = _stream_command([str(v) for v in args], cwd=cwd or self.root,
                                     env={**os.environ, **(env or {})}, lock=self.lock, log=log)
        write_json(status, dict(log=log.name, output_complete=True, returncode=returncode))
        for path in (log, status):
            self.evidence[path.relative_to(self.root).as_posix()] = sha256(path)
        self.check()
        if returncode != expected:
            raise RuntimeError(f'Release step failed (exit {returncode}): {Path(args[0]).name}; output: {log}')


def require_stopped(lock, root):
    if os.name != 'nt':
        raise RuntimeError('The desktop release gate requires Windows')
    # An absent named process still makes Get-Process set PowerShell's error
    # status; explicitly return success after the active-process rejection.
    script = ("$p = Get-Process Empire -ErrorAction SilentlyContinue | "
              "Where-Object { $_.Threads.Count -gt 0 }; if ($p) { exit 3 }; "
              "$backend = Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
              "Where-Object { $_.CommandLine -match '-m\\s+empire[.]desktop_bridge' }; "
              "if ($backend) { exit 3 }; exit 0")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            cwd=root, **lock.child_options())
    if result.returncode != 0:
        raise RuntimeError('Close Empire normally before release or recovery; no process was killed')


def release(root, *, recover_only=False, test_plan=None):
    """Verify and build the repository-dependent Electron launcher."""
    from scripts.build_desktop_launcher import build

    root = Path(root).resolve()
    if recover_only:
        raise ValueError('旧 Qt 目录切换已退役；当前客户端使用本机构建入口')
    with ReleaseLock(root) as lock:
        require_stopped(lock, root)
        run = owned(root, root / 'build' / 'releases' / uuid.uuid4().hex)
        run.mkdir(parents=True)
        runner = Runner(root, lock, run)
        runner.test_plan = test_plan
        try:
            dependency, capacity = verify(runner)
            runner.check()
            build(root, root / 'dist/EmpireDesktop/config.toml', lock=lock)
            runner.check()
            outputs = retain_evidence(runner)
            write_json(run / 'report.json', dict(generated_outputs=outputs, passed=True, kind='local-development-launcher',
                portable=False, source_sha256=runner.inputs['sha256'],
                dependency_report=str(dependency), capacity_report=str(capacity),
                actual_desktop='not verified by this gate'))
        except BaseException:
            write_json(run / 'failure.json', dict(passed=False, run_id=run.name))
            raise
        print('PASS local Electron launcher gate: ' + str(run / 'report.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', action='store_true', help='Restore an interrupted directory switch only')
    parser.add_argument('--test-plan', help='Explicit user-authorized JSON list of complete test files')
    args = parser.parse_args()
    try:
        release(Path(__file__).resolve().parents[1], recover_only=args.recover, test_plan=args.test_plan)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
