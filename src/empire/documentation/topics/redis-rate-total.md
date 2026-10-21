<!-- topic:数据库参考|Redis rate-total -->
<!-- summary:网站总频率许可：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis rate-total

## 用途与归属

网站总频率许可。共享 ROUTE_PERMIT Lua 与网站和出口许可一起计算/更新。

## 结构与身份

键模板：`<namespace>:rate:<group>:total`

类型：**String / millisecond timestamp**。

下一次全站许可 Redis 毫秒时刻；固定模式执行合计间隔，自动模式按显式全站每秒保护计算，不从理论出口数派生合计间隔。

## 读写与关联

与 rate-site 全组冷却、每出口 next 取最大等待；不能把窗口上限当网站许可或实测吞吐。

## 保留与恢复

每次获许可 PX=max(60000, 总许可间隔×2) 毫秒；无人使用后自动到期。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`infra/routing.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[Redis rate-site](help:Redis%20rate-site)、[数据库职责与查阅](help:数据库职责与查阅)
