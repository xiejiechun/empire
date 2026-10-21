<!-- topic:数据库参考|Redis router-mapping -->
<!-- summary:外部代理设备映射：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis router-mapping

## 用途与归属

外部代理设备映射。RouterProxy 拥有发布和删除；Empire ProxyPool 只读，禁止更改生产者 key。

## 结构与身份

键模板：`router:proxies:by-code`

类型：**Hash（外部只读）**。

field 为设备 code，value 为含 code/proxy/exit_ip 的 JSON。proxy 未声明协议按 SOCKS5H，显式 URL 按声明协议；原始密码只留连接内存，不展示正文。

## 读写与关联

候选分配用 Redis TIME 原子核对 Hash 映射与 router:proxies:device 租约；仅 Hash 有值不能证明在线。目录周期共享快照，不每请求全量扫描。

## 保留与恢复

Hash 不由 Empire 设置 TTL；失效设备由 RouterProxy 移出，恢复后重新发布。Empire 不建额外主动健康探测；异常格式只输出脱敏诊断。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`infra/proxy_pool.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[Redis router-directory](help:Redis%20router-directory)、[数据库职责与查阅](help:数据库职责与查阅)
