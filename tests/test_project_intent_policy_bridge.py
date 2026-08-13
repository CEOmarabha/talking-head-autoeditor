from __future__ import annotations

import copy
import unittest

from autoeditor.edit_policy import (
    CAPABILITIES,
    MAX_DURATION_MS,
    PROFILE_NAMES,
    edit_policy_sha256,
)
from autoeditor.project_intent_policy_bridge import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_MANIFEST_SOURCE,
    CURRENT_RUNTIME_CAPABILITIES,
    PROJECT_INTENT_SCHEMA_VERSION,
    ProjectIntentPolicyBridgeError,
    build_edit_policy_request,
    resolve_project_intent_policy,
    validate_capability_manifest,
    validate_project_intent,
)


EXPECTED_CURRENT_RUNTIME_CAPABILITIES = {
    "artifact_receipts",
    "audio_crossfades",
    "audio_quality_analysis",
    "caption_rendering",
    "chart_rendering",
    "color_normalization",
    "cross_dissolves",
    "dialogue_cleanup",
    "graphic_rendering",
    "hard_cuts",
    "loudness_normalization",
    "motion_quality_analysis",
    "project_generated_music",
    "project_generated_sfx",
    "scene_detection",
    "speech_transcription",
    "visual_quality_analysis",
    "word_timestamps",
}


def preferences(**overrides: str) -> dict[str, dict[str, object]]:
    values = {
        "captions": "auto",
        "graphics": "auto",
        "music": "auto",
        "sfx": "auto",
        "transitions": "auto",
    }
    values.update(overrides)
    return {
        name: {"enabled": preference != "none", "preference": preference}
        for name, preference in values.items()
    }


def intent(
    *,
    profile: str = "dialogue_talking_head",
    minimum_ms: int = 30_000,
    maximum_ms: int = 45_000,
    platform: str = "youtube",
    aspect: str = "16:9",
    preference_overrides: dict[str, str] | None = None,
) -> dict:
    return {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": profile,
        "delivery": {"platform": platform, "aspect": aspect},
        "target_duration": {"min_ms": minimum_ms, "max_ms": maximum_ms},
        "preferences": preferences(**(preference_overrides or {})),
    }


def manifest(
    capabilities: set[str] | frozenset[str] = CAPABILITIES,
    **overrides: object,
) -> dict:
    value = {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": "a" * 64,
        "available_capabilities": sorted(capabilities),
    }
    value.update(overrides)
    return value


