import copy
import hashlib
import json
import re
import unicodedata
import unittest

from autoeditor.edit_policy import (
    CAPABILITIES,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    edit_policy_sha256,
    resolve_edit_policy,
)
from autoeditor.music_plan import (
    MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
    MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
    MUSIC_PLAN_JSON_SCHEMA,
    MUSIC_PLAN_SCHEMA_VERSION,
    MusicPlanError,
    canonical_music_asset_manifest_json,
    canonical_music_plan_json,
    compile_music_plan,
    derive_beat_grid_id,
    derive_dialogue_window_id,
    derive_music_asset_id,
    derive_music_mastering,
    derive_music_policy_limits,
    derive_music_region_id,
    derive_source_music_region_id,
    music_asset_manifest_sha256,
    music_compile_receipt_sha256,
    music_plan_sha256,
    validate_music_asset_manifest,
    validate_music_compile_result,
    validate_music_plan,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _policy(
    profile: str = "montage_meme",
    duration_ms: int = 60_000,
    *,
    music_rule: str = "auto",
    platform: str = "web",
):
    auto = {
        "cut_density": "auto",
        "sfx_density": "auto",
        "transition_density": "auto",
        "dialogue_rule": "auto",
        "music_rule": "auto",
        "caption_rule": "auto",
        "visualization_rule": "auto",
    }
    explicit = dict(auto)
    explicit["music_rule"] = music_rule
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": profile,
        "duration_ms": duration_ms,
        "delivery": {"platform": platform, "aspect": "auto"},
        "explicit_intent": explicit,
        "consented_preferences": {"consented": False, "values": dict(auto)},
        "available_capabilities": sorted(CAPABILITIES),
    })


def _asset(name: str, *, loop: bool = True, unicode_license: bool = False):
    license_name = "Édition musicale mondiale" if unicode_license else "Worldwide music license"
    licensor = "Música Société" if unicode_license else "Example Music Ltd"
    payload = {
        "sha256": _hash(name + "-bytes"),
        "byte_length": 500_000 + len(name),
        "decoded_duration_ms": 90_000,
        "sample_rate_hz": 48_000,
        "channels": 2,
        "source_ref": f"licensed-external://music/{name}.wav",
        "provenance": "licensed_external",
        "license": {
            "basis": "licensed_external",
            "license_id": "license-" + name,
            "license_name": license_name,
            "licensor": licensor,
            "evidence_sha256": _hash(name + "-license"),
        },
        "rights_receipt": {
            "receipt_id": "rights-" + name,
            "receipt_sha256": _hash(name + "-rights"),
            "permits_synchronization": True,
            "permits_editing": True,
            "permits_looping": loop,
            "permits_delivery": True,
        },
    }
    return {"asset_id": derive_music_asset_id(payload), **payload}


def _beat_grid(asset):
    payload = {
        "asset_id": asset["asset_id"],
        "asset_sha256": asset["sha256"],
        "analysis_receipt_sha256": _hash(asset["asset_id"] + "-beat-analysis"),
        "beats_ms": list(range(0, 90_001, 1_000)),
        "downbeats_ms": list(range(0, 90_001, 4_000)),
    }
    return {"beat_grid_id": derive_beat_grid_id(payload, [asset]), **payload}


def _dialogue(start_ms=10_000, end_ms=15_000, transcript_sha=None):
    transcript_sha = _hash("trusted-transcript") if transcript_sha is None else transcript_sha
    payload = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "evidence_kind": "transcript",
        "evidence_sha256": _hash(f"dialogue-{start_ms}-{end_ms}"),
    }
    return {
        "dialogue_window_id": derive_dialogue_window_id(payload, 60_000, transcript_sha),
        **payload,
    }


def _manifest(*, include_dialogue=True, unicode_license=False):
    assets = [
        _asset("anthem", unicode_license=unicode_license),
        _asset("underscore"),
        _asset("rhythm"),
    ]
    assets.sort(key=lambda item: item["asset_id"])
    grids = [_beat_grid(asset) for asset in assets]
    grids.sort(key=lambda item: (item["asset_id"], item["beat_grid_id"]))
    transcript = _hash("trusted-transcript") if include_dialogue else None
    return {
        "schema_version": MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": _hash("compiled-output-timeline"),
        "output_duration_ms": 60_000,
        "output_sample_rate_hz": 48_000,
        "output_channels": 2,
        "transcript_sha256": transcript,
        "source_music": {
            "status": "absent",
            "evidence_sha256": _hash("source-music-analysis"),
            "exclusion_authorization_sha256": None,
            "regions": [],
        },
        "assets": assets,
        "beat_grids": grids,
        "dialogue_windows": [_dialogue(transcript_sha=transcript)] if include_dialogue else [],
    }


