"""Require offline coverage and an explicit review after product changes."""
import argparse
import ast
import hashlib
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from .documentation_build import check_generated, compile_help
    from .documentation_storage import storage_snapshots, verify_storage
else:
    from documentation_build import check_generated, compile_help
    from documentation_storage import storage_snapshots, verify_storage

INDEX = "docs/documentation-coverage.json"
REVIEW = "docs/documentation-review.json"
RULES = "src/empire/plugins/collection/rules.json"


def product_sources(root: Path) -> dict[str, str]:
    files = set((root / "src/empire").rglob("*.py"))
    files.update((root / 'src/empire').rglob('*.js'))
    files.add(root / RULES)
    files.update((root / "scripts").glob("*.py"))
    files.update((root / "sql").rglob("*.sql"))
    files.update((root / "sql").rglob("*.json"))
    files.update(root / item for item in ("config/app.example.toml", "Empire.spec"))
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)}


def content_digest(root: Path, coverage: dict) -> str:
    digest = hashlib.sha256()
    authority = compile_help(root).inputs
    for name in sorted({*authority, INDEX, RULES, *coverage["guides"]}):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def declarations(root: Path):
    from empire.bootstrap import build_manager
    from empire.plugins.ui.plugin import UiPlugin

    cfg = tomllib.loads((root / "config/app.example.toml").read_text(encoding="utf-8"))
    manager = build_manager(cfg)
    pages = {page.id: entry.plugin for entry in manager.entries.values()
             if isinstance(entry.plugin, UiPlugin) for page in entry.plugin.create_pages()}
    tasks = manager.entries["collection.control"].plugin.definitions
    return manager, pages, tasks


def reachable_sources(root: Path, modules: list[str]) -> dict[str, str]:
    """Follow finite, static business imports without importing their code.

    Package initializers and their ordinary reexports are source inputs too.
    Imports in functions/type-only blocks conservatively count as dependencies.
    Dynamic import policy remains the architecture contract's responsibility.
    """
    roots = ('empire.plugins.collectors', 'empire.plugins.data',
             'empire.plugins.datasets', 'empire.plugins.ui', 'empire.contracts',
             'empire.features', 'empire.sources')
    result, seen = {}, set()
    pending = list(modules)
    while pending:
        module = pending.pop().removesuffix('.__init__')
        if module in seen:
            continue
        seen.add(module)
        parts = module.split('.')
        if not all(part.isidentifier() for part in parts):
            raise ValueError('Invalid documentation source module: ' + module)
        base = root / 'src' / Path(*parts)
        candidates = [path for path in (base.with_suffix('.py'), base / '__init__.py')
                      if path.is_file()]
        if len(candidates) > 1:
            raise ValueError('Ambiguous documentation source module/package: ' + module)
        if not candidates:
            # A from-import candidate may be an exported symbol, or an implicit
            # namespace package; its explicit child module is queued separately.
            continue
        path = candidates[0]
        package = parts if path.name == '__init__.py' else parts[:-1]
        name = path.relative_to(root).as_posix()
        contents = path.read_bytes()
        result[name] = hashlib.sha256(contents).hexdigest()
        if module == 'empire.contracts.business_schema':
            resource = 'sql/business-schema.json'
            result[resource] = hashlib.sha256((root / resource).read_bytes()).hexdigest()
        # Importing a child executes each available parent initializer. Include
        # them even when the original import named only the deepest module.
        for count in range(1, len(parts)):
            if (root / 'src' / Path(*parts[:count]) / '__init__.py').is_file():
                pending.append('.'.join(parts[:count]))
        for node in ast.walk(ast.parse(contents.decode('utf-8-sig'))):
            imports = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):
                        raise ValueError(f'{name}:{node.lineno}: relative import escapes package')
                    parent = '.'.join(package[:len(package) - node.level + 1])
                    target = parent + ('.' + node.module if node.module else '')
                else:
                    target = node.module or ''
                imports = [target, *(target + '.' + alias.name for alias in node.names
                                     if alias.name != '*')]
            elif isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            pending.extend(value for value in imports
                           if any(value == allowed or value.startswith(allowed + '.')
                                  for allowed in roots))
    return dict(sorted(result.items()))


def feature_snapshots(root: Path, coverage: dict) -> dict:
    manager, pages, tasks = declarations(root)
    bundle = compile_help(root)
    article_map = {a.title: a for a in bundle.articles}
    result = {}
    for kind, entries in (("page", pages), ("task", tasks)):
        for ident, value in entries.items():
            plugin = value if kind == "page" else manager.entries[manager.providers[value.capability]].plugin
            titles = coverage["pages" if kind == "page" else "tasks"][ident]
            digest = hashlib.sha256()
            for title in sorted(titles):
                article = article_map[title]
                digest.update((article.title + article.summary + article.group + article.body).encode())
            if kind == 'task':
                rules = json.loads((root / RULES).read_text(encoding='utf-8'))['tasks']
                digest.update(json.dumps(rules[ident], sort_keys=True, ensure_ascii=False).encode())
            result[f"{kind}:{ident}"] = {
                "sources": reachable_sources(root, [type(plugin).__module__]),
                "content_sha256": digest.hexdigest(),
                "documentation": {title: bundle.origins[title] for title in titles},
            }
    storage = storage_snapshots(root, coverage['storage'], article_map, reachable_sources)
    for kind in ('mysql', 'redis'):
        for ident, entry in coverage['storage'][kind].items():
            title = entry['topic']
            storage[f'{kind}:{ident}']['documentation'] = {title: bundle.origins[title]}
    result.update(storage)
    return result


