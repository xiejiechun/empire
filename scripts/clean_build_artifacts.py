"""Explicit, dry-run-first retention for disposable build artifacts (not databases)."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_identity import owned
from scripts.release_lock import ReleaseLock


def linked(path):
    return bool(path.lstat().st_file_attributes & 1024) if os.name == 'nt' else path.is_symlink()


def confined(root, path):
    """Reuse publication's canonical path and linked-ancestor guard."""
    return owned(root / 'build', path)


def measure(path):
    """No junction traversal, even for cyclic test fixtures."""
    size, newest, database = 0, path.stat().st_mtime, False
    stack = [path]
    while stack:
        folder = stack.pop()
        for child in folder.iterdir():
            stat = child.lstat()
            newest = max(newest, stat.st_mtime)
            if linked(child):
                continue
            if child.is_dir():
                stack.append(child)
            else:
                size += stat.st_size
                database |= child.name in {'auto.cnf', 'ibdata1'}
    return dict(bytes=size, newest=newest, database=database)


def release_time(run):
    # Removing a child changes the directory mtime; retained completion records
    # provide stable ordering across repeated maintenance runs.
    markers = [run / name for name in ('report.json', 'failure.json', 'publication.json')]
    return max((p.stat().st_mtime for p in markers if p.is_file() and not linked(p)),
               default=run.stat().st_mtime)


def candidates(root, days=7, keep=3, now=None):
    if days < 1 or keep < 1:
        raise ValueError('Retention must preserve at least one day and one release')
    cutoff = (time.time() if now is None else now) - days * 86400
    build = root / 'build'
    if not build.exists() or linked(build):
        raise ValueError('A real build directory is required')
    paths = [p for p in build.glob('pytest-*') if p.is_dir() and not linked(p)]
    releases = build / 'releases'
    if releases.exists():
        if linked(releases):
            raise ValueError('Linked releases directory')
        runs = sorted((p for p in releases.iterdir() if p.is_dir() and not linked(p)
                       and re.fullmatch('[0-9a-f]{32}', p.name)),
                      key=release_time, reverse=True)
        for run in runs[keep:]:
            # Unknown/interrupted publication state is retained for inspection.
            if not any((run / name).is_file() for name in
                       ('report.json', 'failure.json', 'publication.json')):
                continue
            for name in ('pytest', 'pyinstaller', 'staging', 'previous',
                         'different working directory', '用户 数据'):
                path = run / name
                if path.is_dir() and not linked(path):
                    paths.append(path)
    result = []
    for path in paths:
        confined(root, path)
        stats = measure(path)
        if stats['newest'] < cutoff and not stats['database']:
            result.append(dict(path=path.relative_to(root).as_posix(), **stats))
    return result


def assert_idle(root):
    if os.name != 'nt':
        raise RuntimeError('Operational cleanup is supported on Windows only')
    # Inspect commands internally; output contains only IDs, never credentials.
    command = r"""
    $items = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
      $_.Name -match '^(python|pythonw|mysqld|node|powershell|pwsh)[.]exe$' -and
      $_.ProcessId -ne $PID -and
      ($_.CommandLine -match '(^|\s)(-m\s+)?pytest(\s|$)|scripts[\\/]release[.]py|verify-release[.]ps1|build[.]ps1' -or
       ($_.CommandLine -match '[\\/]build[\\/]' -and $_.Name -notmatch 'powershell|pwsh'))
    } | Select-Object -ExpandProperty ProcessId)
    ConvertTo-Json -InputObject $items -Compress
    """
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             command], capture_output=True, text=True, check=True, cwd=root)
    busy = json.loads(result.stdout)
    if busy:
        raise RuntimeError('Build/test processes are active; retained everything. PIDs: ' + str(busy))


def remove(root, row, cutoff):
    path = confined(root, root / row['path'])
    before = measure(path)
    if before != {key: row[key] for key in ('bytes', 'newest', 'database')}:
        raise RuntimeError('Artifact changed after planning: ' + row['path'])
    if before['database'] or before['newest'] >= cutoff:
        raise RuntimeError('Database or recent artifact cannot be removed')
    # Python >=3.12 on Windows removes junctions without traversing their targets.
    # Do not chmod read-only files: hard-linked source files must remain untouched.
    shutil.rmtree(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--keep-releases', type=int, default=3)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with ReleaseLock(root):
        assert_idle(root)
        now = time.time()
        rows = candidates(root, args.days, args.keep_releases, now)
        report = dict(applied=args.apply, days=args.days, keep_releases=args.keep_releases,
                      planned_bytes=sum(r['bytes'] for r in rows), targets=rows, removed=[])
        directory = root / 'build' / 'storage-maintenance'
        if directory.exists():
            confined(root, directory)
        directory.mkdir(exist_ok=True)
        output = directory / (str(time.time_ns()) + '.json')
        try:
            if args.apply:
                assert_idle(root)
                for row in rows:
                    remove(root, row, now - args.days * 86400)
                    report['removed'].append(row['path'])
        finally:
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(dict(report=str(output), candidates=len(rows),
                              removed=len(report['removed']),
                              planned_GiB=round(report['planned_bytes'] / 2**30, 3))))


if __name__ == '__main__':
    main()
