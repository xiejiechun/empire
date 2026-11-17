import copy
from pathlib import Path

import pytest

from scripts.assembly_contract import compare

ROOT = Path(__file__).resolve().parents[1]


def pair(group, field):
    before = {'schema': 1, 'semantic': {
        'plugins': {}, 'tasks': {}, 'datasets': {}, 'pages': {}, 'preparation': {}},
        'bindings': {'plugins': {}, 'datasets': {}, 'pages': {}, 'tests': {}}}
    before['semantic'][group]['example'] = {field: '旧名称', 'other': 'preserve'}
    after = copy.deepcopy(before)
    after['semantic'][group]['example'][field] = '新名称'
    change = {'path': f'semantic.{group}.example.{field}', 'before': '旧名称', 'after': '新名称',
              'design': 'docs/collector-task-names.md', 'tests': ['tests/test_assembly_display_names.py']}
    return before, after, change


@pytest.mark.parametrize(('group', 'field'), [('tasks', 'name'), ('pages', 'title')])
def test_names_need_exact_before_after_without_allowing_other_changes(group, field):
    before, after, change = pair(group, field)
    assert compare(before, after, {}, ROOT) == [change['path']]
    assert not compare(before, after, {}, ROOT, [change])
    after['semantic'][group]['example']['other'] = 'changed'
    assert compare(before, after, {}, ROOT, [change]) == [f'semantic.{group}.example.other']


@pytest.mark.parametrize('side', ['before', 'after'])
def test_stale_name_approvals_are_rejected(side):
    before, after, change = pair('tasks', 'name')
    change[side] = 'incorrect'
    with pytest.raises(ValueError, match='stale'):
        compare(before, after, {}, ROOT, [change])


@pytest.mark.parametrize(('group', 'field'), [('tasks', 'source_name'), ('pages', 'source')])
def test_name_review_does_not_authorize_source_changes(group, field):
    before, after, change = pair(group, field)
    with pytest.raises(ValueError, match='Only explicit'):
        compare(before, after, {}, ROOT, [change])
