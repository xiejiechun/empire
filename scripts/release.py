"""One release owner verifies, stages, smokes and safely publishes Empire."""
import argparse
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_identity import (
    assert_inputs,
    input_inventory,
    input_stats,
    owned,
    sha256,
    write_json,
)
from scripts.release_lock import ReleaseLock
from scripts.release_publish import Publication, recover_pending
from scripts.release_steps import package, portable_smoke, prepare_shortcut, retain_evidence, verify


class Runner:
    def __init__(self, root, lock, run):
        self.root, self.lock, self.run_directory = root, lock, run
        self.python = root / '.venv/Scripts/python.exe'
        self.commit = self.git('rev-parse', 'HEAD')
        if len(self.commit) != 40 or any(c not in '0123456789abcdef' for c in self.commit):
            raise RuntimeError('A Git commit is required to identify the release')
        self.dirty = bool(self.git('status', '--porcelain'))
        self.inputs = input_inventory(root)
        self.input_stats = input_stats(root, self.inputs)
        self.evidence = {}
        write_json(run / 'inputs.json', dict(self.inputs, commit=self.commit, dirty=self.dirty,
                                            local_stat_guard=self.input_stats,
                                            private_config='excluded', generated_outputs='excluded'))

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True,
                                       **self.lock.child_options()).strip()

    def check(self):
        assert_inputs(self.root, self.inputs)
        stats = input_stats(self.root, self.inputs)
        if stats != self.input_stats:
            changed = [name for name in stats if stats[name] != self.input_stats[name]]
            raise RuntimeError('Release inputs were edited, including restored bytes: ' + ', '.join(changed[:12]))
        if self.git('rev-parse', 'HEAD') != self.commit:
            raise RuntimeError('Git HEAD changed during the release')
        for name, digest in self.evidence.items():
            if sha256(self.root / name) != digest:
                raise RuntimeError('Generated release evidence changed: ' + name)

    def command(self, args, *, cwd=None, env=None, expected=0):
        self.check()
        print('Release step: ' + ' '.join(str(v) for v in args), flush=True)
        result = subprocess.run([str(v) for v in args], cwd=cwd or self.root,
                                env={**os.environ, **(env or {})},
                                **self.lock.child_options())
        self.check()
        if result.returncode != expected:
            raise RuntimeError(f'Release step failed (exit {result.returncode}): {Path(args[0]).name}')


def require_stopped(lock, root):
    if os.name != 'nt':
        raise RuntimeError('The desktop release gate requires Windows')
    script = ("$p = Get-Process Empire -ErrorAction SilentlyContinue | "
              "Where-Object { $_.Threads.Count -gt 0 }; if ($p) { exit 3 }")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            cwd=root, **lock.child_options())
    if result.returncode != 0:
        raise RuntimeError('Close Empire normally before release or recovery; no process was killed')


def release(root, *, recover_only=False):
    root = Path(root).resolve()
    with ReleaseLock(root) as lock:
        require_stopped(lock, root)
        recover_pending(root)
        if recover_only:
            print('PASS publication recovery; existing bundles and configuration retained.')
            return
        run = owned(root, root / 'build' / 'releases' / uuid.uuid4().hex)
        run.mkdir(parents=True)
        runner = Runner(root, lock, run)
        publication = Publication(root, run)
        try:
            dependency, capacity = verify(runner)
            manifest = package(runner, publication, dependency)
            smoke = portable_smoke(runner, publication)
            prepare_shortcut(runner)
            outputs = retain_evidence(runner)
            require_stopped(lock, root)
            runner.check()
            report = dict(verified_at_utc=datetime.now(UTC).isoformat(), manifest=manifest,
                          source_sha256=runner.inputs['sha256'], inputs=str(run / 'inputs.json'),
                          generated_outputs=outputs,
                          executable_sha256=sha256(publication.stage / 'Empire.exe'),
                          capacity_report=str(capacity), dependency_report=str(dependency),
                          portable_distribution=smoke,
                          configuration='preserved locally; excluded from portable artifacts',
                          actual_desktop='not verified by this gate')
            committed = publication.publish(report, runner.check,
                                             expected_package=smoke['package']['sha256'])
        except BaseException:
            committed = publication.committed()
            if committed:
                print('Publication was committed before interruption; retaining the committed result.')
            else:
                write_json(run / 'failure.json', dict(passed=False, run_id=run.name,
                           recorded_at_utc=datetime.now(UTC).isoformat(),
                           detail='Release failed or interrupted; inspect command output and publication journal'))
                raise
        # The durable committed journal remains authoritative if a summary copy fails.
        try:
            write_json(root / 'build/release-report.json', committed)
        except OSError:
            print('Release committed; summary unavailable. Evidence: ' + str(publication.journal))
        print('PASS release gate; committed evidence: ' + str(publication.journal))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', action='store_true', help='Restore an interrupted directory switch only')
    args = parser.parse_args()
    try:
        release(Path(__file__).resolve().parents[1], recover_only=args.recover)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
