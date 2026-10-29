"""Offline, reviewable collection contracts; never execute source requests."""
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

RESOURCE = Path(__file__).with_name('rules.json')
TEXT_FIELDS = ('start', 'end', 'initial', 'incremental', 'recovery', 'fresh', 'limits',
               'job_key', 'source_file', 'scope', 'source', 'fingerprint_source')
LIST_FIELDS = ('datasets', 'tables', 'topics', 'fingerprint_namespaces')


def validate_rules(document):
    if document.get('schema') != 1 or not isinstance(document.get('tasks'), dict):
        raise ValueError('采集规则资源格式无效')
    for ident, rule in document['tasks'].items():
        for key in TEXT_FIELDS:
            if not isinstance(rule.get(key), str) or not rule[key].strip():
                raise ValueError(f'{ident}: 采集规则缺少 {key}')
        for key in LIST_FIELDS:
            values = rule.get(key)
            if (not isinstance(values, list) or not values or
                    any(not isinstance(v, str) or not v.strip() for v in values) or
                    len(set(values)) != len(values)):
                raise ValueError(f'{ident}: 采集规则列表无效 {key}')
        if not rule.get('requests'):
            raise ValueError(f'{ident}: 缺少请求契约')
        for request in rule['requests']:
            url = urlsplit(request.get('url', ''))
            transport = (request.get('method') in ('GET', 'POST') and url.scheme in ('http', 'https')
                         or request.get('method') == 'STREAM' and url.scheme == 'tls' and url.port is not None)
            if (not transport or not url.hostname or url.username or
                    url.password or
                    not request.get('purpose') or not isinstance(request.get('parameters'), list)):
                raise ValueError(f'{ident}: 请求契约无效')
            names = []
            for param in request['parameters']:
                if any(not isinstance(param.get(k), str) or not param[k].strip()
                       for k in ('name', 'value', 'meaning')):
                    raise ValueError(f'{ident}: 参数缺少名称、取值或含义')
                names.append(param['name'])
            if len(set(names)) != len(names):
                raise ValueError(f'{ident}: 参数重复')
    return document['tasks']


@lru_cache(maxsize=1)
def collection_rules():
    return validate_rules(json.loads(RESOURCE.read_text(encoding='utf-8')))


def rule_details(ident, cfg):
    """Project storage addresses from the active configuration, without I/O or secrets."""
    rule = collection_rules().get(ident)
    if rule is None:
        return None
    ns = cfg['redis']['namespace']
    storage = dict(namespace=ns, database=cfg['mysql']['database'],
        queue=f'{ns}:ingest', checkpoint=f"{ns}:checkpoint:{rule['job_key']}",
        progress=f"{ns}:archive:progress:{rule['job_key']}",
        fingerprints=[f"{ns}:archive:fingerprints:v1:{bucket}:{rule['fingerprint_source']}"
                      for bucket in rule['fingerprint_namespaces']],
        errors=f'{ns}:collection:errors:{ident}', archives=f'{ns}:collection:archives:{ident}',
        control=f'{ns}:collection:control:v1', tables=rule['tables'],
        state_table='collection_state', state_project=ident,
        settings_table='app_setting', intraday=None)
    if pool := rule.get('intraday_pool'):
        prefix = f'{ns}:yuanhang:intraday:{pool}'
        storage['intraday'] = dict(body=prefix + ':snapshots:<version>',
            keys=[prefix + suffix for suffix in (':snapshots', ':times', ':meta')],
            note='盘中快照只存 Redis，最多 72 小时且受容量限制；不入归档队列、不写 MySQL。日终数据按下列路径归档。')
    return {**rule, 'storage': storage}


def verify_registry(manager, tasks, tables, topics, *, rules=None):
    """Release-time exact ownership check; no live config or database access."""
    rules = collection_rules() if rules is None else rules
    if set(rules) != set(tasks):
        raise ValueError(f'采集规则任务覆盖不符: {sorted(set(rules) ^ set(tasks))}')
    contributions = manager.entries['dataset.astock'].plugin.contributions
    for ident, rule in rules.items():
        spec = tasks[ident]
        plugin = manager.entries[manager.providers[spec.capability]].plugin
        if rule.get('intraday_pool') != (getattr(plugin, 'pool', None)
                                       if getattr(plugin, 'intraday', False) else None):
            raise ValueError(f'{ident}: 盘中存储声明不一致')
        bound = [c for c in contributions if ident in c.projects.values()]
        if (rule['job_key'] != plugin.job_key or
                set(rule['datasets']) != {d for c in bound for d in c.datasets} or
                set(rule['fingerprint_namespaces']) != {c.namespace for c in bound}):
            raise ValueError(f'{ident}: 规则与正式入队/归档登记不一致')
        from types import SimpleNamespace
        def declared_source(contribution):
            resolver = getattr(contribution.mapping, 'fingerprint_source', None)
            if resolver:
                envelope = SimpleNamespace(source=rule['source'], dataset=plugin.dataset,
                                           job_key=plugin.job_key)
                return resolver(envelope)
            return getattr(contribution.mapping, 'FINGERPRINT_SOURCE', rule['source'])
        if any(declared_source(c) != rule['fingerprint_source'] for c in bound):
            raise ValueError(f'{ident}: 摘要来源不一致')
        if not set(rule['tables']) <= set(tables) or not set(rule['topics']) <= set(topics):
            raise ValueError(f'{ident}: 规则表或说明主题不存在')
        expected = 'src/' + type(plugin).__module__.replace('.', '/') + '.py'
        if rule['source_file'] != expected:
            raise ValueError(f'{ident}: 来源实现路径不一致')
