from __future__ import annotations

import copy
import hashlib
import json
import random
import unittest

from autoeditor.edit_policy import (
    ASPECTS,
    CAPABILITIES,
    DURATION_BANDS,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    EDIT_POLICY_SCHEMA_VERSION,
    MAX_DURATION_MS,
    PLATFORMS,
    PROFILE_NAMES,
    EditPolicyError,
    canonical_edit_policy_json,
    duration_band,
    edit_policy_sha256,
    resolve_edit_policy,
    validate_edit_policy,
)


EXPECTED_PROFILES = {
    "dialogue_talking_head",
    "podcast_interview",
    "course_tutorial_screencast",
    "commercial_product",
    "vlog_travel",
    "gaming",
    "wedding_event",
    "sports_highlights",
    "music_performance",
    "real_estate",
    "documentary_narrative",
    "montage_meme",
    "utility_faithful",
}


def auto_values() -> dict[str, str]:
    return {
        "cut_density": "auto",
        "sfx_density": "auto",
        "transition_density": "auto",
        "dialogue_rule": "auto",
        "music_rule": "auto",
        "caption_rule": "auto",
        "visualization_rule": "auto",
    }


def request(
    profile: str = "dialogue_talking_head",
    duration_ms: int = 45_000,
    platform: str = "youtube",
    aspect: str = "auto",
) -> dict:
    return {
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": profile,
        "duration_ms": duration_ms,
        "delivery": {"platform": platform, "aspect": aspect},
        "explicit_intent": auto_values(),
        "consented_preferences": {
            "consented": False,
            "values": auto_values(),
        },
        "available_capabilities": sorted(CAPABILITIES),
    }


class EditPolicyProfileTests(unittest.TestCase):
    def test_profile_surface_is_exactly_the_thirteen_approved_profiles(self):
        self.assertEqual(PROFILE_NAMES, EXPECTED_PROFILES)
        self.assertEqual(len(PROFILE_NAMES), 13)

    def test_every_profile_resolves_to_closed_versioned_policy(self):
        for profile in sorted(EXPECTED_PROFILES):
            with self.subTest(profile=profile):
                policy = resolve_edit_policy(request(profile=profile))
                self.assertEqual(policy["schema_version"], EDIT_POLICY_SCHEMA_VERSION)
                self.assertEqual(policy["profile"], profile)
                self.assertEqual(validate_edit_policy(policy), policy)
                self.assertTrue(policy["required_capabilities"])
                self.assertTrue(policy["forbidden_actions"])
                self.assertTrue(policy["qa_checks"])
                self.assertEqual(
                    policy["required_capabilities"],
                    sorted(policy["required_capabilities"]),
                )
                self.assertEqual(
                    policy["forbidden_actions"], sorted(policy["forbidden_actions"])
                )
                self.assertEqual(policy["qa_checks"], sorted(policy["qa_checks"]))

    def test_profile_defaults_cover_all_core_edit_dimensions(self):
        expected = {
            "dialogue_talking_head": ("high", "sparse", "sparse", "primary", "supporting", "required", "allowed"),
            "podcast_interview": ("high", "none", "sparse", "primary", "supporting", "required", "allowed"),
            "course_tutorial_screencast": ("medium", "sparse", "sparse", "primary", "optional", "required", "required"),
            "commercial_product": ("high", "medium", "medium", "supporting", "supporting", "required", "recommended"),
            "vlog_travel": ("high", "medium", "sparse", "supporting", "supporting", "required", "allowed"),
            "gaming": ("very_high", "medium", "sparse", "supporting", "optional", "required", "allowed"),
            "wedding_event": ("medium", "sparse", "medium", "supporting", "supporting", "optional", "forbidden"),
            "sports_highlights": ("very_high", "dense", "medium", "supporting", "supporting", "optional", "recommended"),
            "music_performance": ("high", "sparse", "medium", "none", "source_primary", "optional", "forbidden"),
            "real_estate": ("medium", "sparse", "medium", "supporting", "supporting", "optional", "recommended"),
            "documentary_narrative": ("low", "none", "sparse", "primary", "supporting", "required", "recommended"),
            "montage_meme": ("very_high", "dense", "medium", "supporting", "primary", "required", "allowed"),
            "utility_faithful": ("high", "none", "none", "verbatim", "forbidden", "optional", "forbidden"),
        }
        for profile, wanted in expected.items():
            with self.subTest(profile=profile):
                rules = resolve_edit_policy(request(profile=profile))["rules"]
                actual = (
                    rules["cuts"]["density"],
                    rules["sfx"]["density"],
                    rules["transitions"]["density"],
                    rules["dialogue"]["priority"],
                    rules["music"]["usage"],
                    rules["captions"]["usage"],
                    rules["visualizations"]["usage"],
                )
                self.assertEqual(actual, wanted)

    def test_every_profile_has_profile_specific_integrity_rules(self):
        policies = [resolve_edit_policy(request(profile=name)) for name in PROFILE_NAMES]
        for policy in policies:
            self.assertGreater(len(policy["forbidden_actions"]), 4)
            self.assertGreater(len(policy["qa_checks"]), 7)
            self.assertTrue(policy["rules"]["dialogue"]["preserve_meaning"])
            self.assertTrue(policy["rules"]["captions"]["safe_area_required"])
            self.assertTrue(policy["rules"]["visualizations"]["evidence_required"])

    def test_profile_duration_platform_cross_product_is_total(self):
        representatives = (1, 15_001, 60_001, 300_001, 1_800_001)
        for profile in PROFILE_NAMES:
            for duration_ms in representatives:
                for platform in PLATFORMS:
                    with self.subTest(
                        profile=profile,
                        duration_ms=duration_ms,
                        platform=platform,
                    ):
                        policy = resolve_edit_policy(
                            request(
                                profile=profile,
                                duration_ms=duration_ms,
                                platform=platform,
                            )
                        )
                        self.assertEqual(validate_edit_policy(policy), policy)


