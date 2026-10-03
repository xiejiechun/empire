from __future__ import annotations

import hashlib
import json

from empire.contracts.business_schema import require_dataset_source
from empire.contracts.data import Envelope, UnsupportedSchema, make_envelope
from empire.contracts.dataset import DatasetContribution
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.plugins.datasets import industries, intraday, news, stocks, suspensions, trade_calendar
from empire.plugins.datasets.capital_actions import KINDS, SCHEMA_VERSIONS
from empire.plugins.datasets.capital_archive import CapitalDataset
from empire.plugins.datasets.financial_archive import FinancialDataset
from empire.plugins.datasets.financial_statements import KINDS as FINANCIAL_KINDS
from empire.plugins.datasets.financial_wire import SCHEMA_VERSION as FINANCIAL_SCHEMA_VERSION


class DatasetPlugin:
    manifest = PluginManifest(
        "dataset.astock", "数据契约", provides=("dataset.catalog",),
        description="内部股票、财经新闻、交易日历和停复牌数据契约、校验及业务表写入",
    )

    def __init__(self, contributions=None):
        self.contributions = tuple(contributions or (
            DatasetContribution(intraday, 'incremental', {intraday.JOB: intraday.PROJECT}),
            DatasetContribution(industries, 'incremental', {industries.JOB: industries.PROJECT}),
            *(DatasetContribution(FinancialDataset(kind), 'incremental',
                                  {'ths-' + kind + '-v1': 'ths-' + kind},
                                  schema_version=FINANCIAL_SCHEMA_VERSION) for kind in FINANCIAL_KINDS),
            *(DatasetContribution(CapitalDataset(kind), "incremental", {item[2] + "-v1": item[2]},
                                  schema_version=SCHEMA_VERSIONS[kind])
              for kind, item in KINDS.items()),
            DatasetContribution(stocks, "aggregate", {"sina-universe-v1": "sina-stocks"},
                                stale_outcome="superseded"),
            DatasetContribution(news, "incremental", {"sina-news-v1": "sina-news"}),
            DatasetContribution(trade_calendar, "incremental",
                                {"cninfo-calendar-v1": "cninfo-calendar"}),
            DatasetContribution(suspensions, "incremental",
                                {"tdx-suspensions-v1": "tdx-suspensions"}, schema_version=3),
        ))
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

    async def start(self, context: PluginContext) -> dict:
        return {"dataset.catalog": self}

    async def stop(self) -> None:
        pass

    def health(self) -> dict:
        return {"schemas": [f"{dataset}@{self.datasets[dataset].schema_version}"
                            for dataset in sorted(self.datasets)]}

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

    def stale_outcome(self, envelope):
        return self.mapping(envelope).stale_outcome

    def is_complete(self, envelope):
        return self.mapping(envelope).is_complete(envelope)

    def aggregate_result_keys(self, envelope, prefix):
        contribution = self.mapping(envelope)
        return contribution.mapping.aggregate_result_keys(prefix, envelope.source)

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