def _asset_by_name(manifest, name):
    return next(item for item in manifest["assets"] if f"/{name}.wav" in item["source_ref"])


def _grid_for(manifest, asset):
    return next(item for item in manifest["beat_grids"] if item["asset_id"] == asset["asset_id"])


def _duck(manifest, *, attenuation=12_000, attack=40):
    return {
        "dialogue_window_ids": sorted(item["dialogue_window_id"] for item in manifest["dialogue_windows"]),
        "threshold_millidbfs": -30_000,
        "attenuation_millidb": attenuation,
        "attack_ms": attack,
        "release_ms": 300,
    }


def _region(
    asset,
    *,
    track=0,
    start=0,
    duration=30_000,
    trim=0,
    mode="once",
    loop_length=0,
    loop_crossfade=0,
    gain=-6_000,
    fade_in=500,
    fade_out=500,
    crossfade_in=0,
    crossfade_out=0,
    beat_sync=None,
    ducking=None,
):
    payload = {
        "track_index": track,
        "asset_id": asset["asset_id"],
        "asset_sha256": asset["sha256"],
        "start_ms": start,
        "duration_ms": duration,
        "trim_start_ms": trim,
        "playback_mode": mode,
        "loop_length_ms": loop_length,
        "loop_crossfade_ms": loop_crossfade,
        "gain_millidb": gain,
        "fade_in_ms": fade_in,
        "fade_out_ms": fade_out,
        "crossfade_in_ms": crossfade_in,
        "crossfade_out_ms": crossfade_out,
        "beat_sync": copy.deepcopy(beat_sync),
        "dialogue_ducking": copy.deepcopy(ducking),
    }
    return {"region_id": derive_music_region_id(payload), **payload}


def _refresh_region(region):
    payload = {key: copy.deepcopy(value) for key, value in region.items() if key != "region_id"}
    region["region_id"] = derive_music_region_id(payload)


def _default_regions(manifest):
    return [
        _region(
            _asset_by_name(manifest, "anthem"),
            start=15_000,
            duration=15_000,
            fade_out=1_000,
        ),
        _region(
            _asset_by_name(manifest, "underscore"),
            start=30_000,
            duration=30_000,
            fade_in=1_000,
        ),
    ]


def _plan(manifest=None, policy=None, regions=None, *, source_action="none"):
    manifest = _manifest() if manifest is None else manifest
    policy = _policy() if policy is None else policy
    regions = _default_regions(manifest) if regions is None else regions
    regions = sorted(copy.deepcopy(regions), key=lambda item: (item["start_ms"], item["track_index"], item["region_id"]))
    return {
        "schema_version": MUSIC_PLAN_SCHEMA_VERSION,
        "music_asset_manifest_sha256": music_asset_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "output_timeline_sha256": manifest["output_timeline_sha256"],
        "output_duration_ms": manifest["output_duration_ms"],
        "policy": derive_music_policy_limits(policy, manifest["output_duration_ms"]),
        "mastering": derive_music_mastering(policy),
        "source_music_action": source_action,
        "regions": regions,
    }


def _source_present(manifest, *, authorized=False):
    manifest = copy.deepcopy(manifest)
    payload = {
        "start_ms": 0,
        "end_ms": 60_000,
        "evidence_sha256": _hash("source-music-region"),
    }
    manifest["source_music"] = {
        "status": "present",
        "evidence_sha256": _hash("source-music-analysis"),
        "exclusion_authorization_sha256": _hash("source-exclusion-authorization") if authorized else None,
        "regions": [{"source_region_id": derive_source_music_region_id(payload, 60_000), **payload}],
    }
    return manifest


def _contains_float(value):
    if type(value) is float:
        return True
    if type(value) is dict:
        return any(_contains_float(item) for item in value.values())
    if type(value) is list:
        return any(_contains_float(item) for item in value)
    return False


