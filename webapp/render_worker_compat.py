"""Small stdlib-plus-cryptography helpers shared by the render daemon.

Kept separate so the daemon file stays readable and the crypto is testable
against the Worker's WebCrypto output.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from hashlib import sha256
from pathlib import Path
from typing import Mapping

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "pip install cryptography  (required by the render worker)") from e


def aes_gcm_decrypt(key32: bytes, iv: bytes, ct_and_tag: bytes) -> bytes:
    """Decrypt WebCrypto AES-GCM output (ciphertext||tag, 12-byte IV)."""
    return AESGCM(key32).decrypt(iv, ct_and_tag, None)


def aes_gcm_encrypt(key32: bytes, iv: bytes, plaintext: bytes) -> bytes:
    return AESGCM(key32).encrypt(iv, plaintext, None)


def http_json(url: str, payload: dict | None, token: str = "",
              timeout: int = 60) -> dict:
    data = canonical_json_bytes(payload or {})
    req = urllib.request.Request(url, data=data, headers={
        "content-type": "application/json",
        **({"authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def canonical_json_bytes(payload: dict) -> bytes:
    """Stable request bytes used by the Worker's completion receipt."""
    return json.dumps(payload, sort_keys=True,
                      separators=(",", ":")).encode()


_WINDOWS_RESERVED_STEMS = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def safe_local_upload_name(filename: object, index: int) -> str:
    """Return a short collision-safe filename valid on Windows and macOS."""
    raw = str(filename or "upload")
    normalized = unicodedata.normalize("NFKC", raw)
    cleaned = "".join(
        "_" if (
            char in '<>:"/\\|?*'
            or ord(char) < 32
            or unicodedata.category(char).startswith("C")
        ) else char
        for char in normalized
    ).strip(" .")
    cleaned = re.sub(r"_+", "_", cleaned) or "upload"
    suffix = Path(cleaned).suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
        suffix = ""
    stem = cleaned[:-len(suffix)] if suffix else cleaned
    stem = stem.strip(" .") or "upload"
    if stem.casefold() in _WINDOWS_RESERVED_STEMS:
        stem = f"_{stem}"
    source_digest = sha256(
        raw.encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:10]
    prefix = f"in{index:04d}_{source_digest}_"
    # Keep the local component comfortably below legacy MAX_PATH after the
    # temporary working directory is added. The stable index and digest make
    # truncation collision-safe.
    room = 120 - len(prefix) - len(suffix)
    truncated = []
    used_units = 0
    for char in stem:
        units = len(char.encode("utf-16-le", errors="surrogatepass")) // 2
        if used_units + units > max(room, 1):
            break
        truncated.append(char)
        used_units += units
    stem = "".join(truncated).rstrip(" .") or "upload"
    return f"{prefix}{stem}{suffix}"


def http_get(url: str, dst: Path, token: str = "",
             timeout: int = 600,
             headers: Mapping[str, str] | None = None) -> None:
    req = urllib.request.Request(url, headers={
        **({"authorization": f"Bearer {token}"} if token else {}),
        **dict(headers or {}),
    })
    with urllib.request.urlopen(req, timeout=timeout) as r, \
            open(dst, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def http_put(url: str, src: Path, token: str = "", sha256_hex: str = "",
             timeout: int = 1800,
             headers: Mapping[str, str] | None = None) -> None:
    def chunks():
        with open(src, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk

    headers = {
        **({"authorization": f"Bearer {token}"} if token else {}),
        **({"x-autoeditor-sha256": sha256_hex} if sha256_hex else {}),
        **dict(headers or {}),
        "content-length": str(src.stat().st_size),
    }
    req = urllib.request.Request(url, data=chunks(), method="PUT",
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def http_put_range(url: str, src: Path, offset: int, length: int,
                   token: str = "", timeout: int = 1800,
                   headers: Mapping[str, str] | None = None) -> None:
    """Stream exactly one bounded multipart range without loading it in RAM."""
    if offset < 0 or length <= 0 or offset + length > src.stat().st_size:
        raise ValueError("invalid file range")

    def chunks():
        remaining = length
        with open(src, "rb") as handle:
            handle.seek(offset)
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise OSError("source file ended during multipart upload")
                remaining -= len(chunk)
                yield chunk

    request_headers = {
        **({"authorization": f"Bearer {token}"} if token else {}),
        **dict(headers or {}),
        "content-length": str(length),
    }
    req = urllib.request.Request(url, data=chunks(), method="PUT",
                                 headers=request_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        response.read()
