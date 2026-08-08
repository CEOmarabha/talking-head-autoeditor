#!/usr/bin/env python3
"""AutoEditor Helper — the small app each friend runs on their OWN computer.

It does the video rendering for that friend's projects only, then sleeps.
Nothing runs on Omar's machine; nothing needs to stay up but the friend's
own PC while they want a video made.

First run asks two things (saved to a local config file, never uploaded):
  1. Site address  (e.g. https://autoeditor-web.<acct>.workers.dev)
  2. Connect code   (a personal code Omar gives each friend, one each)

Then it loops: pull MY jobs -> render with the verified engine -> upload
the finished video -> mark it Ready or Needs Review. Close the window to
stop; reopen any time to render queued jobs.

The friend's DeepSeek key never touches this file as text on disk: it
arrives per-job over TLS, lives in memory only while that job renders, and
is dropped afterward. This helper only ever sees THAT friend's own jobs and
media (the connect code is scoped server-side).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG = Path.home() / ".autoeditor_helper.json"


def prompt_config() -> dict:
    print("=" * 60)
    print(" AutoEditor Helper — first-time setup")
    print("=" * 60)
    print("Paste the two things Omar sent you.\n")
    site = input("  Site address: ").strip().rstrip("/")
    code = input("  Your connect code: ").strip()
    cfg = {"site": site, "code": code}
    CONFIG.write_text(json.dumps(cfg))
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass
    print(f"\nSaved. (You can change it later by editing {CONFIG})\n")
    return cfg


def load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text())
        except ValueError:
            pass
    return prompt_config()


def main() -> None:
    cfg = load_config()
    # The helper IS the render worker, pointed at the friend's own scope.
    os.environ["AUTOEDITOR_WEB_API"] = cfg["site"]
    os.environ["WORKER_TOKEN"] = cfg["code"]      # personal, user-scoped
    os.environ.setdefault("WORK_DIR",
                          str(Path.home() / ".autoeditor_helper_work"))
    # user-scoped helpers receive their own key in plaintext over TLS, so
    # no KEY_WRAP_SECRET is needed here.
    print("AutoEditor Helper is running. Leave this window open while you\n"
          "make videos; close it when you're done. Waiting for jobs...\n")
    sys.path.insert(0, str(HERE.parents[2]))
    from webapp.render_worker.render_worker import main as run
    run()


if __name__ == "__main__":
    main()
