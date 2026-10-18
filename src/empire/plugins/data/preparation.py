"""Acceptance dashboard: registered work, executed tests and live data evidence."""
import asyncio
from datetime import datetime

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import CheckEvidence, ComputationContribution
from empire.contracts.preparation_catalog import BY_ID, REQUIREMENTS
from empire.contracts.preparation_research import required_ids, research_summary
from empire.contracts.preparation_scope import PreparationScope
from empire.core.preparation_release import load_evidence, test_evidence
from empire.core.time import CHINA
from empire.plugins.data.preparation_cache import PreparationCache, cache_identity
from empire.plugins.data.preparation_results import accepted, dimension, summarize

SHARED_TESTS = ('tests/test_ingest_reservations.py', 'tests/test_collector_support.py',
                'tests/test_collection_integrity.py',
                'tests/test_fingerprint_versions.py', 'tests/integration/test_archive_fairness.py')
DEVELOPMENT = (
    ('task', '采集任务登记', '任务 ID、采集能力、分类和来源明确', '开发并登记采集任务'),
    ('dataset', '归档与版本契约', '数据集精确归属项目；具备摘要、版本和写入契约', '登记统一归档贡献与版本规则'),
    ('query', '查询及检查接口', '查询插件提供逐条验收结果，不接受整体布尔完成标记', '实现查询、结构校验与专项检查器'),
    ('source_tests', '来源语义回归', '本版本来源专项测试实际执行且全部通过', '补测字段、分页/范围、断点和异常响应并运行发布门禁'),
    ('archive_tests', '归档业务回归', '本版本归档专项集成测试实际执行且全部通过', '验证重复无 DML、修订、旧版拒绝、提交重放与成功清队'),
    ('shared_tests', '公共流程回归', '公共入队隔离、生命周期、版本信任及归档公平性回归通过', '运行包含隔离集成测试的正式发布门禁'),
)


def check(ident, phase, title, expected, action, status='unknown', measured='尚无核验证据'):
    return dict(id=ident, phase=phase, title=title, expected=expected, action=action,
                status=status, measured=measured)