class EditPolicyDurationAndDeliveryTests(unittest.TestCase):
    def test_duration_band_boundaries_are_closed_and_exhaustive(self):
        cases = {
            1: "micro",
            15_000: "micro",
            15_001: "short",
            60_000: "short",
            60_001: "medium",
            300_000: "medium",
            300_001: "long",
            1_800_000: "long",
            1_800_001: "extended",
            MAX_DURATION_MS: "extended",
        }
        self.assertEqual(DURATION_BANDS, ("micro", "short", "medium", "long", "extended"))
        for duration_ms, band in cases.items():
            with self.subTest(duration_ms=duration_ms):
                self.assertEqual(duration_band(duration_ms), band)
                policy = resolve_edit_policy(
                    request(profile="utility_faithful", duration_ms=duration_ms)
                )
                self.assertEqual(policy["duration"]["band"], band)

    def test_duration_rejects_bool_zero_negative_and_over_day(self):
        for value in (True, False, 0, -1, MAX_DURATION_MS + 1, 1.5, "1000"):
            with self.subTest(value=value), self.assertRaises(EditPolicyError):
                resolve_edit_policy(request(duration_ms=value))

    def test_every_platform_auto_aspect_resolves_to_an_allowed_aspect(self):
        self.assertEqual(set(PLATFORMS), {
            "youtube", "youtube_shorts", "tiktok", "instagram_reels",
            "instagram_feed", "facebook", "x", "linkedin", "web",
            "broadcast", "archive",
        })
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                policy = resolve_edit_policy(request(platform=platform))
                self.assertIn(policy["delivery"]["aspect"], ASPECTS)
                self.assertEqual(
                    policy["resolution_sources"]["aspect"], "platform"
                )

    def test_explicit_compatible_aspect_is_recorded(self):
        policy = resolve_edit_policy(request(platform="instagram_feed", aspect="1:1"))
        self.assertEqual(policy["delivery"]["aspect"], "1:1")
        self.assertEqual(policy["resolution_sources"]["aspect"], "explicit_intent")

    def test_incompatible_and_unknown_aspects_fail_closed(self):
        for platform, aspect in (("tiktok", "16:9"), ("broadcast", "9:16"), ("web", "3:2")):
            with self.subTest(platform=platform, aspect=aspect), self.assertRaises(EditPolicyError):
                resolve_edit_policy(request(platform=platform, aspect=aspect))


