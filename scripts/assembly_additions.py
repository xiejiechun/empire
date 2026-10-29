"""Exact new-feature declarations; never permit changes to baseline identities."""
import re


def additions(features):
    return [c for c in features or [] if isinstance(c, dict)
            and str(c.get('path', '')).startswith(('additive.', 'service.', 'management.', 'computation.'))]


def validate(change):
    if (set(change) != {'path', 'before', 'after', 'design', 'tests'} or change['before'] is not None
            or not re.fullmatch(r'(additive|service|management|computation)\.[a-z][a-z0-9_]*', change['path'])
            or not isinstance(change['after'], dict) or set(change['after']) != {'semantic', 'bindings', 'order'}):
        raise ValueError('Invalid exact additive feature declaration')
    value = change['after']
    if (set(value['semantic']) != {'plugins', 'tasks', 'datasets', 'pages'}
            or set(value['bindings']) != {'plugins', 'datasets', 'pages'}
            or set(value['order']) != {'plugins', 'startup', 'tasks', 'datasets', 'pages'}):
        raise ValueError('Additive feature groups must be explicit')
    owner = change['path'].split('.')[1]
    service = change['path'].startswith('service.')
    management = change['path'].startswith('management.')
    computation = change['path'].startswith('computation.')
    if computation and (not value['semantic']['plugins'] or not value['semantic']['pages']
                        or any(value['semantic'][g] for g in ('tasks', 'datasets'))):
        raise ValueError('Computation additions require query/UI plugins and pages only')
    if management and (not value['semantic']['plugins'] or not value['semantic']['pages']
                       or any(value['semantic'][g] for g in ('tasks', 'datasets'))):
        raise ValueError('Management additions require plugins/pages only')
    if service and (not value['semantic']['plugins'] or any(value['semantic'][g]
                    for g in ('tasks', 'datasets', 'pages'))):
        raise ValueError('Source service additions must contain only plugins')
    for group, items in value['semantic'].items():
        if not isinstance(items, dict) or (not service and not management and not computation
                                          and group != 'pages' and not items):
            raise ValueError('Additive feature groups must contain exact identities')
        ordered = value['order'][group]
        if (not isinstance(ordered, list) or len(ordered) != len(set(ordered)) or set(ordered) != set(items)):
            raise ValueError('Additive feature ordering differs from declarations')
    if value['order']['startup'] != value['order']['plugins']:
        raise ValueError('Additive startup must preserve declared plugin order')
    for group, items in value['bindings'].items():
        if set(items) != set(value['semantic'][group]):
            raise ValueError('Additive implementation bindings are incomplete')
        for binding in items.values():
            if management:
                allowed = {'empire.plugins.collection.' + owner, 'empire.plugins.ui.' + owner}
                if binding['module'] not in allowed or (group == 'pages' and
                        binding['module'] != 'empire.plugins.ui.' + owner):
                    raise ValueError('Management binding belongs to another owner')
                continue
            if (binding['module'] != 'empire.sources.' + owner if service else
                    not binding['module'].startswith('empire.features.' + owner + '.')):
                raise ValueError('Additive feature binding belongs to another owner')
    if service and any(not ident.startswith('source.') for ident in value['semantic']['plugins']):
        raise ValueError('Source service additions require source plugin identities')
    if management and any(ident not in {'collection.' + owner, 'ui.' + owner}
                          for ident in value['semantic']['plugins']):
        raise ValueError('Management additions require exact management plugin identities')
    if computation and set(value['semantic']['plugins']) != {'data.' + owner, 'ui.' + owner}:
        raise ValueError('Computation additions require exact query/UI identities')
    return value


def apply(features, semantic, bindings, current, root):
    seen = set()
    for change in additions(features):
        value = validate(change)
        if change['path'] in seen:
            raise ValueError('Duplicate additive feature')
        seen.add(change['path'])
        if (not isinstance(change['tests'], list) or not change['tests']
                or any(not isinstance(p, str) or not (root / p).resolve().is_relative_to(root.resolve())
                       or not (root / p).is_file() for p in [change['design'], *change['tests']])):
            raise ValueError('Additive feature needs independent design and tests')
        for domain, target in (('semantic', semantic), ('bindings', bindings)):
            for group, items in value[domain].items():
                if set(items) & set(target[group]):
                    raise ValueError('Additive feature cannot change existing identities')
                if any(current[domain][group].get(k) != v for k, v in items.items()):
                    raise ValueError('Additive feature differs from reviewed exact declaration')
                target[group].update(items)


def ordered_additions(features, key):
    result = []
    for change in additions(features):
        result.extend(validate(change)['order'].get(key, []))
    if len(result) != len(set(result)):
        raise ValueError('Duplicate additive ordered identity')
    return result
