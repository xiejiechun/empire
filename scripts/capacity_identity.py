"""Freeze benchmark runtime inputs before work and reject changed inputs."""
import hashlib
import importlib.metadata
import os
import platform
from pathlib import Path


def inputs(source):
    root = Path(__file__).resolve().parents[1]
    files = set(source.resolve().rglob('*.py'))
    files.update((root / 'scripts').glob('*.py'))
    files.update((root / 'tests').rglob('*.py'))
    files.update(root / name for name in ('requirements.lock', 'pyproject.toml',
                 'sql/schema.sql', 'sql/business-schema.json', 'config/app.example.toml'))
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}


def environment():
    return dict(platform=platform.platform(), python=platform.python_version(),
        processor=os.environ.get('PROCESSOR_IDENTIFIER', platform.processor()), cpu_count=os.cpu_count(),
        dependencies={name: importlib.metadata.version(name) for name in
                      ('httpx', 'httpcore', 'anyio', 'sniffio', 'pydantic', 'redis', 'sqlalchemy', 'pymysql')})
