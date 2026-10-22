"""Actual documentation-only validation commands and exit codes for this resource update."""
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'AGENTS.md').is_file())
OUT = Path(__file__).parent
phase = sys.argv[1]
commands = [
    ('generate', [sys.executable, '-X', 'utf8', 'scripts/documentation_build.py', 'generate']),
    ('review', [sys.executable, '-X', 'utf8', 'scripts/documentation_contract.py', 'review', '--note',
                '仅说明资源同步：逐字对照确认仅数据准备、区间名义现金股息率两主题差异；修正P3状态及条件阻断，保留来源限制、O7/O8暂缓；按纯正文流程更新外置聚合物，未重建EXE或修改业务实现。']),
    ('verify', [sys.executable, '-X', 'utf8', 'scripts/verify_documentation.py']),
    ('implementation-unchanged', ['git', 'diff', '--exit-code', '6808f85', '--',
        'src/**/*.py', 'scripts', 'tests', 'sql', 'Empire.spec', 'verify-release.ps1']),
    ('whitespace', ['git', 'diff', '--check']),
]
results = []
for label, args in commands:
    started = datetime.now(UTC).isoformat()
    t = time.perf_counter()
    p = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (OUT / f'{phase}-{label}.log').write_bytes(p.stdout)
    results.append(dict(label=label, command=args, at=started, seconds=time.perf_counter() - t,
                        exit_code=p.returncode))
    (OUT / f'{phase}-checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    print(label, p.returncode, p.stdout.decode('utf8', errors='replace')[-1600:], flush=True)
    if p.returncode:
        sys.exit(p.returncode)
