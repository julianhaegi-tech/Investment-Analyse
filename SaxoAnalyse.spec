# PyInstaller-Spec: baut eine einzelne ausführbare Datei (Windows: SaxoAnalyse.exe)
# Aufruf:  pyinstaller SaxoAnalyse.spec
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["run.py"],
    pathex=["."],
    datas=[("saxo_analyse/static", "saxo_analyse/static")],
    hiddenimports=collect_submodules("saxo_analyse") + ["openpyxl", "bs4", "pdfplumber"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PySide6"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="SaxoAnalyse",
    console=True,   # Konsolenfenster zeigt Adresse & Status; schliessen = App beenden
    upx=False,
)
