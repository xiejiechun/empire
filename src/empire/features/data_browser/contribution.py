"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.ui import PageContribution


def catalog_page():
    return PageContribution('catalog', '数据目录', '数据浏览', -1, '按业务分类与来源查找数据', cache_policy='lru')

def workspace_pages():
    return (PageContribution('home', '总览', '工作台', 0, '数据更新与常用操作 · Alt+1', top_level=True, cache_policy='lru'), catalog_page())
