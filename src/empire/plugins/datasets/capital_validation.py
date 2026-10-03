"""Validate persisted canonical fields by reconstructing the declared source contract."""
from decimal import Decimal


def as_source(kind, row):
    d = row['data']
    def scaled(key, factor=1):
        return None if d[key] is None else str(Decimal(d[key]) * Decimal(str(factor)))
    if kind == 'dividends':
        raw = dict(fhbgq=d['report_date'], T013=scaled('bonus_per_share', 10),
            T014=scaled('transfer_per_share', 10), szzs=scaled('total_bonus_per_share', 10),
            T015=scaled('cash_per_share', 10), ygrq=d['announcement_date'], gqdjr=d['record_date'],
            cqcxr=d['ex_date'], fajd=d['status'], T006=d['earnings_per_share'],
            T010=d['net_assets_per_share'], T012=d['capital_reserve_per_share'], T009=d['retained_profit_per_share'])
        return raw, {key: row[key] for key in ('market', 'code', 'name')}
    raw = dict(sc={'SH': 1, 'SZ': 0, 'BJ': 2}[row['market']], code=row['code'], name=row['name'])
    if kind == 'additional_issues':
        raw.update(T097=d['lock_months'], T005=scaled('issued_shares', '0.0001'),
            T039=scaled('shares_before', '0.0001'), T040=scaled('shares_after', '0.0001'),
            T048=d['subscription_code'], T037=d['record_date'], T012=d['issue_price'], ClosePrice=None,
            T043=d['public_issue_date'], T046=d['private_issue_date'], fxrq=d['issue_date'],
            T080=d['listing_date'], rec_id=int(d['source_id']), fxfs=d['issue_method'])
    else:
        raw.update(T005=scaled('rights_per_share', 10), T006=d['rights_price'],
            gqdjr=d['record_date'], cqjzr=d['ex_date'], jqqsr=d['payment_start'], jqjzr=d['payment_end'],
            T015=scaled('issued_shares', '0.0001'), T022=scaled('shares_before', '0.0001'),
            T023=scaled('shares_after', '0.0001'), T038=d['subscription_code'], T043=d['listing_date'], price=None)
    return raw, None
