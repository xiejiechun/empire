import json
from datetime import date, datetime, timedelta

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest


class NewsDataPlugin:
    manifest = PluginManifest("data.news", "财经新闻查询", requires=("mysql.store",),
                              provides=("news.query", "news.schema"),
                              description="检索已归档的财经直播，保留历史并去重更新")

    def __init__(self, source="sina", job_key="sina-news-v1", project_id="sina-news", namespace="empire"):
        self.source, self.job_key, self.project_id = source, job_key, project_id
        self.mysql = None
        self.namespace = namespace

    async def start(self, context):
        self.mysql = context.get("mysql.store")
        await self.mysql.require_schema({"finance_news": {
            "source", "news_id", "title", "content", "published_at", "source_updated_at",
            "is_important", "tags", "url", "first_seen_at", "version_observed_at",
        }}, {"finance_news": ["source", "news_id"]})
        return {"news.query": self, "news.schema": self}

    async def list_news(self, search="", limit=50, important=False, before=None, anchor=None,
                        include_total=True, start='', end=''):
        if (not isinstance(search, str) or len(search) > 100 or not 1 <= limit <= 200
                or type(important) is not bool or type(include_total) is not bool):
            raise ValueError("新闻查询参数超出范围")
        for value in (start, end):
            if value and date.fromisoformat(value).isoformat() != value:
                raise ValueError('新闻日期必须为 YYYY-MM-DD')
        if start and end and start > end:
            raise ValueError('新闻起始日期晚于截止日期')
        return await self.mysql.read(self._list, search.strip(), limit, important,
                                     self._cursor(before), self._cursor(anchor), include_total, start, end)

    @staticmethod
    def _cursor(value):
        if value is None:
            return None
        try:
            if not isinstance(value, dict) or set(value) != {"published_at", "news_id"}:
                raise ValueError
            published = datetime.fromisoformat(value["published_at"])
            ident = value["news_id"]
            if published.tzinfo is not None or type(ident) is not int or ident < 0:
                raise ValueError
            return published, ident
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError("新闻分页游标无效") from None

    @staticmethod
    def _encode_cursor(row):
        return {"published_at": row["published_at"].isoformat(), "news_id": row["news_id"]}

    def _list(self, search, limit, important, before, anchor, include_total, start='', end=''):
        params = {"source": self.source, "fetch_limit": limit + 1}
        filters = ["source=:source"]
        if start:
            filters.append('published_at>=:start')
            params['start'] = datetime.combine(date.fromisoformat(start), datetime.min.time())
        if end:
            filters.append('published_at<:end')
            params['end'] = datetime.combine(date.fromisoformat(end)+timedelta(days=1), datetime.min.time())
        if search:
            params["search"] = ("%" + search.replace("\\", "\\\\").replace("%", "\\%")
                                .replace("_", "\\_") + "%")
            filters.append("(title LIKE :search OR content LIKE :search)")
        if important:
            filters.append("is_important=1")
        if anchor:
            params.update(anchor_at=anchor[0], anchor_id=anchor[1])
            filters.append("(published_at<:anchor_at OR (published_at=:anchor_at AND news_id<=:anchor_id))")
        if before:
            params.update(before_at=before[0], before_id=before[1])
            filters.append("(published_at<:before_at OR (published_at=:before_at AND news_id<:before_id))")
        where = " AND ".join(filters)
        with self.mysql.read_engine.connect() as conn:
            data = conn.execute(text(f"""
                SELECT news_id,title,content,published_at,source_updated_at,is_important,tags,url,version_observed_at
                FROM finance_news WHERE {where} ORDER BY published_at DESC,news_id DESC LIMIT :fetch_limit
            """), params).mappings().all()
            if anchor is None and data:
                anchor = (data[0]["published_at"], data[0]["news_id"])
            total = None
            if include_total:
                count_filters = [item for item in filters if not item.startswith("(published_at<:before_at")]
                total = conn.execute(text(
                    f"SELECT COUNT(*) FROM finance_news WHERE {' AND '.join(count_filters)}"), params).scalar_one()
            visible = data[:limit]
            rows = []
            for row in visible:
                value = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.items()}
                value["tags"] = json.loads(value["tags"]) if isinstance(value["tags"], str) else value["tags"]
                rows.append(value)
        return {"total": total, "rows": rows, "limit": limit,
                "anchor": ({"published_at": anchor[0].isoformat(), "news_id": anchor[1]}
                           if anchor else None),
                "next_cursor": self._encode_cursor(visible[-1]) if len(data) > limit else None}

    async def latest(self):
        def read():
            with self.mysql.read_engine.connect() as conn:
                row = conn.execute(text('SELECT published_at,news_id FROM finance_news WHERE source=:source '
                    'ORDER BY published_at DESC,news_id DESC LIMIT 1'), dict(source=self.source)).mappings().first()
                return self._encode_cursor(row) if row else None
        return await self.mysql.read(read)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
