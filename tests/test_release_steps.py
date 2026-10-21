"""Gate sequencing, evidence retention and portable smoke use isolated outputs."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.release_identity import sha256
from scripts.release_steps import retain_evidence, verify


@pytest.mark.parametrize('failed', [None, 'help', 'pytest', 'capacity', 'architecture', 'assembly'])
def test_verification_requires_all_checks_and_stops_on_failure(tmp_path, failed):
    calls = []
    run = tmp_path / 'build/releases/unit'
    run.mkdir(parents=True)

    def command(args, **kwargs):
        words = [str(v) for v in args]
        text = ' '.join(words)
        calls.append(text)
        if 'assembly_contract.py' in text:
            assert words == [
                'python', str(tmp_path / 'scripts/assembly_contract.py'), 'check',
                '--baseline', str(tmp_path / 'docs/evidence/assembly-baseline-2026-10-19.json'),
                '--mapping', str(tmp_path / 'docs/assembly-migrations.json'),
                '--order-baseline', str(tmp_path / 'docs/evidence/assembly-order-baseline-2026-10-19.json'),
            ]
        if 'documentation_build.py' in text:
            assert words == ['python', str(tmp_path / 'scripts/documentation_build.py'),
                             'check', '--report', str(run / 'help-report.json')]
        if failed and ((failed == 'pytest' and '-m pytest' in text)
                       or (failed == 'help' and 'documentation_build.py' in text)
                       or (failed == 'capacity' and 'measure_capacity.py' in text)
                       or (failed == 'architecture' and 'architecture_contract.py' in text)
                       or (failed == 'assembly' and 'assembly_contract.py' in text)):
            raise RuntimeError('injected gate failure')
        if any(name in text for name in ('audit_dependencies.py', 'measure_capacity.py', 'documentation_build.py')):
            flag = '--report' if 'documentation_build.py' in text else '--output'
            target = Path(words[words.index(flag) + 1])
            target.write_text(json.dumps({'passed': True}), encoding='utf-8')
        if '-m pytest' in text:
            assert kwargs['env']['EMPIRE_INTEGRATION'] == '1'
            target = Path(words[words.index('--junitxml') + 1])
            target.write_text('<testsuite/>', encoding='utf-8')
            assert str(run / 'pytest') in words
        if 'preparation_evidence.py' in text and words[-1] == 'finish':
            target = tmp_path / 'build/generated/preparation-release.json'
            target.parent.mkdir()
            target.write_text('{}', encoding='utf-8')

    runner = SimpleNamespace(root=tmp_path, run_directory=run, python='python', evidence={}, command=command)
    if failed:
        with pytest.raises(RuntimeError, match='injected'):
            verify(runner)
        assert not calls[-1].endswith(' package')
    else:
        dependency, capacity = verify(runner)
        assert dependency.exists() and capacity.exists()
        assert len(runner.evidence) == 5
        assert all('documentation_build.py generate' not in command for command in calls)
        for step in ('verify_release_environment.py', 'audit_dependencies.py', 'documentation_build.py', 'verify_documentation.py',
                     'verify_database_design.py', 'architecture_contract.py', 'assembly_contract.py',
                     '-m ruff check', '-m mypy', '-m pip check', 'diff --check', '-m pytest',
                     'measure_capacity.py', 'verify_foundation_ui.py'):
            assert any(step in call for call in calls), step
        assert calls[-1].endswith(' package')
        assert sum('verify_foundation_ui.py' in call for call in calls) == 4


def test_retained_outputs_survive_later_generated_file_replacement(tmp_path):
    run = tmp_path / 'build/releases/unit'
    run.mkdir(parents=True)
    generated = tmp_path / 'build/evidence.json'
    generated.write_text('{"passed":true}', encoding='utf-8')
    runner = SimpleNamespace(root=tmp_path, run_directory=run,
                             evidence={'build/evidence.json': sha256(generated)}, check=lambda: None)
    result = retain_evidence(runner)
    generated.write_text('{"passed":false}', encoding='utf-8')
    artifact = result['build/evidence.json']
    assert sha256(artifact['path']) == artifact['sha256']
    assert json.loads(Path(artifact['path']).read_text())['passed'] is True
