"""Keep actual commands, outputs and exit codes for this diagnostic delivery."""
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
commands = [
    ('preservation', [sys.executable, '-X', 'utf8', str(OUT / 'preservation.py')]),
    ('related', [sys.executable, '-X', 'utf8', '-m', 'pytest',
        'tests/test_tdx_additional_issues.py', 'tests/test_tdx_rights_issues.py',
        'tests/test_tdx_issue_details.py', 'tests/test_capital_scope.py',
        'tests/test_capital_preparation.py', 'tests/test_capital_recovery.py',
        'tests/test_dividend_distribution.py', 'tests/test_dividend_yield.py',
        'tests/test_repurchases.py', '-q', '--basetemp=build/pytest-o7-contract-audit',
        '--junitxml=build/returns-o7-20261022/related.xml']),
]
rows = []
for name, command in commands:
    started = datetime.now(UTC).isoformat()
    begin = time.perf_counter()
    with (OUT / (name + '.log')).open('wb') as output:
        process = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    rows.append(dict(name=name, command=command, started_at=started,
                     seconds=time.perf_counter() - begin, exit_code=process.returncode,
                     log=name + '.log'))
    (OUT / 'checks.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf8')
    print(name, 'exit', process.returncode, flush=True)
    if process.returncode:
        raise SystemExit(process.returncode)