class EditPolicyPrecedenceTests(unittest.TestCase):
    def test_explicit_intent_beats_platform(self):
        raw = request(platform="tiktok")
        raw["explicit_intent"]["caption_rule"] = "forbidden"
        policy = resolve_edit_policy(raw)
        self.assertEqual(policy["rules"]["captions"]["usage"], "forbidden")
        self.assertEqual(
            policy["resolution_sources"]["caption_rule"], "explicit_intent"
        )

    def test_platform_beats_profile(self):
        policy = resolve_edit_policy(
            request(profile="music_performance", platform="tiktok")
        )
        self.assertEqual(policy["rules"]["captions"]["usage"], "required")
        self.assertEqual(policy["resolution_sources"]["caption_rule"], "platform")

    def test_profile_beats_duration(self):
        policy = resolve_edit_policy(
            request(profile="documentary_narrative", duration_ms=5_000)
        )
        self.assertEqual(policy["rules"]["cuts"]["density"], "low")
        self.assertEqual(policy["resolution_sources"]["cut_density"], "profile")

    def test_duration_beats_consented_preference_when_profile_abstains(self):
        raw = request(profile="podcast_interview", duration_ms=2_000_000)
        raw["consented_preferences"]["consented"] = True
        raw["consented_preferences"]["values"]["cut_density"] = "very_high"
        policy = resolve_edit_policy(raw)
        self.assertEqual(policy["rules"]["cuts"]["density"], "very_low")
        self.assertEqual(policy["resolution_sources"]["cut_density"], "duration")

    def test_consented_preference_fills_a_dimension_on_which_higher_layers_abstain(self):
        raw = request(profile="vlog_travel")
        raw["consented_preferences"]["consented"] = True
        raw["consented_preferences"]["values"]["transition_density"] = "dense"
        policy = resolve_edit_policy(raw)
        self.assertEqual(policy["rules"]["transitions"]["density"], "dense")
        self.assertEqual(
            policy["resolution_sources"]["transition_density"],
            "consented_preferences",
        )

    def test_unconsented_preferences_are_rejected_not_silently_used(self):
        raw = request(profile="vlog_travel")
        raw["consented_preferences"]["values"]["transition_density"] = "dense"
        with self.assertRaisesRegex(EditPolicyError, "unconsented"):
            resolve_edit_policy(raw)

    def test_hard_invariant_beats_explicit_intent_by_rejecting_conflict(self):
        conflicts = (
            ("utility_faithful", "sfx_density", "dense"),
            ("utility_faithful", "music_rule", "primary"),
            ("music_performance", "music_rule", "forbidden"),
            ("course_tutorial_screencast", "visualization_rule", "allowed"),
        )
        for profile, field, value in conflicts:
            raw = request(profile=profile)
            raw["explicit_intent"][field] = value
            with self.subTest(profile=profile, field=field), self.assertRaisesRegex(
                EditPolicyError, "hard invariant"
            ):
                resolve_edit_policy(raw)

    def test_hard_invariants_are_auditable_in_resolution_sources(self):
        policy = resolve_edit_policy(request(profile="utility_faithful"))
        for field in (
            "sfx_density", "transition_density", "dialogue_rule",
            "music_rule", "visualization_rule",
        ):
            self.assertEqual(policy["resolution_sources"][field], "hard_invariant")

    def test_forbidden_effect_grammars_cannot_resolve_nonzero_density(self):
        for profile in ("podcast_interview", "documentary_narrative"):
            raw = request(profile=profile)
            raw["explicit_intent"]["sfx_density"] = "sparse"
            with self.subTest(profile=profile), self.assertRaisesRegex(
                EditPolicyError, "forbids added SFX"
            ):
                resolve_edit_policy(raw)


