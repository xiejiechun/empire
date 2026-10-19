"""Single explicit feature allowlist and cross-contribution ownership checks."""
from empire.contracts.bundle import FeatureBundle, ordered
from empire.contracts.preparation import ComputationContribution
from empire.core.identity import safe_project_id
from empire.features.financial_statements.bundle import bundle as financial_statements_bundle
from empire.features.holders.bundle import bundle as holders_bundle
from empire.features.index_prices.bundle import bundle as index_prices_bundle
from empire.features.indices.bundle import bundle as indices_bundle
from empire.features.industries.bundle import bundle as industries_bundle
from empire.features.news.bundle import bundle as news_bundle
from empire.features.remaining import bundle as remaining_bundle

FACTORIES = (remaining_bundle, news_bundle, holders_bundle, financial_statements_bundle, indices_bundle, industries_bundle, index_prices_bundle)


def builtin_bundles(cfg) -> tuple[FeatureBundle, ...]:
    result = tuple(factory(cfg) for factory in FACTORIES)
    seen = set()
    for bundle in result:
        if bundle.id in seen:
            raise ValueError(f'业务包重复: {bundle.id}')
        seen.add(bundle.id)
    return result


def ordered_contributions(bundles, domain):
    if domain not in ('plugins', 'tasks', 'datasets'):
        raise ValueError('未知贡献排序域')
    return ordered(((bundle.id, item) for bundle in bundles for item in getattr(bundle, domain)), domain)


def dataset_contributions(cfg):
    """Read the same builtin dataset declarations without implicit catalog defaults."""
    return ordered_contributions(builtin_bundles(cfg), 'datasets')


def validate_ownership(bundles, manager):
    """Only inspect constructed declarations; never start plugins or read files."""
    jobs, projects, used = {}, {}, set()
    tasks = {}

    def publisher(owner, project, job, entrypoint):
        if (not isinstance(project, str) or not isinstance(job, str) or not project or not job
                or safe_project_id(project) != project or safe_project_id(job) != job):
            raise ValueError(f'{owner}: 发布者须声明精确 project/job')
        if project in projects or job in jobs:
            raise ValueError(f'{owner}: 发布者项目或 job 重复: {project}/{job}')
        jobs[job] = (owner, project, entrypoint)
        projects[project] = (owner, job)

    for bundle in bundles:
        plugins = {item.value.manifest.id: item.value for item in bundle.plugins}
        for item in bundle.tasks:
            task = item.value
            provider = manager.providers.get(task.capability)
            if provider not in plugins:
                raise ValueError(f'{bundle.id}/{task.id}: 采集能力不属于本业务包: {task.capability}')
            plugin = manager.entries[provider].plugin
            if plugin is not plugins[provider] or getattr(plugin, 'project_id', None) != task.id:
                raise ValueError(f'{bundle.id}/{task.id}: 任务与采集发布者项目不符')
            publisher(bundle.id, task.id, getattr(plugin, 'job_key', None), provider)
            tasks[task.id] = task
        for maintenance in bundle.maintenance_publishers:
            publisher(bundle.id, maintenance.project_id, maintenance.job_key, maintenance.entrypoint)

    catalog = manager.entries[manager.providers['dataset.catalog']].plugin
    for bundle in bundles:
        for item in bundle.datasets:
            contribution = item.value
            if not contribution.projects:
                raise ValueError(f'{bundle.id}/{contribution.namespace}: 数据贡献缺少发布者归属')
            for job, project in contribution.projects.items():
                publisher_info = jobs.get(job)
                if publisher_info is None or publisher_info[:2] != (bundle.id, project):
                    raise ValueError(f'{bundle.id}/{contribution.namespace}: 数据归属不符: {job}/{project}')
                used.add(job)
        for item in bundle.plugins:
            plugin = item.value
            for declaration in getattr(plugin, 'preparation', ()):
                if declaration.capability not in plugin.manifest.provides:
                    raise ValueError(f'{bundle.id}: 准备查询能力不属于声明插件: {declaration.capability}')
                if isinstance(declaration, ComputationContribution):
                    continue
                task = tasks.get(declaration.project_id)
                contribution = catalog.datasets.get(declaration.dataset)
                publisher_info = jobs.get(declaration.job_key)
                if (task is None or task.capability != declaration.collector
                        or contribution is None
                        or contribution.projects.get(declaration.job_key) != declaration.project_id
                        or publisher_info is None
                        or publisher_info[:2] != (bundle.id, declaration.project_id)):
                    raise ValueError(f'{bundle.id}: 准备声明与采集/归档归属不符: {declaration.project_id}')
    unused = set(jobs) - used
    if unused:
        raise ValueError(f'发布者没有对应数据贡献: {sorted(unused)}')
