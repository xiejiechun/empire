# 财经新闻业务包

本目录拥有新浪财经快讯的来源解析、采集、规范数据、归档映射、查询与页面。运行时仍按 `collector.sina_news`、`data.news`、`ui.news` 三个插件独立管理；`bundle.py` 只贡献现有声明。

- `contract.py`：业务身份、新闻 ID 与摘要版本契约。
- `source.py`：来源响应、正文纯文本与分页边界解析。
- `collector.py`：首轮最新窗口、按 ID 续采、失败断点和整轮归档确认。
- `dataset.py`：`news.flash.page` 规范校验、`finance_news` 内容比较/修订/旧版保护与统一摘要贡献。
- `query.py`：正式有界查询及稳定游标。
- `ui.py`：财经快讯页面、查询生命周期和交互状态。
- `bundle.py`：固定身份、任务默认值、归属与装配顺序。

日常操作与来源生命周期以 [新浪财经新闻说明](../../../../docs/sina-news.md) 为权威正文。数据只经共享下载、入队、归档和正式查询路径；业务包不复制这些公共服务，也没有独立 preparation 项。

专项入口：`tests/test_sina_news.py`、`tests/test_news_query.py`、`tests/test_news_ui.py`。正式归档与恢复：`tests/integration/test_news_archive.py`、`tests/integration/test_archive_fairness.py`。共有约束见 [采集开发指南](../../../../docs/collector-development-guide.md)；来源行为改变须按指南重新完成适用实采，新闻不属于按股票随机30样本的业务粒度。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/overview.md](docs/help/overview.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