class PreparationPlugin:
    manifest = PluginManifest('data.preparation', '数据准备验收', provides=('preparation.query',),
                              description='逐项核验开发交付、测试证据与实际数据缺口')

    def __init__(self, contributions, plugins=()):
        self.contributions = tuple(contributions)
        self.plugins = tuple(plugins)
        identities = [(c.requirement, c.capability) for c in self.contributions]
        if len(set(identities)) != len(identities) or any(c.requirement not in BY_ID for c in self.contributions):
            raise ValueError('重复或未知的数据准备声明')
        owners = {}
        collectors = {}
        for contribution in self.contributions:
            group = getattr(contribution, 'response_group', '')
            if group and (not isinstance(group, str) or group != contribution.dataset):
                raise ValueError('共享响应组须精确对应统一数据集')
            identity = ((group, contribution.source, contribution.job_key, contribution.dataset,
                         contribution.collector) if group else contribution.requirement)
            owner = owners.setdefault(contribution.project_id, identity)
            if owner != identity:
                raise ValueError('一个采集项目只能对应一项独立数据；不同采集内容须登记不同项目')
            if BY_ID[contribution.requirement].kind == '采集':
                if isinstance(contribution, ComputationContribution):
                    raise ValueError('派生计算不能冒充采集项目')
                collector_identity = (contribution.project_id, identity) if group else identity
                owner = collectors.setdefault(contribution.collector, collector_identity)
                if owner != collector_identity:
                    raise ValueError('一个采集能力只能负责一项独立数据；请拆成独立采集插件')
        for plugin in self.plugins:
            outputs = {collectors[cap] for cap in plugin.manifest.provides if cap in collectors}
            if len(outputs) > 1:
                raise ValueError('一个采集插件不能包办不同数据准备项；请拆成独立采集插件')
        self.context = None
        self._report_lock = asyncio.Lock()
        self._progress = None
        self._progress_scope = None
        self._checking = False
        self._checked = 0
        self._current = ''
        self._inventory = None
        self._started_at = ''

    async def start(self, context):
        self.context = context
        return {'preparation.query': self}

    def development(self, contribution, artifact, error, kind="采集"):
        if isinstance(contribution, ComputationContribution):
            from empire.plugins.data.preparation_computation import development
            return development(self.plugins, contribution, artifact, error, kind)
        checks = [check(i, '开发', title, expected, action) for i, title, expected, action in DEVELOPMENT]
        for item in checks:
            item['kind'] = kind
        if kind != '采集':
            checks[0].update(title='处理任务登记', expected='本项处理工作有独立任务及明确输入输出',
                             action='实现并登记本项处理任务，不在这里增加网站采集')
            checks[3].update(title='处理规则测试', expected='本版本处理规则、输入缺失与异常结果测试全部通过',
                             action='补齐本项处理规则测试并执行完整检查')
        if contribution is None:
            for item in checks:
                item['measured'] = '未接入：没有登记提供此交付物的插件'
            return checks
        c = contribution
        tasks = [task for plugin in self.plugins
                 for task in getattr(plugin, 'definitions', {}).values()
                 if task.id == c.project_id and task.capability == c.collector
                 and task.category and task.source_name]
        providers = [p for p in self.plugins if c.collector in p.manifest.provides]
        checks[0].update(status='pass' if tasks and providers else 'fail',
                         measured=f'项目 {c.project_id} / 采集能力 {c.collector}；匹配任务 {len(tasks)}、提供者 {len(providers)}')
        mappings = [d for plugin in self.plugins for d in getattr(plugin, 'contributions', ())
                    if hasattr(d, 'datasets') and c.dataset in d.datasets
                    and d.projects.get(c.job_key) == c.project_id]
        valid = bool(mappings) and all(all(callable(getattr(d.mapping, name, None)) for name in
                    ('fingerprint_plan', 'fingerprint_subset', 'write', 'archive_state'))
                    and getattr(d.mapping, 'FINGERPRINT_VERSION', None) for d in mappings)
        checks[1].update(status='pass' if valid else 'fail',
                         measured=f'{c.dataset} / {c.job_key} → {c.project_id}；契约匹配 {len(mappings)} 项')
        query = [p for p in self.plugins if c.capability in p.manifest.provides
                 and callable(getattr(p, c.method, None))]
        checks[2].update(status='pass' if query else 'fail',
                         measured=f'{c.capability}.{c.method}；登记实现 {len(query)} 项；实际结构/内容另看数据验收')
        for item, paths in zip(checks[3:], (c.source_tests, c.archive_tests, SHARED_TESTS), strict=True):
            passed, detail = test_evidence(artifact, paths)
            item.update(status='pass' if passed else 'unknown', measured=error or detail)
        return checks

    async def provider_report(self, requirement, c, artifact, error, request=None):
        checks = self.development(c, artifact, error, requirement.kind)
        live = {}
        problem = '未接入数据检查插件'
        if c:
            service = self.context.optional(c.capability)
            problem = '查询插件未运行或结构校验失败；在插件管理检查依赖'
            if service:
                try:
                    operation = getattr(service, c.method)(request) if c.scoped else getattr(service, c.method)()
                    result = await asyncio.wait_for(operation, timeout=600 if c.scoped else 30)
                    if not isinstance(result, tuple) or not all(isinstance(e, CheckEvidence) for e in result):
                        raise ValueError('无效证据类型')
                    live = {e.criterion: e for e in result}
                    allowed = {criterion.id for criterion in requirement.criteria}
                    if len(live) != len(result) or not set(live).issubset(allowed):
                        raise ValueError('重复或未知检查项')
                    nonblocking = set()
                    if c.scoped and PreparationScope.parse(request).purpose == 'analysis':
                        nonblocking.add('temporal')
                        if getattr(c, 'analysis_quality_limits', False) is True:
                            nonblocking.add('quality')
                    if any(not e.blocking and (e.criterion not in nonblocking or e.status == 'unknown') for e in result):
                        raise ValueError('非阻断证据须为声明分析用途的时点或来源质量限制；完整性仍须通过')
                    problem = '检查器尚未提供本验收项的证据'
                except Exception:
                    live = {}
                    problem = '查询失败、超时或证据无效；本轮不能确认，请检查插件与数据库后重试'
        for criterion in requirement.criteria:
            evidence = live.get(criterion.id)
            checks.append(check(criterion.id, '数据', criterion.title, criterion.expected, criterion.action,
                evidence.status if evidence else 'unknown', evidence.measured if evidence else problem))
            checks[-1]['kind'] = requirement.kind
            checks[-1]['blocking'] = evidence.blocking if evidence else True
            checks[-1]['findings'] = evidence.findings if evidence else ()
            if c and c.scoped and criterion.id in ('fields', 'quality'):
                checks[-1]['recommended_action'] = '保留来源缺值与异常标记；按用途排除受影响记录，或核实原始披露。不要编造字段或修改来源内容来让检查通过。'
            if evidence and not evidence.blocking:
                checks[-1]['recommended_action'] = '按本项列出的限制用于普通分析；历史选股回测需满足本项日期、内容和使用条件后再验收。'
        return self.provider_result(c, checks, request)

    def provider_result(self, c, checks, request):
        for item in checks:
            item['dimension'] = dimension(item)
        return dict(source=c.source if c else '未接入', checks=checks,
                    page=getattr(c, 'page_id', '') if c else '',
                    scope=PreparationScope.parse(request).label() if c and c.scoped else '本数据源声明的完整范围（不使用三表范围筛选）',
                    running=bool(c and self.context.optional(c.capability if isinstance(c, ComputationContribution) else c.collector)),
                    project=c.project_id if c else '')

    def metadata_provider(self, requirement, c, artifact, error, request):
        checks = self.development(c, artifact, error, requirement.kind)
        for criterion in requirement.criteria:
            item = check(criterion.id, '数据', criterion.title, criterion.expected, criterion.action,
                         measured='本项数据检查尚未结束，不能确认通过')
            item.update(kind=requirement.kind, blocking=True, findings=())
            checks.append(item)
        return self.provider_result(c, checks, request)

    async def snapshot(self, request=None):
        """Read bounded report progress without starting SQL or changing its scope."""
        return self._progress if PreparationScope.parse(request) == self._progress_scope else None

    async def inventory(self, exact=False):
        from empire.plugins.data.preparation_inventory import inventory
        async with self._report_lock:
            self._inventory = await inventory(self.context, self.contributions, exact,
                                              lambda result: setattr(self, '_inventory', result))
            return self._inventory

    async def inventory_snapshot(self):
        return self._inventory

    async def overview(self, request=None):
        """Opening a page never implicitly starts an expensive full-history check."""
        async with self._report_lock:
            return await self._overview(request)

    async def _overview(self, request):
        from empire.plugins.data.preparation_inventory import inventory
        scope = PreparationScope.parse(request)
        artifact, error = await asyncio.to_thread(load_evidence)
        results = {r.id: [self.metadata_provider(r, c, artifact, error, request)
                         for c in ([c for c in self.contributions if c.requirement == r.id] or [None])]
                   for r in REQUIREMENTS}
        report = self.assemble_report(results, error or f"本版本测试证据：{artifact['checked_at']}", scope)
        report.update(checking=False, checked_requirements=0, checked_at='',
                      cache_note='尚未检查。选择用途和范围后开始；库存条数不代表研究可用。')
        store = self.context.optional('redis.store')
        if store is not None:
            try:
                cache = PreparationCache(store, cache_identity(self.contributions, self.plugins, self.context), scope)
                cached = await cache.read()
                if cached is not None:
                    report = await self.cached_report(cached, request, scope)
            except Exception:
                report['cache_note'] = '旧报告不可读取；尚未检查，请手动开始。'
        self._inventory = await inventory(self.context, self.contributions)
        report['inventory'] = self._inventory
        return report

    async def report(self, request=None, force=False):
        scope = PreparationScope.parse(request)
        async with self._report_lock:
            store = self.context.optional('redis.store')
            cache, note = None, 'Redis 不可用，本次结果未缓存。'
            if store is not None:
                try:
                    identity = cache_identity(self.contributions, self.plugins, self.context)
                    cache = PreparationCache(store, identity, scope)
                    if not force:
                        cached = await cache.read()
                        if cached is not None:
                            report = await self.cached_report(cached, request, scope)
                            self._progress_scope, self._progress = scope, report
                            return report
                except Exception:
                    note = 'Redis 缓存读取失败，本次重新检查。'
            report = await self._run_report(request, scope)
            if cache is not None:
                try:
                    await cache.write(report)
                    note = '检查结果已保存到 Redis，保存 7 天；重新检查会更新结果和有效期。'
                except Exception:
                    note = '检查已完成，但 Redis 缓存保存失败；下次打开将重新检查。'
            report['cache_note'] = note
            return report

    async def cached_report(self, cached, request, scope):
        """Refresh development evidence while preserving the dated business checks."""
        artifact, error = await asyncio.to_thread(load_evidence)
        results_by_id = {}
        for row in cached['rows']:
            requirement = BY_ID[row['id']]
            declarations = [c for c in self.contributions if c.requirement == requirement.id] or [None]
            results = []
            for previous, contribution in zip(row['providers'], declarations, strict=True):
                checks = self.development(contribution, artifact, error, requirement.kind)
                checks.extend(item for item in previous['checks'] if item['phase'] == '数据')
                results.append(self.provider_result(contribution, checks, request))
            results_by_id[requirement.id] = results
        selected = required_ids(scope) if scope.scan == 'research' else set(BY_ID)
        self._checking, self._checked, self._current = False, len(selected), ''
        report = self.assemble_report(results_by_id, error or f"本版本测试证据：{artifact['checked_at']}", scope)
        report.update(checked_at=cached['checked_at'], cache_note=cached['cache_note'],
                      started_at=cached.get('started_at', ''), finished_at=cached.get('finished_at', ''))
        return report

    async def _run_report(self, request, scope):
        self._started_at = datetime.now(CHINA).isoformat()
        self._checking, self._checked, self._current = True, 0, ''
        self._progress_scope = scope
        results_by_id = {}
        for requirement in REQUIREMENTS:
            providers = [c for c in self.contributions if c.requirement == requirement.id]
            results_by_id[requirement.id] = [self.metadata_provider(requirement, c, {}, '功能测试证据读取中', request)
                                             for c in (providers or [None])]
        self._progress = self.assemble_report(results_by_id, '功能测试证据读取中', scope)
        try:
            artifact, artifact_error = await asyncio.to_thread(load_evidence)
            evidence = artifact_error or f"本版本测试证据：{artifact['checked_at']}"
            for requirement in REQUIREMENTS:
                providers = [c for c in self.contributions if c.requirement == requirement.id]
                results_by_id[requirement.id] = [self.metadata_provider(requirement, c, artifact, artifact_error, request)
                                                 for c in (providers or [None])]
            self._progress = self.assemble_report(results_by_id, evidence, scope)
            for requirement in REQUIREMENTS:
                if scope.scan == 'research' and requirement.id not in required_ids(scope):
                    continue
                self._current = requirement.title
                self._progress = self.assemble_report(results_by_id, evidence, scope)
                providers = [c for c in self.contributions if c.requirement == requirement.id]
                results_by_id[requirement.id] = [await self.provider_report(requirement, c, artifact, artifact_error, request)
                    if request is not None else await self.provider_report(requirement, c, artifact, artifact_error)
                    for c in (providers or [None])]
                self._checked += 1
                self._progress = self.assemble_report(results_by_id, evidence, scope)
            self._checking, self._current = False, ''
            self._progress = self.assemble_report(results_by_id, evidence, scope)
            return self._progress
        finally:
            self._checking, self._current = False, ''
            if self._progress is not None:
                self._progress = {**self._progress, 'checking': False, 'current_requirement': ''}

    def assemble_report(self, results_by_id, evidence, scope):
        rows = []
        for requirement in REQUIREMENTS:
            providers = [c for c in self.contributions if c.requirement == requirement.id]
            results = results_by_id[requirement.id]
            # Never combine partial passes from incompatible sources into a complete dataset.
            best = max(results, key=lambda p: (summarize(p['checks'])['usable'],
                       sum(accepted(x) for x in p['checks'] if x['phase'] == '数据')))
            checks = best['checks']
            development = [x for x in checks if x['phase'] == '开发']
            data = [x for x in checks if x['phase'] == '数据']
            rows.append(dict(id=requirement.id, title=requirement.title, category=requirement.category,
                priority=requirement.priority, kind=requirement.kind, specification=requirement, providers=results,
                source=best['source'], project=best['project'], page=best.get('page', ''), running=best['running'], checks=checks,
                registered=bool(providers), development=sum(x['status'] == 'pass' for x in development),
                development_total=len(development), data=sum(x['status'] == 'pass' for x in data),
                data_total=len(data), own_complete=bool(data) and all(accepted(x) for x in data),
                required=requirement.id in required_ids(scope),
                assessment=summarize(checks), scope=best.get('scope', '本数据源声明范围')))
        by_id = {row['id']: row for row in rows}
        def ready(ident, seen=frozenset()):
            row = by_id[ident]
            return ident not in seen and row['own_complete'] and all(
                ready(dep, seen | {ident}) for dep in row['specification'].dependencies)
        for row in rows:
            row['blockers'] = [BY_ID[dep].title for dep in row['specification'].dependencies if not ready(dep)]
            row['related'] = [BY_ID[dep].title for dep in row['specification'].related]
            row['complete'] = ready(row['id'])
            row['collection_state'] = ('已完成（声明范围）' if row['assessment']['integrity'] == '通过'
                else '有缺口' if row['assessment']['integrity'] == '有缺口' else '未核验')
            row['status'] = ('已验收' if row['complete'] else '未开发' if not row['registered']
                             else '有失败项' if any(c['status'] == 'fail' and c.get('blocking', True)
                                                   for c in row['checks'] if c['phase'] == '数据') else '待验收')
            if row['blockers']:
                row['assessment'].update(usable=False, use_state='依赖未满足')
        return {'rows': rows, 'checked_at': datetime.now(CHINA).isoformat(),
                'started_at': self._started_at,
                'finished_at': '' if self._checking else datetime.now(CHINA).isoformat(),
                'scope': scope.label(), 'research': research_summary(rows, scope),
                'test_evidence': evidence, 'checking': self._checking,
                'checked_requirements': self._checked,
                'total_requirements': len(required_ids(scope)) if scope.scan == 'research' else len(REQUIREMENTS),
                'current_requirement': self._current}

    async def stop(self):
        async with self._report_lock:
            self.context = None

    def health(self):
        return {'checks': len(self.contributions), 'requirements': len(REQUIREMENTS)}