class ProjectIntentValidationTests(unittest.TestCase):
    def test_validates_and_detaches_the_exact_javascript_contract(self):
        raw = intent(preference_overrides={"captions": "verbatim", "music": "none"})
        clean = validate_project_intent(raw)
        self.assertEqual(clean, raw)
        self.assertIsNot(clean, raw)
        self.assertIsNot(clean["delivery"], raw["delivery"])
        self.assertIsNot(clean["preferences"], raw["preferences"])
        raw["preferences"]["captions"]["preference"] = "selective"
        self.assertEqual(clean["preferences"]["captions"]["preference"], "verbatim")

    def test_rejects_unknown_missing_and_mistyped_properties(self):
        mutations = []
        candidate = intent()
        candidate["extra"] = True
        mutations.append(candidate)
        candidate = intent()
        del candidate["delivery"]
        mutations.append(candidate)
        candidate = intent()
        candidate["delivery"]["extra"] = True
        mutations.append(candidate)
        candidate = intent()
        candidate["target_duration"]["min_ms"] = True
        mutations.append(candidate)
        candidate = intent()
        candidate["preferences"]["captions"]["enabled"] = 1
        mutations.append(candidate)
        candidate = intent()
        candidate["preferences"]["extra"] = {
            "enabled": False,
            "preference": "none",
        }
        mutations.append(candidate)
        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ProjectIntentPolicyBridgeError):
                    validate_project_intent(candidate)

    def test_rejects_enabled_preference_inconsistency(self):
        candidate = intent()
        candidate["preferences"]["music"] = {"enabled": False, "preference": "auto"}
        with self.assertRaisesRegex(
            ProjectIntentPolicyBridgeError, "must be none when disabled"
        ):
            validate_project_intent(candidate)
        candidate = intent()
        candidate["preferences"]["music"] = {"enabled": True, "preference": "none"}
        with self.assertRaisesRegex(
            ProjectIntentPolicyBridgeError, "cannot be none when enabled"
        ):
            validate_project_intent(candidate)

    def test_rejects_platform_aspect_mismatch(self):
        with self.assertRaisesRegex(ProjectIntentPolicyBridgeError, "incompatible"):
            validate_project_intent(intent(platform="youtube_shorts", aspect="16:9"))

    def test_rejects_unknown_versions_profiles_and_preference_members(self):
        cases = []
        candidate = intent()
        candidate["schema_version"] = "autoeditor-project-intent/v2"
        cases.append(candidate)
        candidate = intent()
        candidate["profile"] = "generic_short"
        cases.append(candidate)
        candidate = intent()
        candidate["preferences"]["sfx"]["preference"] = "cinematic"
        cases.append(candidate)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ProjectIntentPolicyBridgeError):
                    validate_project_intent(candidate)

    def test_duration_boundaries_match_the_javascript_contract(self):
        for minimum, maximum in (
            (1, 1),
            (1, 15_000),
            (MAX_DURATION_MS, MAX_DURATION_MS),
        ):
            with self.subTest(minimum=minimum, maximum=maximum):
                self.assertEqual(
                    validate_project_intent(
                        intent(minimum_ms=minimum, maximum_ms=maximum)
                    )["target_duration"],
                    {"min_ms": minimum, "max_ms": maximum},
                )
        for minimum, maximum in (
            (0, 1),
            (2, 1),
            (1, MAX_DURATION_MS + 1),
            (1.0, 2),
            (True, 2),
        ):
            with self.subTest(minimum=minimum, maximum=maximum):
                with self.assertRaises(ProjectIntentPolicyBridgeError):
                    validate_project_intent(
                        intent(minimum_ms=minimum, maximum_ms=maximum)
                    )

    def test_rejects_non_object_roots(self):
        for candidate in (None, [], "intent", 3, True):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ProjectIntentPolicyBridgeError):
                    validate_project_intent(candidate)


class CapabilityManifestTests(unittest.TestCase):
    def test_current_runtime_surface_is_explicit_and_conservative(self):
        self.assertEqual(CURRENT_RUNTIME_CAPABILITIES, EXPECTED_CURRENT_RUNTIME_CAPABILITIES)
        self.assertLess(CURRENT_RUNTIME_CAPABILITIES, CAPABILITIES)

    def test_validates_and_detaches_a_receipt_bound_manifest(self):
        raw = manifest(CURRENT_RUNTIME_CAPABILITIES)
        clean = validate_capability_manifest(raw)
        self.assertEqual(clean, raw)
        self.assertIsNot(clean, raw)
        self.assertIsNot(clean["available_capabilities"], raw["available_capabilities"])
        raw["available_capabilities"].clear()
        self.assertEqual(
            clean["available_capabilities"], sorted(CURRENT_RUNTIME_CAPABILITIES)
        )

    def test_rejects_untrusted_or_malformed_manifests(self):
        cases = []
        candidate = manifest()
        candidate["extra"] = True
        cases.append(candidate)
        candidate = manifest(schema_version="autoeditor-capability-manifest/v2")
        cases.append(candidate)
        candidate = manifest(source="model_claim")
        cases.append(candidate)
        candidate = manifest(probe_receipt_sha256="A" * 64)
        cases.append(candidate)
        candidate = manifest(probe_receipt_sha256="a" * 63)
        cases.append(candidate)
        candidate = manifest(available_capabilities="hard_cuts")
        cases.append(candidate)
        candidate = manifest(available_capabilities=["hard_cuts", 7])
        cases.append(candidate)
        candidate = manifest()
        candidate["available_capabilities"].reverse()
        cases.append(candidate)
        candidate = manifest()
        candidate["available_capabilities"].append(
            candidate["available_capabilities"][0]
        )
        cases.append(candidate)
        candidate = manifest()
        candidate["available_capabilities"].append("telepathy")
        candidate["available_capabilities"].sort()
        cases.append(candidate)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ProjectIntentPolicyBridgeError):
                    validate_capability_manifest(candidate)

    def test_empty_capability_manifest_is_valid_but_cannot_pass_policy_gates(self):
        empty = validate_capability_manifest(manifest(set()))
        self.assertEqual(empty["available_capabilities"], [])
        with self.assertRaisesRegex(ProjectIntentPolicyBridgeError, "capability gate failed"):
            resolve_project_intent_policy(intent(), empty)


