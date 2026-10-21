<!-- topic:数据库参考|Redis router-directory -->
<!-- summary:外部代理租约目录：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis router-directory

## 用途与归属

外部代理租约目录。RouterProxy 拥有租约，Empire ProxyPool 只读，与映射共同验证。

## 结构与身份

键模板：`router:proxies:device`

类型：**ZSET（外部只读）**。

member 为与 Hash value 完全相同的 JSON 原文，score 为失效 Unix 秒数；不是设备在线计数或代理密码展示入口。

## 读写与关联

使用 Redis TIME 核对 score 未过期且 JSON 映射一致后采用。设备退出影响后续分配；已发出请求完成，退休连接等全部站点请求退出再关闭。

## 保留与恢复

租约按 score 判定到期，不以 key TTL 替代；移除/重发布由外部生产者负责，不由 Empire 清理。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`infra/proxy_pool.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[Redis router-mapping](help:Redis%20router-mapping)、[数据库职责与查阅](help:数据库职责与查阅)
