"""Original business contributions at their unchanged positions."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.features.adjustment.query import AdjustmentDataPlugin
from empire.features.adjustment.ui import AdjustmentUiPlugin


def bundle(cfg):
    return FeatureBundle('adjustment', plugins=(
        OrderedContribution(11900, AdjustmentDataPlugin(cfg['redis'].get('namespace', 'empire'))),
        OrderedContribution(12000, AdjustmentUiPlugin()),
    ))
