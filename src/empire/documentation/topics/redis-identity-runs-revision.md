<!-- topic:数据库参考|Redis identity-runs-revision -->
<!-- summary:平台身份操作记录的共享修订计数。 -->
<!-- group:Redis -->
# Redis identity-runs-revision

## 用途与归属

平台身份操作的共享修订计数，由RecordsPlugin维护。

## 结构与身份

键模板：`<namespace>:collection:identity-runs-revision:<platform_id>`，类型String整数。由共享RecordsPlugin每次追加或同ID替换操作记录时在同一Lua内递增，平台相互独立。不保存业务数据或凭据。

## 读写与关联

与identity-runs在同一Lua操作中维护，身份查询有界读取，不作为永久身份状态。

## 保留与恢复

每平台一个计数，无TTL，Redis或电脑重启后丢失；只供临时运行记录版本使用，不是SQL进度或完整性证明。身份页面有界读取最近100条；Redis不可用时显示故障，不把计数缺失当操作成功。不清空共享Redis。

## 维护与相关说明

[Redis identity-runs](help:Redis%20identity-runs)、[平台身份管理](help:平台身份管理)
