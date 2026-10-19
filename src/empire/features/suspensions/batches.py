"""Split a validated month into bounded, contiguous date ranges before publishing."""
from empire.contracts.data import make_envelope
from empire.features.suspensions.contract import event_identity


def bounded_batches(days, *, source, job_key, batch_id, first_page, limit, source_url, merge):
    result = []

    def prepare(part):
        events = {}
        dates = {}
        appearances = {}
        for day, rows, _ in part:
            for row in rows:
                identity = event_identity(row)
                try:
                    events[identity] = merge(events[identity], row) if identity in events else row
                except ValueError as exc:
                    raise ValueError(f'{exc}；来源日期：{dates[identity]}、{day}') from None
                dates[identity] = day
                appearances.setdefault(identity, set()).add(day)
        start, end = part[0][0], part[-1][0]
        payload = {'page': first_page + len(result), 'period': start[:7],
                   'start_date': start, 'end_date': end,
                   'checked_dates': [day for day, _, _ in part],
                   'rows': [{**events[key], 'source_dates': sorted(appearances[key])}
                            for key in sorted(events)]}
        envelope = make_envelope(
            source=source, dataset='suspensions.period', job_key=job_key, schema_version=3,
            business_key=f'{batch_id}:{start}:{end}', run_id=batch_id,
            batch_id=batch_id, payload=payload,
        ).model_copy(update={'source_url': source_url})
        if len(envelope.model_dump_json().encode()) > limit:
            if len(part) == 1:
                raise ValueError(f'停复牌 {start} 单日数据超过入队字节上限；断点保留')
            middle = len(part) // 2
            prepare(part[:middle])
            prepare(part[middle:])
        else:
            result.append((envelope, len(events), len(part), sum(pages for _, _, pages in part)))

    prepare(days)
    return result
