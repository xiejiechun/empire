"""Evidence for explicit on-demand computations, without fictitious archive tasks."""
from empire.core.preparation_release import test_evidence


def development(plugins, contribution, artifact, error, kind):
    c = contribution
    providers = [p for p in plugins if c.capability in p.manifest.provides]
    checks = []
    for key, title, expected, passed in (
        ('task', '计算入口登记', '本项按需计算入口已登记，不需要另启采集任务',
         bool(providers) and all(callable(getattr(p, c.execute_method, None)) for p in providers)),
        ('dataset', '输入与结果契约', '明确计算版本及输入输出；只读当前完整归档，不建立重复业务表',
         bool(providers) and bool(c.output_version) and all(getattr(p, 'output_version', None) == c.output_version for p in providers)),
        ('query', '结果与范围检查', '本项具有范围明确的检查接口',
         bool(providers) and all(callable(getattr(p, c.method, None)) for p in providers)),
    ):
        checks.append(dict(id=key, phase='开发', kind=kind, title=title, expected=expected,
                           action='检查计算插件及输入输出契约', status='pass' if passed else 'fail',
                           measured=f'{c.capability} / {c.project_id} / {c.output_version}'))
    for key, title, paths in (('source_tests', '计算规则测试', c.rule_tests),
                              ('archive_tests', '输入归档到计算查询测试', c.integration_tests)):
        passed, detail = test_evidence(artifact, paths)
        checks.append(dict(id=key, phase='开发', kind=kind, title=title, expected='当前版本专项测试全部执行通过',
            action='运行计算专项与隔离集成测试', status='pass' if passed else 'unknown', measured=error or detail))
    checks.append(dict(id='shared_tests', phase='开发', kind=kind, title='读写边界',
        expected='本项计算只读，不新增下载、入队、归档或持久化业务副本', action='检查正式查询的只读回归',
        status='pass' if providers else 'fail', measured='输入沿用统一归档；计算不创建另一份队列和写入路径'))
    for item in checks:
        item['execution'] = 'read_only_computation'
    return checks
