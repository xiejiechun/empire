import pytest

from scripts.measure_capacity import ScenarioModel, build_report, latency, measure_http


def test_latency_summary_is_ordered_and_empty_safe():
    assert latency([]) == {"p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0}
    summary = latency([.004, .001, .003, .002])
    assert 0 < summary["p50_ms"] <= summary["p95_ms"] <= summary["max_ms"]


async def test_shared_exit_measurement_uses_production_egress_identity():
    result = await measure_http(ScenarioModel(
        "shared-test", devices=12, exits=3, requests=12, response_delay=.002))
    assert result["peak_concurrency"] <= 3
    assert result["candidate_checks"] >= result["attempts"]
    assert all(value == 0 for value in result["cleanup"].values())
    for stage in result["latency"].values():
        assert stage["p50_ms"] <= stage["p95_ms"] <= stage["max_ms"]


@pytest.mark.slow
async def test_quick_release_capacity_report_covers_full_matrix_and_1000_churns():
    report = await build_report(quick=True)
    assert report["schema_version"] == 1 and report["passed"]
    assert [item["distinct_exit_ips"] for item in report["baseline"]] == [10, 30, 50, 100]
    assert {item["name"] for item in report["fault_matrix"]} == {
        "transport-failure", "site-429", "request-cancel"}
    assert report["churn"]["iterations"] == 1000
    assert report["churn"]["cancelled_acquires"] == 1000
    assert all(report["checks"].values())
