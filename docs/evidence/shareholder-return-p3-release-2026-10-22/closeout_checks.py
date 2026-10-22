"""Record final documentation checks, preserving command output and exit status."""
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
PY = str(ROOT / '.venv/Scripts/python.exe')
commands = [
    ('closeout-generate', [PY, 'scripts/documentation_build.py', 'generate']),
    ('closeout-review', [PY, 'scripts/documentation_contract.py', 'review', '--note',
     'P3发布结案：复核回购终批全热证明与事务恢复说明、实际容量绑定、正式包身份、真实桌面关开、配置保存及原B项/P2/历史信号与累计注销限制；只更新验收账本和实现状态，产品正文与行为未再变更。']),
    ('closeout-documentation', [PY, 'scripts/verify_documentation.py']),
    ('closeout-documentation-tests', [PY, '-X', 'utf8', '-m', 'pytest',
     'tests/test_documentation_build.py', 'tests/test_documentation_review.py',
     'tests/test_documentation_contracts.py', 'tests/test_documentation_sources.py',
     'tests/test_storage_help.py', '-q', '--basetemp=build/pytest-p3-closeout-docs',
     '--junitxml=build/returns-p3-release-20261022/closeout-documentation-tests.xml']),
]
results = []
for name, command in commands:
    item = dict(command=command, started_at=datetime.now(UTC).isoformat())
    with (OUT / (name + '.log')).open('xb') as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    item.update(returncode=result.returncode, finished_at=datetime.now(UTC).isoformat())
    results.append(item)
    (OUT / 'closeout-checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    print(name, result.returncode, flush=True)
    if result.returncode:
        sys.exit(result.returncode)
