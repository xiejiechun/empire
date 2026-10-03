"""Require offline coverage and an explicit review after product changes."""
import argparse
import hashlib
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from empire.plugins.ui.help_content import read_articles

INDEX = "docs/documentation-coverage.json"
REVIEW = "docs/documentation-review.json"
REFERENCE = "src/empire/plugins/ui/storage_reference.md"


def product_sources(root: Path) -> dict[str, str]:
    files = set((root / "src/empire").rglob("*.py"))
    files.update((root / 'src/empire').rglob('*.js'))
    files.update((root / "scripts").glob("*.py"))
    files.update((root / "sql").rglob("*.sql"))
    files.update(root / item for item in ("config/app.example.toml", "Empire.spec"))
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)}


def content_digest(root: Path, coverage: dict) -> str:
    digest = hashlib.sha256()
    for name in sorted({REFERENCE, INDEX, *coverage["guides"]}):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def verify_coverage(root: Path) -> dict:
    from empire.bootstrap import build_manager
    from empire.plugins.ui.plugin import UiPlugin

    coverage = json.loads((root / INDEX).read_text(encoding="utf-8"))
    articles = {item.title: item for item in read_articles(root / REFERENCE)}
    # Construct declarations only; never start plugins or connect to services.
    cfg = tomllib.loads((root / "config/app.example.toml").read_text(encoding="utf-8"))
    manager = build_manager(cfg)
    pages = {page.id for entry in manager.entries.values() if isinstance(entry.plugin, UiPlugin)
             for page in entry.plugin.create_pages()}
    if pages != set(coverage["pages"]):
        raise RuntimeError(f"文档页面登记不一致，新增或退役页面须同步说明：{sorted(pages ^ set(coverage['pages']))}")
    for page, titles in coverage["pages"].items():
        if not titles or any(title not in articles for title in titles):
            raise RuntimeError(f"页面缺少有效说明主题：{page}")
        if all(articles[title].category == "技术参考" for title in titles):
            raise RuntimeError(f"页面只有技术参考，缺少操作或数据说明：{page}")
    for guide in coverage["guides"]:
        if not (root / guide).is_file():
            raise RuntimeError(f"缺少正式指南：{guide}")
    return coverage


def verify_review(root: Path) -> None:
    coverage = verify_coverage(root)
    review = json.loads((root / REVIEW).read_text(encoding="utf-8"))
    current = product_sources(root)
    previous = review["sources"]
    changed = sorted(name for name in current.keys() | previous.keys()
                     if current.get(name) != previous.get(name))
    if changed or review["content_sha256"] != content_digest(root, coverage):
        raise RuntimeError("文档审阅已过期。补齐说明并执行 scripts/documentation_contract.py review --note <本次审阅说明>；"
                           f"变动文件：{', '.join(changed[:12]) or '说明内容'}")
    if not review.get("note", "").strip():
        raise RuntimeError("文档审阅缺少说明")


def record_review(root: Path, note: str, unchanged_reason: str = "") -> None:
    coverage = verify_coverage(root)
    target = root / REVIEW
    current = product_sources(root)
    digest = content_digest(root, coverage)
    if not note.strip():
        raise ValueError("必须填写实际审阅说明")
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8"))
        if previous["sources"] != current and previous["content_sha256"] == digest and not unchanged_reason.strip():
            raise RuntimeError("源码已改变但说明未更新；须补齐说明，或用 --unchanged-reason 记录无需变更用户说明的具体原因")
    value = {"schema": 1, "reviewed_at": datetime.now(UTC).isoformat(), "note": note,
             "unchanged_reason": unchanged_reason, "sources": current, "content_sha256": digest}
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "review"))
    parser.add_argument("--note", default="")
    parser.add_argument("--unchanged-reason", default="")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.action == "review":
        record_review(root, args.note, args.unchanged_reason)
    else:
        verify_review(root)
    print("PASS offline documentation coverage and review")
