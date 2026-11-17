# 同花顺真实历史行业成员来源核实（2026-11-16）

## 目标与本轮结论

用户要求寻找真实历史来源，补齐早于本地开始保存日期的同花顺行业成员，用于按所选历史日期汇总个股资金。

用户已确认没有 SuperMind / iFinD 账号，优先寻找免费公开来源。本轮完成现行实现核对、官方文档、免费工具、公开仓库及网页存档核实，尚未取得可归档的历史成员集合。不能将“文档存在历史日期参数”写成“历史数据已补齐”，也不能保证免费账号对所需行业指标开放。未改业务代码、采集配置或数据库；新增历史业务记录为 0。

## 工作区与现有正式路径

开工时工作区已有大量修改，包括 `docs/ths-industries.md`、industries 的 bundle/collector/ui/说明和集成测试；本轮不覆盖或归因这些修改。

- `src/empire/features/industries/source.py`：来源是 `https://q.10jqka.com.cn/thshy/`，取得当前目录和当前成员，未声明历史日期接口。
- `src/empire/features/industries/dataset.py`：`industry.snapshot` / `ths-industries`，`industry` 与 `industry_member` 完整当前集合替换。无历史归属、生效日期或历史完整性证明。
- `src/empire/features/industries/query.py`：只读当前成员，并明确限制历史用途。
- 已有通达信更名、ST、解禁和行业两融中的行业标签或行业汇总，均不能提供同花顺当日历史成员关系，不可拼接成历史行业库。

只读核实不启动采集器或归档器，不需要停客户端、迁移或重建。现有修改和共享运行环境保持。

## 官方来源证据

### 1. SuperMind：已确认文档支持历史归属，实际取数需登录

