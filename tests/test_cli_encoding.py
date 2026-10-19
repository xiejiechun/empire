"""The executable entry owns UTF-8 even when Python starts with a legacy pipe encoding."""
import io
import os
import subprocess
import sys

import pytest

from empire import __main__ as cli


@pytest.mark.parametrize('initial_encoding', ['gbk', 'ascii'])
@pytest.mark.parametrize('operation', ['help', 'valid-config', 'missing-config'])
def test_cli_initializes_actual_pipe_encoding_before_help_config_and_errors(
        tmp_path, initial_encoding, operation):
    working = tmp_path / '另一个 工作目录'
    working.mkdir()
    config = tmp_path / '中文 配置🙂.toml'
    if operation == 'valid-config':
        config.write_text('[redis]\nnamespace = "empire:test_cli_encoding"\n[mysql]\n', encoding='utf-8')
    args = ['--help'] if operation == 'help' else ['--config', str(config), 'check-config']
    # This assertion proves the child really starts with the wrong encoding;
    # monkeypatching sys.frozen would not reproduce an interpreter's stdio setup.
    code = ('import os,sys\n'
            'assert sys.stdout.encoding == sys.stderr.encoding == os.environ["PYTHONIOENCODING"]\n'
            'from empire.__main__ import main\n'
            'raise SystemExit(main())\n')
    env = {**os.environ, 'PYTHONIOENCODING': initial_encoding, 'LOCALAPPDATA': str(tmp_path / 'isolated-user')}
    for name in ('EMPIRE_REDIS_PASSWORD', 'EMPIRE_MYSQL_PASSWORD'):
        env.pop(name, None)
    result = subprocess.run([sys.executable, '-c', code, *args], cwd=working, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30)
    stdout, stderr = result.stdout.decode('utf-8'), result.stderr.decode('utf-8')
    assert '\ufffd' not in stdout + stderr
    if operation == 'help':
        assert result.returncode == 0 and not stderr
        assert 'Empire 投资研究桌面' in stdout and '只校验本机配置' in stdout
    elif operation == 'valid-config':
        assert result.returncode == 0 and not stderr
        assert stdout.strip() == f'配置有效：{config.resolve()}'
    else:
        assert result.returncode == 1 and not stdout
        assert stderr.strip() == f'Configuration file does not exist: {config}'
        assert not config.exists()  # Explicit missing config never creates a template.


@pytest.mark.parametrize('startup_failure', [False, True])
def test_frozen_gui_without_stdio_retains_startup_and_dialog_behavior(monkeypatch, startup_failure):
    shown = []
    monkeypatch.setattr(cli, 'load_config', lambda path: {})
    monkeypatch.setattr(cli, 'configure_logging', lambda cfg: None)
    monkeypatch.setattr(cli, 'show_startup_error', shown.append)

    def run(cfg):
        if startup_failure:
            raise ValueError('中文启动错误🙂')
        return 0

    monkeypatch.setattr(cli, 'run_gui', run)
    with monkeypatch.context() as streams:
        streams.setattr(sys, 'argv', ['Empire.exe'])
        streams.setattr(sys, 'frozen', True, raising=False)
        streams.setattr(sys, 'stdout', None)
        streams.setattr(sys, 'stderr', None)
        result = cli.main()
        unchanged = sys.stdout is None and sys.stderr is None
    assert unchanged and result == int(startup_failure)
    assert shown == (['中文启动错误🙂'] if startup_failure else [])


def test_text_only_captures_are_not_replaced_or_closed(monkeypatch):
    output, error = io.StringIO(), io.StringIO()
    with monkeypatch.context() as streams:
        streams.setattr(sys, 'argv', ['empire', '--help'])
        streams.setattr(sys, 'stdout', output)
        streams.setattr(sys, 'stderr', error)
        with pytest.raises(SystemExit) as stopped:
            cli.main()
        unchanged = sys.stdout is output and sys.stderr is error
    assert stopped.value.code == 0 and unchanged
    assert not output.closed and not error.closed
    assert 'Empire 投资研究桌面' in output.getvalue() and not error.getvalue()
