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
import threading
import time
import urllib.error
import urllib.request
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from webapp.render_worker_compat import aes_gcm_decrypt  # noqa: E402
from webapp.render_worker_compat import (  # noqa: E402
    canonical_json_bytes, http_get, http_json, http_put, http_put_range,
    safe_local_upload_name,
)

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
OUTPUT_PART_SIZE = 64 * 1024 * 1024
HEARTBEAT_SECONDS = 30


class CompletionDeliveryError(RuntimeError):
    """The Worker did not durably acknowledge a completion receipt."""


class ClaimLostError(RuntimeError):
    """This daemon attempt no longer owns the job."""


def log(msg: str) -> None:
    # NEVER put key material in a log line.
    print(f"[render-worker {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def api(path: str, payload: dict | None = None):
    return http_json(f"{API}/api{path}", payload, token=TOKEN)


def complete_job(job_id: str, claim_token: str, payload: dict) -> dict:
    """Retry completion; accept 409 only with the exact committed receipt."""
    committed_payload = {**payload, "claim_token": claim_token}
    request_hash = sha256(canonical_json_bytes(committed_payload)).hexdigest()
    expected_receipt = canonical_json_bytes({
        "committed": True,
        "completion_request_hash": request_hash,
        "job_id": job_id,
        "ok": True,
    })
    for attempt in range(8):
        try:
            return api(f"/worker/jobs/{job_id}/complete", committed_payload)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                replay_receipt = exc.read()
                if replay_receipt == expected_receipt:
                    return {"ok": True, "already_completed": True}
                raise ClaimLostError(
                    "completion conflict did not match this request") from exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                OSError) as exc:
            last = exc
        log(f"completion receipt retry {attempt + 1}/8 for job {job_id}")
        time.sleep(min(30, 2 ** attempt))
    raise CompletionDeliveryError(
        f"completion receipt was not acknowledged: {type(last).__name__}")


def progress(job_id: str, claim_token: str, line: str = "",
             status: str = "", detail: str = "",
             strict: bool = False) -> None:
    try:
        api(f"/worker/jobs/{job_id}/progress",
            {"claim_token": claim_token, "line": line,
             "status": status, "detail": detail})
    except urllib.error.HTTPError as e:
        if e.code in {403, 409}:
            raise ClaimLostError("job heartbeat was rejected") from e
        if strict:
            raise
        log(f"progress post failed: {e}")
    except Exception as e:
        if strict:
            raise
        log(f"progress post failed: {e}")


class ClaimHeartbeat:
    def __init__(self, job_id: str, claim_token: str) -> None:
        self.job_id = job_id
        self.claim_token = claim_token
        self.stop_event = threading.Event()
        self.lost_event = threading.Event()
        self.thread = threading.Thread(target=self._run,
                                       name=f"heartbeat-{job_id}",
                                       daemon=True)

    def __enter__(self):
        progress(self.job_id, self.claim_token, strict=True)
        self.thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            try:
                progress(self.job_id, self.claim_token, strict=True)
            except ClaimLostError:
                self.lost_event.set()
                return
            except Exception as exc:
                log(f"heartbeat delivery failed: {type(exc).__name__}")

    def ensure_owned(self) -> None:
        if self.lost_event.is_set():
            raise ClaimLostError("job claim was reassigned")


def decrypt_key(ct_b64: str, iv_b64: str) -> str:
    if not (ct_b64 and iv_b64 and KEK):
        raise RuntimeError("no key available for this user")
    return aes_gcm_decrypt(sha256(KEK.encode()).digest(),
                           base64.b64decode(iv_b64),
                           base64.b64decode(ct_b64)).decode()


