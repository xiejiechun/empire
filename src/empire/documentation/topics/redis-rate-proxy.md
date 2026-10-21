<!-- topic:数据库参考|Redis rate-proxy -->
<!-- summary:网站每出口 IP 许可：查阅键名、内容、所有者与清理规则。 -->
<!-- group:Redis -->
# Redis rate-proxy

## 用途与归属

网站每出口 IP 许可。共享 routing 按 group 和出口 IP 身份摘要分配，多个设备同 exit_ip 共用许可。

## 结构与身份

键模板：`<namespace>:rate:<group>:proxy:<exit_ip_hash>`

类型：**Hash**。

next 为该网站/出口下次许可的 Redis 毫秒时刻；exit_ip_hash 为出口身份 SHA-256 前 24 位，不含代理凭据。

## 读写与关联

同站点同出口共用频控及在途槽；不同站点独立拥有全部健康出口。全组 429 冷却仍生效，全局下载窗口/字节预算仍限制总体容量。

## 保留与恢复

获得许可后 PEXPIRE=86400000 毫秒，一天未使用到期；连接失败隔离和在途连接所有权只在进程内，不另建健康探测键。

Empire Redis 采用纯内存模式。Redis 服务或电脑重启丢失本库内存值；只重启 Empire 且 Redis 仍运行不等于丢失。业务查询以 MySQL 为准，不能把本键当永久数据或备份。

## 维护与相关说明

实现归属：`infra/routing.py`。查询诊断有界且脱敏；维护按确切项目/来源/ID执行，不清空共享 Redis。

[采集出口与频控](help:采集出口与频控)、[数据库职责与查阅](help:数据库职责与查阅)
