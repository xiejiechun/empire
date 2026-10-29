"""Build the local-development double-click launcher, not a portable product release."""
import argparse
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release import require_stopped
from scripts.release_identity import owned, sha256, write_json
from scripts.release_lock import ReleaseLock


def build(root, source):
    with ReleaseLock(root) as lock:
        require_stopped(lock, root)
        destination = owned(root, root / 'dist/EmpireDesktop')
        destination.mkdir(parents=True, exist_ok=True)
        config = destination / 'config.toml'
        if not source.is_file():
            raise ValueError('Explicit source configuration does not exist')
        if config.exists() and config.read_bytes() != source.read_bytes():
            raise ValueError('Existing launcher configuration differs; refusing to overwrite')
        stage = owned(root, root / 'build/desktop-launcher' / uuid.uuid4().hex)
        stage.mkdir(parents=True)
        compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        inputs = [root / 'desktop/launcher/EmpireLauncher.cs', root / 'desktop/electron/main.cjs',
                  root / 'desktop/electron/launch-options.cjs', root / 'desktop/package-lock.json']
        inputs.extend(p for folder in ('src', 'electron') for p in (root / 'desktop' / folder).rglob('*') if p.is_file())
        inputs = list(dict.fromkeys(inputs))
        before = {str(p.relative_to(root)): sha256(p) for p in inputs}
        commands = [
            ['npm.cmd', '--prefix', str(root / 'desktop'), 'run', 'build'],
            ['npm.cmd', '--prefix', str(root / 'desktop'), 'run', 'test:transport'],
            [str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
             '/reference:System.Windows.Forms.dll', '/out:' + str(stage / 'Empire.exe'),
             '/win32icon:' + str(root / 'src/empire/desktop/assets/empire.ico'), str(inputs[0])],
        ]
        for command in commands:
            subprocess.run(command, cwd=root, check=True, **lock.child_options())
        if before != {str(p.relative_to(root)): sha256(p) for p in inputs}:
            raise RuntimeError('Launcher inputs changed during build')
        if not config.exists():
            # Preserve byte-for-byte; never emit configuration content or credentials.
            with config.open('xb') as output:
                output.write(source.read_bytes())
        shutil.copy2(stage / 'Empire.exe', destination / 'Empire.exe')
        write_json(stage / 'report.json', dict(kind='local-development-launcher', inputs=before,
                   executable_sha256=sha256(destination / 'Empire.exe'),
                   configuration_copied_equal=config.read_bytes() == source.read_bytes(),
                   portable=False, original_executable_replaced=False))
        print('Local double-click launcher: ' + str(destination / 'Empire.exe'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-source', required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], Path(args.config_source).resolve())
