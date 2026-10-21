"""Read-only business integrity retained release evidence audit (no business operations)."""
import sys
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = Path(__file__).resolve().parent
RUN = sys.argv[1]
RELEASE = ROOT / 'build/releases' / RUN


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = FOLDER / 'release-audit.json'
    assert not out.exists()
    journal_path = RELEASE / 'publication.json'
    journal = json.loads(journal_path.read_text('utf8'))
    assert journal['state'] == 'committed' and journal['passed'] is True
    assert journal['manifest']['commit'] == sys.argv[2]
    assert journal['manifest']['dirty'] is False
    inputs = json.loads((RELEASE / 'inputs.json').read_text('utf8'))
    assert journal['source_sha256'] == inputs['sha256']
    mismatches = [p for p, digest in inputs['files'].items() if sha(ROOT / p) != digest]
    assert not mismatches, mismatches
    retained = []
    for original, item in journal['generated_outputs'].items():
        path = Path(item['path'])
        assert path.is_relative_to(RELEASE / 'evidence')
        assert sha(path) == item['sha256'], original
        retained.append({'original': original, 'path': str(path.relative_to(ROOT)), 'sha256': item['sha256']})
    steps = []
    for i in range(1, 26):
        path = RELEASE / f'evidence/step-{i:03}.json'
        step = json.loads(path.read_text('utf8'))
        expected = 1 if i == 23 else 0
        assert step['output_complete'] is True and step['returncode'] == expected
        log = path.with_suffix('.log')
        if i == 23:
            assert 'config.toml' in log.read_text('utf8')
        steps.append({'step': i, 'expected_exit': expected, **step, 'log_sha256': sha(log)})
    junit_path = RELEASE / 'evidence/release-tests.xml'
    tree = ET.parse(junit_path)
    cases = tree.findall('.//testcase')
    failed = [c.attrib for c in cases if c.find('failure') is not None or c.find('error') is not None]
    skips = [{'class': c.get('classname'), 'name': c.get('name'), 'message': c.find('skipped').get('message')} for c in cases if c.find('skipped') is not None]
    assert not failed and len(cases) > 0 and len(skips) == 5
    assert all('test_state_unit_isolated' in c['class'] and 'opt-in' in c['message'] for c in skips)
    report = {
        'record_kind': 'read_only_release_evidence_audit',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'release_id': RUN, 'manifest': journal['manifest'],
        'publication_sha256': sha(journal_path),
        'exe_sha256': journal['executable_sha256'],
        'installed_tree_sha256': journal['candidate_sha256'],
        'input_files_rechecked': len(inputs['files']), 'input_mismatches': mismatches,
        'retained_outputs': retained, 'steps': steps,
        'junit': {'path': str(junit_path.relative_to(ROOT)), 'sha256': sha(junit_path),
                  'total': len(cases), 'passed': len(cases)-len(skips), 'failed': failed, 'skips': skips},
        'actual_desktop': 'in_progress_separate_observations',
    }
    with out.open('x', encoding='utf8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'release_id': RUN, 'checked_inputs': len(inputs['files']),
                      'retained_outputs': len(retained), 'passed_tests': len(cases)-len(skips),
                      'skipped': len(skips), 'steps_checked': len(steps)}))


if __name__ == '__main__':
    main()