class BridgeMappingTests(unittest.TestCase):
    def test_maps_supported_preferences_without_inventing_density(self):
        project = intent(
            preference_overrides={
                "captions": "verbatim",
                "graphics": "none",
                "music": "none",
                "sfx": "motivated_only",
                "transitions": "hard_cut_only",
            }
        )
        request = build_edit_policy_request(project, manifest())
        self.assertEqual(request["profile"], "dialogue_talking_head")
        self.assertEqual(request["duration_ms"], 45_000)
        self.assertEqual(request["delivery"], project["delivery"])
        self.assertEqual(
            request["explicit_intent"],
            {
                "cut_density": "auto",
                "sfx_density": "auto",
                "transition_density": "none",
                "dialogue_rule": "auto",
                "music_rule": "forbidden",
                "caption_rule": "verbatim_required",
                "visualization_rule": "forbidden",
            },
        )
        self.assertEqual(
            request["consented_preferences"],
            {
                "consented": False,
                "values": {
                    "cut_density": "auto",
                    "sfx_density": "auto",
                    "transition_density": "auto",
                    "dialogue_rule": "auto",
                    "music_rule": "auto",
                    "caption_rule": "auto",
                    "visualization_rule": "auto",
                },
            },
        )
        self.assertEqual(request["available_capabilities"], sorted(CAPABILITIES))

    def test_maps_each_supported_caption_and_music_preference(self):
        expected_captions = {
            "auto": "auto",
            "none": "forbidden",
            "verbatim": "verbatim_required",
        }
        for source, target in expected_captions.items():
            with self.subTest(feature="captions", source=source):
                request = build_edit_policy_request(
                    intent(preference_overrides={"captions": source}), manifest()
                )
                self.assertEqual(request["explicit_intent"]["caption_rule"], target)
        expected_music = {
            "auto": "auto",
            "none": "forbidden",
            "primary": "primary",
            "source_primary": "source_primary",
            "supporting": "supporting",
        }
        for source, target in expected_music.items():
            with self.subTest(feature="music", source=source):
                request = build_edit_policy_request(
                    intent(preference_overrides={"music": source}), manifest()
                )
                self.assertEqual(request["explicit_intent"]["music_rule"], target)

    def test_rejects_preferences_v1_cannot_preserve(self):
        unsupported = [
            ("captions", "selective"),
            ("graphics", "brand_led"),
            ("graphics", "data_driven"),
            ("graphics", "informational"),
            ("graphics", "minimal"),
        ]
        for feature, preference in unsupported:
            with self.subTest(feature=feature, preference=preference):
                with self.assertRaisesRegex(
                    ProjectIntentPolicyBridgeError, "cannot represent"
                ):
                    build_edit_policy_request(
                        intent(preference_overrides={feature: preference}), manifest()
                    )

    def test_same_band_duration_uses_conservative_maximum(self):
        request = build_edit_policy_request(
            intent(minimum_ms=15_001, maximum_ms=60_000), manifest()
        )
        self.assertEqual(request["duration_ms"], 60_000)

    def test_rejects_every_duration_range_that_crosses_a_policy_band(self):
        for boundary in (15_000, 60_000, 300_000, 1_800_000):
            with self.subTest(boundary=boundary):
                with self.assertRaisesRegex(
                    ProjectIntentPolicyBridgeError, "crosses edit-policy duration bands"
                ):
                    build_edit_policy_request(
                        intent(minimum_ms=boundary, maximum_ms=boundary + 1), manifest()
                    )

    def test_request_is_detached_from_both_inputs(self):
        project = intent(preference_overrides={"music": "none"})
        capability_manifest = manifest()
        request = build_edit_policy_request(project, capability_manifest)
        project["delivery"]["aspect"] = "9:16"
        capability_manifest["available_capabilities"].clear()
        self.assertEqual(request["delivery"]["aspect"], "16:9")
        self.assertEqual(request["available_capabilities"], sorted(CAPABILITIES))


