<!-- topic:数据库参考|Redis identity-runs -->
<!-- summary:按平台保留最近100条申请与登录运行结果。 -->
<!-- group:Redis -->
# Redis identity-runs

## 用途与归属

身份操作诊断，使用共享RecordsPlugin写入，身份管理查询读取。不是业务归档队列或游客配置。

## 结构与身份

键模板：`<namespace>:collection:identity-runs:<platform_id>`。类型List/JSON，最新操作在前。同花顺远航版platform_id为ths-yuanhang-identity。

| 字段 | 含义 |
| --- | --- |
| id / code | 操作唯一ID与固定节点编号；同ID完成时原子替换 |
| operation | application首次申请或login复用登录 |
| status | running、success、failed、interrupted；旧running无活跃所有者在查询时标未确认 |
| started_at / finished_at | UTC带时区时间，未结束为null；页面转北京时间 |
| stage / error_code / message | 白名单阶段、整数错误码和安全说明；不记录原始异常凭据 |

## 读写与关联

操作前写running，结束写结果；空闲扫描不写。每平台最近100条，无TTL，超限裁掉最旧；每条仅白名单元数据，上限8KiB。共享Lua按ID替换、裁剪并递增identity-runs-revision。没有成功响应正文、密码、账号或会话。配置在MySQL，运行记录不归档SQL。

## 保留与恢复

Redis纯内存，服务或电脑重启丢失，不能当永久审计日志。写失败不再次申请，SQL申请状态继续阻止重复；查询失败明确显示不可读取。维护不清空共享Redis。

## 维护与相关说明

[平台身份管理](help:平台身份管理)、[Redis identity-runs-revision](help:Redis%20identity-runs-revision)
