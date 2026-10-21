# F 帮助目录真实桌面反例与修复

当前最终状态：本批适用组织治理与帮助修复已验收。修复包280a7da/release4f8f55d0完整发布、冻结T3及同包真实桌面、配置恢复和正常关开均完成；主体结案da01218已推送精确核实；最后远程证据后记随本次提交交付。见[真实桌面结案](architecture-f-desktop-2026-10-21.md)、[最终逐编号报告](architecture-final-2026-10-21.md)。H3/E4严格来源及历史准备失败不冲销。下文为开发与失败历史，旧“待完成”不代表当前状态。

## 首包失败与现场恢复

干净实现`f2fbe995ab4c975808b42769fe26e50f849f2f43`的正式发布`b1193f65e3084a88a82b17c71ba40499`自然退出0，journal为committed/passed。完整3971 passed、5个原隔离单元opt-in skips、20个弃用警告；1970输入、58输出和25步骤退出码已核对。同包异cwd doctor真实连接、股票/新闻/日历正式API和包内143主题字节核对通过；这些不替代真实桌面。

13:40窗口10227532/PID29740可见工作台、持有人及帮助首页；折叠“入门”和“日常操作”后长期未响应。原生主线程在Qt/Windows UI Automation/COM中；后台财报仍推进，不能据此判财报为根因。多次正常关闭失败后，用户明确仅授权结束29740；核实可执行路径后仅结束该应用，未结束服务或删除锁。其后只读核查pending=0、原config/偏好及冻结文件保持。

重开同包窗口21827388/PID30584，纯截图操作再次复现。没有重新请求无障碍文本仍出现未响应，不能将不用文本当成修复。对30584另行询问授权期间继续开发；重建电脑操作连接后它恢复响应，14:10最终Alt+F4正常退出，进程及窗口消失，未强制结束30584。退出后再次核实pending=0、私库仅四系统库/无其他客户端、原config/偏好及冻结文件保持。

隔离帮助小窗口不连接SQL、Redis或采集；定时折叠与心跳正常。但有遮挡、激活超时及无障碍文本null，不能记为真实交互通过或证明正式桌面已恢复。现场记录保留在本轮build。

## 可重复缺陷和唯一修复路径

Qt6.11.2树无障碍接口按可见行缓存子项。读取全部子项后折叠第一分类，缓存仍返回隐藏的“开始使用”等项，行号反查从2变为0；继续折叠出现更多失配。`probe_accessible_tree.py accessible-tree-before.json`退出1/consistent=false；正式新增测试同样断言失败，不以超时或ImportError代替反例。

对应Qt源码中`QTreeViewPrivate::collapse`移除可见行，`QAccessibleTree::child`以旧逻辑行命中缓存；`QAccessibleTable::modelChange(ModelReset)`清理它。上游源码仅下载在忽略的诊断目录，未替换依赖。堆栈和反例支持此修复方向，是否消除Windows卡顿仍须新包实际确认。

公共`plugins/ui/common.py`新增显式树绑定，在展开/折叠后向活跃无障碍客户端发送标准`QAccessibleTableModelChangeEvent(ModelReset)`；帮助目录在初始创建完成后使用。保持标准接口、目录/主题身份、正文及历史，不关闭无障碍、不新增插件/兼容层。其他页面未调用新绑定，原公共表格、查询及命令不改。首修直接调用PySide未暴露的tableInterface导致AttributeError，保留失败；改为标准公开事件后通过。

新增`test_accessible_directory_rows_follow_collapse_expand_and_search`实际激活Qt无障碍接口、预热全部行缓存、反复折叠/展开、跳主题、搜索及清搜索；逐项核对可见主题集合和反查行号，并验证折叠不改正文/历史。该离屏测试不冒充真实桌面。

“开始使用”权威正文补分类箭头/方向键、正文保持及无障碍定位，显式重新生成143主题聚合物；逐功能review对仅引用common的消费者记录未调用新增绑定的具体理由。未改变来源、网络、SQL/Redis、策略、schema或业务数据，随机30实采不适用；H3空名债券、E4严格来源及资本历史准备限制保留。

## 实际命令、失败与待完成

Python均为项目`.venv/Scripts/python.exe`，pytest均独立build basetemp并保存JUnit。

| 命令 | 退出码与结果 | 范围/限制 |
| --- | --- | --- |
| `probe_accessible_tree.py accessible-tree-before.json` | 1，consistent=false | 私有无服务Qt接口反例 |
| `pytest tests/test_storage_help.py::test_accessible_directory_rows_follow_collapse_expand_and_search` | 首1；首修1；标准事件修复0/1 passed | `tree-counterexample.xml`、`tree-fix-1.xml`、`tree-fix-2.xml` |
| 首相关十文件pytest | 1；109 passed/2 failed | 尚未generate聚合物、尚未最终review；`tree-regression.xml`保留 |
| `documentation_build.py generate`、显式review/check、`verify_documentation.py` | 各0；143主题/405文档/2326链接/55表 | `tree-fix-specific-review.json`逐消费者理由 |
| `ruff check src tests scripts`、`mypy`、architecture check、database design | 各0；strict13、409模块/1463导入/0债务、55表/49数据集/12JSON | 无放宽检查 |
| 帮助、公共交互、生命周期、文档、架构及发布相关十三文件pytest | 0；217 passed/94.95秒 | `tree-final.xml`，非全量发布 |

17容量报告的实际绑定没有本修复变动，数据库设计门禁通过。全源T3身份因common/help/正文变化失效，原通过报告仅属于首包，须按冻结协议完整重测，不能刷新旧hash。后续完整唯一发布、新包实际目录/搜索/链接/章节/历史、业务页、适用U1/U2/U3、正常关开、结案与推送尚待完成。


修复最终开发复核：最后README及事实文档审阅后，四文件文档/帮助pytest退出0，40 passed/65.41秒；review/check和verify_documentation退出0（406文档/2330链接/55表）。等待外部worker自然结束、无并发测试/构建后，原完整T3重测退出0，[新原始报告](architecture-f-tree-t3-2026-10-21.json)18/18通过、可比差异为空、cleanup=true，source db18e010363abc1b315d1ccce8af1466163987c85eba1ca3de2060cab5f45284；cold median 1192.947000ms/p95 1243.882540ms。冻结文件逐字节保持，原T3不替代本轮。下一步为干净修复提交、完整新发布与同包真实桌面。
