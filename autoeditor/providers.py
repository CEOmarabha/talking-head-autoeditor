"""Pluggable LLM + notification providers.

The pipeline never *requires* a model. Every LLM call has a deterministic
fallback, so the editor produces a finished video with zero API keys, you just
get fewer creative decisions (heuristic punch-ins instead of scripted ones) and
one fewer verification gate.

Configure with environment variables (or a .env file next to the repo root):

    DEEPSEEK_API_KEY=sk-xxx      # cheapest; ~1 cent per video
    OPENAI_API_KEY=sk-xxx        # or
    ANTHROPIC_API_KEY=sk-ant-xxx   # or
    LLM_MODEL=deepseek-chat        # optional override

    TELEGRAM_BOT_TOKEN=123:ABC     # optional: delivery to your phone
    TELEGRAM_CHAT_ID=123456789

Priority order is DeepSeek -> OpenAI -> Anthropic -> local `hermes` CLI (if you
happen to run one) -> None. `None` is a supported state, not an error.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

__all__ = ["llm_json", "llm_available", "notify", "send_video", "load_dotenv"]

_TIMEOUT_DEFAULT = 300


def load_dotenv(root: Path | None = None) -> None:
    """Populate os.environ from a .env file. Existing vars always win."""
    root = root or Path(__file__).resolve().parent.parent
    env = root / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict | None:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _provider() -> tuple[str, str, str] | None:
    """(name, api_key, model) for the first configured provider."""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return ("deepseek", os.environ["DEEPSEEK_API_KEY"],
                os.environ.get("LLM_MODEL", "deepseek-chat"))
    if os.environ.get("OPENAI_API_KEY"):
        return ("openai", os.environ["OPENAI_API_KEY"],
                os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ("anthropic", os.environ["ANTHROPIC_API_KEY"],
                os.environ.get("LLM_MODEL", "claude-sonnet-4-5"))
    if shutil.which("hermes"):
        return ("hermes", "", os.environ.get("LLM_MODEL", "deepseek-chat"))
    return None


def llm_available() -> bool:
    return _provider() is not None


def extract_json(text: str, require: tuple[str, ...] = ()) -> dict | None:
    """Pull the first BALANCED JSON object out of a model reply.

    Models wrap JSON in prose and code fences, and a greedy ``\\{.*\\}`` regex
    swallows trailing text and then fails to parse. That silently degraded
    this pipeline's whole creative layer until it was fixed. Scan for balanced
    braces instead, string-aware, and accept the first candidate that parses
    and carries the keys we asked for.
    """
    txt = re.sub(r"```(?:json)?|```", "", text or "")
    for start in (i for i, c in enumerate(txt) if c == "{"):
        depth, instr, esc = 0, False, False
        for i in range(start, len(txt)):
            c = txt[i]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
                continue
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        cand = json.loads(txt[start:i + 1])
                    except Exception:
                        cand = None
                    if isinstance(cand, dict) and (
                            not require or any(k in cand for k in require)):
                        return cand
                    break
    return None


def llm_json(prompt: str, require: tuple[str, ...] = (),
             timeout: int = _TIMEOUT_DEFAULT, attempts: int = 3) -> dict | None:
    """Ask the configured model for JSON. Returns None if unavailable/failed.

    Callers MUST treat None as normal and fall back to deterministic logic.

    Retries matter more than they look: a single dropped call used to collapse
    the whole creative layer to the heuristic fallback (1 b-roll instead of 12)
    and the only symptom was a thin-looking video. Transient timeouts are the
    common case, so we back off and try again before giving up.
    """
    for attempt in range(attempts):
        got = _llm_json_once(prompt, require,
                             timeout + attempt * (timeout // 2))
        if got is not None:
            return got
        if attempt + 1 < attempts:
            import time
            time.sleep(2 ** attempt)
    return None


def _llm_json_once(prompt: str, require: tuple[str, ...],
                   timeout: int) -> dict | None:
    prov = _provider()
    if prov is None:
        return None
    name, key, model = prov
    raw = ""
    if name == "hermes":
        try:
            p = subprocess.run(
                ["hermes", "chat", "-q", prompt, "-Q", "--max-turns", "1"],
                capture_output=True, timeout=timeout)
            raw = p.stdout.decode(errors="replace")
        except Exception:
            return None
    elif name == "anthropic":
        data = _post("https://api.anthropic.com/v1/messages",
                     {"model": model, "max_tokens": 8000,
                      "messages": [{"role": "user", "content": prompt}]},
                     {"x-api-key": key,
                      "anthropic-version": "2023-06-01"}, timeout)
        if not data:
            return None
        raw = "".join(b.get("text", "") for b in data.get("content", []))
    else:
        url = ("https://api.deepseek.com/chat/completions" if name == "deepseek"
               else "https://api.openai.com/v1/chat/completions")
        data = _post(url,
                     {"model": model, "messages": [
                         {"role": "user", "content": prompt}]},
                     {"Authorization": f"Bearer {key}"}, timeout)
        if not data:
            return None
        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return None
    return extract_json(raw, require)


# ------------------------------------------------------------------ delivery
def _tg() -> tuple[str, str] | None:
    tok, chat = (os.environ.get("TELEGRAM_BOT_TOKEN"),
                 os.environ.get("TELEGRAM_CHAT_ID"))
    return (tok, chat) if tok and chat else None


def notify(text: str) -> bool:
    """Send a text message. Silent no-op when Telegram isn't configured."""
    cfg = _tg()
    if not cfg:
        return False
    tok, chat = cfg
    return _post(f"https://api.telegram.org/bot{tok}/sendMessage",
                 {"chat_id": chat, "text": text}, {}, 60) is not None


def send_video(path: Path, caption: str = "",
               width: int = 0, height: int = 0) -> bool:
    """Upload a video file. Telegram bots cap uploads at 50 MB -- the caller is
    responsible for handing us a file under that (see `watch copy` in the
    pipeline). width/height matter: without them Telegram renders a square
    bubble instead of a proper landscape player."""
    cfg = _tg()
    if not cfg or not path.exists():
        return False
    tok, chat = cfg
    boundary = "----autoeditor-boundary"
    fields = {"chat_id": chat, "caption": caption[:1024],
              "supports_streaming": "true"}
    if width and height:
        fields.update(width=str(width), height=str(height))
    body = bytearray()
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="{k}"\r\n\r\n{v}\r\n').encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             f'name="video"; filename="{path.name}"\r\n'
             f"Content-Type: video/mp4\r\n\r\n").encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{tok}/sendVideo", data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception:
        return False
