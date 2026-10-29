"""Exercise the actual entry point in a fresh process, without a GUI fixture."""
import os
import subprocess
import sys
from pathlib import Path


def test_bridge_keeps_qt_alive_for_runtime_request_signers():
    root = Path(__file__).resolve().parents[1]
    script = r'''
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from empire.desktop_bridge.__main__ import main

def sign():
    from empire.plugins.collectors.ths_session import ThsSession, ThsDirectorySession
    assert QCoreApplication.instance() is not None
    for cls in (ThsSession, ThsDirectorySession):
        headers = cls().headers('https://q.10jqka.com.cn/')
        assert len(headers['Cookie']) == 62

class Runtime:
    def __init__(self, *args):
        self.thread = SimpleNamespace(ident=1, join=self.join)
        self.closed = SimpleNamespace(is_set=lambda: True)
    def start(self):
        assert QCoreApplication.instance() is not None
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(sign).result()
    def join(self):
        assert QCoreApplication.instance() is not None

with patch('empire.core.config.load_config', return_value={}), \
     patch('empire.__main__.acquire_instance_lock', return_value=SimpleNamespace(unlock=lambda: None)), \
     patch('empire.__main__.configure_logging'), \
     patch('empire.core.runtime.Runtime', Runtime), \
     patch('empire.desktop_bridge.server.Server.serve'):
    assert main() == 0
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=root,
                            capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    assert result.returncode == 0, result.stderr
