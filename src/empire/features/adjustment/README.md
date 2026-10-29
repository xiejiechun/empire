# 自算复权因子与行情

本包拥有只读复权计算及页面，不创建第二套采集或因子存储。正式输入自2026-10-25起切为远航版不复权日线与同源除权事件；旧通达信方案和开盘啦快照不再进入本页计算。名义股息率仍属于分红业务的独立用途，本批未替换该口径。

- contract.py：来源每原股事件、理论参考价、区间因子和版本。
- inputs.py：沿调用方SQL快照使用yuanhang.api并核对正式日历。
- query.py：证券解析、同一RR快照、查询与准备检查。
- ui.py及chart.py：按需创建的K线、因子曲线、事件输入回链。

最多150年/54900价格行，事件最多2000个；首日归一，不写业务SQL。未知输入拒绝复权，已验证原始行情可单独显示。使用和限制见[复权说明](../../../../docs/adjustment-factors.md)。

权威帮助在docs/help，修改后运行documentation_build.py generate和文档审阅。专项及端到端入口为tests/test_adjustment.py、tests/test_adjustment_query.py、tests/test_adjustment_chart.py及tests/integration/test_adjustment_pipeline.py。