"""Retention must not follow links, touch databases, or discard release evidence."""
import os
import subprocess
import time

import pytest

from scripts.clean_build_artifacts import candidates, confined, measure, remove


def old_tree(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'payload').write_bytes(b'artifact')
    then = time.time() - 30 * 86400
    for entry in (path / 'payload', path):
        os.utime(entry, (then, then))
    return path


def test_retention_preserves_evidence_recent_runs_and_database(tmp_path):
    for index in range(4):
        run = tmp_path / 'build/releases' / f'{index:032x}'
        old_tree(run / 'pytest')
        (run / 'report.json').write_text('{}')
        os.utime(run / 'report.json', (100 + index, 100 + index))
        os.utime(run, (100 + index, 100 + index))
    os.utime(tmp_path / 'build/releases' / ('0' * 32), None)
    old_tree(tmp_path / 'build/pytest-old')
    fresh = tmp_path / 'build/pytest-fresh'
    fresh.mkdir()
    (fresh / 'payload').write_bytes(b'recent')
    db = old_tree(tmp_path / 'build/pytest-database')
    (db / 'auto.cnf').write_text('database identity')
    os.utime(db / 'auto.cnf', (100, 100))
    os.utime(db, (100, 100))
    rows = candidates(tmp_path)
    assert {r['path'] for r in rows} == {
        'build/pytest-old', 'build/releases/' + '0' * 32 + '/pytest'}
    for row in rows:
        remove(tmp_path, row, time.time() - 7 * 86400)
    assert (tmp_path / 'build/releases' / ('0' * 32) / 'report.json').is_file()
    assert (db / 'auto.cnf').is_file()
    assert (fresh / 'payload').is_file()


def test_changed_target_is_not_removed(tmp_path):
    path = old_tree(tmp_path / 'build/pytest-old')
    row = candidates(tmp_path)[0]
    (path / 'payload').write_bytes(b'new work')
    with pytest.raises(RuntimeError, match='changed'):
        remove(tmp_path, row, time.time())
    assert path.exists()


def test_outside_and_build_root_are_rejected(tmp_path):
    (tmp_path / 'build').mkdir()
    for path in (tmp_path, tmp_path / 'build', tmp_path / 'src',
                 tmp_path / 'build/../src'):
        with pytest.raises(RuntimeError):
            confined(tmp_path, path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction counterexample')
def test_junction_cycle_and_outside_target_are_never_followed(tmp_path):
    path = old_tree(tmp_path / 'build/pytest-old')
    outside = tmp_path / 'source'
    outside.mkdir()
    sentinel = outside / 'keep'
    sentinel.write_bytes(b'original')
    for name, target in [('cycle', path), ('outside', outside)]:
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(path / name), str(target)],
                       check=True, capture_output=True)
    os.utime(path, (100, 100))
    assert measure(path)['bytes'] == len(b'artifact')
    with pytest.raises(RuntimeError):
        confined(tmp_path, path / 'outside/keep')
    row = candidates(tmp_path, now=time.time() + 40 * 86400)[0]
    remove(tmp_path, row, time.time() + 30 * 86400)
    assert sentinel.read_bytes() == b'original'
    assert not path.exists()


def test_unfinished_release_is_retained(tmp_path):
    run = tmp_path / 'build/releases' / ('a' * 32)
    old_tree(run / 'pytest')
    assert candidates(tmp_path, keep=1) == []
    # Two directories ensure the unfinished one is not protected only by keep=1.
    latest = tmp_path / 'build/releases' / ('b' * 32)
    latest.mkdir()
    os.utime(run, (100, 100))
    assert candidates(tmp_path, keep=1) == []


def test_cleanup_cannot_take_publication_lock(tmp_path):
    from scripts.release_lock import ReleaseLock

    with ReleaseLock(tmp_path):
        with pytest.raises(RuntimeError):
            with ReleaseLock(tmp_path):
                pytest.fail('Second owner acquired the publication lock')
