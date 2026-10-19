"""Real Windows children exercise release output together with inherited ownership."""
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from scripts import release
from scripts.release_identity import sha256
from scripts.release_lock import ReleaseLock
from scripts.release_steps import retain_evidence

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Real Windows stdio and handle inheritance')


def make_runner(root, lock, monkeypatch):
    monkeypatch.setattr(release.Runner, 'git', lambda self, *args: '0' * 40)
    run = root / 'build/releases/output'
    run.mkdir(parents=True)
    return release.Runner(root, lock, run)


class BinaryConsole:
    def __init__(self, buffer):
        self.buffer = buffer
        self.header = ''

    def write(self, value):
        self.header += value
        return len(value)

    def flush(self):
        pass


class TextConsole(io.StringIO):
    class RejectedRawBuffer:
        def write(self, value):
            raise AssertionError('A console must receive decoded text')

        def flush(self):
            raise AssertionError('A console must receive decoded text')

    buffer = RejectedRawBuffer()

    def isatty(self):
        return True


class DigestBuffer:
    def __init__(self):
        self.digest = hashlib.sha256()
        self.size = self.largest = self.chunks = 0

    def write(self, value):
        self.digest.update(value)
        self.size += len(value)
        self.largest = max(self.largest, len(value))
        self.chunks += 1
        return len(value)

    def flush(self):
        pass


@pytest.mark.parametrize('console_kind', ['binary', 'text-only', 'tty'])
def test_python_print_unicode_has_explicit_encoding_and_preserves_environment(
        tmp_path, monkeypatch, console_kind):
    binary = io.BytesIO()
    console = (BinaryConsole(binary) if console_kind == 'binary' else
               TextConsole() if console_kind == 'tty' else io.StringIO())
    child_working = tmp_path / '\u4e2d\u6587 \u5de5\u4f5c\u76ee\u5f55'
    child_working.mkdir()
    child_path = child_working / '\u4e2d\u6587\u6587\u4ef6.txt'
    # Keep the command header ASCII: only the child can emit the expected text.
    code = (
        "import json,os,sys\n"
        "value=json.loads(sys.argv[1]); print(value,flush=True); print(value,file=sys.stderr,flush=True)\n"
        "assert os.getcwd()==os.path.dirname(value)\n"
        "assert os.environ['EMPIRE_TEST_OUTPUT_ENV']=='preserved'\n"
        "assert sys.stdout.encoding==sys.stderr.encoding=='utf-8'\n"
    )
    monkeypatch.setenv('PYTHONIOENCODING', 'gbk')
    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'stdout', console)
            runner.command([sys.executable, '-c', code, json.dumps(str(child_path))],
                           cwd=child_working,
                           env={'PYTHONIOENCODING': 'ascii', 'EMPIRE_TEST_OUTPUT_ENV': 'preserved'})
        expected = (str(child_path) + '\r\n') * 2
        log = runner.run_directory / 'steps/step-001.log'
        assert log.read_bytes() == expected.encode('utf-8')
        if console_kind == 'binary':
            assert binary.getvalue() == expected.encode('utf-8')
        else:
            assert expected in console.getvalue()
            assert '\ufffd' not in console.getvalue()


@pytest.mark.parametrize('tty', [False, True])
def test_shortcut_script_declares_utf8_for_real_powershell_streams(tmp_path, monkeypatch, tty):
    console = TextConsole() if tty else io.StringIO()

    def literal(path):
        return "'" + str(path).replace("'", "''") + "'"

    script = Path(__file__).resolve().parents[1] / 'scripts/release_shortcut.ps1'
    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        candidate = runner.run_directory / 'candidate.lnk'
        working = runner.run_directory
        # Dot-source the actual shortcut entry point, then exercise both streams
        # with its declared encoding. The header contains only ASCII char codes.
        code = (
            "$ErrorActionPreference='Stop'; . " + literal(script)
            + ' -Candidate ' + literal(candidate) + ' -Existing ' + literal(working / 'absent.lnk')
            + ' -Target ' + literal(working / 'Empire.exe') + ' -WorkingDirectory ' + literal(working)
            + "; $v = [string][char]0x4e2d + [string][char]0x6587; "
            + "Write-Output $v; [Console]::Error.WriteLine($v)"
        )
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'stdout', console)
            runner.command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code])
        expected = '\u4e2d\u6587\r\n' * 2
        assert candidate.is_file()
        assert (runner.run_directory / 'steps/step-001.log').read_bytes() == expected.encode('utf-8')
        assert expected in console.getvalue()
        assert '\ufffd' not in console.getvalue()


