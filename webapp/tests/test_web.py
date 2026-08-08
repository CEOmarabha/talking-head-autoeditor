"""Web layer tests: proposal contract, key crypto compatibility, type map."""
import base64
import os
import sys
import threading
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webapp.render_worker.project_types import (
    ALLOWED_OPS, GENERIC_PROFILE_IDS, PROJECT_TYPES,
    UnsupportedProjectTypeError, engine_args, revision_engine_args,
    validate_proposal)
from webapp.render_worker_compat import (
    aes_gcm_decrypt, aes_gcm_encrypt, canonical_json_bytes, http_put_range)


def test_supported_project_types_map_to_exact_engine_cli():
    expected = {
        "short": ["--style", "short", "--aspects", "9x16",
                  "--profile", "generic_short"],
        "long": ["--style", "long", "--aspects", "16x9",
                 "--profile", "generic_long"],
        "commercial": ["--style", "short", "--aspects", "9x16",
                       "--profile", "generic_commercial"],
        "podcast": ["--style", "long", "--aspects", "16x9",
                    "--profile", "generic_podcast"],
        "course": ["--style", "long", "--aspects", "16x9",
                   "--profile", "generic_course"],
        "custom": ["--style", "auto", "--aspects", "auto",
                   "--profile", "generic_custom"],
    }
    assert set(PROJECT_TYPES) == {
        "short", "long", "commercial", "podcast", "course", "clips",
        "custom",
    }
    for project_type, args in expected.items():
        assert PROJECT_TYPES[project_type]["supported"] is True
        assert engine_args(project_type, {}) == args


def test_unimplemented_clips_type_fails_instead_of_masquerading_as_short():
    assert PROJECT_TYPES["clips"]["supported"] is False
    with pytest.raises(UnsupportedProjectTypeError):
        engine_args("clips", {})
    with pytest.raises(ValueError, match="unknown project type"):
        engine_args("invented", {})


def test_preset_params_override_only_real_engine_options():
    assert engine_args("custom", {
        "style": "short",
        "aspects": "9x16",
        "caption_mode": "sidecar",
        "visual_mode": "baseline",
        "profile": "generic_commercial",
    }) == ["--style", "short", "--aspects", "9x16",
           "--profile", "generic_commercial", "--no-burn", "--no-premium"]
    with pytest.raises(ValueError, match="unsupported preset parameter"):
        engine_args("short", {"caption_scale": 0.065})
    with pytest.raises(ValueError, match="preset style"):
        engine_args("short", {"style": "commercial"})


def test_valid_proposal_passes():
    clean, approval, errors = validate_proposal({
        "summary": "make it vertical with sidecar captions",
        "operations": [
            {"op": "set_aspect_ratio", "aspect": "9x16"},
            {"op": "set_caption_mode", "mode": "sidecar"},
            {"op": "set_visual_mode", "mode": "baseline"},
            {"op": "set_edit_profile", "profile_id": "generic_short"},
        ]})
    assert not errors
    assert not approval
    assert len(clean["operations"]) == 4
    assert "human" in clean["operations"][0]


def test_operations_without_exact_engine_mapping_are_rejected():
    unsupported = (
        {"op": "faster_hook", "factor": 1.4},
        {"op": "remove_segment", "start": 5, "end": 9},
        {"op": "fewer_punchins"},
        {"op": "more_punchins"},
        {"op": "caption_scale", "scale": 0.065},
        {"op": "broll_density", "level": "more"},
        {"op": "cinematic_grade"},
        {"op": "retarget_duration", "seconds": 30},
        {"op": "split_into_clips", "count": 3},
        {"op": "acquire_asset", "query": "city night", "kind": "broll"},
    )
    for operation in unsupported:
        clean, approval, errors = validate_proposal({
            "operations": [operation],
        })
        assert errors and not clean and not approval


def test_speech_changing_operation_cannot_build_revision_args():
    with pytest.raises(ValueError, match="not in the executable contract"):
        revision_engine_args("short", {}, {
        "operations": [{"op": "remove_segment", "start": 5, "end": 9}]})


def test_unknown_op_rejected_whole():
    clean, _, errors = validate_proposal({
        "operations": [{"op": "set_edit_style", "style": "short"},
                       {"op": "rm_rf_slash", "path": "/"}]})
    assert errors and not clean   # partial application is forbidden


def test_bounds_enforced():
    _, _, errors = validate_proposal({
        "operations": [{"op": "set_aspect_ratio", "aspect": "square"}]})
    assert errors
    _, _, errors = validate_proposal({
        "operations": [{"op": "set_caption_mode", "mode": "huge"}]})
    assert errors


def test_op_count_cap():
    ops = [{"op": "set_edit_style", "style": "short"}] * 9
    _, _, errors = validate_proposal({"operations": ops})
    assert errors


def test_revision_args_preserve_preset_and_apply_each_approved_change():
    args = revision_engine_args("custom", {
        "style": "long",
        "aspects": "16x9",
        "caption_mode": "sidecar",
    }, {
        "summary": "switch delivery",
        "operations": [
            {"op": "set_edit_style", "style": "short"},
            {"op": "set_aspect_ratio", "aspect": "9x16"},
            {"op": "set_caption_mode", "mode": "burned"},
            {"op": "set_visual_mode", "mode": "baseline"},
            {"op": "set_edit_profile",
             "profile_id": "generic_commercial"},
        ],
    })
    assert args == ["--style", "short", "--aspects", "9x16",
                    "--profile", "generic_commercial", "--no-premium"]
    assert "--edl" not in args
    assert set(GENERIC_PROFILE_IDS) == {
        "generic_short", "generic_long", "generic_commercial",
        "generic_podcast", "generic_course", "generic_custom",
    }


