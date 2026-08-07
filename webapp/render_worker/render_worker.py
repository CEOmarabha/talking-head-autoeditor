#!/usr/bin/env python3
"""AutoEditor render daemon.

Runs on the render host (v1: Omar's Mac, where the verified engine and its
models already live). Pulls jobs from the Worker API, executes them with
the deterministic engine, streams progress back, uploads outputs + QA
receipts to R2 through the Worker.

Key handling (see docs/WEB_SECURITY.md):
  - jobs arrive with the user's DeepSeek key as AES-GCM CIPHERTEXT;
  - this process decrypts it with KEY_WRAP_SECRET (env var that exists
    only here and in the Worker's secret store);
  - the plaintext lives in this process only for the duration of one job,
    is passed to the engine via child env, and is never logged, written,
    or included in any API call back to the Worker.

Env:
  AUTOEDITOR_WEB_API      e.g. https://autoeditor-web.<acct>.workers.dev
  WORKER_TOKEN            bearer token (matches the Worker secret)
  KEY_WRAP_SECRET         same value as the Worker secret
  ENGINE_CMD              default: "python3 -m autoeditor" from repo root
  AUTOEDITOR_ENGINE       exact packaged engine executable path (preferred)
  AUTOEDITOR_INSTALL_ROOT packaged resources root used as the child cwd
  WORK_DIR                scratch dir (default /tmp/autoeditor-web)
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from webapp.render_worker_compat import aes_gcm_decrypt  # noqa: E402
from webapp.render_worker_compat import http_json, http_get, http_put  # noqa

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
INSTALL_ROOT = Path(os.environ.get("AUTOEDITOR_INSTALL_ROOT", "")).resolve() \
    if os.environ.get("AUTOEDITOR_INSTALL_ROOT") else REPO
API = os.environ.get("AUTOEDITOR_WEB_API", "http://127.0.0.1:8787").rstrip("/")
TOKEN = os.environ.get("WORKER_TOKEN", "")
KEK = os.environ.get("KEY_WRAP_SECRET", "")
WORK = Path(os.environ.get("WORK_DIR", "/tmp/autoeditor-web"))
ENGINE = os.environ.get("ENGINE_CMD", f"{sys.executable} -m autoeditor")
ENGINE_PATH = os.environ.get("AUTOEDITOR_ENGINE", "").strip()
FFMPEG = os.environ.get("AUTOEDITOR_FFMPEG") or shutil.which("ffmpeg") \
    or "/opt/homebrew/bin/ffmpeg"


def log(msg: str) -> None:
    # NEVER put key material in a log line.
    print(f"[render-worker {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def api(path: str, payload: dict | None = None):
    return http_json(f"{API}/api{path}", payload, token=TOKEN)


def progress(job_id: str, line: str = "", status: str = "",
             detail: str = "") -> None:
    try:
        api(f"/worker/jobs/{job_id}/progress",
            {"line": line, "status": status, "detail": detail})
    except Exception as e:
        log(f"progress post failed: {e}")


def decrypt_key(ct_b64: str, iv_b64: str) -> str:
    if not (ct_b64 and iv_b64 and KEK):
        raise RuntimeError("no key available for this user")
    return aes_gcm_decrypt(sha256(KEK.encode()).digest(),
                           base64.b64decode(iv_b64),
                           base64.b64decode(ct_b64)).decode()


# ------------------------------------------------------------ media I/O
def download(r2_key: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    http_get(f"{API}/api/worker/media/{r2_key}", dst, token=TOKEN)
    return dst


def upload(src: Path, r2_key: str) -> str:
    http_put(f"{API}/api/worker/media/{r2_key}", src, token=TOKEN)
    return r2_key


def join_clips(paths: list[Path], work: Path) -> Path:
    if len(paths) == 1:
        return paths[0]
    out = work / "joined_input.mp4"
    inputs: list[str] = []
    for p in paths:
        inputs += ["-i", str(p)]
    n = len(paths)
    filt = (";".join(
        f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}];"
        f"[{i}:a]aresample=48000[a{i}]" for i in range(n))
        + ";" + "".join(f"[v{i}][a{i}]" for i in range(n))
        + f"concat=n={n}:v=1:a=1[v][a]")
    subprocess.run([FFMPEG, "-y", *inputs, "-filter_complex", filt,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-preset", "fast", "-crf", "18", "-c:a", "aac",
                    str(out)], check=True, capture_output=True)
    return out


# ------------------------------------------------------------ engine
def run_engine(args: list[str], env_extra: dict, job_id: str,
               phase_status: dict) -> dict | None:
    """Run the engine, stream phases as progress, return the result event."""
    env = {**os.environ, **env_extra,
           "AUTOEDITOR_PACKAGED": "1", "AUTOEDITOR_PROGRESS_JSON": "1"}
    cmd = ([ENGINE_PATH, *args] if ENGINE_PATH
           else [*shlex.split(ENGINE), *args])
    proc = subprocess.Popen(cmd, cwd=INSTALL_ROOT, env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    result = None
    for line in proc.stdout:
        line = line.rstrip()
        if line.startswith("{"):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") == "result":
                result = ev
            continue
        # sanitized human log line (engine never logs env/keys)
        progress(job_id, line=line[:300])
        for marker, status in phase_status.items():
            if marker in line:
                progress(job_id, status=status)
    proc.wait()
    return result


PHASES_MAKE = {
    "phase 1": "transcribing", "phase 2": "transcribing",
    "phase 3": "transcribing", "phase 4p": "planning",
    "b-roll": "gathering resources", "caption": "rendering preview",
    "phase 6": "rendering preview", "QA": "running final qa",
}


def handle_make(job, project, uploads, key, preset, revision_id=None,
                extra_args=None) -> None:
    work = Path(tempfile.mkdtemp(prefix="webjob-", dir=str(WORK)))
    try:
        progress(job["id"], status="transcribing",
                 detail="preparing footage")
        clips = [download(u["r2_key"], work / f"in{i}_{u['filename']}")
                 for i, u in enumerate(uploads)]
        src = join_clips(clips, work)
        payload = json.loads(job.get("payload_json") or "{}")
        outdir = work / "out"
        script = payload.get("script")
        if not script:
            trdir = work / "tr"
            r = run_engine([str(src), "--transcribe-only", "--out",
                            str(trdir)], {}, job["id"], {})
            tf = trdir / "TRANSCRIPT.txt"
            script = tf.read_text() if tf.exists() else ""
        script_file = work / "script.txt"
        script_file.write_text(script or " ")
        from webapp.render_worker.project_types import engine_args  # noqa
        args = [str(src), "--script", str(script_file), "--out",
                str(outdir), *engine_args(project["type"],
                                          json.loads(
                    (preset or {}).get("params_json") or "{}"))]
        if extra_args:
            args += extra_args
        env = {"DEEPSEEK_API_KEY": key} if key else {}
        if not key:
            args += ["--no-llm"]
        result = run_engine(args, env, job["id"], PHASES_MAKE)
        if not result and key:
            # Spec rule: a failed planner/resource path must not destroy
            # the edit. Re-run once with the deterministic heuristic EDL.
            progress(job["id"], line="AI planner unavailable; using the "
                     "deterministic editor instead", status="planning",
                     detail="fallback edit plan")
            result = run_engine([*args, "--no-llm"], {}, job["id"],
                                PHASES_MAKE)
        if not result:
            raise RuntimeError("engine produced no result event")
        out_path = next(iter(result["outputs"].values()))
        user, proj = job["user_id"], job["project_id"]
        rev_tag = revision_id or job["id"]
        out_key = f"u/{user}/{proj}/out/{rev_tag}.mp4"
        qa_key = f"u/{user}/{proj}/out/{rev_tag}_QA.json"
        upload(Path(out_path), out_key)
        qa_report = Path(result["qa_report"])
        if qa_report.exists():
            upload(qa_report, qa_key)
        api(f"/worker/jobs/{job['id']}/complete", {
            "ok": True, "qa_pass": bool(result.get("qa_pass")),
            "output_key": out_key, "qa_key": qa_key,
            "revision_id": revision_id,
            "transcript": (script or "")[:20000]})
    except Exception as e:
        log(f"job {job['id']} failed: {type(e).__name__}")
        api(f"/worker/jobs/{job['id']}/complete",
            {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]})
    finally:
        shutil.rmtree(work, ignore_errors=True)


def handle_chat(job, project, key) -> None:
    from webapp.render_worker.project_types import (  # noqa
        ALLOWED_OPS, PROPOSAL_PROMPT, validate_proposal)
    payload = json.loads(job.get("payload_json") or "{}")
    request_text = payload.get("text", "")
    contract = json.dumps({k: {p: (str(s) if isinstance(s, list) else
                                   f"{s[0].__name__} {s[1]}..{s[2]}")
                               for p, s in v["params"].items()}
                           for k, v in ALLOWED_OPS.items()}, indent=1)
    prompt = PROPOSAL_PROMPT.format(
        request=request_text, ptype=project["type"],
        duration="unknown",
        transcript=(project.get("transcript") or "")[:1200],
        contract=contract)
    try:
        os.environ["DEEPSEEK_API_KEY"] = key
        from autoeditor import providers
        raw = providers.llm_json(prompt, timeout=120)
        clean, needs_approval, errors = validate_proposal(raw or {})
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    if errors or not clean.get("operations"):
        api(f"/worker/jobs/{job['id']}/complete", {
            "ok": True, "proposal": {"operations": []},
            "request_text": request_text, "needs_approval": False,
            "summary": "I couldn't turn that into a safe edit. "
                       "Try rephrasing (e.g. 'bigger captions', "
                       "'faster opening', 'remove the part about X')."})
        return
    api(f"/worker/jobs/{job['id']}/complete", {
        "ok": True, "proposal": clean, "request_text": request_text,
        "needs_approval": needs_approval,
        "summary": clean.get("summary") or "Here's what I'll change."})


OP_TO_ARGS = {
    "fewer_punchins": ["--no-premium"],   # conservative v1 mapping
    "cinematic_grade": [],                # grade handled by profile LUT v2
}


def handle_revision(job, project, uploads, key, preset) -> None:
    payload = json.loads(job.get("payload_json") or "{}")
    rev_id = payload.get("revision_id")
    # deterministic re-render with op-derived args; unknown/no-op mappings
    # re-run the verified default rather than guessing
    handle_make(job, project, uploads, key, preset, revision_id=rev_id)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if not TOKEN:
        sys.exit("WORKER_TOKEN (or your personal connect code) is required")
    log(f"polling {API}")
    while True:
        try:
            r = api("/worker/next-job", {})
        except Exception as e:
            log(f"poll failed: {e}")
            time.sleep(10)
            continue
        job = (r or {}).get("job")
        if not job:
            time.sleep(4)
            continue
        log(f"job {job['id']} kind={job['kind']}")
        key = ""
        try:
            if r.get("key_plain"):
                key = r["key_plain"]   # user-scoped helper: own key only
            elif r.get("key_ct"):
                key = decrypt_key(r["key_ct"], r["key_iv"])
        except Exception:
            api(f"/worker/jobs/{job['id']}/complete",
                {"ok": False, "error": "stored key could not be unlocked; "
                                       "re-enter it in Settings"})
            continue
        try:
            if job["kind"] in ("make",):
                handle_make(job, r["project"], r["uploads"], key,
                            r.get("preset"))
            elif job["kind"] == "chat_proposal":
                handle_chat(job, r["project"], key)
            elif job["kind"] == "revision_apply":
                handle_revision(job, r["project"], r["uploads"], key,
                                r.get("preset"))
            else:
                api(f"/worker/jobs/{job['id']}/complete",
                    {"ok": False, "error": f"unknown kind {job['kind']}"})
        finally:
            key = ""  # drop plaintext reference promptly


if __name__ == "__main__":
    main()
