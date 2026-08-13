from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from autoeditor.edit_policy import CAPABILITIES, edit_policy_sha256
from autoeditor.project_intent_authority import (
    PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA,
    ProjectIntentAuthorityError,
    build_project_intent_engine_envelope,
    build_project_intent_render_receipt,
    canonical_project_intent_engine_envelope_bytes,
    project_intent_engine_envelope_sha256,
    validate_project_intent_engine_envelope,
    validate_project_intent_render_receipt,
)
from autoeditor.project_intent_policy_bridge import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_MANIFEST_SOURCE,
    PROJECT_INTENT_SCHEMA_VERSION,
    resolve_project_intent_policy,
)
from autoeditor.pipeline import (
    build_engine_artifact_contract,
    build_project_intent_actual_render_facts,
    intentional_silent_sequence_mode,
    load_project_intent_engine_envelope,
    validate_project_intent_render_settings,
    write_edit_boundaries_receipt,
)


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def project_intent(**preference_overrides: str) -> dict:
    preferences = {
        "captions": "auto", "graphics": "auto", "music": "auto",
        "sfx": "auto", "transitions": "auto",
    }
    preferences.update(preference_overrides)
    return {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": "dialogue_talking_head",
        "delivery": {"platform": "youtube", "aspect": "16:9"},
        "target_duration": {"min_ms": 30_000, "max_ms": 45_000},
        "preferences": {
            name: {"enabled": value != "none", "preference": value}
            for name, value in preferences.items()
        },
    }


def capability_manifest() -> dict:
    return {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": "a" * 64,
        "available_capabilities": sorted(CAPABILITIES),
    }


def authority(**preference_overrides: str) -> dict:
    project = project_intent(**preference_overrides)
    manifest = capability_manifest()
    policy = resolve_project_intent_policy(project, manifest)
    return {
        "schema_version": "autoeditor-project-intent-authority/v2",
        "authorization_id": "1" * 32,
        "approved_proposal_sha256": "b" * 64,
        "project_intent": project,
        "project_intent_sha256": digest(project),
        "edit_policy": policy,
        "edit_policy_sha256": edit_policy_sha256(policy),
        "capability_manifest": manifest,
        "capability_manifest_sha256": digest(manifest),
        "authorization_hmac_sha256": "f" * 64,
    }


def actual_render(**preference_overrides: object) -> dict:
    preferences = {
        "captions": {"delivery": "burned", "event_count": 12},
        "graphics": {"event_count": 2},
        "music": {
            "added_music_present": True, "source_music_preserved": False,
        },
        "sfx": {
            "cue_count": 3, "policy_usage": "motivated_only",
            "policy_bound": True,
        },
        "transitions": {
            "event_count": 2, "non_hard_event_count": 1,
            "policy_usage": "motivated_only", "policy_bound": True,
        },
    }
    preferences.update(preference_overrides)
    return {
        "duration_ms": 35_000,
        "delivery": {
            "platform": "youtube", "configured_aspect": "16:9",
            "artifact_aspect": "16:9", "width": 1920, "height": 1080,
        },
        "preferences": preferences,
    }


def music_evidence(region_count: int = 1) -> dict:
    return {
        "ok": True, "mode": "rendered" if region_count else "no_safe_gap",
        "region_count": region_count, "policy_usage": "supporting",
        "policy_bound": True, "rights_verified": True,
        "dialogue_masking_verified": True, "loudness_verified": True,
        "receipt_sha256": "c" * 64, "output_sha256": "d" * 64,
        "note": "",
    }


