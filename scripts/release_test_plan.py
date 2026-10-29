"""Explicit whole-file release sampling; never attest unexecuted tests."""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

import pytest


def select(nodes, files):
    if not isinstance(files, list) or not files or len(files) != len(set(files)):
        raise ValueError('Test plan must contain unique complete test files')
    available = {node.split('::')[0] for node in nodes}
    if any(not isinstance(p, str) or not p.startswith('tests/') or not p.endswith('.py')
           or '..' in Path(p).parts or p not in available for p in files):
        raise ValueError('Test plan contains an unknown or unsafe test file')
    selected = [node for node in nodes if node.split('::')[0] in files]
    # Keep directory collectors contiguous: interleaved explicit paths can lose
    # a later directory's autouse conftest fixtures during pytest collection.
    return dict(mode='explicit_sample', files=sorted(files), total_count=len(nodes),
                selected_count=len(selected), fraction=len(selected) / len(nodes),
                whole_files=True, untested_count=len(nodes) - len(selected))


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    nodes = []
    class Inventory:
        def pytest_collection_finish(self, session):
            nodes.extend(item.nodeid for item in session.items)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = pytest.main(['--collect-only', '-q'], plugins=[Inventory()])
    if code != 0:
        raise RuntimeError('Test collection failed: ' + output.getvalue()[-8000:])
    result = select(nodes, json.loads(Path(args.plan).read_text(encoding='utf-8')))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Explicit sample: {result['selected_count']}/{result['total_count']} tests ({result['fraction']:.2%})")


if __name__ == '__main__':
    main()
