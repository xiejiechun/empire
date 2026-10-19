"""Build identity embedded by the release build; source runs use an explicit fallback."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from empire import __version__

_REQUIRED = {"version", "commit", "dirty", "requirements_sha256", "built_at_utc",
             "python", "pyinstaller", "dependency_count", "dependency_report_sha256",
             "source_sha256", "release_id"}
_DIGESTS = {"requirements_sha256", "dependency_report_sha256", "source_sha256"}


def load_build_info(path: Path | None = None) -> dict:
    target = path or Path(__file__).with_name("build_manifest.json")
    if not target.is_file():
        if getattr(sys, "frozen", False):
            raise ValueError("Missing Empire build manifest")
        return {"version": __version__, "commit": "development", "dirty": True,
                "requirements_sha256": "", "built_at_utc": "", "python": "",
                "pyinstaller": "", "dependency_count": 0, "dependency_report_sha256": "",
                "source_sha256": "", "release_id": "",
                "packaged": False}
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != _REQUIRED:
        raise ValueError("Invalid Empire build manifest")
    if (value["version"] != __version__ or not isinstance(value["dirty"], bool)
            or type(value["dependency_count"]) is not int or value["dependency_count"] < 0
            or any(not isinstance(value[key], str) or not value[key]
                   for key in _REQUIRED - {"dirty", "dependency_count"})):
        raise ValueError("Inconsistent Empire build manifest")
    if (any(not re.fullmatch(r"[0-9a-f]{64}", value[key]) for key in _DIGESTS)
            or not re.fullmatch(r"[0-9a-f]{40}", value["commit"])
            or not re.fullmatch(r"[0-9a-f]{32}", value["release_id"])):
        raise ValueError("Invalid Empire build manifest identity")
    return {**value, "packaged": True}


def build_identity() -> str:
    value = load_build_info()
    revision = value["commit"][:12]
    suffix = "+dirty" if value["dirty"] else ""
    return f"{value['version']} ({revision}{suffix})"


def build_summary() -> tuple[str, str]:
    value = load_build_info()
    if not value["packaged"]:
        return f"Empire {value['version']} · 开发环境", "当前从源码运行，未绑定发布制品摘要。"
    dirty = " · 含未提交修改" if value["dirty"] else " · 干净提交"
    text = f"Empire {value['version']} · {value['commit'][:12]}{dirty}"
    detail = (f"构建时间 UTC：{value['built_at_utc']}\nPython：{value['python']} · "
              f"PyInstaller：{value['pyinstaller']}\n依赖组件：{value['dependency_count']}\n"
              f"发布 ID：{value['release_id']}\n源输入 SHA-256：{value['source_sha256']}\n"
              f"依赖锁 SHA-256：{value['requirements_sha256']}\n"
              f"依赖清单 SHA-256：{value['dependency_report_sha256']}")
    return text, detail
