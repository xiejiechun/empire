"""Sina source response parsing; no requests or storage side effects."""
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from empire.core.time import CHINA
from empire.features.news.contract import news_id

API_URL = "https://app.cj.sina.com.cn/api/news/pc"
PAGE_SIZE = 50


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("br", "p", "div") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div") and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def source_time(value):
    date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if date.year < 2000:
        raise ValueError("新闻来源时间无效")
    return date.replace(tzinfo=CHINA).astimezone(UTC).isoformat()


def normalize_source(row):
    if not isinstance(row, dict):
        raise ValueError("新闻条目必须是对象")
    ident = news_id(row.get("id"))
    raw = row.get("rich_text")
    if not isinstance(raw, str) or len(raw.encode()) > 200000:
        raise ValueError("新闻正文缺失或过大")
    parser = PlainText()
    parser.feed(raw)
    # HTMLParser may retain trailing plain text while an ampersand could still
    # begin a character reference (for example, "H&M").  Closing the parser
    # flushes that valid text before we decide whether the article is empty.
    parser.close()
    content = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    if not content:
        raise ValueError("新闻正文为空，不推进该页断点")
    tags = row.get("tag", [])
    if not isinstance(tags, list) or len(tags) > 32:
        raise ValueError("新闻分类字段无效")
    normalized_tags = []
    for tag in tags:
        if not isinstance(tag, dict) or not isinstance(tag.get("name"), str) or len(tag["name"]) > 100:
            raise ValueError("新闻分类名称无效")
        normalized_tags.append({"id": str(news_id(tag.get("id"))), "name": tag["name"]})
    url = row.get("docurl") or "https://finance.sina.com.cn/7x24/"
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (len(url) > 2048 or parsed.scheme not in ("http", "https") or parsed.username
            or not any(host == domain or host.endswith("." + domain) for domain in ("sina.com.cn", "sina.cn"))):
        raise ValueError("新闻来源链接无效")
    title_match = re.match(r"【([^】]+)】", content)
    published = source_time(row.get("create_time"))
    updated = source_time(row.get("update_time") or row.get("create_time"))
    return {"news_id": ident, "title": (title_match.group(1) if title_match else content.splitlines()[0])[:256],
            "content": content, "published_at": published, "source_updated_at": updated,
            "is_important": row.get("is_focus") in (1, "1") or any(t["id"] == "9" for t in normalized_tags),
            "tags": normalized_tags, "url": url}


def parse_feed(response, before_id=0):
    body = response.json()
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict) or result.get("status", {}).get("code") != 0:
        raise ValueError("新浪财经新闻接口业务状态异常")
    feed = result.get("data", {}).get("feed")
    if not isinstance(feed, dict) or not isinstance(feed.get("list"), list):
        raise ValueError("新浪财经新闻缺少 feed.list")
    rows = [normalize_source(row) for row in feed["list"]]
    if len(rows) > PAGE_SIZE:
        raise ValueError("新浪财经新闻返回页大小超出请求范围")
    ids = [row["news_id"] for row in rows]
    if any(a <= b for a, b in zip(ids, ids[1:])) or (ids and before_id and ids[0] >= before_id):
        raise ValueError("新浪新闻 ID 重复、逆序或分页游标未前进")
    if ids and (news_id(feed.get("min_id")) != ids[-1] or news_id(feed.get("max_id")) != ids[0]):
        raise ValueError("新浪新闻分页边界与条目 ID 不一致")
    return rows
