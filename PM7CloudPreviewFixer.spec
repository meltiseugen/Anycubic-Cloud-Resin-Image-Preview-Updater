# PyInstaller configuration: Windows x64, offline, no console or external Python required.
from pathlib import Path

root = Path(SPECPATH)
analysis = Analysis(
    [str(root / "src" / "main.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(root / "THIRD_PARTY_NOTICES.md"), "."),
           (str(root / "licenses"), "licenses")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.QtNetwork", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="PM7CloudPreviewFixer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=str(root / "packaging" / "version.txt"),
)
