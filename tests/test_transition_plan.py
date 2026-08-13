from __future__ import annotations

import copy
import hashlib
import json
import unittest

from autoeditor.edit_policy import (
    CAPABILITIES,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    edit_policy_sha256,
    resolve_edit_policy,
)
from autoeditor.transition_plan import (
    MAX_TRANSITION_DURATION_MS,
    TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION,
    TRANSITION_PLAN_JSON_SCHEMA,
    TRANSITION_PLAN_SCHEMA_VERSION,
    TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
    TransitionPlanError,
    canonical_transition_plan_json,
    canonical_transition_sequence_manifest_json,
    compile_transition_plan,
    density_transition_limit,
    derive_boundary_id,
    transition_compile_receipt_sha256,
    transition_plan_sha256,
    transition_sequence_manifest_sha256,
    validate_transition_plan,
    validate_transition_sequence_manifest,
)


def _auto_values() -> dict[str, str]:
    return {
        "cut_density": "auto",
        "sfx_density": "auto",
        "transition_density": "auto",
        "dialogue_rule": "auto",
        "music_rule": "auto",
        "caption_rule": "auto",
        "visualization_rule": "auto",
    }


def _policy(
    *,
    profile: str = "commercial_product",
    density: str = "auto",
) -> dict:
    explicit = _auto_values()
    explicit["transition_density"] = density
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": profile,
        "duration_ms": 8_000,
        "delivery": {"platform": "youtube", "aspect": "auto"},
        "explicit_intent": explicit,
        "consented_preferences": {
            "consented": False,
            "values": _auto_values(),
        },
        "available_capabilities": sorted(CAPABILITIES),
    })


def _segment(
    segment_id: str,
    digest_character: str,
    *,
    duration_ms: int = 2_000,
    handles_ms: int = 1_000,
    dialogue_at_start: bool = False,
    dialogue_at_end: bool = False,
) -> dict:
    return {
        "segment_id": segment_id,
        "source_sha256": digest_character * 64,
        "duration_ms": duration_ms,
        "video_leading_handle_ms": min(handles_ms, duration_ms),
        "video_trailing_handle_ms": min(handles_ms, duration_ms),
        "audio_leading_handle_ms": min(handles_ms, duration_ms),
        "audio_trailing_handle_ms": min(handles_ms, duration_ms),
        "dialogue_at_start": dialogue_at_start,
        "dialogue_at_end": dialogue_at_end,
    }


def _manifest(*, frame_rate: tuple[int, int] = (30, 1)) -> dict:
    return {
        "schema_version": TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
        "sequence_plan_sha256": "e" * 64,
        "sequence_compile_receipt_sha256": "f" * 64,
        "frame_rate": {
            "numerator": frame_rate[0],
            "denominator": frame_rate[1],
        },
        "segments": [
            _segment("seg-a", "a", dialogue_at_end=True),
            _segment("seg-b", "b", dialogue_at_start=True),
            _segment("seg-c", "c"),
            _segment("seg-d", "d"),
        ],
    }


def _boundary(
    left: dict,
    right: dict,
    boundary_ms: int,
    *,
    kind: str,
    duration_ms: int,
    motivation: str,
) -> dict:
    return {
        "boundary_id": derive_boundary_id(
            left["segment_id"],
            right["segment_id"],
            left["source_sha256"],
            right["source_sha256"],
            boundary_ms,
        ),
        "left_segment_id": left["segment_id"],
        "right_segment_id": right["segment_id"],
        "left_source_sha256": left["source_sha256"],
        "right_source_sha256": right["source_sha256"],
        "cumulative_boundary_ms": boundary_ms,
        "kind": kind,
        "motivation": motivation,
        "duration_ms": duration_ms,
        "audio_behavior": (
            "hard_cut" if kind == "hard_cut" else "equal_power_crossfade"
        ),
        "motivation_verified": kind != "hard_cut",
        "semantic_safety_verified": True,
        "dialogue_preservation_verified": True,
    }


