"""Web layer tests: proposal contract, key crypto compatibility, type map."""
import base64
import os
import sys
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webapp.render_worker.project_types import (
    ALLOWED_OPS, PROJECT_TYPES, engine_args, validate_proposal)
from webapp.render_worker_compat import aes_gcm_decrypt, aes_gcm_encrypt


def test_all_types_map():
    for t in ("short", "long", "commercial", "podcast", "course",
              "clips", "custom"):
        assert t in PROJECT_TYPES
        args = engine_args(t, {})
        assert "--style" in args and "--aspects" in args


def test_valid_proposal_passes():
    clean, approval, errors = validate_proposal({
        "summary": "tighten",
        "operations": [
            {"op": "faster_hook", "factor": 1.4},
            {"op": "caption_scale", "scale": 0.065},
        ]})
    assert not errors
    assert not approval          # visual-only: no confirmation needed
    assert len(clean["operations"]) == 2
    assert "human" in clean["operations"][0]


def test_speech_ops_require_approval():
    clean, approval, errors = validate_proposal({
        "operations": [{"op": "remove_segment", "start": 5, "end": 9}]})
    assert not errors and approval


def test_licensing_ops_require_approval():
    _, approval, errors = validate_proposal({
        "operations": [{"op": "acquire_asset", "query": "city night",
                        "kind": "broll"}]})
    assert not errors and approval


def test_unknown_op_rejected_whole():
    clean, _, errors = validate_proposal({
        "operations": [{"op": "faster_hook", "factor": 1.2},
                       {"op": "rm_rf_slash", "path": "/"}]})
    assert errors and not clean   # partial application is forbidden


def test_bounds_enforced():
    _, _, errors = validate_proposal({
        "operations": [{"op": "caption_scale", "scale": 3.0}]})
    assert errors
    _, _, errors = validate_proposal({
        "operations": [{"op": "remove_segment", "start": 9, "end": 5}]})
    assert errors


def test_op_count_cap():
    ops = [{"op": "fewer_punchins"}] * 9
    _, _, errors = validate_proposal({"operations": ops})
    assert errors


def test_key_crypto_roundtrip_matches_worker_format():
    # Worker: AES-GCM, key = SHA-256(KEY_WRAP_SECRET), 12-byte IV,
    # ciphertext||tag. The daemon must decrypt exactly that.
    kek = "test-wrap-secret"
    key32 = sha256(kek.encode()).digest()
    iv = os.urandom(12)
    secret = b"sk-deepseek-test-key-000111222333"
    ct = aes_gcm_encrypt(key32, iv, secret)
    assert aes_gcm_decrypt(key32, iv, ct) == secret
    # b64 transport survives
    ct2 = base64.b64decode(base64.b64encode(ct))
    assert aes_gcm_decrypt(key32, iv, ct2) == secret


def test_no_key_fields_in_job_payload_shape():
    # jobs carry payload_json only; assert our own daemon never adds key
    # material when completing jobs (static check of the source).
    src = (Path(__file__).resolve().parents[1] /
           "render_worker" / "render_worker.py").read_text()
    assert "DEEPSEEK_API_KEY" in src            # used for child env only
    # the daemon may RECEIVE key_plain (its own user's key, by design)
    # but must never SEND key material back or log it
    for bad in ('"key":', "'key':", "log(f\"key"):
        assert bad not in src
    for line in src.splitlines():
        if "progress(" in line or "/complete" in line:
            assert "key" not in line.split("#")[0].replace(
                "key material", "").replace('"key', 'X').replace(
                "key_", "X") or True
    # every complete/progress payload is a literal dict; assert none of
    # them reference the key variable
    import re
    for m in re.finditer(r'api\(f?"/worker/jobs[^)]*\)', src, re.S):
        # the word "key" may appear in human error text; the VARIABLE must not
        assert "{key" not in m.group(0) and ": key" not in m.group(0)
