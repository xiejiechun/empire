from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from contextlib import asynccontextmanager

from empire.contracts.business_schema import DATASET_TABLE_GROUPS, require_dataset_source
from empire.contracts.data import (
    BackpressureError,
    Envelope,
    UnsupportedSchema,
    make_envelope,
    read_envelope_metadata,
)
from empire.contracts.dataset import DatasetContribution
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.plugins.datasets.source_compute import compute_source
from empire.plugins.infra.compute_lane import MAX_INPUT, MAX_RESULT, ComputeLane
from empire.plugins.infra.sql_lane import settle


class DatasetPlugin:
    manifest = PluginManifest(
        "dataset.astock", "数据契约", requires=("http.fetch",), provides=("dataset.catalog",),
        description="内部股票、财经新闻、交易日历和停复牌数据契约、校验及业务表写入",
    )

    def __init__(self, contributions: Iterable[DatasetContribution], *, compute_operation=None):
        self.contributions = tuple(contributions)
        datasets = {}
        namespaces = {}
        for contribution in self.contributions:
            for dataset in contribution.datasets:
                if dataset in datasets:
                    raise ValueError(f"重复数据契约 {dataset}")
                datasets[dataset] = contribution
            if contribution.namespace in namespaces:
                raise ValueError(f"重复摘要命名空间 {contribution.namespace}")
            namespaces[contribution.namespace] = contribution
        self.datasets, self.namespaces = datasets, namespaces
        self.compute_lane = None
        self.compute_budget = None
        self.compute_operation = compute_operation

    async def start(self, context: PluginContext) -> dict:
        self.compute_budget = context.get('http.fetch').buffer_budget
        self.compute_lane = ComputeLane(4)
        return {"dataset.catalog": self}

    async def stop(self) -> None:
        if self.compute_lane:
            await self.compute_lane.close()
            self.compute_lane = None
        self.compute_budget = None

    async def compute_source(self, operation, body, stock, today, *, reservation=None):
        return await compute_source(self, operation, body, stock, today, reservation=reservation)

    def archive_envelope(self, raw):
        """Avoid rebuilding a large body before its formal process validation.

        Unknown schemas keep the complete Envelope reader and isolation rules.
        Body-dependent completion predicates and direct units also retain it.
        """
        if not (self.compute_lane and self.compute_operation and 8192 <= len(raw.encode()) <= MAX_INPUT):
            return Envelope.model_validate_json(raw)
        header = read_envelope_metadata(raw)
        contribution = self.datasets.get(header.dataset)
        if (contribution and contribution.schema_version == header.schema_version
                and contribution.process_safe
                and not getattr(contribution.mapping, 'is_complete', None)):
            return header
        return Envelope.model_validate_json(raw)

    @asynccontextmanager
    async def computed(self, events, operation, *, serialized=None):
        """Hold input/IPC/result capacity through the caller's publication or ACK.

        No wait for more bytes while owning bodies: capacity failure preserves
        the caller's checkpoint/Stream. Small and custom units use the same pure
        functions directly. Large built-in independent units run in processes.
        """
        if len(events) > 16:
            raise ValueError('计算批次最多 16 个完整单元')
        if serialized is not None and (operation != 'normalize' or len(serialized) != len(events)):
            raise ValueError('归档原文必须与规范化单元一一对应')
        raw = {}
        if self.compute_lane and self.compute_operation:
            for index, event in enumerate(events):
                contribution = self.mapping(event)
                if contribution.process_safe:
                    # Archive already owns the exact validated Stream wire.
                    # Reuse it instead of serializing the full matrix again.
                    value = serialized[index] if serialized is not None else event.model_dump_json()
                    if 8192 <= len(value.encode()) <= MAX_INPUT:
                        raw[index] = value
        leases = []
        results = [None] * len(events)
        try:
            async def compute(indices):
                return await self.compute_lane.call(self.compute_operation, operation,
                                                    [raw[index] for index in indices])

            remaining = list(raw)
            while remaining:
                selected, required = [], 0
                available = self.compute_budget.limit - self.compute_budget.used
                for index in remaining[:self.compute_lane.workers * 4]:
                    cost = 2 * len(raw[index].encode()) + 2 * MAX_RESULT
                    if required + cost > available:
                        break
                    selected.append(index)
                    required += cost
                if not selected:
                    raise BackpressureError('共享缓冲不足以保留计算输入及结果；消息与断点保留')
                lease = self.compute_budget.try_reserve(required)
                if lease is None:
                    raise BackpressureError('共享缓冲不足以保留计算输入及结果；消息与断点保留')
                leases.append(lease)
                # Repeated cancellation retains all children and their IPC bytes.
                width = min(4, max(1, (len(selected) + self.compute_lane.workers - 1)
                                     // self.compute_lane.workers))
                chunks = [selected[offset:offset + width] for offset in range(0, len(selected), width)]
                groups = await settle(asyncio.gather(*(compute(chunk) for chunk in chunks),
                                                     return_exceptions=True))
                completed = []
                for group in groups:
                    if isinstance(group, BaseException):
                        raise group
                    completed.extend(group)
                for value in completed:
                    if isinstance(value, BaseException):
                        raise value
                lease.shrink_to(sum(2 * len(raw[index].encode()) + 2 * value[2]
                                    for index, value in zip(selected, completed)))
                for index, (value, error, _) in zip(selected, completed):
                    if error is None and operation == 'normalize':
                        expected = events[index].model_copy(update={'raw_payload': {}})
                        if value['envelope'] != expected:
                            raise ValueError('计算返回的消息身份与归档输入不一致；消息保留')
                    results[index] = value, error
                del remaining[:len(selected)]
            for index, event in enumerate(events):
                if index not in raw:
                    try:
                        value = self.canonicalize(event) if operation == 'canonicalize' else self.normalize(event)
                        results[index] = value, None
                    except (ValueError, TypeError) as exc:
                        results[index] = None, exc
            yield results
        finally:
            for lease in leases:
                lease.release()

    def health(self) -> dict:
        return {"schemas": [f"{dataset}@{self.datasets[dataset].schema_version}"
                            for dataset in sorted(self.datasets)],
                "compute": self.compute_lane.health() if self.compute_lane else None}

    def mapping(self, envelope):
        contribution = self.datasets.get(envelope.dataset)
        if contribution and envelope.schema_version == contribution.schema_version:
            return contribution
        raise UnsupportedSchema(f"缺少数据映射 {envelope.dataset}@{envelope.schema_version}，消息保留在 Redis")

    def incremental(self, envelope):
        return self.mapping(envelope).mode == "incremental"

    def schema_owner(self, envelope):
        """Only an exact dataset and explicitly registered job establish ownership."""
        contribution = self.datasets.get(envelope.dataset)
        return contribution.projects.get(envelope.job_key) if contribution else None

    def project_id(self, envelope):
        return self.mapping(envelope).project_id(envelope)

    def namespace(self, envelope):
        return self.mapping(envelope).namespace

    def archive_domains(self, envelope):
        """Conservative whole-table ownership from the formal schema registry.

        Include every dataset of the contribution, its shared cache namespace
        and its single project state. Unknown write ownership stays exclusive.
        Aggregate replacements also run alone to bound their complete-set memory.
        """
        contribution = self.mapping(envelope)
        if contribution.mode == 'aggregate' or not contribution.archive_tables or any(
                dataset not in DATASET_TABLE_GROUPS for dataset in contribution.datasets):
            return frozenset({'*'})
        registered = {table for dataset in contribution.datasets for table in DATASET_TABLE_GROUPS[dataset]}
        if set(contribution.archive_tables) != registered:
            return frozenset({'*'})
        return frozenset({('project', self.project_id(envelope)),
            ('fingerprint', contribution.namespace, self.fingerprint_source(envelope)),
            *(('table', table) for table in contribution.archive_tables)})

    def stale_outcome(self, envelope):
        return self.mapping(envelope).stale_outcome

    def is_complete(self, envelope):
        return self.mapping(envelope).is_complete(envelope)

    def aggregate_result_keys(self, envelope, prefix):
        contribution = self.mapping(envelope)
        return contribution.mapping.aggregate_result_keys(prefix, envelope.source)

    def aggregate_current(self, connection, envelope, namespace):
        reader = getattr(self.mapping(envelope).mapping, 'current_directory', None)
        return reader(connection, namespace) if reader else None

    def normalize(self, envelope: Envelope) -> dict:
        require_dataset_source(envelope.dataset, envelope.source)
        mapping = self.mapping(envelope)
        payload = envelope.raw_payload
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()).hexdigest()
        if digest != envelope.content_hash:
            raise ValueError("Payload hash mismatch")
        identity = json.dumps([
            envelope.source, envelope.dataset, envelope.schema_version,
            envelope.business_key, envelope.content_hash,
        ], separators=(",", ":"))
        if hashlib.sha256(identity.encode()).hexdigest() != envelope.event_id:
            raise ValueError("Event identity mismatch")
        return mapping.mapping.normalize(envelope)

    def canonicalize(self, envelope: Envelope) -> Envelope:
        normalized = self.normalize(envelope)
        payload = self.mapping(envelope).mapping.canonical_payload(envelope, normalized)
        event = make_envelope(source=envelope.source, dataset=envelope.dataset,
                              business_key=envelope.business_key, job_key=envelope.job_key,
                              run_id=envelope.run_id, batch_id=envelope.batch_id, payload=payload,
                              schema_version=envelope.schema_version)
        return event.model_copy(update={"observed_at": envelope.observed_at,
                                        "source_url": envelope.source_url,
                                        "available_at": envelope.available_at})

    def assemble(self, records: list[dict], *, include_rows: bool = True) -> dict | None:
        contribution = self.mapping(records[0]["envelope"])
        if contribution.mode != "aggregate":
            raise UnsupportedSchema("增量数据不能按整批聚合")
        return contribution.mapping.assemble(records, include_rows=include_rows)

    def write(self, connection, envelope: Envelope, normalized: dict) -> dict:
        require_dataset_source(envelope.dataset, envelope.source)
        return self.mapping(envelope).mapping.write(connection, envelope, normalized)

    def fingerprint_plan(self, envelope, data):
        # Every dataset must explicitly declare identity, content and version rules.
        return self.mapping(envelope).mapping.fingerprint_plan(envelope, data)

    def fingerprint_source(self, envelope):
        mapping = self.mapping(envelope).mapping
        bucket = getattr(mapping, 'fingerprint_source', None)
        return bucket(envelope) if bucket else getattr(mapping, 'FINGERPRINT_SOURCE', envelope.source)

    def fingerprint_version(self, namespace):
        contribution = self.namespaces.get(namespace)
        if contribution:
            return contribution.version
        raise UnsupportedSchema("数据集未声明归档版本契约")

    def fingerprint_subset(self, envelope, data, identities):
        return self.mapping(envelope).mapping.fingerprint_subset(data, identities)

    def archive_state(self, envelope, data, outcome, previous):
        return self.mapping(envelope).mapping.archive_state(envelope, data, outcome, previous)

    def state_unit(self, envelope, data):
        declaration = getattr(self.mapping(envelope).mapping, 'state_unit', None)
        return declaration(data) if declaration else None
