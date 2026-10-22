"""One-off documentation-only deployment evidence; never changes code or configuration."""
import difflib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'AGENTS.md').is_file())
OUT = Path(__file__).parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]
from documentation_build import check_generated
from empire.plugins.ui.help_content import parse_articles
from release_identity import sha256, tree_inventory
from release_lock import ReleaseLock

PACKAGE = ROOT / 'dist/Empire'
RESOURCE = Path('_internal/empire/plugins/ui/storage_reference.md')
SOURCE = ROOT / 'src/empire/plugins/ui/storage_reference.md'
JOURNAL = ROOT / 'build/releases/3892410b3e6a48858002a318bee648d5/publication.json'


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding='utf8').strip()


def snapshot():
    files = {
        'root_config': ROOT / 'config.toml',
        'installed_config': PACKAGE / 'config.toml',
        'plugin_preferences': Path(os.environ['LOCALAPPDATA']) / 'Empire/plugin-state.json',
    }
    processes = json.loads(command('powershell', '-NoProfile', '-Command',
        "ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter \"name='Empire.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,ThreadCount)"))
    return dict(at=datetime.now(UTC).isoformat(), head=command('git', 'rev-parse', 'HEAD'),
                tree=tree_inventory(PACKAGE), source_sha256=sha256(SOURCE),
                preserved={k: sha256(v) for k, v in files.items()},
                processes=processes)


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def main():
    mode = sys.argv[1]
    check_generated(ROOT)
    if mode == 'compare':
        before = snapshot()
        journal = json.loads(JOURNAL.read_text(encoding='utf8'))
        assert before['tree']['sha256'] == journal['candidate_sha256'], 'Installed package differs from journal'
        old = (PACKAGE / RESOURCE).read_bytes()
        new = SOURCE.read_bytes()
        (OUT / 'previous-storage_reference.txt').write_bytes(old)
        previous = {a.title: a for a in parse_articles(old.decode('utf8'))}
        current = {a.title: a for a in parse_articles(new.decode('utf8'))}
        changed = [t for t in previous.keys() | current.keys() if previous.get(t) != current.get(t)]
        before['changed_topics'] = sorted(changed)
        before['original_release'] = journal['run_id']
        write('before.json', before)
        write('installed-versus-current.json', dict(unified_diff=''.join(difflib.unified_diff(
            old.decode('utf8').splitlines(keepends=True), new.decode('utf8').splitlines(keepends=True),
            fromfile='installed-before', tofile='source-3e7a3ac'))))
        print(json.dumps({k: v for k, v in before.items() if k != 'tree'}, ensure_ascii=False, indent=2))
        print('installed_tree_sha256', before['tree']['sha256'])
        return
    if mode == 'sync':
        with ReleaseLock(ROOT):
            before = json.loads((OUT / 'before.json').read_text(encoding='utf8'))
            closed = snapshot()
            write('closed.json', closed)
            assert not any(p['ThreadCount'] > 0 for p in closed['processes']), 'Empire still running'
            assert closed['head'] == before['head'], 'HEAD changed'
            assert closed['tree'] == before['tree'], 'Package changed'
            assert closed['preserved'] == before['preserved'], 'Configuration/preferences changed'
            assert closed['source_sha256'] == before['source_sha256'], 'Help source changed'
            target = PACKAGE / RESOURCE
            temporary = target.with_name(target.name + '.help-sync.tmp')
            with temporary.open('xb') as output:
                output.write(SOURCE.read_bytes())
                output.flush()
                os.fsync(output.fileno())
            assert sha256(temporary) == before['source_sha256']
            temporary.replace(target)
            after = snapshot()
            write('after.json', after)
            changed = sorted(k for k in before['tree']['files'].keys() | after['tree']['files'].keys()
                             if before['tree']['files'].get(k) != after['tree']['files'].get(k))
            assert changed == [RESOURCE.as_posix()], changed
            assert after['preserved'] == before['preserved']
            assert (PACKAGE / RESOURCE).read_bytes() == SOURCE.read_bytes()
            write('deployment.json', dict(at=after['at'], method='external-help-only; EXE not rebuilt',
                rule='docs/documentation-maintenance.md:104',
                source_commit=before['head'], original_release=before['original_release'],
                changed_files=changed, previous_tree_sha256=before['tree']['sha256'],
                current_tree_sha256=after['tree']['sha256'], resource_sha256=sha256(target),
                exe_sha256=sha256(PACKAGE / 'Empire.exe')))
            print((OUT / 'deployment.json').read_text(encoding='utf8'))
        return
    if mode == 'reopened':
        before = json.loads((OUT / 'before.json').read_text(encoding='utf8'))
        after = json.loads((OUT / 'after.json').read_text(encoding='utf8'))
        current = snapshot()
        write('reopened.json', current)
        assert current['tree'] == after['tree']
        assert current['preserved'] == before['preserved']
        assert any(p['ThreadCount'] > 0 for p in current['processes'])
        assert (PACKAGE / RESOURCE).read_bytes() == SOURCE.read_bytes()
        print('Verified reopened package, external help bytes, unchanged EXE/config/preferences')
        return
    raise ValueError(mode)


if __name__ == '__main__':
    main()