class MusicPlanTests(unittest.TestCase):
    def assert_plan_rejected(self, plan, manifest=None, policy=None):
        manifest = _manifest() if manifest is None else manifest
        policy = _policy() if policy is None else policy
        with self.assertRaises(MusicPlanError):
            validate_music_plan(plan, manifest, policy)

    def test_valid_plan_compiles_to_deterministic_inert_receipt(self):
        manifest = _manifest(unicode_license=True)
        policy = _policy()
        plan = _plan(manifest, policy)
        validated = validate_music_plan(plan, manifest, policy)
        self.assertEqual(validated, plan)
        compiled_a = compile_music_plan(plan, manifest, policy)
        compiled_b = compile_music_plan(copy.deepcopy(plan), copy.deepcopy(manifest), copy.deepcopy(policy))
        self.assertEqual(compiled_a, compiled_b)
        self.assertEqual(compiled_a["schema_version"], MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(compiled_a["receipt"]["region_count"], 2)
        self.assertEqual(compiled_a["receipt"]["max_observed_polyphony"], 1)
        self.assertEqual(compiled_a["receipt"]["added_coverage_ms"], 45_000)
        self.assertEqual(compiled_a["receipt_sha256"], music_compile_receipt_sha256(compiled_a["receipt"]))
        self.assertEqual(validate_music_compile_result(compiled_a, plan, manifest, policy), compiled_a)
        self.assertFalse(
            compiled_a["compiled_regions"][0]["dialogue_sidechain_ffmpeg_primitive_tokens"])
        self.assertIn(
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
            compiled_a["compiled_regions"][0]["source_ffmpeg_primitive_tokens"])
        self.assertIn("apad=whole_dur=60.000",
                      compiled_a["music_bus_ffmpeg_primitive_tokens"])
        self.assertIn("apad=whole_dur=60.000",
                      compiled_a["program_mix_ffmpeg_primitive_tokens"])
        self.assertFalse(_contains_float(compiled_a))

    def test_compile_tokens_are_shell_free_and_path_free(self):
        compiled = compile_music_plan(_plan(), _manifest(), _policy())
        forbidden = re.compile(r"[;&|$()<>\\\n\r]")
        token_lists = [
            compiled["track_crossfade_ffmpeg_primitive_tokens"],
            compiled["music_bus_ffmpeg_primitive_tokens"],
            compiled["program_mix_ffmpeg_primitive_tokens"],
            compiled["output_ffmpeg_argument_tokens"],
        ]
        for item in compiled["compiled_regions"]:
            token_lists.extend(value for key, value in item.items() if key.endswith("_tokens"))
        for tokens in token_lists:
            for token in tokens:
                self.assertIsNone(forbidden.search(token))
                self.assertNotIn("://", token)

    def test_manifest_and_plan_hashes_are_canonical_and_detached(self):
        manifest = _manifest(unicode_license=True)
        plan = _plan(manifest)
        manifest_json = canonical_music_asset_manifest_json(manifest)
        self.assertIn("\\u00c9", manifest_json)
        self.assertEqual(manifest_json, canonical_music_asset_manifest_json(copy.deepcopy(manifest)))
        self.assertEqual(music_asset_manifest_sha256(manifest), hashlib.sha256(manifest_json.encode()).hexdigest())
        plan_json = canonical_music_plan_json(plan)
        self.assertEqual(music_plan_sha256(plan), hashlib.sha256(plan_json.encode()).hexdigest())
        detached = validate_music_asset_manifest(manifest)
        manifest["assets"][0]["license"]["license_name"] = "changed"
        self.assertNotEqual(detached["assets"][0]["license"]["license_name"], "changed")

    def test_non_nfc_unicode_is_rejected(self):
        manifest = _manifest(unicode_license=True)
        manifest["assets"][0]["license"]["license_name"] = unicodedata.normalize("NFD", "Édition")
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)

    def test_closed_schemas_reject_unknown_and_missing_keys(self):
        manifest = _manifest()
        manifest["surprise"] = True
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)
        plan = _plan()
        del plan["mastering"]
        self.assert_plan_rejected(plan)
        self.assertFalse(MUSIC_PLAN_JSON_SCHEMA["additionalProperties"])
        self.assertEqual(set(MUSIC_PLAN_JSON_SCHEMA["required"]), set(_plan()))
        for key in ("policy", "mastering"):
            nested = MUSIC_PLAN_JSON_SCHEMA["properties"][key]
            self.assertFalse(nested["additionalProperties"])
            self.assertEqual(set(nested["required"]), set(nested["properties"]))
        region = MUSIC_PLAN_JSON_SCHEMA["properties"]["regions"]["items"]
        self.assertFalse(region["additionalProperties"])
        self.assertEqual(set(region["required"]), set(region["properties"]))

    def test_missing_or_tampered_license_and_rights_receipts_fail(self):
        manifest = _manifest()
        del manifest["assets"][0]["license"]["evidence_sha256"]
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)

    def test_license_claims_reject_reserved_case_and_surrounding_whitespace(self):
        for license_id, license_name, licensor in (
            ("PROJECT-GENERATED", "External license", "Vendor"),
            ("external-1", " unknown ", "Vendor"),
            ("external-1", "External license", " PROJECT "),
            ("external-1", "External license", "User"),
        ):
            manifest = _manifest()
            asset = copy.deepcopy(manifest["assets"][0])
            asset["license"].update({
                "license_id": license_id,
                "license_name": license_name,
                "licensor": licensor,
            })
            payload = {key: copy.deepcopy(value) for key, value in asset.items()
                       if key != "asset_id"}
            with self.assertRaises(MusicPlanError):
                derive_music_asset_id(payload)

        manifest = _manifest()
        asset = copy.deepcopy(manifest["assets"][0])
        asset["provenance"] = "user_supplied"
        asset["source_ref"] = "user-supplied://music/user.wav"
        asset["license"]["basis"] = "user_authorized"
        for licensor in ("User", "user ", "project"):
            payload = {key: copy.deepcopy(value) for key, value in asset.items()
                       if key != "asset_id"}
            payload["license"]["licensor"] = licensor
            with self.assertRaises(MusicPlanError):
                derive_music_asset_id(payload)
        manifest = _manifest()
        manifest["assets"][0]["rights_receipt"]["receipt_sha256"] = _hash("tampered")
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)
        manifest = _manifest()
        manifest["assets"][0]["license"]["license_name"] = "unknown"
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)

    def test_asset_hash_and_plan_asset_binding_tamper_fail(self):
        manifest = _manifest()
        manifest["assets"][0]["sha256"] = _hash("other bytes")
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)
        manifest = _manifest()
        plan = _plan(manifest)
        plan["regions"][0]["asset_sha256"] = _hash("substitution")
        _refresh_region(plan["regions"][0])
        self.assert_plan_rejected(plan, manifest)

    def test_manifest_and_edit_policy_hash_mismatch_fail(self):
        plan = _plan()
        plan["music_asset_manifest_sha256"] = _hash("other manifest")
        self.assert_plan_rejected(plan)
        plan = _plan()
        plan["edit_policy_sha256"] = _hash("other policy")
        self.assert_plan_rejected(plan)
        plan = _plan()
        plan["policy"]["max_region_count"] -= 1
        self.assert_plan_rejected(plan)

    def test_edit_policy_duration_must_equal_trusted_output_duration(self):
        with self.assertRaises(MusicPlanError):
            derive_music_policy_limits(_policy(duration_ms=59_000), 60_000)

    def test_delivery_audio_is_exact_48000_hz_stereo(self):
        for rate, channels in ((8_000, 2), (48_000, 1), (44_100, 6)):
            manifest = _manifest()
            manifest["output_sample_rate_hz"] = rate
            manifest["output_channels"] = channels
            with self.assertRaises(MusicPlanError):
                validate_music_asset_manifest(manifest)

    def test_mastering_targets_are_exactly_policy_derived(self):
        broadcast = _policy(platform="broadcast")
        self.assertEqual(derive_music_mastering(broadcast), {
            "target_loudness_millilufs": -23_000,
            "true_peak_ceiling_millidbtp": -2_000,
        })
        plan = _plan(policy=broadcast)
        plan["mastering"]["target_loudness_millilufs"] = -14_000
        self.assert_plan_rejected(plan, policy=broadcast)

    def test_dialogue_overlap_requires_exact_grounded_ducking(self):
        manifest = _manifest()
        region = _region(
            _asset_by_name(manifest, "anthem"), start=9_000,
            duration=7_000, ducking=None)
        plan = _plan(manifest, regions=[region])
        self.assert_plan_rejected(plan, manifest)
        region = _region(
            _asset_by_name(manifest, "anthem"), start=9_000,
            duration=7_000, ducking=_duck(manifest))
        plan = _plan(manifest, regions=[region])
        self.assert_plan_rejected(plan, manifest)

    def test_dialogue_masking_gain_and_attack_guards(self):
        manifest = _manifest()
        one = _region(
            _asset_by_name(manifest, "anthem"), start=9_000,
            duration=7_000, gain=0,
            ducking=_duck(manifest, attenuation=9_000))
        plan = _plan(manifest, regions=[one])
        self.assert_plan_rejected(plan, manifest)
        primary_dialogue = _policy(profile="dialogue_talking_head", music_rule="supporting")
        one = _region(_asset_by_name(manifest, "anthem"), duration=60_000, gain=-6_000, ducking=_duck(manifest, attenuation=12_000, attack=40))
        plan = _plan(manifest, primary_dialogue, [one])
        self.assert_plan_rejected(plan, manifest, primary_dialogue)

    def test_unmotivated_ducking_is_rejected(self):
        manifest = _manifest(include_dialogue=False)
        region = _region(_asset_by_name(manifest, "anthem"), duration=60_000, ducking={
            "dialogue_window_ids": ["dialogue-" + "0" * 64],
            "threshold_millidbfs": -30_000,
            "attenuation_millidb": 12_000,
            "attack_ms": 40,
            "release_ms": 300,
        })
        self.assert_plan_rejected(_plan(manifest, regions=[region]), manifest)

    def test_invalid_once_and_loop_parameters_fail(self):
        manifest = _manifest()
        asset = _asset_by_name(manifest, "anthem")
        once = _region(asset, duration=60_000, loop_length=10_000, ducking=_duck(manifest))
        self.assert_plan_rejected(_plan(manifest, regions=[once]), manifest)
        loop = _region(
            asset, duration=55_001, mode="loop", loop_length=10_000,
            loop_crossfade=1_000, ducking=_duck(manifest),
        )
        self.assert_plan_rejected(_plan(manifest, regions=[loop]), manifest)
        loop = _region(
            asset, duration=54_000, mode="loop", loop_length=4_000,
            loop_crossfade=1_500, ducking=_duck(manifest),
        )
        self.assert_plan_rejected(_plan(manifest, regions=[loop]), manifest)

    def test_loop_is_rejected_until_v1_has_an_executable_topology(self):
        manifest = _manifest()
        loop = _region(
            _asset_by_name(manifest, "anthem"), duration=55_000, mode="loop",
            loop_length=10_000, loop_crossfade=1_000, ducking=_duck(manifest),
        )
        plan = _plan(manifest, regions=[loop])
        self.assert_plan_rejected(plan, manifest)

    def test_looping_without_explicit_right_fails(self):
        manifest = _manifest()
        asset = copy.deepcopy(_asset_by_name(manifest, "anthem"))
        asset["rights_receipt"]["permits_looping"] = False
        payload = {key: copy.deepcopy(value) for key, value in asset.items() if key != "asset_id"}
        asset = {"asset_id": derive_music_asset_id(payload), **payload}
        manifest["assets"] = [asset]
        manifest["beat_grids"] = []
        region = _region(asset, duration=55_000, mode="loop", loop_length=10_000, loop_crossfade=1_000, ducking=_duck(manifest))
        plan = _plan(manifest, regions=[region])
        self.assert_plan_rejected(plan, manifest)

    def test_loop_timing_must_align_to_exact_decoded_samples(self):
        manifest = _manifest()
        asset = copy.deepcopy(_asset_by_name(manifest, "anthem"))
        asset["sample_rate_hz"] = 44_100
        payload = {key: copy.deepcopy(value) for key, value in asset.items() if key != "asset_id"}
        asset = {"asset_id": derive_music_asset_id(payload), **payload}
        manifest["assets"] = [asset]
        manifest["beat_grids"] = []
        region = _region(
            asset,
            duration=10_011,
            mode="loop",
            loop_length=1_001,
            loop_crossfade=100,
            ducking=_duck(manifest),
        )
        self.assert_plan_rejected(_plan(manifest, regions=[region]), manifest)

    def test_missing_sync_edit_or_delivery_right_fails(self):
        for permission in ("permits_synchronization", "permits_editing", "permits_delivery"):
            manifest = _manifest()
            asset = copy.deepcopy(_asset_by_name(manifest, "anthem"))
            asset["rights_receipt"][permission] = False
            payload = {key: copy.deepcopy(value) for key, value in asset.items() if key != "asset_id"}
            asset = {"asset_id": derive_music_asset_id(payload), **payload}
            manifest["assets"] = [asset]
            manifest["beat_grids"] = []
            region = _region(asset, duration=60_000, ducking=_duck(manifest))
            self.assert_plan_rejected(_plan(manifest, regions=[region]), manifest)

    def test_crossfade_must_equal_exact_overlap_and_be_paired(self):
        manifest = _manifest()
        plan = _plan(manifest)
        plan["regions"][0]["crossfade_out_ms"] = 500
        _refresh_region(plan["regions"][0])
        self.assert_plan_rejected(plan, manifest)
        plan = _plan(manifest)
        plan["regions"][1]["crossfade_in_ms"] = 500
        _refresh_region(plan["regions"][1])
        self.assert_plan_rejected(plan, manifest)

    def test_ungrounded_beat_claims_fail(self):
        manifest = _manifest()
        asset = _asset_by_name(manifest, "anthem")
        grid = _grid_for(manifest, asset)
        beat = {
            "beat_grid_id": grid["beat_grid_id"],
            "analysis_receipt_sha256": grid["analysis_receipt_sha256"],
            "asset_beat_ms": 1_234,
            "output_beat_ms": 0,
        }
        region = _region(asset, duration=60_000, beat_sync=beat, ducking=_duck(manifest))
        self.assert_plan_rejected(_plan(manifest, regions=[region]), manifest)
        beat["asset_beat_ms"] = 0
        beat["analysis_receipt_sha256"] = _hash("fabricated analysis")
        region = _region(asset, duration=60_000, beat_sync=beat, ducking=_duck(manifest))
        self.assert_plan_rejected(_plan(manifest, regions=[region]), manifest)

    def test_trusted_beat_mapping_compiles(self):
        manifest = _manifest(include_dialogue=False)
        asset = _asset_by_name(manifest, "anthem")
        grid = _grid_for(manifest, asset)
        beat = {
            "beat_grid_id": grid["beat_grid_id"],
            "analysis_receipt_sha256": grid["analysis_receipt_sha256"],
            "asset_beat_ms": 0,
            "output_beat_ms": 0,
        }
        region = _region(asset, duration=60_000, beat_sync=beat, ducking=None)
        compiled = compile_music_plan(_plan(manifest, regions=[region]), manifest, _policy())
        self.assertEqual(compiled["receipt"]["beat_synced_region_count"], 1)

    def test_source_music_preservation_blocks_added_overlap(self):
        manifest = _source_present(_manifest())
        plan = _plan(manifest, source_action="preserve")
        self.assert_plan_rejected(plan, manifest)

    def test_source_music_exclusion_requires_exact_authorization(self):
        manifest = _source_present(_manifest(), authorized=False)
        plan = _plan(manifest, source_action="exclude_authorized")
        self.assert_plan_rejected(plan, manifest)
        authorized = _source_present(_manifest(), authorized=True)
        invalid = _plan(authorized, source_action="exclude_authorized")
        self.assert_plan_rejected(invalid, authorized)

    def test_source_primary_policy_requires_preservation_and_no_added_assets(self):
        manifest = _source_present(_manifest())
        policy = _policy(profile="music_performance")
        valid = _plan(manifest, policy, [], source_action="preserve")
        self.assertEqual(validate_music_plan(valid, manifest, policy), valid)
        invalid = _plan(manifest, policy, [], source_action="exclude_authorized")
        self.assert_plan_rejected(invalid, manifest, policy)

    def test_forbidden_policy_allows_no_added_music(self):
        manifest = _manifest()
        policy = _policy(profile="utility_faithful")
        empty = _plan(manifest, policy, [], source_action="none")
        self.assertEqual(validate_music_plan(empty, manifest, policy), empty)
        with_music = _plan(manifest, policy, [_region(_asset_by_name(manifest, "anthem"), duration=60_000, ducking=None)])
        self.assert_plan_rejected(with_music, manifest, policy)

    def test_polyphony_and_track_count_bounds_fail_closed(self):
        manifest = _manifest(include_dialogue=False)
        regions = [
            _region(asset, track=index, duration=9_000)
            for index, asset in enumerate(manifest["assets"])
        ]
        self.assert_plan_rejected(_plan(manifest, regions=regions), manifest)
        optional = _policy(music_rule="optional")
        regions = [
            _region(manifest["assets"][0], track=0, duration=9_000),
            _region(manifest["assets"][1], track=1, start=20_000, duration=9_000),
        ]
        self.assert_plan_rejected(_plan(manifest, optional, regions), manifest, optional)

    def test_duration_density_and_optional_coverage_are_enforced(self):
        manifest = _manifest(include_dialogue=False)
        optional = _policy(music_rule="optional")
        region = _region(manifest["assets"][0], duration=40_000)
        self.assert_plan_rejected(_plan(manifest, optional, [region]), manifest, optional)
        regions = [
            _region(manifest["assets"][index % 3], start=index * 12_000, duration=5_000)
            for index in range(5)
        ]
        self.assert_plan_rejected(_plan(manifest, regions=regions), manifest)

    def test_arbitrary_paths_and_shell_injection_are_rejected(self):
        manifest = _manifest()
        manifest["assets"][0]["source_ref"] = "licensed-external://music/ok.wav;calc.exe"
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)
        manifest = _manifest()
        manifest["assets"][0]["source_ref"] = "C:\\music\\song.wav"
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)

    def test_invalid_transcript_and_beat_evidence_fail(self):
        manifest = _manifest()
        manifest["transcript_sha256"] = None
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)
        manifest = _manifest()
        manifest["beat_grids"][0]["beats_ms"].append(manifest["beat_grids"][0]["beats_ms"][-1])
        with self.assertRaises(MusicPlanError):
            validate_music_asset_manifest(manifest)

    def test_boolean_is_not_accepted_as_integer(self):
        plan = _plan()
        plan["regions"][0]["start_ms"] = True
        with self.assertRaises(MusicPlanError):
            canonical_music_plan_json(plan)

    def test_receipt_tamper_and_omission_are_rejected(self):
        manifest = _manifest()
        policy = _policy()
        plan = _plan(manifest, policy)
        compiled = compile_music_plan(plan, manifest, policy)
        tampered = copy.deepcopy(compiled)
        tampered["receipt"]["compiled_regions_sha256"] = _hash("tampered regions")
        tampered["receipt_sha256"] = music_compile_receipt_sha256(tampered["receipt"])
        with self.assertRaises(MusicPlanError):
            validate_music_compile_result(tampered, plan, manifest, policy)
        omitted = copy.deepcopy(compiled)
        del omitted["program_mix_ffmpeg_primitive_tokens"]
        with self.assertRaises(MusicPlanError):
            validate_music_compile_result(omitted, plan, manifest, policy)

    def test_receipt_replay_against_another_plan_fails(self):
        manifest = _manifest()
        policy = _policy()
        first = _plan(manifest, policy)
        compiled = compile_music_plan(first, manifest, policy)
        second = copy.deepcopy(first)
        second["regions"][0]["gain_millidb"] = -9_000
        _refresh_region(second["regions"][0])
        with self.assertRaises(MusicPlanError):
            validate_music_compile_result(compiled, second, manifest, policy)

    def test_json_round_trip_preserves_exact_contract(self):
        manifest = _manifest(unicode_license=True)
        plan = _plan(manifest)
        manifest_round_trip = json.loads(canonical_music_asset_manifest_json(manifest))
        plan_round_trip = json.loads(canonical_music_plan_json(plan))
        self.assertEqual(validate_music_asset_manifest(manifest_round_trip), validate_music_asset_manifest(manifest))
        self.assertEqual(validate_music_plan(plan_round_trip, manifest_round_trip, _policy()), validate_music_plan(plan, manifest, _policy()))


if __name__ == "__main__":
    unittest.main()
