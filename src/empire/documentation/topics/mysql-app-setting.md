<!-- topic:数据库参考|MySQL app_setting -->
<!-- summary:用户正式保存的任务、网站频控、下载资源配置。 -->
<!-- group:MySQL -->
# MySQL app_setting

## 用途与归属

采集任务的批量启动和批量停止复用单任务配置保存流程：逐项保存 enabled 启停状态，其他已保存配置保持；不提交界面草稿，不增加批量配置表或整批事务，部分失败通过逐项结果呈现。

用户正式保存的任务、网站频控、下载资源配置。

下载资源当前只编辑同时下载数和共享临时内存。原stock/news/calendar/generic_response_bytes分类字段保留既有存储格式，但不再决定HTTP响应上限；HTTP与使用共享策略的原生传输按实际正文及解压数据申请额度，不在启动时改写本表。文件大小和目录保护仍使用原设置。

远航版节点身份维护也复用本表，`kind=yuanhang / setting_key=guest-profiles` 保存按RouterProxy设备code绑定的逻辑客户端档案。节点只提供代理出口，无需安装远航版。自动身份服务建立持久档案后才申请游客；IP变化、离线和重启不会换档案。正式行情采集任务仍须另行验收。

运行服务仅发现未知code时新增档案，仅申请状态变化时更新；稳定目录轮询、正常登录及重复检查不刷新updated_at。最多1000个保留档案包含离线节点；达到上限报错，不自动删旧档案腾位。每60秒重读MySQL配置，失败保留原值并停止申请；已有requested/rejected/unknown使自动申请暂停，插件显示降级并列出阻塞节点，不能靠重启重复注册。账号正常认证失败也不触发重新注册。操作和故障处理见“采集出口与频控”。

唯一配置写入器 `infra/settings.py`；任务由 `collection/control.py` 管理，网站和下载资源由 `infra/http.py` 加载。任务、网站、下载资源页面调用命令，不各自写 SQL。

按项目诊断通过 `diagnostics/project.py` 只读该任务已保存的一行配置，正文上限 16 KiB；与 Redis 运行副本分别显示，不启动任务或保存配置。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `namespace` | `VARCHAR(160) NOT NULL` | 配置/采集空间，取 redis.namespace；与业务来源不同。 |
| `kind` | `VARCHAR(16) NOT NULL` | task 任务、site 网站、download 下载资源、yuanhang 远航节点身份。 |
| `setting_key` | `VARCHAR(120) NOT NULL` | task 为项目 ID，site 为网站组，download 为 global。 |
| `payload` | `JSON NOT NULL` | 按 kind 校验的配置 JSON：task 含计划/代理/重试/启停/archived；site 含出口间隔/全站保护/扩展模式/并发；download 为字节整数资源值；yuanhang 为schema2、最多1000个节点且总计4MiB的身份配置。 |
| `updated_at` | `DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)` | 该行最近实际内容更新时刻，MySQL DATETIME 按北京时间保存。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (namespace, kind, setting_key)`

## 读写与关联

按 namespace/kind 读取、setting_key 定位；连接凭据只在程序目录 config.toml，不放在 payload。任务保存后计划生效、网络策略下一轮生效；网站规则作用于后续请求；下载资源保存后正常重启生效。

上述连接凭据指Redis/MySQL连接配置。远航节点条目含profile_id、registration、可选protected密文、rejection_code及creation参数快照，不含代理密码、出口IP或会话。registration分为unrequested、requested、rejected、unknown、ready，只有ready表示源站账号已取得；固定逻辑客户端标识从UUID产生，不读取本机MAC，不冒充代理设备硬件地址。游客账号及密码通过Windows当前用户DPAPI加密，并绑定namespace、code和profile_id；会话只在内存。每个游客只能绑定一个节点，普通登录不更新配置。

初次申请前先提交requested，源拒绝或结果未知保留原档案，不换标识重试。使用SettingsStore.mutate在锁定配置行的事务内更新，同内容零DML；失败不返回成功分配。显式维护入口scripts/yuanhang_node_profiles.py：无参数只读状态，--initialize为当前在线节点建档，--provision CODE仅为指定节点首次申请或复用登录。成功凭据不显示在输出和日志中。

task 的 request_retries 统一允许整数0～100，首次请求另计；原默认2次及已保存值保持不变，保存后下一轮生效。

SettingsStore 直接事务保存，不进入业务队列；同内容不写。软件、Redis 或电脑重启后配置保留，运行计划重新构建。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

节点从在线目录消失不会删除身份。DPAPI密文依赖原Windows用户保护环境，解密失败保留原配置并报错，不能自动重新注册；换机迁移须另行安排凭据恢复，不靠复制密文冒充成功迁移。身份维护不启动业务采集或归档，不代表全量行情已经初始化。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

配置保存走 SettingsStore；旧下载配置转换用 scripts/migrate_download_settings.py / migrate_download_capacity.py，当前合法配置不需再次迁移。程序目录连接配置仅用 scripts/migrate_program_config.py 显式搬入，不存本表。

[执行采集与计划](help:执行采集与计划)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)

远航creation保留配方版本、参数来源、记录/申请时刻、客户端版本、固定逻辑MAC/IMEI、申请URL、GET方法及imei/qsid/reqtype白名单参数。新档案在请求前保存；旧schema1必须正常关闭Empire后用scripts/migrate_yuanhang_profiles.py核查，再以--apply显式迁移。旧记录标注legacy-reconstructed，首次申请时刻未知为null；迁移保持code、UUID、密文及状态不变。运行时不自动转换，参数不可在页面随意改写。操作历史只存Redis，不混入本表。日常入口见[平台身份管理](help:平台身份管理)。

远航节点账号档案仍使用本表既有设置契约。跨任务复用的认证会话仅驻留身份服务内存，程序退出即释放，不将通行证写入app_setting，也不在每次采集结束时更新账号档案。
