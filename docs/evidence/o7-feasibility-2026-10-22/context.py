"""Record Git, unchanged product/package identity and the live application."""
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.release_identity import tree_inventory

results = []
for command in [
    ['git', 'rev-parse', 'HEAD'],
    ['git', '-c', 'http.proxy=http://127.0.0.1:7890', 'ls-remote', 'origin', 'refs/heads/main'],
    ['git', 'diff', '--exit-code', '6808f85188be0aae58c897b417e5819a9e6da529', '--',
     'src', 'scripts', 'tests', 'sql', 'config', 'Empire.spec', 'verify-release.ps1'],
    ['powershell.exe', '-NoProfile', '-Command',
     'Get-Process Empire -ErrorAction Stop | Select-Object Id,Path,StartTime | ConvertTo-Json -Compress'],
]:
    process = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    results.append(dict(command=command, exit_code=process.returncode,
                        stdout=process.stdout.decode('utf8', errors='replace').strip(),
                        stderr=process.stderr.decode('utf8', errors='replace').strip()))
    assert process.returncode == 0
journal = json.loads((ROOT / 'build/releases/3892410b3e6a48858002a318bee648d5/publication.json').read_text('utf8'))
exe_hash = hashlib.sha256((ROOT / 'dist/Empire/Empire.exe').read_bytes()).hexdigest()
tree_hash = tree_inventory(ROOT / 'dist/Empire')['sha256']
assert exe_hash == journal['executable_sha256']
assert tree_hash == journal['candidate_sha256']
result = dict(at=datetime.now(UTC).isoformat(), commands=results,
              release_id='3892410b3e6a48858002a318bee648d5', manifest=journal['manifest'],
              exe_sha256=exe_hash, tree_sha256=tree_hash)
(Path(__file__).parent / 'context.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print('Git/product/package/running process identity checked; current P3 package unchanged.')
