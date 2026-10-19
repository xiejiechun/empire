"""Existing news declarations, with stable identities and individual positions."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution
from empire.features.news import dataset
from empire.features.news.collector import SinaNewsCollector
from empire.features.news.contract import JOB, PROJECT
from empire.features.news.query import NewsDataPlugin
from empire.features.news.ui import NewsUiPlugin


def bundle(cfg):
    return FeatureBundle('news', plugins=(
        OrderedContribution(12300, NewsDataPlugin(namespace=cfg["redis"].get("namespace", "empire"))),
        OrderedContribution(12400, SinaNewsCollector(cfg.get("sina_news", {}))),
        OrderedContribution(15100, NewsUiPlugin()),
    ), tasks=(
        OrderedContribution(4300, TaskContribution(PROJECT, "新浪 7×24 小时全球实时财经新闻直播",
                    "collector.sina_news", "sina", "最新窗口刷新与增量补采 · 正文 / 时间 / 分类 / 重点新闻",
                    interval_seconds=60, category="资讯", source_name="新浪财经", unit_name='条新闻',
                    fresh_description="重新扫描最新窗口并建立增量基线，已有新闻保留；请先检查尚未处理的缺口。")),
    ), datasets=(
        OrderedContribution(4300, DatasetContribution(dataset, "incremental", {JOB: PROJECT})),
    ))
