from empire.plugins.pipeline.archive_metrics import ArchiveMetrics, StageWindow


def test_fixed_histogram_windows_expire_and_storage_is_bounded():
    window = StageWindow()
    for tick in range(10000):
        for _ in range(5):
            window.add(.003, tick)
        assert len(window.buckets) <= 300
    recent = window.snapshot(9999, 10)
    assert recent['count'] == 50 and recent['p99_upper_ms'] == 3
    assert window.snapshot(9999, 300)['count'] == 1500
    assert window.snapshot(10300, 300)['count'] == 0
    assert not window.buckets


def test_unknown_project_or_phase_cannot_grow_metrics_and_reset_clears_timing():
    metrics = ArchiveMetrics()
    metrics.reset({'news'})
    for i in range(1000):
        with metrics.span(str(i), 'hash'):
            pass
        with metrics.span('news', str(i)):
            pass
    assert not metrics.timings
    with metrics.span('news', 'hash'):
        pass
    assert metrics.snapshot('news')['timings']['hash']['10s']['count'] == 1
    metrics.reset({'news'})
    assert not metrics.snapshot('news')['timings']
