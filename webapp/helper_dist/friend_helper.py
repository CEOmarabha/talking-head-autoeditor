#!/usr/bin/env python3
"""AutoEditor Helper — runs on the friend's own computer, renders their
own videos, then sleeps. Double-click "Start Helper" to launch this.

Asks two things the first time (saved locally, never uploaded):
  1. Site address   2. Connect code
Both are on the website under "set up your Helper".
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
sys.path.insert(0, str(PKG))                 # find autoeditor/ + webapp/
CONFIG = Path.home() / ".autoeditor_helper.json"


def _decode(setup_code: str):
    """A setup code is base64 of 'site|connectcode'. Returns (site, code)
    or None if it isn't one."""
    import base64
    try:
        raw = base64.urlsafe_b64decode(setup_code + "=" * (-len(setup_code)
              % 4)).decode()
        site, sep, code = raw.partition("|")
        if sep and site.startswith("http") and code:
            return site.rstrip("/"), code
    except Exception:
        pass
    return None


def setup() -> dict:
    print("First-time setup.")
    print("On the website, open 'set up your Helper', click Copy on your")
    print("Setup code, then paste it right here and press Enter.\n")
    while True:
        raw = input("  Paste your Setup code: ").strip()
        dec = _decode(raw)
        if dec:
            site, code = dec
            break
        # fallbacks for anyone who pasted the parts separately
        if raw.startswith("http"):
            site = raw.rstrip("/")
            code = input("  And your connect code: ").strip()
            if code:
                break
        print("  That didn't look right — copy the Setup code from the")
        print("  website and paste the whole thing. Let's try again.\n")
    CONFIG.write_text(json.dumps({"site": site, "code": code}))
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass
    print("\nSaved. You won't need to paste that again.\n")
    return {"site": site, "code": code}


def main() -> None:
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else setup()
    os.environ["AUTOEDITOR_WEB_API"] = cfg["site"]
    os.environ["WORKER_TOKEN"] = cfg["code"]
    os.environ.setdefault("WORK_DIR", str(Path.home() / ".autoeditor_work"))
    print("Helper is running. Leave this window open while you make a\n"
          "video; close it when you're done. Waiting for work...\n")
    from webapp.render_worker.render_worker import main as run
    run()


if __name__ == "__main__":
    main()
