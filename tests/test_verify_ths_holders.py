"""Holder verification counterexamples without external services or source requests."""
import asyncio
import copy
import importlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from empire.plugins.collection.unit_prefetch import DeferredResponse


def test_cli_initializes_and_retains_qt_for_real_shared_ths_token():
    code = '''
import sys
sys.path.insert(0, 'scripts')
import verify_ths_holders as module
from PySide6.QtCore import QCoreApplication
from empire.plugins.collectors.ths_session import ThsSession
async def checked(*args, **kwargs):
    assert QCoreApplication.instance() is not None
    headers = ThsSession().headers('https://basic.10jqka.com.cn/601139/holder.html')
    assert headers and headers.get('Cookie')
    return True
module.verification.verify = checked
raise SystemExit(module.main(['--test-mysql-settings', 'unused-private.json',
                             '--output', 'build/unused-test-output.json', '--proxy-only']))
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'PASS'


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('verify_ths_holders')


def source_result(verifier, code='601139.SH', gaps=None):
    return {kind: [] for kind in verifier.KINDS}, datetime.now(UTC), 'https://basic.10jqka.com.cn/' + code[:6] + '/holder.html', gaps or []


def gap():
    return dict(kind='bond_holders', report_date='2023-12-31', source_panel='b0her_1',
                reason='instrument_name_missing')


@pytest.mark.asyncio
async def test_deferred_observation_preserves_response_reservation_and_cleanup(verifier):
    raw = source_result(verifier)
    response = Mock()
    deferred = DeferredResponse(response, AsyncMock(return_value=raw))
    original = AsyncMock(return_value=deferred)
    stock = dict(unified_code='601139.SH')
    summaries, reservation = {}, object()
    wrapped = verifier.observe_fetch(SimpleNamespace(fetch=original), [stock], summaries)
    returned = await wrapped(stock, reservation=reservation, defer=True)
    assert returned is deferred and not summaries
    original.assert_awaited_once_with(stock, reservation=reservation, defer=True)
    assert await returned.consume() is raw
    assert summaries['601139.SH']['digest'] == verifier.digest(raw[0])
    response.close.assert_not_called()
    returned.close()
    returned.close()
    response.close.assert_called_once()


@pytest.mark.asyncio
async def test_cancelled_consumer_is_not_swallowed_or_double_closed(verifier):
    response = Mock()
    deferred = DeferredResponse(response, AsyncMock(side_effect=asyncio.CancelledError))
    stock = dict(unified_code='601139.SH')
    wrapped = verifier.observe_fetch(SimpleNamespace(fetch=AsyncMock(return_value=deferred)), [stock], {})
    result = await wrapped(stock, defer=True)
    with pytest.raises(asyncio.CancelledError):
        await result.consume()
    response.close.assert_not_called()
    result.close()
    response.close.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_foreign_and_missing_sections_are_rejected(verifier):
    raw = source_result(verifier)
    collector = SimpleNamespace(fetch=AsyncMock(return_value=raw))
    stock = dict(unified_code='601139.SH')
    wrapped = verifier.observe_fetch(collector, [stock], {})
    assert await wrapped(stock) is raw
    with pytest.raises(ValueError, match='重复消费'):
        await wrapped(stock)
    with pytest.raises(ValueError, match='样本外'):
        await verifier.observe_fetch(collector, [dict(unified_code='601140.SH')], {})(stock)
    del raw[0]['bond_holders']
    with pytest.raises(ValueError, match='缺少持有人栏目'):
        await verifier.observe_fetch(collector, [stock], {})(stock)


@pytest.mark.asyncio
async def test_publish_observer_only_records_successful_formal_enqueue(verifier):
    stock, summaries, publications = dict(unified_code='601139.SH'), {}, {}
    raw = source_result(verifier)
    collector = SimpleNamespace(fetch=AsyncMock(return_value=raw),
                                publish=AsyncMock(return_value=dict(revision=1, cursor={'pages': 1})))
    await verifier.observe_fetch(collector, [stock], summaries)(stock)
    wrapped = verifier.observe_publish(collector, summaries, publications)
    state, cursor = dict(revision=0), dict(pages=1)
    assert await wrapped(state, cursor, stock['unified_code'], raw[0], None, raw[1], raw[2], []) == dict(revision=1, cursor={'pages': 1})
    assert publications[stock['unified_code']]['revision'] == 1
    collector.publish.assert_awaited_once_with(state, cursor, stock['unified_code'], raw[0], None, raw[1], raw[2], [])
    collector.publish.side_effect = RuntimeError('enqueue failed')
    fresh = {}
    with pytest.raises(RuntimeError, match='enqueue failed'):
        await verifier.observe_publish(collector, summaries, fresh)(state, cursor, stock['unified_code'], raw[0], None, raw[1], raw[2], [])
    assert not fresh
    with pytest.raises(ValueError, match='规范内容不同'):
        await verifier.observe_publish(collector, summaries, {})(state, cursor, stock['unified_code'], raw[0], None, raw[1], raw[2], [gap()])


async def evidence(verifier, with_gap):
    summaries = {}
    for security in ('601139.SH', '300398.SZ'):
        raw = source_result(verifier, security, [gap()] if with_gap and security == '300398.SZ' else [])
        stock = dict(unified_code=security)
        await verifier.observe_fetch(SimpleNamespace(fetch=AsyncMock(return_value=raw)), [stock], summaries)(stock)
    units = {}
    for security, value in summaries.items():
        units[security] = dict(contract=4, digest=value['digest'], count=0,
            source_gaps=value['gaps'], source_gaps_digest=value['gaps_digest'], observed_at=value['observed_at'],
            kinds={kind: dict(contract=4, observed_at=value['observed_at'], count=0,
                digest=value['kinds'][kind]['digest'], report_keys=[],
                availability='source_gap' if kind == 'bond_holders' and value['gaps'] else 'not_published')
                for kind in verifier.KINDS})
    manifest = verifier.expected_manifest(summaries)
    state = dict(contract_version=4, units=units)
    publications = {key: {} for key in summaries}
    cursor = dict(phase='fetch', index=0, source_gap='300398.SZ')
    if not with_gap:
        state['manifest'] = manifest
        publications['manifest'] = dict(manifest=manifest)
        cursor = dict(phase='complete')
    return summaries, state, cursor, publications


@pytest.mark.asyncio
async def test_gap_remains_in_sql_and_cursor_without_fabricated_manifest(verifier):
    summaries, state, cursor, publications = await evidence(verifier, True)
    gaps, _ = verifier.check_state(state, summaries, cursor, True, publications)
    assert gaps == {'300398.SZ': [gap()]}
    for changed in ({**cursor, 'phase': 'complete'}, {**cursor, 'index': 1}):
        with pytest.raises(ValueError, match='缺口被隐藏|连续断点'):
            verifier.check_state(state, summaries, changed, True, publications)
    for damage in ('drop_gap', 'pretend_unpublished', 'add_manifest'):
        bad = copy.deepcopy(state)
        if damage == 'drop_gap':
            bad['units']['300398.SZ']['source_gaps'] = []
        elif damage == 'pretend_unpublished':
            bad['units']['300398.SZ']['kinds']['bond_holders']['availability'] = 'not_published'
        else:
            bad['manifest'] = verifier.expected_manifest(summaries)
        with pytest.raises(ValueError):
            verifier.check_state(bad, summaries, cursor, True, publications)


@pytest.mark.asyncio
async def test_complete_manifest_uses_full_market_identity_and_exact_set(verifier):
    summaries, state, cursor, publications = await evidence(verifier, False)
    gaps, manifest = verifier.check_state(state, summaries, cursor, False, publications)
    assert not gaps and manifest['securities'] == ['300398.SZ', '601139.SH']
    bad = copy.deepcopy(state)
    bad['units']['300398.SH'] = bad['units'].pop('300398.SZ')
    with pytest.raises(ValueError, match='证券集合'):
        verifier.check_state(bad, summaries, cursor, False, publications)
    bad = copy.deepcopy(state)
    bad['manifest']['scope_hash'] = '0' * 64
    with pytest.raises(ValueError, match='manifest'):
        verifier.check_state(bad, summaries, cursor, False, publications)


def test_equal_counts_different_member_sets_are_detected(verifier):
    from empire.features.holders.source import parse
    from tests.test_ths_holders import STOCK, source

    first = parse(source(), 'top_holders', STOCK)
    changed_name = copy.deepcopy(first)
    changed_name[0]['members'][0]['holder_name'] = '另一位来源持有人'
    a = verifier.row_summary('top_holders', STOCK['unified_code'], first)
    b = verifier.row_summary('top_holders', STOCK['unified_code'], changed_name)
    assert a['count'] == b['count'] and a['report_keys'] == b['report_keys']
    assert a['digest'] != b['digest'] and a['reports'] != b['reports']


@pytest.mark.asyncio
async def test_query_rejects_equal_count_duplicate_or_foreign_keys(verifier):
    query = SimpleNamespace(kind='top_holders', detail=AsyncMock())
    head = dict(report_key='a' * 64, report_date='2024-12-31', unified_code='601139.SH', kind='top_holders')
    query.browse = AsyncMock(return_value=dict(rows=[head, head], next=None))
    with pytest.raises(ValueError, match='键重复'):
        await verifier.query_summary(query, '601139.SH')
    query.browse.return_value = dict(rows=[{**head, 'unified_code': '601139.SZ'}], next=None)
    with pytest.raises(ValueError, match='归属错误'):
        await verifier.query_summary(query, '601139.SH')
    query.detail.assert_not_awaited()


def test_known_failures_are_extra_fixed_cases_and_old_production_mutation_flags_retired(verifier):
    assert {'300398.SZ', '601515.SH'} <= set(verifier.FIXED_CODES)
    assert len(verifier.FIXED_CODES) == len(set(verifier.FIXED_CODES))
    options = verifier.parser()
    for flag in ('--apply', '--all-stocks', '--rebuild-proofs', '--expected-gaps'):
        with pytest.raises(SystemExit):
            options.parse_args(['--test-mysql-settings', 'private.json', '--output', 'build/report.json', flag])
