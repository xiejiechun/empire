"""Source-bound test evidence. Existence of a test file is not a passing result."""
import hashlib
import json
import sys
from pathlib import Path


def source_digest(root):
    paths = []
    for folder in ('src', 'tests', 'scripts', 'sql', 'config'):
        paths.extend(p for p in (root / folder).rglob('*') if p.is_file()
                     and p.suffix in {'.py', '.sql', '.toml', '.js', '.json', '.md', '.png', '.ico', '.svg'}
                     and '__pycache__' not in p.parts and p.name != 'local.toml')
    paths.extend(root / name for name in ('requirements.lock', 'pyproject.toml', 'Empire.spec',
                                         'build.ps1', 'verify-release.ps1'))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_evidence(root=None):
    root = root or Path(__file__).resolve().parents[3]
    packaged = getattr(sys, 'frozen', False)
    target = (Path(__file__).resolve().parents[1] / 'preparation-release.json' if packaged
              else root / 'build/generated/preparation-release.json')
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
        if (value.get('schema') != 1 or value.get('passed') is not True
                or not isinstance(value.get('cases'), list) or not value['cases']
                or not isinstance(value.get('checked_at'), str)
                or not isinstance(value.get('source_sha256'), str)):
            return {}, '没有有效的专项测试证据；执行正式发布门禁'
        for case in value['cases']:
            if (not isinstance(case, dict) or not isinstance(case.get('module'), str)
                    or not isinstance(case.get('name'), str)
                    or case.get('status') not in {'passed', 'skipped', 'failure', 'error'}):
                return {}, '测试证据损坏；执行正式发布门禁'
        if not packaged and value['source_sha256'] != source_digest(root):
            return {}, '代码/测试已改变，既有测试证据已失效；重新执行发布门禁'
        return value, ''
    except (OSError, ValueError, KeyError, TypeError):
        return {}, '尚无当前版本测试证据；执行正式发布门禁'


def test_evidence(value, paths):
    if not paths:
        return False, '尚未登记专项测试'
    selected = []
    for path in paths:
        module = path.removesuffix('.py').replace('/', '.')
        cases = [c for c in value.get('cases', [])
                 if c['module'] == module or c['module'].startswith(module + '.')]
        if not cases or any(c['status'] != 'passed' for c in cases):
            return False, f'{path}：缺少全部通过的执行证据（跳过不算通过）'
        selected.extend(cases)
    return True, f"{len(selected)} 项测试通过；{value['checked_at']}；" + '、'.join(paths)
