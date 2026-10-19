from dataclasses import replace

from empire.contracts.bundle import OrderedContribution, ordered
from empire.core.manager import PluginManager
from empire.core.redaction import Redactor
from empire.features.builtin import builtin_bundles, ordered_contributions, validate_ownership
from empire.plugins.collection.control import CollectionControl
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.data.preparation import PreparationPlugin
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.infra.archive_confirmation import ArchiveConfirmationPlugin
from empire.plugins.infra.download_settings import DownloadSettingsPlugin
from empire.plugins.infra.http import HttpPlugin
from empire.plugins.infra.mysql_store import MySQLPlugin
from empire.plugins.infra.proxy_pool import ProxyPoolPlugin
from empire.plugins.infra.redis_store import RedisPlugin
from empire.plugins.pipeline.archive import ArchivePlugin
from empire.plugins.pipeline.ingest import IngestPlugin
from empire.plugins.ui.collection import CollectionUiPlugin
from empire.plugins.ui.downloads import DownloadSettingsUiPlugin
from empire.plugins.ui.help import HelpUiPlugin
from empire.plugins.ui.preparation import PreparationUiPlugin
from empire.plugins.ui.proxies import ProxyUiPlugin
from empire.plugins.ui.system import SystemUiPlugin
from empire.plugins.ui.workspace import WorkspaceUiPlugin


def build_manager(cfg: dict) -> PluginManager:
    # Explicit internal declarations only: no discovery, service starts or page creation.
    bundles = builtin_bundles(cfg)
    rate_groups = dict(cfg["rate_groups"])
    rate_groups.setdefault("ths", {"domains": ["10jqka.com.cn"], "min_interval_ms": 2000})
    rate_groups.setdefault('kaipanla', {'domains': ['longhuvip.com'], 'min_interval_ms': 2000})
    rate_groups.setdefault('eastmoney', {'domains': ['eastmoney.com'], 'min_interval_ms': 2000,
        'proxy_interval_ms': 2000, 'total_interval_ms': 2000, 'max_concurrency': 1, 'scaling_mode': 'fixed'})
    rate_groups.setdefault('bse', {'domains': ['bse.cn'], 'min_interval_ms': 2000})
    for group, domains in {"sse": ["sse.com.cn"], "szse": ["szse.cn"], "tax": ["chinatax.gov.cn"], "government": ["gov.cn"], "chinaclear": ["chinaclear.cn"], "chinagate": ["chinagate.cn"]}.items():
        rate_groups.setdefault(group, {"domains": domains, "min_interval_ms": 2000})
    platform = (
        OrderedContribution(6300, DatasetPlugin(ordered_contributions(bundles, 'datasets'))),
        OrderedContribution(6400, RedisPlugin(cfg["redis"])),
        OrderedContribution(6500, MySQLPlugin(cfg["mysql"])),
        OrderedContribution(6600, RecordsPlugin(secrets=tuple(
                    cfg.get(section, {}).get("password", "") for section in ("redis", "mysql")
                ))),
        OrderedContribution(6700, ProxyPoolPlugin()),
        OrderedContribution(6800, DownloadSettingsPlugin()),
        OrderedContribution(6900, HttpPlugin(rate_groups, cfg.get("http", {}))),
        OrderedContribution(7000, ArchivePlugin(cfg["archive"])),
        OrderedContribution(7100, IngestPlugin(cfg["ingest"])),
        OrderedContribution(7200, ArchiveConfirmationPlugin()),
        OrderedContribution(14700, CollectionControl(ordered_contributions(bundles, 'tasks'))),
        OrderedContribution(14800, WorkspaceUiPlugin()),
        OrderedContribution(14900, CollectionUiPlugin()),
        OrderedContribution(15400, SystemUiPlugin()),
        OrderedContribution(15500, HelpUiPlugin()),
        OrderedContribution(15600, ProxyUiPlugin()),
        OrderedContribution(15700, DownloadSettingsUiPlugin()),
    )
    positioned_plugins = [('platform', contribution) for contribution in platform]
    positioned_plugins.extend((bundle.id, contribution) for bundle in bundles for contribution in bundle.plugins)
    plugins = list(ordered(positioned_plugins, 'plugins'))
    plugins.extend([PreparationPlugin(
        (contribution for plugin in plugins
         for contribution in getattr(plugin, 'preparation', ())), plugins
    ), PreparationUiPlugin()])
    for plugin in plugins:
        plugin.manifest = replace(plugin.manifest, autostart=True)
    manager = PluginManager(plugins, redactor=Redactor.from_config(cfg))
    validate_ownership(bundles, manager)
    return manager
