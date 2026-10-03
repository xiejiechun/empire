"""Keep a failed security frontier while admitting independent valid securities."""
from datetime import date, timedelta

from empire.plugins.collectors.support import record_error_safely
from empire.plugins.collectors.tdx_capital_source import PAGE_URL


def recent_plans(rows, today):
    """Recheck dated plans in the last 90 days; unknown dates remain unknown."""
    lower = today - timedelta(days=90)
    result = set()
    for row in rows:
        data = row['data']
        dates = [date.fromisoformat(data[key]) for key in (
            'issue_date', 'public_issue_date', 'private_issue_date', 'listing_date', 'record_date')
            if data.get(key)]
        if any(lower <= value <= today for value in dates):
            result.add(data['source_id'])
    return result


async def retain_failure(c, exc, unit):
    await record_error_safely(c.records, c.stats, c.project_id, exc,
        stage='source_validation', unavailable_message='证券错误记录暂未写入 Redis',
        fields={'request_url': PAGE_URL, 'metadata': {'unit': unit}})
    c.stats['failed_units'] = c.stats.get('failed_units', 0) + 1
