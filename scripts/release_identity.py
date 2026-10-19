"""Deterministic release inputs and bounded, workspace-owned output paths."""
import hashlib
import json
import os
from pathlib import Path

INPUT_DIRECTORIES = ('src', 'tests', 'scripts', 'sql', 'config', 'docs')
ROOT_SUFFIXES = {'.md', '.toml', '.lock', '.ps1', '.spec', '.json', '.yml', '.yaml', '.txt', '.py', '.js'}
EXCLUDED_PARTS = {'__pycache__', '.pytest_cache', '.ruff_cache'}
PRIVATE_INPUTS = {'config.toml', 'config/local.toml'}


def owned(root, path):
    root, path = Path(root).resolve(), Path(path)
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise RuntimeError('Release path escaped its owned directory')
    # Check the original spelling as well: normalizing link/.. first can hide a junction.
    lexical = path.absolute()
    while True:
        if lexical.is_symlink() or lexical.is_junction():
            raise RuntimeError('Release paths cannot contain links or junctions')
        parent = lexical.parent
        if parent == lexical:
            break
        lexical = parent
    current = Path(os.path.abspath(path))
    if not current.is_relative_to(root):
        raise RuntimeError('Release path must use its canonical workspace location')
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise RuntimeError('Release paths cannot contain links or junctions')
        parent = current.parent
        if parent == current:
            raise RuntimeError('Release path ancestry escaped its owned directory')
        current = parent
    return resolved


def files(directory, *, source=True):
    directory = Path(directory)
    if not directory.exists():
        return
    for path in sorted(directory.iterdir()):
        if source and (path.name in EXCLUDED_PARTS or path.name.endswith('.egg-info')):
            continue
        if path.is_symlink() or path.is_junction():
            raise RuntimeError('Release input/output contains a link or junction: ' + path.name)
        if path.is_dir():
            yield from files(path, source=source)
        elif path.is_file():
            if not source or path.suffix not in {'.pyc', '.pyo'}:
                yield path


def sha256(path):
    before = stat_signature(path)
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    if stat_signature(path) != before:
        raise RuntimeError('Release file changed while hashing: ' + Path(path).name)
    return digest.hexdigest()


def stat_signature(path):
    value = Path(path).stat()
    return (value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_dev, value.st_ino)


def input_stats(root, inventory):
    # Local run guard only: unlike the content digest, these metadata are not portable.
    return {name: stat_signature(Path(root) / name) for name in inventory['files']}


def mapping_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def input_inventory(root):
    root = Path(root).resolve()
    paths = [p for folder in INPUT_DIRECTORIES for p in files(root / folder)]
    paths.extend(p for p in root.iterdir() if p.is_file()
                 and (p.suffix in ROOT_SUFFIXES or p.name == '.gitignore')
                 and p.name not in {'.build.lock', 'config.toml'})
    entries = {}
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if relative in PRIVATE_INPUTS or path.name.startswith('.download-settings-'):
            continue
        owned(root, path)
        entries[relative] = sha256(path)
    return {'sha256': mapping_digest(entries), 'files': entries}


def tree_inventory(directory):
    directory = Path(directory)
    entries = {p.relative_to(directory).as_posix(): sha256(p) for p in files(directory, source=False)}
    return {'sha256': mapping_digest(entries), 'files': entries}


def assert_inputs(root, expected):
    current = input_inventory(root)
    if current != expected:
        changed = sorted(k for k in current['files'].keys() | expected['files'].keys()
                         if current['files'].get(k) != expected['files'].get(k))
        raise RuntimeError('Release inputs changed; rerun the gate: ' + ', '.join(changed[:12]))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
