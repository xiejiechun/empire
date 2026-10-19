"""Navigation page composition; stable plugin identity stays independently managed."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.features.data_browser.contribution import workspace_pages
from empire.plugins.ui.workspace import WorkspaceUiPlugin


def bundle(cfg):
    return FeatureBundle('data_browser', plugins=(
        OrderedContribution(14800, WorkspaceUiPlugin(workspace_pages)),
    ))
