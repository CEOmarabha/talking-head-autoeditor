from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from autoeditor_law import (
    ArchiveContractError,
    ContractError,
    UnsupportedSchemaError,
    canonical_sha256,
    load_registry,
    validate_edit_intent,
    validate_planner_proposal,
    validate_receipt_envelope,
    validate_render_request,
    verify_archive,
)
from autoeditor_law.contracts import (
    ARCHIVE_MANIFEST_SCHEMA_ID,
    CONTRACT_ID,
    EDIT_INTENT_SCHEMA_ID,
    PLANNER_PROPOSAL_SCHEMA_ID,
    RECEIPT_ENVELOPE_SCHEMA_ID,
    RENDER_REQUEST_SCHEMA_ID,
)


REPO = Path(__file__).resolve().parents[1]
SHA = "1" * 64


def edit_intent() -> dict:
    return {
        "schema_id": EDIT_INTENT_SCHEMA_ID,
        "timeline_grid": {
            "unit": "tick",
            "ticks_per_second": {"numerator": 30_000, "denominator": 1001},
        },
        "transcript_sha256": "2" * 64,
        "events": [
            {
                "event_id": "opening-punch",
                "layer": "punch_in",
                "anchor_quote": "Around Philly this is permanent law",
                "duration_ticks": 90,
                "parameters": {
                    "scale_milli": 1120,
                    "reason": "open on the protected spoken claim",
                },
            }
        ],
    }


def planner_proposal() -> dict:
    intent = edit_intent()
    return {
        "schema_id": PLANNER_PROPOSAL_SCHEMA_ID,
        "proposal_id": "proposal-2026-001",
        "created_at": "2026-08-13T12:00:00Z",
        "planner": {
            "adapter_id": "deepseek-v4-adapter",
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "model_revision": "2026-08-13",
        },
        "inputs": {
            "transcript_sha256": "2" * 64,
            "project_intent_sha256": "3" * 64,
            "profile_sha256": "4" * 64,
        },
        "proposal": {
            "payload_schema_id": EDIT_INTENT_SCHEMA_ID,
            "contract_sha256": "5" * 64,
            "payload_sha256": canonical_sha256(intent),
            "payload": intent,
        },
        "qualification": {
            "suite_id": "urn:autoeditor:qualification:planner-incidents-2026",
            "suite_sha256": "6" * 64,
            "adapter_sha256": "7" * 64,
            "pass": True,
        },
    }


def render_request() -> dict:
    return {
        "schema_id": RENDER_REQUEST_SCHEMA_ID,
        "request_id": "render-2026-001",
        "created_at": "2026-08-13T12:01:00Z",
        "render_adapter_id": "urn:autoeditor:adapter:ffmpeg-render-1",
        "archive_manifest_sha256": "1" * 64,
        "planner_proposal_sha256": "2" * 64,
        "edl_sha256": "3" * 64,
        "source_map_sha256": "4" * 64,
        "render_profile_sha256": "5" * 64,
        "policy_id": "urn:autoeditor:policy:lesson-2026-1",
        "toolchain": {
            "renderer_sha256": "6" * 64,
            "ffmpeg_sha256": "7" * 64,
            "ffprobe_sha256": "8" * 64,
        },
    }


def receipt_envelope() -> dict:
    return {
        "schema_id": RECEIPT_ENVELOPE_SCHEMA_ID,
        "receipt_id": "receipt-2026-001",
        "created_at": "2026-08-13T12:02:00Z",
        "subject_digest": {"algorithm": "sha256", "value": "1" * 64},
        "capability_id": "urn:autoeditor:capability:deterministic.av-sync",
        "check_id": "urn:autoeditor:check:av-sync",
        "algorithm_id": "urn:autoeditor:algorithm:raw-av-sync-2",
        "payload_schema_id": ARCHIVE_MANIFEST_SCHEMA_ID,
        "policy_id": "urn:autoeditor:policy:lesson-2026-1",
        "artifact_contract_id": "urn:autoeditor:artifact-contract:master-mp4-1",
        "result": "pass",
        "evidence": [
            {
                "path": "evidence/sync-probe.json",
                "digest": {"algorithm": "sha256", "value": "2" * 64},
            }
        ],
        "producer": {
            "name": "autoeditor-law",
            "version": "1.0.0",
            "source_sha256": "3" * 64,
        },
        "payload": {"measured_ms": 0, "pass": True},
    }


