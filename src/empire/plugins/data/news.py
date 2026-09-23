import json

from sqlalchemy import inspect, text

from empire.contracts.plugin import PluginManifest

NEWS_COLUMNS = {"source", "news_id", "title", "content", "published_at", "source_updated_at",
                "is_important", "tags", "url", "first_seen_at", "last_seen_at"}


class NewsDataPlugin:
    manifest = PluginManifest("data.news", "财经新闻查询", requires=("mysql.store", "redis.store"),
                              provides=("news.query",), description="检索已归档的财经直播，保留历史并去重更新")

    def __init__(self, source="sina", job_key="sina-news-v1"):
        self.source, self.job_key = source, job_key
        self.mysql = self.redis = None

    async def start(self, context):
        self.mysql, self.redis = context.get("mysql.store"), context.get("redis.store")
        await self.mysql.read(self._validate)
        return {"news.query": self}

    def _validate(self):
        with self.mysql.engine.connect() as conn:
            schema = inspect(conn)
            if "finance_news" not in schema.get_table_names():
                raise RuntimeError("缺少 finance_news 业务表，请显式建表；启动不会自动改库")
            if not NEWS_COLUMNS <= {c["name"] for c in schema.get_columns("finance_news")}:
                raise RuntimeError("finance_news 字段不完整")
            if (schema.get_pk_constraint("finance_news")["constrained_columns"] != ["source", "news_id"]
                    or schema.get_table_options("finance_news").get("mysql_engine", "").lower() != "innodb"):
                raise RuntimeError("finance_news 必须有来源/新闻 ID 主键并使用 InnoDB")

    async def page_status(self, batch_id, page):
        raw = await self.redis.client.get(f"{self.redis.prefix}:archive:progress:{self.job_key}")
        value = json.loads(raw) if raw else {}
        if value.get("batch_id") == batch_id and (value.get("status") == "invalid" or value.get("page", 0) >= page):
            return value
        return None

    async def list_news(self, search="", offset=0, limit=50, important=False):
        if not isinstance(search, str) or len(search) > 100 or not 0 <= offset <= 100000 or not 1 <= limit <= 200:
            raise ValueError("新闻查询参数超出范围")
        return await self.mysql.read(self._list, search.strip(), offset, limit, bool(important))

    def _list(self, search, offset, limit, important):
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params = {"source": self.source, "search": pattern, "offset": offset, "limit": limit}
        where = "source=:source AND (title LIKE :search OR content LIKE :search)"
        if important:
            where += " AND is_important=1"
        with self.mysql.engine.connect() as conn:
            total = conn.execute(text(f"SELECT COUNT(*) FROM finance_news WHERE {where}"), params).scalar_one()
            data = conn.execute(text(f"""
                SELECT news_id,title,content,published_at,source_updated_at,is_important,tags,url,last_seen_at
                FROM finance_news WHERE {where} ORDER BY published_at DESC,news_id DESC LIMIT :limit OFFSET :offset
            """), params).mappings()
            rows = []
            for row in data:
                value = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.items()}
                value["tags"] = json.loads(value["tags"]) if isinstance(value["tags"], str) else value["tags"]
                rows.append(value)
        return {"total": total, "rows": rows, "offset": offset, "limit": limit}

    async def stop(self):
        self.mysql = self.redis = None

    def health(self):
        return {"status": "ok" if self.mysql else "stopped"}
