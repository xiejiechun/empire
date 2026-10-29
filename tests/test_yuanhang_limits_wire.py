import base64
import zlib

import pytest

from empire.features.yuanhang_limits.contract import MAX_UNIT_BYTES
from empire.features.yuanhang_limits.model import member
from empire.features.yuanhang_limits.wire import decode, encode
from tests.test_yuanhang_limits_source import row


def test_large_complete_pool_fits_default_ingest_without_losing_nulls_or_precision():
    unit = dict(trade_date='2026-07-15', pool_type='limit_down_pool', filter='HS,GEM2STAR', source_total=5000,
                rows=[member(row(f'{i:06}'), '2026-07-15') for i in range(5000)])
    packed = encode(unit)
    assert len(packed) < 480 * 1024
    assert decode(packed) == unit


@pytest.mark.parametrize('value', ['?', 'eA==', base64.b64encode(zlib.compress(b'{}') + b'extra').decode(),
    base64.b64encode(zlib.compress(b'x' * (MAX_UNIT_BYTES + 1))).decode()])
def test_invalid_or_bomb_compression_rejected(value):
    with pytest.raises(ValueError):
        decode(value)
