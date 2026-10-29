import json
from copy import deepcopy
from pathlib import Path

import pytest

from empire.plugins.collection.rules import collection_rules, validate_rules, verify_registry
from scripts.documentation_contract import declarations

ROOT = Path(__file__).resolve().parents[1]


def test_rules_cover_real_registry_and_sql():
    manager, _, tasks = declarations(ROOT)
    coverage = json.loads((ROOT / 'docs/documentation-coverage.json').read_text(encoding='utf-8'))
    from empire.plugins.ui.help_content import topics
    verify_registry(manager, tasks, coverage['storage']['mysql'], topics())
    bad = dict(tasks)
    bad['new-unregistered-source'] = next(iter(tasks.values()))
    with pytest.raises(ValueError, match='覆盖'):
        verify_registry(manager, bad, coverage['storage']['mysql'], topics())


@pytest.mark.parametrize('field', ['initial', 'incremental', 'start', 'end', 'job_key', 'tables'])
def test_incomplete_rule_rejected(field):
    rules = deepcopy(collection_rules())
    rules['sina-news'][field] = ''
    with pytest.raises(ValueError):
        validate_rules(dict(schema=1, tasks=rules))


def test_request_contracts_match_real_source_parameters():

    from empire.features.performance.source import params
    rules = collection_rules()
    for kind in ('earnings_forecast', 'earnings_quick', 'earnings_disclosure', 'earnings_report'):
        rule = rules['tdx-' + kind.replace('_', '-')]
        actual = params(kind, '2026-06-30')
        declared = rule['requests'][-1]['parameters']
        assert len(declared) == len(actual)
        for p, value in zip(declared, actual, strict=True):
            if p['value'] not in ('YYYY-MM-DD', '空字符串'):
                assert p['value'] == value




def test_same_count_wrong_dataset_is_rejected():
    manager, _, tasks = declarations(ROOT)
    contribution = next(c for c in manager.entries['dataset.astock'].plugin.contributions
                        if 'sina-news' in c.projects.values())
    original = contribution.mapping.DATASETS
    contribution.mapping.DATASETS = {'incorrect.dataset'}
    try:
        from empire.plugins.ui.help_content import topics
        coverage = json.loads((ROOT / 'docs/documentation-coverage.json').read_text(encoding='utf-8'))
        with pytest.raises(ValueError, match='不一致'):
            verify_registry(manager, tasks, coverage['storage']['mysql'], topics())
    finally:
        contribution.mapping.DATASETS = original




def test_rule_storage_addresses_follow_config_without_leaking_credentials():
    from empire.plugins.collection.rules import rule_details
    cfg = {'redis': {'namespace': 'custom:test', 'password': 'REDIS_SECRET'},
           'mysql': {'database': 'custom_db', 'password': 'MYSQL_SECRET'}}
    import json
    for ident in collection_rules():
        value = rule_details(ident, cfg)
        s = value['storage']
        assert s['queue'] == 'custom:test:ingest'
        assert s['checkpoint'] == 'custom:test:checkpoint:' + value['job_key']
        assert s['database'] == 'custom_db'
        assert s['tables'] == value['tables']
        assert 'SECRET' not in json.dumps(value)
    financial = rule_details('ths-yuanhang-financial', cfg)['storage']
    assert financial['fingerprints'] == [
        'custom:test:archive:fingerprints:v1:ths_yuanhang_history_v2:ths_yuanhang:financial']
    pool = rule_details('ths-yuanhang-limit-up-pool', cfg)['storage']['intraday']
    assert pool['body'] == 'custom:test:yuanhang:intraday:limit_up_pool:snapshots:<version>'
    assert '不写 MySQL' in pool['note']
    assert rule_details('ths-yuanhang-reason', cfg)['storage']['intraday'] is None
    assert rule_details('unknown', cfg) is None