def _plan(
    manifest: dict | None = None,
    policy: dict | None = None,
    *,
    decisions: list[tuple[str, int]] | None = None,
) -> dict:
    manifest = copy.deepcopy(manifest if manifest is not None else _manifest())
    policy = copy.deepcopy(policy if policy is not None else _policy())
    if decisions is None:
        decisions = [
            ("cross_dissolve", 400),
            ("dip_to_black", 200),
            ("hard_cut", 0),
        ]
    usage = policy["rules"]["transitions"]["usage"]
    motivation = "motivated_only" if usage == "hard_cut_only" else usage
    cumulative = 0
    boundaries = []
    for index, left in enumerate(manifest["segments"][:-1]):
        cumulative += left["duration_ms"]
        kind, duration = decisions[index]
        boundaries.append(_boundary(
            left,
            manifest["segments"][index + 1],
            cumulative,
            kind=kind,
            duration_ms=duration,
            motivation=motivation,
        ))
    return {
        "schema_version": TRANSITION_PLAN_SCHEMA_VERSION,
        "sequence_manifest_sha256": transition_sequence_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "frame_rate": copy.deepcopy(manifest["frame_rate"]),
        "policy": copy.deepcopy(policy["rules"]["transitions"]),
        "boundaries": boundaries,
    }