def write_archive(root: Path, roles: dict[str, bytes], grade: str) -> dict:
    files = []
    for index, (role, payload) in enumerate(roles.items()):
        relative = (
            "output/master.mp4" if role == "master"
            else f"evidence/{index:02d}-{role}.bin"
        )
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        files.append({
            "path": relative,
            "role": role,
            "bytes": len(payload),
            "digest": {
                "algorithm": "sha256",
                "value": hashlib.sha256(payload).hexdigest(),
            },
        })
    manifest = {
        "schema_id": ARCHIVE_MANIFEST_SCHEMA_ID,
        "contract_id": CONTRACT_ID,
        "archive_id": "test-archive",
        "assurance_grade": grade,
        "created_at": "2026-08-13T12:03:00Z",
        "historical_policy_id": (
            None if grade == "identity"
            else "urn:autoeditor:policy:lesson-2026-1"
        ),
        "required_schema_ids": [ARCHIVE_MANIFEST_SCHEMA_ID],
        "files": files,
        "attestation": {
            "status": "none", "signature_file": None, "anchor": None,
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


class AutoEditorLawContracts(unittest.TestCase):
    def test_registry_hash_locks_every_supported_schema(self):
        registry = load_registry()
        self.assertEqual(registry["contract_id"], CONTRACT_ID)
        self.assertEqual(len(registry["schemas"]), 6)
        self.assertIn(
            "visual_quality_analysis",
            registry["retired_ambiguous_capabilities"],
        )
        self.assertEqual(
            registry["retired_ambiguous_capabilities"]["visual_quality_analysis"],
            [
                "urn:autoeditor:capability:deterministic.visual.rgb24",
                "urn:autoeditor:capability:semantic.visual.calibrated",
            ],
        )

    def test_every_literal_production_schema_is_registered_or_frozen_legacy(self):
        registry = load_registry()
        known = {
            entry["id"] for entry in registry["schemas"]
        } | set(registry["legacy_schema_ids"])
        emitted: set[str] = set()
        pattern = re.compile(r"autoeditor-[a-z0-9-]+/v[0-9]+")
        roots = [REPO / "autoeditor", REPO / "packaging", REPO / "desktop/helper",
                 REPO / "desktop/scripts"]
        skipped_parts = {"node_modules", "dist", "build", "staging", "__pycache__"}
        for root in roots:
            for path in root.rglob("*"):
                if (not path.is_file() or path.suffix not in {".py", ".js", ".mjs"}
                        or skipped_parts.intersection(path.parts)
                        or path.name == "transformers.web.min.js"):
                    continue
                emitted.update(pattern.findall(path.read_text(
                    encoding="utf-8", errors="ignore"
                )))
        self.assertEqual(sorted(emitted - known), [])

    def test_edit_intent_uses_integer_declared_grid_and_word_anchors(self):
        validated = validate_edit_intent(edit_intent())
        self.assertEqual(
            validated["timeline_grid"]["ticks_per_second"],
            {"denominator": 1001, "numerator": 30_000},
        )
        invalid = deepcopy(validated)
        invalid["events"][0]["duration_ticks"] = 1.5
        with self.assertRaisesRegex(ContractError, "integer ticks"):
            validate_edit_intent(invalid)
        invalid = deepcopy(validated)
        invalid["events"][0]["anchor_quote"] = "too short"
        with self.assertRaisesRegex(ContractError, "5-to-20-word"):
            validate_edit_intent(invalid)

    def test_planner_is_vendor_provenance_not_promotion_authority(self):
        validated = validate_planner_proposal(planner_proposal())
        self.assertEqual(validated["planner"]["provider_id"], "deepseek")
        unqualified = deepcopy(validated)
        unqualified["qualification"]["pass"] = False
        with self.assertRaisesRegex(ContractError, "not qualified"):
            validate_planner_proposal(unqualified)
        tampered = deepcopy(validated)
        tampered["proposal"]["payload"]["events"][0]["duration_ticks"] += 1
        with self.assertRaisesRegex(ContractError, "digest"):
            validate_planner_proposal(tampered)

    def test_render_adapter_request_is_hash_bound(self):
        validated = validate_render_request(render_request())
        self.assertEqual(
            validated["render_adapter_id"],
            "urn:autoeditor:adapter:ffmpeg-render-1",
        )
        changed = deepcopy(validated)
        changed["ffmpeg_sha256"] = SHA
        with self.assertRaisesRegex(ContractError, "closed schema"):
            validate_render_request(changed)

    def test_receipts_separate_check_algorithm_policy_and_payload_schema(self):
        validated = validate_receipt_envelope(receipt_envelope())
        self.assertEqual(
            validated["capability_id"],
            "urn:autoeditor:capability:deterministic.av-sync",
        )
        self.assertEqual(validated["check_id"], "urn:autoeditor:check:av-sync")
        unsupported = deepcopy(validated)
        unsupported["payload_schema_id"] = "urn:autoeditor:schema:unknown:9"
        with self.assertRaises(UnsupportedSchemaError):
            validate_receipt_envelope(unsupported)
        swapped = deepcopy(validated)
        swapped["check_id"] = swapped["capability_id"]
        with self.assertRaisesRegex(ContractError, "must use urn:autoeditor:check"):
            validate_receipt_envelope(swapped)

    def test_golden_identity_archive_still_verifies(self):
        result = verify_archive(
            REPO / "compatibility/archives/2026-identity"
        )
        self.assertEqual(result.assurance_grade, "identity")
        self.assertEqual(result.file_count, 1)
        self.assertEqual(
            result.master_sha256,
            "5737cbb79f94da013e555126db4c8deecc6749abc8289e45ffee0277cc8580e0",
        )

    def test_archive_grade_drops_closed_when_raw_or_project_state_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archive(root, {"master": b"master"}, "fresh_reverification")
            with self.assertRaisesRegex(
                ArchiveContractError, "missing roles:.*original_source"
            ):
                verify_archive(root)

    def test_archive_rejects_tamper_and_unlisted_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archive(root, {"master": b"master"}, "identity")
            (root / "output/master.mp4").write_bytes(b"changed")
            with self.assertRaisesRegex(ArchiveContractError, "identity changed"):
                verify_archive(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archive(root, {"master": b"master"}, "identity")
            (root / "unlisted.txt").write_text("hidden", encoding="utf-8")
            with self.assertRaisesRegex(ArchiveContractError, "inventory is not closed"):
                verify_archive(root)

    def test_archive_rejects_a_symlinked_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            archive = parent / "archive"
            archive.mkdir()
            write_archive(archive, {"master": b"master"}, "identity")
            link = parent / "archive-link"
            link.symlink_to(archive, target_is_directory=True)
            with self.assertRaisesRegex(ArchiveContractError, "root cannot be a symlink"):
                verify_archive(link)


if __name__ == "__main__":
    unittest.main()
