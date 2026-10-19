import json
import socket
from pathlib import Path

import pytest

from empire import __main__ as main
from empire import build_info
from empire.core.manager import PluginManager


def test_package_declarations_use_real_constructors_without_starting_services(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Package smoke must not start services or connect')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(PluginManager, 'start', forbidden)
    monkeypatch.setattr(PluginManager, 'autostart', forbidden)
    manager = main.package_declarations()
    assert manager.providers['collector.sina_news'] == 'collector.sina_news'
    assert not manager.registry.values
    assert all(entry.context is None and entry.state == 'STOPPED'
               for entry in manager.entries.values())


@pytest.mark.parametrize('damage', ['unexpected_field', 'missing_field', 'missing_file'])
def test_packaged_smoke_rejects_invalid_identity_before_shell_or_connections(tmp_path, monkeypatch, damage):
    path = tmp_path / 'build_manifest.json'
    value = {'version': '0.1.0', 'commit': 'a' * 40, 'dirty': False,
             'source_sha256': 'b' * 64, 'release_id': 'c' * 32,
             'requirements_sha256': 'd' * 64, 'built_at_utc': '2026-10-19T00:00:00Z',
             'python': '3.12.9', 'pyinstaller': '6.22.3', 'dependency_count': 42,
             'dependency_report_sha256': 'e' * 64}
    if damage == 'unexpected_field':
        value['unknown_identity'] = True
    elif damage == 'missing_field':
        del value['release_id']
    if damage != 'missing_file':
        path.write_text(json.dumps(value), encoding='utf-8')
    reader = build_info.load_build_info
    monkeypatch.setattr(build_info, 'load_build_info', lambda: reader(path))
    monkeypatch.setattr(main.sys, 'frozen', True, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError('Invalid package identity must fail before GUI or services')

    from PySide6 import QtWidgets
    monkeypatch.setattr(QtWidgets, 'QApplication', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    with pytest.raises((ValueError, RuntimeError), match='manifest|清单'):
        main.package_smoke(str(Path(tmp_path) / 'must-not-exist.png'))
    assert not (tmp_path / 'must-not-exist.png').exists()
