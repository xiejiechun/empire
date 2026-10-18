"""Batch commands delegate to the normal task lifecycle and saved policies."""


async def execute_batch(control, operation, identifiers):
    if operation not in ('start', 'stop'):
        raise ValueError('批量操作只支持启动或停止')
    if not isinstance(identifiers, (list, tuple)) or not identifiers or any(
        not isinstance(ident, str) for ident in identifiers
    ):
        raise ValueError('请选择具体采集任务')
    results = []
    for ident in dict.fromkeys(identifiers):
        result = {'id': ident, 'status': 'success', 'message': ''}
        enabled = False
        try:
            job = control.state['jobs'][ident]
            if job['policy'].get('archived'):
                result.update(status='skipped', message='任务已归档')
            elif operation == 'start':
                task = control.tasks.get(ident)
                if task is not None and not task.done():
                    result.update(status='skipped', message='任务正在执行')
                else:
                    if not job['policy']['enabled']:
                        await control.configure(ident, {**job['policy'], 'enabled': True})
                        enabled = True
                    await control.run(ident)
                    result['message'] = '已启动，使用已保存配置'
            else:
                result['message'] = await control.pause(ident)
        except Exception as exc:
            result.update(status='failed', message=('已启用并保存，但启动失败：' if enabled else '')
                          + control.records.sanitize_text(exc))
        results.append(result)
    return {'operation': operation, 'results': results}
