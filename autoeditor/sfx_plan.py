"""Closed, deterministic planning and compilation for added sound effects.

This module is an inert contract boundary.  It never resolves an asset path,
opens media, or invokes FFmpeg.  A trusted producer supplies an independently
verified cue manifest that binds every asset byte hash and media fact, its
source/provenance/license evidence, the exact output timeline, motivated
anchors, and detected speech windows.  A planner may only select from those
facts and from a validated ``autoeditor-edit-policy/v1``.

Compilation emits constant-shape FFmpeg *filter primitives*, never a command
line.  The execution layer must re-hash the selected source bytes, attach
trusted stream labels, construct ``filter_complex`` without a shell, and
verify the rendered artifact separately.  Milliseconds and milli-decibels are
integers throughout serialized contracts.  Decimal spellings occur only in
inert filter strings where FFmpeg requires seconds or dB units.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from autoeditor.edit_policy import (
    EditPolicyError,
    edit_policy_sha256,
    validate_edit_policy,
)


SFX_CUE_MANIFEST_SCHEMA_VERSION = "autoeditor-sfx-cue-manifest/v1"
SFX_PLAN_SCHEMA_VERSION = "autoeditor-sfx-plan/v1"
SFX_COMPILE_RECEIPT_SCHEMA_VERSION = "autoeditor-sfx-compile-receipt/v1"

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_ASSETS = 512
MAX_ANCHORS = 4_096
MAX_SPEECH_WINDOWS = 4_096
MAX_CUES = 2_048
MAX_ASSET_DURATION_MS = 600_000
MAX_CUE_DURATION_MS = 300_000
MAX_ASSET_BYTES = 1_099_511_627_776

SAMPLE_RATES_HZ = frozenset({
    8_000, 11_025, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000,
    88_200, 96_000, 176_400, 192_000,
})
DELIVERY_SAMPLE_RATE_HZ = 48_000
DELIVERY_CHANNELS = 2
PROVENANCE_KINDS = frozenset({
    "project_generated", "user_supplied", "licensed_external",
})
LICENSE_BASES = frozenset({
    "project_owned", "user_authorized", "licensed_external",
})
ANCHOR_CATEGORIES = frozenset({"boundary", "event", "interface_feedback"})
CUE_KINDS = frozenset({
    "ambience",
    "foley",
    "gameplay_event",
    "impact",
    "interface_feedback",
    "riser",
    "sports_event",
    "transition_accent",
    "whoosh",
})
POLICY_DENSITIES = frozenset({"none", "sparse", "medium", "dense"})
POLICY_USAGES = frozenset({
    "forbidden",
    "motivated_only",
    "interface_feedback_only",
    "event_accent_only",
    "source_only",
})
DUCK_ATTENUATIONS_MILLIDB = frozenset({6_000, 9_000, 12_000, 18_000, 24_000})

_MANIFEST_KEYS = frozenset({
    "schema_version",
    "output_timeline_sha256",
    "output_duration_ms",
    "output_sample_rate_hz",
    "output_channels",
    "assets",
    "anchors",
    "speech_windows",
})
_ASSET_KEYS = frozenset({
    "asset_id",
    "sha256",
    "byte_length",
    "duration_ms",
    "sample_rate_hz",
    "channels",
    "source_ref",
    "provenance",
    "license",
})
_ASSET_PAYLOAD_KEYS = _ASSET_KEYS - {"asset_id"}
_LICENSE_KEYS = frozenset({
    "basis", "license_id", "licensor", "evidence_sha256",
})
_ANCHOR_KEYS = frozenset({
    "anchor_id",
    "category",
    "reference_id",
    "time_ms",
    "evidence_start_ms",
    "evidence_end_ms",
    "evidence_sha256",
})
_ANCHOR_PAYLOAD_KEYS = _ANCHOR_KEYS - {"anchor_id"}
_SPEECH_KEYS = frozenset({
    "speech_id", "start_ms", "end_ms", "evidence_sha256",
})
_SPEECH_PAYLOAD_KEYS = _SPEECH_KEYS - {"speech_id"}

_PLAN_KEYS = frozenset({
    "schema_version",
    "cue_manifest_sha256",
    "edit_policy_sha256",
    "output_timeline_sha256",
    "output_duration_ms",
    "policy",
    "cues",
})
_POLICY_KEYS = frozenset({
    "profile",
    "density",
    "usage",
    "max_cue_count",
    "max_polyphony",
    "max_gain_millidb",
    "speech_effective_gain_ceiling_millidb",
})
_CUE_KEYS = frozenset({
    "cue_id",
    "asset_id",
    "asset_sha256",
    "kind",
    "motivation",
    "placement",
    "ducking",
})
_CUE_PAYLOAD_KEYS = _CUE_KEYS - {"cue_id"}
_MOTIVATION_KEYS = frozenset({
    "category",
    "anchor_id",
    "reference_id",
    "anchor_ms",
    "evidence_start_ms",
    "evidence_end_ms",
    "evidence_sha256",
})
_PLACEMENT_KEYS = frozenset({
    "start_ms",
    "trim_start_ms",
    "trim_duration_ms",
    "gain_millidb",
    "attack_fade_ms",
    "release_fade_ms",
})
_DUCKING_KEYS = frozenset({
    "start_ms",
    "end_ms",
    "attenuation_millidb",
    "attack_ms",
    "release_ms",
})

_RECEIPT_KEYS = frozenset({
    "schema_version",
    "sfx_plan_sha256",
    "cue_manifest_sha256",
    "edit_policy_sha256",
    "output_timeline_sha256",
    "compiled_cues_sha256",
    "mix_primitives_sha256",
    "ordered_cue_ids",
    "ordered_asset_ids",
    "cue_count",
    "unique_asset_count",
    "output_duration_ms",
    "output_sample_rate_hz",
    "output_channels",
    "max_observed_polyphony",
    "speech_overlap_cue_count",
    "time_base",
    "millidb_base",
    "policy",
})
_BASE_KEYS = frozenset({"numerator", "denominator"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ASSET_ID_RE = re.compile(r"^sfxasset-[0-9a-f]{64}$", re.ASCII)
_ANCHOR_ID_RE = re.compile(r"^sfxanchor-[0-9a-f]{64}$", re.ASCII)
_SPEECH_ID_RE = re.compile(r"^speech-[0-9a-f]{64}$", re.ASCII)
_CUE_ID_RE = re.compile(r"^sfxcue-[0-9a-f]{64}$", re.ASCII)
_BOUNDARY_REF_RE = re.compile(r"^boundary-[0-9a-f]{64}$", re.ASCII)
_EVENT_REF_RE = re.compile(r"^event-[A-Za-z0-9][A-Za-z0-9._-]{0,94}$", re.ASCII)
_INTERFACE_REF_RE = re.compile(
    r"^interface-[A-Za-z0-9][A-Za-z0-9._-]{0,90}$", re.ASCII
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$", re.ASCII)
_LICENSOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._&()-]{0,127}$", re.ASCII)
_SOURCE_REF_RE = re.compile(
    r"^(project-generated|user-supplied|licensed-external)://"
    r"[A-Za-z0-9][A-Za-z0-9._/-]{0,383}$",
    re.ASCII,
)

_PROVENANCE_LICENSE = {
    "project_generated": ("project-generated", "project_owned"),
    "user_supplied": ("user-supplied", "user_authorized"),
    "licensed_external": ("licensed-external", "licensed_external"),
}

# The first value is a profile ceiling.  Density may lower it further.
_PROFILE_MAX_POLYPHONY = {
    "commercial_product": 3,
    "course_tutorial_screencast": 2,
    "dialogue_talking_head": 2,
    "documentary_narrative": 0,
    "gaming": 4,
    "montage_meme": 4,
    "music_performance": 0,
    "podcast_interview": 0,
    "real_estate": 2,
    "sports_highlights": 4,
    "utility_faithful": 0,
    "vlog_travel": 3,
    "wedding_event": 2,
}
_PROFILE_MAX_GAIN_MILLIDB = {
    "commercial_product": 3_000,
    "course_tutorial_screencast": 0,
    "dialogue_talking_head": 0,
    "documentary_narrative": -60_000,
    "gaming": 3_000,
    "montage_meme": 3_000,
    "music_performance": -60_000,
    "podcast_interview": -60_000,
    "real_estate": 0,
    "sports_highlights": 3_000,
    "utility_faithful": -60_000,
    "vlog_travel": 0,
    "wedding_event": -3_000,
}
_DENSITY_MAX_POLYPHONY = {"none": 0, "sparse": 1, "medium": 2, "dense": 4}
_DENSITY_LOCAL_TEN_SECOND_LIMIT = {
    "none": 0, "sparse": 2, "medium": 5, "dense": 10,
}
_DENSITY_PER_ANCHOR_LIMIT = {"none": 0, "sparse": 1, "medium": 2, "dense": 3}
_SPEECH_GAIN_CEILING = {
    "none": -9_000,
    "supporting": -12_000,
    "primary": -15_000,
    "verbatim": -18_000,
}
_KIND_MAX_DURATION_MS = {
    "ambience": MAX_CUE_DURATION_MS,
    "foley": 30_000,
    "gameplay_event": 10_000,
    "impact": 5_000,
    "interface_feedback": 5_000,
    "riser": 10_000,
    "sports_event": 10_000,
    "transition_accent": 10_000,
    "whoosh": 10_000,
}
_KIND_OFFSET_RANGE_MS = {
    "ambience": (0, 250),
    "foley": (-250, 250),
    "gameplay_event": (-250, 250),
    "impact": (-250, 250),
    "interface_feedback": (-250, 250),
    "riser": (-2_000, 0),
    "sports_event": (-250, 250),
    "transition_accent": (-1_000, 250),
    "whoosh": (-1_000, 250),
}
_ANCHOR_ALLOWED_KINDS = {
    "boundary": frozenset({"impact", "riser", "transition_accent", "whoosh"}),
    "event": frozenset({
        "ambience", "foley", "gameplay_event", "impact", "riser",
        "sports_event", "whoosh",
    }),
    "interface_feedback": frozenset({"interface_feedback"}),
}

# Ratio 2:1 with a full-scale deterministic gate.  These thresholds produce
# the requested steady-state reduction (within FFmpeg's decimal parsing) while
# attack/release remain explicit.  The gate, not arbitrary user audio, drives
# the sidechain, so the result does not depend on sidechain programme level.
DUCK_SIDECHAIN_THRESHOLD_TEXT = {
    6_000: "0.2511886432",
    9_000: "0.1258925412",
    12_000: "0.06309573445",
    18_000: "0.01584893192",
    24_000: "0.003981071706",
}


class SfxPlanError(ValueError):
    """The trusted manifest, policy, SFX plan, or receipt is malformed."""


def _fail(message: str) -> None:
    raise SfxPlanError(message)


def _exact_dict(value: object, expected: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    keys = frozenset(value)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
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


def _safe_text(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(f"{label} must be bounded safe ASCII text")
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
        raise SfxPlanError(f"{label} is not canonical JSON") from error


def _ffmpeg_seconds(milliseconds: int) -> str:
    return f"{milliseconds // 1_000}.{milliseconds % 1_000:03d}"


def _ffmpeg_millidb(millidb: int) -> str:
    sign = "-" if millidb < 0 else ""
    absolute = abs(millidb)
    return f"{sign}{absolute // 1_000}.{absolute % 1_000:03d}dB"


def _ffmpeg_channel_layout(channels: int) -> str:
    return {
        1: "mono",
        2: "stereo",
        3: "2.1",
        4: "quad",
        5: "5.0",
        6: "5.1",
        7: "6.1",
        8: "7.1",
    }[channels]


def _normalize_license(value: object, provenance: str, label: str) -> dict[str, str]:
    raw = _exact_dict(value, _LICENSE_KEYS, label)
    basis = _enum(raw["basis"], LICENSE_BASES, f"{label}.basis")
    license_id = _safe_text(raw["license_id"], _SAFE_ID_RE, f"{label}.license_id")
    licensor = _safe_text(raw["licensor"], _LICENSOR_RE, f"{label}.licensor")
    if license_id != license_id.strip() or licensor != licensor.strip():
        _fail(f"{label} contains noncanonical surrounding whitespace")
    evidence = _sha256(raw["evidence_sha256"], f"{label}.evidence_sha256")
    expected_basis = _PROVENANCE_LICENSE[provenance][1]
    if basis != expected_basis:
        _fail(f"{label}.basis does not match asset provenance")
    license_id_lower = license_id.casefold()
    licensor_lower = licensor.casefold()
    lowered = {license_id_lower, licensor_lower}
    if lowered & {"unknown", "none", "unlicensed", "tbd", "n/a"}:
        _fail(f"{label} contains a placeholder instead of rights evidence")
    if provenance == "project_generated":
        if license_id != "project-generated" or licensor != "project":
            _fail(f"{label} must identify project-generated ownership exactly")
    elif provenance == "licensed_external":
        if (license_id_lower == "project-generated"
                or licensor_lower in {"project", "user"}):
            _fail(f"{label} is not valid external license attribution")
    elif (license_id_lower == "project-generated" or licensor != "user"):
        _fail(
            f"{label} must identify exact user authorization without "
            "claiming project ownership"
        )
    return {
        "basis": basis,
        "license_id": license_id,
        "licensor": licensor,
        "evidence_sha256": evidence,
    }


def _normalize_asset_payload(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _ASSET_PAYLOAD_KEYS, label)
    provenance = _enum(raw["provenance"], PROVENANCE_KINDS, f"{label}.provenance")
    source_ref = _safe_text(raw["source_ref"], _SOURCE_REF_RE, f"{label}.source_ref")
    source_scheme = source_ref.split("://", 1)[0]
    expected_scheme = _PROVENANCE_LICENSE[provenance][0]
    if source_scheme != expected_scheme:
        _fail(f"{label}.source_ref scheme does not match provenance")
    if any(part in {"", ".", ".."} for part in source_ref.split("://", 1)[1].split("/")):
        _fail(f"{label}.source_ref contains an unsafe path segment")
    sample_rate = _integer(
        raw["sample_rate_hz"], f"{label}.sample_rate_hz",
        minimum=min(SAMPLE_RATES_HZ), maximum=max(SAMPLE_RATES_HZ),
    )
    if sample_rate not in SAMPLE_RATES_HZ:
        _fail(f"{label}.sample_rate_hz is unsupported")
    return {
        "sha256": _sha256(raw["sha256"], f"{label}.sha256"),
        "byte_length": _integer(
            raw["byte_length"], f"{label}.byte_length",
            minimum=1, maximum=MAX_ASSET_BYTES,
        ),
        "duration_ms": _integer(
            raw["duration_ms"], f"{label}.duration_ms",
            minimum=1, maximum=MAX_ASSET_DURATION_MS,
        ),
        "sample_rate_hz": sample_rate,
        "channels": _integer(raw["channels"], f"{label}.channels", minimum=1, maximum=8),
        "source_ref": source_ref,
        "provenance": provenance,
        "license": _normalize_license(raw["license"], provenance, f"{label}.license"),
    }


def derive_sfx_asset_id(asset_without_id: object) -> str:
    """Derive an id from every trusted byte/media/source/rights fact."""
    normalized = _normalize_asset_payload(asset_without_id, "SFX asset binding")
    digest = hashlib.sha256(
        _canonical_json(normalized, "SFX asset binding").encode("utf-8")
    ).hexdigest()
    return "sfxasset-" + digest


def _normalize_anchor_payload(value: object, label: str, output_duration_ms: int) -> dict[str, Any]:
    raw = _exact_dict(value, _ANCHOR_PAYLOAD_KEYS, label)
    category = _enum(raw["category"], ANCHOR_CATEGORIES, f"{label}.category")
    reference_pattern = {
        "boundary": _BOUNDARY_REF_RE,
        "event": _EVENT_REF_RE,
        "interface_feedback": _INTERFACE_REF_RE,
    }[category]
    reference_id = _identifier(raw["reference_id"], reference_pattern, f"{label}.reference_id")
    time_ms = _integer(raw["time_ms"], f"{label}.time_ms", maximum=output_duration_ms)
    evidence_start = _integer(
        raw["evidence_start_ms"], f"{label}.evidence_start_ms",
        maximum=output_duration_ms,
    )
    evidence_end = _integer(
        raw["evidence_end_ms"], f"{label}.evidence_end_ms",
        maximum=output_duration_ms,
    )
    if evidence_start > time_ms or time_ms > evidence_end:
        _fail(f"{label} evidence interval must contain its exact anchor")
    return {
        "category": category,
        "reference_id": reference_id,
        "time_ms": time_ms,
        "evidence_start_ms": evidence_start,
        "evidence_end_ms": evidence_end,
        "evidence_sha256": _sha256(raw["evidence_sha256"], f"{label}.evidence_sha256"),
    }


def derive_sfx_anchor_id(anchor_without_id: object, output_duration_ms: int) -> str:
    duration = _integer(output_duration_ms, "output_duration_ms", minimum=1)
    normalized = _normalize_anchor_payload(
        anchor_without_id, "SFX anchor binding", duration
    )
    digest = hashlib.sha256(
        _canonical_json(normalized, "SFX anchor binding").encode("utf-8")
    ).hexdigest()
    return "sfxanchor-" + digest


def _normalize_speech_payload(value: object, label: str, output_duration_ms: int) -> dict[str, Any]:
    raw = _exact_dict(value, _SPEECH_PAYLOAD_KEYS, label)
    start = _integer(raw["start_ms"], f"{label}.start_ms", maximum=output_duration_ms)
    end = _integer(raw["end_ms"], f"{label}.end_ms", maximum=output_duration_ms)
    if end <= start:
        _fail(f"{label} must have positive duration")
    return {
        "start_ms": start,
        "end_ms": end,
        "evidence_sha256": _sha256(raw["evidence_sha256"], f"{label}.evidence_sha256"),
    }


def derive_speech_window_id(speech_without_id: object, output_duration_ms: int) -> str:
    duration = _integer(output_duration_ms, "output_duration_ms", minimum=1)
    normalized = _normalize_speech_payload(
        speech_without_id, "speech-window binding", duration
    )
    digest = hashlib.sha256(
        _canonical_json(normalized, "speech-window binding").encode("utf-8")
    ).hexdigest()
    return "speech-" + digest


def validate_sfx_cue_manifest(manifest: object) -> dict[str, Any]:
    """Validate and detach a trusted asset/anchor/speech manifest."""
    raw = _exact_dict(manifest, _MANIFEST_KEYS, "SFX cue manifest")
    if raw["schema_version"] != SFX_CUE_MANIFEST_SCHEMA_VERSION:
        _fail("SFX cue manifest schema_version is unsupported")
    timeline_hash = _sha256(raw["output_timeline_sha256"], "SFX cue manifest.output_timeline_sha256")
    output_duration = _integer(
        raw["output_duration_ms"], "SFX cue manifest.output_duration_ms", minimum=1
    )
    output_rate = _integer(
        raw["output_sample_rate_hz"], "SFX cue manifest.output_sample_rate_hz",
        minimum=min(SAMPLE_RATES_HZ), maximum=max(SAMPLE_RATES_HZ),
    )
    if output_rate not in SAMPLE_RATES_HZ:
        _fail("SFX cue manifest.output_sample_rate_hz is unsupported")
    output_channels = _integer(
        raw["output_channels"], "SFX cue manifest.output_channels", minimum=1, maximum=8
    )
    if output_rate != DELIVERY_SAMPLE_RATE_HZ or output_channels != DELIVERY_CHANNELS:
        _fail("SFX cue manifest output must be the exact 48000 Hz stereo delivery format")

    if type(raw["assets"]) is not list or len(raw["assets"]) > MAX_ASSETS:
        _fail("SFX cue manifest.assets has invalid cardinality")
    assets = []
    asset_ids: set[str] = set()
    source_refs: set[str] = set()
    asset_hashes: set[str] = set()
    for index, raw_asset in enumerate(raw["assets"]):
        label = f"SFX cue manifest.assets[{index}]"
        item = _exact_dict(raw_asset, _ASSET_KEYS, label)
        payload = _normalize_asset_payload(
            {key: item[key] for key in _ASSET_PAYLOAD_KEYS}, label
        )
        asset_id = _identifier(item["asset_id"], _ASSET_ID_RE, f"{label}.asset_id")
        if asset_id != derive_sfx_asset_id(payload):
            _fail(f"{label}.asset_id does not bind exact asset and rights facts")
        if asset_id in asset_ids or payload["source_ref"] in source_refs or payload["sha256"] in asset_hashes:
            _fail("SFX cue manifest assets must have unique ids, sources, and byte hashes")
        asset_ids.add(asset_id)
        source_refs.add(payload["source_ref"])
        asset_hashes.add(payload["sha256"])
        assets.append({"asset_id": asset_id, **payload})
    if [item["asset_id"] for item in assets] != sorted(asset_ids):
        _fail("SFX cue manifest.assets must be ordered by asset_id")

    if type(raw["anchors"]) is not list or len(raw["anchors"]) > MAX_ANCHORS:
        _fail("SFX cue manifest.anchors has invalid cardinality")
    anchors = []
    anchor_ids: set[str] = set()
    reference_ids: set[str] = set()
    for index, raw_anchor in enumerate(raw["anchors"]):
        label = f"SFX cue manifest.anchors[{index}]"
        item = _exact_dict(raw_anchor, _ANCHOR_KEYS, label)
        payload = _normalize_anchor_payload(
            {key: item[key] for key in _ANCHOR_PAYLOAD_KEYS}, label, output_duration
        )
        anchor_id = _identifier(item["anchor_id"], _ANCHOR_ID_RE, f"{label}.anchor_id")
        if anchor_id != derive_sfx_anchor_id(payload, output_duration):
            _fail(f"{label}.anchor_id does not bind exact motivation evidence")
        if anchor_id in anchor_ids or payload["reference_id"] in reference_ids:
            _fail("SFX cue manifest anchors must have unique ids and references")
        anchor_ids.add(anchor_id)
        reference_ids.add(payload["reference_id"])
        anchors.append({"anchor_id": anchor_id, **payload})
    if [(item["time_ms"], item["anchor_id"]) for item in anchors] != sorted(
        (item["time_ms"], item["anchor_id"]) for item in anchors
    ):
        _fail("SFX cue manifest.anchors must be ordered by time_ms then anchor_id")

    if type(raw["speech_windows"]) is not list or len(raw["speech_windows"]) > MAX_SPEECH_WINDOWS:
        _fail("SFX cue manifest.speech_windows has invalid cardinality")
    speech_windows = []
    speech_ids: set[str] = set()
    previous_end = 0
    for index, raw_speech in enumerate(raw["speech_windows"]):
        label = f"SFX cue manifest.speech_windows[{index}]"
        item = _exact_dict(raw_speech, _SPEECH_KEYS, label)
        payload = _normalize_speech_payload(
            {key: item[key] for key in _SPEECH_PAYLOAD_KEYS}, label, output_duration
        )
        speech_id = _identifier(item["speech_id"], _SPEECH_ID_RE, f"{label}.speech_id")
        if speech_id != derive_speech_window_id(payload, output_duration):
            _fail(f"{label}.speech_id does not bind exact speech evidence")
        if speech_id in speech_ids:
            _fail("SFX cue manifest speech ids must be unique")
        if payload["start_ms"] < previous_end:
            _fail("SFX cue manifest speech windows must be ordered and non-overlapping")
        speech_ids.add(speech_id)
        previous_end = payload["end_ms"]
        speech_windows.append({"speech_id": speech_id, **payload})

    return copy.deepcopy({
        "schema_version": SFX_CUE_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": timeline_hash,
        "output_duration_ms": output_duration,
        "output_sample_rate_hz": output_rate,
        "output_channels": output_channels,
        "assets": assets,
        "anchors": anchors,
        "speech_windows": speech_windows,
    })


def canonical_sfx_cue_manifest_json(manifest: object) -> str:
    return _canonical_json(validate_sfx_cue_manifest(manifest), "SFX cue manifest")


def sfx_cue_manifest_sha256(manifest: object) -> str:
    return hashlib.sha256(canonical_sfx_cue_manifest_json(manifest).encode("utf-8")).hexdigest()


def density_cue_limit(density: object, output_duration_ms: object) -> int:
    """Return a conservative global count ceiling; it is never a quota."""
    member = _enum(density, POLICY_DENSITIES, "SFX density")
    duration = _integer(output_duration_ms, "output_duration_ms", minimum=1)
    if member == "none":
        return 0
    interval = {"sparse": 15_000, "medium": 6_000, "dense": 3_000}[member]
    return min(MAX_CUES, (duration + interval - 1) // interval)


def _policy_limits(policy: dict[str, Any], output_duration_ms: int) -> dict[str, Any]:
    profile = policy["profile"]
    if profile not in _PROFILE_MAX_POLYPHONY:
        _fail("edit policy profile has no closed SFX limits")
    rule = policy["rules"]["sfx"]
    density = rule["density"]
    usage = rule["usage"]
    max_count = density_cue_limit(density, output_duration_ms)
    if usage in {"forbidden", "source_only"}:
        max_count = 0
    max_polyphony = min(
        _PROFILE_MAX_POLYPHONY[profile], _DENSITY_MAX_POLYPHONY[density]
    )
    if max_count == 0:
        max_polyphony = 0
    dialogue_priority = policy["rules"]["dialogue"]["priority"]
    return {
        "profile": profile,
        "density": density,
        "usage": usage,
        "max_cue_count": max_count,
        "max_polyphony": max_polyphony,
        "max_gain_millidb": _PROFILE_MAX_GAIN_MILLIDB[profile],
        "speech_effective_gain_ceiling_millidb": _SPEECH_GAIN_CEILING[dialogue_priority],
    }


def derive_sfx_policy_limits(
    edit_policy: object, output_duration_ms: object
) -> dict[str, Any]:
    """Return the exact SFX snapshot a plan must bind for this policy/timeline."""
    duration = _integer(output_duration_ms, "output_duration_ms", minimum=1)
    try:
        policy = validate_edit_policy(edit_policy)
    except EditPolicyError as error:
        raise SfxPlanError("edit policy is invalid") from error
    if policy["duration"]["duration_ms"] != duration:
        _fail("edit policy duration does not match the exact SFX output duration")
    return copy.deepcopy(_policy_limits(policy, duration))


def _normalize_policy_snapshot(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _POLICY_KEYS, label)
    profile = _safe_text(raw["profile"], _SAFE_ID_RE, f"{label}.profile")
    return {
        "profile": profile,
        "density": _enum(raw["density"], POLICY_DENSITIES, f"{label}.density"),
        "usage": _enum(raw["usage"], POLICY_USAGES, f"{label}.usage"),
        "max_cue_count": _integer(raw["max_cue_count"], f"{label}.max_cue_count", maximum=MAX_CUES),
        "max_polyphony": _integer(raw["max_polyphony"], f"{label}.max_polyphony", maximum=8),
        "max_gain_millidb": _integer(
            raw["max_gain_millidb"], f"{label}.max_gain_millidb",
            minimum=-60_000, maximum=6_000,
        ),
        "speech_effective_gain_ceiling_millidb": _integer(
            raw["speech_effective_gain_ceiling_millidb"],
            f"{label}.speech_effective_gain_ceiling_millidb",
            minimum=-60_000, maximum=0,
        ),
    }


def _normalize_motivation(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _MOTIVATION_KEYS, label)
    category = _enum(raw["category"], ANCHOR_CATEGORIES, f"{label}.category")
    reference_pattern = {
        "boundary": _BOUNDARY_REF_RE,
        "event": _EVENT_REF_RE,
        "interface_feedback": _INTERFACE_REF_RE,
    }[category]
    return {
        "category": category,
        "anchor_id": _identifier(raw["anchor_id"], _ANCHOR_ID_RE, f"{label}.anchor_id"),
        "reference_id": _identifier(raw["reference_id"], reference_pattern, f"{label}.reference_id"),
        "anchor_ms": _integer(raw["anchor_ms"], f"{label}.anchor_ms"),
        "evidence_start_ms": _integer(raw["evidence_start_ms"], f"{label}.evidence_start_ms"),
        "evidence_end_ms": _integer(raw["evidence_end_ms"], f"{label}.evidence_end_ms"),
        "evidence_sha256": _sha256(raw["evidence_sha256"], f"{label}.evidence_sha256"),
    }


def _normalize_placement(value: object, label: str) -> dict[str, int]:
    raw = _exact_dict(value, _PLACEMENT_KEYS, label)
    return {
        "start_ms": _integer(raw["start_ms"], f"{label}.start_ms"),
        "trim_start_ms": _integer(raw["trim_start_ms"], f"{label}.trim_start_ms"),
        "trim_duration_ms": _integer(
            raw["trim_duration_ms"], f"{label}.trim_duration_ms",
            minimum=20, maximum=MAX_CUE_DURATION_MS,
        ),
        "gain_millidb": _integer(
            raw["gain_millidb"], f"{label}.gain_millidb",
            minimum=-60_000, maximum=6_000,
        ),
        "attack_fade_ms": _integer(
            raw["attack_fade_ms"], f"{label}.attack_fade_ms", maximum=5_000
        ),
        "release_fade_ms": _integer(
            raw["release_fade_ms"], f"{label}.release_fade_ms", maximum=5_000
        ),
    }


def _normalize_ducking(value: object, label: str) -> dict[str, int] | None:
    if value is None:
        return None
    raw = _exact_dict(value, _DUCKING_KEYS, label)
    attenuation = _integer(
        raw["attenuation_millidb"], f"{label}.attenuation_millidb",
        minimum=min(DUCK_ATTENUATIONS_MILLIDB), maximum=max(DUCK_ATTENUATIONS_MILLIDB),
    )
    if attenuation not in DUCK_ATTENUATIONS_MILLIDB:
        _fail(f"{label}.attenuation_millidb is not a deterministic v1 preset")
    return {
        "start_ms": _integer(raw["start_ms"], f"{label}.start_ms"),
        "end_ms": _integer(raw["end_ms"], f"{label}.end_ms"),
        "attenuation_millidb": attenuation,
        "attack_ms": _integer(raw["attack_ms"], f"{label}.attack_ms", minimum=1, maximum=200),
        "release_ms": _integer(raw["release_ms"], f"{label}.release_ms", minimum=1, maximum=2_000),
    }


def _normalize_cue_payload(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _CUE_PAYLOAD_KEYS, label)
    return {
        "asset_id": _identifier(raw["asset_id"], _ASSET_ID_RE, f"{label}.asset_id"),
        "asset_sha256": _sha256(raw["asset_sha256"], f"{label}.asset_sha256"),
        "kind": _enum(raw["kind"], CUE_KINDS, f"{label}.kind"),
        "motivation": _normalize_motivation(raw["motivation"], f"{label}.motivation"),
        "placement": _normalize_placement(raw["placement"], f"{label}.placement"),
        "ducking": _normalize_ducking(raw["ducking"], f"{label}.ducking"),
    }


def derive_sfx_cue_id(cue_without_id: object) -> str:
    normalized = _normalize_cue_payload(cue_without_id, "SFX cue binding")
    digest = hashlib.sha256(
        _canonical_json(normalized, "SFX cue binding").encode("utf-8")
    ).hexdigest()
    return "sfxcue-" + digest


def _normalize_plan(plan: object) -> dict[str, Any]:
    raw = _exact_dict(plan, _PLAN_KEYS, "SFX plan")
    if raw["schema_version"] != SFX_PLAN_SCHEMA_VERSION:
        _fail("SFX plan schema_version is unsupported")
    cues_raw = raw["cues"]
    if type(cues_raw) is not list or len(cues_raw) > MAX_CUES:
        _fail("SFX plan.cues has invalid cardinality")
    cues = []
    cue_ids: set[str] = set()
    for index, raw_cue in enumerate(cues_raw):
        label = f"SFX plan.cues[{index}]"
        item = _exact_dict(raw_cue, _CUE_KEYS, label)
        payload = _normalize_cue_payload(
            {key: item[key] for key in _CUE_PAYLOAD_KEYS}, label
        )
        cue_id = _identifier(item["cue_id"], _CUE_ID_RE, f"{label}.cue_id")
        if cue_id != derive_sfx_cue_id(payload):
            _fail(f"{label}.cue_id does not bind the exact cue decision")
        if cue_id in cue_ids:
            _fail("SFX plan cue ids must be unique")
        cue_ids.add(cue_id)
        cues.append({"cue_id": cue_id, **payload})
    expected_order = sorted(cues, key=lambda cue: (cue["placement"]["start_ms"], cue["cue_id"]))
    if cues != expected_order:
        _fail("SFX plan.cues must be ordered by start_ms then cue_id")
    return {
        "schema_version": SFX_PLAN_SCHEMA_VERSION,
        "cue_manifest_sha256": _sha256(raw["cue_manifest_sha256"], "SFX plan.cue_manifest_sha256"),
        "edit_policy_sha256": _sha256(raw["edit_policy_sha256"], "SFX plan.edit_policy_sha256"),
        "output_timeline_sha256": _sha256(raw["output_timeline_sha256"], "SFX plan.output_timeline_sha256"),
        "output_duration_ms": _integer(raw["output_duration_ms"], "SFX plan.output_duration_ms", minimum=1),
        "policy": _normalize_policy_snapshot(raw["policy"], "SFX plan.policy"),
        "cues": cues,
    }


def canonical_sfx_plan_json(plan: object) -> str:
    return _canonical_json(_normalize_plan(plan), "SFX plan")


def sfx_plan_sha256(plan: object) -> str:
    return hashlib.sha256(canonical_sfx_plan_json(plan).encode("utf-8")).hexdigest()


def _max_polyphony(intervals: list[tuple[int, int]]) -> int:
    events: list[tuple[int, int]] = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    active = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def _speech_intersections(
    start_ms: int,
    end_ms: int,
    speech_windows: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    intersections = []
    for speech in speech_windows:
        start = max(start_ms, speech["start_ms"])
        end = min(end_ms, speech["end_ms"])
        if end > start:
            intersections.append((start, end))
    return intersections


def validate_sfx_plan(
    plan: object,
    cue_manifest: object,
    edit_policy: object,
) -> dict[str, Any]:
    """Validate exact manifest/policy binding and all timeline safeguards."""
    normalized = _normalize_plan(plan)
    manifest = validate_sfx_cue_manifest(cue_manifest)
    try:
        policy = validate_edit_policy(edit_policy)
        expected_policy_hash = edit_policy_sha256(policy)
    except EditPolicyError as error:
        raise SfxPlanError("edit policy is invalid") from error
    expected_manifest_hash = sfx_cue_manifest_sha256(manifest)
    if normalized["cue_manifest_sha256"] != expected_manifest_hash:
        _fail("SFX plan does not bind the trusted cue manifest")
    if normalized["edit_policy_sha256"] != expected_policy_hash:
        _fail("SFX plan does not bind the resolved edit policy")
    if normalized["output_timeline_sha256"] != manifest["output_timeline_sha256"]:
        _fail("SFX plan does not bind the trusted output timeline")
    if normalized["output_duration_ms"] != manifest["output_duration_ms"]:
        _fail("SFX plan does not bind the exact output duration")
    if policy["duration"]["duration_ms"] != manifest["output_duration_ms"]:
        _fail("edit policy duration does not match the exact SFX output duration")
    expected_limits = _policy_limits(policy, manifest["output_duration_ms"])
    if normalized["policy"] != expected_limits:
        _fail("SFX plan policy snapshot does not match the resolved edit policy")
    if len(normalized["cues"]) > expected_limits["max_cue_count"]:
        _fail("SFX plan exceeds its policy-derived cue density ceiling")
    if expected_limits["usage"] in {"forbidden", "source_only"} and normalized["cues"]:
        _fail("SFX policy permits no added cue assets")

    assets = {asset["asset_id"]: asset for asset in manifest["assets"]}
    anchors = {anchor["anchor_id"]: anchor for anchor in manifest["anchors"]}
    intervals: list[tuple[int, int]] = []
    speech_intervals: list[tuple[int, int]] = []
    anchor_counts: dict[str, int] = {}
    used_asset_anchor: set[tuple[str, str]] = set()
    anchor_times: list[int] = []
    dialogue_priority = policy["rules"]["dialogue"]["priority"]

    for index, cue in enumerate(normalized["cues"]):
        label = f"SFX plan.cues[{index}]"
        asset = assets.get(cue["asset_id"])
        if asset is None:
            _fail(f"{label}.asset_id is absent from the trusted cue manifest")
        if cue["asset_sha256"] != asset["sha256"]:
            _fail(f"{label}.asset_sha256 does not match trusted asset bytes")
        motivation = cue["motivation"]
        anchor = anchors.get(motivation["anchor_id"])
        if anchor is None:
            _fail(f"{label}.motivation.anchor_id is absent from the trusted manifest")
        exact_motivation = {
            "category": anchor["category"],
            "anchor_id": anchor["anchor_id"],
            "reference_id": anchor["reference_id"],
            "anchor_ms": anchor["time_ms"],
            "evidence_start_ms": anchor["evidence_start_ms"],
            "evidence_end_ms": anchor["evidence_end_ms"],
            "evidence_sha256": anchor["evidence_sha256"],
        }
        if motivation != exact_motivation:
            _fail(f"{label}.motivation does not copy exact trusted anchor evidence")
        if cue["kind"] not in _ANCHOR_ALLOWED_KINDS[anchor["category"]]:
            _fail(f"{label}.kind is not motivated by its anchor category")
        usage = expected_limits["usage"]
        if usage == "interface_feedback_only" and (
            anchor["category"] != "interface_feedback" or cue["kind"] != "interface_feedback"
        ):
            _fail(f"{label} violates interface-feedback-only policy")
        if usage == "event_accent_only" and anchor["category"] != "event":
            _fail(f"{label} violates event-accent-only policy")
        profile = expected_limits["profile"]
        if cue["kind"] == "gameplay_event" and profile != "gaming":
            _fail(f"{label}.kind is reserved for the gaming profile")
        if cue["kind"] == "sports_event" and profile != "sports_highlights":
            _fail(f"{label}.kind is reserved for the sports profile")

        placement = cue["placement"]
        start = placement["start_ms"]
        duration = placement["trim_duration_ms"]
        end = start + duration
        if end > manifest["output_duration_ms"]:
            _fail(f"{label} extends beyond the exact output duration")
        if placement["trim_start_ms"] + duration > asset["duration_ms"]:
            _fail(f"{label} trim exceeds the trusted asset duration")
        if duration > _KIND_MAX_DURATION_MS[cue["kind"]]:
            _fail(f"{label} duration exceeds its cue-kind ceiling")
        if placement["attack_fade_ms"] + placement["release_fade_ms"] > duration:
            _fail(f"{label} attack and release fades overlap")
        if placement["gain_millidb"] > expected_limits["max_gain_millidb"]:
            _fail(f"{label}.placement.gain_millidb exceeds its profile ceiling")
        offset = start - anchor["time_ms"]
        minimum_offset, maximum_offset = _KIND_OFFSET_RANGE_MS[cue["kind"]]
        if not minimum_offset <= offset <= maximum_offset:
            _fail(f"{label} is too far from its trusted motivation anchor")
        if not start <= anchor["time_ms"] <= end:
            _fail(f"{label} does not contain its trusted motivation anchor")

        asset_anchor = (cue["asset_id"], anchor["anchor_id"])
        if asset_anchor in used_asset_anchor:
            _fail("SFX plan cannot stack the same asset on the same anchor")
        used_asset_anchor.add(asset_anchor)
        anchor_counts[anchor["anchor_id"]] = anchor_counts.get(anchor["anchor_id"], 0) + 1
        if anchor_counts[anchor["anchor_id"]] > _DENSITY_PER_ANCHOR_LIMIT[expected_limits["density"]]:
            _fail("SFX plan exceeds its density-specific per-anchor limit")
        anchor_times.append(anchor["time_ms"])
        intervals.append((start, end))

        intersections = _speech_intersections(start, end, manifest["speech_windows"])
        ducking = cue["ducking"]
        if intersections:
            speech_intervals.extend(intersections)
            if ducking is None:
                _fail(f"{label} overlaps speech without deterministic ducking")
            first_speech = intersections[0][0]
            last_speech = intersections[-1][1]
            if ducking["start_ms"] > first_speech or ducking["end_ms"] < last_speech:
                _fail(f"{label}.ducking does not cover every speech overlap")
            if ducking["start_ms"] < start or ducking["end_ms"] > end or ducking["end_ms"] <= ducking["start_ms"]:
                _fail(f"{label}.ducking must be a positive window inside the cue")
            if ducking["attack_ms"] + ducking["release_ms"] > ducking["end_ms"] - ducking["start_ms"]:
                _fail(f"{label}.ducking attack/release exceed the duck window")
            if dialogue_priority in {"primary", "verbatim"} and ducking["attack_ms"] > 20:
                _fail(f"{label}.ducking attack is too slow for primary speech")
            if placement["gain_millidb"] > 0:
                _fail(f"{label} may not use positive gain across speech")
            effective_gain = placement["gain_millidb"] - ducking["attenuation_millidb"]
            if effective_gain > expected_limits["speech_effective_gain_ceiling_millidb"]:
                _fail(f"{label} could mask speech after requested ducking")
        elif ducking is not None:
            _fail(f"{label}.ducking is unmotivated because the cue does not overlap speech")

    anchor_times.sort()
    for left in range(len(anchor_times)):
        local_count = 0
        window_end = anchor_times[left] + 10_000
        for value in anchor_times[left:]:
            if value >= window_end:
                break
            local_count += 1
        if local_count > _DENSITY_LOCAL_TEN_SECOND_LIMIT[expected_limits["density"]]:
            _fail("SFX plan clusters too many cues inside a ten-second window")

    observed_polyphony = _max_polyphony(intervals)
    if observed_polyphony > expected_limits["max_polyphony"]:
        _fail("SFX plan exceeds its profile/density polyphony ceiling")
    observed_speech_polyphony = _max_polyphony(speech_intervals)
    speech_polyphony_limit = (
        1 if dialogue_priority in {"primary", "verbatim"}
        else min(2, expected_limits["max_polyphony"])
    )
    if observed_speech_polyphony > speech_polyphony_limit:
        _fail("SFX plan stacks too many cues across speech")
    return copy.deepcopy(normalized)


def _normalize_receipt(receipt: object) -> dict[str, Any]:
    raw = _exact_dict(receipt, _RECEIPT_KEYS, "SFX compile receipt")
    if raw["schema_version"] != SFX_COMPILE_RECEIPT_SCHEMA_VERSION:
        _fail("SFX compile receipt schema_version is unsupported")
    hashes = {
        key: _sha256(raw[key], f"SFX compile receipt.{key}")
        for key in (
            "sfx_plan_sha256", "cue_manifest_sha256", "edit_policy_sha256",
            "output_timeline_sha256", "compiled_cues_sha256", "mix_primitives_sha256",
        )
    }
    cue_ids_raw = raw["ordered_cue_ids"]
    asset_ids_raw = raw["ordered_asset_ids"]
    if type(cue_ids_raw) is not list or len(cue_ids_raw) > MAX_CUES:
        _fail("SFX compile receipt.ordered_cue_ids has invalid cardinality")
    if type(asset_ids_raw) is not list or len(asset_ids_raw) != len(cue_ids_raw):
        _fail("SFX compile receipt.ordered_asset_ids must align one-to-one with cues")
    cue_ids = []
    seen_cues: set[str] = set()
    for index, value in enumerate(cue_ids_raw):
        cue_id = _identifier(value, _CUE_ID_RE, f"SFX compile receipt.ordered_cue_ids[{index}]")
        if cue_id in seen_cues:
            _fail("SFX compile receipt cue ids must be unique")
        seen_cues.add(cue_id)
        cue_ids.append(cue_id)
    asset_ids = [
        _identifier(value, _ASSET_ID_RE, f"SFX compile receipt.ordered_asset_ids[{index}]")
        for index, value in enumerate(asset_ids_raw)
    ]
    cue_count = _integer(raw["cue_count"], "SFX compile receipt.cue_count", maximum=MAX_CUES)
    if cue_count != len(cue_ids):
        _fail("SFX compile receipt.cue_count does not match ordered ids")
    unique_count = _integer(
        raw["unique_asset_count"], "SFX compile receipt.unique_asset_count", maximum=MAX_ASSETS
    )
    if unique_count != len(set(asset_ids)):
        _fail("SFX compile receipt.unique_asset_count does not match asset ids")
    policy_snapshot = _normalize_policy_snapshot(
        raw["policy"], "SFX compile receipt.policy"
    )
    if cue_count > policy_snapshot["max_cue_count"]:
        _fail("SFX compile receipt cue_count exceeds its policy ceiling")
    observed_polyphony = _integer(
        raw["max_observed_polyphony"],
        "SFX compile receipt.max_observed_polyphony", maximum=8,
    )
    if observed_polyphony > policy_snapshot["max_polyphony"]:
        _fail("SFX compile receipt polyphony exceeds its policy ceiling")
    rate = _integer(
        raw["output_sample_rate_hz"], "SFX compile receipt.output_sample_rate_hz",
        minimum=min(SAMPLE_RATES_HZ), maximum=max(SAMPLE_RATES_HZ),
    )
    if rate not in SAMPLE_RATES_HZ:
        _fail("SFX compile receipt.output_sample_rate_hz is unsupported")
    channels = _integer(
        raw["output_channels"], "SFX compile receipt.output_channels",
        minimum=1, maximum=8,
    )
    if rate != DELIVERY_SAMPLE_RATE_HZ or channels != DELIVERY_CHANNELS:
        _fail("SFX compile receipt output must be the exact 48000 Hz stereo delivery format")
    time_base = _exact_dict(raw["time_base"], _BASE_KEYS, "SFX compile receipt.time_base")
    if time_base != {"numerator": 1, "denominator": 1_000}:
        _fail("SFX compile receipt.time_base must be exact 1/1000")
    millidb_base = _exact_dict(raw["millidb_base"], _BASE_KEYS, "SFX compile receipt.millidb_base")
    if millidb_base != {"numerator": 1, "denominator": 1_000}:
        _fail("SFX compile receipt.millidb_base must be exact 1/1000 dB")
    return {
        "schema_version": SFX_COMPILE_RECEIPT_SCHEMA_VERSION,
        **hashes,
        "ordered_cue_ids": cue_ids,
        "ordered_asset_ids": asset_ids,
        "cue_count": cue_count,
        "unique_asset_count": unique_count,
        "output_duration_ms": _integer(raw["output_duration_ms"], "SFX compile receipt.output_duration_ms", minimum=1),
        "output_sample_rate_hz": rate,
        "output_channels": channels,
        "max_observed_polyphony": observed_polyphony,
        "speech_overlap_cue_count": _integer(raw["speech_overlap_cue_count"], "SFX compile receipt.speech_overlap_cue_count", maximum=cue_count),
        "time_base": {"numerator": 1, "denominator": 1_000},
        "millidb_base": {"numerator": 1, "denominator": 1_000},
        "policy": policy_snapshot,
    }


def canonical_sfx_compile_receipt_json(receipt: object) -> str:
    """Return closed key-sorted ASCII JSON for a compile receipt."""
    return _canonical_json(_normalize_receipt(receipt), "SFX compile receipt")


def sfx_compile_receipt_sha256(receipt: object) -> str:
    return hashlib.sha256(
        canonical_sfx_compile_receipt_json(receipt).encode("utf-8")
    ).hexdigest()


def compile_sfx_plan(
    plan: object,
    cue_manifest: object,
    edit_policy: object,
) -> dict[str, Any]:
    """Compile a validated plan to inert, shell-free audio-filter primitives."""
    validated = validate_sfx_plan(plan, cue_manifest, edit_policy)
    manifest = validate_sfx_cue_manifest(cue_manifest)
    assets = {asset["asset_id"]: asset for asset in manifest["assets"]}
    compiled = []
    intervals: list[tuple[int, int]] = []
    speech_overlap_count = 0
    for index, cue in enumerate(validated["cues"]):
        asset = assets[cue["asset_id"]]
        placement = cue["placement"]
        start = placement["start_ms"]
        duration = placement["trim_duration_ms"]
        end = start + duration
        intervals.append((start, end))
        cue_tokens = [
            "atrim=start=" + _ffmpeg_seconds(placement["trim_start_ms"])
            + ":duration=" + _ffmpeg_seconds(duration),
            "asetpts=PTS-STARTPTS",
            "aresample=" + str(manifest["output_sample_rate_hz"])
            + ":async=0:first_pts=0",
            "aformat=sample_fmts=fltp:sample_rates="
            + str(manifest["output_sample_rate_hz"])
            + ":channel_layouts="
            + _ffmpeg_channel_layout(manifest["output_channels"]),
        ]
        if placement["attack_fade_ms"]:
            cue_tokens.append(
                "afade=t=in:st=0.000:d="
                + _ffmpeg_seconds(placement["attack_fade_ms"])
                + ":curve=qsin"
            )
        if placement["release_fade_ms"]:
            release_start = duration - placement["release_fade_ms"]
            cue_tokens.append(
                "afade=t=out:st=" + _ffmpeg_seconds(release_start)
                + ":d=" + _ffmpeg_seconds(placement["release_fade_ms"])
                + ":curve=qsin"
            )
        cue_tokens.append(
            "volume=" + _ffmpeg_millidb(placement["gain_millidb"])
            + ":precision=double"
        )

        duck = cue["ducking"]
        sidechain_gate_tokens: list[str] = []
        compressor_tokens: list[str] = []
        if duck is not None:
            speech_overlap_count += 1
            duck_duration = duck["end_ms"] - duck["start_ms"]
            relative_start = duck["start_ms"] - start
            relative_end = relative_start + duck_duration
            sidechain_gate_tokens = [
                "aevalsrc=if(between(t\\," + _ffmpeg_seconds(relative_start)
                + "\\," + _ffmpeg_seconds(relative_end)
                + ")\\,1\\,0):d=" + _ffmpeg_seconds(duration)
                + ":s=" + str(manifest["output_sample_rate_hz"]) + ":c=mono",
            ]
            compressor_tokens = [
                "sidechaincompress=threshold="
                + DUCK_SIDECHAIN_THRESHOLD_TEXT[duck["attenuation_millidb"]]
                + ":ratio=2:attack=" + str(duck["attack_ms"])
                + ":release=" + str(duck["release_ms"])
                + ":makeup=1:knee=1:link=maximum:detection=peak:mix=1"
            ]
        timeline_tokens = ["adelay=delays=" + str(start) + ":all=1"]
        compiled.append({
            "cue_index": index,
            "cue_id": cue["cue_id"],
            "asset_id": asset["asset_id"],
            "asset_sha256": asset["sha256"],
            "asset_byte_length": asset["byte_length"],
            "asset_duration_ms": asset["duration_ms"],
            "asset_sample_rate_hz": asset["sample_rate_hz"],
            "asset_channels": asset["channels"],
            "source_ref": asset["source_ref"],
            "provenance": asset["provenance"],
            "license": asset["license"],
            "kind": cue["kind"],
            "motivation": cue["motivation"],
            "placement": placement,
            "ducking": duck,
            "output_start_ms": start,
            "output_end_ms": end,
            "speech_overlap_ms": sum(
                right - left for left, right in _speech_intersections(
                    start, end, manifest["speech_windows"]
                )
            ),
            "cue_ffmpeg_primitive_tokens": cue_tokens,
            "duck_sidechain_gate_ffmpeg_primitive_tokens": sidechain_gate_tokens,
            "sidechaincompress_ffmpeg_primitive_tokens": compressor_tokens,
            "timeline_ffmpeg_primitive_tokens": timeline_tokens,
        })

    if compiled:
        output_rate = str(manifest["output_sample_rate_hz"])
        output_layout = _ffmpeg_channel_layout(manifest["output_channels"])
        output_duration = _ffmpeg_seconds(manifest["output_duration_ms"])
        program_input_tokens = [
            "aresample=" + output_rate + ":async=0:first_pts=0",
            "aformat=sample_fmts=fltp:sample_rates=" + output_rate
            + ":channel_layouts=" + output_layout,
            "apad=whole_dur=" + output_duration,
            "atrim=start=0.000:duration=" + output_duration,
            "asetpts=PTS-STARTPTS",
        ]
        sfx_bus_tokens = [
            "amix=inputs=" + str(len(compiled))
            + ":duration=longest:dropout_transition=0:normalize=0",
            "alimiter=limit=0.891251:attack=5:release=50:level=0:latency=1",
            "apad=whole_dur=" + output_duration,
            "atrim=start=0.000:duration=" + output_duration,
            "asetpts=PTS-STARTPTS",
        ]
        program_mix_tokens = [
            "amix=inputs=2:duration=first:dropout_transition=0:normalize=0",
            "alimiter=limit=0.891251:attack=5:release=50:level=0:latency=1",
            "atrim=start=0.000:duration=" + output_duration,
            "asetpts=PTS-STARTPTS",
        ]
    else:
        program_input_tokens = []
        sfx_bus_tokens = []
        program_mix_tokens = []
    mix_primitives = {
        "program_input_ffmpeg_primitive_tokens": program_input_tokens,
        "sfx_bus_ffmpeg_primitive_tokens": sfx_bus_tokens,
        "program_mix_ffmpeg_primitive_tokens": program_mix_tokens,
    }
    compiled_hash = hashlib.sha256(
        _canonical_json(compiled, "compiled SFX cues").encode("utf-8")
    ).hexdigest()
    mix_hash = hashlib.sha256(
        _canonical_json(mix_primitives, "compiled SFX mix primitives").encode("utf-8")
    ).hexdigest()
    receipt = _normalize_receipt({
        "schema_version": SFX_COMPILE_RECEIPT_SCHEMA_VERSION,
        "sfx_plan_sha256": sfx_plan_sha256(validated),
        "cue_manifest_sha256": sfx_cue_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(edit_policy),
        "output_timeline_sha256": manifest["output_timeline_sha256"],
        "compiled_cues_sha256": compiled_hash,
        "mix_primitives_sha256": mix_hash,
        "ordered_cue_ids": [item["cue_id"] for item in compiled],
        "ordered_asset_ids": [item["asset_id"] for item in compiled],
        "cue_count": len(compiled),
        "unique_asset_count": len({item["asset_id"] for item in compiled}),
        "output_duration_ms": manifest["output_duration_ms"],
        "output_sample_rate_hz": manifest["output_sample_rate_hz"],
        "output_channels": manifest["output_channels"],
        "max_observed_polyphony": _max_polyphony(intervals),
        "speech_overlap_cue_count": speech_overlap_count,
        "time_base": {"numerator": 1, "denominator": 1_000},
        "millidb_base": {"numerator": 1, "denominator": 1_000},
        "policy": validated["policy"],
    })
    return {
        "compiled_cues": copy.deepcopy(compiled),
        **copy.deepcopy(mix_primitives),
        "receipt": copy.deepcopy(receipt),
        "receipt_sha256": sfx_compile_receipt_sha256(receipt),
    }


_LICENSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_LICENSE_KEYS),
    "properties": {
        "basis": {"type": "string", "enum": sorted(LICENSE_BASES)},
        "license_id": {"type": "string", "pattern": _SAFE_ID_RE.pattern},
        "licensor": {"type": "string", "pattern": _LICENSOR_RE.pattern},
        "evidence_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
    },
}

_POLICY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_POLICY_KEYS),
    "properties": {
        "profile": {"type": "string", "pattern": _SAFE_ID_RE.pattern},
        "density": {"type": "string", "enum": sorted(POLICY_DENSITIES)},
        "usage": {"type": "string", "enum": sorted(POLICY_USAGES)},
        "max_cue_count": {"type": "integer", "minimum": 0, "maximum": MAX_CUES},
        "max_polyphony": {"type": "integer", "minimum": 0, "maximum": 8},
        "max_gain_millidb": {"type": "integer", "minimum": -60_000, "maximum": 6_000},
        "speech_effective_gain_ceiling_millidb": {
            "type": "integer", "minimum": -60_000, "maximum": 0,
        },
    },
}

_MOTIVATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_MOTIVATION_KEYS),
    "properties": {
        "category": {"type": "string", "enum": sorted(ANCHOR_CATEGORIES)},
        "anchor_id": {"type": "string", "pattern": _ANCHOR_ID_RE.pattern},
        "reference_id": {"type": "string", "minLength": 1, "maxLength": 96},
        "anchor_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
        "evidence_start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
        "evidence_end_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
        "evidence_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
    },
}

_PLACEMENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_PLACEMENT_KEYS),
    "properties": {
        "start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
        "trim_start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_ASSET_DURATION_MS},
        "trim_duration_ms": {"type": "integer", "minimum": 20, "maximum": MAX_CUE_DURATION_MS},
        "gain_millidb": {"type": "integer", "minimum": -60_000, "maximum": 6_000},
        "attack_fade_ms": {"type": "integer", "minimum": 0, "maximum": 5_000},
        "release_fade_ms": {"type": "integer", "minimum": 0, "maximum": 5_000},
    },
}

_DUCKING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_DUCKING_KEYS),
    "properties": {
        "start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
        "end_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
        "attenuation_millidb": {
            "type": "integer", "enum": sorted(DUCK_ATTENUATIONS_MILLIDB),
        },
        "attack_ms": {"type": "integer", "minimum": 1, "maximum": 200},
        "release_ms": {"type": "integer", "minimum": 1, "maximum": 2_000},
    },
}

SFX_CUE_MANIFEST_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_MANIFEST_KEYS),
    "properties": {
        "schema_version": {"const": SFX_CUE_MANIFEST_SCHEMA_VERSION},
        "output_timeline_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "output_duration_ms": {"type": "integer", "minimum": 1, "maximum": MAX_SAFE_INTEGER},
        "output_sample_rate_hz": {"const": DELIVERY_SAMPLE_RATE_HZ},
        "output_channels": {"const": DELIVERY_CHANNELS},
        "assets": {
            "type": "array", "maxItems": MAX_ASSETS,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": sorted(_ASSET_KEYS),
                "properties": {
                    "asset_id": {"type": "string", "pattern": _ASSET_ID_RE.pattern},
                    "sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
                    "byte_length": {"type": "integer", "minimum": 1, "maximum": MAX_ASSET_BYTES},
                    "duration_ms": {"type": "integer", "minimum": 1, "maximum": MAX_ASSET_DURATION_MS},
                    "sample_rate_hz": {"type": "integer", "enum": sorted(SAMPLE_RATES_HZ)},
                    "channels": {"type": "integer", "minimum": 1, "maximum": 8},
                    "source_ref": {"type": "string", "pattern": _SOURCE_REF_RE.pattern},
                    "provenance": {"type": "string", "enum": sorted(PROVENANCE_KINDS)},
                    "license": copy.deepcopy(_LICENSE_JSON_SCHEMA),
                },
            },
        },
        "anchors": {
            "type": "array", "maxItems": MAX_ANCHORS,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": sorted(_ANCHOR_KEYS),
                "properties": {
                    "anchor_id": {"type": "string", "pattern": _ANCHOR_ID_RE.pattern},
                    "category": {"type": "string", "enum": sorted(ANCHOR_CATEGORIES)},
                    "reference_id": {"type": "string", "minLength": 1, "maxLength": 96},
                    "time_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
                    "evidence_start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
                    "evidence_end_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
                    "evidence_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
                },
            },
        },
        "speech_windows": {
            "type": "array", "maxItems": MAX_SPEECH_WINDOWS,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": sorted(_SPEECH_KEYS),
                "properties": {
                    "speech_id": {"type": "string", "pattern": _SPEECH_ID_RE.pattern},
                    "start_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
                    "end_ms": {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
                    "evidence_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
                },
            },
        },
    },
}

SFX_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_PLAN_KEYS),
    "properties": {
        "schema_version": {"const": SFX_PLAN_SCHEMA_VERSION},
        "cue_manifest_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "edit_policy_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "output_timeline_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
        "output_duration_ms": {"type": "integer", "minimum": 1, "maximum": MAX_SAFE_INTEGER},
        "policy": copy.deepcopy(_POLICY_JSON_SCHEMA),
        "cues": {
            "type": "array",
            "maxItems": MAX_CUES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_CUE_KEYS),
                "properties": {
                    "cue_id": {"type": "string", "pattern": _CUE_ID_RE.pattern},
                    "asset_id": {"type": "string", "pattern": _ASSET_ID_RE.pattern},
                    "asset_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
                    "kind": {"type": "string", "enum": sorted(CUE_KINDS)},
                    "motivation": copy.deepcopy(_MOTIVATION_JSON_SCHEMA),
                    "placement": copy.deepcopy(_PLACEMENT_JSON_SCHEMA),
                    "ducking": {
                        "oneOf": [
                            {"type": "null"},
                            copy.deepcopy(_DUCKING_JSON_SCHEMA),
                        ]
                    },
                },
            },
        },
    },
}

SFX_COMPILE_RECEIPT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_RECEIPT_KEYS),
    "properties": {
        "schema_version": {"const": SFX_COMPILE_RECEIPT_SCHEMA_VERSION},
        **{
            key: {"type": "string", "pattern": _SHA256_RE.pattern}
            for key in (
                "sfx_plan_sha256", "cue_manifest_sha256", "edit_policy_sha256",
                "output_timeline_sha256", "compiled_cues_sha256", "mix_primitives_sha256",
            )
        },
        "ordered_cue_ids": {
            "type": "array", "maxItems": MAX_CUES,
            "items": {"type": "string", "pattern": _CUE_ID_RE.pattern},
        },
        "ordered_asset_ids": {
            "type": "array", "maxItems": MAX_CUES,
            "items": {"type": "string", "pattern": _ASSET_ID_RE.pattern},
        },
        "cue_count": {"type": "integer", "minimum": 0, "maximum": MAX_CUES},
        "unique_asset_count": {"type": "integer", "minimum": 0, "maximum": MAX_ASSETS},
        "output_duration_ms": {"type": "integer", "minimum": 1, "maximum": MAX_SAFE_INTEGER},
        "output_sample_rate_hz": {"const": DELIVERY_SAMPLE_RATE_HZ},
        "output_channels": {"const": DELIVERY_CHANNELS},
        "max_observed_polyphony": {"type": "integer", "minimum": 0, "maximum": 8},
        "speech_overlap_cue_count": {"type": "integer", "minimum": 0, "maximum": MAX_CUES},
        "time_base": {
            "type": "object", "additionalProperties": False,
            "required": sorted(_BASE_KEYS),
            "properties": {
                "numerator": {"const": 1}, "denominator": {"const": 1_000},
            },
        },
        "millidb_base": {
            "type": "object", "additionalProperties": False,
            "required": sorted(_BASE_KEYS),
            "properties": {
                "numerator": {"const": 1}, "denominator": {"const": 1_000},
            },
        },
        "policy": copy.deepcopy(_POLICY_JSON_SCHEMA),
    },
}
