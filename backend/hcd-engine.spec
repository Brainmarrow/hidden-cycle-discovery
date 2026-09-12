# -*- mode: python -*-
"""
PyInstaller spec: freezes the FastAPI backend + all ML engines into a
single-folder distribution (one-folder is much faster to start than one-file
for SciPy/PyTorch-sized apps).

Build:  pyinstaller --clean hcd-engine.spec
Output: dist/hcd-engine/
"""
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Heavy scientific packages need full collection
for pkg in ["scipy", "sklearn", "statsmodels", "pywt", "astropy",
            "pandas", "numpy", "ephem"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Torch: collect submodules only (collect_all drags in gigabytes of test data)
hiddenimports += collect_submodules("torch")

# App + server internals PyInstaller can miss
hiddenimports += [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "aiosqlite", "passlib.handlers.bcrypt",
    "app", "app.main",
] + collect_submodules("app")

a = Analysis(
    ["desktop_main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "matplotlib.tests", "scipy.spatial.cKDTree",   # trims size
        "tkinter", "PyQt5", "PySide2",
        "celery.bin",        # eager mode doesn't need the CLI
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="hcd-engine",
    console=True,            # keep console for engine logs; Electron hides it
    upx=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    name="hcd-engine",
)
