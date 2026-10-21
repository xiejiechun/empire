"""Run the installed, published binary read-only from another cwd."""
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
EXE = ROOT / 'dist/Empire/Empire.exe'
RELEASE = ROOT / 'build/releases/4c672429732f48669159d410a91917d9'
TARGET = OUT / 'installed-cli-audit.json'
assert not TARGET.exists()
journal = json.loads((RELEASE / 'publication.json').read_text('utf8'))
assert journal['state'] == 'committed' and journal['passed'] is True
assert hashlib.sha256(EXE.read_bytes()).hexdigest() == journal['executable_sha256']
report = dict(at=datetime.now(UTC).isoformat(), release_id=RELEASE.name,
              executable_sha256=journal['executable_sha256'], cwd='C:\\Windows', runs=[])
commands = [
    ('connections', ['doctor']),
    ('quote-project', ['doctor','--project','kaipanla-quote','--security','000001.SZ','--date','2026-10-20']),
    ('dividends-project', ['doctor','--project','tdx-dividends','--security','000001.SZ','--date','2026-10-20']),
    ('suspension-project', ['doctor', '--project', 'tdx-suspensions',
                            '--error-id', '38622b7215a44fe4a5224031bdf4d963',
                            '--security', '603517.SH', '--date', '2026-10-19']),
]
for name, args in commands:
    run = subprocess.run([str(EXE), *args], cwd='C:\\Windows',
                         capture_output=True, encoding='utf8', errors='replace')
    log = OUT / (name + '-installed.log')
    with log.open('x', encoding='utf8') as stream:
        stream.write(run.stdout)
        stream.write(run.stderr)
    report['runs'].append(dict(command=[str(EXE), *args], exit_code=run.returncode,
                               log=str(log.relative_to(ROOT)),
                               log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
    if name == 'connections':
        data = json.loads(run.stdout)
        report['connections'] = data
        assert run.returncode == 0 and all(data[k]['connected'] for k in ('mysql', 'redis'))
    else:
        assert run.returncode in (0, 2), run.returncode
with TARGET.open('x', encoding='utf8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
print(json.dumps({'release_id': RELEASE.name, 'runs': report['runs']}, ensure_ascii=False))
