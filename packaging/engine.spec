# PyInstaller spec: frozen AutoEditor engine (onedir, console).
# Build:  pyinstaller packaging/engine.spec
# Output: dist/autoeditor-engine/

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

spec_dir = Path(SPECPATH).resolve()
repo_root = spec_dir.parent

datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub",
            "onnxruntime", "av"):
    # Every release lock includes these runtime backends.  Failing the freeze
    # is safer than creating an installer that opens normally and only finds
    # out on a friend's first transcript that a native ASR dependency was
    # silently omitted.
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    [str(spec_dir / "engine_entry.py")],
    pathex=[str(repo_root)],
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
    # auto-editor 29.3.1 on PyPI is only a first-run native-binary downloader.
    # The product uses its own frozen in-process low-speech cutter instead,
    # so keep the network loader out of every Mac and Windows artifact.
    excludes=["tkinter", "matplotlib", "pytest", "auto_editor"],
)
pyz = PYZ(a.pure)
options = [("X utf8", None, "OPTION")]
exe = EXE(pyz, a.scripts, options, exclude_binaries=True,
          name="autoeditor-engine", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="autoeditor-engine")
