"""Seven independent products; unchanged sparse contribution slots."""
from empire.contracts.bundle import FeatureBundle, positioned
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import HISTORICAL_DAY_DEFAULTS, TaskContribution
from empire.features.kaipanla.collector import KaipanlaProductCollector
from empire.features.kaipanla.contract import PRODUCTS, project
from empire.features.kaipanla.dataset import ProductDataset
from empire.features.kaipanla.query import KaipanlaProductDataPlugin
from empire.features.kaipanla.ui import KaipanlaProductUiPlugin


def bundle(cfg):
    return FeatureBundle('kaipanla', plugins=(
        *positioned((9800, 9900, 10000, 10100, 10200, 10300, 10400), (KaipanlaProductDataPlugin(kind, namespace=cfg['redis'].get('namespace', 'empire')) for kind in PRODUCTS)),
        *positioned((10500, 10600, 10700, 10800, 10900, 11000, 11100), (KaipanlaProductCollector(kind) for kind in PRODUCTS)),
        *positioned((11200, 11300, 11400, 11500, 11600, 11700, 11800), (KaipanlaProductUiPlugin(kind) for kind in PRODUCTS)),
    ), tasks=(
        *positioned((2500, 2600, 2700, 2800, 2900, 3000, 3100), (TaskContribution(project(kind), '开盘啦' + item.title,
                    'collector.kaipanla_' + kind, 'kaipanla', item.note,
                    category='高频行情', source_name='开盘啦', interval_seconds=86400, unit_name='股票日',
                    parallel_downloads=True, default_enabled=False,
                    default_schedule=HISTORICAL_DAY_DEFAULTS,
                    fresh_description='从 2021 年起逐证券日重新核验本项，保留已归档历史；普通采集补缺，每周回看最近五个交易日。')
                    for kind, item in PRODUCTS.items())),
    ), datasets=(
        *positioned((2800, 2900, 3000, 3100, 3200, 3300, 3400), (DatasetContribution(ProductDataset(kind), 'incremental',
                        {ProductDataset(kind).JOB: ProductDataset(kind).PROJECT}) for kind in PRODUCTS)),
    ))
