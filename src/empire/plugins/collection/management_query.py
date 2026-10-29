"""Lightweight desktop projections over the authoritative task registry/state."""
import copy
from datetime import datetime


def task_page(control, *, offset=0, limit=50, query='', source='', category='', status='', archived=False):
    rows = []
    for spec in control.definitions.values():
        job = control.state['jobs'].get(spec.id)
        if job is None:
            continue
        policy = job['policy']
        state = 'running' if job.get('active') else job.get('last_status', 'idle')
        if bool(policy.get('archived')) != archived:
            continue
        if source and spec.rate_group != source or category and spec.category != category:
            continue
        if status == 'disabled':
            if policy['enabled']:
                continue
        elif status and state != status:
            continue
        haystack = ' '.join((spec.id, spec.name, spec.source_name, spec.rate_group, spec.description))
        if query.casefold() not in haystack.casefold():
            continue
        rows.append(dict(id=spec.id, name=spec.name, source=spec.rate_group,
                         source_name=spec.source_name or spec.rate_group, category=spec.category,
                         state=state, enabled=policy['enabled'], archived=archived,
                         next_due=job.get('next_due')))
    rows.sort(key=lambda r: (r['source_name'], r['source'], r['name'], r['id']))
    total = len(rows)
    offset = min(offset, max(0, (total - 1) // limit * limit))
    page = rows[offset:offset + limit]
    for row in page:
        if row['state'] == 'running':
            service = control.context.optional(control.definitions[row['id']].capability)
            progress = service.health() if service else {}
            row['progress'] = {key: progress.get(key) for key in (
                'status', 'completed_units', 'processed_units', 'total_units', 'unit_name')}
    return dict(rows=page, total=total, offset=offset, limit=limit,
                sources=sorted({(s.rate_group, s.source_name or s.rate_group) for s in control.definitions.values()}),
                categories=sorted({s.category for s in control.definitions.values()}))


async def record_page(control, records, *, kind='collection', project='', offset=0, limit=50):
    if kind == 'collection':
        data = await control.workspace(section='history', project=project, offset=offset, limit=limit)
        return dict(rows=data['history'], total=data['total'], offset=data['offset'], limit=limit)
    if not project:
        return await records.list_all_records(kind, offset=offset, limit=limit)
    if project not in control.definitions:
        raise ValueError('Unknown collection task')
    if kind == 'errors':
        return await records.list_error_summaries(project, min(offset, 299), limit)
    rows = await records.list_archives(project)
    offset = min(offset, max(0, (len(rows) - 1) // limit * limit))
    return dict(rows=copy.deepcopy(rows[offset:offset + limit]), total=len(rows), offset=offset, limit=limit)


async def event_page(control, records, *, ident, run_id='', unlinked=False, stage='', offset=0, limit=25):
    """Combine bounded metadata, never infer run membership from timestamp proximity."""
    if ident not in control.definitions:
        raise ValueError('Unknown collection task')
    runs = [copy.deepcopy(r) for r in control.state['history'] if r['task_id'] == ident]
    active = control.state['jobs'][ident].get('active')
    if active:
        runs.insert(0, {**copy.deepcopy(active), 'status': 'running'})
    archives = await records.list_archives(ident)
    errors = []
    for start in range(0, 300, 100):
        page = await records.list_error_summaries(ident, start, 100)
        errors.extend(page['rows'])
        if start + 100 >= page['total']:
            break
    rows = []
    for kind, values in [('collection', runs), ('archives', archives), ('errors', errors)]:
        for row in values:
            linked = row.get('run_id') or row.get('metadata', {}).get('run_id')
            timestamp = row.get('finished_at') or row.get('created_at') or row.get('started_at')
            try:
                stamp = float(timestamp) if isinstance(timestamp, (int, float)) else datetime.fromisoformat(timestamp).timestamp()
            except (ValueError, TypeError):
                stamp = 0
            rows.append(dict(id=f"{kind}:{row.get('id') or row.get('run_id')}", record_id=row.get('id'),
                             stage=kind, timestamp=stamp or None, run_id=linked,
                             status=row.get('status') or row.get('stage'),
                             message=row.get('message') or row.get('error') or row.get('notice') or '',
                             detail=row))
    unlinked_count = sum(not r['run_id'] for r in rows)
    filtered = [r for r in rows if (not stage or r['stage'] == stage)
                and ((not r['run_id']) if unlinked else (not run_id or r['run_id'] == run_id))]
    filtered.sort(key=lambda r: (r['timestamp'] or 0, r['id']))
    offset = min(offset, max(0, (len(filtered) - 1) // limit * limit))
    return dict(rows=filtered[offset:offset + limit], total=len(filtered), offset=offset, limit=limit,
                unlinked_count=unlinked_count, retention='collection:100 archives:100 errors:300')
