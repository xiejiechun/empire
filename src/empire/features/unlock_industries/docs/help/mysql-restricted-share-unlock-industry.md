<!-- topic:数据库参考|MySQL restricted_share_unlock_industry -->
<!-- group:MySQL -->
<!-- summary:月与来源行业名唯一的类型化汇总；保留历史，基准日版本保护。 -->
# MySQL restricted_share_unlock_industry

## 用途与归属

源码归属`features/unlock_industries`：`contract`定义字段，`dataset`事务保存，`query`提供正式读取；下载经唯一共享`sources/tdx_unlock.py`协议与公共下载/入队/归档服务。入口与存储身份保持，启动不迁移。
数据集unlocks.tdx_industry_month，固定tdx，采集项目tdx-unlock-industries；统一归档与unlock_industries.tdx_query唯一正式路径。

## 结构与身份
| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `unlock_month` | `DATE NOT NULL` | 来源解禁月份固定1日，主键 |
| `industry` | `VARCHAR(200) NOT NULL` | 来源行业名，主键；没有来源行业代码 |
| `basis_date` | `DATE NOT NULL` | 目录mxt估值基准日 |
| `shares` | `DECIMAL(28,8) NULL` | T003万股转股，NULL未知 |
| `unlock_value` | `DECIMAL(28,8) NULL` | T004万元转元，NULL未知 |
| `market_cap` | `DECIMAL(28,8) NULL` | MarketCap行业总市值，元，NULL未知 |
| `negotiable_cap` | `DECIMAL(28,8) NULL` | NegotiableCap行业流通市值，元，NULL未知 |
| `market_percent` | `DECIMAL(28,8) NULL` | zszbl百分数，NULL未知 |
| `float_percent` | `DECIMAL(28,8) NULL` | ltszbl百分数，NULL未知 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范月行业内容SHA-256 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本观测时间，北京时间 |

## 读写与关联
`PRIMARY KEY (unlock_month,industry)`支持月份范围与完整月；`KEY ix_industry_month (industry,unlock_month)`支持行业历史。

`CONSTRAINT ck_unlock_industry_month CHECK (DAY(unlock_month)=1)`固定月份首日；`CONSTRAINT ck_unlock_industry_name CHECK (CHAR_LENGTH(TRIM(industry))>0)`保证行业非空；`CONSTRAINT ck_unlock_industry_values CHECK (shares>=0 AND unlock_value>=0 AND market_cap>=0 AND negotiable_cap>=0 AND market_percent>=0 AND float_percent>=0)`拒绝负值。单页200，单月500，当前目录120月；完整证明在collection_state同项目一行。

## 保留与恢复
完整月事务接收修订并删除本月撤回行业；目录外已有月份保留。相同内容零业务DML，旧基准/旧观测不覆盖。可信摘要免SQL；成功清队和SQL后重放由统一归档执行。显式建表scripts/create_unlock_industry_schema.py，启动不DDL，不清共享Redis。

## 维护与相关说明
[大小非解禁行业](help:大小非解禁行业)
