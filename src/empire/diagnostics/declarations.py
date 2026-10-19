"""Read existing contributions and select existing bounded formal query methods."""
import inspect
import re
from dataclasses import asdict
from datetime import datetime

from empire.contracts.market_storage import SERIES
from empire.contracts.preparation_catalog import BY_ID
from empire.core.time import CHINA
from empire.diagnostics.readonly import DiagnosticLimit


def project_declaration(cfg, project, manager=None):
    if not isinstance(project, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', project):
        raise ValueError('项目 ID 格式无效')
    if manager is None:
        from empire.bootstrap import build_manager
        manager = build_manager(cfg)  # Declarations only. Never start this manager.
    if any(getattr(entry, 'context', None) is not None
           or getattr(entry, 'state', 'STOPPED') != 'STOPPED' for entry in manager.entries.values()):
        raise ValueError('诊断只接收未启动的声明管理器；运行状态请单独传 Runtime.snapshot')
    control = manager.entries[manager.providers['collection.control']].plugin
    if project not in control.definitions:
        raise ValueError('未登记的采集项目')
    task = control.definitions[project]
    collector = manager.entries[manager.providers[task.capability]].plugin
    catalog = manager.entries[manager.providers['dataset.catalog']].plugin
    contributions = [c for c in catalog.contributions if project in c.projects.values()]
    jobs = sorted({job for c in contributions for job, owner in c.projects.items() if owner == project})
    declarations = [(p, c) for entry in manager.entries.values() for p in (entry.plugin,)
                    for c in getattr(p, 'preparation', ()) if c.project_id == project]
    query_plugins = {c.capability: p for p, c in declarations}
    # Older sources such as news own a schema capability on the formal query
    # plugin. Follow the existing dependency, rather than another project map.
    for cap in collector.manifest.requires:
        provider = manager.entries[manager.providers[cap]].plugin
        if provider.manifest.id.startswith('data.'):
            for provided in provider.manifest.provides:
                if provided.endswith('.query'):
                    query_plugins.setdefault(provided, provider)
    scope = [{**asdict(BY_ID[c.requirement]), 'capability': c.capability,
              'dataset': c.dataset} for _, c in declarations]
    return {'project_id': project, 'task': asdict(task), 'job_keys': jobs,
            'datasets': sorted({d for c in contributions for d in c.datasets}),
            'declared_scope': scope or [{'description': task.description,
                                        'note': '该来源未登记独立 preparation 范围，不能推断全历史完整'}]}, query_plugins


def query_preview(plugin, security='', day=''):
    """Return a call to a formal public reader, with its actual bounded scope."""
    day = day or datetime.now(CHINA).date().isoformat()
    if hasattr(plugin, 'month'):
        return 'month', {'month': day[:7]}
    if hasattr(plugin, 'archived_date'):
        if not security:
            raise DiagnosticLimit('证券日查询需要 --security 证券身份；未执行全历史扫描')
        kwargs = {'market': security[-2:], 'code': security[:6], 'trade_date': day}
        if getattr(plugin, 'kind', None) in SERIES and hasattr(plugin, 'page'):
            return 'page', {**kwargs, 'limit': 20}
        if getattr(plugin, 'kind', None) == 'quote' and hasattr(plugin, 'day'):
            return 'day', kwargs
        raise DiagnosticLimit('该正式预览没有可用的定日 reader；未改查最新日期，请使用对应数据页面')
    methods = ('browse', 'list_records', 'list_events', 'list_plans', 'list_rules',
               'list_news', 'list_statement_securities', 'directory', 'candidates')
    for name in methods:
        if not hasattr(plugin, name):
            continue
        parameters = inspect.signature(getattr(plugin, name)).parameters
        if any(p.default is inspect.Parameter.empty for p in parameters.values()):
            continue
        kwargs = {'limit': 20} if 'limit' in parameters else {}
        if 'include_total' in parameters:
            kwargs['include_total'] = False
        if security:
            if 'code' in parameters:
                # Legacy financial selectors and explicit market/code APIs use
                # six digits. New event/report readers accept the canonical key.
                kwargs['code'] = (security[:6] if 'market' in parameters
                                  or name == 'list_statement_securities' else security)
            if 'market' in parameters:
                kwargs['market'] = security[-2:]
            if name == 'candidates':
                kwargs['search'] = security[:6]
            if 'code' not in parameters and 'market' not in parameters and name != 'candidates':
                raise DiagnosticLimit('该正式预览不接受股票身份筛选；请省略 --security 或使用对应页面')
        if 'start' in parameters and 'end' in parameters:
            kwargs.update(start=day, end=day)
        return name, kwargs
    raise DiagnosticLimit('本项目未提供可自动调用的有界正式预览；请使用对应数据页面的范围查询')
