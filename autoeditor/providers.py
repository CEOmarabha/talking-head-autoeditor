"""LLM and notification providers.

DeepSeek is an untrusted planner. Callers define the JSON contract and perform
their own semantic validation after this transport layer verifies that the
response is complete JSON. A model failure never becomes a successful
"DeepSeek" result through an unnamed fallback.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

__all__ = [
    "DEEPSEEK_MODELS",
    "DEFAULT_DEEPSEEK_MODEL",
    "ProviderConfigurationError",
    "extract_json",
    "llm_json",
    "llm_available",
    "notify",
    "send_video",
    "load_dotenv",
]

_TIMEOUT_DEFAULT = 300
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEEPSEEK_MODELS = frozenset({"deepseek-v4-pro", "deepseek-v4-flash"})
_RETIRED_DEEPSEEK_MODELS = frozenset({"deepseek-chat", "deepseek-reasoner"})


class ProviderConfigurationError(RuntimeError):
    """A configured provider cannot satisfy the requested model contract."""


def load_dotenv(root: Path | None = None) -> None:
    """Load project settings, then the existing Hermes DeepSeek bridge.

    Existing environment variables always win. The Hermes file is limited to
    keys this program owns; unrelated credentials are never imported.
    """
    if os.environ.get("AUTOEDITOR_PACKAGED"):
        # Desktop builds receive credentials from the shell's OS keystore via
        # the child environment ONLY. No dotfiles are read and none are
        # written, so a key can never end up in .env, logs, or diagnostics.
        return
    root = root or Path(__file__).resolve().parent.parent
    allowed = {
        "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL",
        "LLM_MODEL",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "PEXELS_API_KEY", "PIXABAY_API_KEY", "ELEVENLABS_API_KEY",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
        "TELEGRAM_HOME_CHANNEL", "CLIP_CATALOGS",
    }
    for env in (root / ".env", Path.home() / ".hermes" / ".env"):
        if not env.exists():
            continue
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in allowed:
                os.environ.setdefault(
                    key, value.strip().strip("'\"")
                )


def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict | None:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers})
    deadline = time.monotonic() + max(float(timeout), 0.001)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = bytearray()
            read_chunk = getattr(r, "read1", r.read)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    r.fp.raw._sock.settimeout(remaining)
                except (AttributeError, OSError):
                    pass
                chunk = read_chunk(65536)
                if not chunk:
                    break
                body.extend(chunk)
            return json.loads(body.decode())
    except urllib.error.HTTPError as exc:
        return {"_transport_error": f"http_{exc.code}"}
    except urllib.error.URLError:
        return {"_transport_error": "url_error"}
    except TimeoutError:
        return {"_transport_error": "timeout"}
    except http.client.IncompleteRead:
        return {"_transport_error": "incomplete_read"}
    except http.client.HTTPException:
        return {"_transport_error": "http_protocol_error"}
    except json.JSONDecodeError:
        return {"_transport_error": "non_json_response"}
    except OSError:
        return {"_transport_error": "os_error"}


def _deepseek_model(model: str | None = None) -> str:
    selected = (
        model
        or os.environ.get("DEEPSEEK_MODEL")
        or DEFAULT_DEEPSEEK_MODEL
    )
    if selected in _RETIRED_DEEPSEEK_MODELS:
        raise ProviderConfigurationError(
            f"DeepSeek model {selected!r} was retired; use "
            f"{DEFAULT_DEEPSEEK_MODEL!r}"
        )
    if selected not in DEEPSEEK_MODELS:
        raise ProviderConfigurationError(
            f"unsupported DeepSeek model {selected!r}; allowed: "
            + ", ".join(sorted(DEEPSEEK_MODELS))
        )
    return selected


def _provider(preferred: str | None = None,
              model: str | None = None) -> tuple[str, str, str] | None:
    """Return ``(name, api_key, model)`` for the requested provider."""
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if preferred == "deepseek":
        return (
            ("deepseek", deepseek_key, _deepseek_model(model))
            if deepseek_key else None
        )
    if deepseek_key:
        return ("deepseek", deepseek_key, _deepseek_model(model))
    if os.environ.get("OPENAI_API_KEY"):
        return ("openai", os.environ["OPENAI_API_KEY"],
                model or os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ("anthropic", os.environ["ANTHROPIC_API_KEY"],
                model or os.environ.get("LLM_MODEL", "claude-sonnet-4-5"))
    if shutil.which("hermes"):
        return ("hermes", "", model or DEFAULT_DEEPSEEK_MODEL)
    return None


def llm_available(provider: str | None = None) -> bool:
    return _provider(provider) is not None


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
                            not require or all(k in cand for k in require)):
                        return cand
                    break
    return None


def llm_json(prompt: str, require: tuple[str, ...] = (),
             timeout: int = _TIMEOUT_DEFAULT, attempts: int = 3,
             *, provider: str | None = None, model: str | None = None,
             system: str = "", max_tokens: int = 32768,
             reasoning_effort: str = "max",
             validator: Callable[[dict], bool] | None = None,
             purpose: str = "json_task",
             receipt: dict | None = None) -> dict | None:
    """Ask a model for complete JSON and record a safe execution receipt."""
    record = receipt if receipt is not None else {}
    record.clear()
    record.update({
        "purpose": purpose,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "attempts": [],
        "ok": False,
    })
    for attempt in range(attempts):
        got = _llm_json_once(
            prompt, require, timeout + attempt * (timeout // 2),
            provider=provider, model=model, system=system,
            max_tokens=max_tokens, reasoning_effort=reasoning_effort,
            receipt=record,
        )
        if got is not None and validator is not None:
            try:
                if not validator(got):
                    record["attempts"][-1]["result"] = "validator_rejected"
                    got = None
            except Exception as exc:
                record["attempts"][-1]["result"] = (
                    f"validator_error:{type(exc).__name__}"
                )
                got = None
        if got is not None:
            record["ok"] = True
            return got
        result = str(record["attempts"][-1].get("result", ""))
        status_match = re.fullmatch(r"http_(\d{3})", result)
        if (status_match
                and 400 <= int(status_match.group(1)) < 500
                and int(status_match.group(1)) not in {408, 429}):
            break
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    return None


def _llm_json_once(prompt: str, require: tuple[str, ...],
                   timeout: int, *, provider: str | None = None,
                   model: str | None = None, system: str = "",
                   max_tokens: int = 32768,
                   reasoning_effort: str = "max",
                   receipt: dict | None = None) -> dict | None:
    prov = _provider(provider, model)
    if prov is None:
        if receipt is not None:
            receipt["attempts"].append({"result": "provider_unavailable"})
        return None
    name, key, model = prov
    if receipt is not None:
        receipt.update({
            "provider": name,
            "model": model,
            "reasoning_effort": (
                reasoning_effort if name == "deepseek" else "provider_default"
            ),
            "json_mode": name == "deepseek",
        })
    attempt_receipt = {"result": "started"}
    if receipt is not None:
        receipt["attempts"].append(attempt_receipt)
    raw = ""
    if name == "hermes":
        try:
            query = f"{system}\n\n{prompt}" if system else prompt
            p = subprocess.run(
                ["hermes", "chat", "-q", query, "-Q", "--max-turns", "1"],
                capture_output=True, timeout=timeout)
            if p.returncode:
                attempt_receipt["result"] = f"exit_{p.returncode}"
                return None
            raw = p.stdout.decode(errors="replace")
        except Exception:
            attempt_receipt["result"] = "hermes_error"
            return None
    elif name == "anthropic":
        messages = [{"role": "user", "content": prompt}]
        payload = {"model": model, "max_tokens": max_tokens,
                   "messages": messages}
        if system:
            payload["system"] = system
        data = _post("https://api.anthropic.com/v1/messages",
                     payload,
                     {"x-api-key": key,
                      "anthropic-version": "2023-06-01"}, timeout)
        if not data or data.get("_transport_error"):
            attempt_receipt["result"] = (
                data.get("_transport_error", "empty_response")
                if data else "empty_response"
            )
            return None
        if data.get("stop_reason") not in (None, "end_turn", "stop_sequence"):
            attempt_receipt["result"] = (
                f"finish_{data.get('stop_reason', 'unknown')}"
            )
            return None
        raw = "".join(b.get("text", "") for b in data.get("content", []))
    else:
        url = ("https://api.deepseek.com/chat/completions" if name == "deepseek"
               else "https://api.openai.com/v1/chat/completions")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages,
                   "max_tokens": max_tokens}
        if name == "deepseek":
            payload.update({
                "response_format": {"type": "json_object"},
                "thinking": {"type": "enabled"},
                "reasoning_effort": reasoning_effort,
            })
        data = _post(url,
                     payload,
                     {"Authorization": f"Bearer {key}"}, timeout)
        if not data or data.get("_transport_error"):
            attempt_receipt["result"] = (
                data.get("_transport_error", "empty_response")
                if data else "empty_response"
            )
            return None
        try:
            choice = data["choices"][0]
            finish = choice.get("finish_reason")
            attempt_receipt["finish_reason"] = finish
            if finish != "stop":
                attempt_receipt["result"] = f"finish_{finish or 'missing'}"
                return None
            raw = choice["message"]["content"] or ""
            if data.get("system_fingerprint"):
                attempt_receipt["system_fingerprint"] = (
                    data["system_fingerprint"]
                )
        except (KeyError, IndexError):
            attempt_receipt["result"] = "malformed_response"
            return None
    if not raw.strip():
        attempt_receipt["result"] = "empty_content"
        return None
    parsed = extract_json(raw, require)
    attempt_receipt["result"] = "json_ok" if parsed is not None else "json_invalid"
    return parsed


# ------------------------------------------------------------------ delivery
def _tg() -> tuple[str, str] | None:
    tok, chat = (os.environ.get("TELEGRAM_BOT_TOKEN"),
                 (os.environ.get("TELEGRAM_CHAT_ID")
                  or os.environ.get("TELEGRAM_HOME_CHANNEL")))
    return (tok, chat) if tok and chat else None


def notify(text: str) -> bool:
    """Send a text message. Silent no-op when Telegram isn't configured."""
    cfg = _tg()
    if not cfg:
        return False
    tok, chat = cfg
    result = _post(
        f"https://api.telegram.org/bot{tok}/sendMessage",
        {"chat_id": chat, "text": text}, {}, 60
    )
    return bool(result and not result.get("_transport_error")
                and result.get("ok", True))


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
