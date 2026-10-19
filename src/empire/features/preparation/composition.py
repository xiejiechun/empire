"""The existing final preparation construction phase, after all providers exist."""
from empire.features.preparation.query import PreparationPlugin
from empire.features.preparation.ui import PreparationUiPlugin


def plugins_for(plugins):
    return [PreparationPlugin(
        (contribution for plugin in plugins
         for contribution in getattr(plugin, 'preparation', ())), plugins
    ), PreparationUiPlugin()]
