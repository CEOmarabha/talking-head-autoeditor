import copy
import hashlib
import json
import math
import unittest

from autoeditor.edit_policy import (
    CAPABILITIES,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    edit_policy_sha256,
    resolve_edit_policy,
)
from autoeditor.sfx_plan import (
    DUCK_ATTENUATIONS_MILLIDB,
    DUCK_SIDECHAIN_THRESHOLD_TEXT,
    SFX_COMPILE_RECEIPT_SCHEMA_VERSION,
    SFX_COMPILE_RECEIPT_JSON_SCHEMA,
    SFX_CUE_MANIFEST_JSON_SCHEMA,
    SFX_CUE_MANIFEST_SCHEMA_VERSION,
    SFX_PLAN_JSON_SCHEMA,
    SFX_PLAN_SCHEMA_VERSION,
    SfxPlanError,
    canonical_sfx_compile_receipt_json,
    canonical_sfx_cue_manifest_json,
    canonical_sfx_plan_json,
    compile_sfx_plan,
    density_cue_limit,
    derive_sfx_anchor_id,
    derive_sfx_asset_id,
    derive_sfx_cue_id,
    derive_sfx_policy_limits,
    derive_speech_window_id,
    sfx_compile_receipt_sha256,
    sfx_cue_manifest_sha256,
    sfx_plan_sha256,
    validate_sfx_cue_manifest,
    validate_sfx_plan,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _policy(profile: str = "dialogue_talking_head", duration_ms: int = 60_000):
    values = {
        "cut_density": "auto",
        "sfx_density": "auto",
        "transition_density": "auto",
        "dialogue_rule": "auto",
        "music_rule": "auto",
        "caption_rule": "auto",
        "visualization_rule": "auto",
    }
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": profile,
        "duration_ms": duration_ms,
        "delivery": {"platform": "web", "aspect": "auto"},
        "explicit_intent": dict(values),
        "consented_preferences": {
            "consented": False,
            "values": dict(values),
        },
        "available_capabilities": sorted(CAPABILITIES),
    })


def _asset(
    name: str,
    provenance: str,
    *,
    duration_ms: int = 3_000,
    sample_rate_hz: int = 48_000,
    channels: int = 2,
):
    if provenance == "project_generated":
        scheme = "project-generated"
        license_value = {
            "basis": "project_owned",
            "license_id": "project-generated",
            "licensor": "project",
            "evidence_sha256": _hash(name + "-generation-receipt"),
        }
    elif provenance == "user_supplied":
        scheme = "user-supplied"
        license_value = {
            "basis": "user_authorized",
            "license_id": "user-consent-" + name,
            "licensor": "user",
            "evidence_sha256": _hash(name + "-user-consent"),
        }
    else:
        scheme = "licensed-external"
        license_value = {
            "basis": "licensed_external",
            "license_id": "stock-license-" + name,
            "licensor": "Sound Vendor",
            "evidence_sha256": _hash(name + "-license-document"),
        }
    payload = {
        "sha256": _hash(name + "-audio-bytes"),
        "byte_length": 10_000 + len(name),
        "duration_ms": duration_ms,
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
        "source_ref": f"{scheme}://cues/{name}.wav",
        "provenance": provenance,
        "license": license_value,
    }
    return {"asset_id": derive_sfx_asset_id(payload), **payload}


def _anchor(category: str, reference_id: str, time_ms: int):
    payload = {
        "category": category,
        "reference_id": reference_id,
        "time_ms": time_ms,
        "evidence_start_ms": time_ms - 100,
        "evidence_end_ms": time_ms + 100,
        "evidence_sha256": _hash(reference_id + "-evidence"),
    }
    return {"anchor_id": derive_sfx_anchor_id(payload, 60_000), **payload}


def _speech(start_ms: int, end_ms: int):
    payload = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "evidence_sha256": _hash(f"speech-{start_ms}-{end_ms}"),
    }
    return {"speech_id": derive_speech_window_id(payload, 60_000), **payload}


