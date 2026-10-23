# 开盘啦题材来源契约与第二批实现

## 范围与环境

2026-10-24继续实施。用户确认保留子题材，热度和排名缺失时显示“来源未提供”。本批实现来源解析、共享HTTP匿名详情及日内身份/精度修订；没有声明全题材已上线。另一个同项目聊天在研究同花顺接口，因此未操作共享迁移、正式采集、归档或发布，未修改其模块。开工两项旧文件仅有行尾工作区标记，无语义差异，本批不混入提交。

读取已安装APK及运行进程专用`[anon:dalvik-DEX data]`代码映射，仅提取DEX代码；没有读取账号配置、会话数据或登录帧，没有修改或重启模拟器应用。APK SHA-256：`eb0fa9f9109104f87a1dd88705e8344ee38d17cc42d50bb7bbf588c4c3625457`。相关DEX代码摘要：`265e5dc7013a234a7bf75540e9173a9496e367008db3a8526c9e5a5145aa9e1c`、`fce98010a73de86b0025906f559bacce436aff03a31a65615a02de8b49422b2b`。第三方反编译结果仅在本地build调查目录，不作为项目源码或发布资源。

## 来源核实

- 应用ThemeExcavateListModel在channel3009发送空HQListReq；Hq.themeListResp根字段为codeSwitch、state、items，未定义总数。旧项目“收到1条即可返回”不是完整性证明。
- Item字段：1 id、2 name、3 desc、4 pinyin、5 isHot、6 hotVal、7 ztNum、8 upNum、9 isNew、10 plateSwitch、11 createTime、12 ratio(binary32)、13 list(Concept)。Concept字段为CID、name、pinyin、ratio(binary32)、ztNum，没有独立热度或排名。
- ThemeExcavateListBean映射按根条目顺序累计排名，只在isNew=0时递增；子项复用父ID并另带CID。本项目区分展示顺序与排名，不给新题材/子项编造名次。hotVal与isHot分别解读，不能把热度标记当热度值。
- 静态调用定位到Theme.InfoSearch(key)与InfoSearchHot(ID)。通过共享代理匿名核实：空关键词搜索返回空List，后者返回成功状态但无目录。它们不能替代全目录。
- 当前SocketRepository使用挑战签名；AuthReq存在userId默认0、token默认空串分支，但仍调用原生whiteBoxEncrypt生成签名。此代码只证明有游客参数分支，不证明游客能获得完整目录。未伪造登录成功或复用已登录Socket。

## 实际修改

- catalog_protocol：有界严格protobuf解码，拒绝重复标量/重复身份、截断、类型变化、未知字段和非有限浮点；保留原始state/codeSwitch而不猜状态语义。没有把解码成功冒充来源完整。
- catalog_mapping/history_model：父ID与CID组合身份、子项NULL热度/排名、新题材排名空值、binary32精确十进制往返；未部署的开发契约直接更新，不建立运行时旧格式兼容分支。
- detail_source：只使用共享下载器，固定详情动作及显式项目，随机DeviceID，无账号字段、禁止重定向，复用strip_credentials删除共享客户端继承的Cookie/Authorization。
- detail_model：结构化正文、分类、证券和关联理由；按分类ID/证券代码/名称/理由交叉核对Table和StockList.Tag。同证券不同分类的理由分别保留。证券保留来源代码，正式SQL前仍须公共身份映射。

## 真实来源范围

本批最终详情规范化验证共3次共享代理请求，直连/回退均0，均未登录；仅运行infra.http依赖和只读SQL守卫，不启动采集器或归档器，不持久化成功原始响应。

| 题材 | 分类 | 唯一证券 | 关联 | 集合及理由核对 |
|---|---:|---:|---:|---|
| 军工148 | 71 | 177 | 253 | 通过 |
| 电力229 | 27 | 218 | 273 | 通过 |
| AI硬件25 | 88 | 385 | 505 | 通过 |

这三项是固定来源样本，不是随机30题材，不是30股票门槛，也未经过Redis入队→统一归档→MySQL正式查询；完整目录尚未取得，因此没有编造抽样池或换样凑数。Power=0本身不作为数据掩码判定，实际按名字/理由及集合校验。

## 验证与限制

来源与日内专项覆盖：同数异集、标签理由冲突、同父CID重复/跨父CID独立、热度值与标记区分、新题材不占排名、掩码/非法身份、字段截断、未知结构、非有限浮点、binary32精确值、真实共享HTTP继承凭据剥离和缓冲释放。日内真实Redis使用专属UUID前缀，测试MySQL使用本批独立15327实例及完整schema隔离框架，不更改生产表或共享服务。

最终专项命令：`python -m pytest tests/test_theme_history_model.py tests/test_theme_catalog_protocol.py tests/test_theme_detail_source.py tests/integration/test_theme_history.py -q --tb=short`，启用EMPIRE_INTEGRATION并指定独占测试MySQL设置；72 passed，32.01秒。ruff通过。文档生成/审阅及verify_documentation通过（429篇、3597链接、55个schema表）。测试结束后15327实例已正常shutdown，未重启共享Redis或生产MySQL。

文档sources/review/contracts/build四组回归57 passed，70.10秒；最后的证据记录更新后再次执行正式文档审阅与校验。没有执行完整发布门禁或生成EXE，因为正式来源与归档接线未完成。

仍未完成：游客Socket签名/完整帧/状态契约及全目录实际样本，共享Socket传输，正式采集调度/入队归档、SQL维护与查询、数据准备、页面、真实端到端/容量及发布。根Stocks非空或新分类层级暂明确拒绝，后续须核实再扩展，不跳过有效业务。不得把本批结果描述为全部题材已完整采集。
