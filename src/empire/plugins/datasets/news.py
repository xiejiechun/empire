"""Sina flash-news business fields and idempotent historical storage."""
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sqlalchemy import bindparam, text

DATASETS = {"news.flash.page"}
CHINA = timezone(timedelta(hours=8))


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


def news_id(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise ValueError("新闻 ID 必须是正整数")
    result = int(value)
    if result > 9223372036854775807:
        raise ValueError("新闻 ID 超出支持范围")
    return result


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


def normalize(envelope):
    payload = envelope.raw_payload
    page, rows = payload.get("page"), payload.get("rows")
    if type(page) is not int or not 1 <= page <= 100000:
        raise ValueError("新闻分页编号无效")
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError("新闻分页最多 50 条")
    clean = []
    fields = {"news_id", "title", "content", "published_at", "source_updated_at", "is_important", "tags", "url"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("新闻只允许规范化业务字段")
        news_id(row["news_id"])
        if (not isinstance(row["title"], str) or not 1 <= len(row["title"]) <= 256
                or not isinstance(row["content"], str) or not 1 <= len(row["content"].encode()) <= 200000
                or type(row["is_important"]) is not bool):
            raise ValueError("新闻正文、标题或重要性无效")
        for field in ("published_at", "source_updated_at"):
            date = datetime.fromisoformat(row[field])
            if date.tzinfo is None:
                raise ValueError("新闻时间必须包含时区")
        if not isinstance(row["tags"], list) or len(json.dumps(row["tags"], ensure_ascii=False).encode()) > 16384:
            raise ValueError("新闻分类无效")
        if not isinstance(row["url"], str) or len(row["url"]) > 2048:
            raise ValueError("新闻来源链接过长")
        clean.append(dict(row))
    ids = [row["news_id"] for row in clean]
    if any(a <= b for a, b in zip(ids, ids[1:])):
        raise ValueError("新闻 ID 重复或未按倒序排列")
    return {"page": page, "rows": clean, "row_count": len(clean)}


def canonical_payload(envelope, normalized):
    return {"page": normalized["page"], "rows": normalized["rows"]}


def write(connection, envelope, data):
    values = []
    observed = envelope.observed_at.astimezone(UTC).replace(tzinfo=None)
    for row in data["rows"]:
        values.append({**row, "source": envelope.source,
                       "published_at": datetime.fromisoformat(row["published_at"]).astimezone(UTC).replace(tzinfo=None),
                       "source_updated_at": datetime.fromisoformat(row["source_updated_at"]).astimezone(UTC).replace(tzinfo=None),
                       "tags": json.dumps(row["tags"], ensure_ascii=False), "observed": observed})
    processed = len(values)
    if values:
        # Compare a bounded page under the same transaction. Observation-only changes
        # must not issue DML; retain source version changes to reject stale replays.
        existing = connection.execute(text("""
            SELECT * FROM finance_news WHERE source=:source AND news_id IN :ids FOR UPDATE
        """).bindparams(bindparam("ids", expanding=True)),
            {"source": envelope.source, "ids": [v["news_id"] for v in values]}).mappings()
        previous = {r["news_id"]: dict(r) for r in existing}
        changed = []
        for value in values:
            old = previous.get(value["news_id"])
            if old is not None:
                old["tags"] = json.loads(old["tags"]) if isinstance(old["tags"], str) else old["tags"]
                if ((value["source_updated_at"], observed) < (old["source_updated_at"], old["last_seen_at"])
                        or all((json.loads(value[k]) if k == "tags" else value[k]) == old[k]
                               for k in data["rows"][0])):
                    continue
            changed.append(value)
        values = changed
    newer = "(VALUES(source_updated_at)>source_updated_at OR (VALUES(source_updated_at)=source_updated_at AND VALUES(last_seen_at)>=last_seen_at))"
    updates = ",".join(f"{field}=IF({newer},VALUES({field}),{field})" for field in (
        "title", "content", "published_at", "is_important", "tags", "url"))
    if values:
        connection.execute(text(f"""
            INSERT INTO finance_news (source,news_id,title,content,published_at,source_updated_at,
                                      is_important,tags,url,first_seen_at,last_seen_at)
            VALUES (:source,:news_id,:title,:content,:published_at,:source_updated_at,
                    :is_important,:tags,:url,:observed,:observed)
            ON DUPLICATE KEY UPDATE {updates},
                source_updated_at=GREATEST(source_updated_at,VALUES(source_updated_at)),
                first_seen_at=LEAST(first_seen_at,VALUES(first_seen_at)),
                last_seen_at=GREATEST(last_seen_at,VALUES(last_seen_at))
        """), values)
    return {"status": "complete", "row_count": processed, "written_count": len(values),
            "skipped_count": processed - len(values)}
