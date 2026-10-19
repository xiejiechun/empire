"""Frozen local architecture benchmarks; never use production configuration or sources."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
import tomllib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.architecture_benchmark_data import digest, private_database
from scripts.release_lock import ReleaseLock

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'docs/evidence/architecture-performance-protocol-2026-10-19.json'
HARNESS = ('scripts/architecture_benchmark.py', 'scripts/architecture_benchmark_data.py',
           'scripts/release_lock.py')
FONT_FILES = tuple(Path('C:/Windows/Fonts') / name for name in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf'))


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity(root):
    files = [p for folder in ('src', 'sql') for p in (root / folder).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.pyo'}]
    files.append(root / 'config/app.example.toml')
    return digest({p.relative_to(root).as_posix(): file_hash(p) for p in sorted(files)})


def percentile(values, proportion):
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(values):
    if not values or any(type(value) not in (int, float) or not math.isfinite(value)
                         or value < 0 for value in values):
        raise ValueError('Invalid benchmark samples')
    return dict(samples_ms=values, median_ms=statistics.median(values),
                p95_ms=percentile(values, .95), min_ms=min(values), max_ms=max(values))


def sample(action, schedule):
    signatures, values = [], []
    for index in range(schedule['warmup'] + schedule['repetitions']):
        started = time.perf_counter_ns()
        result = action()
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        signatures.append(digest(result))
        if index >= schedule['warmup']:
            values.append(elapsed)
    if len(set(signatures)) != 1:
        raise RuntimeError('Benchmark output changed across fixed-input repetitions')
    return summarize(values), signatures[0]


@contextmanager
def restricted_network(port=None):
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def connect(sock, address):
        if port is None or not isinstance(address, tuple) or address[:2] != ('127.0.0.1', port):
            raise RuntimeError('Benchmark attempted a connection outside its isolated MySQL')
        return original(sock, address)

    def connect_ex(sock, address):
        if port is None or not isinstance(address, tuple) or address[:2] != ('127.0.0.1', port):
            raise RuntimeError('Benchmark attempted a connection outside its isolated MySQL')
        return original_ex(sock, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    try:
        yield
    finally:
        socket.socket.connect = original
        socket.socket.connect_ex = original_ex


def configuration(root):
    return tomllib.loads((root / 'config/app.example.toml').read_text('utf-8'))


def manager_signature(manager):
    if any(entry.context is not None or str(entry.state) != 'STOPPED'
           for entry in manager.entries.values()):
        raise RuntimeError('Benchmark manager unexpectedly started a plugin')
    return dict(plugins=sorted(manager.entries), providers=dict(sorted(manager.providers.items())))


def machine_environment(root):
    return dict(machine=dict(host_sha256=hashlib.sha256(platform.node().encode()).hexdigest(),
                             os=platform.platform(), machine=platform.machine(),
                             processor=os.environ.get('PROCESSOR_IDENTIFIER', platform.processor()),
                             logical_cpus=os.cpu_count(), python=platform.python_version(),
                             fonts={p.name: file_hash(p) for p in FONT_FILES}),
                dependencies={d.metadata['Name']: d.version for d in importlib.metadata.distributions()
                              if d.metadata.get('Name')},
                requirements_sha256=file_hash(root / 'requirements.lock'))


def measure_queries(manager, engine, rows, protocol, runner):
    from empire.plugins.infra.sql_lane import SQLLane

    async def execute():
        lane = SQLLane('architecture-benchmark-read', protocol['mysql']['query_lane_workers'],
                       protocol['mysql']['query_lane_waiting'])
        mysql = SimpleNamespace(read=lane.call, read_engine=engine)
        news = manager.entries[manager.providers['news.query']].plugin
        news.mysql = mysql
        holders = [manager.entries[manager.providers[kind + '.query']].plugin
                   for kind in protocol['fixture']['holder_kinds']]
        for query in holders:
            query.mysql = mysql
        try:
            first = await news.list_news(limit=protocol['fixture']['news_page_size'])
            expected = list(range(protocol['fixture']['news_rows'],
                                  protocol['fixture']['news_rows'] - 50, -1))
            if [r['news_id'] for r in first['rows']] != expected:
                raise RuntimeError('Formal news result differs from fixture business keys')
            selected = [next((key, row) for key, row in rows['reports'] if row['kind'] == query.kind)
                        for query in holders]

            async def browse():
                return [await query.browse(limit=protocol['fixture']['holder_page_size'])
                        for query in holders]

            async def details():
                return [await query.detail(key) for query, (key, _) in zip(holders, selected, strict=True)]

            actions = dict(news_first=lambda: news.list_news(limit=50),
                           news_next=lambda: news.list_news(limit=50, before=first['next_cursor'],
                               anchor=first['anchor'], include_total=False),
                           news_search=lambda: news.list_news('产业', limit=50, important=True),
                           holders_browse=browse, holders_detail=details)
            metrics, correctness, results = {}, {}, {}
            for name, action in actions.items():
                signatures, values = [], []
                for index in range(protocol['warm']['warmup'] + protocol['warm']['repetitions']):
                    started = time.perf_counter_ns()
                    result = await action()
                    elapsed = (time.perf_counter_ns() - started) / 1_000_000
                    results[name] = result
                    signatures.append(digest(result))
                    if index >= protocol['warm']['warmup']:
                        values.append(elapsed)
                if len(set(signatures)) != 1:
                    raise RuntimeError('Formal query result changed during benchmark: ' + name)
                metrics[name], correctness[name] = summarize(values), signatures[0]
            if results['holders_detail'] != [row for _, row in selected]:
                raise RuntimeError('Formal holder details differ from all synthetic fields/members')
            if (results['news_first']['total'] != len(rows['news'])
                    or len(results['news_next']['rows']) != 50
                    or results['news_search']['total'] != sum(r['news_id'] % 30 == 0 for r in rows['news'])
                    or any(len(result['rows']) != 20 for result in results['holders_browse'])):
                raise RuntimeError('Formal query scope/count differs from frozen workload')
            return metrics, correctness, results
        finally:
            await lane.close()

    return runner.run(execute())


def measure_ui(manager, results, protocol, output):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFontDatabase, QFontMetrics, QImage
    from PySide6.QtWidgets import QApplication, QWidget

    from empire.desktop.theme import desktop_style

    app = QApplication.instance() or QApplication([])
    for path in FONT_FILES:
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            raise RuntimeError('The production desktop font could not be loaded: ' + path.name)
    app.setStyleSheet(desktop_style())
    pages = {page.id: page for entry in manager.entries.values()
             if hasattr(entry.plugin, 'create_pages') for page in entry.plugin.create_pages()}

    def no_background(*args):
        raise RuntimeError('UI benchmark attempted an asynchronous service request')

    shell = SimpleNamespace(cfg={}, shutting_down=False,
                            runtime=SimpleNamespace(invoke=no_background, config={}))
    seen = set()

    def render(ident, payload):
        page = pages[ident].factory(shell)
        page.timer.stop()
        try:
            page.resize(protocol['ui']['width'], protocol['ui']['height'])
            page.show()
            page.timer.stop()
            if not all(QFontMetrics(page.font()).inFontUcs4(ord(char)) for char in '财经123'):
                raise RuntimeError('UI benchmark font cannot render Chinese and numeric text')
            page.render(payload)
            app.processEvents()
            image = QImage(page.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            QWidget.render(page, image)
            content = (page.detail.toPlainText() + page.feed.toPlainText() if ident == 'news'
                       else page.reader.toPlainText())
            if not content or image.isNull():
                raise RuntimeError('Formal page failed to render its fixed result')
            if ident not in seen:
                # First images are produced during the uncounted warmup.
                image.save(str(output.parent / (ident + '-benchmark.png')))
                seen.add(ident)
            return dict(page=ident, text_sha256=digest(content), width=image.width(), height=image.height())
        finally:
            page.close()
            page.deleteLater()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()

    operations = dict(news_ui=lambda: render('news', results['news_first']),
                      holders_ui=lambda: [render(kind, row) for kind, row in zip(
                          protocol['fixture']['holder_kinds'], results['holders_detail'], strict=True)])
    metrics, correctness = {}, {}
    for name, action in operations.items():
        metrics[name], correctness[name] = sample(action, protocol['warm'])
    return metrics, correctness


def validate_report(report, protocol, protocol_hash=None):
    required = ('protocol_sha256', 'harness_sha256', 'source_sha256', 'machine', 'dependencies',
                'requirements_sha256', 'fixture_sha256', 'ddl_sha256', 'mysql', 'correctness',
                'measured_at_utc', 'limits')
    errors = [key for key in required if not report.get(key)]
    if report.get('schema') != 1 or report.get('passed') is not True or report.get('cleanup') is not True:
        errors.append('invalid measurement')
    if protocol_hash is not None and report.get('protocol_sha256') != protocol_hash:
        errors.append('protocol identity')
    metrics = report.get('metrics', {})
    if not isinstance(metrics, dict) or set(metrics) != set(protocol['metrics']):
        errors.append('metric set')
        metrics = metrics if isinstance(metrics, dict) else {}
    if not isinstance(report.get('correctness'), dict) or set(report['correctness']) != set(protocol['metrics']):
        errors.append('correctness set')
    for name in protocol['metrics']:
        metric = metrics.get(name, {})
        schedule = protocol['cold_process'] if name == 'cold_declarations' else protocol['warm']
        values = metric.get('samples_ms') if isinstance(metric, dict) else None
        if not isinstance(values, list) or len(values) != schedule['repetitions']:
            errors.append(name + '.samples')
            continue
        try:
            summary = summarize(values)
        except (TypeError, ValueError):
            errors.append(name + '.samples')
            continue
        if any(type(metric.get(stat)) not in (int, float) or metric[stat] != value
               for stat, value in summary.items() if stat != 'samples_ms'):
            errors.append(name + '.statistics')
    return errors


def compare(baseline, current, protocol, protocol_hash=None):
    bindings = ('protocol_sha256', 'harness_sha256', 'machine', 'dependencies',
                'requirements_sha256', 'fixture_sha256', 'ddl_sha256', 'mysql', 'correctness')
    differences = [key for key in bindings if key not in baseline or key not in current
                   or baseline[key] != current[key]]
    differences.extend('baseline.' + error for error in validate_report(baseline, protocol, protocol_hash))
    differences.extend('current.' + error for error in validate_report(current, protocol, protocol_hash))
    checks = {}
    if differences:
        return dict(passed=False, incomparable=differences, checks=checks)
    for name in protocol['metrics']:
        category = ('cold' if name == 'cold_declarations' else 'assembly' if name == 'assembly'
                    else 'ui' if name.endswith('_ui') else 'query')
        for stat in protocol['statistics']:
            before = baseline.get('metrics', {}).get(name, {}).get(stat)
            after = current.get('metrics', {}).get(name, {}).get(stat)
            if (type(before) not in (int, float) or type(after) not in (int, float)
                    or not math.isfinite(before) or not math.isfinite(after) or before < 0 or after < 0):
                differences.append(name + '.' + stat)
                continue
            limit = max(before * protocol['acceptance']['relative_multiplier'],
                        before + protocol['acceptance']['absolute_noise_ms'][category])
            checks[name + '.' + stat] = dict(baseline_ms=before, current_ms=after,
                                           limit_ms=limit, passed=after <= limit)
    return dict(passed=not differences and all(v['passed'] for v in checks.values()),
                incomparable=differences, checks=checks)


def measure(root, protocol_path, settings_path, output):
    protocol_bytes = protocol_path.read_bytes()
    protocol = json.loads(protocol_bytes)
    protocol_hash = hashlib.sha256(protocol_bytes).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    settings = json.loads(settings_path.read_text('utf-8'))
    # Windows initializes its event-loop wakeup socketpair before the connection guard.
    # All benchmark work and formal query execution remain under the guard.
    with ReleaseLock(root) as lock, asyncio.Runner() as runner, restricted_network(protocol['mysql']['port']):
        if os.name != 'nt':
            raise RuntimeError('This frozen machine protocol requires Windows')
        stopped = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            "if (Get-Process Empire -ErrorAction SilentlyContinue | Where-Object { $_.Threads.Count -gt 0 }) { exit 3 }"],
            cwd=root, **lock.child_options())
        if stopped.returncode:
            raise RuntimeError('Close Empire normally before measuring; background collection would bias the baseline')
        before = source_identity(root)
        harness = {name: file_hash(root / name) for name in HARNESS}
        environment = machine_environment(root)
        os.environ['QT_QPA_PLATFORM'] = protocol['ui']['platform']
        os.environ['QT_SCALE_FACTOR'] = protocol['ui']['scale_factor']
        from empire.bootstrap import build_manager
        cfg = configuration(root)
        metrics, correctness = {}, {}
        metrics['assembly'], correctness['assembly'] = sample(
            lambda: manager_signature(build_manager(cfg)), protocol['warm'])
        manager = build_manager(cfg)
        with private_database(root, settings, protocol) as (engine, rows, state):
            query_metrics, query_correctness, results = measure_queries(manager, engine, rows, protocol, runner)
            metrics.update(query_metrics)
            correctness.update(query_correctness)
        if not state['cleaned']:
            raise RuntimeError('Owned benchmark schema was not cleaned')
        ui_metrics, ui_correctness = measure_ui(manager, results, protocol, output)
        metrics.update(ui_metrics)
        correctness.update(ui_correctness)

        def cold():
            worker = subprocess.run([sys.executable, str(root / HARNESS[0]), 'worker-cold'],
                cwd=root, env={**os.environ, 'PYTHONHASHSEED': '0'},
                capture_output=True, text=True, encoding='utf-8', timeout=60,
                **lock.child_options())
            if worker.returncode:
                raise RuntimeError('Cold declaration worker failed; no performance conclusion')
            return json.loads(worker.stdout)

        metrics['cold_declarations'], correctness['cold_declarations'] = sample(cold, protocol['cold_process'])
        if source_identity(root) != before or harness != {name: file_hash(root / name) for name in HARNESS}:
            raise RuntimeError('Source or benchmark harness changed during measurement')
        if file_hash(protocol_path) != protocol_hash or machine_environment(root) != environment:
            raise RuntimeError('Protocol, machine, or dependencies changed during measurement')
        return dict(schema=1, passed=True, measured_at_utc=datetime.now(UTC).isoformat(),
                    protocol_sha256=protocol_hash, harness_sha256=digest(harness),
                    source_sha256=before, **environment,
                    metrics=metrics, correctness=correctness, fixture_sha256=state['fixture_sha256'],
                    ddl_sha256=state['ddl_sha256'], mysql=state['mysql'], cleanup=state['cleaned'],
                    limits=protocol['limits'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('measure', 'compare', 'freeze', 'worker-cold'))
    parser.add_argument('--protocol', type=Path, default=PROTOCOL)
    parser.add_argument('--test-settings', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'worker-cold':
        with restricted_network():
            from empire.bootstrap import build_manager
            print(json.dumps(manager_signature(build_manager(configuration(ROOT)))))
        return 0
    if args.output is None:
        parser.error('--output is required')
    if args.action != 'freeze' and not args.output.resolve().is_relative_to((ROOT / 'build').resolve()):
        parser.error('measurement/comparison output must remain under build/')
    protocol = json.loads(args.protocol.read_text('utf-8'))
    if args.action == 'measure':
        if not args.test_settings:
            parser.error('--test-settings is required; production defaults are never loaded')
        result = measure(ROOT, args.protocol, args.test_settings, args.output)
        if args.baseline:
            comparison = compare(json.loads(args.baseline.read_text('utf-8')), result, protocol,
                                 file_hash(args.protocol))
            result.update(comparison=comparison, passed=comparison['passed'])
    else:
        if not args.report:
            parser.error('--report is required')
        report = json.loads(args.report.read_text('utf-8'))
        if args.action == 'freeze':
            errors = validate_report(report, protocol, file_hash(args.protocol))
            if (report.get('harness_sha256') != digest({name: file_hash(ROOT / name) for name in HARNESS})
                    or report.get('source_sha256') != source_identity(ROOT)):
                errors.append('measurement inputs changed before baseline freeze')
            if errors:
                raise ValueError('Cannot freeze invalid measurement: ' + ', '.join(errors))
            result = dict(report, frozen_baseline=True)
        else:
            if not args.baseline:
                parser.error('--baseline is required')
            result = compare(json.loads(args.baseline.read_text('utf-8')), report, protocol,
                             file_hash(args.protocol))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x' if args.action == 'freeze' else 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(('PASS' if result['passed'] else 'FAIL') + ' architecture benchmark: ' + str(args.output))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
