"""Real filesystem writes must invalidate a release even within one clock tick."""
import os
import struct
from types import SimpleNamespace

import pytest

from scripts import release
from scripts import release_identity as identity
from scripts.release_lock import ReleaseLock


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows NTFS change identity')
def test_same_stat_edit_restore_still_invalidates_runner(tmp_path, monkeypatch):
    path = tmp_path / 'module.py'
    path.write_bytes(b'before')
    # Model the actual failing filesystem tick, rather than sleeping until the
    # legacy timestamp guard happens to see a change.
    signature = identity.stat_signature(path)
    monkeypatch.setattr(identity, 'stat_signature', lambda path: signature)
    monkeypatch.setattr(release.Runner, 'git', lambda self, *args: '0' * 40)
    run = tmp_path / 'build/releases/runner'
    run.mkdir(parents=True)
    with ReleaseLock(tmp_path) as lock:
        runner = release.Runner(tmp_path, lock, run)
        for _ in range(30):
            runner.input_stats = identity.input_stats(tmp_path, runner.inputs)
            runner.check()
            path.write_bytes(b'intermediate code')
            path.write_bytes(b'before')
            assert identity.input_inventory(tmp_path) == runner.inputs
            with pytest.raises(RuntimeError, match='restored bytes'):
                runner.check()


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows file sharing semantics')
def test_open_writer_rejects_snapshot_before_final_usn_is_published(tmp_path):
    path = tmp_path / 'module.py'
    path.write_bytes(b'before')
    inventory = identity.input_inventory(tmp_path)
    before = identity.input_stats(tmp_path, inventory)
    with path.open('r+b') as writer:
        writer.write(b'after!')
        writer.flush()
        writer.seek(0)
        writer.write(b'before')
        writer.flush()
        assert identity.input_inventory(tmp_path) == inventory
        with pytest.raises(RuntimeError, match='change identity'):
            identity.input_stats(tmp_path, inventory)
    assert identity.input_stats(tmp_path, inventory) != before


@pytest.mark.parametrize('major,minimum,offset', [(2, 60, 24), (3, 76, 40)])
def test_supported_usn_records_preserve_monotonic_change_identity(major, minimum, offset):
    value = bytearray(minimum)
    struct.pack_into('<IHH', value, 0, minimum, major, 0)
    struct.pack_into('<q', value, offset, 12345)
    assert identity._parse_file_usn(value) == (major, 0, 12345)


@pytest.mark.parametrize('record', [b'', struct.pack('<IHH', 8, 4, 0),
    struct.pack('<IHH', 60, 2, 1) + bytes(52),
    struct.pack('<IHH', 60, 2, 0) + bytes(52),
    struct.pack('<IHH', 80, 3, 0) + bytes(68)])
def test_unknown_incomplete_or_unavailable_usn_cannot_be_trusted(record):
    with pytest.raises(RuntimeError):
        identity._parse_file_usn(record)


@pytest.mark.skipif(os.name != 'nt', reason='Windows error and handle ownership')
@pytest.mark.parametrize('close_ok', [True, False])
def test_usn_query_failure_closes_owned_handle_and_preserves_primary_error(tmp_path, monkeypatch, close_ok):
    import ctypes

    closed = []
    def query(*args):
        ctypes.set_last_error(1)
        return False
    def close(handle):
        closed.append(handle)
        ctypes.set_last_error(6)
        return close_ok
    api = SimpleNamespace(CreateFileW=lambda *args: 123, DeviceIoControl=query, CloseHandle=close)
    monkeypatch.setattr(identity, '_file_change_api', lambda: api)
    with pytest.raises(RuntimeError, match='change identity') as error:
        identity._windows_file_change_token(tmp_path/'source.py')
    assert closed == [123]
    assert bool(getattr(error.value, '__notes__', [])) is not close_ok
