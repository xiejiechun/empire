"""Record real documentation command results and archive an explicit allowlist."""
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
commands = [
    ('generate', [sys.executable, 'scripts/documentation_build.py', 'generate']),
    ('review', [sys.executable, 'scripts/documentation_contract.py', 'review', '--note',
        'O7正式输入调查：逐键核实增发与配股，记录实施、股份口径及归因契约不足；无真实计算正例，'
        '按用户要求保持O7未实施未验收。未改产品正文/行为/数据路径，P3及原B/P2失败保持。']),
    ('documentation', [sys.executable, 'scripts/verify_documentation.py']),
    ('documentation-tests', [sys.executable, '-X', 'utf8', '-m', 'pytest',
        'tests/test_documentation_build.py', 'tests/test_documentation_review.py',
        'tests/test_documentation_contracts.py', 'tests/test_documentation_sources.py',
        'tests/test_storage_help.py', '-q', '--basetemp=build/pytest-o7-contract-docs',
        '--junitxml=build/returns-o7-20261022/documentation.xml']),
    ('diff', ['git', 'diff', '--check']),
]
results = []
for name, command in commands:
    began = time.perf_counter()
    with (OUT / (name + '.log')).open('wb') as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    results.append(dict(name=name, command=command, at=datetime.now(UTC).isoformat(),
                        exit_code=result.returncode, seconds=time.perf_counter()-began))
    (OUT / 'documentation-checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    print(name, result.returncode, flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)

target = ROOT / 'docs/evidence/shareholder-return-o7-2026-10-22'
target.mkdir(exist_ok=True)
names = ['audit.py', 'input-audit.json', 'preservation.py', 'preservation.json',
    'run_checks.py', 'checks.json', 'preservation.log', 'related.log', 'related.xml',
    'doctor-tdx-additional-issues.json', 'doctor-tdx-additional-issues.log',
    'doctor-tdx-rights-issues.json', 'doctor-tdx-rights-issues.log', 'closeout.py',
    'documentation-checks.json', 'documentation.xml', 'initial-documentation.log',
    'initial-documentation-checks.json', 'initial-closeout.py'] + [n + '.log' for n, _ in commands]
inventory = {}
for name in names:
    src, dest = OUT / name, target / name
    assert src.is_file()
    if dest.exists():
        assert src.read_bytes() == dest.read_bytes()
    else:
        shutil.copyfile(src, dest)
    inventory[name] = dict(bytes=dest.stat().st_size, sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
(target / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf8')