class BridgeResolutionTests(unittest.TestCase):
    def test_resolves_a_supported_intent_through_the_real_policy_contract(self):
        policy = resolve_project_intent_policy(
            intent(
                preference_overrides={
                    "captions": "verbatim",
                    "graphics": "none",
                    "music": "none",
                    "sfx": "motivated_only",
                    "transitions": "motivated_only",
                }
            ),
            manifest(),
        )
        self.assertEqual(policy["duration"], {"duration_ms": 45_000, "band": "short"})
        self.assertEqual(policy["rules"]["captions"]["usage"], "verbatim_required")
        self.assertEqual(policy["rules"]["music"]["usage"], "forbidden")
        self.assertEqual(policy["rules"]["sfx"]["usage"], "motivated_only")
        self.assertNotEqual(policy["rules"]["sfx"]["density"], "none")
        self.assertEqual(policy["rules"]["transitions"]["usage"], "motivated_only")
        self.assertNotEqual(policy["rules"]["transitions"]["density"], "none")

    def test_rejects_profile_grammar_mismatch_for_typed_effect_preferences(self):
        for feature, preference in (
            ("sfx", "event_accent_only"),
            ("transitions", "location_motivated"),
        ):
            with self.subTest(feature=feature, preference=preference):
                with self.assertRaisesRegex(
                    ProjectIntentPolicyBridgeError, "does not support requested"
                ):
                    resolve_project_intent_policy(
                        intent(preference_overrides={feature: preference}), manifest()
                    )

    def test_hard_cut_only_is_faithfully_represented_by_zero_transition_density(self):
        policy = resolve_project_intent_policy(
            intent(preference_overrides={"transitions": "hard_cut_only"}), manifest()
        )
        self.assertEqual(policy["rules"]["transitions"]["density"], "none")

    def test_missing_required_capability_fails_closed(self):
        capabilities = set(CAPABILITIES) - {"hard_cuts"}
        with self.assertRaisesRegex(
            ProjectIntentPolicyBridgeError, "missing: hard_cuts"
        ):
            resolve_project_intent_policy(intent(), manifest(capabilities))

    def test_current_runtime_resolves_only_profiles_with_verified_requirements(self):
        failures = {}
        resolved = set()
        for profile in sorted(PROFILE_NAMES):
            disabled = {
                "captions": "none",
                "graphics": "auto" if profile == "course_tutorial_screencast" else "none",
                "music": "auto" if profile == "music_performance" else "none",
                "sfx": "none",
                "transitions": "none",
            }
            with self.subTest(profile=profile):
                try:
                    resolve_project_intent_policy(
                        intent(profile=profile, preference_overrides=disabled),
                        manifest(CURRENT_RUNTIME_CAPABILITIES),
                    )
                except ProjectIntentPolicyBridgeError as error:
                    self.assertIn("capability gate failed", str(error))
                    failures[profile] = str(error)
                else:
                    resolved.add(profile)
        self.assertEqual(
            resolved,
            {"commercial_product", "dialogue_talking_head", "utility_faithful"},
        )
        self.assertEqual(set(failures), set(PROFILE_NAMES) - resolved)
        self.assertIn("multicam_sync", failures["podcast_interview"])
        self.assertIn("motion_tracking", failures["course_tutorial_screencast"])

    def test_extra_verified_capabilities_do_not_change_the_policy_hash(self):
        project = intent(
            preference_overrides={
                "graphics": "none",
                "music": "none",
                "sfx": "none",
                "transitions": "none",
            }
        )
        full = resolve_project_intent_policy(project, manifest())
        minimal = resolve_project_intent_policy(
            project, manifest(set(full["required_capabilities"]))
        )
        self.assertEqual(edit_policy_sha256(full), edit_policy_sha256(minimal))

    def test_resolution_does_not_mutate_inputs(self):
        project = intent()
        capability_manifest = manifest()
        before_project = copy.deepcopy(project)
        before_manifest = copy.deepcopy(capability_manifest)
        resolve_project_intent_policy(project, capability_manifest)
        self.assertEqual(project, before_project)
        self.assertEqual(capability_manifest, before_manifest)


if __name__ == "__main__":
    unittest.main()
