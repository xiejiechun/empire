import hashlib
import json

import pytest

from scripts.capacity_display_names import equivalent, preserved_binding

BEFORE = "tasks = [TaskContribution(item[2], item[0] + '（通达信）', 'collector', 'tdx', interval_seconds=86400)]"
AFTER = BEFORE.replace("item[0] + '（通达信）'", 'item[0]')


def test_only_pure_platform_suffix_can_reuse_capacity():
    assert equivalent(BEFORE, AFTER)
    assert not equivalent(BEFORE, BEFORE)


@pytest.mark.parametrize('changed', [
    AFTER.replace('86400', '1'), AFTER.replace("'tdx'", "'other'"),
    AFTER.replace('item[0]', 'read_source()'),
    AFTER.replace('item[2]', 'item[3]'),
    AFTER + '\nremove_business_data()\n',
])
def test_business_changes_and_side_effects_are_not_label_changes(changed):
    assert not equivalent(BEFORE, changed)


def test_proof_keeps_old_checksum_and_requires_reviewed_files(tmp_path):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'before.txt').write_text(BEFORE, encoding='utf8')
    (tmp_path / 'bundle.py').write_text(AFTER, encoding='utf8')
    (tmp_path / 'design.md').touch()
    (tmp_path / 'test.py').touch()
    proof = {'schema': 1, 'bindings': {'bundle.py': {
        'before': 'before.txt', 'design': 'design.md', 'tests': ['test.py']}}}
    (tmp_path / 'docs/capacity-display-names.json').write_text(json.dumps(proof))
    checksum = hashlib.sha256(BEFORE.encode()).hexdigest()
    assert preserved_binding(tmp_path, 'bundle.py', checksum)
    assert not preserved_binding(tmp_path, 'other.py', checksum)
    assert not preserved_binding(tmp_path, 'bundle.py', '0' * 64)
    (tmp_path / 'test.py').unlink()
    with pytest.raises(ValueError, match='baseline/design/tests'):
        preserved_binding(tmp_path, 'bundle.py', checksum)
