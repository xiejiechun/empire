"""Process kernel for the catalog's existing pure business functions only.

Mappings originate from the explicit builtin contribution registry. No
configuration, services, credentials, HTTP, SQL or Runtime is passed to children.
"""
import json
import pickle

from empire.contracts.data import BackpressureError, Envelope
from empire.features.builtin import dataset_contributions
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.infra.compute_lane import MAX_RESULT
from empire.plugins.pipeline.fingerprints import digest

_catalog = None


def execute(operation, inputs):
    global _catalog
    if _catalog is None:
        # Same explicit builtin allowlist. No service starts or connection config.
        cfg = {'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}}
        _catalog = DatasetPlugin(dataset_contributions(cfg))
    return [_execute_one(_catalog, operation, raw) for raw in inputs]


def _execute_one(catalog, operation, raw):
    event = Envelope.model_validate_json(raw)
    try:
        if operation == 'canonicalize':
            canonical = catalog.canonicalize(event)
            value = dict(publication=canonical.model_dump_json(),
                         envelope=canonical.model_copy(update={'raw_payload': {}}))
        elif operation == 'normalize':
            data = catalog.normalize(event)
            namespace, plan = catalog.fingerprint_plan(event, data)
            hashes = {key: dict(hash=digest(content), version=version)
                      for key, (content, version) in plan.items()}
            # Transfer the complete row graph as one lossless binary block.
            # Hot confirmation only needs its validated hash and header. Avoid
            # creating thousands of Python row objects again in the parent;
            # a SQL miss materializes this same result once, without revalidation.
            value = dict(envelope=event.model_copy(update={'raw_payload': {}}),
                         normalized={key: item for key, item in data.items() if key != 'rows'},
                         rows_pickle=pickle.dumps(data['rows'], protocol=5), namespace=namespace,
                         plan={key: (None, version) for key, (_, version) in plan.items()}, hashes=hashes,
                         normalized_bytes=len(json.dumps(data, default=str, ensure_ascii=False,
                                                         separators=(',', ':')).encode()))
        else:
            raise ValueError('未知计算操作')
        size = len(pickle.dumps(value, protocol=5))
        if size > MAX_RESULT:
            raise BackpressureError('计算结果超过单元 IPC 上限；消息保留')
        return value, None, size
    except (ValueError, TypeError) as exc:
        return None, exc, 0
