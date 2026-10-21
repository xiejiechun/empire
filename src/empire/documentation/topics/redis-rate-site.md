<!-- topic:数据库参考|Redis rate-site -->
<!-- summary:网站直连许可与全组冷却：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis rate-site

## 用途与归属

网站直连许可与全组冷却。共享 HTTP routing/COOLDOWN_LUA 写，所有该站任务共用；不是站点配置表。

## 结构与身份

键模板：`<namespace>:rate:<group>`

类型：**Hash**。

next 为本机下次请求许可的 Redis 毫秒时间；cooldown 为服务器冷却截止毫秒时间。group 为域名组，同站点直连最多一个在途请求。

## 读写与关联

代理和本机均原子核对全组 cooldown；429 冷却所有出口，不能轮换绕过。普通重试上限提高到100次后，每次仍核对该冷却；单次退避最多30秒不截短来源声明的全组冷却。网站策略保存于 app_setting kind=site，运行时在内存加载，不存在现行 site-intervals Redis 键。指数YYYY临时404重试每次仍重新申请共享站点/出口许可，与其他重试使用同一频控，不绕过冷却或限速。

## 保留与恢复

本 Hash 无自动 TTL；时间届满不再阻止请求。服务重启丢失许可/冷却，不能宣称跨 Redis 重启恢复。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`infra/routing.py`、`infra/http.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[代理与站点速度](help:代理与站点速度)、[数据库职责与查阅](help:数据库职责与查阅)
