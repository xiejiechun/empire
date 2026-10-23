# 题材日内历史（开发中）

实施授权和完整设计见 [实施方案](../../../../docs/kaipanla-theme-implementation.md)。此包尚未加入 builtin 白名单，不启动采集、不写MySQL，不存在已上线任务或页面。

当前实现：history_model.py验证规范目录并计算字段差异；history.py提供独立Redis键族的原子提交和按时回放。存储内核不证明来源完整，调用前须由未来来源插件验证完整目录。

2026-10-24新增catalog_protocol.py严格解码应用themeListResp，catalog_mapping.py映射来源主题材ID/CID、子题材空热度/排名和精确binary32涨跌幅；detail_source.py通过共享HTTP匿名读取，detail_model.py核对分类关联与股票标签集合/理由。详情调用剥离继承的Cookie/Authorization。真实军工、电力、AI硬件三题材通过来源解析，不代表完整目录或SQL归档验收。来源协议、实测范围与阻碍见[来源实施证据](../../../../docs/evidence/kaipanla-theme-source-2026-10-24.md)。

运行纯逻辑与来源专项测试：`.venv/Scripts/python.exe -m pytest tests/test_theme_history_model.py tests/test_theme_catalog_protocol.py tests/test_theme_detail_source.py -q`。

真实Redis集成通过现有隔离框架：设置EMPIRE_INTEGRATION=1及具备测试建库权限的EMPIRE_TEST_MYSQL_SETTINGS后运行tests/integration/test_theme_history.py。每例完整初始化UUID测试SQL库，Redis仅使用自有UUID namespace；测试不会清理共享业务。

当前catalog_source.py通过共享request_stream执行全新游客认证及首次目录订阅；guest_protocol.py严格处理挑战/请求，guest_crypto.py提供已对照原生运算的纯Python签名算法。每个连接使用随机设备ID、UserID=0且无Token，TLS与AES-GCM认证均必须通过。应用材料由GuestMaterial显式传入，未把APK、私钥、白盒表或AES密钥打包入项目；正式本地材料维护入口仍待实施，不依赖模拟器已登录会话。

2026-10-24实测匿名完整目录251主题材/1子题材，并经252条规范化→独占Redis两轮存储→按时回放集合和内容核对。见[游客目录证据](../../../../docs/evidence/kaipanla-theme-guest-catalog-2026-10-24.md)。本次数量不是固定目录总数。

未完成：本地协议材料维护入口、统一入队/归档、SQL维护/查询、正式调度、数据准备、列表和曲线页面、随机题材端到端及七日容量/正式发布。此包仍未注册任务；来源成功不代表全功能已上线。
