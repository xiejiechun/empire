from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.features.observation_calendar.query import ObservationQuery
from empire.features.observation_calendar.ui import ObservationUi


def bundle(cfg):
    return FeatureBundle('observation_calendar', plugins=(
        OrderedContribution(43000, ObservationQuery()), OrderedContribution(43010, ObservationUi())))