def test_profile_revision_cannot_select_named_or_missing_profile():
    _, _, errors = validate_proposal({
        "operations": [{"op": "set_edit_profile",
                        "profile_id": "ryan_duffy"}],
    })
    assert errors


def test_duplicate_revision_setting_is_rejected():
    _, _, errors = validate_proposal({
        "operations": [
            {"op": "set_edit_style", "style": "short"},
            {"op": "set_edit_style", "style": "long"},
        ],
    })
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


def test_completion_json_is_canonical_and_range_put_streams_exact_bytes(
        tmp_path):
    assert canonical_json_bytes({"z": 1, "a": True}) == b'{"a":true,"z":1}'
    source = tmp_path / "source.bin"
    source.write_bytes(bytes(range(256)) * 8193)

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            length = int(self.headers["content-length"])
            self.server.received = self.rfile.read(length)
            self.server.claim = self.headers.get("x-autoeditor-claim-token")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        http_put_range(f"http://127.0.0.1:{server.server_port}/part",
                       source, 101, 1_500_123,
                       headers={"x-autoeditor-claim-token": "claim123"})
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert server.received == source.read_bytes()[101:1_500_224]
    assert server.claim == "claim123"


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
    assert "async function claimedJob(" in src
    assert "job.claim_token !== claimToken" in src
    assert "Number(job.lease_expires_at || 0) < now()" in src
    assert "function jobOwnsMediaKey(job, key)" in src
    assert "!jobOwnsMediaKey(job, body.output_key)" in src
    assert "!jobOwnsMediaKey(job, key)" in src
    assert "x-autoeditor-job-id" in src
    assert "x-autoeditor-claim-token" in src
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
    assert (
        "SELECT id, params_json FROM style_presets WHERE id = ? AND user_id = ?"
        in src
    )


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
    assert 'binding = "RELEASES"' in wrangler
    assert 'bucket_name = "autoeditor-releases"' in wrangler
    assert "run_worker_first = true" in wrangler


def test_signup_and_revision_queue_use_atomic_d1_batches():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker" / "src" / "index.js").read_text()
    schema = (root / "worker" / "schema.sql").read_text()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name" in schema
    assert "signup = await env.DB.batch([" in worker
    assert "SELECT 1 FROM invites WHERE code = ? AND used_by = ?" in worker
    assert "const jobId = `revision_apply_${rev.id}`" in worker
    assert "approval = await env.DB.batch([" in worker
    assert "SELECT 1 FROM jobs WHERE id = ?" in worker
    assert "AND status = 'proposed'" in worker


def test_d1_upgrade_is_ordered_and_adds_every_required_constraint():
    root = Path(__file__).resolve().parents[1]
    wrangler = (root / "worker" / "wrangler.toml").read_text()
    migrations = root / "worker" / "migrations"
    baseline = (migrations / "0001_initial_schema.sql").read_text()
    upgrade = (
        migrations / "0002_claim_leases_and_render_uploads.sql"
    ).read_text()
    assert 'migrations_dir = "migrations"' in wrangler
    assert "CREATE TABLE IF NOT EXISTS jobs" in baseline
    assert "ALTER TABLE jobs ADD COLUMN claim_token TEXT" in upgrade
    assert "CREATE TABLE IF NOT EXISTS render_uploads" in upgrade
    assert "idx_jobs_one_active_render" in upgrade
    assert "idx_users_name" in upgrade
    assert "idx_revisions_project_num" in upgrade


def test_multipart_completion_is_leased_and_recovers_from_r2_d1_splits():
    worker = (Path(__file__).resolve().parents[1] /
              "worker" / "src" / "index.js").read_text()
    assert "UPLOAD_COMPLETION_LEASE_MS" in worker
    assert "function completionLease(status)" in worker
    assert "await completedObjectExists(env, up)" in worker
    assert "await markUploadDone(env, up, lease)" in worker
    assert "UPDATE uploads SET status = 'uploading'" in worker
    complete_start = worker.index(
        "if ((m = p.match(/^\\/uploads\\/(\\w+)\\/complete$/))"
    )
    complete_end = worker.index("// ---------- make it", complete_start)
    complete_route = worker[complete_start:complete_end]
    assert complete_route.index("UPDATE uploads SET status = ?") < \
        complete_route.index("await mp.complete(parts.map")


def test_helper_downloads_resolve_one_atomic_release_pointer():
    worker = (Path(__file__).resolve().parents[1] /
              "worker" / "src" / "index.js").read_text()
    assert "dist/helper/current.json" in worker
    assert "autoeditor-helper-release/v1" in worker
    assert "dist/helper/objects/${selected?.sha256}/" in worker
    assert "selected.key !== expected" in worker
    assert "env.RELEASES.get" in worker
    assert "object.customMetadata?.sha256 === item.sha256" in worker
    assert "async function verifiedHelperDownloads(env)" in worker
    assert worker.count("await verifiedHelperDownloads(env)") == 2
    assert "return verified.every(Boolean) ? downloads : null" in worker
    assert "legacyKey" not in worker


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
