"""Public pure codec extracted without business-rule changes."""
import json


def decode(row):
    data = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
    return {k: row[k] for k in ('record_key', 'market', 'code', 'name')} | {
        'event_date': row['event_date'].isoformat() if row['event_date'] else None, 'data': data}
