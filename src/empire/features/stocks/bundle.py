import empire.features.stocks.dataset as stocks
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.confirmation import ConfirmationContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.stocks.confirmation import stock_status
from empire.features.stocks.query import StockDataPlugin
from empire.features.stocks.sina_collector import SinaUniverseCollector
from empire.features.stocks.ths_collector import ThsUniverseCollector
from empire.features.stocks.ui import StockUiPlugin


def bundle(cfg):
    return FeatureBundle('stocks', plugins=(
        OrderedContribution(7300, StockDataPlugin(cfg["redis"].get("namespace", "empire"))),
        OrderedContribution(12100, SinaUniverseCollector(cfg.get("sina_universe", {}))),
        OrderedContribution(12200, ThsUniverseCollector()),
        OrderedContribution(15000, StockUiPlugin()),
    ), tasks=(
        OrderedContribution(4100, TaskContribution('ths-stocks', '同花顺 A 股股票列表',
                    'collector.ths_universe', 'ths', '沪深北完整单页目录 · 一次HTTP获取代码与名称',
                    category='基础数据', source_name='同花顺', unit_name='只股票', default_schedule=TaskDefaults('daily',
                        description='每天北京时间18:00完整核验一次当前目录；可编辑执行计划。'))),
        OrderedContribution(4200, TaskContribution("sina-stocks", "新浪 A 股股票列表",
                    "collector.sina_universe", "sina", "沪深北全量股票 · 代码 / 名称 / 统一代码 / 市场",
                    category="基础数据", source_name="新浪财经", parallel_downloads=True, unit_name='只股票')),
    ), datasets=(
        OrderedContribution(4200, DatasetContribution(stocks, "aggregate", {"sina-universe-v1": "sina-stocks", 'ths-universe-v1': 'ths-stocks'},
                                        stale_outcome="superseded", confirmation="stocks.snapshot")),
    ), confirmations=(ConfirmationContribution("stocks.snapshot", stock_status),))