@pytest.mark.parametrize(('expected', 'actual'), [(0, 0), (7, 7), (0, 7)])
def test_both_streams_exact_exit_and_retained_output(tmp_path, monkeypatch, capsys, expected, actual):
    first, second = b'child stdout marker\n', b'child stderr marker\n'
    code = ('import os,sys; os.write(1,bytes.fromhex(sys.argv[1])); '
            'os.write(2,bytes.fromhex(sys.argv[2])); raise SystemExit(int(sys.argv[3]))')
    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        command = [sys.executable, '-c', code, first.hex(), second.hex(), str(actual)]
        if expected == actual:
            runner.command(command, expected=expected)
        else:
            with pytest.raises(RuntimeError, match='exit 7'):
                runner.command(command, expected=expected)
        # The command header contains only hex, so it cannot satisfy this assertion.
        assert (first + second).decode() in capsys.readouterr().out
        log = runner.run_directory / 'steps/step-001.log'
        status = log.with_suffix('.json')
        assert log.read_bytes() == first + second
        assert json.loads(status.read_text()) == {
            'log': log.name, 'output_complete': True, 'returncode': actual}
        for path in (log, status):
            assert runner.evidence[path.relative_to(tmp_path).as_posix()] == sha256(path)
        retained = retain_evidence(runner)
        copied = Path(retained[log.relative_to(tmp_path).as_posix()]['path'])
        assert copied.read_bytes() == first + second
        log.write_bytes(b'tampered')
        marker = runner.run_directory / 'must-not-run'
        with pytest.raises(RuntimeError, match='Generated release evidence changed'):
            runner.command([sys.executable, '-c',
                            'import sys; from pathlib import Path; Path(sys.argv[1]).touch()', marker])
        assert not marker.exists()


def test_partial_line_is_forwarded_before_child_can_finish(tmp_path, monkeypatch):
    marker, tail = b'live-without-newline', b'completed'
    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        proceed = runner.run_directory / 'allow-child-exit'

        class HandshakeBuffer:
            def __init__(self):
                self.value = bytearray()
                self.released = False

            def write(self, value):
                self.value.extend(value)
                if marker in self.value and not self.released:
                    self.released = True
                    proceed.touch()
                return len(value)

            def flush(self):
                pass

        output = HandshakeBuffer()
        code = (
            "import os,sys,time; from pathlib import Path\n"
            "os.write(1,bytes.fromhex(sys.argv[1])); gate=Path(sys.argv[2]); end=time.monotonic()+10\n"
            "while not gate.exists() and time.monotonic()<end: time.sleep(.01)\n"
            "if not gate.exists(): raise SystemExit(9)\n"
            "os.write(2,bytes.fromhex(sys.argv[3]))\n"
        )
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'stdout', BinaryConsole(output))
            runner.command([sys.executable, '-c', code, marker.hex(), proceed, tail.hex()])
        assert output.released and bytes(output.value) == marker + tail
        assert (runner.run_directory / 'steps/step-001.log').read_bytes() == marker + tail


def test_large_output_is_bounded_and_preserves_stderr_tail(tmp_path, monkeypatch):
    count, block, tail = 256, b'x' * 16384, b'\nstderr tail\n'
    output = DigestBuffer()
    code = (
        "import os,sys\n"
        "for _ in range(256): os.write(1,b'x'*16384)\n"
        "os.write(2,bytes.fromhex(sys.argv[1]))\n"
    )
    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'stdout', BinaryConsole(output))
            runner.command([sys.executable, '-c', code, tail.hex()])
        expected = hashlib.sha256(block * count + tail).hexdigest()
        log = runner.run_directory / 'steps/step-001.log'
        assert output.digest.hexdigest() == sha256(log) == expected
        assert output.size == len(block) * count + len(tail)
        assert output.chunks > 1 and output.largest <= 64 * 1024


@pytest.mark.parametrize('tty', [False, True])
def test_console_decodes_utf8_across_observed_chunks(tmp_path, monkeypatch, tty):
    payload = '\U0001f600中文 without newline'.encode()
    prefix, suffix = payload[:2], payload[2:]
    console = TextConsole() if tty else io.StringIO()
    seen, stop = threading.Event(), threading.Event()
    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        log = runner.run_directory / 'steps/step-001.log'
        proceed = runner.run_directory / 'continue-utf8'

        def observe_prefix():
            deadline = time.monotonic() + 10
            while not stop.is_set() and time.monotonic() < deadline:
                if log.exists() and log.stat().st_size >= len(prefix):
                    if log.read_bytes() == prefix:
                        seen.set()
                        proceed.touch()
                    return
                stop.wait(.01)

        observer = threading.Thread(target=observe_prefix)
        observer.start()
        code = (
            "import os,sys,time; from pathlib import Path\n"
            "os.write(1,bytes.fromhex(sys.argv[1])); gate=Path(sys.argv[2]); end=time.monotonic()+10\n"
            "while not gate.exists() and time.monotonic()<end: time.sleep(.01)\n"
            "if not gate.exists(): raise SystemExit(9)\n"
            "os.write(2,bytes.fromhex(sys.argv[3]))\n"
        )
        try:
            with monkeypatch.context() as patch:
                patch.setattr(sys, 'stdout', console)
                runner.command([sys.executable, '-c', code, prefix.hex(), proceed, suffix.hex()])
        finally:
            stop.set()
            proceed.touch()
            observer.join(timeout=15)
        assert not observer.is_alive() and seen.is_set()
        assert payload.decode() in console.getvalue()
        assert '\ufffd' not in console.getvalue()
        assert log.read_bytes() == payload


