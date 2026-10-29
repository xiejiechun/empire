"""Exact reviewed removals; immutable historical baselines remain unchanged."""
import copy


def declarations(features):
    result = [c for c in features or [] if c.get('path', '').startswith('retirement.')]
    if len({c['path'] for c in result}) != len(result):
        raise ValueError('Duplicate retirement')
    for c in result:
        if (set(c) != {'path', 'before', 'after', 'design', 'tests'} or c['after'] is not None
                or set(c['before']) != {'semantic', 'bindings', 'order'} or not c['tests']):
            raise ValueError('Retirement requires exact prior declarations and verification')
    return result


def semantic_baseline(baseline, current, features, root):
    result = copy.deepcopy(baseline)
    for change in declarations(features):
        for path in [change['design'], *change['tests']]:
            if not (root/path).resolve().is_relative_to(root.resolve()) or not (root/path).is_file():
                raise ValueError('Retirement evidence missing')
        for domain in ('semantic', 'bindings'):
            for group, entries in change['before'][domain].items():
                for key, value in entries.items():
                    if result[domain][group].get(key) != value or key in current[domain][group]:
                        raise ValueError('Retirement differs from reviewed identity: ' + key)
                    del result[domain][group][key]
    return result


def order_inputs(baseline, features):
    baseline, features = copy.deepcopy(baseline), copy.deepcopy(features)
    for change in declarations(features):
        for group, entries in change['before']['order'].items():
            if [v for v in baseline[group] if v in entries] != entries:
                raise ValueError('Retirement order differs from historical baseline')
            baseline[group] = [v for v in baseline[group] if v not in entries]
            if group == 'startup':
                for item in features:
                    if item['path'] == 'order.startup':
                        for side in ('before', 'after'):
                            item[side] = [v for v in item[side] if v not in entries]
    return baseline, features
