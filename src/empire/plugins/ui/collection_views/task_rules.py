"""Read-only rule inspector, independent of task drafts and refresh timers."""
from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QComboBox, QTextBrowser, QVBoxLayout, QWidget

from empire.plugins.collection.rules import collection_rules
from empire.plugins.ui.help_content import topics
from empire.plugins.ui.help_reader import render_article


@lru_cache(maxsize=1)
def rule_topics():
    return topics()


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def rule_markdown(job, cfg):
    rule = collection_rules().get(job['id'])
    if rule is None:
        return '# 采集规则不可用\n\n## 规则缺失\n\n当前任务尚未登记有效规则，请检查程序发布资源。'
    namespace = cfg.get('redis', {}).get('namespace', 'empire:dev')
    database = cfg.get('mysql', {}).get('database', '配置中的MySQL数据库')
    text = [f"# {job['name']} · 采集规则", '只读规则随程序版本更新；不触发采集、不保存或修改任务草稿。'
            '以下是程序支持的计划范围，不表示已采完；实际进度见运行详情与数据浏览。',
            '## 来源链接与请求参数',
            '未注明可配置的参数均由采集器固定或按当前采集单元自动生成，不能在任务配置中任意修改。'
            '无参数的静态文档直接GET。网址为请求契约，可选中复制；不会在本页自动请求。']
    for request in rule['requests']:
        text += [f"### {request['purpose']} · {request['method']}", f"`{request['url']}`"]
        if request['method'] == 'POST' and '/TQLEX?' in request['url']:
            text += ['参数按下标从0开始组成 `{"Params":[...]}` JSON请求正文；'
                     '按来源协议声明 `application/x-www-form-urlencoded; charset=UTF-8`。']
        elif request['method'] == 'POST':
            text += ['参数通过表单正文提交；明确标注为查询参数的字段放在URL查询串。']
        else:
            text += ['路径模板中的变量替换到URL；其余参数通过URL查询串提交。']
        if request['parameters']:
            rows = ['| 参数/位置 | 取值与设置方式 | 含义 |', '| --- | --- | --- |']
            rows += ['| ' + ' | '.join(cell(p[k]) for k in ('name', 'value', 'meaning')) + ' |'
                     for p in request['parameters']]
            text.append('\n'.join(rows))
        else:
            text += ['无查询参数或请求体；直接读取所列文档。']
    for title, key in [('证券与市场范围', 'scope'), ('采集范围开始', 'start'), ('采集范围结束', 'end'),
                       ('初始化怎么采集', 'initial'), ('增量、补缺与修订', 'incremental'),
                       ('重新采集', 'fresh'), ('中断与Redis丢失', 'recovery'), ('限制', 'limits')]:
        text += [f'## {title}', rule[key]]
    text += ['## Redis与MySQL去向', f"任务ID：`{job['id']}`；job_key：`{rule['job_key']}`。",
             f"Redis Stream：`{namespace}:ingest`，字段 `envelope` 保存规范化业务消息；"
             '不是源站成功原文，也不是每任务独立队列。按 job_key 和 dataset 识别本任务消息。',
             '数据集：' + '、'.join(f'`{v}`' for v in rule['datasets']) + '。',
             f"Redis Hash断点：`{namespace}:checkpoint:{rule['job_key']}`，字段 `revision` 和 `cursor`；"
             '业务入队与已入队断点原子提交，已入队不代表已归档。',
             f"MySQL数据库：`{database}`（当前程序配置）；业务表：" +
             '、'.join(f'`{v}`' for v in rule['tables']) + '。',
             f"统一状态：`collection_state`，主键 `(namespace, project_id)` = (`{namespace}`, `{job['id']}`)。"
             'SQL状态与业务变更同事务提交；可信摘要命中不刷新SQL核验时间。',
             '摘要桶：' + '、'.join(
                 f"`{namespace}:archive:fingerprints:v1:{v}:{rule['fingerprint_source']}`" for v in rule['fingerprint_namespaces']) +
             '；配对 `:expiry` ZSET。仅保存摘要与版本，默认最后成功确认后7天、每桶最多10000键。',
             '统一归档器独立消费；插入、更新、确认相同、可信摘要命中、确认旧版无需写入均成功清除对应消息；'
             '失败留队。聚合分页未收齐继续暂存。整轮入队结束后才等待全部归档，不逐批阻塞下载。',
             '任务与网络计划保存于 `app_setting`；运行记录、错误样本和临时计划只存Redis。'
             'Redis或电脑重启丢失这些临时状态；仅重启Empire且Redis仍在可续跑。',
             '## 配置在哪里设置',
             '任务配置可修改启停、执行方式、间隔秒数、每日北京时间、重试次数与网络方式。'
             '固定间隔为1～2592000秒，从上轮结束后计时；同任务不重叠。请求重试为0～100次。'
             '保存到MySQL；执行计划立即生效，重试与网络下一轮生效。默认代理优先、不可用可退回直连；已保存选择优先。'
             '网站频控在采集管理→站点访问规则设置；下载资源保存后正常重启生效。'
             '日期/证券范围按本任务规则生成；任务配置未提供的范围输入不能在此编辑。',
             f"## 规则依据\n\n实现：`{rule['source_file']}`。下面复用程序内来源专项说明，包含数据字段、恢复细节与查询限制。"]
    for title in rule['topics']:
        body = rule_topics()[title]
        text += [body.replace('# ' + title + '\n', '## ' + title + '\n', 1)]
    return '\n\n'.join(text)


class TaskRules(QWidget):
    def __init__(self):
        super().__init__()
        self.identity = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        self.chapters = QComboBox()
        self.chapters.setAccessibleName('采集规则章节')
        self.browser = QTextBrowser()
        self.browser.setAccessibleName('采集规则正文')
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.browser.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                             Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(self.chapters)
        layout.addWidget(self.browser, 1)
        self.chapters.activated.connect(self.jump)

    def show_job(self, job, cfg):
        if self.identity == job['id']:
            return  # Runtime refresh must not reset selection or reading position.
        self.identity = job['id']
        render_article(self.browser, self.chapters, rule_markdown(job, cfg))

    def jump(self, index):
        cursor = self.browser.textCursor()
        cursor.setPosition(self.chapters.itemData(index) or 0)
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()