class ProjectIntentPipelineAuthorityTests(unittest.TestCase):
    def test_daemon_authority_becomes_canonical_secret_free_envelope(self):
        envelope = build_project_intent_engine_envelope(authority())
        self.assertEqual(
            envelope["schema_version"], PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA
        )
        self.assertNotIn("authorization_hmac_sha256", envelope)
        self.assertEqual(
            envelope["capability_probe_receipt_sha256"], "a" * 64
        )
        encoded = canonical_project_intent_engine_envelope_bytes(envelope)
        self.assertEqual(encoded, canonical(envelope).encode("utf-8"))
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            project_intent_engine_envelope_sha256(envelope),
        )

    def test_engine_recomputes_every_object_hash_and_policy(self):
        envelope = build_project_intent_engine_envelope(authority())
        for mutation in (
            lambda value: value.update(project_intent_sha256="0" * 64),
            lambda value: value.update(edit_policy_sha256="0" * 64),
            lambda value: value.update(capability_manifest_sha256="0" * 64),
            lambda value: value.update(
                capability_probe_receipt_sha256="0" * 64),
            lambda value: value.update(
                approved_transition_carrier={
                    "sequence_plan_sha256": "0" * 64,
                }),
            lambda value: value["edit_policy"]["delivery"].update(
                aspect="9:16"),
            lambda value: value.update(extra=True),
        ):
            candidate = copy.deepcopy(envelope)
            mutation(candidate)
            with self.subTest(candidate=mutation):
                with self.assertRaises(ProjectIntentAuthorityError):
                    validate_project_intent_engine_envelope(candidate)

    def test_pipeline_loads_only_exact_canonical_file_and_paired_digest(self):
        envelope = build_project_intent_engine_envelope(authority())
        canonical_bytes = canonical_project_intent_engine_envelope_bytes(envelope)
        with tempfile.TemporaryDirectory(prefix="intent-engine-envelope-") as raw:
            root = Path(raw)
            path = root / "authority.json"
            path.write_bytes(canonical_bytes)
            expected_hash = hashlib.sha256(canonical_bytes).hexdigest()
            loaded, measured = load_project_intent_engine_envelope(
                path, expected_hash
            )
            self.assertEqual(loaded, envelope)
            self.assertEqual(measured, expected_hash)

            path.write_bytes(canonical_bytes + b"\n")
            with self.assertRaises(ProjectIntentAuthorityError):
                load_project_intent_engine_envelope(
                    path, hashlib.sha256(path.read_bytes()).hexdigest()
                )
            with self.assertRaises(ProjectIntentAuthorityError):
                load_project_intent_engine_envelope(path, "0" * 64)
            with self.assertRaises(ProjectIntentAuthorityError):
                load_project_intent_engine_envelope(path, None)

    def test_artifact_contract_v4_is_conditional_and_legacy_v2_is_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="intent-artifact-contract-") as raw:
            root = Path(raw)
            names = {
                "delivery": "pending.UNVERIFIED.mp4",
                "final": "final.mp4",
                "captions": "PSE_CAPTIONS.srt",
                "caption_render": "CAPTION_RENDER_RECEIPT.json",
                "boundaries": "EDIT_BOUNDARIES.json",
                "mix": "AUDIO_MIX_RECEIPT.json",
                "intent": "PROJECT_INTENT_RENDER_RECEIPT.json",
                "music": "MUSIC_PRODUCTION_RECEIPT.json",
                "sfx": "SFX_PRODUCTION_RECEIPT.json",
            }
            paths = {key: root / name for key, name in names.items()}
            for key, path in paths.items():
                if key != "final":
                    path.write_bytes(f"{key}-bytes".encode("ascii"))
            legacy = build_engine_artifact_contract(
                mode="generic-baseline", delivery=paths["delivery"],
                final_file=paths["final"], edl=None,
                captions=paths["captions"],
                caption_render=paths["caption_render"],
                edit_boundaries=paths["boundaries"], audio_mix=paths["mix"],
                sequence=None,
            )
            self.assertEqual(
                legacy["schema"], "autoeditor-engine-artifact-contract/v2"
            )
            self.assertEqual(set(legacy), {
                "schema", "mode", "delivery", "edl", "captions",
                "caption_render", "edit_boundaries", "audio_mix", "sequence",
            })
            governed = build_engine_artifact_contract(
                mode="generic-baseline", delivery=paths["delivery"],
                final_file=paths["final"], edl=None,
                captions=paths["captions"],
                caption_render=paths["caption_render"],
                edit_boundaries=paths["boundaries"], audio_mix=paths["mix"],
                sequence=None, project_intent=paths["intent"],
                music_production=paths["music"],
                sfx_production=paths["sfx"],
            )
            self.assertEqual(
                governed["schema"], "autoeditor-engine-artifact-contract/v4"
            )
            self.assertEqual(set(governed), {
                "schema", "mode", "delivery", "edl", "captions",
                "caption_render", "edit_boundaries", "audio_mix", "sequence",
                "project_intent", "music_production", "sfx_production",
            })
            self.assertEqual(
                governed["project_intent"]["file"],
                "PROJECT_INTENT_RENDER_RECEIPT.json",
            )
            self.assertEqual(
                governed["music_production"]["file"],
                "MUSIC_PRODUCTION_RECEIPT.json",
            )
            self.assertEqual(
                governed["sfx_production"]["file"],
                "SFX_PRODUCTION_RECEIPT.json",
            )
            for missing in ("intent", "music", "sfx"):
                governed_paths = {
                    "project_intent": paths["intent"],
                    "music_production": paths["music"],
                    "sfx_production": paths["sfx"],
                }
                del governed_paths[{
                    "intent": "project_intent", "music": "music_production",
                    "sfx": "sfx_production",
                }[missing]]
                with self.subTest(missing=missing), self.assertRaisesRegex(
                        RuntimeError, "typed music and SFX"):
                    build_engine_artifact_contract(
                        mode="generic-baseline", delivery=paths["delivery"],
                        final_file=paths["final"], edl=None, captions=None,
                        caption_render=None, edit_boundaries=paths["boundaries"],
                        audio_mix=paths["mix"], sequence=None,
                        **governed_paths,
                    )

    def test_governed_settings_reject_every_raw_music_input(self):
        for preference in ("none", "auto", "supporting", "primary",
                           "source_primary"):
            envelope = build_project_intent_engine_envelope(
                authority(music=preference)
            )
            with self.subTest(preference=preference), self.assertRaisesRegex(
                    ProjectIntentAuthorityError, "raw --music"):
                validate_project_intent_render_settings(
                    envelope, configured_aspects="16x9", music_present=True,
                )
            validate_project_intent_render_settings(
                envelope, configured_aspects="16x9", music_present=False,
            )

    def test_daemon_carrier_never_exposes_hmac_and_detects_mutation(self):
        import importlib.util

        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "pipeline_authority_daemon",
            root / "packaging" / "helper_daemon_entry.py",
        )
        assert spec is not None and spec.loader is not None
        daemon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(daemon)
        with tempfile.TemporaryDirectory(prefix="intent-daemon-carrier-") as raw:
            work = Path(raw).resolve()
            binding = daemon._open_project_intent_engine_envelope(
                work, authority()
            )
            try:
                payload = binding["path"].read_bytes()
                self.assertNotIn(b"authorization_hmac_sha256", payload)
                self.assertEqual(
                    hashlib.sha256(payload).hexdigest(), binding["sha256"]
                )
                daemon._verify_project_intent_engine_envelope(binding)
                binding["path"].write_bytes(payload.replace(
                    b'"authorization_id":"1111',
                    b'"authorization_id":"2111', 1,
                ))
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    daemon._verify_project_intent_engine_envelope(binding)
            finally:
                daemon._clear_project_intent_engine_envelope(binding)
            self.assertFalse(binding["path"].exists())

    def test_render_receipt_passes_exact_actual_settings(self):
        envelope = build_project_intent_engine_envelope(authority())
        receipt = build_project_intent_render_receipt(
            envelope, project_intent_engine_envelope_sha256(envelope),
            actual_render(),
        )
        self.assertTrue(receipt["pass"])
        self.assertTrue(all(
            check["ok"] for check in receipt["checks"].values()
        ))
        self.assertEqual(validate_project_intent_render_receipt(receipt), receipt)

    def test_actual_duration_delivery_and_preferences_fail_closed(self):
        cases = []

        wrong_duration = actual_render()
        wrong_duration["duration_ms"] = 46_000
        cases.append((authority(), wrong_duration, "target_duration"))

        wrong_aspect = actual_render()
        wrong_aspect["delivery"]["artifact_aspect"] = "9:16"
        cases.append((authority(), wrong_aspect, "delivery"))

        cases.extend([
            (authority(captions="none"), actual_render(), "captions"),
            (authority(graphics="none"), actual_render(), "graphics"),
            (authority(music="none"), actual_render(), "music"),
            (authority(sfx="none"), actual_render(), "sfx"),
            (authority(transitions="hard_cut_only"), actual_render(),
             "transitions"),
        ])
        for raw_authority, actual, expected_check in cases:
            with self.subTest(check=expected_check):
                envelope = build_project_intent_engine_envelope(raw_authority)
                receipt = build_project_intent_render_receipt(
                    envelope, project_intent_engine_envelope_sha256(envelope),
                    actual,
                )
                self.assertFalse(receipt["pass"])
                self.assertFalse(receipt["checks"][expected_check]["ok"])

    def test_typed_preferences_require_bound_real_events(self):
        for name, preference, fact in (
            ("music", "supporting", {
                "added_music_present": False,
                "source_music_preserved": False,
            }),
            ("sfx", "motivated_only", {
                "cue_count": 0, "policy_usage": "motivated_only",
                "policy_bound": True,
            }),
            ("transitions", "motivated_only", {
                "event_count": 1, "non_hard_event_count": 1,
                "policy_usage": "motivated_only", "policy_bound": False,
            }),
        ):
            with self.subTest(name=name):
                envelope = build_project_intent_engine_envelope(
                    authority(**{name: preference})
                )
                receipt = build_project_intent_render_receipt(
                    envelope, project_intent_engine_envelope_sha256(envelope),
                    actual_render(**{name: fact}),
                )
                self.assertFalse(receipt["checks"][name]["ok"])

    def test_auto_still_enforces_the_resolved_expert_policy(self):
        envelope = build_project_intent_engine_envelope(authority())
        cases = (
            ("captions", {"delivery": "none", "event_count": 0}),
            ("music", {
                "added_music_present": False,
                "source_music_preserved": False,
            }),
            ("sfx", {
                "cue_count": 2, "policy_usage": "unverified",
                "policy_bound": False,
            }),
            ("transitions", {
                "event_count": 1, "non_hard_event_count": 1,
                "policy_usage": "unverified", "policy_bound": False,
            }),
        )
        for name, facts in cases:
            with self.subTest(name=name):
                receipt = build_project_intent_render_receipt(
                    envelope, project_intent_engine_envelope_sha256(envelope),
                    actual_render(**{name: facts}),
                )
                self.assertFalse(receipt["checks"][name]["ok"])

    def test_transition_facts_distinguish_hard_cuts_from_effects(self):
        envelope = build_project_intent_engine_envelope(authority())
        handoff = {
            "boundaries": [
                {"kind": "hard_cut"},
                {"kind": "cross_dissolve"},
            ],
            "transition_compile_receipt": {
                "policy": envelope["edit_policy"]["rules"]["transitions"],
                "edit_policy_sha256": envelope["edit_policy_sha256"],
            },
        }
        with mock.patch(
                "autoeditor.pipeline.preflight",
                return_value={"width": 1920, "height": 1080}), mock.patch(
                "autoeditor.pipeline._dur", return_value=35.0):
            facts = build_project_intent_actual_render_facts(
                envelope, Path("render.mp4"), resolved_aspects="16x9",
                caption_render_receipt=None, caption_sidecar=None,
                graphic_event_count=0, sfx_cue_count=0,
                transition_handoff_receipt=handoff,
                music_production_evidence=music_evidence(),
            )
        transitions = facts["preferences"]["transitions"]
        self.assertEqual(transitions["event_count"], 2)
        self.assertEqual(transitions["non_hard_event_count"], 1)
        self.assertTrue(transitions["policy_bound"])

    def test_actual_music_fact_comes_only_from_verified_region_count(self):
        envelope = build_project_intent_engine_envelope(authority())
        with mock.patch(
                "autoeditor.pipeline.preflight",
                return_value={"width": 1920, "height": 1080}), mock.patch(
                "autoeditor.pipeline._dur", return_value=35.0):
            present = build_project_intent_actual_render_facts(
                envelope, Path("render.mp4"), resolved_aspects="16x9",
                caption_render_receipt=None, caption_sidecar=None,
                graphic_event_count=0, sfx_cue_count=0,
                transition_handoff_receipt=None,
                music_production_evidence=music_evidence(1),
            )
            absent = build_project_intent_actual_render_facts(
                envelope, Path("render.mp4"), resolved_aspects="16x9",
                caption_render_receipt=None, caption_sidecar=None,
                graphic_event_count=0, sfx_cue_count=0,
                transition_handoff_receipt=None,
                music_production_evidence=music_evidence(0),
            )
            with self.assertRaisesRegex(
                    ProjectIntentAuthorityError, "music production evidence"):
                build_project_intent_actual_render_facts(
                    envelope, Path("render.mp4"), resolved_aspects="16x9",
                    caption_render_receipt=None, caption_sidecar=None,
                    graphic_event_count=0, sfx_cue_count=0,
                    transition_handoff_receipt=None,
                    music_production_evidence=None,
                )
        self.assertTrue(
            present["preferences"]["music"]["added_music_present"]
        )
        self.assertFalse(
            absent["preferences"]["music"]["added_music_present"]
        )

    def test_verified_music_disables_intentional_silence(self):
        sequence = {
            "ordered_segment_ids": ["seg-1"],
            "synthesized_silence_source_ids": ["source-1"],
            "used_audio_source_ids": [],
        }
        self.assertTrue(intentional_silent_sequence_mode(
            sequence, [], [], None, music_present=False,
        ))
        self.assertFalse(intentional_silent_sequence_mode(
            sequence, [], [], None, music_present=True,
        ))

    def test_transition_boundary_projection_preserves_adjacency_index(self):
        handoff = {
            "schema_version": "autoeditor-sequence-handoff-receipt/v2",
            "hard_cut_boundaries_ms": [2_500],
            "boundaries": [
                {
                    "boundary_index": 0, "kind": "hard_cut",
                    "output_start_ms": 2_500, "output_end_ms": 2_500,
                    "overlap_ms": 0,
                },
                {
                    "boundary_index": 1, "kind": "cross_dissolve",
                    "output_start_ms": 4_800, "output_end_ms": 5_000,
                    "overlap_ms": 200,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as raw:
            receipt = write_edit_boundaries_receipt(
                Path(raw) / "EDIT_BOUNDARIES.json", [],
                sequence_handoff_receipt=handoff,
            )
        self.assertEqual(receipt["transition_support"], "implemented")
        self.assertEqual(receipt["transitions"], [{
            "index": 1, "s": 4.8, "e": 5.0,
            "kind": "cross_dissolve", "duration_ms": 200,
        }])

    def test_receipt_rejects_swapped_or_tampered_evidence(self):
        envelope = build_project_intent_engine_envelope(authority())
        receipt = build_project_intent_render_receipt(
            envelope, project_intent_engine_envelope_sha256(envelope),
            actual_render(),
        )
        for mutation in (
            lambda value: value.update(project_intent_sha256="0" * 64),
            lambda value: value["actual_render"].update(duration_ms=46_000),
            lambda value: value["checks"]["delivery"].update(ok=False),
            lambda value: value.update(extra=True),
        ):
            candidate = copy.deepcopy(receipt)
            mutation(candidate)
            with self.subTest(candidate=mutation):
                with self.assertRaises(ProjectIntentAuthorityError):
                    validate_project_intent_render_receipt(candidate)


if __name__ == "__main__":
    unittest.main()
