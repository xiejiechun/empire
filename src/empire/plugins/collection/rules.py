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
            if (url.scheme not in ('http', 'https') or not url.hostname or url.username or
                    url.password or request.get('method') not in ('GET', 'POST') or
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


def verify_registry(manager, tasks, tables, topics, *, rules=None):
    """Release-time exact ownership check; no live config or database access."""
    rules = collection_rules() if rules is None else rules
    if set(rules) != set(tasks):
        raise ValueError(f'采集规则任务覆盖不符: {sorted(set(rules) ^ set(tasks))}')
    contributions = manager.entries['dataset.astock'].plugin.contributions
    for ident, rule in rules.items():
        spec = tasks[ident]
        plugin = manager.entries[manager.providers[spec.capability]].plugin
        bound = [c for c in contributions if ident in c.projects.values()]
        if (rule['job_key'] != plugin.job_key or
                set(rule['datasets']) != {d for c in bound for d in c.datasets} or
                set(rule['fingerprint_namespaces']) != {c.namespace for c in bound}):
            raise ValueError(f'{ident}: 规则与正式入队/归档登记不一致')
        if any(getattr(c.mapping, 'FINGERPRINT_SOURCE', rule['source']) != rule['fingerprint_source']
               for c in bound):
            raise ValueError(f'{ident}: 摘要来源不一致')
        if not set(rule['tables']) <= set(tables) or not set(rule['topics']) <= set(topics):
            raise ValueError(f'{ident}: 规则表或说明主题不存在')
        expected = 'src/' + type(plugin).__module__.replace('.', '/') + '.py'
        if rule['source_file'] != expected:
            raise ValueError(f'{ident}: 来源实现路径不一致')
