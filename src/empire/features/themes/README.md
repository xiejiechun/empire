# 题材日内历史（开发中）

实施授权和完整设计见 [实施方案](../../../../docs/kaipanla-theme-implementation.md)。此包尚未加入 builtin 白名单，不启动采集、不写MySQL，不存在已上线任务或页面。

当前实现：history_model.py验证规范目录并计算字段差异；history.py提供独立Redis键族的原子提交和按时回放。存储内核不证明来源完整，调用前须由未来来源插件验证完整目录。

2026-10-24新增catalog_protocol.py严格解码应用themeListResp，catalog_mapping.py映射来源主题材ID/CID、子题材空热度/排名和精确binary32涨跌幅；detail_source.py通过共享HTTP匿名读取，detail_model.py核对分类关联与股票标签集合/理由。详情调用剥离继承的Cookie/Authorization。真实军工、电力、AI硬件三题材通过来源解析，不代表完整目录或SQL归档验收。来源协议、实测范围与阻碍见[来源实施证据](../../../../docs/evidence/kaipanla-theme-source-2026-10-24.md)。

运行纯逻辑与来源专项测试：`.venv/Scripts/python.exe -m pytest tests/test_theme_history_model.py tests/test_theme_catalog_protocol.py tests/test_theme_detail_source.py -q`。

真实Redis集成通过现有隔离框架：设置EMPIRE_INTEGRATION=1及具备测试建库权限的EMPIRE_TEST_MYSQL_SETTINGS后运行tests/integration/test_theme_history.py。每例完整初始化UUID测试SQL库，Redis仅使用自有UUID namespace；测试不会清理共享业务。

未完成：匿名全目录/动态字段与Socket结束边界、共享网络接线、统一入队/归档、SQL维护/查询、数据准备、列表和曲线页面、真实题材端到端及容量/正式发布。军工详情匿名可取不等于匿名全目录已经得到证明。
