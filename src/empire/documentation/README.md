# 程序内说明的权威来源

业务片段与代码共同归属 `features/<业务>/docs/help/`；跨业务操作和公共存储说明放在 `topics/`。每个完整主题一篇文件。[help-index.json](help-index.json) 只规定归属、路径和阅读顺序，不复制主题正文或页面/任务关系。

片段直接放在对应目录，文件名只用小写英文字母、数字、下划线或连字符，并以 `.md` 结尾。检查器递归发现 Markdown 文件；嵌套片段、未登记文章、非规范文件名及链接/目录联接都会拒绝，不能通过移动到子目录绕过清单。

编辑本业务片段后，在发布冻结前执行 `python scripts/documentation_build.py generate`，再显式 review 与相关回归。生成的 [storage_reference.md](../plugins/ui/storage_reference.md) 供源码和 EXE 使用，禁止手工维护；未生成、手改聚合物或无效关联都会被 check/review 拒绝。

字段、索引、Redis 键等覆盖登记仍在既有 documentation-coverage.json 中，完整操作见 [说明文档维护](../../../docs/documentation-maintenance.md)。历史 evidence 不迁移、不改写。