class EditPolicyCapabilityGateTests(unittest.TestCase):
    def test_each_derived_required_capability_is_individually_gated(self):
        raw = request(profile="sports_highlights")
        policy = resolve_edit_policy(raw)
        for capability in policy["required_capabilities"]:
            broken = copy.deepcopy(raw)
            broken["available_capabilities"].remove(capability)
            with self.subTest(capability=capability), self.assertRaisesRegex(
                EditPolicyError, "capability gate failed"
            ):
                resolve_edit_policy(broken)

    def test_unknown_and_duplicate_capabilities_fail_closed(self):
        unknown = request()
        unknown["available_capabilities"].append("telepathy")
        duplicate = request()
        duplicate["available_capabilities"].append(
            duplicate["available_capabilities"][0]
        )
        for raw in (unknown, duplicate):
            with self.assertRaises(EditPolicyError):
                resolve_edit_policy(raw)

    def test_rule_changes_derive_corresponding_capabilities_and_qa(self):
        raw = request(profile="utility_faithful")
        # Use a profile without the faithful hard gate for explicit effects.
        raw["profile"] = "dialogue_talking_head"
        raw["explicit_intent"]["sfx_density"] = "dense"
        raw["explicit_intent"]["transition_density"] = "dense"
        raw["explicit_intent"]["visualization_rule"] = "required"
        policy = resolve_edit_policy(raw)
        for capability in (
            "project_generated_sfx", "audio_crossfades", "cross_dissolves",
            "motion_quality_analysis", "graphic_rendering",
        ):
            self.assertIn(capability, policy["required_capabilities"])
        self.assertIn("sfx_motivation_and_masking_verified", policy["qa_checks"])
        self.assertIn(
            "sfx_generation_and_rights_receipt_verified", policy["qa_checks"]
        )
        self.assertNotIn("licensed_sfx", policy["required_capabilities"])
        self.assertIn("transition_motivation_verified", policy["qa_checks"])
        self.assertIn("visualization_data_provenance_verified", policy["qa_checks"])

    def test_verbatim_captions_require_word_grounding_capabilities(self):
        raw = request(profile="music_performance")
        raw["explicit_intent"]["caption_rule"] = "verbatim_required"
        policy = resolve_edit_policy(raw)
        self.assertIn("speech_transcription", policy["required_capabilities"])
        self.assertIn("word_timestamps", policy["required_capabilities"])

    def test_extra_available_capabilities_do_not_change_contract_hash(self):
        full = request(profile="utility_faithful")
        full_policy = resolve_edit_policy(full)
        minimal = copy.deepcopy(full)
        minimal["available_capabilities"] = full_policy["required_capabilities"]
        minimal_policy = resolve_edit_policy(minimal)
        self.assertEqual(full_policy, minimal_policy)
        self.assertEqual(edit_policy_sha256(full_policy), edit_policy_sha256(minimal_policy))


