# PyInstaller spec: frozen AutoEditor engine (onedir, console).
# Build:  pyinstaller packaging/engine.spec
# Output: dist/autoeditor-engine/

import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub",
            "onnxruntime", "av"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass  # optional deps may be absent in slim builds

a = Analysis(
    ["engine_entry.py"],
    pathex=[os.path.abspath(os.path.join(os.getcwd(), ".."))
            if os.path.basename(os.getcwd()) == "packaging" else os.getcwd()],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports + ["autoeditor", "autoeditor.pipeline",
                                   "autoeditor.premium",
                                   "autoeditor.creative_contract",
                                   "autoeditor.providers",
                                   "autoeditor.profiles",
                                   "autoeditor.config",
                                   "autoeditor.calibrate",
                                   "PIL", "numpy"],
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="autoeditor-engine", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="autoeditor-engine")
