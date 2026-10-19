"""Business-owned dates; moved declarations retain existing behavior."""
from datetime import date

BSE_OPEN = date(2021, 11, 15)


def lifecycle(stock):
    return dict(listing_date=stock['listing_date'], listing_source='eastmoney',
                market_start=BSE_OPEN.isoformat() if stock['market'] == 'BJ' else stock['listing_date'])


def required_days(stock, calendar, excluded):
    start = max(date.fromisoformat(stock['listing_date']),
                BSE_OPEN if stock['market'] == 'BJ' else date(2021, 1, 1))
    return [day for day in calendar if day >= start and day not in excluded]