class EditPolicyClosedContractTests(unittest.TestCase):
    def test_unknown_profile_schema_and_nested_properties_fail_closed(self):
        mutations = []
        bad = request()
        bad["profile"] = "everything_world_class"
        mutations.append(bad)
        bad = request()
        bad["schema_version"] = "autoeditor-edit-policy-request/v2"
        mutations.append(bad)
        bad = request()
        bad["surprise"] = True
        mutations.append(bad)
        bad = request()
        bad["delivery"]["fps"] = 60
        mutations.append(bad)
        bad = request()
        bad["explicit_intent"]["glitch_pack"] = "maximum"
        mutations.append(bad)
        bad = request()
        bad["consented_preferences"]["source"] = "implicit_tracking"
        mutations.append(bad)
        for index, raw in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(EditPolicyError):
                resolve_edit_policy(raw)

    def test_every_input_nested_object_requires_every_contract_key(self):
        paths = (
            ("delivery", "aspect"),
            ("explicit_intent", "music_rule"),
            ("consented_preferences", "consented"),
        )
        for outer, inner in paths:
            raw = request()
            del raw[outer][inner]
            with self.subTest(path=f"{outer}.{inner}"), self.assertRaises(EditPolicyError):
                resolve_edit_policy(raw)
        raw = request()
        del raw["consented_preferences"]["values"]["caption_rule"]
        with self.assertRaises(EditPolicyError):
            resolve_edit_policy(raw)

    def test_unknown_enum_members_and_type_confusion_fail_closed(self):
        mutations = []
        bad = request()
        bad["explicit_intent"]["cut_density"] = "maximum"
        mutations.append(bad)
        bad = request()
        bad["explicit_intent"]["caption_rule"] = True
        mutations.append(bad)
        bad = request()
        bad["consented_preferences"]["consented"] = 1
        mutations.append(bad)
        bad = request()
        bad["available_capabilities"] = "hard_cuts"
        mutations.append(bad)
        for raw in mutations:
            with self.assertRaises(EditPolicyError):
                resolve_edit_policy(raw)

    def test_resolved_policy_rejects_extra_missing_and_inconsistent_fields(self):
        original = resolve_edit_policy(request())
        mutations = []
        bad = copy.deepcopy(original)
        bad["debug"] = True
        mutations.append(bad)
        bad = copy.deepcopy(original)
        del bad["rules"]["music"]["usage"]
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["duration"]["band"] = "extended"
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["rules"]["dialogue"]["preserve_meaning"] = False
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["rules"]["captions"]["max_lines"] = 3
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["rules"]["visualizations"]["evidence_required"] = False
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["required_capabilities"] = bad["required_capabilities"][:-1]
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["forbidden_actions"] = list(reversed(bad["forbidden_actions"]))
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["qa_checks"].append("looks_good_to_model")
        mutations.append(bad)
        for index, policy in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(EditPolicyError):
                validate_edit_policy(policy)

    def test_profile_specific_detail_cannot_be_mutated_to_another_genre(self):
        original = resolve_edit_policy(request(profile="documentary_narrative"))
        for path, replacement in (
            (("cuts", "motivation"), "retention_motivated"),
            (("cuts", "j_l_cuts"), "forbidden"),
            (("sfx", "usage"), "event_accent_only"),
            (("transitions", "usage"), "beat_or_phrase_motivated"),
        ):
            bad = copy.deepcopy(original)
            bad["rules"][path[0]][path[1]] = replacement
            with self.subTest(path=path), self.assertRaises(EditPolicyError):
                validate_edit_policy(bad)

    def test_random_single_mutations_fail_closed(self):
        rng = random.Random(29_481)
        base = request(profile="utility_faithful")
        mutators = (
            lambda raw: raw.update(profile="unknown"),
            lambda raw: raw.update(duration_ms=0),
            lambda raw: raw["delivery"].update(aspect="2:3"),
            lambda raw: raw["explicit_intent"].update(sfx_density="maximum"),
            lambda raw: raw["available_capabilities"].append("unknown"),
            lambda raw: raw["consented_preferences"]["values"].update(caption_rule="sometimes"),
        )
        for _ in range(100):
            raw = copy.deepcopy(base)
            rng.choice(mutators)(raw)
            with self.assertRaises(EditPolicyError):
                resolve_edit_policy(raw)


class EditPolicyCanonicalTests(unittest.TestCase):
    def test_canonical_json_and_hash_are_independently_reproducible(self):
        policy = resolve_edit_policy(request(profile="commercial_product"))
        encoded = canonical_edit_policy_json(policy)
        self.assertNotIn(" ", encoded)
        self.assertNotIn("\n", encoded)
        self.assertEqual(json.loads(encoded), policy)
        expected = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.assertEqual(edit_policy_sha256(policy), expected)
        self.assertRegex(expected, r"^[0-9a-f]{64}$")

    def test_input_mapping_and_capability_order_do_not_change_policy_or_hash(self):
        first = request(profile="real_estate", platform="instagram_feed")
        second = copy.deepcopy(first)
        second["available_capabilities"] = list(reversed(second["available_capabilities"]))
        second = {key: second[key] for key in reversed(tuple(second))}
        policy_a = resolve_edit_policy(first)
        policy_b = resolve_edit_policy(second)
        self.assertEqual(policy_a, policy_b)
        self.assertEqual(edit_policy_sha256(policy_a), edit_policy_sha256(policy_b))

    def test_hash_changes_for_material_policy_change(self):
        base = resolve_edit_policy(request(profile="dialogue_talking_head"))
        raw = request(profile="dialogue_talking_head")
        raw["explicit_intent"]["cut_density"] = "very_high"
        changed = resolve_edit_policy(raw)
        self.assertNotEqual(edit_policy_sha256(base), edit_policy_sha256(changed))

    def test_validation_returns_a_detached_copy(self):
        policy = resolve_edit_policy(request())
        validated = validate_edit_policy(policy)
        validated["rules"]["cuts"]["density"] = "very_low"
        self.assertEqual(policy["rules"]["cuts"]["density"], "high")


if __name__ == "__main__":
    unittest.main()
