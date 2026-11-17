"""Read-only computation and its independently registered desktop page."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.features.market_review.query import ReviewQuery
from empire.features.market_review.ui import ReviewUi


def bundle(cfg):
    return FeatureBundle('market_review', plugins=(
        OrderedContribution(42000, ReviewQuery(cfg['redis'].get('namespace', 'empire'))),
        OrderedContribution(42010, ReviewUi())))
