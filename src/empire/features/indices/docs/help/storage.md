<!-- topic:技术参考|指数存储与维护 -->
<!-- summary:核对指数存储与维护的正式字段、规则和维护边界。 -->
# 指数存储与维护

## 字段与维护

指数目录/成员归features/indices，日行情归features/index_prices；bundle保留原正式身份与顺序。指数标识语法由公共contracts/security.py唯一提供，HTML树由sources/ths_catalog_html.py共享。开发实采verify_indices.py及verify_index_prices.py仅向核实不同server_uuid的私有UUID库和owner前缀写入，逐项核对公开查询集合与内容；容量与来源结果分别记录，不把工具存在当成验收通过。

表、主键和成员可用性见 [MySQL stock_index](help:MySQL%20stock_index)、[MySQL stock_index_member](help:MySQL%20stock_index_member)。

目录及单指数成员各自独立事务提交，相同业务内容不写业务表，迟到旧代次不覆盖，统一摘要命中免SQL，成功处理后统一清除对应Redis消息。观察时刻表示本轮请求代次，不冒充来源修订时间。目录移除成员后，统一归档器在SQL确认后失效该来源旧摘要，保证重新加入能恢复成员；失效失败保留队列并安全重放。新增表只通过create_index_schema.py显式维护，启动不建表。只保留当前关系及每项目一条collection_state，不保存日快照或成功HTTP正文。
