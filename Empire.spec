# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH)
source_root = project_root / "src"

a = Analysis(
    [str(source_root / "empire" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[
        (str(source_root / "empire" / "desktop" / "assets"), "empire/desktop/assets"),
        (str(project_root / "config" / "app.example.toml"), "config"),
        (str(project_root / "sql" / "schema.sql"), "sql"),
        (
            str(source_root / "empire" / "plugins" / "ui" / "storage_reference.md"),
            "empire/plugins/ui",
        ),
        (str(project_root / "build" / "generated" / "build_manifest.json"), "empire"),
        (str(project_root / "build" / "dependency-report.json"), "empire"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Empire",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(project_root / "src" / "empire" / "desktop" / "assets" / "empire.ico")],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Empire",
)
