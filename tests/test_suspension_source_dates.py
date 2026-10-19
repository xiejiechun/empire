from datetime import date, timedelta

import pytest

from empire.features.suspensions.batches import bounded_batches
from empire.features.suspensions.collector import API_URL, merge_event
from empire.features.suspensions.contract import normalize_source_row, validate_period


def source_record(resumed=None):
    return normalize_source_row(dict(sc=0, code='000411', name='英特集团',
        tprq='2006-07-10 09:30', fprq=resumed,
        sj='今起复牌' if resumed else '今起停牌',
        sjcontent='修改对价方案的沟通结果公告' if resumed else '进行股权分置改革的提示性公告'))


def test_source_calendar_dates_survive_month_aggregation_without_guessing():
    stopped = source_record()
    resumed = source_record('2006-07-31 09:30')
    days = [((date(2006, 7, 1) + timedelta(days=i)).isoformat(), [], 1) for i in range(31)]
    days[9] = ('2006-07-10', [stopped], 2)
    days[10] = ('2006-07-11', [stopped], 2)
    days[30] = ('2006-07-31', [resumed], 2)
    envelope, *_ = bounded_batches(days, source='tdx', job_key='tdx-suspensions-v1',
        batch_id='test', first_page=1, limit=524288, source_url=API_URL, merge=merge_event)[0]
    payload = envelope.raw_payload
    result = validate_period(payload['start_date'], payload['end_date'], payload['checked_dates'], payload['rows'])
    assert next(row for row in result if row['resumed_at'])['source_dates'] == ['2006-07-31']
    assert next(row for row in result if not row['resumed_at'])['source_dates'] == ['2006-07-10', '2006-07-11']


@pytest.mark.parametrize('dates', [[], ['2006-08-01'], ['2006-07-10', '2006-07-10'],
                                  ['2006-07-11', '2006-07-10'], [None]])
def test_invalid_source_dates_are_rejected(dates):
    row = {**source_record(), 'source_dates': dates}
    with pytest.raises(ValueError, match='来源日期'):
        validate_period('2006-07-10', '2006-07-11', ['2006-07-10', '2006-07-11'], [row])
