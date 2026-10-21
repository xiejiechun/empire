<!-- topic:数据库参考|MySQL finance_news -->
<!-- summary:新浪历史财经快讯，一来源新闻 ID 一行。 -->
<!-- group:MySQL -->
# MySQL finance_news

## 用途与归属

新浪历史财经快讯，一来源新闻 ID 一行。

新闻业务统一位于 `features/news`：统一归档器调用 `dataset.py` 写入，`query.py` 提供正式查询；纯业务身份与规范在 `contract.py`，来源解析在 `source.py`。业务页面不直接写表，迁移没有改变表、消息身份或既有数据。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `source` | `VARCHAR(80) NOT NULL` | 来源标识；新闻逐行保留，项目状态与登记来源一致。 |
| `news_id` | `BIGINT NOT NULL` | 来源新闻 ID，与 source 联合去重。 |
| `title` | `VARCHAR(256) NOT NULL` | 提取的新闻标题，无显式标题时取正文开头，最长 256 字符。 |
| `content` | `MEDIUMTEXT NOT NULL` | 去掉 HTML 后的业务新闻正文，保留段落；不是整份 API 响应。 |
| `published_at` | `DATETIME(6) NOT NULL` | 来源发布时间，保存/展示为北京时间。 |
| `source_updated_at` | `DATETIME(6) NOT NULL` | 来源修订时间；版本比较防止迟到旧响应覆盖。 |
| `is_important` | `BOOLEAN NOT NULL DEFAULT FALSE` | 来源焦点或分类 9 的重点标志。 |
| `tags` | `JSON NOT NULL` | 规范分类 ID/名称 JSON 数组。 |
| `url` | `VARCHAR(2048) NOT NULL` | 来源文章地址，缺单篇地址时为直播页面。 |
| `first_seen_at` | `DATETIME(6) NOT NULL` | 新闻首次入库北京时间，重复采集不刷新。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前入库存储版本的请求观测时刻（北京时间），用于版本排序；相同内容不刷新。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (source, news_id)`
- `INDEX ix_news_published (source, published_at, news_id)`
- `INDEX ix_news_important (source, is_important, published_at, news_id)`

## 读写与关联

新闻正式游标查询增加日期范围，范围随分页保持；阅读流按日期分组，不因新消息提示替换旧阅读位置。

按 source/published_at/news_id 游标分页，重点筛选使用 ix_news_important；首屏确定上界，后续页不使用 OFFSET，不把浏览游标写入 Redis。

历史新闻保留，允许来源有效修订；更旧修订不覆盖。同内容和来源版本不变不刷新观测时刻。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[财经快讯](help:财经快讯)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
