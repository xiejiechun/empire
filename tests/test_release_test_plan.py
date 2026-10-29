import pytest

from scripts.release_test_plan import select


def test_sample_selects_whole_files_and_reports_untested_scope():
    result = select(['tests/a.py::test_a[1]', 'tests/a.py::test_a[2]', 'tests/b.py::test_b'], ['tests/a.py'])
    assert result['selected_count'] == 2 and result['total_count'] == 3
    assert result['untested_count'] == 1 and result['whole_files']


@pytest.mark.parametrize('files', [[], ['tests/a.py', 'tests/a.py'], ['tests/../private.py']])
def test_sample_rejects_empty_duplicate_and_unknown_files(files):
    with pytest.raises(ValueError):
        select(['tests/a.py::test_a'], files)


def test_sample_groups_directory_collectors_without_omitting_files():
    files = ['tests/integration/a.py', 'tests/unit.py', 'tests/integration/b.py']
    result = select([p + '::test_a' for p in files], files)
    assert result['files'] == sorted(files)
    assert result['selected_count'] == 3
