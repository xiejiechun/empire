"""The single offline article format shared by the reader and release checks."""
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

CATEGORIES = ("入门", "日常操作", "数据说明", "故障处理", "数据库参考", "技术参考")


@dataclass(frozen=True)
class Article:
    category: str
    title: str
    body: str
    group: str = ""
    summary: str = ""


def parse_articles(text: str) -> list[Article]:
    result = []
    for part in text.split("<!-- topic:")[1:]:
        heading, body = part.split(" -->", 1)
        category, title = heading.split("|", 1)
        group = re.search(r"<!-- group:([^>]+) -->", body)
        summary = re.search(r"<!-- summary:([^>]+) -->", body)
        body = re.sub(r"<!-- (?:group|summary):[^>]+ -->\s*", "", body)
        body = body.strip()
        if category not in CATEGORIES or not body.startswith(f"# {title}\n"):
            raise ValueError(f"说明主题分类或标题无效：{heading}")
        if not re.search(r"^## ", body, re.MULTILINE):
            raise ValueError(f"说明主题缺少章节：{title}")
        if not summary or not 8 <= len(summary[1].strip()) <= 140:
            raise ValueError(f"说明主题缺少简短摘要：{title}")
        if category == "数据说明":
            if not group or not group[1].strip():
                raise ValueError(f"数据说明缺少业务分组：{title}")
            for section in ("如何查看", "数据范围与更新", "字段与日期", "限制与排错", "相关说明"):
                if f"## {section}\n" not in body:
                    raise ValueError(f"数据说明缺少章节 {section}：{title}")
        if category == "数据库参考":
            if not group or group[1].strip() not in ("总览", "MySQL", "Redis"):
                raise ValueError(f"数据库参考缺少存储分组：{title}")
            for section in ("用途与归属", "结构与身份", "读写与关联", "保留与恢复", "维护与相关说明"):
                if f"## {section}\n" not in body:
                    raise ValueError(f"数据库参考缺少章节 {section}：{title}")
        result.append(Article(category, title, body, group[1].strip() if group else "",
                              summary[1].strip()))
    titles = {item.title for item in result}
    if not result or len(titles) != len(result):
        raise ValueError("说明主题为空或重复")
    for item in result:
        for target in re.findall(r"\]\(help:([^)]*)\)", item.body):
            if re.search(r"\s", target):
                raise ValueError(f"说明链接空格须编码为 %20：{item.title} → {target}")
            if unquote(target) not in titles:
                raise ValueError(f"说明链接目标不存在：{item.title} → {target}")
    return result


def read_articles(path: Path) -> list[Article]:
    return parse_articles(path.read_text(encoding="utf-8"))


def articles():
    return read_articles(Path(__file__).with_name("storage_reference.md"))


def topics():
    return {item.title: item.body for item in articles()}


def search_articles(values: list[Article], query: str) -> list[Article]:
    words = query.strip().casefold().split()
    def rank(item):
        title, summary = item.title.casefold(), item.summary.casefold()
        return (0 if all(word in title for word in words) else
                1 if all(word in title + summary for word in words) else 2,
                item.category == "技术参考", values.index(item))
    return sorted((item for item in values if all(word in
                  (item.title + item.summary + item.group + item.body).casefold() for word in words)),
                  key=rank)
