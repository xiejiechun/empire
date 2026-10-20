"""Preserve the explicit maintenance publisher and original dataset slot."""
from empire.contracts.bundle import FeatureBundle, MaintenancePublisher, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.features.security_aliases import dataset


def bundle(cfg):
    return FeatureBundle('security_aliases', datasets=(
        OrderedContribution(2000, DatasetContribution(dataset, 'incremental', {dataset.JOB: dataset.PROJECT})),
    ), maintenance_publishers=(MaintenancePublisher(
        dataset.PROJECT, dataset.JOB, 'scripts/import_bse_code_mapping.py'),))