# ------------------------------------------------------------ media I/O
def download(job_id: str, claim_token: str, r2_key: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    http_get(f"{API}/api/worker/media/{r2_key}", dst, token=TOKEN,
             headers={"x-autoeditor-job-id": job_id,
                      "x-autoeditor-claim-token": claim_token})
    return dst


def output_receipts(src: Path) -> tuple[str, list[str]]:
    whole = sha256()
    part_hashes: list[str] = []
    with src.open("rb") as handle:
        while chunk := handle.read(OUTPUT_PART_SIZE):
            whole.update(chunk)
            part_hashes.append(sha256(chunk).hexdigest())
    if not part_hashes:
        raise RuntimeError("engine produced an empty video")
    return whole.hexdigest(), part_hashes


def upload_output(job: dict, src: Path, heartbeat: ClaimHeartbeat) -> dict:
    claim_token = job["claim_token"]
    content_hash, part_hashes = output_receipts(src)
    start = api(f"/worker/jobs/{job['id']}/output/start", {
        "claim_token": claim_token,
        "size": src.stat().st_size,
        "content_sha256": content_hash,
        "part_hashes": part_hashes,
    })
    part_size = int(start.get("part_size") or 0)
    if part_size != OUTPUT_PART_SIZE:
        raise RuntimeError("Worker output part size does not match daemon")
    uploaded = set(start.get("uploaded_parts") or [])
    for index, part_hash in enumerate(part_hashes):
        heartbeat.ensure_owned()
        part_number = index + 1
        if part_number in uploaded:
            continue
        offset = index * OUTPUT_PART_SIZE
        length = min(OUTPUT_PART_SIZE, src.stat().st_size - offset)
        http_put_range(
            f"{API}/api/worker/jobs/{job['id']}/output/part?n={part_number}",
            src, offset, length, token=TOKEN,
            headers={"x-autoeditor-claim-token": claim_token,
                     "x-autoeditor-part-sha256": part_hash})
    heartbeat.ensure_owned()
    return api(f"/worker/jobs/{job['id']}/output/complete", {
        "claim_token": claim_token,
    })


def upload_qa(job: dict, qa_src: Path, output: dict,
              work: Path, heartbeat: ClaimHeartbeat) -> str:
    heartbeat.ensure_owned()
    report = json.loads(qa_src.read_text())
    report["_autoeditor"] = {
        "claim_token": job["claim_token"],
        "output_key": output["output_key"],
        "output_content_sha256": output["content_sha256"],
        "output_multipart_sha256": output["multipart_sha256"],
        "output_size": output["size"],
    }
    bound = work / "QA_REPORT_BOUND.json"
    bound.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")))
    digest = sha256(bound.read_bytes()).hexdigest()
    http_put(f"{API}/api/worker/jobs/{job['id']}/qa", bound, token=TOKEN,
             sha256_hex=digest,
             headers={"x-autoeditor-claim-token": job["claim_token"]})
    return str(output["qa_key"])


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
               claim_token: str, phase_status: dict) -> dict | None:
    """Run the engine, stream phases as progress, return the result event."""
    env = {**os.environ, **env_extra,
           "AUTOEDITOR_PACKAGED": "1", "AUTOEDITOR_PROGRESS_JSON": "1",
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    cmd = ([ENGINE_PATH, *args] if ENGINE_PATH
           else [*shlex.split(ENGINE), *args])
    proc = subprocess.Popen(cmd, cwd=INSTALL_ROOT, env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
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
        progress(job_id, claim_token, line=line[:300])
        for marker, status in phase_status.items():
            if marker in line:
                progress(job_id, claim_token, status=status)
    proc.wait()
    return result


PHASES_MAKE = {
    "phase 1": "transcribing", "phase 2": "transcribing",
    "phase 3": "transcribing", "phase 4p": "planning",
    "b-roll": "gathering resources", "caption": "rendering preview",
    "phase 6": "rendering preview", "QA": "running final qa",
}


def preset_params(preset: dict | None) -> dict:
    """Decode the user-owned preset or reject malformed/ambiguous input."""
    raw = (preset or {}).get("params_json") or "{}"
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("style preset parameters are not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("style preset parameters must be an object")
    return parsed


def handle_make(job, project, uploads, key, preset,
                heartbeat: ClaimHeartbeat, revision_id=None,
                engine_args_override=None) -> None:
    work = Path(tempfile.mkdtemp(prefix="webjob-", dir=str(WORK)))
    try:
        claim_token = job["claim_token"]
        progress(job["id"], claim_token, status="transcribing",
                 detail="preparing footage")
        clips = [download(job["id"], claim_token, u["r2_key"],
                          work / safe_local_upload_name(u["filename"], i))
                 for i, u in enumerate(uploads)]
        src = join_clips(clips, work)
        payload = json.loads(job.get("payload_json") or "{}")
        outdir = work / "out"
        script = payload.get("script")
        if not script:
            trdir = work / "tr"
            r = run_engine([str(src), "--transcribe-only", "--out",
                            str(trdir)], {}, job["id"], claim_token, {})
            tf = trdir / "TRANSCRIPT.txt"
            script = tf.read_text() if tf.exists() else ""
        script_file = work / "script.txt"
        script_file.write_text(script or " ")
        from webapp.render_worker.project_types import engine_args  # noqa
        mapped_args = (list(engine_args_override)
                       if engine_args_override is not None
                       else engine_args(project["type"],
                                        preset_params(preset)))
        args = [str(src), "--script", str(script_file), "--out",
                str(outdir), *mapped_args]
        env = {"DEEPSEEK_API_KEY": key} if key else {}
        if not key and "--no-premium" not in args:
            args += ["--no-llm"]
        result = run_engine(args, env, job["id"], claim_token, PHASES_MAKE)
        if not result and key and "--no-premium" not in args:
            # Spec rule: a failed planner/resource path must not destroy
            # the edit. Re-run once with the deterministic heuristic EDL.
            progress(job["id"], claim_token,
                     line="AI planner unavailable; using the "
                     "deterministic editor instead", status="planning",
                     detail="fallback edit plan")
            result = run_engine([*args, "--no-llm"], {}, job["id"], claim_token,
                                PHASES_MAKE)
        if not result:
            raise RuntimeError("engine produced no result event")
        out_path = next(iter(result["outputs"].values()))
        output = upload_output(job, Path(out_path), heartbeat)
        qa_report = Path(result["qa_report"])
        if not qa_report.exists():
            raise RuntimeError("engine produced no QA report")
        qa_key = upload_qa(job, qa_report, output, work, heartbeat)
        complete_job(job["id"], claim_token, {
            "ok": True,
            "output_key": output["output_key"], "qa_key": qa_key,
            "revision_id": revision_id,
            "transcript": (script or "")[:20000]})
    except ClaimLostError as e:
        log(f"job {job['id']} claim ended: {e}")
    except CompletionDeliveryError as e:
        log(f"job {job['id']} completion remains pending: {e}")
    except Exception as e:
        log(f"job {job['id']} failed: {type(e).__name__}")
        try:
            complete_job(job["id"], job["claim_token"],
                         {"ok": False,
                          "error": f"{type(e).__name__}: {e}"[:300]})
        except CompletionDeliveryError as completion_error:
            log(f"job {job['id']} failure receipt remains pending: "
                f"{completion_error}")
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
        complete_job(job["id"], job["claim_token"], {
            "ok": True, "proposal": {"operations": []},
            "request_text": request_text, "needs_approval": False,
            "summary": "I couldn't turn that into a safe edit. "
                       "Try rephrasing (e.g. 'make it vertical', "
                       "'use short pacing', or 'use sidecar captions')."})
        return
    complete_job(job["id"], job["claim_token"], {
        "ok": True, "proposal": clean, "request_text": request_text,
        "needs_approval": needs_approval,
        "summary": clean.get("summary") or "Here's what I'll change."})


def handle_revision(job, project, uploads, key, preset,
                    heartbeat: ClaimHeartbeat) -> None:
    payload = json.loads(job.get("payload_json") or "{}")
    rev_id = payload.get("revision_id")
    if not isinstance(rev_id, str) or not rev_id:
        raise RuntimeError("revision job has no bound revision id")

    proposal = payload.get("proposal")
    encoded = payload.get("proposal_json")
    if encoded is not None:
        if not isinstance(encoded, str):
            raise RuntimeError("approved proposal JSON must be a string")
        try:
            decoded = json.loads(encoded)
        except ValueError as exc:
            raise RuntimeError("approved proposal JSON is invalid") from exc
        if proposal is not None and proposal != decoded:
            raise RuntimeError("approved proposal representations disagree")
        proposal = decoded
    if not isinstance(proposal, dict):
        raise RuntimeError(
            "revision job does not include its Worker-bound approved proposal")

    from webapp.render_worker.project_types import revision_engine_args  # noqa
    mapped_args = revision_engine_args(
        project["type"], preset_params(preset), proposal)
    handle_make(job, project, uploads, key, preset, heartbeat,
                revision_id=rev_id, engine_args_override=mapped_args)


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
        claim_token = str(job.get("claim_token") or "")
        if not claim_token:
            log(f"job {job['id']} arrived without a claim token")
            time.sleep(2)
            continue
        key = ""
        try:
            if r.get("key_plain"):
                key = r["key_plain"]   # user-scoped helper: own key only
            elif r.get("key_ct"):
                key = decrypt_key(r["key_ct"], r["key_iv"])
        except Exception:
            try:
                complete_job(job["id"], claim_token,
                    {"ok": False, "error":
                     "stored key could not be unlocked; re-enter it in Settings"})
            except CompletionDeliveryError as e:
                log(f"job {job['id']} failure receipt remains pending: {e}")
            continue
        try:
            with ClaimHeartbeat(job["id"], claim_token) as heartbeat:
                if job["kind"] in ("make",):
                    handle_make(job, r["project"], r["uploads"], key,
                                r.get("preset"), heartbeat)
                elif job["kind"] == "chat_proposal":
                    handle_chat(job, r["project"], key)
                elif job["kind"] == "revision_apply":
                    handle_revision(job, r["project"], r["uploads"], key,
                                    r.get("preset"), heartbeat)
                else:
                    complete_job(job["id"], claim_token,
                        {"ok": False,
                         "error": f"unknown kind {job['kind']}"})
        except ClaimLostError as e:
            log(f"job {job['id']} claim ended: {e}")
        except CompletionDeliveryError as e:
            log(f"job {job['id']} completion remains pending: {e}")
        except Exception as e:
            log(f"job {job['id']} failed: {type(e).__name__}")
            try:
                complete_job(job["id"], claim_token,
                             {"ok": False,
                              "error": f"{type(e).__name__}: {e}"[:300]})
            except CompletionDeliveryError as completion_error:
                log(f"job {job['id']} failure receipt remains pending: "
                    f"{completion_error}")
        finally:
            key = ""  # drop plaintext reference promptly


if __name__ == "__main__":
    main()
