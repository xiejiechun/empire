"""Sampling acceptance cannot replace failures with a convenient fixed sample."""
from argparse import Namespace

import pytest

from scripts.verify_ths_capital import run, select_sample


def pool(size=100):
    return [dict(code=f'{600000+i:06d}', unified_code=f'{600000+i:06d}.SH') for i in range(size)]


def test_random_thirty_are_distinct_extra_to_required_and_reproducible():
    selected, evidence = select_sample(pool(), ['600001', '600002'], 30, 1234)
    assert len(selected) == len({r['unified_code'] for r in selected}) == 32
    assert len(evidence['random_codes']) == 30
    assert not set(evidence['random_codes']) & set(evidence['required_codes'])
    assert select_sample(list(reversed(pool())), ['600002', '600001'], 30, 1234) == (selected, evidence)
    assert select_sample(pool(), ['600001', '600002'], 30, 1235)[1]['random_codes'] != evidence['random_codes']


def test_small_pool_cannot_be_reused_to_claim_thirty():
    with pytest.raises(ValueError, match='抽样池不足'):
        select_sample(pool(30), ['600001'], 30, 1234)


async def test_apply_refuses_less_than_thirty_before_services_start():
    with pytest.raises(ValueError, match='至少随机30只'):
        await run(Namespace(apply=True, random_count=29))
