"""Bind complete pytest results to the exact source checked by the release gate."""
import argparse
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from empire.core.preparation_release import source_digest

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=('begin', 'finish', 'package'))
args = parser.parse_args()
folder = root / 'build/generated'
folder.mkdir(parents=True, exist_ok=True)
target = folder / 'preparation-release.json'
baseline = folder / 'preparation-source.json'
digest = source_digest(root)
if args.action == 'begin':
    baseline.write_text(json.dumps({'sha256': digest}), encoding='utf-8')
    target.write_text(json.dumps({'schema': 1, 'passed': False}), encoding='utf-8')
elif args.action == 'finish':
    if json.loads(baseline.read_text(encoding='utf-8'))['sha256'] != digest:
        raise RuntimeError('Source changed during tests; rerun the release gate')
    cases = []
    for case in ET.parse(root / 'build/release-tests.xml').iter('testcase'):
        status = 'passed'
        for child in case:
            if child.tag in ('failure', 'error', 'skipped'):
                status = child.tag
        cases.append({'module': case.attrib['classname'], 'name': case.attrib['name'], 'status': status})
    if not cases or any(c['status'] in ('failure', 'error') for c in cases):
        raise RuntimeError('Cannot attest failing or empty test suite')
    target.write_text(json.dumps({'schema': 1, 'passed': True, 'source_sha256': digest,
        'checked_at': datetime.now(UTC).isoformat(), 'cases': cases}, ensure_ascii=False), encoding='utf-8')
else:
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        value = {}
    if value.get('source_sha256') != digest:
        target.write_text(json.dumps({'schema': 1, 'passed': False}), encoding='utf-8')
