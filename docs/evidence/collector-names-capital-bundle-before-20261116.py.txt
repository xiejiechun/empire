"""Original business contributions at their unchanged positions."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution, positioned
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution
from empire.features.capital_actions.contract import KINDS, SCHEMA_VERSIONS
from empire.features.capital_actions.dataset import CapitalDataset
from empire.features.capital_actions.dividends_collector import TdxDividendsCollector
from empire.features.capital_actions.issues_collector import TdxAdditionalIssuesCollector
from empire.features.capital_actions.query import CapitalDataPlugin
from empire.features.capital_actions.rights_collector import TdxRightsIssuesCollector
from empire.features.capital_actions.ui import CapitalUiPlugin


def bundle(cfg):
    return FeatureBundle('capital_actions', plugins=(
        *positioned((12900, 13000, 13100), (CapitalDataPlugin(kind, namespace=cfg['redis'].get('namespace', 'empire'),
                                    archive_settings=cfg.get('archive', {})) for kind in KINDS)),
        OrderedContribution(13200, TdxDividendsCollector()),
        OrderedContribution(13300, TdxAdditionalIssuesCollector()),
        OrderedContribution(13400, TdxRightsIssuesCollector()),
        *positioned((13500, 13600, 13700), (CapitalUiPlugin(kind) for kind in KINDS)),
    ), tasks=(
        *positioned((3800, 3900, 4000), (TaskContribution(item[2], item[0] + '（通达信）',
                    'collector.tdx_' + kind, 'tdx', '全部可得历史核验 · 单证券完整归档',
                    category='增发送配', source_name='通达信', parallel_downloads=kind != 'rights_issues', unit_name='只股票',
                    fresh_description='从当前来源完整范围重新核验，保留已归档历史；普通采集优先续跑已入队断点。')
                    for kind, item in KINDS.items())),
    ), datasets=(
        *positioned((3900, 4000, 4100), (DatasetContribution(CapitalDataset(kind), "incremental", {item[2] + "-v1": item[2]},
                                          schema_version=SCHEMA_VERSIONS[kind])
                      for kind, item in KINDS.items())),
    ))
