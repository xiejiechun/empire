"""Static UI size and shell/control boundaries, independent of UI file location."""
import json
from pathlib import Path

from scripts.architecture_contract import import_edges, module_metadata, read_modules


def check_ui_architecture(root: Path, policy=None) -> list[str]:
    if policy is None:
        policy = json.loads((root / 'docs/architecture-contract.json').read_text('utf-8'))
    modules = read_modules(root)
    metadata, errors = module_metadata(modules, policy)
    edges, import_errors = import_edges(modules)
    errors.extend(import_errors)
    selected = {name for name in modules
                if name == 'empire.desktop' or name.startswith('empire.desktop.')
                or name == 'empire.plugins.ui' or name.startswith('empire.plugins.ui.')
                or metadata.get(name, {}).get('role') in {'ui', 'shared_ui'}}
    for name in sorted(selected):
        module = modules[name]
        contents = module.path.read_text('utf-8-sig')
        if len(contents.splitlines()) > 350:
            errors.append(f'{name}: Split UI responsibilities before growing beyond 350 lines')
        if module.path.name == 'tasks.py' and ('"sina-news"' in contents or '"cninfo-calendar"' in contents):
            errors.append(f'{name}: task form must not hard-code source task identities')
    for edge in edges:
        if edge.source not in selected:
            continue
        source = metadata.get(edge.source, {})
        target = metadata.get(edge.target, {})
        business = policy.get('owners', {}).get(target.get('owner'), {}).get('kind') == 'business'
        plugin = edge.target == 'empire.plugins' or edge.target.startswith('empire.plugins.')
        shell = edge.source == 'empire.desktop' or edge.source.startswith('empire.desktop.')
        common = edge.source == 'empire.plugins.ui.common'
        location = f'{edge.source}:{edge.line}'
        if shell and (plugin or business):
            errors.append(f'{location}: desktop shell imports plugin/business implementation {edge.target}')
        if common and (plugin or business):
            errors.append(f'{location}: common controls import plugin/business implementation {edge.target}')
        if source.get('role') == 'shared_ui' and business:
            errors.append(f'{location}: shared UI imports business implementation {edge.target}')
        if edge.target == 'empire.plugins.ui.collection':
            errors.append(f'{location}: shared controls must not be imported from the collection page')
        if edge.target == 'empire.features.data_browser.catalog' and set(edge.names) - {'DataCatalogPage'}:
            errors.append(f'{location}: catalog only exposes DataCatalogPage to other UI modules')
    return sorted(set(errors))
