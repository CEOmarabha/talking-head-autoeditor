# PyInstaller spec for the website render daemon. The editing engine remains
# a separate frozen executable so command-line behavior and QA receipts stay
# identical to the desktop product.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

spec_dir = Path(SPECPATH).resolve()
repo_root = spec_dir.parent
datas, binaries, hiddenimports = [], [], []
for pkg in ("cryptography", "certifi", "PIL", "numpy"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [str(spec_dir / "helper_daemon_entry.py")],
    pathex=[str(repo_root)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports + [
        "webapp", "webapp.render_worker_compat",
        "webapp.render_worker.render_worker",
        "webapp.render_worker.project_types",
        "autoeditor", "autoeditor.providers", "autoeditor.premium",
        "autoeditor.config", "autoeditor.creative_contract",
        "autoeditor.creative_constraints", "autoeditor.sequence_plan",
        "autoeditor.sequence_render", "autoeditor.color_contract",
        "autoeditor.transition_plan", "autoeditor.transition_render",
        "autoeditor.sfx_plan", "autoeditor.sfx_render",
        "autoeditor.sfx_production",
        "autoeditor.music_plan", "autoeditor.music_render",
        "autoeditor.edit_policy",
        "autoeditor.project_intent_policy_bridge",
        "autoeditor.project_intent_authority",
        "autoeditor.runtime_capabilities",
    ],
    excludes=["tkinter", "matplotlib", "pytest", "av"],
)
pyz = PYZ(a.pure)
options = [("X utf8", None, "OPTION")]
exe = EXE(pyz, a.scripts, options, exclude_binaries=True,
          name="autoeditor-helper-daemon", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="autoeditor-helper-daemon")
