"""New bundle registration cannot silently replace existing assembly identities."""
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.assembly_contract import compare, compare_order, order_snapshot, snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_additive_registration_preserves_old_identity_and_order():
    import json

    changes = json.loads((ROOT/'docs/assembly-feature-changes.json').read_text('utf8'))
    addition = next(c for c in changes if c['path'] == 'additive.hot_list')
    current = snapshot(ROOT)
    before = copy.deepcopy(current)
    for section in ('semantic', 'bindings'):
        groups = addition['after'][section]
        for group, values in groups.items():
            for key in values:
                before[section][group].pop(key)
    assert not compare(before, current, {}, ROOT, [addition])
    with pytest.raises(ValueError, match='existing identities'):
        compare(current, current, {}, ROOT, [addition])
    wrong = copy.deepcopy(current)
    wrong['semantic']['tasks']['sina-news']['interval_seconds'] = 99
    assert compare(before, wrong, {}, ROOT, [addition]) == ['semantic.tasks.sina-news.interval_seconds']
    ordered = order_snapshot(ROOT)
    old = copy.deepcopy(ordered)
    for group in ('plugins', 'tasks', 'datasets', 'pages', 'preparation'):
        remove = addition['after']['semantic'].get(group, {})
        old[group] = [key for key in old[group] if key not in remove]
        if group == 'plugins':
            old['startup'] = [key for key in old['startup'] if key not in remove]
    assert not compare_order(old, ordered, [addition])
    swapped = copy.deepcopy(ordered)
    swapped['tasks'][:2] = reversed(swapped['tasks'][:2])
    assert compare_order(old, swapped, [addition]) == ['order.tasks']


async def test_verifier_cancel_restores_shared_methods_and_policy(monkeypatch):
    import asyncio
    import importlib

    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    verifier = importlib.import_module('verify_hot_list')
    http = SimpleNamespace(request=AsyncMock())
    ingest = SimpleNamespace(publish_page=AsyncMock())
    collector = SimpleNamespace(http=http, ingest=ingest, execute=AsyncMock(side_effect=asyncio.CancelledError()), checkpoint_revision=AsyncMock(return_value=0))
    values = {'collector.tdx_hot_list': collector, 'hot_list.query': object()}
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=values.__getitem__))
    before = http.request, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get()
    with pytest.raises(asyncio.CancelledError):
        await verifier.verify_scope(manager, dict(selected=[]), SimpleNamespace(proxy_only=False), dict(results={}))
    assert before == (http.request, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get())
