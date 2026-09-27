import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.data import make_envelope
from empire.contracts.dataset import DatasetContribution
from empire.plugins.collectors.sina_news import SinaNewsCollector
from empire.plugins.collectors.sina_universe import SinaUniverseCollector
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.pipeline.archive import ArchivePlugin
from empire.plugins.pipeline.archive_queue import ArchiveQueue


class MetricMapping:
    DATASETS = {"metric.sample.page"}
    FINGERPRINT_NAMESPACE = "metric-sample"
    FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)

    @staticmethod
    def normalize(envelope):
        value = envelope.raw_payload
        if set(value) != {"page", "value"} or type(value["page"]) is not int:
            raise ValueError("invalid metric sample")
        return {**value, "row_count": 1}


def metric_catalog():
    return DatasetPlugin([DatasetContribution(
        MetricMapping, "incremental", {"metric-sample-v1": "metric-sample"})])


def metric_event():
    return make_envelope(
        source="test-source", dataset="metric.sample.page", business_key="sample:1",
        job_key="metric-sample-v1", run_id="run", batch_id="batch",
        payload={"page": 1, "value": 42},
    )


async def test_fourth_dataset_contribution_uses_generic_archive_and_project_identity():
    catalog = metric_catalog()
    envelope = metric_event()
    assert catalog.normalize(envelope) == {"page": 1, "value": 42, "row_count": 1}
    assert catalog.incremental(envelope)
    assert catalog.project_id(envelope) == "metric-sample"
    assert catalog.fingerprint_version("metric-sample") is MetricMapping.FINGERPRINT_VERSION

    queue = ArchiveQueue(10)
    queue.add("1-0", envelope, catalog.incremental(envelope), catalog.project_id(envelope))
    assert queue.take().project == "metric-sample"

    worker = ArchivePlugin({})
    worker.catalog = catalog
    worker.stop_event = asyncio.Event()
    worker.redis = SimpleNamespace(stream="test:archive", client=SimpleNamespace(xrange=AsyncMock(return_value=[
        ("1-0", {"envelope": envelope.model_dump_json()})
    ])))
    worker._archive_data = AsyncMock(return_value={"row_count": 1})
    worker._history = AsyncMock()
    worker._incremental_result = AsyncMock()
    worker.acknowledge = AsyncMock()
    record = {"id": "1-0", "envelope": envelope.model_copy(update={"raw_payload": {}}),
              "normalized": {"page": 1, "value": 42, "row_count": 1}}
    await worker._flush_incremental([record], "metric-sample")
    worker._archive_data.assert_awaited_once()
    worker.acknowledge.assert_awaited_once_with(["1-0"])


def test_collectors_depend_only_on_their_own_business_schema():
    assert "stocks.schema" in SinaUniverseCollector.manifest.requires
    assert "news.schema" not in SinaUniverseCollector.manifest.requires
    assert "news.schema" in SinaNewsCollector.manifest.requires
    assert "stocks.schema" not in SinaNewsCollector.manifest.requires