def _manifest():
    assets = [
        _asset("generated-whoosh", "project_generated"),
        _asset("user-click", "user_supplied"),
        _asset("licensed-impact", "licensed_external"),
        _asset("licensed-whoosh", "licensed_external"),
    ]
    anchors = [
        _anchor("event", "event-product-drop", 5_000),
        _anchor("boundary", "boundary-" + _hash("cut-a"), 25_000),
        _anchor("interface_feedback", "interface-submit-button", 45_000),
    ]
    return {
        "schema_version": SFX_CUE_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": _hash("compiled-output-timeline"),
        "output_duration_ms": 60_000,
        "output_sample_rate_hz": 48_000,
        "output_channels": 2,
        "assets": sorted(assets, key=lambda item: item["asset_id"]),
        "anchors": sorted(anchors, key=lambda item: (item["time_ms"], item["anchor_id"])),
        "speech_windows": [_speech(5_000, 5_500)],
    }


def _asset_by_name(manifest, fragment: str):
    return next(item for item in manifest["assets"] if fragment in item["source_ref"])


def _anchor_by_category(manifest, category: str):
    return next(item for item in manifest["anchors"] if item["category"] == category)


def _cue(
    asset,
    anchor,
    *,
    kind: str,
    start_ms: int,
    trim_duration_ms: int = 1_000,
    gain_millidb: int = -6_000,
    attack_fade_ms: int = 50,
    release_fade_ms: int = 100,
    ducking=None,
):
    payload = {
        "asset_id": asset["asset_id"],
        "asset_sha256": asset["sha256"],
        "kind": kind,
        "motivation": {
            "category": anchor["category"],
            "anchor_id": anchor["anchor_id"],
            "reference_id": anchor["reference_id"],
            "anchor_ms": anchor["time_ms"],
            "evidence_start_ms": anchor["evidence_start_ms"],
            "evidence_end_ms": anchor["evidence_end_ms"],
            "evidence_sha256": anchor["evidence_sha256"],
        },
        "placement": {
            "start_ms": start_ms,
            "trim_start_ms": 0,
            "trim_duration_ms": trim_duration_ms,
            "gain_millidb": gain_millidb,
            "attack_fade_ms": attack_fade_ms,
            "release_fade_ms": release_fade_ms,
        },
        "ducking": copy.deepcopy(ducking),
    }
    return {"cue_id": derive_sfx_cue_id(payload), **payload}


def _refresh_cue_id(cue):
    payload = {key: copy.deepcopy(value) for key, value in cue.items() if key != "cue_id"}
    cue["cue_id"] = derive_sfx_cue_id(payload)


def _default_cues(manifest):
    event = _anchor_by_category(manifest, "event")
    boundary = _anchor_by_category(manifest, "boundary")
    return [
        _cue(
            _asset_by_name(manifest, "licensed-impact"),
            event,
            kind="impact",
            start_ms=5_000,
            ducking={
                "start_ms": 5_000,
                "end_ms": 5_500,
                "attenuation_millidb": 12_000,
                "attack_ms": 20,
                "release_ms": 200,
            },
        ),
        _cue(
            _asset_by_name(manifest, "generated-whoosh"),
            boundary,
            kind="whoosh",
            start_ms=24_500,
            trim_duration_ms=1_500,
            gain_millidb=-9_000,
        ),
    ]


def _plan(manifest=None, policy=None, cues=None):
    manifest = _manifest() if manifest is None else manifest
    policy = _policy() if policy is None else policy
    cues = _default_cues(manifest) if cues is None else cues
    cues = sorted(copy.deepcopy(cues), key=lambda cue: (cue["placement"]["start_ms"], cue["cue_id"]))
    return {
        "schema_version": SFX_PLAN_SCHEMA_VERSION,
        "cue_manifest_sha256": sfx_cue_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "output_timeline_sha256": manifest["output_timeline_sha256"],
        "output_duration_ms": manifest["output_duration_ms"],
        "policy": derive_sfx_policy_limits(policy, manifest["output_duration_ms"]),
        "cues": cues,
    }


