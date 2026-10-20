# 同花顺公司资本运作

唯一业务包：contract定义九栏目及八表字段/身份，表组只读取sql/business-schema.json；source使用公共sources/html.py解析完整响应；collector复用下载、预取、统一入队和整轮确认；dataset归档与query正式游标/详情/准备审计；ui惰性创建；bundle保留原插件/任务/数据集槽位。

日常入口、字段、初始化/补缺/修订/恢复、日期与来源限制见[业务手册](../../../../docs/ths-capital.md)。不存成功HTML、不另造归档/摘要/调度，历史来源窗口外记录保留。开发与动态实采、容量、发布及桌面证据见[本批记录](../../../../docs/evidence/architecture-e6a-2026-10-20.md)。
