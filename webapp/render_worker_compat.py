"""Small stdlib-plus-cryptography helpers shared by the render daemon.

Kept separate so the daemon file stays readable and the crypto is testable
against the Worker's WebCrypto output.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

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
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "content-type": "application/json",
        **({"authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def http_get(url: str, dst: Path, token: str = "",
             timeout: int = 600) -> None:
    req = urllib.request.Request(url, headers={
        "authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=timeout) as r, \
            open(dst, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def http_put(url: str, src: Path, token: str = "",
             timeout: int = 1800) -> None:
    with open(src, "rb") as f:
        data = f.read()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()