def _contains_float(value):
    if type(value) is float:
        return True
    if type(value) is dict:
        return any(_contains_float(item) for item in value.values())
    if type(value) is list:
        return any(_contains_float(item) for item in value)
    return False


class SfxPlanTests(unittest.TestCase):
    def assert_rejected(self, plan, manifest=None, policy=None):
        manifest = _manifest() if manifest is None else manifest
        policy = _policy() if policy is None else policy
        with self.assertRaises(SfxPlanError):
            validate_sfx_plan(plan, manifest, policy)

    def test_trusted_manifest_binds_all_three_provenance_and_license_classes(self):
        manifest = _manifest()
        clean = validate_sfx_cue_manifest(manifest)
        self.assertEqual(clean, manifest)
        self.assertIsNot(clean, manifest)
        observed = {
            item["provenance"]: item["license"]["basis"]
            for item in clean["assets"]
        }
        self.assertEqual(observed, {
            "project_generated": "project_owned",
            "user_supplied": "user_authorized",
            "licensed_external": "licensed_external",
        })
        for asset in clean["assets"]:
            payload = {key: copy.deepcopy(value) for key, value in asset.items() if key != "asset_id"}
            self.assertEqual(asset["asset_id"], derive_sfx_asset_id(payload))

    def test_forged_hash_source_provenance_and_external_license_fail_closed(self):
        mutations = []
        changed = _manifest()
        changed["assets"][0]["sha256"] = "0" * 64
        mutations.append(changed)
        changed = _manifest()
        changed["assets"][0]["source_ref"] = "user-supplied://cues/forged.wav"
        mutations.append(changed)
        changed = _manifest()
        external = next(item for item in changed["assets"] if item["provenance"] == "licensed_external")
        external["license"]["basis"] = "project_owned"
        mutations.append(changed)
        changed = _manifest()
        external = next(item for item in changed["assets"] if item["provenance"] == "licensed_external")
        external["license"]["license_id"] = "unknown"
        mutations.append(changed)
        changed = _manifest()
        external = next(item for item in changed["assets"] if item["provenance"] == "licensed_external")
        external["license"].pop("evidence_sha256")
        mutations.append(changed)
        for index, invalid in enumerate(mutations):
            with self.subTest(index=index):
                with self.assertRaises(SfxPlanError):
                    validate_sfx_cue_manifest(invalid)

    def test_reserved_rights_claims_reject_case_and_whitespace_bypasses(self):
        for provenance in ("user_supplied", "licensed_external"):
            for field, invalid in (
                ("license_id", "PROJECT-GENERATED"),
                ("licensor", "Project"),
                ("licensor", "User"),
                ("licensor", "unknown "),
                ("licensor", "project "),
            ):
                asset = _asset("rights-bypass", provenance)
                asset["license"][field] = invalid
                payload = {
                    key: copy.deepcopy(value)
                    for key, value in asset.items() if key != "asset_id"
                }
                with self.subTest(
                    provenance=provenance, field=field, invalid=invalid
                ), self.assertRaises(SfxPlanError):
                    derive_sfx_asset_id(payload)

    def test_manifest_rejects_floats_booleans_unknown_keys_order_and_unsafe_sources(self):
        invalid = []
        changed = _manifest()
        changed["output_duration_ms"] = 60_000.0
        invalid.append(changed)
        changed = _manifest()
        changed["assets"][0]["channels"] = True
        invalid.append(changed)
        changed = _manifest()
        changed["assets"][0]["extra"] = "x"
        invalid.append(changed)
        changed = _manifest()
        changed["assets"].reverse()
        invalid.append(changed)
        changed = _manifest()
        changed["anchors"].reverse()
        invalid.append(changed)
        changed = _manifest()
        changed["assets"][0]["source_ref"] = "project-generated://cues/../escape.wav"
        invalid.append(changed)
        changed = _manifest()
        changed["schema_version"] = "autoeditor-sfx-cue-manifest/v2"
        invalid.append(changed)
        changed = _manifest()
        changed["output_sample_rate_hz"] = 44_100
        invalid.append(changed)
        changed = _manifest()
        changed["output_channels"] = 1
        invalid.append(changed)
        for index, value in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(SfxPlanError):
                    validate_sfx_cue_manifest(value)

    def test_valid_sparse_plan_exactly_binds_policy_manifest_and_output(self):
        manifest = _manifest()
        policy = _policy()
        clean = validate_sfx_plan(_plan(manifest, policy), manifest, policy)
        self.assertEqual(clean["policy"], {
            "profile": "dialogue_talking_head",
            "density": "sparse",
            "usage": "motivated_only",
            "max_cue_count": 4,
            "max_polyphony": 1,
            "max_gain_millidb": 0,
            "speech_effective_gain_ceiling_millidb": -15_000,
        })
        self.assertEqual(len(clean["cues"]), 2)

    def test_exact_anchor_boundary_and_event_evidence_cannot_be_forged(self):
        manifest = _manifest()
        policy = _policy()
        mutations = []
        changed = _plan(manifest, policy)
        changed["cues"][0]["motivation"]["evidence_sha256"] = _hash("forged")
        _refresh_cue_id(changed["cues"][0])
        mutations.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][1]["motivation"]["reference_id"] = "boundary-" + _hash("other")
        _refresh_cue_id(changed["cues"][1])
        mutations.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][1]["motivation"]["anchor_ms"] += 1
        _refresh_cue_id(changed["cues"][1])
        mutations.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["kind"] = "transition_accent"
        _refresh_cue_id(changed["cues"][0])
        mutations.append(changed)
        for index, value in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_rejected(value, manifest, policy)

    def test_forbidden_and_source_only_policies_accept_only_an_empty_added_cue_plan(self):
        manifest = _manifest()
        for profile, usage in (
            ("podcast_interview", "forbidden"),
            ("music_performance", "source_only"),
        ):
            policy = _policy(profile)
            empty = _plan(manifest, policy, cues=[])
            clean = validate_sfx_plan(empty, manifest, policy)
            self.assertEqual(clean["policy"]["usage"], usage)
            self.assertEqual(clean["policy"]["max_cue_count"], 0)
            invalid = _plan(manifest, policy, cues=_default_cues(manifest)[:1])
            with self.subTest(profile=profile):
                self.assert_rejected(invalid, manifest, policy)

    def test_interface_only_and_event_only_policies_enforce_anchor_semantics(self):
        manifest = _manifest()
        interface = _anchor_by_category(manifest, "interface_feedback")
        interface_cue = _cue(
            _asset_by_name(manifest, "user-click"), interface,
            kind="interface_feedback", start_ms=45_000,
        )
        course = _policy("course_tutorial_screencast")
        validate_sfx_plan(_plan(manifest, course, [interface_cue]), manifest, course)
        event_cue = _default_cues(manifest)[0]
        self.assert_rejected(_plan(manifest, course, [event_cue]), manifest, course)

        gaming = _policy("gaming")
        boundary_cue = _default_cues(manifest)[1]
        self.assert_rejected(_plan(manifest, gaming, [boundary_cue]), manifest, gaming)

    def test_density_is_a_ceiling_and_rejects_global_or_local_overuse(self):
        self.assertEqual(
            [density_cue_limit(name, 60_000) for name in ("none", "sparse", "medium", "dense")],
            [0, 4, 10, 20],
        )
        self.assertEqual(density_cue_limit("sparse", 1), 1)
        with self.assertRaises(SfxPlanError):
            density_cue_limit("high", 60_000)

        manifest = _manifest()
        policy = _policy("commercial_product")
        event = _anchor_by_category(manifest, "event")
        asset = _asset_by_name(manifest, "licensed-impact")
        # Three separately motivated anchors inside ten seconds are allowed by
        # medium's local limit, while six are not.  Add exact trusted anchors.
        new_anchors = []
        for index in range(6):
            new_anchors.append(_anchor("event", f"event-cluster-{index}", 10_000 + index * 1_000))
        manifest["anchors"] = sorted(manifest["anchors"] + new_anchors, key=lambda item: (item["time_ms"], item["anchor_id"]))
        cues = [
            _cue(asset, anchor, kind="impact", start_ms=anchor["time_ms"], trim_duration_ms=500)
            for anchor in new_anchors
        ]
        self.assert_rejected(_plan(manifest, policy, cues), manifest, policy)

        # Overall medium density is ten cues in one minute.
        manifest = _manifest()
        spaced = []
        for index in range(11):
            time_ms = 2_000 + index * 5_000
            spaced.append(_anchor("event", f"event-many-{index}", time_ms))
        manifest["anchors"] = sorted(manifest["anchors"] + spaced, key=lambda item: (item["time_ms"], item["anchor_id"]))
        cues = [
            _cue(asset, anchor, kind="impact", start_ms=anchor["time_ms"], trim_duration_ms=250)
            for anchor in spaced
        ]
        self.assert_rejected(_plan(manifest, policy, cues), manifest, policy)

    def test_profile_and_density_polyphony_ceiling_rejects_stacked_cues(self):
        manifest = _manifest()
        policy = _policy("commercial_product")
        anchors = [
            _anchor("event", f"event-overlap-{index}", 10_000 + index * 100)
            for index in range(3)
        ]
        manifest["anchors"] = sorted(manifest["anchors"] + anchors, key=lambda item: (item["time_ms"], item["anchor_id"]))
        assets = [
            _asset_by_name(manifest, "licensed-impact"),
            _asset_by_name(manifest, "generated-whoosh"),
            _asset_by_name(manifest, "licensed-whoosh"),
        ]
        cues = [
            _cue(asset, anchor, kind="impact" if index == 0 else "whoosh", start_ms=anchor["time_ms"], trim_duration_ms=2_000)
            for index, (asset, anchor) in enumerate(zip(assets, anchors))
        ]
        self.assert_rejected(_plan(manifest, policy, cues), manifest, policy)

    def test_trim_fade_gain_duration_and_timeline_ranges_fail_closed(self):
        manifest = _manifest()
        policy = _policy()
        cases = []
        for key, value in (
            ("trim_start_ms", 3_001),
            ("trim_duration_ms", 19),
            ("gain_millidb", 1),
            ("attack_fade_ms", 901),
        ):
            changed = _plan(manifest, policy)
            changed["cues"][0]["placement"][key] = value
            if key != "trim_duration_ms":
                _refresh_cue_id(changed["cues"][0])
            cases.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["placement"]["start_ms"] = 59_500
        _refresh_cue_id(changed["cues"][0])
        changed["cues"].sort(key=lambda cue: (cue["placement"]["start_ms"], cue["cue_id"]))
        cases.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["placement"]["gain_millidb"] = True
        cases.append(changed)
        for index, value in enumerate(cases):
            with self.subTest(index=index):
                self.assert_rejected(value, manifest, policy)

    def test_speech_masking_requires_coverage_reduction_fast_attack_and_no_stacking(self):
        manifest = _manifest()
        policy = _policy()
        invalid = []
        changed = _plan(manifest, policy)
        changed["cues"][0]["ducking"] = None
        _refresh_cue_id(changed["cues"][0])
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["ducking"]["end_ms"] = 5_400
        _refresh_cue_id(changed["cues"][0])
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["ducking"]["attenuation_millidb"] = 6_000
        changed["cues"][0]["placement"]["gain_millidb"] = -6_000
        _refresh_cue_id(changed["cues"][0])
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["ducking"]["attack_ms"] = 21
        _refresh_cue_id(changed["cues"][0])
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["ducking"]["attenuation_millidb"] = 7_000
        invalid.append(changed)
        for index, value in enumerate(invalid):
            with self.subTest(index=index):
                self.assert_rejected(value, manifest, policy)

    def test_sidechain_thresholds_produce_exact_requested_steady_state_reduction(self):
        # FFmpeg sidechaincompress at a full-scale sidechain, hard knee and
        # ratio 2 reduces by half the threshold exceedance in dB.  Verify the
        # independently calculated attenuation for every closed preset.
        for attenuation_millidb in sorted(DUCK_ATTENUATIONS_MILLIDB):
            threshold = float(DUCK_SIDECHAIN_THRESHOLD_TEXT[attenuation_millidb])
            observed_millidb = round(
                (-20 * math.log10(threshold)) * (1 - 1 / 2) * 1_000
            )
            self.assertEqual(observed_millidb, attenuation_millidb)

    def test_ducking_without_trusted_speech_overlap_is_rejected_as_unmotivated(self):
        manifest = _manifest()
        policy = _policy()
        changed = _plan(manifest, policy)
        changed["cues"][1]["ducking"] = {
            "start_ms": 24_500,
            "end_ms": 25_000,
            "attenuation_millidb": 12_000,
            "attack_ms": 20,
            "release_ms": 200,
        }
        _refresh_cue_id(changed["cues"][1])
        self.assert_rejected(changed, manifest, policy)

    def test_asset_manifest_timeline_duration_policy_and_asset_hash_bindings_detect_tampering(self):
        manifest = _manifest()
        policy = _policy()
        cases = []
        changed = _plan(manifest, policy)
        changed["cue_manifest_sha256"] = "0" * 64
        cases.append(changed)
        changed = _plan(manifest, policy)
        changed["edit_policy_sha256"] = "0" * 64
        cases.append(changed)
        changed = _plan(manifest, policy)
        changed["output_timeline_sha256"] = "0" * 64
        cases.append(changed)
        changed = _plan(manifest, policy)
        changed["output_duration_ms"] -= 1
        cases.append(changed)
        changed = _plan(manifest, policy)
        changed["policy"]["density"] = "medium"
        cases.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["asset_sha256"] = "0" * 64
        _refresh_cue_id(changed["cues"][0])
        cases.append(changed)
        for index, value in enumerate(cases):
            with self.subTest(index=index):
                self.assert_rejected(value, manifest, policy)

        wrong_duration_policy = _policy(duration_ms=30_000)
        changed = _plan(manifest, policy)
        changed["edit_policy_sha256"] = edit_policy_sha256(wrong_duration_policy)
        self.assert_rejected(changed, manifest, wrong_duration_policy)
        with self.assertRaises(SfxPlanError):
            derive_sfx_policy_limits(wrong_duration_policy, 60_000)

    def test_cue_ids_order_duplicates_and_closed_keys_fail_closed(self):
        manifest = _manifest()
        policy = _policy()
        invalid = []
        changed = _plan(manifest, policy)
        changed["cues"][0]["cue_id"] = "sfxcue-" + "0" * 64
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"].reverse()
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"].append(copy.deepcopy(changed["cues"][1]))
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["cues"][0]["comment"] = "nice"
        invalid.append(changed)
        changed = _plan(manifest, policy)
        changed["schema_version"] = "autoeditor-sfx-plan/v2"
        invalid.append(changed)
        for index, value in enumerate(invalid):
            with self.subTest(index=index):
                self.assert_rejected(value, manifest, policy)

    def test_canonical_json_hashes_are_key_order_independent_and_contain_no_floats(self):
        manifest = _manifest()
        policy = _policy()
        plan = _plan(manifest, policy)
        reversed_manifest = {key: copy.deepcopy(manifest[key]) for key in reversed(list(manifest))}
        reversed_plan = {key: copy.deepcopy(plan[key]) for key in reversed(list(plan))}
        reversed_plan["cues"] = [
            {key: copy.deepcopy(cue[key]) for key in reversed(list(cue))}
            for cue in reversed_plan["cues"]
        ]
        self.assertEqual(canonical_sfx_cue_manifest_json(manifest), canonical_sfx_cue_manifest_json(reversed_manifest))
        self.assertEqual(canonical_sfx_plan_json(plan), canonical_sfx_plan_json(reversed_plan))
        self.assertEqual(sfx_plan_sha256(plan), sfx_plan_sha256(reversed_plan))
        self.assertFalse(_contains_float(validate_sfx_cue_manifest(manifest)))
        self.assertFalse(_contains_float(validate_sfx_plan(plan, manifest, policy)))

    def test_compilation_emits_inert_ffmpeg_primitives_and_exact_receipt(self):
        manifest = _manifest()
        policy = _policy()
        result = compile_sfx_plan(_plan(manifest, policy), manifest, policy)
        first = result["compiled_cues"][0]
        self.assertEqual(first["cue_ffmpeg_primitive_tokens"], [
            "atrim=start=0.000:duration=1.000",
            "asetpts=PTS-STARTPTS",
            "aresample=48000:async=0:first_pts=0",
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
            "afade=t=in:st=0.000:d=0.050:curve=qsin",
            "afade=t=out:st=0.900:d=0.100:curve=qsin",
            "volume=-6.000dB:precision=double",
        ])
        self.assertEqual(first["duck_sidechain_gate_ffmpeg_primitive_tokens"], [
            "aevalsrc=if(between(t\\,0.000\\,0.500)\\,1\\,0):d=1.000:s=48000:c=mono",
        ])
        self.assertEqual(first["sidechaincompress_ffmpeg_primitive_tokens"], [
            "sidechaincompress=threshold=0.06309573445:ratio=2:attack=20:release=200:makeup=1:knee=1:link=maximum:detection=peak:mix=1"
        ])
        self.assertEqual(first["timeline_ffmpeg_primitive_tokens"], [
            "adelay=delays=5000:all=1"
        ])
        self.assertEqual(result["sfx_bus_ffmpeg_primitive_tokens"][0],
                         "amix=inputs=2:duration=longest:dropout_transition=0:normalize=0")
        self.assertEqual(result["program_input_ffmpeg_primitive_tokens"][:2], [
            "aresample=48000:async=0:first_pts=0",
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
        ])
        self.assertEqual(result["program_mix_ffmpeg_primitive_tokens"][0],
                         "amix=inputs=2:duration=first:dropout_transition=0:normalize=0")
        self.assertIn("alimiter=limit=0.891251:attack=5:release=50:level=0:latency=1",
                      result["program_mix_ffmpeg_primitive_tokens"])
        self.assertIn("apad=whole_dur=60.000",
                      result["sfx_bus_ffmpeg_primitive_tokens"])
        receipt = result["receipt"]
        self.assertEqual(receipt["schema_version"], SFX_COMPILE_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["output_duration_ms"], 60_000)
        self.assertEqual(receipt["cue_count"], 2)
        self.assertEqual(receipt["speech_overlap_cue_count"], 1)
        self.assertEqual(receipt["max_observed_polyphony"], 1)
        self.assertEqual(result["receipt_sha256"], sfx_compile_receipt_sha256(receipt))
        self.assertEqual(
            result["receipt_sha256"],
            hashlib.sha256(canonical_sfx_compile_receipt_json(receipt).encode("utf-8")).hexdigest(),
        )
        self.assertFalse(_contains_float(result))
        all_tokens = json.dumps(result["compiled_cues"])
        self.assertNotIn("licensed-external://", " ".join(
            token
            for cue in result["compiled_cues"]
            for key, value in cue.items()
            if key.endswith("_primitive_tokens")
            for token in value
        ))
        self.assertIn("licensed-external://", all_tokens)

    def test_empty_plan_compiles_to_no_mix_graph_but_a_bound_receipt(self):
        manifest = _manifest()
        policy = _policy("podcast_interview")
        result = compile_sfx_plan(_plan(manifest, policy, cues=[]), manifest, policy)
        self.assertEqual(result["compiled_cues"], [])
        self.assertEqual(result["program_input_ffmpeg_primitive_tokens"], [])
        self.assertEqual(result["sfx_bus_ffmpeg_primitive_tokens"], [])
        self.assertEqual(result["program_mix_ffmpeg_primitive_tokens"], [])
        self.assertEqual(result["receipt"]["cue_count"], 0)
        self.assertEqual(result["receipt"]["unique_asset_count"], 0)

    def test_compile_receipt_hash_is_closed_and_detects_tampering(self):
        manifest = _manifest()
        policy = _policy()
        receipt = compile_sfx_plan(_plan(manifest, policy), manifest, policy)["receipt"]
        original = sfx_compile_receipt_sha256(receipt)
        changed = copy.deepcopy(receipt)
        changed["output_duration_ms"] += 1
        self.assertNotEqual(original, sfx_compile_receipt_sha256(changed))
        changed = copy.deepcopy(receipt)
        changed["compiled_cues_sha256"] = "0" * 64
        self.assertNotEqual(original, sfx_compile_receipt_sha256(changed))
        changed = copy.deepcopy(receipt)
        changed["extra"] = True
        with self.assertRaises(SfxPlanError):
            sfx_compile_receipt_sha256(changed)
        changed = copy.deepcopy(receipt)
        changed["cue_count"] += 1
        with self.assertRaises(SfxPlanError):
            sfx_compile_receipt_sha256(changed)

    def test_json_schema_advertises_closed_plan_cue_and_ducking_surfaces(self):
        schema = SFX_PLAN_JSON_SCHEMA
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema_version"]["const"], SFX_PLAN_SCHEMA_VERSION)
        cue = schema["properties"]["cues"]["items"]
        self.assertFalse(cue["additionalProperties"])
        self.assertEqual(cue["properties"]["kind"]["enum"], [
            "ambience", "foley", "gameplay_event", "impact",
            "interface_feedback", "riser", "sports_event",
            "transition_accent", "whoosh",
        ])
        duck = cue["properties"]["ducking"]["oneOf"][1]
        self.assertFalse(duck["additionalProperties"])
        self.assertEqual(set(duck["properties"]), set(duck["required"]))
        self.assertEqual(
            set(schema["properties"]["policy"]["properties"]),
            set(schema["properties"]["policy"]["required"]),
        )
        self.assertEqual(
            set(cue["properties"]["motivation"]["properties"]),
            set(cue["properties"]["motivation"]["required"]),
        )
        self.assertEqual(
            set(cue["properties"]["placement"]["properties"]),
            set(cue["properties"]["placement"]["required"]),
        )
        self.assertFalse(SFX_CUE_MANIFEST_JSON_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(SFX_CUE_MANIFEST_JSON_SCHEMA["properties"]),
            set(SFX_CUE_MANIFEST_JSON_SCHEMA["required"]),
        )
        self.assertEqual(
            SFX_CUE_MANIFEST_JSON_SCHEMA["properties"]["output_sample_rate_hz"],
            {"const": 48_000},
        )
        self.assertEqual(
            SFX_CUE_MANIFEST_JSON_SCHEMA["properties"]["output_channels"],
            {"const": 2},
        )
        self.assertFalse(SFX_COMPILE_RECEIPT_JSON_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(SFX_COMPILE_RECEIPT_JSON_SCHEMA["properties"]),
            set(SFX_COMPILE_RECEIPT_JSON_SCHEMA["required"]),
        )
        self.assertEqual(DUCK_ATTENUATIONS_MILLIDB,
                         frozenset({6_000, 9_000, 12_000, 18_000, 24_000}))


if __name__ == "__main__":
    unittest.main()
