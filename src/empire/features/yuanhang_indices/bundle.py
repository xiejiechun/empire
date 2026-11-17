"""Three separately scheduled index tasks with truthful source ownership."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.yuanhang_indices import catalog_dataset, member_dataset, price_dataset
from empire.features.yuanhang_indices.catalog_collector import CatalogCollector
from empire.features.yuanhang_indices.member_collector import MemberCollector
from empire.features.yuanhang_indices.price_collector import PriceCollector
from empire.features.yuanhang_indices.price_query import PriceQuery
from empire.features.yuanhang_indices.query import CatalogQuery, MemberQuery
from empire.features.yuanhang_indices.ui import IndexUiPlugin


def bundle(cfg):
    namespace = cfg.get('redis', {}).get('namespace', 'empire')
    collectors = (CatalogCollector(), MemberCollector(), PriceCollector())
    queries = tuple(cls(namespace, cfg.get('archive', {})) for cls in (CatalogQuery, MemberQuery, PriceQuery))
    descriptions = (
        '远航版A股指数完整目录与原生市场、名称；以客户端实际集合为准',
        '原同花顺网页端当前成分；来源明确暂无正常完成并保持空，不提供历史调样',
        '远航原生指数日K；最近十交易日优先，每轮另补最多64个指数历史；缺值保留',
    )
    titles = ('A股指数', '指数成分', '指数日K')
    tasks = tuple(OrderedContribution(40200+i, TaskContribution(c.project_id, titles[i], c.capability,
        'ths' if i == 1 else 'ths_yuanhang', descriptions[i], category='指数数据',
        source_name='同花顺' if i == 1 else '同花顺远航版',
        parallel_downloads=i != 0, unit_name='个指数',
        default_schedule=TaskDefaults('daily', description='每天北京时间18:00；目录先归档，下游独立维护；计划可编辑。'),
        fresh_description=('完整刷新当前目录；不删除指数日K历史。' if i == 0 else
            '完整刷新网页当前成员；明确暂无清除旧当前名单，不提供历史成分。' if i == 1 else
            '核实所选指数全部来源历史；保留原值及缺值，按完整区间修订。')))
        for i, c in enumerate(collectors))
    return FeatureBundle('yuanhang_indices',
        plugins=tuple(OrderedContribution(40200+i, p) for i, p in enumerate((*queries, *collectors, IndexUiPlugin()))),
        tasks=tasks,
        datasets=tuple(OrderedContribution(40200+i, DatasetContribution(mapping, 'incremental', {c.job_key: c.project_id}))
            for i, (mapping, c) in enumerate(zip((catalog_dataset, member_dataset, price_dataset), collectors, strict=True))))
