"""Bounded presentation snapshot; never persist collector cursors or business rows."""

DISPLAY_FIELDS = (
    'collected', 'queued_records', 'expected_count', 'record_name', 'unit_name',
    'completed_units', 'processed_units', 'total_units', 'total_months', 'pages',
    'source_pages', 'current_security', 'current_date', 'current_month',
    'continuous_collected', 'failed_units', 'details_unavailable', 'unavailable',
    'unlisted_without_date', 'source_gap_units', 'source_identity_gaps',
)


def display_snapshot(stats):
    result = {key: value[:512] if isinstance(value, str) else value
              for key in DISPLAY_FIELDS
              if isinstance(value := stats.get(key), (int, float, str))}
    categories = stats.get('failure_categories')
    if isinstance(categories, dict):
        result['failure_categories'] = {
            key: categories[key] for key in ('source_request', 'minute_gap', 'placeholder', 'invalid_fields')
            if type(categories.get(key)) is int}
    return result
