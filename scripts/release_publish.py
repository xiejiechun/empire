"""Journaled same-volume publication; old bundles are retained for recovery."""
import json
import os
from pathlib import Path

from scripts.release_identity import owned, sha256, tree_inventory, write_json


class Publication:
    def __init__(self, root, run):
        self.root = Path(root).resolve()
        self.run = owned(self.root / 'build' / 'releases', run)
        if self.run.parent != self.root / 'build' / 'releases':
            raise RuntimeError('Invalid release run directory')
        self.target = owned(self.root, self.root / 'dist' / 'Empire')
        self.stage = owned(self.run, self.run / 'staging' / '中文 空格' / 'Empire')
        self.backup = owned(self.run, self.run / 'previous' / 'Empire')
        self.rejected = owned(self.run, self.run / 'rejected' / 'Empire')
        self.journal = owned(self.run, self.run / 'publication.json')
        self.shortcut = owned(self.root, self.root / 'Empire.lnk')
        self.shortcut_stage = owned(self.run, self.run / 'Empire.lnk')
        self.shortcut_backup = owned(self.run, self.run / 'previous' / 'Empire.lnk')
        self.shortcut_rejected = owned(self.run, self.run / 'rejected' / 'Empire.lnk')

    def identity(self, path, *, file=False):
        if not path.exists():
            return None
        path = owned(self.root, path)
        return sha256(path) if file else tree_inventory(path)['sha256']

    def committed(self):
        if not self.journal.exists():
            return None
        value = json.loads(self.journal.read_text(encoding='utf-8'))
        if (value.get('schema') == 1 and value.get('run_id') == self.run.name
                and value.get('state') == 'committed' and value.get('passed') is True):
            return value
        return None

    def _restore(self, target_path, backup_path, rejected_path, previous, candidate, *, file=False):
        target, backup = self.identity(target_path, file=file), self.identity(backup_path, file=file)
        if backup is not None and backup != previous:
            raise RuntimeError('Previous artifact changed; refusing automatic recovery')
        if backup is None and target == previous:
            pass
        elif target == candidate:
            if previous is not None and backup is None:
                raise RuntimeError('Previous artifact missing; refusing destructive recovery')
            rejected_path.parent.mkdir(parents=True, exist_ok=True)
            if rejected_path.exists():
                raise RuntimeError('Recovery destination exists; refusing to overwrite it')
            os.rename(target_path, rejected_path)
            target = None
        if backup is not None:
            if target is not None:
                raise RuntimeError('Publication target changed; refusing to overwrite it')
            os.rename(backup_path, target_path)
        elif target != previous:
            raise RuntimeError('Publication target changed; manual recovery required')

    def recover(self):
        if not self.journal.exists():
            return
        value = json.loads(self.journal.read_text(encoding='utf-8'))
        if value.get('schema') != 1 or value.get('run_id') != self.run.name:
            raise RuntimeError('Unrecognized publication journal; manual inspection required')
        if value['state'] in {'committed', 'rolled_back'}:
            return
        if value['state'] != 'switching':
            raise RuntimeError('Unknown publication state; manual inspection required')
        self._restore(self.target, self.backup, self.rejected,
                      value['previous_sha256'], value['candidate_sha256'])
        shortcut = value.get('shortcut')
        if shortcut:
            self._restore(self.shortcut, self.shortcut_backup, self.shortcut_rejected,
                          shortcut['previous_sha256'], shortcut['candidate_sha256'], file=True)
        value.update(state='rolled_back', passed=False)
        write_json(self.journal, value)

    def publish(self, report, check_inputs, *, expected_package=None):
        if any(p.exists() for p in (self.journal, self.backup, self.rejected,
                                    self.shortcut_backup, self.shortcut_rejected)):
            raise RuntimeError('Release run has already entered publication')
        if not (self.stage / 'Empire.exe').is_file():
            raise RuntimeError('Staged executable is missing')
        if expected_package is not None and self.identity(self.stage) != expected_package:
            raise RuntimeError('Staged package changed after portable smoke')
        # Copy credentials only after portable smoke; never put them in public artifacts.
        config = self.target / 'config.toml'
        prepared = owned(self.run, self.stage / 'config.toml')
        if prepared.exists():
            raise RuntimeError('Staged bundle contains unexpected program credentials')
        previous = self.identity(self.target)
        if config.exists():
            owned(self.root, config)
            data = config.read_bytes()
            with prepared.open('xb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if prepared.read_bytes() != data:
                raise RuntimeError('Program configuration preservation failed')
        candidate = self.identity(self.stage)
        shortcut = (dict(previous_sha256=self.identity(self.shortcut, file=True),
                         candidate_sha256=self.identity(self.shortcut_stage, file=True))
                    if self.shortcut_stage.exists() else None)
        check_inputs()
        if previous != self.identity(self.target):
            raise RuntimeError('Installed bundle/config changed before publication')
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.backup.parent.mkdir(parents=True, exist_ok=True)
        value = dict(report, schema=1, run_id=self.run.name, state='switching', passed=False,
                     previous_sha256=previous, candidate_sha256=candidate, shortcut=shortcut)
        write_json(self.journal, value)
        try:
            if self.target.exists():
                os.rename(self.target, self.backup)
            os.rename(self.stage, self.target)
            if shortcut:
                if self.identity(self.shortcut, file=True) != shortcut['previous_sha256']:
                    raise RuntimeError('Shortcut changed before publication')
                if self.shortcut.exists():
                    os.rename(self.shortcut, self.shortcut_backup)
                os.rename(self.shortcut_stage, self.shortcut)
            check_inputs()
            if self.identity(self.target) != candidate:
                raise RuntimeError('Published bundle/config differs from the verified candidate')
            if shortcut and self.identity(self.shortcut, file=True) != shortcut['candidate_sha256']:
                raise RuntimeError('Published shortcut differs from verified candidate')
            value.update(state='committed', passed=True)
            write_json(self.journal, value)
        except BaseException:
            committed = self.committed()
            if committed:
                return committed  # The durable commit wins over a late cancellation.
            self.recover()
            raise
        return value


def recover_pending(root):
    folder = owned(Path(root).resolve(), Path(root) / 'build' / 'releases')
    if folder.exists():
        for journal in sorted(folder.glob('*/publication.json')):
            Publication(root, journal.parent).recover()
