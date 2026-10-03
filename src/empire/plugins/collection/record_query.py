"""Cross-project Redis history projection; bodies stay out of list responses."""
import hashlib
import heapq
import json


async def all_records(records, kind, offset=0, limit=50, known_revision=None):
    if kind not in ('errors', 'archives') or type(offset) is not int or offset < 0:
        raise ValueError('Invalid history query')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid history page size')
    prefix = f'{records.redis.prefix}:collection:{kind}:'
    keys = sorted({key async for key in records.redis.client.scan_iter(match=prefix+'*')})
    revisions = await records.redis.client.mget([
        records._revision_key(kind, key[len(prefix):]) for key in keys]) if keys else []
    revision = hashlib.sha256(json.dumps([keys, revisions]).encode()).hexdigest()
    counts = []
    if keys:
        async with records.redis.client.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.llen(key)
            counts = await pipe.execute()
    total = sum(counts)
    offset = min(offset, max(0, (total-1)//limit*limit))
    result = dict(revision=revision, total=total, offset=offset, limit=limit,
                  changed=known_revision != revision, rows=[])
    if not result['changed']:
        return result
    candidates = []
    for key, count in zip(keys, counts, strict=True):
        project = key[len(prefix):]
        if kind == 'errors':
            values = []
            for start in range(0, min(count, 300), 100):
                page = await records.list_error_summaries(project, start, 100)
                values.extend(page['rows'])
        else:
            values = await records.list_archives(project)
        candidates.extend({**row, 'project_id': project} for row in values)
        # Retain only the requested prefix, not every project's history.
        candidates = heapq.nlargest(offset+limit, candidates, key=_order)
    result['rows'] = candidates[offset:offset+limit]
    return result


def _order(row):
    return row.get('created_at', ''), row['project_id'], row['id']
