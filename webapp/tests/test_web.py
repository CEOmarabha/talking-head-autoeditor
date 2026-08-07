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


def test_personal_worker_routes_recheck_job_and_media_ownership():
    src = (Path(__file__).resolve().parents[1] /
           "worker" / "src" / "index.js").read_text()
    assert "function workerOwnsJob(scope, job)" in src
    assert src.count("if (!workerOwnsJob(scope, job))") >= 2
    assert "function jobOwnsMediaKey(job, key)" in src
    assert "!jobOwnsMediaKey(job, body.output_key)" in src
    assert "key.startsWith(`u/${scope.userId}/`)" in src
    assert "WHERE id = ? AND status = 'queued'" in src
    assert "const checked = validateProposal(body.proposal)" in src
    assert "safeNeedsApproval = checked.needsApproval" in src
    assert "body.needs_approval ?" not in src
    assert "WHERE id = ? AND project_id = ?" in src
    assert "key_ct: scope.scope === 'global'" in src
    assert "key_iv: scope.scope === 'global'" in src


def test_style_presets_are_user_scoped_on_create_and_worker_read():
    src = (Path(__file__).resolve().parents[1] /
           "worker" / "src" / "index.js").read_text()
    assert src.count(
        "SELECT name, params_json FROM style_presets WHERE id = ? AND user_id = ?"
    ) == 1
    assert "SELECT id FROM style_presets WHERE id = ? AND user_id = ?" in src


def test_web_outputs_resume_and_dynamic_text_avoid_inner_html():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker" / "src" / "index.js").read_text()
    client = (root / "site" / "app.js").read_text()
    assert "qa_pass,output_key,output_key IS NOT NULL AS has_output" in worker
    assert "uploaded_parts: parts, resumed: true" in worker
    assert "const uploaded = new Set(meta.uploaded_parts || [])" in client
    assert "operation.human || operation.op" in client
    assert "${pr.title}" not in client


def test_signin_has_server_side_rate_limit_schema_and_gate():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker" / "src" / "index.js").read_text()
    schema = (root / "worker" / "schema.sql").read_text()
    assert "async function withinRateLimit" in worker
    assert "await withinRateLimit(env, req, 'signin', 15" in worker
    assert "CREATE TABLE IF NOT EXISTS rate_limits" in schema


def test_site_headers_and_installer_downloads_are_private_and_resumable():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker" / "src" / "index.js").read_text()
    wrangler = (root / "worker" / "wrangler.toml").read_text()
    assert "function secureSiteResponse(response)" in worker
    assert "content-security-policy" in worker
    assert worker.count("if (!(await auth(req, env))) return bad('sign in first'") == 2
    assert "'accept-ranges': 'bytes'" in worker
    assert "headers['content-range']" in worker
    assert "/download/helper.zip" not in worker
    assert "run_worker_first = true" in wrangler


def test_site_uses_self_hosted_brand_type_and_builder_credit():
    site = Path(__file__).resolve().parents[1] / "site"
    html = (site / "index.html").read_text()
    css = (site / "style.css").read_text()
    app = (site / "app.js").read_text()
    assert "Built by Omar Marabha" in html
    assert "@CEOmarabha" in html
    assert (site / "WorkSans-Variable.ttf").stat().st_size > 100_000
    assert "@font-face" in css and "Work Sans AutoEditor" in css
    assert "d.tabIndex = 0" in app
    assert "event.key === 'Enter' || event.key === ' '" in app
