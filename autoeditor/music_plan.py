"""Deterministic, rights-aware planning for added music.

This module is an inert contract boundary.  It does not open an asset, resolve
a path, invoke FFmpeg, or infer that anybody owns synchronization rights.  A
trusted producer must supply exact byte/media facts and explicit license and
rights receipts.  A planner may only select those facts under a validated
``autoeditor-edit-policy/v1``.

Compilation emits bounded FFmpeg argument/filter *tokens*.  The later trusted
executor must re-hash asset bytes, assign its own stream labels, build a graph
without a shell, and bind the rendered artifact to the compile receipt.
Serialized timing and gain values are integer milliseconds and milli-decibels;
decimal text exists only in grammar-checked inert FFmpeg tokens.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from typing import Any

from autoeditor.edit_policy import (
    EditPolicyError,
    edit_policy_sha256,
    validate_edit_policy,
)


MUSIC_ASSET_MANIFEST_SCHEMA_VERSION = "autoeditor-music-asset-manifest/v1"
MUSIC_PLAN_SCHEMA_VERSION = "autoeditor-music-plan/v1"
MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION = "autoeditor-music-compile-receipt/v1"

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_ASSETS = 128
MAX_BEAT_GRIDS = 128
MAX_DIALOGUE_WINDOWS = 4_096
MAX_SOURCE_MUSIC_REGIONS = 4_096
MAX_MUSIC_REGIONS = 256
MAX_TRACKS = 8
MAX_ASSET_BYTES = 1_099_511_627_776
MAX_ASSET_DURATION_MS = 14_400_000
MAX_OUTPUT_DURATION_MS = 86_400_000

SAMPLE_RATES_HZ = frozenset({
    8_000, 11_025, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000,
    88_200, 96_000, 176_400, 192_000,
})
PROVENANCE_KINDS = frozenset({
    "project_generated", "user_supplied", "licensed_external",
})
LICENSE_BASES = frozenset({
    "project_owned", "user_authorized", "licensed_external",
})
MUSIC_USAGES = frozenset({
    "forbidden", "optional", "supporting", "primary", "source_primary",
})
SOURCE_MUSIC_STATUSES = frozenset({"absent", "present"})
SOURCE_MUSIC_ACTIONS = frozenset({"none", "preserve"})
PLAYBACK_MODES = frozenset({"once", "loop"})
EVIDENCE_KINDS = frozenset({"audio_analysis", "transcript"})
DUCK_ATTENUATIONS_MILLIDB = frozenset({9_000, 12_000, 18_000, 24_000})
DUCK_THRESHOLDS_MILLIDBFS = frozenset({-36_000, -30_000, -24_000, -18_000})

_DUCK_THRESHOLD_LINEAR = {
    -36_000: "0.01584893192",
    -30_000: "0.03162277660",
    -24_000: "0.06309573445",
    -18_000: "0.1258925412",
}

_MANIFEST_KEYS = frozenset({
    "schema_version", "output_timeline_sha256", "output_duration_ms",
    "output_sample_rate_hz", "output_channels", "transcript_sha256",
    "source_music", "assets", "beat_grids", "dialogue_windows",
})
_SOURCE_MUSIC_KEYS = frozenset({
    "status", "evidence_sha256", "exclusion_authorization_sha256", "regions",
})
_SOURCE_REGION_KEYS = frozenset({
    "source_region_id", "start_ms", "end_ms", "evidence_sha256",
})
_SOURCE_REGION_PAYLOAD_KEYS = _SOURCE_REGION_KEYS - {"source_region_id"}
_ASSET_KEYS = frozenset({
    "asset_id", "sha256", "byte_length", "decoded_duration_ms",
    "sample_rate_hz", "channels", "source_ref", "provenance", "license",
    "rights_receipt",
})
_ASSET_PAYLOAD_KEYS = _ASSET_KEYS - {"asset_id"}
_LICENSE_KEYS = frozenset({
    "basis", "license_id", "license_name", "licensor", "evidence_sha256",
})
_RIGHTS_KEYS = frozenset({
    "receipt_id", "receipt_sha256", "permits_synchronization",
    "permits_editing", "permits_looping", "permits_delivery",
})
_BEAT_GRID_KEYS = frozenset({
    "beat_grid_id", "asset_id", "asset_sha256", "analysis_receipt_sha256",
    "beats_ms", "downbeats_ms",
})
_BEAT_GRID_PAYLOAD_KEYS = _BEAT_GRID_KEYS - {"beat_grid_id"}
_DIALOGUE_KEYS = frozenset({
    "dialogue_window_id", "start_ms", "end_ms", "evidence_kind",
    "evidence_sha256",
})
_DIALOGUE_PAYLOAD_KEYS = _DIALOGUE_KEYS - {"dialogue_window_id"}

_PLAN_KEYS = frozenset({
    "schema_version", "music_asset_manifest_sha256", "edit_policy_sha256",
    "output_timeline_sha256", "output_duration_ms", "policy", "mastering",
    "source_music_action", "regions",
})
_POLICY_KEYS = frozenset({
    "profile", "usage", "duck_under_dialogue", "max_added_track_count",
    "max_region_count", "max_polyphony", "max_added_coverage_ms",
    "max_gain_millidb", "speech_effective_gain_ceiling_millidb",
})
_MASTERING_KEYS = frozenset({
    "target_loudness_millilufs", "true_peak_ceiling_millidbtp",
})
_REGION_KEYS = frozenset({
    "region_id", "track_index", "asset_id", "asset_sha256", "start_ms",
    "duration_ms", "trim_start_ms", "playback_mode", "loop_length_ms",
    "loop_crossfade_ms", "gain_millidb", "fade_in_ms", "fade_out_ms",
    "crossfade_in_ms", "crossfade_out_ms", "beat_sync", "dialogue_ducking",
})
_REGION_PAYLOAD_KEYS = _REGION_KEYS - {"region_id"}
_BEAT_SYNC_KEYS = frozenset({
    "beat_grid_id", "analysis_receipt_sha256", "asset_beat_ms", "output_beat_ms",
})
_DUCKING_KEYS = frozenset({
    "dialogue_window_ids", "threshold_millidbfs", "attenuation_millidb",
    "attack_ms", "release_ms",
})

_RECEIPT_KEYS = frozenset({
    "schema_version", "music_plan_sha256", "music_asset_manifest_sha256",
    "edit_policy_sha256", "output_timeline_sha256", "compiled_regions_sha256",
    "mix_primitives_sha256", "ordered_region_ids", "ordered_asset_ids",
    "region_count", "unique_asset_count", "added_track_count",
    "max_observed_polyphony", "added_coverage_ms", "dialogue_overlap_region_count",
    "beat_synced_region_count", "looped_region_count", "source_music_action",
    "output_duration_ms", "output_sample_rate_hz", "output_channels",
    "target_loudness_millilufs", "true_peak_ceiling_millidbtp", "time_base",
    "millidb_base", "policy",
})
_BASE_KEYS = frozenset({"numerator", "denominator"})
_COMPILE_RESULT_KEYS = frozenset({
    "schema_version", "compiled_regions", "track_crossfade_ffmpeg_primitive_tokens",
    "music_bus_ffmpeg_primitive_tokens", "program_mix_ffmpeg_primitive_tokens",
    "output_ffmpeg_argument_tokens", "receipt", "receipt_sha256",
})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ASSET_ID_RE = re.compile(r"^musicasset-[0-9a-f]{64}$", re.ASCII)
_BEAT_GRID_ID_RE = re.compile(r"^beatgrid-[0-9a-f]{64}$", re.ASCII)
_DIALOGUE_ID_RE = re.compile(r"^dialogue-[0-9a-f]{64}$", re.ASCII)
_SOURCE_REGION_ID_RE = re.compile(r"^sourcemusic-[0-9a-f]{64}$", re.ASCII)
_REGION_ID_RE = re.compile(r"^musicregion-[0-9a-f]{64}$", re.ASCII)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$", re.ASCII)
_SOURCE_REF_RE = re.compile(
    r"^(project-generated|user-supplied|licensed-external)://"
    r"[A-Za-z0-9][A-Za-z0-9._/-]{0,383}$",
    re.ASCII,
)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_=.:,+*/-]{1,512}$", re.ASCII)

_PROVENANCE_LICENSE = {
    "project_generated": ("project-generated", "project_owned"),
    "user_supplied": ("user-supplied", "user_authorized"),
    "licensed_external": ("licensed-external", "licensed_external"),
}

_PROFILE_REGION_INTERVAL_MS = {
    "commercial_product": 30_000,
    "course_tutorial_screencast": 90_000,
    "dialogue_talking_head": 120_000,
    "documentary_narrative": 120_000,
    "gaming": 60_000,
    "montage_meme": 15_000,
    "music_performance": MAX_OUTPUT_DURATION_MS,
    "podcast_interview": 180_000,
    "real_estate": 60_000,
    "sports_highlights": 45_000,
    "utility_faithful": MAX_OUTPUT_DURATION_MS,
    "vlog_travel": 45_000,
    "wedding_event": 90_000,
}
_PROFILE_TRACK_CEILING = {
    "commercial_product": 2,
    "course_tutorial_screencast": 1,
    "dialogue_talking_head": 1,
    "documentary_narrative": 1,
    "gaming": 2,
    "montage_meme": 3,
    "music_performance": 0,
    "podcast_interview": 1,
    "real_estate": 1,
    "sports_highlights": 2,
    "utility_faithful": 0,
    "vlog_travel": 2,
    "wedding_event": 2,
}
_USAGE_TRACK_CEILING = {
    "forbidden": 0, "optional": 1, "supporting": 2, "primary": 3,
    "source_primary": 0,
}
_USAGE_POLYPHONY_CEILING = {
    "forbidden": 0, "optional": 1, "supporting": 1, "primary": 2,
    "source_primary": 0,
}
_PROFILE_GAIN_CEILING = {
    "commercial_product": 0, "course_tutorial_screencast": -3_000,
    "dialogue_talking_head": -6_000, "documentary_narrative": -6_000,
    "gaming": 0, "montage_meme": 0, "music_performance": -60_000,
    "podcast_interview": -9_000, "real_estate": -3_000,
    "sports_highlights": 0, "utility_faithful": -60_000,
    "vlog_travel": -3_000, "wedding_event": -6_000,
}
_SPEECH_GAIN_CEILING = {
    "none": 0, "supporting": -15_000, "primary": -18_000, "verbatim": -21_000,
}


class MusicPlanError(ValueError):
    """A manifest, policy, plan, compile result, or receipt is malformed."""


def _fail(message: str) -> None:
    raise MusicPlanError(message)


def _exact_dict(value: object, expected: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        _fail(f"{label} has invalid keys ({'; '.join(details)})")
    return value


def _integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_SAFE_INTEGER,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be boolean")
    return value


def _enum(value: object, choices: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in choices:
        _fail(f"{label} is unsupported")
    return value


def _identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(f"{label} has an invalid ASCII identifier")
    return value


def _sha256(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be a full lowercase SHA-256 digest")
    return value


def _nullable_sha256(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, label)


def _safe_ascii(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(f"{label} must be bounded safe ASCII text")
    return value


def _unicode_text(value: object, label: str, maximum: int = 160) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum:
        _fail(f"{label} must be bounded non-empty text")
    if value != unicodedata.normalize("NFC", value):
        _fail(f"{label} must use NFC Unicode normalization")
    if any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    ):
        _fail(f"{label} contains control, formatting, private, or surrogate characters")
    return value


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MusicPlanError(f"{label} is not canonical JSON") from error


def _ffmpeg_seconds(milliseconds: int) -> str:
    return f"{milliseconds // 1_000}.{milliseconds % 1_000:03d}"


def _ffmpeg_millidb(millidb: int, suffix: str = "dB") -> str:
    sign = "-" if millidb < 0 else ""
    absolute = abs(millidb)
    return f"{sign}{absolute // 1_000}.{absolute % 1_000:03d}{suffix}"


def _validate_tokens(tokens: object, label: str) -> list[str]:
    if type(tokens) is not list or len(tokens) > 512:
        _fail(f"{label} has invalid token cardinality")
    clean = []
    for index, token in enumerate(tokens):
        if type(token) is not str or _TOKEN_RE.fullmatch(token) is None:
            _fail(f"{label}[{index}] is not a safe inert token")
        clean.append(token)
    return clean


def _normalize_license(value: object, provenance: str, label: str) -> dict[str, str]:
    raw = _exact_dict(value, _LICENSE_KEYS, label)
    basis = _enum(raw["basis"], LICENSE_BASES, f"{label}.basis")
    expected_basis = _PROVENANCE_LICENSE[provenance][1]
    if basis != expected_basis:
        _fail(f"{label}.basis does not match asset provenance")
    license_id = _safe_ascii(raw["license_id"], _SAFE_ID_RE, f"{label}.license_id")
    license_name = _unicode_text(raw["license_name"], f"{label}.license_name")
    licensor = _unicode_text(raw["licensor"], f"{label}.licensor")
    if license_id != license_id.strip() or license_name != license_name.strip() or licensor != licensor.strip():
        _fail(f"{label} values must not have surrounding whitespace")
    license_id_folded = license_id.casefold()
    license_name_folded = license_name.casefold()
    licensor_folded = licensor.casefold()
    placeholders = {license_id_folded, license_name_folded, licensor_folded}
    if placeholders & {"unknown", "none", "unlicensed", "tbd", "n/a"}:
        _fail(f"{label} contains a placeholder rather than license evidence")
    if provenance == "project_generated":
        if license_id != "project-generated" or license_name != "Project ownership" or licensor != "project":
            _fail(f"{label} must identify project-generated ownership exactly")
    elif provenance == "licensed_external":
        if license_id_folded == "project-generated" or licensor_folded in {"project", "user"}:
            _fail(f"{label} does not establish an external license")
    else:
        if license_id_folded == "project-generated":
            _fail(f"{label}.license_id falsely claims project ownership")
        if licensor != "user":
            _fail(f"{label}.licensor must identify user authorization exactly")
    return {
        "basis": basis,
        "license_id": license_id,
        "license_name": license_name,
        "licensor": licensor,
        "evidence_sha256": _sha256(raw["evidence_sha256"], f"{label}.evidence_sha256"),
    }


def _normalize_rights(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _RIGHTS_KEYS, label)
    receipt_id = _safe_ascii(raw["receipt_id"], _SAFE_ID_RE, f"{label}.receipt_id")
    if receipt_id != receipt_id.strip() or receipt_id.casefold() in {"unknown", "none", "tbd", "n/a"}:
        _fail(f"{label}.receipt_id is a placeholder")
    return {
        "receipt_id": receipt_id,
        "receipt_sha256": _sha256(raw["receipt_sha256"], f"{label}.receipt_sha256"),
        "permits_synchronization": _boolean(raw["permits_synchronization"], f"{label}.permits_synchronization"),
        "permits_editing": _boolean(raw["permits_editing"], f"{label}.permits_editing"),
        "permits_looping": _boolean(raw["permits_looping"], f"{label}.permits_looping"),
        "permits_delivery": _boolean(raw["permits_delivery"], f"{label}.permits_delivery"),
    }


def _normalize_asset_payload(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _ASSET_PAYLOAD_KEYS, label)
    provenance = _enum(raw["provenance"], PROVENANCE_KINDS, f"{label}.provenance")
    source_ref = _safe_ascii(raw["source_ref"], _SOURCE_REF_RE, f"{label}.source_ref")
    expected_scheme = _PROVENANCE_LICENSE[provenance][0]
    if source_ref.split("://", 1)[0] != expected_scheme:
        _fail(f"{label}.source_ref scheme does not match provenance")
    tail = source_ref.split("://", 1)[1]
    if any(part in {"", ".", ".."} for part in tail.split("/")):
        _fail(f"{label}.source_ref contains an unsafe path segment")
    sample_rate = _integer(
        raw["sample_rate_hz"], f"{label}.sample_rate_hz",
        minimum=min(SAMPLE_RATES_HZ), maximum=max(SAMPLE_RATES_HZ),
    )
    if sample_rate not in SAMPLE_RATES_HZ:
        _fail(f"{label}.sample_rate_hz is unsupported")
    return {
        "sha256": _sha256(raw["sha256"], f"{label}.sha256"),
        "byte_length": _integer(raw["byte_length"], f"{label}.byte_length", minimum=1, maximum=MAX_ASSET_BYTES),
        "decoded_duration_ms": _integer(raw["decoded_duration_ms"], f"{label}.decoded_duration_ms", minimum=1, maximum=MAX_ASSET_DURATION_MS),
        "sample_rate_hz": sample_rate,
        "channels": _integer(raw["channels"], f"{label}.channels", minimum=1, maximum=8),
        "source_ref": source_ref,
        "provenance": provenance,
        "license": _normalize_license(raw["license"], provenance, f"{label}.license"),
        "rights_receipt": _normalize_rights(raw["rights_receipt"], f"{label}.rights_receipt"),
    }


def derive_music_asset_id(asset_without_id: object) -> str:
    normalized = _normalize_asset_payload(asset_without_id, "music asset binding")
    digest = hashlib.sha256(_canonical_json(normalized, "music asset binding").encode("utf-8")).hexdigest()
    return "musicasset-" + digest


def _normalize_source_region_payload(value: object, label: str, duration: int) -> dict[str, Any]:
    raw = _exact_dict(value, _SOURCE_REGION_PAYLOAD_KEYS, label)
    start = _integer(raw["start_ms"], f"{label}.start_ms", maximum=duration)
    end = _integer(raw["end_ms"], f"{label}.end_ms", maximum=duration)
    if end <= start:
        _fail(f"{label} must have positive duration")
    return {"start_ms": start, "end_ms": end, "evidence_sha256": _sha256(raw["evidence_sha256"], f"{label}.evidence_sha256")}


def derive_source_music_region_id(region_without_id: object, output_duration_ms: object) -> str:
    duration = _integer(output_duration_ms, "output_duration_ms", minimum=1, maximum=MAX_OUTPUT_DURATION_MS)
    normalized = _normalize_source_region_payload(region_without_id, "source music region binding", duration)
    digest = hashlib.sha256(_canonical_json(normalized, "source music region binding").encode("utf-8")).hexdigest()
    return "sourcemusic-" + digest


def _normalize_dialogue_payload(value: object, label: str, duration: int, transcript: str | None) -> dict[str, Any]:
    raw = _exact_dict(value, _DIALOGUE_PAYLOAD_KEYS, label)
    start = _integer(raw["start_ms"], f"{label}.start_ms", maximum=duration)
    end = _integer(raw["end_ms"], f"{label}.end_ms", maximum=duration)
    if end <= start:
        _fail(f"{label} must have positive duration")
    evidence_kind = _enum(raw["evidence_kind"], EVIDENCE_KINDS, f"{label}.evidence_kind")
    if evidence_kind == "transcript" and transcript is None:
        _fail(f"{label} claims transcript evidence without a trusted transcript")
    return {
        "start_ms": start,
        "end_ms": end,
        "evidence_kind": evidence_kind,
        "evidence_sha256": _sha256(raw["evidence_sha256"], f"{label}.evidence_sha256"),
    }


def derive_dialogue_window_id(
    window_without_id: object,
    output_duration_ms: object,
    transcript_sha256: object = None,
) -> str:
    duration = _integer(output_duration_ms, "output_duration_ms", minimum=1, maximum=MAX_OUTPUT_DURATION_MS)
    transcript = _nullable_sha256(transcript_sha256, "transcript_sha256")
    normalized = _normalize_dialogue_payload(window_without_id, "dialogue window binding", duration, transcript)
    digest = hashlib.sha256(_canonical_json(normalized, "dialogue window binding").encode("utf-8")).hexdigest()
    return "dialogue-" + digest


def _normalize_beat_grid_payload(value: object, label: str, assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = _exact_dict(value, _BEAT_GRID_PAYLOAD_KEYS, label)
    asset_id = _identifier(raw["asset_id"], _ASSET_ID_RE, f"{label}.asset_id")
    asset = assets.get(asset_id)
    if asset is None:
        _fail(f"{label}.asset_id is absent from the trusted asset manifest")
    asset_hash = _sha256(raw["asset_sha256"], f"{label}.asset_sha256")
    if asset_hash != asset["sha256"]:
        _fail(f"{label}.asset_sha256 does not match trusted bytes")
    beats_raw = raw["beats_ms"]
    if type(beats_raw) is not list or not 1 <= len(beats_raw) <= 65_536:
        _fail(f"{label}.beats_ms has invalid cardinality")
    beats = [_integer(item, f"{label}.beats_ms[{index}]", maximum=asset["decoded_duration_ms"]) for index, item in enumerate(beats_raw)]
    if beats != sorted(set(beats)):
        _fail(f"{label}.beats_ms must be strictly increasing and unique")
    down_raw = raw["downbeats_ms"]
    if type(down_raw) is not list or len(down_raw) > len(beats):
        _fail(f"{label}.downbeats_ms has invalid cardinality")
    downbeats = [_integer(item, f"{label}.downbeats_ms[{index}]", maximum=asset["decoded_duration_ms"]) for index, item in enumerate(down_raw)]
    if downbeats != sorted(set(downbeats)) or not set(downbeats).issubset(beats):
        _fail(f"{label}.downbeats_ms must be a sorted subset of beats_ms")
    return {
        "asset_id": asset_id,
        "asset_sha256": asset_hash,
        "analysis_receipt_sha256": _sha256(raw["analysis_receipt_sha256"], f"{label}.analysis_receipt_sha256"),
        "beats_ms": beats,
        "downbeats_ms": downbeats,
    }


def derive_beat_grid_id(grid_without_id: object, assets: object) -> str:
    if type(assets) is not list:
        _fail("assets must be a list")
    asset_map = {}
    for index, value in enumerate(assets):
        item = _exact_dict(value, _ASSET_KEYS, f"assets[{index}]")
        payload = _normalize_asset_payload({key: item[key] for key in _ASSET_PAYLOAD_KEYS}, f"assets[{index}]")
        asset_id = _identifier(item["asset_id"], _ASSET_ID_RE, f"assets[{index}].asset_id")
        if asset_id != derive_music_asset_id(payload):
            _fail(f"assets[{index}].asset_id does not bind exact facts")
        asset_map[asset_id] = {"asset_id": asset_id, **payload}
    normalized = _normalize_beat_grid_payload(grid_without_id, "beat grid binding", asset_map)
    digest = hashlib.sha256(_canonical_json(normalized, "beat grid binding").encode("utf-8")).hexdigest()
    return "beatgrid-" + digest


def validate_music_asset_manifest(manifest: object) -> dict[str, Any]:
    raw = _exact_dict(manifest, _MANIFEST_KEYS, "music asset manifest")
    if raw["schema_version"] != MUSIC_ASSET_MANIFEST_SCHEMA_VERSION:
        _fail("music asset manifest schema_version is unsupported")
    timeline_hash = _sha256(raw["output_timeline_sha256"], "music asset manifest.output_timeline_sha256")
    duration = _integer(raw["output_duration_ms"], "music asset manifest.output_duration_ms", minimum=1, maximum=MAX_OUTPUT_DURATION_MS)
    sample_rate = _integer(raw["output_sample_rate_hz"], "music asset manifest.output_sample_rate_hz", minimum=48_000, maximum=48_000)
    channels = _integer(raw["output_channels"], "music asset manifest.output_channels", minimum=2, maximum=2)
    transcript = _nullable_sha256(raw["transcript_sha256"], "music asset manifest.transcript_sha256")

    assets_raw = raw["assets"]
    if type(assets_raw) is not list or len(assets_raw) > MAX_ASSETS:
        _fail("music asset manifest.assets has invalid cardinality")
    assets = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    seen_refs: set[str] = set()
    for index, raw_asset in enumerate(assets_raw):
        label = f"music asset manifest.assets[{index}]"
        item = _exact_dict(raw_asset, _ASSET_KEYS, label)
        payload = _normalize_asset_payload({key: item[key] for key in _ASSET_PAYLOAD_KEYS}, label)
        asset_id = _identifier(item["asset_id"], _ASSET_ID_RE, f"{label}.asset_id")
        if asset_id != derive_music_asset_id(payload):
            _fail(f"{label}.asset_id does not bind exact media and rights facts")
        if asset_id in seen_ids or payload["sha256"] in seen_hashes or payload["source_ref"] in seen_refs:
            _fail("music assets must have unique ids, byte hashes, and source references")
        seen_ids.add(asset_id)
        seen_hashes.add(payload["sha256"])
        seen_refs.add(payload["source_ref"])
        assets.append({"asset_id": asset_id, **payload})
    if assets != sorted(assets, key=lambda item: item["asset_id"]):
        _fail("music asset manifest.assets must be ordered by asset_id")
    asset_map = {item["asset_id"]: item for item in assets}

    grids_raw = raw["beat_grids"]
    if type(grids_raw) is not list or len(grids_raw) > MAX_BEAT_GRIDS:
        _fail("music asset manifest.beat_grids has invalid cardinality")
    grids = []
    grid_ids: set[str] = set()
    grid_assets: set[str] = set()
    for index, raw_grid in enumerate(grids_raw):
        label = f"music asset manifest.beat_grids[{index}]"
        item = _exact_dict(raw_grid, _BEAT_GRID_KEYS, label)
        payload = _normalize_beat_grid_payload({key: item[key] for key in _BEAT_GRID_PAYLOAD_KEYS}, label, asset_map)
        grid_id = _identifier(item["beat_grid_id"], _BEAT_GRID_ID_RE, f"{label}.beat_grid_id")
        expected = "beatgrid-" + hashlib.sha256(_canonical_json(payload, label).encode("utf-8")).hexdigest()
        if grid_id != expected:
            _fail(f"{label}.beat_grid_id does not bind exact trusted beat evidence")
        if grid_id in grid_ids or payload["asset_id"] in grid_assets:
            _fail("music asset manifest permits only one unique beat grid per asset")
        grid_ids.add(grid_id)
        grid_assets.add(payload["asset_id"])
        grids.append({"beat_grid_id": grid_id, **payload})
    if grids != sorted(grids, key=lambda item: (item["asset_id"], item["beat_grid_id"])):
        _fail("music asset manifest.beat_grids must be ordered by asset_id then beat_grid_id")

    dialogue_raw = raw["dialogue_windows"]
    if type(dialogue_raw) is not list or len(dialogue_raw) > MAX_DIALOGUE_WINDOWS:
        _fail("music asset manifest.dialogue_windows has invalid cardinality")
    dialogue = []
    dialogue_ids: set[str] = set()
    for index, raw_window in enumerate(dialogue_raw):
        label = f"music asset manifest.dialogue_windows[{index}]"
        item = _exact_dict(raw_window, _DIALOGUE_KEYS, label)
        payload = _normalize_dialogue_payload({key: item[key] for key in _DIALOGUE_PAYLOAD_KEYS}, label, duration, transcript)
        window_id = _identifier(item["dialogue_window_id"], _DIALOGUE_ID_RE, f"{label}.dialogue_window_id")
        expected = "dialogue-" + hashlib.sha256(_canonical_json(payload, label).encode("utf-8")).hexdigest()
        if window_id != expected:
            _fail(f"{label}.dialogue_window_id does not bind exact evidence")
        if window_id in dialogue_ids:
            _fail("dialogue window ids must be unique")
        dialogue_ids.add(window_id)
        dialogue.append({"dialogue_window_id": window_id, **payload})
    if dialogue != sorted(dialogue, key=lambda item: (item["start_ms"], item["dialogue_window_id"])):
        _fail("dialogue windows must be ordered by start_ms then id")
    for left, right in zip(dialogue, dialogue[1:]):
        if left["end_ms"] > right["start_ms"]:
            _fail("trusted dialogue windows must not overlap")

    source_raw = _exact_dict(raw["source_music"], _SOURCE_MUSIC_KEYS, "music asset manifest.source_music")
    status = _enum(source_raw["status"], SOURCE_MUSIC_STATUSES, "music asset manifest.source_music.status")
    source_evidence = _sha256(source_raw["evidence_sha256"], "music asset manifest.source_music.evidence_sha256")
    authorization = _nullable_sha256(source_raw["exclusion_authorization_sha256"], "music asset manifest.source_music.exclusion_authorization_sha256")
    source_regions_raw = source_raw["regions"]
    if type(source_regions_raw) is not list or len(source_regions_raw) > MAX_SOURCE_MUSIC_REGIONS:
        _fail("music asset manifest.source_music.regions has invalid cardinality")
    source_regions = []
    source_ids: set[str] = set()
    for index, raw_region in enumerate(source_regions_raw):
        label = f"music asset manifest.source_music.regions[{index}]"
        item = _exact_dict(raw_region, _SOURCE_REGION_KEYS, label)
        payload = _normalize_source_region_payload({key: item[key] for key in _SOURCE_REGION_PAYLOAD_KEYS}, label, duration)
        region_id = _identifier(item["source_region_id"], _SOURCE_REGION_ID_RE, f"{label}.source_region_id")
        if region_id != derive_source_music_region_id(payload, duration):
            _fail(f"{label}.source_region_id does not bind exact source evidence")
        if region_id in source_ids:
            _fail("source music region ids must be unique")
        source_ids.add(region_id)
        source_regions.append({"source_region_id": region_id, **payload})
    if source_regions != sorted(source_regions, key=lambda item: (item["start_ms"], item["source_region_id"])):
        _fail("source music regions must be ordered by start_ms then id")
    for left, right in zip(source_regions, source_regions[1:]):
        if left["end_ms"] > right["start_ms"]:
            _fail("source music regions must not overlap")
    if status == "absent" and (source_regions or authorization is not None):
        _fail("absent source music cannot have regions or exclusion authority")
    if status == "present" and not source_regions:
        _fail("present source music requires trusted detected regions")

    return copy.deepcopy({
        "schema_version": MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": timeline_hash,
        "output_duration_ms": duration,
        "output_sample_rate_hz": sample_rate,
        "output_channels": channels,
        "transcript_sha256": transcript,
        "source_music": {
            "status": status,
            "evidence_sha256": source_evidence,
            "exclusion_authorization_sha256": authorization,
            "regions": source_regions,
        },
        "assets": assets,
        "beat_grids": grids,
        "dialogue_windows": dialogue,
    })


def canonical_music_asset_manifest_json(manifest: object) -> str:
    return _canonical_json(validate_music_asset_manifest(manifest), "music asset manifest")


def music_asset_manifest_sha256(manifest: object) -> str:
    return hashlib.sha256(canonical_music_asset_manifest_json(manifest).encode("utf-8")).hexdigest()


def _mastering_from_policy(policy: dict[str, Any]) -> dict[str, int]:
    platform = policy["delivery"]["platform"]
    if platform == "broadcast":
        return {"target_loudness_millilufs": -23_000, "true_peak_ceiling_millidbtp": -2_000}
    if platform == "archive":
        return {"target_loudness_millilufs": -18_000, "true_peak_ceiling_millidbtp": -2_000}
    return {"target_loudness_millilufs": -14_000, "true_peak_ceiling_millidbtp": -1_000}


def _policy_limits(policy: dict[str, Any], duration: int) -> dict[str, Any]:
    profile = policy["profile"]
    if profile not in _PROFILE_REGION_INTERVAL_MS:
        _fail("edit policy profile has no closed music limits")
    usage = policy["rules"]["music"]["usage"]
    max_tracks = min(_PROFILE_TRACK_CEILING[profile], _USAGE_TRACK_CEILING[usage])
    max_polyphony = min(max_tracks, _USAGE_POLYPHONY_CEILING[usage])
    if usage in {"forbidden", "source_primary"}:
        max_regions = 0
        coverage = 0
    else:
        interval = _PROFILE_REGION_INTERVAL_MS[profile]
        max_regions = min(MAX_MUSIC_REGIONS, (duration + interval - 1) // interval)
        coverage = duration // 2 if usage == "optional" else duration
    dialogue_priority = policy["rules"]["dialogue"]["priority"]
    return {
        "profile": profile,
        "usage": usage,
        "duck_under_dialogue": policy["rules"]["music"]["duck_under_dialogue"],
        "max_added_track_count": max_tracks,
        "max_region_count": max_regions,
        "max_polyphony": max_polyphony,
        "max_added_coverage_ms": coverage,
        "max_gain_millidb": _PROFILE_GAIN_CEILING[profile],
        "speech_effective_gain_ceiling_millidb": _SPEECH_GAIN_CEILING[dialogue_priority],
    }


def derive_music_policy_limits(edit_policy: object, output_duration_ms: object) -> dict[str, Any]:
    duration = _integer(output_duration_ms, "output_duration_ms", minimum=1, maximum=MAX_OUTPUT_DURATION_MS)
    try:
        policy = validate_edit_policy(edit_policy)
    except EditPolicyError as error:
        raise MusicPlanError("edit policy is invalid") from error
    if policy["duration"]["duration_ms"] != duration:
        _fail("edit policy duration does not match the exact output duration")
    return copy.deepcopy(_policy_limits(policy, duration))


def derive_music_mastering(edit_policy: object) -> dict[str, int]:
    try:
        policy = validate_edit_policy(edit_policy)
    except EditPolicyError as error:
        raise MusicPlanError("edit policy is invalid") from error
    return copy.deepcopy(_mastering_from_policy(policy))


def _normalize_policy_snapshot(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _POLICY_KEYS, label)
    return {
        "profile": _safe_ascii(raw["profile"], _SAFE_ID_RE, f"{label}.profile"),
        "usage": _enum(raw["usage"], MUSIC_USAGES, f"{label}.usage"),
        "duck_under_dialogue": _boolean(raw["duck_under_dialogue"], f"{label}.duck_under_dialogue"),
        "max_added_track_count": _integer(raw["max_added_track_count"], f"{label}.max_added_track_count", maximum=MAX_TRACKS),
        "max_region_count": _integer(raw["max_region_count"], f"{label}.max_region_count", maximum=MAX_MUSIC_REGIONS),
        "max_polyphony": _integer(raw["max_polyphony"], f"{label}.max_polyphony", maximum=MAX_TRACKS),
        "max_added_coverage_ms": _integer(raw["max_added_coverage_ms"], f"{label}.max_added_coverage_ms", maximum=MAX_OUTPUT_DURATION_MS),
        "max_gain_millidb": _integer(raw["max_gain_millidb"], f"{label}.max_gain_millidb", minimum=-60_000, maximum=6_000),
        "speech_effective_gain_ceiling_millidb": _integer(raw["speech_effective_gain_ceiling_millidb"], f"{label}.speech_effective_gain_ceiling_millidb", minimum=-60_000, maximum=0),
    }


def _normalize_mastering(value: object, label: str) -> dict[str, int]:
    raw = _exact_dict(value, _MASTERING_KEYS, label)
    target = _integer(raw["target_loudness_millilufs"], f"{label}.target_loudness_millilufs", minimum=-40_000, maximum=-5_000)
    peak = _integer(raw["true_peak_ceiling_millidbtp"], f"{label}.true_peak_ceiling_millidbtp", minimum=-9_000, maximum=-100)
    return {"target_loudness_millilufs": target, "true_peak_ceiling_millidbtp": peak}


def _normalize_beat_sync(value: object, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = _exact_dict(value, _BEAT_SYNC_KEYS, label)
    return {
        "beat_grid_id": _identifier(raw["beat_grid_id"], _BEAT_GRID_ID_RE, f"{label}.beat_grid_id"),
        "analysis_receipt_sha256": _sha256(raw["analysis_receipt_sha256"], f"{label}.analysis_receipt_sha256"),
        "asset_beat_ms": _integer(raw["asset_beat_ms"], f"{label}.asset_beat_ms", maximum=MAX_ASSET_DURATION_MS),
        "output_beat_ms": _integer(raw["output_beat_ms"], f"{label}.output_beat_ms", maximum=MAX_OUTPUT_DURATION_MS),
    }


def _normalize_ducking(value: object, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = _exact_dict(value, _DUCKING_KEYS, label)
    ids_raw = raw["dialogue_window_ids"]
    if type(ids_raw) is not list or not 1 <= len(ids_raw) <= MAX_DIALOGUE_WINDOWS:
        _fail(f"{label}.dialogue_window_ids has invalid cardinality")
    ids = [_identifier(item, _DIALOGUE_ID_RE, f"{label}.dialogue_window_ids[{index}]") for index, item in enumerate(ids_raw)]
    if ids != sorted(set(ids)):
        _fail(f"{label}.dialogue_window_ids must be sorted and unique")
    threshold = _integer(raw["threshold_millidbfs"], f"{label}.threshold_millidbfs", minimum=-60_000, maximum=0)
    if threshold not in DUCK_THRESHOLDS_MILLIDBFS:
        _fail(f"{label}.threshold_millidbfs is not a deterministic v1 preset")
    attenuation = _integer(raw["attenuation_millidb"], f"{label}.attenuation_millidb", minimum=1, maximum=60_000)
    if attenuation not in DUCK_ATTENUATIONS_MILLIDB:
        _fail(f"{label}.attenuation_millidb is not a deterministic v1 preset")
    return {
        "dialogue_window_ids": ids,
        "threshold_millidbfs": threshold,
        "attenuation_millidb": attenuation,
        "attack_ms": _integer(raw["attack_ms"], f"{label}.attack_ms", minimum=1, maximum=200),
        "release_ms": _integer(raw["release_ms"], f"{label}.release_ms", minimum=1, maximum=2_000),
    }


def _normalize_region_payload(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _REGION_PAYLOAD_KEYS, label)
    return {
        "track_index": _integer(raw["track_index"], f"{label}.track_index", maximum=MAX_TRACKS - 1),
        "asset_id": _identifier(raw["asset_id"], _ASSET_ID_RE, f"{label}.asset_id"),
        "asset_sha256": _sha256(raw["asset_sha256"], f"{label}.asset_sha256"),
        "start_ms": _integer(raw["start_ms"], f"{label}.start_ms", maximum=MAX_OUTPUT_DURATION_MS),
        "duration_ms": _integer(raw["duration_ms"], f"{label}.duration_ms", minimum=20, maximum=MAX_OUTPUT_DURATION_MS),
        "trim_start_ms": _integer(raw["trim_start_ms"], f"{label}.trim_start_ms", maximum=MAX_ASSET_DURATION_MS),
        "playback_mode": _enum(raw["playback_mode"], PLAYBACK_MODES, f"{label}.playback_mode"),
        "loop_length_ms": _integer(raw["loop_length_ms"], f"{label}.loop_length_ms", maximum=MAX_ASSET_DURATION_MS),
        "loop_crossfade_ms": _integer(raw["loop_crossfade_ms"], f"{label}.loop_crossfade_ms", maximum=2_000),
        "gain_millidb": _integer(raw["gain_millidb"], f"{label}.gain_millidb", minimum=-60_000, maximum=6_000),
        "fade_in_ms": _integer(raw["fade_in_ms"], f"{label}.fade_in_ms", maximum=10_000),
        "fade_out_ms": _integer(raw["fade_out_ms"], f"{label}.fade_out_ms", maximum=10_000),
        "crossfade_in_ms": _integer(raw["crossfade_in_ms"], f"{label}.crossfade_in_ms", maximum=5_000),
        "crossfade_out_ms": _integer(raw["crossfade_out_ms"], f"{label}.crossfade_out_ms", maximum=5_000),
        "beat_sync": _normalize_beat_sync(raw["beat_sync"], f"{label}.beat_sync"),
        "dialogue_ducking": _normalize_ducking(raw["dialogue_ducking"], f"{label}.dialogue_ducking"),
    }


def derive_music_region_id(region_without_id: object) -> str:
    normalized = _normalize_region_payload(region_without_id, "music region binding")
    digest = hashlib.sha256(_canonical_json(normalized, "music region binding").encode("utf-8")).hexdigest()
    return "musicregion-" + digest


def _normalize_plan(plan: object) -> dict[str, Any]:
    raw = _exact_dict(plan, _PLAN_KEYS, "music plan")
    if raw["schema_version"] != MUSIC_PLAN_SCHEMA_VERSION:
        _fail("music plan schema_version is unsupported")
    regions_raw = raw["regions"]
    if type(regions_raw) is not list or len(regions_raw) > MAX_MUSIC_REGIONS:
        _fail("music plan.regions has invalid cardinality")
    regions = []
    ids: set[str] = set()
    for index, raw_region in enumerate(regions_raw):
        label = f"music plan.regions[{index}]"
        item = _exact_dict(raw_region, _REGION_KEYS, label)
        payload = _normalize_region_payload({key: item[key] for key in _REGION_PAYLOAD_KEYS}, label)
        region_id = _identifier(item["region_id"], _REGION_ID_RE, f"{label}.region_id")
        if region_id != derive_music_region_id(payload):
            _fail(f"{label}.region_id does not bind the exact region decision")
        if region_id in ids:
            _fail("music region ids must be unique")
        ids.add(region_id)
        regions.append({"region_id": region_id, **payload})
    if regions != sorted(regions, key=lambda item: (item["start_ms"], item["track_index"], item["region_id"])):
        _fail("music regions must be ordered by start_ms, track_index, then id")
    return {
        "schema_version": MUSIC_PLAN_SCHEMA_VERSION,
        "music_asset_manifest_sha256": _sha256(raw["music_asset_manifest_sha256"], "music plan.music_asset_manifest_sha256"),
        "edit_policy_sha256": _sha256(raw["edit_policy_sha256"], "music plan.edit_policy_sha256"),
        "output_timeline_sha256": _sha256(raw["output_timeline_sha256"], "music plan.output_timeline_sha256"),
        "output_duration_ms": _integer(raw["output_duration_ms"], "music plan.output_duration_ms", minimum=1, maximum=MAX_OUTPUT_DURATION_MS),
        "policy": _normalize_policy_snapshot(raw["policy"], "music plan.policy"),
        "mastering": _normalize_mastering(raw["mastering"], "music plan.mastering"),
        "source_music_action": _enum(raw["source_music_action"], SOURCE_MUSIC_ACTIONS, "music plan.source_music_action"),
        "regions": regions,
    }


def canonical_music_plan_json(plan: object) -> str:
    return _canonical_json(_normalize_plan(plan), "music plan")


def music_plan_sha256(plan: object) -> str:
    return hashlib.sha256(canonical_music_plan_json(plan).encode("utf-8")).hexdigest()


def _intersects(start: int, end: int, other_start: int, other_end: int) -> bool:
    return max(start, other_start) < min(end, other_end)


def _max_polyphony(intervals: list[tuple[int, int]]) -> int:
    events = []
    for start, end in intervals:
        events.extend(((start, 1), (end, -1)))
    active = 0
    observed = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        observed = max(observed, active)
    return observed


def _coverage_ms(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    total = 0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start > end:
            total += end - start
            start, end = next_start, next_end
        else:
            end = max(end, next_end)
    return total + end - start


def validate_music_plan(plan: object, asset_manifest: object, edit_policy: object) -> dict[str, Any]:
    normalized = _normalize_plan(plan)
    manifest = validate_music_asset_manifest(asset_manifest)
    try:
        policy = validate_edit_policy(edit_policy)
        policy_hash = edit_policy_sha256(policy)
    except EditPolicyError as error:
        raise MusicPlanError("edit policy is invalid") from error
    if policy["duration"]["duration_ms"] != manifest["output_duration_ms"]:
        _fail("resolved edit policy duration does not match the trusted output duration")
    if normalized["music_asset_manifest_sha256"] != music_asset_manifest_sha256(manifest):
        _fail("music plan does not bind the trusted asset manifest")
    if normalized["edit_policy_sha256"] != policy_hash:
        _fail("music plan does not bind the resolved edit policy")
    if normalized["output_timeline_sha256"] != manifest["output_timeline_sha256"]:
        _fail("music plan does not bind the trusted output timeline")
    if normalized["output_duration_ms"] != manifest["output_duration_ms"]:
        _fail("music plan does not bind the exact output duration")
    expected_policy = _policy_limits(policy, manifest["output_duration_ms"])
    if normalized["policy"] != expected_policy:
        _fail("music plan policy snapshot does not match the resolved edit policy")
    if normalized["mastering"] != _mastering_from_policy(policy):
        _fail("music plan mastering target does not match delivery policy")
    if len(normalized["regions"]) > expected_policy["max_region_count"]:
        _fail("music plan exceeds its profile/duration region density ceiling")

    source = manifest["source_music"]
    action = normalized["source_music_action"]
    if source["status"] == "absent":
        if action != "none":
            _fail("source music action must be none when source music is absent")
    else:
        if action != "preserve":
            _fail("present source music must be preserved by music contract v1")
    usage = expected_policy["usage"]
    if usage in {"forbidden", "source_primary"} and normalized["regions"]:
        _fail("music policy permits no added music assets")
    if usage == "source_primary":
        if source["status"] != "present" or action != "preserve":
            _fail("source-primary music requires detected source music to be preserved")
    if usage == "forbidden" and source["status"] == "present" and action != "preserve":
        _fail("forbidden added music does not authorize deleting source programme audio")

    assets = {item["asset_id"]: item for item in manifest["assets"]}
    grids = {item["beat_grid_id"]: item for item in manifest["beat_grids"]}
    dialogue = {item["dialogue_window_id"]: item for item in manifest["dialogue_windows"]}
    intervals: list[tuple[int, int]] = []
    track_regions: dict[int, list[dict[str, Any]]] = {}
    used_tracks: set[int] = set()
    dialogue_priority = policy["rules"]["dialogue"]["priority"]

    for index, region in enumerate(normalized["regions"]):
        label = f"music plan.regions[{index}]"
        asset = assets.get(region["asset_id"])
        if asset is None:
            _fail(f"{label}.asset_id is absent from the trusted manifest")
        if region["asset_sha256"] != asset["sha256"]:
            _fail(f"{label}.asset_sha256 does not match trusted bytes")
        rights = asset["rights_receipt"]
        if not rights["permits_synchronization"] or not rights["permits_editing"] or not rights["permits_delivery"]:
            _fail(f"{label} lacks explicit synchronization, editing, or delivery rights")
        start = region["start_ms"]
        end = start + region["duration_ms"]
        if end > manifest["output_duration_ms"]:
            _fail(f"{label} extends beyond the exact output duration")
        if region["gain_millidb"] > expected_policy["max_gain_millidb"]:
            _fail(f"{label}.gain_millidb exceeds its profile ceiling")
        if region["fade_in_ms"] + region["fade_out_ms"] > region["duration_ms"]:
            _fail(f"{label} fade-in and fade-out overlap")
        if region["crossfade_in_ms"] > region["fade_in_ms"] or region["crossfade_out_ms"] > region["fade_out_ms"]:
            _fail(f"{label} crossfade must be covered by its edge fade")
        if region["crossfade_in_ms"] or region["crossfade_out_ms"]:
            _fail(f"{label} crossfade topology is not executable in music contract v1")
        mode = region["playback_mode"]
        if mode == "once":
            if region["loop_length_ms"] != 0 or region["loop_crossfade_ms"] != 0:
                _fail(f"{label} once playback cannot carry loop parameters")
            if region["trim_start_ms"] + region["duration_ms"] > asset["decoded_duration_ms"]:
                _fail(f"{label} trim exceeds trusted decoded asset duration")
        else:
            _fail(f"{label} loop playback is not executable in music contract v1")

        beat = region["beat_sync"]
        if beat is not None:
            grid = grids.get(beat["beat_grid_id"])
            if grid is None or grid["asset_id"] != asset["asset_id"]:
                _fail(f"{label}.beat_sync is not grounded in a trusted grid for this asset")
            if beat["analysis_receipt_sha256"] != grid["analysis_receipt_sha256"]:
                _fail(f"{label}.beat_sync does not copy the trusted analysis receipt")
            if beat["asset_beat_ms"] not in grid["beats_ms"]:
                _fail(f"{label}.beat_sync asset beat is absent from trusted evidence")
            if beat["asset_beat_ms"] != region["trim_start_ms"] or beat["output_beat_ms"] != start:
                _fail(f"{label}.beat_sync does not map the selected source beat to region start")
            if mode == "loop" and region["trim_start_ms"] + region["loop_length_ms"] not in grid["beats_ms"]:
                _fail(f"{label} loop endpoint is not grounded in the trusted beat grid")

        overlapping_dialogue = sorted(
            window_id for window_id, window in dialogue.items()
            if _intersects(start, end, window["start_ms"], window["end_ms"])
        )
        duck = region["dialogue_ducking"]
        if duck is not None:
            _fail(f"{label} dialogue sidechain topology is not executable in music contract v1")
        if overlapping_dialogue and expected_policy["duck_under_dialogue"]:
            _fail(f"{label} overlaps dialogue that requires an unimplemented v1 sidechain")
        elif duck is not None:
            _fail(f"{label}.dialogue_ducking is unmotivated by policy-grounded dialogue overlap")

        if action == "preserve":
            for source_region in source["regions"]:
                if _intersects(start, end, source_region["start_ms"], source_region["end_ms"]):
                    _fail(f"{label} overlaps source music that must be preserved exclusively")
        intervals.append((start, end))
        used_tracks.add(region["track_index"])
        track_regions.setdefault(region["track_index"], []).append(region)

    if used_tracks and used_tracks != set(range(max(used_tracks) + 1)):
        _fail("music track indices must be contiguous from zero")
    if len(used_tracks) > expected_policy["max_added_track_count"]:
        _fail("music plan exceeds its profile/usage added-track ceiling")
    if _max_polyphony(intervals) > expected_policy["max_polyphony"]:
        _fail("music plan exceeds its profile/usage polyphony ceiling")
    if _coverage_ms(intervals) > expected_policy["max_added_coverage_ms"]:
        _fail("music plan exceeds its usage coverage ceiling")

    for track_index, regions in track_regions.items():
        ordered = sorted(regions, key=lambda item: (item["start_ms"], item["region_id"]))
        if ordered[0]["crossfade_in_ms"] != 0 or ordered[-1]["crossfade_out_ms"] != 0:
            _fail(f"music track {track_index} has an unpaired edge crossfade")
        for left, right in zip(ordered, ordered[1:]):
            overlap = max(0, left["start_ms"] + left["duration_ms"] - right["start_ms"])
            if left["crossfade_out_ms"] != overlap or right["crossfade_in_ms"] != overlap:
                _fail(f"music track {track_index} crossfade does not equal exact region overlap")
            if overlap > min(5_000, left["duration_ms"] // 2, right["duration_ms"] // 2):
                _fail(f"music track {track_index} crossfade exceeds adjacent duration guards")
            if overlap:
                _fail(f"music track {track_index} crossfade topology is not executable in music contract v1")
    return copy.deepcopy(normalized)


def _normalize_receipt(receipt: object) -> dict[str, Any]:
    raw = _exact_dict(receipt, _RECEIPT_KEYS, "music compile receipt")
    if raw["schema_version"] != MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION:
        _fail("music compile receipt schema_version is unsupported")
    hashes = {key: _sha256(raw[key], f"music compile receipt.{key}") for key in (
        "music_plan_sha256", "music_asset_manifest_sha256", "edit_policy_sha256",
        "output_timeline_sha256", "compiled_regions_sha256", "mix_primitives_sha256",
    )}
    region_ids_raw = raw["ordered_region_ids"]
    asset_ids_raw = raw["ordered_asset_ids"]
    if type(region_ids_raw) is not list or len(region_ids_raw) > MAX_MUSIC_REGIONS:
        _fail("music compile receipt.ordered_region_ids has invalid cardinality")
    if type(asset_ids_raw) is not list or len(asset_ids_raw) != len(region_ids_raw):
        _fail("music compile receipt.ordered_asset_ids must align one-to-one")
    region_ids = [_identifier(item, _REGION_ID_RE, f"music compile receipt.ordered_region_ids[{index}]") for index, item in enumerate(region_ids_raw)]
    if len(region_ids) != len(set(region_ids)):
        _fail("music compile receipt region ids must be unique")
    asset_ids = [_identifier(item, _ASSET_ID_RE, f"music compile receipt.ordered_asset_ids[{index}]") for index, item in enumerate(asset_ids_raw)]
    region_count = _integer(raw["region_count"], "music compile receipt.region_count", maximum=MAX_MUSIC_REGIONS)
    if region_count != len(region_ids):
        _fail("music compile receipt.region_count does not match ids")
    unique_count = _integer(raw["unique_asset_count"], "music compile receipt.unique_asset_count", maximum=MAX_ASSETS)
    if unique_count != len(set(asset_ids)):
        _fail("music compile receipt.unique_asset_count does not match ids")
    time_base = _exact_dict(raw["time_base"], _BASE_KEYS, "music compile receipt.time_base")
    millidb_base = _exact_dict(raw["millidb_base"], _BASE_KEYS, "music compile receipt.millidb_base")
    if time_base != {"numerator": 1, "denominator": 1_000} or millidb_base != {"numerator": 1, "denominator": 1_000}:
        _fail("music compile receipt bases must be exact 1/1000")
    output_rate = _integer(
        raw["output_sample_rate_hz"],
        "music compile receipt.output_sample_rate_hz",
        minimum=min(SAMPLE_RATES_HZ),
        maximum=max(SAMPLE_RATES_HZ),
    )
    if output_rate not in SAMPLE_RATES_HZ:
        _fail("music compile receipt.output_sample_rate_hz is unsupported")
    output_duration = _integer(
        raw["output_duration_ms"],
        "music compile receipt.output_duration_ms",
        minimum=1,
        maximum=MAX_OUTPUT_DURATION_MS,
    )
    added_tracks = _integer(
        raw["added_track_count"],
        "music compile receipt.added_track_count",
        maximum=MAX_TRACKS,
    )
    polyphony = _integer(
        raw["max_observed_polyphony"],
        "music compile receipt.max_observed_polyphony",
        maximum=MAX_TRACKS,
    )
    coverage = _integer(
        raw["added_coverage_ms"],
        "music compile receipt.added_coverage_ms",
        maximum=MAX_OUTPUT_DURATION_MS,
    )
    if added_tracks > region_count or polyphony > region_count or coverage > output_duration:
        _fail("music compile receipt aggregate counts exceed their bound timeline/regions")
    if region_count == 0 and (added_tracks or polyphony or coverage):
        _fail("empty music compile receipt must have zero aggregate usage")
    return {
        "schema_version": MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
        **hashes,
        "ordered_region_ids": region_ids,
        "ordered_asset_ids": asset_ids,
        "region_count": region_count,
        "unique_asset_count": unique_count,
        "added_track_count": added_tracks,
        "max_observed_polyphony": polyphony,
        "added_coverage_ms": coverage,
        "dialogue_overlap_region_count": _integer(raw["dialogue_overlap_region_count"], "music compile receipt.dialogue_overlap_region_count", maximum=region_count),
        "beat_synced_region_count": _integer(raw["beat_synced_region_count"], "music compile receipt.beat_synced_region_count", maximum=region_count),
        "looped_region_count": _integer(raw["looped_region_count"], "music compile receipt.looped_region_count", maximum=region_count),
        "source_music_action": _enum(raw["source_music_action"], SOURCE_MUSIC_ACTIONS, "music compile receipt.source_music_action"),
        "output_duration_ms": output_duration,
        "output_sample_rate_hz": output_rate,
        "output_channels": _integer(raw["output_channels"], "music compile receipt.output_channels", minimum=1, maximum=8),
        "target_loudness_millilufs": _integer(raw["target_loudness_millilufs"], "music compile receipt.target_loudness_millilufs", minimum=-40_000, maximum=-5_000),
        "true_peak_ceiling_millidbtp": _integer(raw["true_peak_ceiling_millidbtp"], "music compile receipt.true_peak_ceiling_millidbtp", minimum=-9_000, maximum=-100),
        "time_base": {"numerator": 1, "denominator": 1_000},
        "millidb_base": {"numerator": 1, "denominator": 1_000},
        "policy": _normalize_policy_snapshot(raw["policy"], "music compile receipt.policy"),
    }


def music_compile_receipt_sha256(receipt: object) -> str:
    return hashlib.sha256(_canonical_json(_normalize_receipt(receipt), "music compile receipt").encode("utf-8")).hexdigest()


def compile_music_plan(plan: object, asset_manifest: object, edit_policy: object) -> dict[str, Any]:
    validated = validate_music_plan(plan, asset_manifest, edit_policy)
    manifest = validate_music_asset_manifest(asset_manifest)
    assets = {item["asset_id"]: item for item in manifest["assets"]}
    dialogue = manifest["dialogue_windows"]
    compiled = []
    intervals = []
    dialogue_overlap_count = 0
    beat_count = 0
    loop_count = 0
    for index, region in enumerate(validated["regions"]):
        asset = assets[region["asset_id"]]
        start = region["start_ms"]
        end = start + region["duration_ms"]
        intervals.append((start, end))
        source_tokens = [
            "atrim=start=" + _ffmpeg_seconds(region["trim_start_ms"]) + ":duration=" + _ffmpeg_seconds(region["loop_length_ms"] if region["playback_mode"] == "loop" else region["duration_ms"]),
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
        ]
        loop_tokens = []
        if region["playback_mode"] == "loop":
            loop_count += 1
            advances = (region["duration_ms"] - region["loop_length_ms"]) // (region["loop_length_ms"] - region["loop_crossfade_ms"])
            loop_tokens = [
                "aloop=loop=" + str(advances) + ":size=" + str(region["loop_length_ms"] * asset["sample_rate_hz"] // 1_000) + ":start=0",
                "acrossfade=d=" + _ffmpeg_seconds(region["loop_crossfade_ms"]) + ":c1=qsin:c2=qsin",
                "atrim=start=0.000:duration=" + _ffmpeg_seconds(region["duration_ms"]),
            ]
        edge_tokens = []
        if region["fade_in_ms"]:
            edge_tokens.append("afade=t=in:st=0.000:d=" + _ffmpeg_seconds(region["fade_in_ms"]) + ":curve=qsin")
        if region["fade_out_ms"]:
            edge_tokens.append("afade=t=out:st=" + _ffmpeg_seconds(region["duration_ms"] - region["fade_out_ms"]) + ":d=" + _ffmpeg_seconds(region["fade_out_ms"]) + ":curve=qsin")
        edge_tokens.append("volume=" + _ffmpeg_millidb(region["gain_millidb"]) + ":precision=fixed")
        duck_tokens = []
        if region["dialogue_ducking"] is not None:
            dialogue_overlap_count += 1
            duck = region["dialogue_ducking"]
            duck_tokens = [
                "sidechaincompress=threshold=" + _DUCK_THRESHOLD_LINEAR[duck["threshold_millidbfs"]] + ":ratio=8:attack=" + str(duck["attack_ms"]) + ":release=" + str(duck["release_ms"]) + ":makeup=1:knee=1:link=maximum:detection=rms:mix=1",
                "volume=" + _ffmpeg_millidb(-duck["attenuation_millidb"]) + ":precision=fixed",
            ]
        if region["beat_sync"] is not None:
            beat_count += 1
        timeline_tokens = ["adelay=delays=" + str(start) + ":all=1"]
        for name, tokens in (
            ("source", source_tokens), ("loop", loop_tokens), ("edge", edge_tokens),
            ("duck", duck_tokens), ("timeline", timeline_tokens),
        ):
            _validate_tokens(tokens, f"compiled region {index} {name} tokens")
        compiled.append({
            "region_index": index,
            "region_id": region["region_id"],
            "track_index": region["track_index"],
            "asset_id": asset["asset_id"],
            "asset_sha256": asset["sha256"],
            "asset_byte_length": asset["byte_length"],
            "asset_decoded_duration_ms": asset["decoded_duration_ms"],
            "asset_sample_rate_hz": asset["sample_rate_hz"],
            "asset_channels": asset["channels"],
            "source_ref": asset["source_ref"],
            "provenance": asset["provenance"],
            "license": asset["license"],
            "rights_receipt": asset["rights_receipt"],
            "output_start_ms": start,
            "output_end_ms": end,
            "playback_mode": region["playback_mode"],
            "beat_sync": region["beat_sync"],
            "dialogue_ducking": region["dialogue_ducking"],
            "dialogue_overlap_ms": sum(max(0, min(end, item["end_ms"]) - max(start, item["start_ms"])) for item in dialogue),
            "source_ffmpeg_primitive_tokens": source_tokens,
            "loop_ffmpeg_primitive_tokens": loop_tokens,
            "edge_ffmpeg_primitive_tokens": edge_tokens,
            "dialogue_sidechain_ffmpeg_primitive_tokens": duck_tokens,
            "timeline_ffmpeg_primitive_tokens": timeline_tokens,
        })

    crossfade_tokens = []
    for track in sorted({item["track_index"] for item in validated["regions"]}):
        ordered = sorted((item for item in validated["regions"] if item["track_index"] == track), key=lambda item: item["start_ms"])
        for left, right in zip(ordered, ordered[1:]):
            if left["crossfade_out_ms"]:
                crossfade_tokens.append("acrossfade=d=" + _ffmpeg_seconds(left["crossfade_out_ms"]) + ":c1=qsin:c2=qsin")
    music_bus_tokens = [] if not compiled else [
        "amix=inputs=" + str(len({item["track_index"] for item in validated["regions"]})) + ":duration=longest:dropout_transition=0:normalize=0",
        "apad=whole_dur=" + _ffmpeg_seconds(manifest["output_duration_ms"]),
        "atrim=start=0.000:duration=" + _ffmpeg_seconds(manifest["output_duration_ms"]),
        "asetpts=PTS-STARTPTS",
    ]
    mastering = validated["mastering"]
    program_tokens = [] if not compiled else [
        "aresample=48000",
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
        "apad=whole_dur=" + _ffmpeg_seconds(manifest["output_duration_ms"]),
        "atrim=start=0.000:duration=" + _ffmpeg_seconds(manifest["output_duration_ms"]),
        "asetpts=PTS-STARTPTS",
        "amix=inputs=2:duration=first:dropout_transition=0:normalize=0",
        "loudnorm=I=" + _ffmpeg_millidb(mastering["target_loudness_millilufs"], "") + ":TP=" + _ffmpeg_millidb(mastering["true_peak_ceiling_millidbtp"], "") + ":LRA=11.000:linear=true",
    ]
    output_args = [
        "-map", "AUTOEDITOR_PROGRAM_AUDIO", "-ar", str(manifest["output_sample_rate_hz"]),
        "-ac", str(manifest["output_channels"]),
    ]
    for name, tokens in (
        ("track crossfade", crossfade_tokens), ("music bus", music_bus_tokens),
        ("program mix", program_tokens), ("output arguments", output_args),
    ):
        _validate_tokens(tokens, f"compiled {name} tokens")
    mix_primitives = {
        "track_crossfade_ffmpeg_primitive_tokens": crossfade_tokens,
        "music_bus_ffmpeg_primitive_tokens": music_bus_tokens,
        "program_mix_ffmpeg_primitive_tokens": program_tokens,
        "output_ffmpeg_argument_tokens": output_args,
    }
    compiled_hash = hashlib.sha256(_canonical_json(compiled, "compiled music regions").encode("utf-8")).hexdigest()
    mix_hash = hashlib.sha256(_canonical_json(mix_primitives, "compiled music mix primitives").encode("utf-8")).hexdigest()
    receipt = _normalize_receipt({
        "schema_version": MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
        "music_plan_sha256": music_plan_sha256(validated),
        "music_asset_manifest_sha256": music_asset_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(edit_policy),
        "output_timeline_sha256": manifest["output_timeline_sha256"],
        "compiled_regions_sha256": compiled_hash,
        "mix_primitives_sha256": mix_hash,
        "ordered_region_ids": [item["region_id"] for item in compiled],
        "ordered_asset_ids": [item["asset_id"] for item in compiled],
        "region_count": len(compiled),
        "unique_asset_count": len({item["asset_id"] for item in compiled}),
        "added_track_count": len({item["track_index"] for item in compiled}),
        "max_observed_polyphony": _max_polyphony(intervals),
        "added_coverage_ms": _coverage_ms(intervals),
        "dialogue_overlap_region_count": dialogue_overlap_count,
        "beat_synced_region_count": beat_count,
        "looped_region_count": loop_count,
        "source_music_action": validated["source_music_action"],
        "output_duration_ms": manifest["output_duration_ms"],
        "output_sample_rate_hz": manifest["output_sample_rate_hz"],
        "output_channels": manifest["output_channels"],
        "target_loudness_millilufs": mastering["target_loudness_millilufs"],
        "true_peak_ceiling_millidbtp": mastering["true_peak_ceiling_millidbtp"],
        "time_base": {"numerator": 1, "denominator": 1_000},
        "millidb_base": {"numerator": 1, "denominator": 1_000},
        "policy": validated["policy"],
    })
    return {
        "schema_version": MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
        "compiled_regions": copy.deepcopy(compiled),
        **copy.deepcopy(mix_primitives),
        "receipt": copy.deepcopy(receipt),
        "receipt_sha256": music_compile_receipt_sha256(receipt),
    }


def validate_music_compile_result(result: object, plan: object, asset_manifest: object, edit_policy: object) -> dict[str, Any]:
    """Reject omission/tampering by exact comparison with deterministic compile."""
    raw = _exact_dict(result, _COMPILE_RESULT_KEYS, "music compile result")
    expected = compile_music_plan(plan, asset_manifest, edit_policy)
    if _canonical_json(raw, "music compile result") != _canonical_json(expected, "expected music compile result"):
        _fail("music compile result does not exactly match deterministic compilation")
    return copy.deepcopy(expected)


_POLICY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": sorted(_POLICY_KEYS),
    "properties": {
        "profile": {"type": "string", "pattern": _SAFE_ID_RE.pattern},
        "usage": {"type": "string", "enum": sorted(MUSIC_USAGES)},
        "duck_under_dialogue": {"type": "boolean"},
        "max_added_track_count": {"type": "integer", "minimum": 0, "maximum": MAX_TRACKS},
        "max_region_count": {"type": "integer", "minimum": 0, "maximum": MAX_MUSIC_REGIONS},
        "max_polyphony": {"type": "integer", "minimum": 0, "maximum": MAX_TRACKS},
        "max_added_coverage_ms": {"type": "integer", "minimum": 0, "maximum": MAX_OUTPUT_DURATION_MS},
        "max_gain_millidb": {"type": "integer", "minimum": -60_000, "maximum": 6_000},
        "speech_effective_gain_ceiling_millidb": {"type": "integer", "minimum": -60_000, "maximum": 0},
    },
}
_MASTERING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": sorted(_MASTERING_KEYS),
    "properties": {
        "target_loudness_millilufs": {"type": "integer", "minimum": -40_000, "maximum": -5_000},
        "true_peak_ceiling_millidbtp": {"type": "integer", "minimum": -9_000, "maximum": -100},
    },
}
_BEAT_SYNC_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": sorted(_BEAT_SYNC_KEYS),
    "properties": {
        "beat_grid_id": {"type": "string", "pattern": _BEAT_GRID_ID_RE.pattern},
        "analysis_receipt_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "asset_beat_ms": {"type": "integer", "minimum": 0, "maximum": MAX_ASSET_DURATION_MS},
        "output_beat_ms": {"type": "integer", "minimum": 0, "maximum": MAX_OUTPUT_DURATION_MS},
    },
}
_DUCKING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": sorted(_DUCKING_KEYS),
    "properties": {
        "dialogue_window_ids": {
            "type": "array", "minItems": 1, "maxItems": MAX_DIALOGUE_WINDOWS,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": _DIALOGUE_ID_RE.pattern},
        },
        "threshold_millidbfs": {"type": "integer", "enum": sorted(DUCK_THRESHOLDS_MILLIDBFS)},
        "attenuation_millidb": {"type": "integer", "enum": sorted(DUCK_ATTENUATIONS_MILLIDB)},
        "attack_ms": {"type": "integer", "minimum": 1, "maximum": 200},
        "release_ms": {"type": "integer", "minimum": 1, "maximum": 2_000},
    },
}
_REGION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": sorted(_REGION_KEYS),
    "properties": {
        "region_id": {"type": "string", "pattern": _REGION_ID_RE.pattern},
        "track_index": {"type": "integer", "minimum": 0, "maximum": MAX_TRACKS - 1},
        "asset_id": {"type": "string", "pattern": _ASSET_ID_RE.pattern},
        "asset_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_OUTPUT_DURATION_MS},
        "duration_ms": {"type": "integer", "minimum": 20, "maximum": MAX_OUTPUT_DURATION_MS},
        "trim_start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_ASSET_DURATION_MS},
        "playback_mode": {"const": "once"},
        "loop_length_ms": {"const": 0},
        "loop_crossfade_ms": {"const": 0},
        "gain_millidb": {"type": "integer", "minimum": -60_000, "maximum": 6_000},
        "fade_in_ms": {"type": "integer", "minimum": 0, "maximum": 10_000},
        "fade_out_ms": {"type": "integer", "minimum": 0, "maximum": 10_000},
        "crossfade_in_ms": {"const": 0},
        "crossfade_out_ms": {"const": 0},
        "beat_sync": {"oneOf": [{"type": "null"}, copy.deepcopy(_BEAT_SYNC_JSON_SCHEMA)]},
        "dialogue_ducking": {"const": None},
    },
}

MUSIC_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_PLAN_KEYS),
    "properties": {
        "schema_version": {"const": MUSIC_PLAN_SCHEMA_VERSION},
        "music_asset_manifest_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "edit_policy_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "output_timeline_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "output_duration_ms": {"type": "integer", "minimum": 1, "maximum": MAX_OUTPUT_DURATION_MS},
        "policy": copy.deepcopy(_POLICY_JSON_SCHEMA),
        "mastering": copy.deepcopy(_MASTERING_JSON_SCHEMA),
        "source_music_action": {"type": "string", "enum": sorted(SOURCE_MUSIC_ACTIONS)},
        "regions": {
            "type": "array", "maxItems": MAX_MUSIC_REGIONS,
            "items": copy.deepcopy(_REGION_JSON_SCHEMA),
        },
    },
}
