# 开盘啦七产品

本业务包拥有 trend、auction、volume、trades、entrust、large_order、quote 七套独立任务、数据贡献和页面。入口为 bundle.py；插件ID、任务ID、数据集、schema、既有稀疏装配顺序和来源范围保持各自声明。

| 需求 | 入口 |
| --- | --- |
| 产品身份、产品与能力名 | contract.py |
| 上市/市场日期范围 | dates.py；上市资料下载在 listings_source.py |
| 北交所历史代码纯证明/解析 | alias_contract.py；实际请求在 alias_source.py |
| 来源协议与匿名每次尝试参数 | source_protocol.py |
| 纯来源解析 | parser.py / pair_parser.py |
| 共享下载/预取/轮次状态 | collector.py / product_source.py / download.py / refresh.py |
| quote单次显式证券/日期闭区间及公共收盘时刻资格 | selection.py / closing.py |
| 证券日规范、内容摘要、入库可表示性 | normalization.py / canonical.py |
| 结构化存储与可逆编码 | storage_contract.py / codec.py / trade_blocks.py；schema.py读取正式结构清单 |
| 统一归档组合及事务内读写 | dataset.py / repository.py |
| 正式查询与范围验收 | query.py / audit.py / scope.py |
| 对其他业务的连接内行情输入 | api.py 的 ValidatedDayReader；query.py 唯一实现 iter_validated_days |
| 页面声明/控件 | ui.py 注册；product_page.py、quote_page.py和各视图叶子拥有控件 |
| 旧配对数据显式转换 | legacy_pair.py，仅维护入口使用；正常运行不依赖其旧数据契约 |

iter_validated_days(conn, market, code, start, end) 是惰性迭代。调用方拥有已开始的连接/事务；本方法既不关闭/重开连接，也不调用 mysql.read。必须在调用方事务作用域内消费；超过10000个日头拒绝，每16日加载事实；规范内容、身份、摘要和版本校验失败即向调用方报错。复权在自己既有 REPEATABLE READ 事务内调用，行情、证券身份、日历和公司行动仍处于同一快照。

normalize 的 storage_check=True 仍执行 codec.encode 检查可表示性；repository.read_day 用 storage_check=False 重建规范内容并核对点数、契约版本、内容摘要与键集合。禁止靠删去这一步解决依赖循环。摘要仍排除仅供观察的来源metadata；旧响应/重复内容/提交后重放规则由现行统一归档路径执行。

使用说明继续通过程序内开盘啦相关主题提供。维护路径与现行测试保留：tests/test_kaipanla*.py、test_market_mapping.py、test_market_suspension_days.py，以及 integration/test_kaipanla_products_archive.py、test_kaipanla_suspension_scope.py、test_market_storage.py、test_adjustment_pipeline.py。新增公开连接边界用 test_kaipanla_public_inputs.py 核查惰性、既有conn和失败顺序。以上列举是验证入口，不代表迁移已通过验证。

scripts/verify_kaipanla.py 使用共享source_verification/PrivateStorage生命周期，显式独立13348配置、实际server_uuid、UUID归属与SQL守卫；参考日历/停牌只读快照在私有守卫建立前完成。最低随机30、显式seed及proxy-only不可省略，原002731/三只北交所/605333反例额外固定加入；日期由显式有界规划控制。观察正式来源规范化、Redis入队、统一归档、day与完整分页的集合/内容，记录每随机证券的有效单元，不将有来源缺口的管线一致当成30股全成功。来源失败保留首缺口及严格FAIL；清理/取消/恢复由共享生命周期执行，不写生产业务或改变日常计划。

若改变来源/范围/参数/解析/版本/校验/恢复行为，必须满足采集开发指南随机30股及已知失败固定回归；纯组织迁移也需独立的隔离恢复、有限真实正式查询、UI和发布证据。实际结果和动态缺口单列到docs/evidence，不把本文作为已执行证明。

collect-intraday的quote可选--securities/--start/--end/--proxy-priority只作用本轮；同一正式collector与control执行，范围写入既有活动记录及断点。待归档范围不能被新范围覆盖；有限范围完成不推进全池每周复核标记。无参数日常行为及保存网络/任务策略保持，其他六项不支持该有限参数。

## 程序内说明维护

离线帮助的权威正文位于本包 [docs/help/intraday.md](docs/help/intraday.md) 及同目录其他完整主题；[来源清单](../../documentation/help-index.json) 统一声明阅读顺序。修改片段后在发布冻结前显式执行 scripts/documentation_build.py generate，再完成文档审阅与相关验证。原有来源指南继续解释业务契约；生成聚合物不手工维护。
