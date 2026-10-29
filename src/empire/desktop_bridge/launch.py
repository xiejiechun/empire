"""Launch the sole Electron desktop from the source command line."""
import os
import subprocess
from pathlib import Path


def launch(config):
    root = Path(__file__).resolve().parents[3]
    electron = root / 'desktop/node_modules/electron/dist/electron.exe'
    if not electron.is_file():
        raise RuntimeError('请先在 desktop 安装依赖并构建新版客户端')
    env = dict(os.environ)
    env.pop('ELECTRON_RUN_AS_NODE', None)
    return subprocess.call([str(electron), str(root / 'desktop'),
                            '--empire-config=' + str(Path(config).resolve())], cwd=root, env=env)
