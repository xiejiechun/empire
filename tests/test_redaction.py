import json
import logging
from urllib.parse import quote, quote_plus

import pytest

from empire.core.redaction import REDACTED, RedactingFormatter, Redactor, redact


@pytest.mark.parametrize("password", ['"', "'", "\\", 'quote"slash\\中文@+/#?:%', "\n\t"])
def test_structured_redaction_preserves_json_keys_and_structure(password):
    original = {"plugins": [{"id": "infra.mysql", "health": {"message": f"failure {password}",
                "password": password, "rows": 12, "ok": False}}], 'quoted"key': "ordinary"}
    result = Redactor((password,)).value(original)
    restored = json.loads(json.dumps(result))
    assert set(restored) == set(original)
    assert restored["plugins"][0]["id"] == "infra.mysql"
    health = restored["plugins"][0]["health"]
    assert health["message"] == "failure " + REDACTED
    assert health["password"] == REDACTED
    assert health["rows"] == 12 and health["ok"] is False
    assert original["plugins"][0]["health"]["password"] == password


def test_free_text_logs_cover_json_repr_and_url_encoded_credentials():
    password = 'complex"\\@+/% 中文'
    guard = Redactor((password,))
    variants = (password, json.dumps(password)[1:-1], repr(password)[1:-1],
                quote(password, safe=""), quote_plus(password))
    for variant in variants:
        assert guard.text("driver failed: " + variant) == "driver failed: " + REDACTED


@pytest.mark.parametrize("scheme", ["http", "https", "socks5", "socks5h", "redis", "rediss", "mysql+pymysql"])
def test_all_supported_connection_schemes_remove_userinfo_and_private_queries(scheme):
    result = Redactor().text(
        f'{scheme}://name:p@ss"word%40@localhost:1234/path?access_token=private&page=2#hidden')
    for credential in ("name", "word", "private", "hidden"):
        assert credential not in result
    assert "localhost:1234/path" in result and "page=2" in result


def test_headers_and_escaped_quoted_values_share_one_redactor():
    raw = 'Proxy-Authorization: Basic private header\nSet-Cookie: session=privatecookie\n'
    raw += 'password="private\\\"suffix"\n{"token": "private\\\\suffix", "broken":'
    result = Redactor().text(raw)
    assert "private" not in result and "suffix" not in result


def test_common_log_formatter_and_ui_text_use_the_same_rules():
    cfg = {"mysql": {"password": 'complex"quoted'}}
    message = 'database complex"quoted; socks5h://user:proxysecret@localhost:1'
    log = logging.LogRecord("test", logging.ERROR, "", 1, "%s", (message,), None)
    assert redact(message, cfg) in RedactingFormatter(cfg).format(log)
    assert "proxysecret" not in RedactingFormatter(cfg).format(log)


def test_structured_redaction_bounds_cycles_without_changing_mapping_keys():
    value = {"nested": {"Authorization": "private"}, "password_counter": 5}
    value["cycle"] = value
    result = Redactor().value(value, max_depth=5)
    assert result["nested"]["Authorization"] == REDACTED
    assert set(result) == set(value)
    assert "depth limited" in json.dumps(result)


def test_plugin_diagnostics_serialize_only_after_redacting_values():
    import os
    from types import SimpleNamespace

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.system import PluginsPage

    app = QApplication.instance() or QApplication([])
    runtime = SimpleNamespace(snapshot=lambda: {"plugins": [
        {"id": "infra.mysql", "name": "MySQL", "state": "RUNNING", "requires": [],
         "health": {'quoted"key': 'failed "', "password": '"'}}]})
    page = PluginsPage(SimpleNamespace(runtime=runtime, cfg={"mysql": {"password": '"'}}))
    try:
        page.timer.stop()
        diagnostic = json.loads(page.diagnostics.toPlainText())
        assert diagnostic["标识"] == "infra.mysql"
        assert diagnostic["运行状态"]['quoted"key'] == "failed [REDACTED]"
        assert diagnostic["运行状态"]["password"] == "[REDACTED]"
    finally:
        page.deleteLater()
        app.processEvents()
