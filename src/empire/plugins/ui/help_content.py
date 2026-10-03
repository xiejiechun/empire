"""The single offline article format shared by the reader and release checks."""
import re
from dataclasses import dataclass
from pathlib import Path

CATEGORIES = ("入门", "日常操作", "数据说明", "故障处理", "技术参考")


@dataclass(frozen=True)
class Article:
    category: str
    title: str
    body: str


def read_articles(path: Path) -> list[Article]:
    result = []
    for part in path.read_text(encoding="utf-8").split("<!-- topic:")[1:]:
        heading, body = part.split(" -->", 1)
        category, title = heading.split("|", 1)
        body = body.strip()
        if category not in CATEGORIES or not body.startswith(f"# {title}\n"):
            raise ValueError(f"说明主题分类或标题无效：{heading}")
        if not re.search(r"^## ", body, re.MULTILINE):
            raise ValueError(f"说明主题缺少章节：{title}")
        result.append(Article(category, title, body))
    titles = {item.title for item in result}
    if not result or len(titles) != len(result):
        raise ValueError("说明主题为空或重复")
    for item in result:
        for target in re.findall(r"\]\(help:([^)]*)\)", item.body):
            if target not in titles:
                raise ValueError(f"说明链接目标不存在：{item.title} → {target}")
    return result


def articles():
    return read_articles(Path(__file__).with_name("storage_reference.md"))


def topics():
    return {item.title: item.body for item in articles()}