class TransitionPlanTests(unittest.TestCase):
    def assert_rejected(
        self,
        plan: object,
        manifest: object | None = None,
        policy: object | None = None,
    ) -> None:
        with self.assertRaises(TransitionPlanError):
            validate_transition_plan(
                plan,
                _manifest() if manifest is None else manifest,
                _policy() if policy is None else policy,
            )

    def test_valid_plan_decides_every_exact_boundary_and_detaches(self):
        manifest = _manifest()
        policy = _policy()
        raw = _plan(manifest, policy)
        clean = validate_transition_plan(raw, manifest, policy)

        self.assertEqual(clean, raw)
        self.assertIsNot(clean, raw)
        self.assertIsNot(clean["boundaries"], raw["boundaries"])
        self.assertEqual(len(clean["boundaries"]), 3)
        self.assertEqual(
            [item["cumulative_boundary_ms"] for item in clean["boundaries"]],
            [2_000, 4_000, 6_000],
        )
        self.assertEqual(
            clean["policy"],
            {"density": "medium", "usage": "motivated_only"},
        )

    def test_boundary_id_binds_both_segments_hashes_and_cumulative_time(self):
        manifest = _manifest()
        first = _plan(manifest)["boundaries"][0]
        original_id = first["boundary_id"]
        self.assertRegex(original_id, r"^boundary-[0-9a-f]{64}$")

        mutations = (
            ("left_segment_id", "seg-z"),
            ("right_segment_id", "seg-z"),
            ("left_source_sha256", "9" * 64),
            ("right_source_sha256", "8" * 64),
            ("cumulative_boundary_ms", 2_001),
        )
        for key, value in mutations:
            arguments = {
                "left_segment_id": first["left_segment_id"],
                "right_segment_id": first["right_segment_id"],
                "left_source_sha256": first["left_source_sha256"],
                "right_source_sha256": first["right_source_sha256"],
                "cumulative_boundary_ms": first["cumulative_boundary_ms"],
            }
            arguments[key] = value
            with self.subTest(key=key):
                self.assertNotEqual(derive_boundary_id(**arguments), original_id)

        plan = _plan(manifest)
        plan["boundaries"][0]["boundary_id"] = "boundary-" + "0" * 64
        self.assert_rejected(plan, manifest)

    def test_missing_duplicate_reordered_and_phantom_boundaries_fail_closed(self):
        manifest = _manifest()
        policy = _policy()

        missing = _plan(manifest, policy)
        missing["boundaries"].pop()
        self.assert_rejected(missing, manifest, policy)

        duplicate = _plan(manifest, policy)
        duplicate["boundaries"].append(copy.deepcopy(duplicate["boundaries"][-1]))
        self.assert_rejected(duplicate, manifest, policy)

        reordered = _plan(manifest, policy)
        reordered["boundaries"][0], reordered["boundaries"][1] = (
            reordered["boundaries"][1], reordered["boundaries"][0]
        )
        self.assert_rejected(reordered, manifest, policy)

        phantom = _plan(manifest, policy)
        last = manifest["segments"][-1]
        fake = _segment("seg-after-last", "9")
        phantom["boundaries"].append(_boundary(
            last, fake, 8_000,
            kind="hard_cut", duration_ms=0, motivation="motivated_only",
        ))
        self.assert_rejected(phantom, manifest, policy)

    def test_single_segment_accepts_only_an_empty_boundary_decision_list(self):
        manifest = _manifest()
        manifest["segments"] = manifest["segments"][:1]
        policy = _policy()
        plan = _plan(manifest, policy, decisions=[])
        clean = validate_transition_plan(plan, manifest, policy)
        self.assertEqual(clean["boundaries"], [])

        phantom = copy.deepcopy(plan)
        other = _segment("seg-phantom", "9")
        phantom["boundaries"].append(_boundary(
            manifest["segments"][0], other, 2_000,
            kind="hard_cut", duration_ms=0, motivation="motivated_only",
        ))
        self.assert_rejected(phantom, manifest, policy)

    def test_duration_is_integer_bounded_and_kind_specific(self):
        manifest = _manifest()
        policy = _policy()

        for invalid in (-1, True, 200.0, MAX_TRANSITION_DURATION_MS + 1):
            plan = _plan(manifest, policy)
            plan["boundaries"][0]["duration_ms"] = invalid
            with self.subTest(invalid=invalid):
                self.assert_rejected(plan, manifest, policy)

        hard_with_duration = _plan(manifest, policy)
        hard_with_duration["boundaries"][2]["duration_ms"] = 100
        self.assert_rejected(hard_with_duration, manifest, policy)

        timed_without_duration = _plan(manifest, policy)
        timed_without_duration["boundaries"][0]["duration_ms"] = 0
        self.assert_rejected(timed_without_duration, manifest, policy)

        maximum = _plan(
            manifest, policy,
            decisions=[("cross_dissolve", 1_000), ("hard_cut", 0),
                       ("hard_cut", 0)],
        )
        validate_transition_plan(maximum, manifest, policy)

    def test_duration_must_be_frame_aligned_and_at_least_two_frames(self):
        manifest = _manifest()
        policy = _policy()

        for invalid in (33, 66, 401):
            plan = _plan(
                manifest, policy,
                decisions=[("cross_dissolve", invalid), ("hard_cut", 0),
                           ("hard_cut", 0)],
            )
            with self.subTest(invalid=invalid):
                self.assert_rejected(plan, manifest, policy)

        aligned = _plan(
            manifest, policy,
            decisions=[("cross_dissolve", 67), ("hard_cut", 0),
                       ("hard_cut", 0)],
        )
        validate_transition_plan(aligned, manifest, policy)

        ntsc_manifest = _manifest(frame_rate=(30_000, 1_001))
        valid_ntsc = _plan(
            ntsc_manifest, policy,
            decisions=[("cross_dissolve", 334), ("hard_cut", 0),
                       ("hard_cut", 0)],
        )
        validate_transition_plan(valid_ntsc, ntsc_manifest, policy)
        invalid_ntsc = copy.deepcopy(valid_ntsc)
        invalid_ntsc["boundaries"][0]["duration_ms"] = 333
        self.assert_rejected(invalid_ntsc, ntsc_manifest, policy)

    def test_dip_to_black_requires_even_symmetric_frame_count(self):
        manifest = _manifest()
        policy = _policy()
        for invalid in (67, 100, 300):  # 2, 3, and 9 frames at 30fps.
            plan = _plan(
                manifest, policy,
                decisions=[("dip_to_black", invalid), ("hard_cut", 0),
                           ("hard_cut", 0)],
            )
            with self.subTest(invalid=invalid):
                self.assert_rejected(plan, manifest, policy)

        valid = _plan(
            manifest, policy,
            decisions=[("dip_to_black", 200), ("hard_cut", 0),
                       ("hard_cut", 0)],
        )
        validate_transition_plan(valid, manifest, policy)

    def test_video_and_audio_decoded_handle_shortages_fail_independently(self):
        handle_cases = (
            (0, "video_trailing_handle_ms"),
            (1, "video_leading_handle_ms"),
            (0, "audio_trailing_handle_ms"),
            (1, "audio_leading_handle_ms"),
        )
        policy = _policy()
        for segment_index, key in handle_cases:
            manifest = _manifest()
            manifest["segments"][segment_index][key] = 399
            plan = _plan(manifest, policy)
            with self.subTest(segment_index=segment_index, key=key):
                self.assert_rejected(plan, manifest, policy)

    def test_transition_must_leave_a_complete_frame_in_both_segments(self):
        manifest = _manifest()
        manifest["segments"][0] = _segment(
            "seg-a", "a", duration_ms=400, handles_ms=400,
            dialogue_at_end=True,
        )
        policy = _policy()
        plan = _plan(
            manifest, policy,
            decisions=[("cross_dissolve", 400), ("hard_cut", 0),
                       ("hard_cut", 0)],
        )
        self.assert_rejected(plan, manifest, policy)

    def test_two_transition_windows_cannot_overlap_inside_middle_segment(self):
        manifest = _manifest()
        manifest["segments"][1] = _segment(
            "seg-b", "b", duration_ms=1_000, handles_ms=1_000,
            dialogue_at_start=True,
        )
        policy = _policy()
        plan = _plan(
            manifest, policy,
            decisions=[("cross_dissolve", 600),
                       ("cross_dissolve", 600),
                       ("hard_cut", 0)],
        )
        self.assert_rejected(plan, manifest, policy)

    def test_two_transition_windows_leave_a_complete_interior_frame(self):
        policy = _policy()

        exact_consumption = _manifest()
        exact_consumption["segments"][1] = _segment(
            "seg-b", "b", duration_ms=800, handles_ms=800,
            dialogue_at_start=True,
        )
        self.assert_rejected(_plan(
            exact_consumption, policy,
            decisions=[("cross_dissolve", 400),
                       ("cross_dissolve", 400),
                       ("hard_cut", 0)],
        ), exact_consumption, policy)

        one_frame_remains = _manifest()
        one_frame_remains["segments"][1] = _segment(
            "seg-b", "b", duration_ms=834, handles_ms=834,
            dialogue_at_start=True,
        )
        validate_transition_plan(_plan(
            one_frame_remains, policy,
            decisions=[("cross_dissolve", 400),
                       ("cross_dissolve", 400),
                       ("hard_cut", 0)],
        ), one_frame_remains, policy)

        ntsc_exact = _manifest(frame_rate=(30_000, 1_001))
        ntsc_exact["segments"][1] = _segment(
            "seg-b", "b", duration_ms=668, handles_ms=668,
            dialogue_at_start=True,
        )
        self.assert_rejected(_plan(
            ntsc_exact, policy,
            decisions=[("cross_dissolve", 334),
                       ("cross_dissolve", 334),
                       ("hard_cut", 0)],
        ), ntsc_exact, policy)

        ntsc_one_frame = _manifest(frame_rate=(30_000, 1_001))
        ntsc_one_frame["segments"][1] = _segment(
            "seg-b", "b", duration_ms=702, handles_ms=702,
            dialogue_at_start=True,
        )
        validate_transition_plan(_plan(
            ntsc_one_frame, policy,
            decisions=[("cross_dissolve", 334),
                       ("cross_dissolve", 334),
                       ("hard_cut", 0)],
        ), ntsc_one_frame, policy)

    def test_cut_only_policy_accepts_hard_cuts_and_rejects_timed_transitions(self):
        manifest = _manifest()
        policy = _policy(profile="utility_faithful")
        cuts = _plan(
            manifest, policy,
            decisions=[("hard_cut", 0), ("hard_cut", 0), ("hard_cut", 0)],
        )
        clean = validate_transition_plan(cuts, manifest, policy)
        self.assertEqual(clean["policy"],
                         {"density": "none", "usage": "hard_cut_only"})
        self.assertTrue(all(item["motivation"] == "motivated_only"
                            for item in clean["boundaries"]))

        timed = _plan(
            manifest, policy,
            decisions=[("cross_dissolve", 400), ("hard_cut", 0),
                       ("hard_cut", 0)],
        )
        self.assert_rejected(timed, manifest, policy)

    def test_density_is_a_conservative_ceiling_not_a_transition_quota(self):
        self.assertEqual(
            [density_transition_limit(name, 9)
             for name in ("none", "sparse", "medium", "dense")],
            [0, 3, 5, 9],
        )
        manifest = _manifest()

        sparse_policy = _policy(density="sparse")
        one = _plan(
            manifest, sparse_policy,
            decisions=[("cross_dissolve", 400), ("hard_cut", 0),
                       ("hard_cut", 0)],
        )
        validate_transition_plan(one, manifest, sparse_policy)
        two = _plan(
            manifest, sparse_policy,
            decisions=[("cross_dissolve", 400),
                       ("cross_dissolve", 400),
                       ("hard_cut", 0)],
        )
        self.assert_rejected(two, manifest, sparse_policy)

        dense_policy = _policy(density="dense")
        three = _plan(
            manifest, dense_policy,
            decisions=[("cross_dissolve", 400),
                       ("cross_dissolve", 400),
                       ("cross_dissolve", 400)],
        )
        validate_transition_plan(three, manifest, dense_policy)

    def test_policy_hash_density_usage_and_motivation_are_exactly_bound(self):
        manifest = _manifest()
        policy = _policy()
        mutations = []

        changed = _plan(manifest, policy)
        changed["edit_policy_sha256"] = "0" * 64
        mutations.append(changed)
        changed = _plan(manifest, policy)
        changed["policy"]["density"] = "sparse"
        mutations.append(changed)
        changed = _plan(manifest, policy)
        changed["policy"]["usage"] = "continuity_motivated"
        mutations.append(changed)
        changed = _plan(manifest, policy)
        changed["boundaries"][0]["motivation"] = "location_motivated"
        mutations.append(changed)

        for index, invalid in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_rejected(invalid, manifest, policy)

        other_policy = _policy(profile="podcast_interview")
        self.assert_rejected(_plan(manifest, policy), manifest, other_policy)

    def test_semantic_motivation_and_dialogue_safety_fail_closed(self):
        manifest = _manifest()
        policy = _policy()

        for key in (
            "motivation_verified",
            "semantic_safety_verified",
            "dialogue_preservation_verified",
        ):
            plan = _plan(manifest, policy)
            plan["boundaries"][0][key] = False
            with self.subTest(key=key):
                self.assert_rejected(plan, manifest, policy)

        for key in ("semantic_safety_verified", "dialogue_preservation_verified"):
            plan = _plan(manifest, policy)
            plan["boundaries"][2][key] = False
            with self.subTest(hard_cut_key=key):
                self.assert_rejected(plan, manifest, policy)

        wrong_audio = _plan(manifest, policy)
        wrong_audio["boundaries"][0]["audio_behavior"] = "hard_cut"
        self.assert_rejected(wrong_audio, manifest, policy)

    def test_compile_emits_exact_inert_video_audio_primitives_and_receipt(self):
        manifest = _manifest()
        policy = _policy()
        result = compile_transition_plan(_plan(manifest, policy), manifest, policy)
        compiled = result["compiled_boundaries"]
        receipt = result["receipt"]

        self.assertEqual(
            compiled[0]["video_ffmpeg_primitive_tokens"],
            ["xfade=transition=fade:duration=0.400:offset=1.600"],
        )
        self.assertEqual(
            compiled[0]["audio_ffmpeg_primitive_tokens"],
            ["acrossfade=d=0.400:o=1:c1=qsin:c2=qsin"],
        )
        self.assertEqual(compiled[0]["duration_frames"], 12)
        self.assertTrue(compiled[0]["dialogue_crossing"])
        self.assertEqual(
            compiled[1]["video_ffmpeg_primitive_tokens"],
            ["xfade=transition=fadeblack:duration=0.200:offset=3.400"],
        )
        self.assertEqual(compiled[1]["output_boundary_ms"], 3_600)
        self.assertEqual(
            compiled[2]["video_ffmpeg_primitive_tokens"],
            ["concat=n=2:v=1:a=0"],
        )
        self.assertEqual(
            compiled[2]["audio_ffmpeg_primitive_tokens"],
            ["concat=n=2:v=0:a=1"],
        )
        self.assertEqual(receipt["schema_version"],
                         TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["source_duration_ms"], 8_000)
        self.assertEqual(receipt["output_duration_ms"], 7_400)
        self.assertEqual(receipt["boundary_count"], 3)
        self.assertEqual(receipt["non_hard_transition_count"], 2)
        self.assertEqual(receipt["time_base"],
                         {"numerator": 1, "denominator": 1_000})
        self.assertEqual(result["receipt_sha256"],
                         transition_compile_receipt_sha256(receipt))

        expected_compiled_hash = hashlib.sha256(json.dumps(
            compiled,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")).hexdigest()
        self.assertEqual(receipt["compiled_boundaries_sha256"],
                         expected_compiled_hash)

    def test_compilation_and_hashes_are_deterministic_under_object_key_order(self):
        manifest = _manifest()
        policy = _policy()
        plan = _plan(manifest, policy)
        reordered_plan = {
            key: copy.deepcopy(plan[key]) for key in reversed(list(plan))
        }
        reordered_plan["boundaries"] = [
            {key: item[key] for key in reversed(list(item))}
            for item in reordered_plan["boundaries"]
        ]
        reordered_manifest = {
            key: copy.deepcopy(manifest[key]) for key in reversed(list(manifest))
        }

        self.assertEqual(canonical_transition_plan_json(plan),
                         canonical_transition_plan_json(reordered_plan))
        self.assertEqual(transition_plan_sha256(plan),
                         transition_plan_sha256(reordered_plan))
        self.assertEqual(canonical_transition_sequence_manifest_json(manifest),
                         canonical_transition_sequence_manifest_json(
                             reordered_manifest
                         ))
        self.assertEqual(
            compile_transition_plan(plan, manifest, policy),
            compile_transition_plan(reordered_plan, reordered_manifest, policy),
        )

    def test_plan_manifest_and_receipt_hashes_detect_tampering(self):
        manifest = _manifest()
        policy = _policy()
        plan = _plan(manifest, policy)
        original_plan_hash = transition_plan_sha256(plan)

        for key, value in (
            ("kind", "hard_cut"),
            ("duration_ms", 600),
            ("semantic_safety_verified", False),
        ):
            changed = copy.deepcopy(plan)
            changed["boundaries"][0][key] = value
            if key == "kind":
                changed["boundaries"][0]["duration_ms"] = 0
                changed["boundaries"][0]["audio_behavior"] = "hard_cut"
            with self.subTest(key=key):
                if key == "semantic_safety_verified":
                    with self.assertRaises(TransitionPlanError):
                        transition_plan_sha256(changed)
                else:
                    self.assertNotEqual(transition_plan_sha256(changed),
                                        original_plan_hash)

        changed_manifest = copy.deepcopy(manifest)
        changed_manifest["segments"][0]["video_trailing_handle_ms"] -= 1
        self.assertNotEqual(
            transition_sequence_manifest_sha256(changed_manifest),
            transition_sequence_manifest_sha256(manifest),
        )

        receipt = compile_transition_plan(plan, manifest, policy)["receipt"]
        original_receipt_hash = transition_compile_receipt_sha256(receipt)
        changed_receipt = copy.deepcopy(receipt)
        changed_receipt["output_duration_ms"] += 1
        self.assertNotEqual(transition_compile_receipt_sha256(changed_receipt),
                            original_receipt_hash)
        changed_receipt = copy.deepcopy(receipt)
        changed_receipt["extra"] = True
        with self.assertRaises(TransitionPlanError):
            transition_compile_receipt_sha256(changed_receipt)

    def test_manifest_is_closed_ordered_and_handle_bounded(self):
        manifest = _manifest()
        clean = validate_transition_sequence_manifest(manifest)
        self.assertEqual(clean, manifest)
        self.assertIsNot(clean, manifest)

        invalid_manifests = []
        changed = _manifest()
        changed["generated_at"] = "today"
        invalid_manifests.append(changed)
        changed = _manifest()
        changed["segments"][0]["extra"] = True
        invalid_manifests.append(changed)
        changed = _manifest()
        changed["segments"][1]["segment_id"] = "seg-a"
        invalid_manifests.append(changed)
        changed = _manifest()
        changed["segments"][0]["video_leading_handle_ms"] = 2_001
        invalid_manifests.append(changed)
        changed = _manifest()
        changed["segments"][0]["duration_ms"] = True
        invalid_manifests.append(changed)
        changed = _manifest()
        changed["frame_rate"] = {"numerator": 60, "denominator": 2}
        invalid_manifests.append(changed)

        for index, invalid in enumerate(invalid_manifests):
            with self.subTest(index=index):
                with self.assertRaises(TransitionPlanError):
                    validate_transition_sequence_manifest(invalid)

        reordered = _manifest()
        reordered["segments"][0], reordered["segments"][1] = (
            reordered["segments"][1], reordered["segments"][0]
        )
        self.assertNotEqual(transition_sequence_manifest_sha256(reordered),
                            transition_sequence_manifest_sha256(manifest))

    def test_exact_keys_enums_types_and_versions_are_closed(self):
        manifest = _manifest()
        policy = _policy()
        invalid_plans = []

        changed = _plan(manifest, policy)
        changed["schema_version"] = "autoeditor-transition-plan/v2"
        invalid_plans.append(changed)
        changed = _plan(manifest, policy)
        changed["comment"] = "unknown"
        invalid_plans.append(changed)
        changed = _plan(manifest, policy)
        changed["frame_rate"]["drop_frame"] = False
        invalid_plans.append(changed)
        changed = _plan(manifest, policy)
        changed["boundaries"][0]["kind"] = "spin"
        invalid_plans.append(changed)
        changed = _plan(manifest, policy)
        changed["boundaries"][0]["motivation"] = "random"
        invalid_plans.append(changed)
        changed = _plan(manifest, policy)
        changed["boundaries"][0]["audio_behavior"] = "drop_audio"
        invalid_plans.append(changed)
        changed = _plan(manifest, policy)
        changed["boundaries"][0]["semantic_safety_verified"] = 1
        invalid_plans.append(changed)

        for index, invalid in enumerate(invalid_plans):
            with self.subTest(index=index):
                self.assert_rejected(invalid, manifest, policy)

        changed_manifest = _manifest()
        changed_manifest["schema_version"] = (
            "autoeditor-transition-sequence-manifest/v2"
        )
        with self.assertRaises(TransitionPlanError):
            validate_transition_sequence_manifest(changed_manifest)

    def test_json_schema_advertises_the_same_closed_surface(self):
        schema = TRANSITION_PLAN_JSON_SCHEMA
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema_version"]["const"],
                         TRANSITION_PLAN_SCHEMA_VERSION)
        boundaries = schema["properties"]["boundaries"]
        self.assertEqual(boundaries["maxItems"], 255)
        self.assertFalse(boundaries["items"]["additionalProperties"])
        properties = boundaries["items"]["properties"]
        self.assertEqual(properties["duration_ms"]["maximum"], 1_000)
        self.assertEqual(properties["kind"]["enum"],
                         ["cross_dissolve", "dip_to_black", "hard_cut"])
        self.assertEqual(
            properties["motivation"]["enum"],
            ["beat_or_phrase_motivated", "continuity_motivated",
             "location_motivated", "motivated_only"],
        )


if __name__ == "__main__":
    unittest.main()