@pytest.mark.parametrize(('kind', 'terminate_failure'), [
    ('console', False), ('cancel', False), ('log', False), ('console', True),
])
def test_output_failure_or_cancel_reaps_only_owned_child_and_preserves_error(
        tmp_path, monkeypatch, kind, terminate_failure):
    primary = KeyboardInterrupt('test cancellation') if kind == 'cancel' else OSError('test ' + kind + ' failure')
    real_popen, real_open = subprocess.Popen, Path.open
    children = []
    marker = b'owned child is ready'
    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        stop_other = runner.run_directory / 'stop-unrelated'
        other_code = (
            "import sys,time; from pathlib import Path\n"
            "gate=Path(sys.argv[1]); end=time.monotonic()+20\n"
            "while not gate.exists() and time.monotonic()<end: time.sleep(.01)\n"
        )
        other = real_popen([sys.executable, '-c', other_code, str(stop_other)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

        def launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            if terminate_failure:
                def failed_terminate():
                    raise OSError('injected owned terminate failure')
                child.terminate = failed_terminate
            return child

        class FailedBuffer:
            def write(self, value):
                raise primary

            def flush(self):
                pass

        class FailedLog:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def write(self, value):
                raise primary

            def flush(self):
                self.wrapped.flush()

            def close(self):
                self.wrapped.close()
                raise OSError('injected log close failure')

        def open_file(path, *args, **kwargs):
            value = real_open(path, *args, **kwargs)
            if kind == 'log' and path.name == 'step-001.log' and args and args[0] == 'xb':
                return FailedLog(value)
            return value

        child_code = (
            "import os,sys,time\n"
            "os.write(1,bytes.fromhex(sys.argv[1])); time.sleep(20)\n"
        )
        try:
            with monkeypatch.context() as patch:
                patch.setattr(release.subprocess, 'Popen', launch)
                patch.setattr(Path, 'open', open_file)
                patch.setattr(sys, 'stdout', BinaryConsole(DigestBuffer() if kind == 'log' else FailedBuffer()))
                with pytest.raises(type(primary)) as caught:
                    runner.command([sys.executable, '-c', child_code, marker.hex()])
            assert caught.value is primary
            assert len(children) == 1 and children[0].poll() is not None
            assert children[0].stdout.closed
            assert other.poll() is None  # No wildcard process kill.
            status = runner.run_directory / 'steps/step-001.json'
            assert json.loads(status.read_text())['output_complete'] is False
            assert not runner.evidence
            notes = '\n'.join(primary.__notes__)
            assert 'incomplete' in notes
            if kind == 'log':
                assert 'log close failure' in notes
            else:
                assert (status.with_suffix('.log')).read_bytes() == marker
            if terminate_failure:
                assert 'injected owned terminate failure' in notes
        finally:
            stop_other.touch()
            other.wait(timeout=10)
            for child in children:
                if child.poll() is None:
                    real_popen.kill(child)  # Exact test-created process only, even after an assertion failure.
                    child.wait(timeout=10)
    assert (tmp_path / '.build.lock').exists()
    with ReleaseLock(tmp_path):
        pass


def test_short_console_write_fails_closed(tmp_path, monkeypatch):
    class ShortBuffer:
        def write(self, value):
            return max(0, len(value) - 1)

        def flush(self):
            pass

    with ReleaseLock(tmp_path) as lock:
        runner = make_runner(tmp_path, lock, monkeypatch)
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'stdout', BinaryConsole(ShortBuffer()))
            with pytest.raises(OSError, match='output write was incomplete'):
                runner.command([sys.executable, '-c', 'import os; os.write(1,b"payload")'])
        status = runner.run_directory / 'steps/step-001.json'
        assert json.loads(status.read_text())['output_complete'] is False
        assert not runner.evidence
