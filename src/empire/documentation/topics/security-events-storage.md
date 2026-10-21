<!-- topic:技术参考|更名及上市事件存储 -->
<!-- summary:核对名称变更、上市状态事件的业务粒度、正式字段与查询规则。 -->
# 更名及上市事件存储

## 更名契约

字段与业务身份见 [MySQL security_name_change](help:MySQL%20security_name_change)。公司同日不同名称组合分别保留，股票同证券同日重复身份拒绝；更名不会生成代码变更或 ST 状态。

## 上市事件契约

字段与查询索引见 [MySQL security_listing_event](help:MySQL%20security_listing_event)。按完整自然月证明与业务集合验收，最大事件日不证明完整覆盖；不推算最后交易日。
