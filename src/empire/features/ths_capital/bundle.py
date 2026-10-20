"""Capital-operation declarations at the original stable slots."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.ths_capital.collector import CapitalPageCollector
from empire.features.ths_capital.dataset import CapitalPageDataset
from empire.features.ths_capital.query import CapitalPageDataPlugin
from empire.features.ths_capital.ui import CapitalPageUiPlugin


def bundle(cfg):
    return FeatureBundle('ths_capital', plugins=(
        OrderedContribution(500, CapitalPageDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(600, CapitalPageCollector()),
        OrderedContribution(700, CapitalPageUiPlugin()),
    ), tasks=(
        OrderedContribution(400, TaskContribution('ths-capital', '公司资本运作（同花顺）', 'collector.ths_capital', 'ths',
                    '一次HTML完整采集融资、投资、交易、参股IPO及质押解冻，原币种与历史保留',
                    category='公司行动', source_name='同花顺', parallel_downloads=True, unit_name='只股票', default_enabled=False,
                    default_schedule=TaskDefaults('daily', daily_time='18:30', description='每天北京时间18:30完整核验页面历史和解除修订；启用后生效，可编辑。'),
                    fresh_description='重建当前股票池和页面全部栏目；保留历史；待归档阶段先确认原轮次。')),
    ), datasets=(
        OrderedContribution(100, DatasetContribution(CapitalPageDataset(), 'incremental',
                        {CapitalPageDataset.JOB: CapitalPageDataset.PROJECT}, schema_version=2)),
    ))
