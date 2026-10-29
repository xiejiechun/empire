"""Explicit adapters; no renderer-selected Python method names."""
from dataclasses import asdict

from empire.contracts.download_settings import FIELDS
from empire.plugins.collection.management_query import event_page, record_page, task_page
from empire.plugins.collection.rules import rule_details


async def execute(runtime, operation, params):
    registry = runtime.manager.registry
    if operation == 'health.read':
        return runtime.snapshot()
    if operation == 'exits.read':
        snapshot = await registry.get('proxy.pool').snapshot()
        # Deliberately omit connection addresses as well as credential-bearing objects.
        keys = ('code', 'exit_ip', 'protocol', 'remaining_seconds', 'cooldown_seconds', 'busy', 'requests', 'failures')
        return {**{k: snapshot.get(k) for k in ('error', 'online', 'online_egresses', 'waiting', 'invalid')},
                'devices': [{k: row.get(k) for k in keys} for row in snapshot['devices']]}
    if operation.startswith('resources.'):
        service = registry.get('download.settings')
        if operation == 'resources.read':
            http = registry.optional('http.fetch')
            live = None if http is None else {
                'active_requests': http.global_active,
                'buffer_reserved_bytes': http.buffer_budget.used,
                'buffer_limit_bytes': http.buffer_budget.limit,
                'waiting': http.buffer_budget.waiting + sum(
                    row.get('waiting_reasons', {}).get('global', 0) for row in http.stats.values()),
            }
            return {**await service.snapshot(), 'live': live,
                    'fields': [asdict(f) for f in FIELDS if f.key in
                               {'max_parallel_downloads', 'buffer_budget_bytes'}]}
        if operation == 'resources.save':
            return await service.save_limits(params['values'])
        raise ValueError('未知下载资源操作')
    if operation.startswith('identities.') or operation == 'identity.service':
        service = registry.get('identities.query')
        if operation == 'identities.catalog':
            return await service.catalog()
        if operation == 'identities.read':
            return await service.snapshot(**params)
        platforms = {p['id']: p for p in await service.catalog()}
        if params['platform'] not in platforms:
            raise ValueError('Unknown identity platform')
        # Keep the same Runtime.command path, including preference persistence.
        import asyncio
        await asyncio.wrap_future(runtime.command(params['action'], platforms[params['platform']]['plugin_id']))
        return {'message': '平台服务操作已完成'}
    control = registry.get('collection.control')
    if 'ident' in params and params['ident'] not in control.definitions:
        raise ValueError('Unknown collection task')
    if operation == 'preview.catalog':
        from .preview import catalog
        return catalog(params['ident'])
    if operation == 'preview.read':
        import json

        from .preview import read
        return await read(registry, **{**params, 'cursor': json.loads(params['cursor'])})
    if operation == 'tasks.list':
        return task_page(control, **params)
    if operation == 'task.read':
        data = await control.workspace(focus_task_id=params['ident'])
        if not data['jobs']:
            return None
        archive = registry.optional('archive.worker')
        return {**data['jobs'][0], 'latest_run': data['history'][0] if data['history'] else None,
                'archive_metrics': archive.metrics.snapshot(params['ident']) if archive else None}
    if operation == 'collection.rules.read':
        return rule_details(params['ident'], runtime.cfg)
    if operation == 'collection.policy.save':
        return {'message': await control.configure(**params)}
    if operation == 'collection.run':
        return {'run_id': await control.run(**params), 'message': '已接收运行请求；完成状态以实际进度为准'}
    if operation == 'collection.pause':
        return await control.pause(**params)
    if operation == 'collection.batch':
        return await control.batch(**params)
    if operation == 'collection.archive':
        return await control.set_archived(**params)
    if operation == 'sites.list':
        return await control.workspace(section='sites', **params)
    if operation == 'sites.save':
        return await control.configure_site(**params)
    records = registry.get('collection.records')
    if operation == 'run.events':
        return await event_page(control, records, **params)
    if operation == 'records.list':
        return await record_page(control, records, **params)
    if operation == 'error.read':
        return await records.get_error(params['ident'], params['record_id'])
    if operation == 'errors.clear':
        return {'removed': await records.clear_errors(params['ident'], params['record_ids'])}
    raise ValueError('Operation is not implemented')
