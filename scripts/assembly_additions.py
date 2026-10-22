"""Exact reviewed new-feature additions; existing identities remain immutable."""
from pathlib import Path


def additions(baseline, current, features, root):
    seen = set()
    for change in features:
        if not change.get('path', '').startswith('addition.'):
            continue
        if (set(change) != {'path', 'before', 'after', 'design', 'tests'} or change['before'] is not None
                or not isinstance(change['after'], dict) or set(change['after']) != {'semantic', 'bindings'}
                or change['path'] in seen or not change['tests']):
            raise ValueError('Feature addition requires exact new declarations, bindings, design and tests')
        seen.add(change['path'])
        for filename in [change['design'], *change['tests']]:
            path = (root / filename).resolve()
            if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
                raise ValueError('Feature addition design and tests must exist inside the repository')
        for section, groups in change['after'].items():
            if not isinstance(groups, dict) or not groups:
                raise ValueError('Feature addition is empty')
            for group, entries in groups.items():
                if group not in baseline[section] or not isinstance(entries, dict) or not entries:
                    raise ValueError('Feature addition group is invalid')
                for identity, declaration in entries.items():
                    if identity in baseline[section][group] or current[section][group].get(identity) != declaration:
                        raise ValueError('Feature addition replaces existing identity or differs from exact declaration')
                    baseline[section][group][identity] = declaration
    return baseline


def order_additions(features):
    result = {k: set() for k in ('plugins', 'startup', 'tasks', 'datasets', 'pages', 'preparation')}
    for change in features or []:
        if change.get('path', '').startswith('addition.') and change.get('before') is None:
            for group, rows in change['after']['semantic'].items():
                result[group].update(rows)
                if group == 'plugins':
                    result['startup'].update(rows)
    return result
