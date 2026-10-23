"""Theme ownership uses the same collection and archive contribution contracts."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.themes.collector import ThemeCollector
from empire.features.themes.dataset import ThemeDailyDataset, ThemeDetailDataset
from empire.features.themes.query import ThemeDataPlugin
from empire.features.themes.ui import ThemeUiPlugin


def bundle(cfg):
    collectors = [ThemeCollector(kind, cfg.get('kaipanla_guest')) for kind in ('list', 'detail')]
    mappings = [ThemeDailyDataset(), ThemeDetailDataset()]
    return FeatureBundle('themes', plugins=(
        OrderedContribution(30000, ThemeDataPlugin(cfg.get('archive', {}))),
        *(OrderedContribution(30010 + i, c) for i, c in enumerate(collectors)),
        OrderedContribution(30020, ThemeUiPlugin()),
    ), tasks=tuple(OrderedContribution(30000 + i, TaskContribution(
        c.project_id, '题材' + ('列表与日内变化' if i == 0 else '最新详情') + '（开盘啦）', c.capability,
        'kaipanla', '匿名全目录；最近七个自然日日内差异' if i == 0 else '补齐缺失题材，分批核验最新详情',
        interval_seconds=180, category='题材数据', source_name='开盘啦', parallel_downloads=i == 1,
        default_schedule=TaskDefaults('interval', 180, description='每轮完成后等待180秒；同一任务不重叠。'),
        fresh_description='保留已有日内历史与每日列表；详情优先补齐，单轮最多32题材。', unit_name='个题材'))
        for i, c in enumerate(collectors)), datasets=tuple(
            OrderedContribution(30000 + i, DatasetContribution(m, 'incremental', {m.JOB: m.PROJECT}))
            for i, m in enumerate(mappings)))
