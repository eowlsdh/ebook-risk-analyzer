# PyInstaller one-folder build for the offline Windows application.
# Run from the repository root with `python -m PyInstaller packaging/ebook-risk-analyzer.spec`.
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis

ROOT = Path(SPECPATH).resolve().parent
PACKAGE = ROOT / "ebook_risk_analyzer"


a = Analysis(
    [str(ROOT / "packaging" / "windows_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(PACKAGE / "templates"), "ebook_risk_analyzer/templates"),
        (str(PACKAGE / "static"), "ebook_risk_analyzer/static"),
        (str(ROOT / "config"), "config"),
    ],
    hiddenimports=["ebook_risk_analyzer.web_app"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

# The GUI executable launches the browser UI when its Start Menu/Desktop shortcut
# supplies the `web` argument. The CLI executable preserves analyze/compare usage.
gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EbookRiskAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=None,
)
cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EbookRiskAnalyzerCLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=None,
)

coll = COLLECT(
    gui,
    cli,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EbookRiskAnalyzer",
)
