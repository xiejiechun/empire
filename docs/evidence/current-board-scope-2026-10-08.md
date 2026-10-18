# 当前板块成分准备范围调整

## 用户确认与改动

用户只需知道当前股票属于哪些来源名单，不要求历史板块起止日期或转板记录。数据准备项目改为“股票当前所属板块”，范围为同花顺 hs、ss、bj、cyb、kcb 五个当前完整成分名单。成员身份为名单编号＋股票编号，允许交叉归属，不相减推导主板。仅保存当前成员，行业分类独立。

修改 preparation_foundation.py 中既有目录声明，并同步 docs/data-preparation.md 及程序内 storage_reference.md 的数据准备主题；既有 preparation 页面主题关联继续适用。本次未开发采集器、数据库表或实际数据验收，未部署程序。

## 验证及共享环境

工作区已有大量修改，均保留。另一聊天正在修复采集错误，本次未操作数据库、采集服务、桌面或发布目录。

执行 tests/test_preparation.py 与 tests/test_preparation_cache.py，共 40 项通过。最后修改后执行 documentation_contract.py review，审阅成功；随后的 verify_documentation.py 被另一聊天对 kaipanla_scope.py 的修改阻断，报告审阅过期。全项目文档验证须在并行修复停止修改后重新执行，本记录不宣称全项目门禁或实际采集验收完成。