def verify_coverage(root: Path) -> dict:
    coverage = json.loads((root / INDEX).read_text(encoding="utf-8"))
    bundle = check_generated(root)
    articles = {item.title: item for item in bundle.articles}
    # Construct declarations only; never start plugins or connect to services.
    manager, page_plugins, tasks = declarations(root)
    pages = set(page_plugins)
    if pages != set(coverage["pages"]):
        raise RuntimeError(f"文档页面登记不一致，新增或退役页面须同步说明：{sorted(pages ^ set(coverage['pages']))}")
    if set(tasks) != set(coverage.get("tasks", {})):
        raise RuntimeError("文档采集任务登记不一致；没有独立数据页的任务也须说明")
    for page, titles in coverage["pages"].items():
        if not titles or any(title not in articles for title in titles):
            raise RuntimeError(f"页面缺少有效说明主题：{page}")
        if all(articles[title].category in ("技术参考", "数据库参考") for title in titles):
            raise RuntimeError(f"页面只有技术参考，缺少操作或数据说明：{page}")
        if len(set(titles)) != len(titles):
            raise RuntimeError(f"页面重复登记说明主题：{page}")
        contribution = next(item for item in page_plugins[page].create_pages() if item.id == page)
        if contribution.catalogued and not any(articles[title].category == "数据说明" for title in titles):
            raise RuntimeError(f"数据页面缺少数据范围说明：{page}")
    for ident, titles in coverage["tasks"].items():
        if (not titles or len(set(titles)) != len(titles)
                or any(title not in articles for title in titles)
                or not any(articles[title].category == "数据说明" for title in titles)):
            raise RuntimeError(f"采集任务缺少独立数据范围说明：{ident}")
    for guide in coverage["guides"]:
        if not (root / guide).is_file():
            raise RuntimeError(f"缺少正式指南：{guide}")
    verify_storage(root, coverage, articles)
    from empire.plugins.collection.rules import validate_rules, verify_registry
    rules = validate_rules(json.loads((root / RULES).read_text(encoding='utf-8')))
    verify_registry(manager, tasks, coverage['storage']['mysql'], articles, rules=rules)
    if any(rule['topics'] != coverage['tasks'][ident] for ident, rule in rules.items()):
        raise ValueError('采集规则与正式任务说明关联不一致')
    return coverage


def verify_review(root: Path) -> None:
    coverage = verify_coverage(root)
    review = json.loads((root / REVIEW).read_text(encoding="utf-8"))
    if review.get("schema") != 3:
        raise RuntimeError("须通过显式 review 建立按功能审阅记录")
    current = product_sources(root)
    previous = review["sources"]
    changed = sorted(name for name in current.keys() | previous.keys()
                     if current.get(name) != previous.get(name))
    if (changed or review["content_sha256"] != content_digest(root, coverage)
            or review.get("features") != feature_snapshots(root, coverage)):
        raise RuntimeError("文档审阅已过期。补齐说明并执行 scripts/documentation_contract.py review --note <本次审阅说明>；"
                           f"变动文件：{', '.join(changed[:12]) or '说明内容'}")
    if not review.get("note", "").strip():
        raise RuntimeError("文档审阅缺少说明")


def record_review(root: Path, note: str, unchanged_reason: str = "", *, exceptions=None) -> None:
    coverage = verify_coverage(root)
    target = root / REVIEW
    current = product_sources(root)
    digest = content_digest(root, coverage)
    features = feature_snapshots(root, coverage)
    exceptions = exceptions or {}
    if any(key not in features or len(reason.strip()) < 12 for key, reason in exceptions.items()):
        raise ValueError("逐项豁免须使用真实 page:/task:/mysql:/redis: 身份并填写具体理由（至少12字）")
    if not note.strip():
        raise ValueError("必须填写实际审阅说明")
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8"))
        stale = [key for key, feature in features.items()
                 if key in previous.get("features", {})
                 and feature["sources"] != previous["features"][key]["sources"]
                 and feature["content_sha256"] == previous["features"][key]["content_sha256"]
                 and key not in exceptions]
        if stale:
            raise RuntimeError("受影响功能的说明未更新，修改无关文章不能通过：" + ", ".join(stale))
        if previous["sources"] != current and previous["content_sha256"] == digest and not unchanged_reason.strip():
            raise RuntimeError("源码已改变但说明未更新；须补齐说明，或用 --unchanged-reason 记录无需变更用户说明的具体原因")
    value = {"schema": 3, "reviewed_at": datetime.now(UTC).isoformat(), "note": note,
             "unchanged_reason": unchanged_reason, "exceptions": exceptions,
             "sources": current, "content_sha256": digest, "features": features}
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "review"))
    parser.add_argument("--note", default="")
    parser.add_argument("--unchanged-reason", default="")
    parser.add_argument("--unchanged", action="append", default=[], metavar="FEATURE=REASON")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.action == "review":
        if any("=" not in item for item in args.unchanged):
            parser.error("--unchanged 须为 page:ID=理由 或 task:ID=理由")
        record_review(root, args.note, args.unchanged_reason,
                      exceptions=dict(item.split("=", 1) for item in args.unchanged))
    else:
        verify_review(root)
    print("PASS offline documentation coverage and review")
