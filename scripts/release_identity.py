"""Deterministic release inputs and bounded, workspace-owned output paths."""
import hashlib
import json
import os
import struct
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _file_change_api():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _parse_file_usn(record):
    if len(record) < 8:
        raise RuntimeError('Incomplete NTFS change identity')
    length, major, minor = struct.unpack_from('<IHH', record)
    minimum, offset = {2: (60, 24), 3: (76, 40)}.get(major, (0, 0))
    if not minimum or minor != 0 or length != len(record) or length < minimum:
        raise RuntimeError('Unsupported NTFS change identity')
    usn = struct.unpack_from('<q', record, offset)[0]
    if usn <= 0:
        raise RuntimeError('NTFS change journal identity is unavailable')
    return major, minor, usn


def _windows_file_change_token(path):
    import ctypes
    from ctypes import wintypes

    kernel = _file_change_api()
    # READ_DATA, SHARE_READ only: an outstanding writer/deleter must also reject
    # the snapshot, even before closing its handle publishes the final USN.
    handle = kernel.CreateFileW(str(Path(path).resolve()), 1, 1, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        raise RuntimeError('Cannot obtain release input change identity: ' + Path(path).name) from ctypes.WinError(ctypes.get_last_error())
    primary = None
    try:
        versions = ctypes.create_string_buffer(struct.pack('<HH', 2, 3))
        output = ctypes.create_string_buffer(4096)
        size = wintypes.DWORD()
        # FSCTL_READ_FILE_USN_DATA reads this file, without enumerating or writing
        # a volume journal. Unsupported filesystems/journals fail closed.
        if not kernel.DeviceIoControl(handle, 0x900eb, versions, 4, output, len(output),
                                      ctypes.byref(size), None):
            raise RuntimeError('Cannot obtain release input change identity: ' + Path(path).name) from ctypes.WinError(ctypes.get_last_error())
        return _parse_file_usn(output.raw[:size.value])
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if not kernel.CloseHandle(handle):
            cleanup = ctypes.WinError(ctypes.get_last_error())
            if primary is None:
                raise cleanup
            primary.add_note('Release input identity handle close failed: ' + str(cleanup))


def input_stats(root, inventory):
    # Local run guard only: unlike the content digest, these metadata are not portable.
    result = {}
    for name in inventory['files']:
        path = Path(root) / name
        before = stat_signature(path)
        token = (_windows_file_change_token(path),) if os.name == 'nt' else ()
        if stat_signature(path) != before:
            raise RuntimeError('Release input changed while identifying: ' + name)
        result[name] = (*before, *token)
    return result


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
