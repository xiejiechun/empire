"""Single explicit feature allowlist and cross-contribution ownership checks."""
from empire.contracts.bundle import FeatureBundle, ordered
from empire.contracts.preparation import ComputationContribution
from empire.core.identity import safe_project_id
from empire.features.adjustment.bundle import bundle as adjustment_bundle
from empire.features.calendar.bundle import bundle as calendar_bundle
from empire.features.capital_actions.bundle import bundle as capital_actions_bundle
from empire.features.data_browser.bundle import bundle as data_browser_bundle
from empire.features.financial_statements.bundle import bundle as financial_statements_bundle
from empire.features.holders.bundle import bundle as holders_bundle
from empire.features.index_prices.bundle import bundle as index_prices_bundle
from empire.features.indices.bundle import bundle as indices_bundle
from empire.features.industries.bundle import bundle as industries_bundle
from empire.features.kaipanla.bundle import bundle as kaipanla_bundle
from empire.features.listing_status.bundle import bundle as listing_status_bundle
from empire.features.listings.bundle import bundle as listings_bundle
from empire.features.name_changes.bundle import bundle as name_changes_bundle
from empire.features.unlocks.bundle import bundle as unlocks_bundle
from empire.features.unlock_industries.bundle import bundle as unlock_industries_bundle
from empire.features.news.bundle import bundle as news_bundle
from empire.features.remaining import bundle as remaining_bundle
from empire.features.security_aliases.bundle import bundle as security_aliases_bundle
from empire.features.st_events.bundle import bundle as st_events_bundle
from empire.features.stocks.bundle import bundle as stocks_bundle
from empire.features.suspensions.bundle import bundle as suspensions_bundle
from empire.features.ths_capital.bundle import bundle as ths_capital_bundle

FACTORIES = (remaining_bundle, news_bundle, holders_bundle, financial_statements_bundle, indices_bundle, industries_bundle, index_prices_bundle, stocks_bundle, calendar_bundle, suspensions_bundle, data_browser_bundle, kaipanla_bundle, capital_actions_bundle, adjustment_bundle, ths_capital_bundle, listings_bundle, listing_status_bundle, security_aliases_bundle, name_changes_bundle, st_events_bundle, unlocks_bundle, unlock_industries_bundle)


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


def confirmation_handlers(bundles):
    """Resolve exact dataset-owned callbacks without starting a provider."""
    declarations, required = {}, {}
    for bundle in bundles:
        for item in bundle.confirmations:
            if item.id in declarations:
                raise ValueError('归档确认贡献重复: ' + item.id)
            declarations[item.id] = (bundle.id, item.handler)
        for item in bundle.datasets:
            identity = item.value.confirmation
            if identity:
                if identity in required and required[identity] != bundle.id:
                    raise ValueError('归档确认需求跨业务冲突: ' + identity)
                required[identity] = bundle.id
    if declarations.keys() != required.keys():
        raise ValueError('归档确认贡献缺失或没有对应数据集: ' +
                         ', '.join(sorted(declarations.keys() ^ required.keys())))
    for identity, owner in required.items():
        if declarations[identity][0] != owner:
            raise ValueError('归档确认贡献不属于数据集业务: ' + identity)
    return {identity: value[1] for identity, value in declarations.items()}
