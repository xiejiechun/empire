"""Financial statements at their original stable contribution positions."""
from empire.contracts.bundle import FeatureBundle, positioned
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution
from empire.features.financial_statements.collector import ThsStatementCollector
from empire.features.financial_statements.contract import KINDS as FINANCIAL_KINDS
from empire.features.financial_statements.dataset import FinancialDataset
from empire.features.financial_statements.query import FinancialDataPlugin
from empire.features.financial_statements.ui import FinancialUiPlugin
from empire.features.financial_statements.wire import SCHEMA_VERSION as FINANCIAL_SCHEMA_VERSION


def bundle(cfg):
    return FeatureBundle('financial_statements', plugins=(
        *positioned((13800, 13900, 14000), (FinancialDataPlugin(kind, namespace=cfg['redis'].get('namespace', 'empire'),
                                     archive_settings=cfg.get('archive', {})) for kind in FINANCIAL_KINDS)),
        *positioned((14100, 14200, 14300), (ThsStatementCollector(kind) for kind in FINANCIAL_KINDS)),
        *positioned((14400, 14500, 14600), (FinancialUiPlugin(kind) for kind in FINANCIAL_KINDS)),
    ), tasks=(
        *positioned((3500, 3600, 3700), (TaskContribution('ths-' + kind, item[0] + '（同花顺）',
                    'collector.ths_' + kind, 'ths', '逐证券完整历史 · 来源舍入金额 · 无公告日期',
                    category='基本面', source_name='同花顺', interval_seconds=86400, parallel_downloads=True, unit_name='只股票',
                    fresh_description='从当前股票池首个证券重查全部历史；保留已归档报表。')
                    for kind, item in FINANCIAL_KINDS.items())),
    ), datasets=(
        *positioned((3600, 3700, 3800), (DatasetContribution(FinancialDataset(kind), 'incremental',
                                          {'ths-' + kind + '-v1': 'ths-' + kind},
                                          schema_version=FINANCIAL_SCHEMA_VERSION) for kind in FINANCIAL_KINDS)),
    ))
