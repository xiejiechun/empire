"""Acceptance detail: specification, per-check evidence and actionable blockers."""
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from empire.features.preparation.definition import SCOPE_POLICY, SOURCE_POLICY, VERSION_POLICY
from empire.features.preparation.results import summarize
from empire.features.preparation.ui_words import (
    PRIORITY,
    STATUS,
    action,
    check_title,
    expected,
    finding,
    plain,
)
from empire.plugins.ui.common import rows, table

LABELS = {'pass': '没问题', 'fail': '有问题', 'unknown': '还没查清'}


def result_label(item):
    return LABELS[item['status']] if item.get('blocking', True) else '用途限制'


class PreparationDetail(QWidget):
    def __init__(self):
        super().__init__()
        self.entry = None
        self.checks = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.heading = QLabel('选一项，看看做到哪了')
        bar.addWidget(self.heading, 1)
        self.source = QComboBox()
        self.source.setAccessibleName('数据来源')
        self.source.currentIndexChanged.connect(self.render_checks)
        bar.addWidget(self.source)
        layout.addLayout(bar)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('数据准备详细信息')
        layout.addWidget(self.tabs)
        acceptance = QWidget()
        acceptance_layout = QVBoxLayout(acceptance)
        self.table = table(['检查什么', '哪一部分', '结果'])
        self.table.setAccessibleName('每一步检查结果')
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 100)
        self.table.itemSelectionChanged.connect(self.show_check)
        acceptance_layout.addWidget(self.table, 1)
        self.evidence = QTextBrowser()
        self.evidence.setAccessibleName('检查要求、实际情况和下一步')
        acceptance_layout.addWidget(self.evidence, 1)
        self.tabs.addTab(acceptance, '逐项看看')
        self.specification = QTextBrowser()
        self.specification.setAccessibleName('需要准备的具体内容')
        self.tabs.addTab(self.specification, '要准备什么')
        self.blockers = QTextBrowser()
        self.blockers.setAccessibleName('还缺什么和先做什么')
        self.tabs.insertTab(0, self.blockers, '还差什么')
        self.tabs.setCurrentWidget(self.blockers)
        self.technical = QTextBrowser()
        self.technical.setAccessibleName('给开发人员的详细检查记录')
        self.tabs.addTab(self.technical, '详细检查记录')
        self.findings = table(['证券', '报告期', '检查项', '问题'])
        self.findings.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((110, 120, 170)):
            self.findings.setColumnWidth(column, width)
        self.findings.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.findings.setAccessibleName('证券报告期问题样例')
        self.tabs.addTab(self.findings, '问题定位')

    def render(self, entry):
        old_id = self.entry['id'] if self.entry else None
        old_source = self.source.currentText() if old_id == entry['id'] else entry['source']
        self.entry = entry
        self.heading.setText(f"{plain(entry['title'])} · {STATUS.get(entry['status'], entry['status'])}")
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItems([p['source'] for p in entry['providers']])
        self.source.setCurrentIndex(max(0, self.source.findText(old_source)))
        self.source.blockSignals(False)
        spec = entry['specification']
        self.specification.setPlainText(
            f'{plain(spec.title)}\n\n工作类型：{spec.kind}\n本项范围：{plain(spec.boundary)}\n\n用来做什么：{plain(spec.purpose)}\n准备顺序：{PRIORITY.get(spec.priority, spec.priority)}\n'
            f'每条记录表示什么：{plain(spec.grain)}\n\n必需信息：\n{plain(spec.fields)}\n\n'
            f'可选信息（缺少不影响本项通过）：\n{plain(spec.optional_fields) or "无额外要求"}\n\n'
            f'怎么识别重复记录：\n{plain(spec.key)}\n\n要收集到什么程度：\n{plain(spec.coverage)}\n\n'
            f'多久更新一次：\n{plain(spec.cadence)}\n\n'
            f'日期与使用口径：\n{plain(next(c.expected for c in spec.criteria if c.id == "temporal"))}\n\n'
            f'怎样判断可用：\n{SOURCE_POLICY}\n{SCOPE_POLICY}\n{VERSION_POLICY}\n\n'
            '这些是要做的事情。写进清单不代表已经做好，要检查后才能算完成。')
        self.render_checks()

    def render_checks(self):
        if not self.entry or self.source.currentIndex() < 0:
            return
        provider = self.entry['providers'][self.source.currentIndex()]
        self.checks = provider['checks']
        assessment = summarize(self.checks)
        self.heading.setText(f"{plain(self.entry['title'])} · 用途：{assessment['use_state']} · 开发验收：{assessment['development']}")
        rows(self.table, [[check_title(c), c.get('dimension', c['phase']), result_label(c)] for c in self.checks],
             keys=[c['id'] for c in self.checks])
        if self.table.rowCount() and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.show_check()
        remaining = [c for c in self.checks if c['status'] != 'pass' and c.get('blocking', True)]
        development_remaining = [c for c in remaining if c['phase'] == '开发']
        data_remaining = [c for c in remaining if c['phase'] == '数据']
        restrictions = [c for c in self.checks if not c.get('blocking', True)]
        pieces = [SOURCE_POLICY, f"本项只负责：{plain(self.entry['specification'].boundary)}",
                  f"本次结论：{assessment['outcome']}（仅限下述用途与范围）",
                  f"配合使用的数据：{'、'.join(plain(v) for v in self.entry['related']) or '无'}（不影响本项单独完成）",
                  f"还需要先准备好：{'、'.join(plain(v) for v in self.entry['blockers']) or '没有其他数据挡着这一步'}",
                  f"本项功能：{'已开启' if provider['running'] else '未开启或还没接入'}。暂停运行不代表功能没做好。",
                  '检查范围：' + provider.get('scope', self.entry.get('scope', '来源声明范围')),
                  '采集完整性、来源质量、用途条件分别查看；采集一致不代表来源金额无异常。',
                  f"开发验收有 {len(development_remaining)} 项待处理；数据用途有 {len(data_remaining)} 项阻断或待确认，另有 {len(restrictions)} 项限制。"]
        pieces.append('实际来源/归档证据时间：' + ('、'.join(sorted({c['observed_at'] for c in self.checks if c.get('observed_at')}))
            or '见逐项实际记录；没有独立时间字段的检查不能以本次执行时间代替'))
        pieces.append('已满足条件：' + ('、'.join(check_title(c) for c in self.checks
            if c['phase'] == '数据' and c['status'] == 'pass') or '尚无'))
        for c in remaining:
            pieces.append(f"【{check_title(c)} · {result_label(c)}】\n"
                          f"现在：{finding(c)}\n接下来：{action(c)}")
        pieces.extend(f"【用途限制】{finding(c)}\n{action(c)}" for c in restrictions)
        details = [[x.get('code', ''), x.get('report_date', ''), check_title(c), x['message']]
                   for c in self.checks for x in c.get('findings', ())]
        rows(self.findings, details)
        pieces.append('问题定位每个检查项最多列出 100 个样例，完整数量见逐项记录；不把样例数量当作问题总数。')
        self.blockers.setPlainText('\n\n'.join(pieces))
        self.technical.setPlainText('以下保留具体检查记录，排查问题时使用。\n\n' + '\n\n'.join(
            f"{c['title']} · {c['status']}\n标准：{c['expected']}\n记录：{c['measured']}\n后续：{c['action']}"
            for c in self.checks))

    def show_check(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.checks):
            item = self.checks[index]
            self.evidence.setPlainText(
                f"{check_title(item)} · {result_label(item)}\n\n怎样才算做好：\n{expected(item)}\n\n"
                f"现在查到的情况：\n{finding(item)}\n\n"
                f"接下来做什么：\n{action(item) if item['status'] != 'pass' else '这一步已通过，以后数据或功能变化时会重新检查。'}")

    def clear(self):
        self.entry = None
        self.checks = []
        self.heading.setText('没有找到符合条件的数据')
        self.source.clear()
        rows(self.table, [])
        rows(self.findings, [])
        for browser in (self.evidence, self.specification, self.blockers, self.technical):
            browser.clear()
