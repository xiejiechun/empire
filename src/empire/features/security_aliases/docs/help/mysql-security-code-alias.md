<!-- topic:数据库参考|MySQL security_code_alias -->
<!-- summary:北交所官方历史换码关系，可按旧代码或当前统一证券键查询，不推算换码日期。 -->
<!-- group:MySQL -->
# MySQL security_code_alias

## 用途与归属

北交所官网正式换码表，一项旧代码到新统一证券键一行，固定来源bse。后续直接以920号段上市的股票没有可推算旧代码。没有新增桌面页面或定时任务。

## 结构与身份

| 字段 | SQL 声明 | 含义 |
| --- | --- | --- |
| `legacy_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 北交所公布的旧六位代码 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 现代码加.BJ后缀的统一证券键 |
| `name` | `VARCHAR(100) NOT NULL` | 换码表中的证券简称，不替代当前股票名称 |
| `listing_date` | `DATE NOT NULL` | 来源上市日期；精选层平移证券为原精选层挂牌日 |
| `version_observed_at` | `DATETIME NOT NULL` | 最近实际变化版本的北京时间观测时刻，写入前截断到秒，重复导入不刷新；统一状态保留微秒排序 |

- `PRIMARY KEY (legacy_code)`
- `UNIQUE KEY ux_alias_security (unified_code)`
- `CONSTRAINT ck_alias_old CHECK (REGEXP_LIKE(legacy_code, '^[48][0-9]{5}$'))`
- `CONSTRAINT ck_alias_current CHECK (REGEXP_LIKE(unified_code, '^920[0-9]{3}[.]BJ$'))`
- `CONSTRAINT ck_alias_name CHECK (CHAR_LENGTH(TRIM(name)) BETWEEN 1 AND 100)`

## 读写与关联

旧代码精确查询命中主键，新unified_code精确查询命中ux_alias_security，最多一行。全表按legacy_code排序、最多1000行。业务写入由数据集bse.code_mapping.complete经统一归档器完成，collection_state项目为bse-code-mapping。完整来源数组只在共享Redis待归档期间保存，成功确认后删除。官方表不存在ISIN和换码生效日，本表不填造。

## 保留与恢复

历史关系保留，不外键级联stock。完全相同不写业务表；较早响应不覆盖较新版本；一对一关系冲突拒绝整份事务。SQL失败留队，SQL提交后Redis确认失败安全重放；Redis重启重新从官方表导入，MySQL关系仍保留。

## 维护与相关说明

正常关闭Empire、待归档Stream清零后运行scripts/create_security_alias_schema.py --apply，持单实例与SQL维护锁显式新增表；启动不迁移。scripts/import_bse_code_mapping.py默认只读核实，加--apply通过共享下载器代理优先、可回退直连，校验完整表后统一入队归档；不更改日常任务政策。可直接在SQL按legacy_code或unified_code查询。具体设计见docs/bse-code-mapping.md。本映射不保证开盘啦旧代码请求成功，未解决行情错误仍保留。

业务实现集中在features/security_aliases，原显式维护命令、数据集身份、整表校验和历史关系保留规则保持，没有新增页面或定时任务。开发用千行容量及官方整表代理验证各使用UUID私有测试资源，实际核实例与归属，清理并保存新报告后才报告通过；这些开发结果不代表生产已更新或未公布关系可推断。