[官方 API 文档](https://quant.10jqka.com.cn/view/help/4)列出：

| 接口 | 官方声明与证据 | 尚未验证 |
| --- | --- | --- |
| `get_symbol_industry(symbol, date=None)` | 按股票和日期查行业；明确包含同花顺、申万、中信等分类。示例 `get_symbol_industry('300033.SZ', date='20230801')` 返回 `industryid1='T10'`、`industryid2='T1003'`、`industryid3='T100301'` | 真实账号结果、最早覆盖、历史修订语义、退市股票范围 |
| `get_industry_stocks(symbol, date=None)` | 指定日期的行业成员列表，日期格式 `YYYYMMDD`；官方成员例子使用中信 `CI311000` | 同花顺代码的实测结果与完整集合 |
| `get_industry_relate(date='now', types='industryid1', fields=None)` | 历史行业目录，包含 `industry_symbol`、`industry_index`、`industry_thscode` 等 | 与现有 thshy 六位行业代码的层级和逐项映射 |

[行业分类数据页](https://quant.10jqka.com.cn/view/dataplatform/detail/24)中的2023年示例不是最早覆盖日期声明。目录记录也不是股票成员记录。

实际从官网点击“研究环境”，新页跳转至 `https://upass.10jqka.com.cn/login?redir=HTTP_REFERER`。当前浏览会话未登录，未运行样本，不尝试绕过认证。平台内调用与本地下载/自动采集权限分别核实。

### 2. 同花顺数据接口 / iFinD：官方存在免费本地接口范围，行业指标仍待实测

从 [iFinD 官网](https://ft.10jqka.com.cn/)“同花顺数据接口”进入[数据接口官网](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/)。

[官方权限说明](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center/permission.html)明确写明：

- 免费版仅需要 iFinD 账号即可登录，不需要申请试用。
- 基础数据、日期序列和专题报表各列出60万/月额度；数据量按单元格计算。
- 免费用户基础数据、日期序列、历史行情的取值年限为最近5年；专题报表取值年限不限制。
- 免费版基础数据和日期序列单次提取不超过1万单元格。

这是通用函数权限，不证明“同花顺历史行业成员”这一具体指标存在、免费、覆盖5年或覆盖全部历史。此前“本地接口付费”的概括不能覆盖此官网现行免费版说明。

[产品手册](https://quantapi.10jqka.com.cn/gwstatic/static/ds_web/quantapi-web/help-center/manual.html)声明 `THS_iFinDLogin` 需要接口账号，`THS_BD` / `THS_DS` 支持多代码多指标，具体指标及参数需在 SuperCommand 查询或生成。当前尚未核实历史行业指标的精确名称、参数及实值，不凭记忆填写指标、不编造请求。未登录、申请试用、安装 SDK/Skill 或购买服务。

### 3. Tushare：本次历史补齐不可用

[官方 ths_member 文档](https://tushare.pro/document/2?doc_id=261)明确写“是最新的概念板块成分”，需6000积分。字段 `in_date`、`out_date` 分别注明“纳入日期(暂无)”“剔除日期(暂无)”。不能因存在字段名就认定有历史成员，更不能据此还原同花顺历史行业。

## 免费公开来源核实

### 4. AKShare：已核对的同花顺行业文档未提供历史成员

[板块与热度官方文档](https://akshare.akfamily.xyz/data/stock/stock_board.html)中：

- `stock_board_industry_summary_ths` 明确为“当前时刻同花顺行业一览表”。
- `stock_board_industry_name_ths` 返回行业名称和代码，没有历史日期参数。
- `stock_board_industry_info_ths` 为板块简介，只有行业参数，没有历史成员集合。
- `stock_board_industry_index_ths` 虽有 `start_date` / `end_date`，输出是日期、开高低收、成交量及成交额，属于历史指数行情，不能还原股票归属。
- `stock_board_concept_summary_ths` 的概念添加日期和成分股数量，也不是行业成员调入调出记录。

本次核对的行业文档没有可用于补齐的历史成员接口；这不等于对所有版本和所有第三方库作穷尽证明。未安装库或运行第三方采集脚本。

### 5. 公开爬虫文章与仓库：“历史”实际指行情

[2018 年文章](https://www.jianshu.com/p/13381aac9245)标题为“Python爬虫-同花顺行业历史数据及成分股”，正文历史数据来自按年份划分的指数行情，成分另取当前页面。

关联[公开仓库](https://github.com/sadjjk/tonghuashun_industry)只有一个提交 `acb844148ab4cdb109828af8555a14781596a3de`（2018-08-17），列出三个 Python 文件，无成员数据集或发布包。[industry_history.py](https://github.com/sadjjk/tonghuashun_industry/blob/master/industry_history.py)可见字段为日期、开高低收、成交量、成交额，没有股票成员或历史归属字段。不能把代码提交日期当作成员快照日期。第三方代码未执行。

### 6. Wayback：存在首页存档线索，尚不能确认历史成员覆盖

[公开存档日历](https://web.archive.org/web/*/https://q.10jqka.com.cn/thshy/)显示该 HTTPS 首页保存 565 次，范围从 2016-12-22 至 2026-05-18；这是本次页面所示抓取范围，不是行业业务数据最早覆盖声明。

进入其 [URLs 清单](https://web.archive.org/web/*/https://q.10jqka.com.cn/thshy/*)后，页面返回 `Wayback Machine failed to return archive information.`。当前仅取得首页捕获元信息，未取得可校验的行业详情、完整分页成员或成员变化记录；清单失败不能解释为没有任何详情存档。

即便后续找到单个历史详情，也须逐一确认抓取时点、行业身份、全部分页和证券集合。不同页抓取时间可能不同；零散存档不得向前后日期填充为连续历史，抓取日期不得直接称为分类生效日期。本轮网页调查不作为共享下载/代理的业务实采验收。

## 继续实施前的具体取数验证

当前策略以免费公开来源为先，不再把“等待用户提供账号”作为唯一后续。公开存档是未完成核实的候选；SuperMind 与 iFinD 保留为需账号的文档候选，未注册、付费、申请试用或安装。任何一个来源能独立满足业务即可，不要求双源全量核对。

接入仍缺少可验证的真实历史成员样本，当前没有证据支持承诺免费完整补齐。缺失的是同一分类体系下的历史行业目录、日期对应的完整股票成员集合，或足以重建这些集合的完整调入调出事件与生效日。

取得访问条件后，先执行有界样本核实：

1. 明确同花顺行业层级，与当前 thshy 行业代码逐项映射；不能按行业名称拼接或混用其他分类。
2. 查询资金已有起点2026-05-11、文档示例2023-08-01等少量完整业务单元；日期是验证目标，不预设来源一定支持。
3. 纳入真实分类变化的前后日期及上市/退市边界，证明来源确实处理历史日期；相同结果本身不能证明历史能力。
4. 核对完整目录/成员的来源总数、唯一键、关联、分页和截断，不仅比较条数。样本成功响应不长期另存为业务副本。
5. 分别记录最早实际可取、连续完整、缺失和权限受限范围；没有响应不解释为历史无成员。
6. 先完成业务粒度、结构化字段、查询索引、容量、完整性、迁移与恢复设计，再接入共享下载/代理、Redis 入队、统一归档及正式历史查询。来源核实和实采遵循现行采集指南；网页文档阅读不作为代理实采验收。

当前没有新增数据集或表的实现设计，也不预先创建空历史库、凭空生成历史关系或将观察日期写成生效日期。现有板块资金缺失提示不能改成已可用。

## 实际交付边界

本次未找到已验证可用的免费公开同花顺历史成员来源，公开网页存档仍仅是待验证线索。真实历史成员补齐、历史存储、资金按历史成员聚合均未完成；新增历史记录 0 条，不承诺未经验证的最早年份或免费全历史。未来开始保存真实快照只能积累后续历史，不能完成更早历史补齐；其他行业分类不得静默替换同花顺口径。纯调查记录不触发客户端构建、重启或数据库维护。

本轮只更新此调查证据，不改变页面、任务、表、Redis 键或用户使用契约，因此不刷新其他功能的文档审阅记录。验证范围为文档契约；没有业务实现变更，不执行采集、数据库或桌面发布验收。
