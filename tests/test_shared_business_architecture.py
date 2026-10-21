"""Public APIs do not permit infrastructure to import a concrete business."""
from pathlib import Path

import pytest

from scripts.architecture_contract import analyze


@pytest.mark.parametrize('owner,role', [
    ('ui_components', 'shared_ui'),
])
@pytest.mark.parametrize('target_role', ['contract', 'api', 'query'])
@pytest.mark.parametrize('statement', [
    'from empire.features.sample.api import read',
    'import empire.features.sample.api as api',
    'from ..features.sample.api import read',
    'from ..features.sample import api',
    'def delayed():\n    from empire.features.sample.api import read',
])
def test_shared_imports_of_business_fail_even_for_public_symbols(tmp_path, owner, role, target_role, statement):
    api = tmp_path / 'src/empire/features/sample/api.py'
    caller = tmp_path / 'src/empire/common/service.py'
    api.parent.mkdir(parents=True)
    caller.parent.mkdir(parents=True)
    api.write_text('def read(): return 1\n', 'utf8')
    caller.write_text(statement, 'utf8')
    policy = dict(schema=1, owners={owner: {'kind': 'platform'}, 'sample': {'kind': 'business'}},
        module_groups=[
            dict(modules=['empire.common.service'], owner=owner, role=role, reason='Shared runtime'),
            dict(modules=['empire.features.sample.api'], owner='sample', role=target_role,
                 public_symbols=['read'], reason='Business API'),
        ], feature_layouts=[], debt=[])
    report = analyze(tmp_path, policy)
    assert not report['errors']
    expected = 'shared_to_business'
    assert expected in {item['rule'] for item in report['new_debt']}


@pytest.mark.parametrize('role', ['composition', 'dataset_registry'])
def test_only_explicit_composition_roles_may_bind_business_handlers(tmp_path, role):
    sources = {'empire/features/sample/api.py': 'def read(): return 1\n',
               'empire/assembly.py': 'from empire.features.sample.api import read\n'}
    for name, text in sources.items():
        path = tmp_path / 'src' / Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, 'utf8')
    policy = dict(schema=1, owners={'application': {'kind': 'platform'}, 'sample': {'kind': 'business'}},
        module_groups=[
            dict(modules=['empire.assembly'], owner='application', role=role, reason='Reviewed application composition'),
            dict(modules=['empire.features.sample.api'], owner='sample', role='api', reason='Business API'),
        ], feature_layouts=[], debt=[])
    assert analyze(tmp_path, policy)['passed']
