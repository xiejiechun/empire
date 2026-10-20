import copy

import pytest

from empire.contracts.data import make_envelope
from empire.features.security_aliases.contract import URL, validate
from empire.features.security_aliases.dataset import JOB, normalize
from empire.features.security_aliases.source import HEADER, NOTE, parse

ROWS = [dict(legacy_code='836149', unified_code='920149.BJ', name='旭杰科技', listing_date='2020-07-27')]


def document(rows=None):
    rows = rows or [['1', '旭杰科技', '2020/7/27', '836149', '920149']]
    return ('<table><tr>' + ''.join('<td>' + value + '</td>' for value in HEADER) + '</tr>' + ''.join(
        '<tr>' + ''.join('<td>' + value + '</td>' for value in row) + '</tr>' for row in rows)
        + '<tr><td>' + NOTE + '</td></tr></table>').encode()


def envelope(rows=None):
    rows = rows or ROWS
    return make_envelope(source='bse', dataset='bse.code_mapping.complete', business_key='official-table',
        job_key=JOB, run_id='test', batch_id='test', payload=dict(page=1, rows=rows, source_count=len(rows), source_url=URL))


def test_official_table_and_no_numeric_inference():
    assert parse(document()) == ROWS
    rows = parse(document([['1', '芭薇股份', '2024/3/29', '837023', '920123']]))
    assert rows[0]['unified_code'] == '920123.BJ'
    assert normalize(envelope())['row_count'] == 1


@pytest.mark.parametrize('body', [document().replace(b'</table>', b''), document().replace(NOTE.encode(), b''),
    document([['2', '旭杰科技', '2020/7/27', '836149', '920149']]),
    document([['1', '旭杰科技', '2020/7/27', '836149', '920149'], ['2', '其他', '2020/7/27', '836149', '920200']])])
def test_incomplete_or_same_count_wrong_set_rejected(body):
    with pytest.raises(ValueError):
        parse(body)


def test_business_conflicts_and_count_proof():
    rows = copy.deepcopy(ROWS) + [dict(legacy_code='831010', unified_code='920149.BJ', name='另一证券', listing_date='2020-07-27')]
    with pytest.raises(ValueError):
        validate(rows)
    event = envelope()
    with pytest.raises(ValueError):
        normalize(event.model_copy(update={'raw_payload': {**event.raw_payload, 'source_count': 2}}))
