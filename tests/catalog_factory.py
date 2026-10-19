"""Existing builtin declarations for isolated tests; no service is started."""
from empire.features.builtin import dataset_contributions
from empire.plugins.datasets.astock import DatasetPlugin


def builtin_catalog():
    cfg = {'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}}
    return DatasetPlugin(dataset_contributions(cfg))
