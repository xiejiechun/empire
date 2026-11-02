import pytest

from scripts.retire_unused_sprint_history import RETIRED, validate_unused


def test_only_an_unused_idle_project_can_be_retired():
    control = dict(jobs={RETIRED: dict(active=None, last_status='idle')}, history=[])
    values = dict(states=0, settings=0, keys=[], pending=0)
    validate_unused(control, **values)
    for key, value in dict(states=1, settings=1, keys=['checkpoint'], pending=1).items():
        with pytest.raises(ValueError, match='拒绝'):
            validate_unused(control, **{**values, key: value})
    for job in (dict(active={'run_id': 'x'}, last_status='idle'), dict(active=None, last_status='complete')):
        with pytest.raises(ValueError, match='拒绝'):
            validate_unused(dict(jobs={RETIRED: job}), **values)
    with pytest.raises(ValueError, match='拒绝'):
        validate_unused(dict(history=[{'task_id': RETIRED}]), **values)
