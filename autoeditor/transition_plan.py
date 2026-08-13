"""Closed, deterministic transition planning for an ordered sequence.

This module is deliberately an inert contract/compiler.  It never resolves a
path, opens media, builds a shell command, or invokes FFmpeg.  A trusted
producer first describes the already-compiled sequence in an
``autoeditor-transition-sequence-manifest/v1``.  That manifest binds the
ordered segment ids and source hashes, exact durations, decoded edge handles,
dialogue-at-edge observations, frame rate, and the upstream plan/compile
receipt hashes.

The transition plan then makes one explicit decision for every real adjacency,
including hard cuts.  Boundary ids are derived from the exact adjacent segment
ids, source hashes, and cumulative millisecond boundary, so a planner cannot
move a transition to a different cut while retaining its identity.  Validation
also binds the resolved edit-policy hash and its transition density/usage.

Compilation emits only inert, constant-shape FFmpeg filter primitive tokens.
The execution layer must attach trusted stream labels, compose the graph, and
pass it to FFmpeg without a shell.  ``qsin``/``qsin`` audio curves are used for
the equal-power crossfade.  The video primitives use FFmpeg's ``xfade``
``fade`` and ``fadeblack`` transitions.  Both require normalized CFR inputs
with the same geometry, pixel format, frame rate, and time base; satisfying
that renderer precondition remains an integration responsibility.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any

from autoeditor.edit_policy import (
    EditPolicyError,
    edit_policy_sha256,
    validate_edit_policy,
)


TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION = (
    "autoeditor-transition-sequence-manifest/v1"
)
TRANSITION_PLAN_SCHEMA_VERSION = "autoeditor-transition-plan/v1"
TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-transition-compile-receipt/v1"
)

MAX_SEGMENTS = 256
MAX_TRANSITION_DURATION_MS = 1_000
MIN_TRANSITION_FRAMES = 2
MIN_DIP_TO_BLACK_FRAMES = 4
MAX_SAFE_INTEGER = 9_007_199_254_740_991

TRANSITION_KINDS = frozenset({
    "hard_cut", "cross_dissolve", "dip_to_black",
})
MOTIVATIONS = frozenset({
    "motivated_only",
    "beat_or_phrase_motivated",
    "continuity_motivated",
    "location_motivated",
})
AUDIO_BEHAVIORS = frozenset({"hard_cut", "equal_power_crossfade"})
POLICY_DENSITIES = frozenset({"none", "sparse", "medium", "dense"})
POLICY_USAGES = frozenset((*MOTIVATIONS, "hard_cut_only"))

_MANIFEST_KEYS = frozenset({
    "schema_version",
    "sequence_plan_sha256",
    "sequence_compile_receipt_sha256",
    "frame_rate",
    "segments",
})
_MANIFEST_SEGMENT_KEYS = frozenset({
    "segment_id",
    "source_sha256",
    "duration_ms",
    "video_leading_handle_ms",
    "video_trailing_handle_ms",
    "audio_leading_handle_ms",
    "audio_trailing_handle_ms",
    "dialogue_at_start",
    "dialogue_at_end",
})
_FRAME_RATE_KEYS = frozenset({"numerator", "denominator"})
_PLAN_KEYS = frozenset({
    "schema_version",
    "sequence_manifest_sha256",
    "edit_policy_sha256",
    "frame_rate",
    "policy",
    "boundaries",
})
_POLICY_KEYS = frozenset({"density", "usage"})
_BOUNDARY_KEYS = frozenset({
    "boundary_id",
    "left_segment_id",
    "right_segment_id",
    "left_source_sha256",
    "right_source_sha256",
    "cumulative_boundary_ms",
    "kind",
    "motivation",
    "duration_ms",
    "audio_behavior",
    "motivation_verified",
    "semantic_safety_verified",
    "dialogue_preservation_verified",
})
_RECEIPT_KEYS = frozenset({
    "schema_version",
    "transition_plan_sha256",
    "sequence_manifest_sha256",
    "edit_policy_sha256",
    "sequence_plan_sha256",
    "sequence_compile_receipt_sha256",
    "compiled_boundaries_sha256",
    "ordered_boundary_ids",
    "boundary_count",
    "non_hard_transition_count",
    "source_duration_ms",
    "output_duration_ms",
    "time_base",
    "frame_rate",
    "policy",
})
_TIME_BASE_KEYS = frozenset({"numerator", "denominator"})

_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$", re.ASCII)
_BOUNDARY_ID = re.compile(r"^boundary-[0-9a-f]{64}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


def _frame_rate_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_FRAME_RATE_KEYS),
        "properties": {
            "numerator": {"type": "integer", "minimum": 1,
                          "maximum": 240_000},
            "denominator": {"type": "integer", "minimum": 1,
                            "maximum": 10_000},
        },
    }


TRANSITION_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_PLAN_KEYS),
    "properties": {
        "schema_version": {"const": TRANSITION_PLAN_SCHEMA_VERSION},
        "sequence_manifest_sha256": {
            "type": "string", "pattern": _SHA256.pattern,
        },
        "edit_policy_sha256": {
            "type": "string", "pattern": _SHA256.pattern,
        },
        "frame_rate": _frame_rate_json_schema(),
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_POLICY_KEYS),
            "properties": {
                "density": {"type": "string",
                            "enum": sorted(POLICY_DENSITIES)},
                "usage": {"type": "string", "enum": sorted(POLICY_USAGES)},
            },
        },
        "boundaries": {
            "type": "array",
            "minItems": 0,
            "maxItems": MAX_SEGMENTS - 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_BOUNDARY_KEYS),
                "properties": {
                    "boundary_id": {
                        "type": "string", "pattern": _BOUNDARY_ID.pattern,
                    },
                    "left_segment_id": {
                        "type": "string", "pattern": _SEGMENT_ID.pattern,
                    },
                    "right_segment_id": {
                        "type": "string", "pattern": _SEGMENT_ID.pattern,
                    },
                    "left_source_sha256": {
                        "type": "string", "pattern": _SHA256.pattern,
                    },
                    "right_source_sha256": {
                        "type": "string", "pattern": _SHA256.pattern,
                    },
                    "cumulative_boundary_ms": {
                        "type": "integer", "minimum": 1,
                        "maximum": MAX_SAFE_INTEGER,
                    },
                    "kind": {"type": "string",
                             "enum": sorted(TRANSITION_KINDS)},
                    "motivation": {"type": "string",
                                   "enum": sorted(MOTIVATIONS)},
                    "duration_ms": {
                        "type": "integer", "minimum": 0,
                        "maximum": MAX_TRANSITION_DURATION_MS,
                    },
                    "audio_behavior": {"type": "string",
                                       "enum": sorted(AUDIO_BEHAVIORS)},
                    "motivation_verified": {"type": "boolean"},
                    "semantic_safety_verified": {"type": "boolean"},
                    "dialogue_preservation_verified": {"type": "boolean"},
                },
            },
        },
    },
}


class TransitionPlanError(ValueError):
    """The sequence, policy, transition plan, or receipt is unsafe/malformed."""


def _fail(message: str) -> None:
    raise TransitionPlanError(message)


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


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be a boolean")
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
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a full lowercase SHA-256 digest")
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
        raise TransitionPlanError(f"{label} is not canonical JSON") from error


def _normalize_frame_rate(value: object, label: str) -> dict[str, int]:
    raw = _exact_dict(value, _FRAME_RATE_KEYS, label)
    numerator = _integer(
        raw["numerator"], f"{label}.numerator", minimum=1, maximum=240_000
    )
    denominator = _integer(
        raw["denominator"], f"{label}.denominator",
        minimum=1, maximum=10_000,
    )
    if math.gcd(numerator, denominator) != 1:
        _fail(f"{label} must be a reduced rational")
    if numerator < denominator or numerator > 240 * denominator:
        _fail(f"{label} must be from 1 to 240 frames per second")
    return {"numerator": numerator, "denominator": denominator}


def _round_positive_ratio(numerator: int, denominator: int) -> int:
    """Round a non-negative rational half-up using integer arithmetic."""
    return (2 * numerator + denominator) // (2 * denominator)


def _duration_frames(duration_ms: int, frame_rate: dict[str, int]) -> int:
    return _round_positive_ratio(
        duration_ms * frame_rate["numerator"],
        1_000 * frame_rate["denominator"],
    )


def _canonical_frame_duration_ms(
    frames: int, frame_rate: dict[str, int]
) -> int:
    return _round_positive_ratio(
        frames * 1_000 * frame_rate["denominator"],
        frame_rate["numerator"],
    )


def _minimum_frame_ms(frame_rate: dict[str, int]) -> int:
    # Ceiling is conservative: at least one complete output frame remains.
    numerator = 1_000 * frame_rate["denominator"]
    return (numerator + frame_rate["numerator"] - 1) // frame_rate["numerator"]


def _ffmpeg_seconds(milliseconds: int) -> str:
    return f"{milliseconds // 1_000}.{milliseconds % 1_000:03d}"


def _normalize_policy(value: object, label: str) -> dict[str, str]:
    raw = _exact_dict(value, _POLICY_KEYS, label)
    return {
        "density": _enum(raw["density"], POLICY_DENSITIES,
                         f"{label}.density"),
        "usage": _enum(raw["usage"], POLICY_USAGES, f"{label}.usage"),
    }


def validate_transition_sequence_manifest(manifest: object) -> dict[str, Any]:
    """Validate and detach the trusted ordered-sequence transition input."""
    raw = _exact_dict(manifest, _MANIFEST_KEYS, "transition sequence manifest")
    if raw["schema_version"] != TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION:
        _fail("transition sequence manifest schema_version is unsupported")
    plan_hash = _sha256(
        raw["sequence_plan_sha256"],
        "transition sequence manifest.sequence_plan_sha256",
    )
    receipt_hash = _sha256(
        raw["sequence_compile_receipt_sha256"],
        "transition sequence manifest.sequence_compile_receipt_sha256",
    )
    frame_rate = _normalize_frame_rate(
        raw["frame_rate"], "transition sequence manifest.frame_rate"
    )
    raw_segments = raw["segments"]
    if type(raw_segments) is not list or not 1 <= len(raw_segments) <= MAX_SEGMENTS:
        _fail(f"transition sequence manifest.segments must contain 1-{MAX_SEGMENTS} entries")

    segments: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_duration = 0
    for index, raw_segment in enumerate(raw_segments):
        label = f"transition sequence manifest.segments[{index}]"
        item = _exact_dict(raw_segment, _MANIFEST_SEGMENT_KEYS, label)
        segment_id = _identifier(item["segment_id"], _SEGMENT_ID,
                                 f"{label}.segment_id")
        if segment_id in seen_ids:
            _fail(f"{label}.segment_id must be unique")
        seen_ids.add(segment_id)
        source_hash = _sha256(item["source_sha256"],
                              f"{label}.source_sha256")
        duration = _integer(item["duration_ms"], f"{label}.duration_ms",
                            minimum=1)
        handles = {}
        for key in (
            "video_leading_handle_ms", "video_trailing_handle_ms",
            "audio_leading_handle_ms", "audio_trailing_handle_ms",
        ):
            handles[key] = _integer(item[key], f"{label}.{key}",
                                    maximum=duration)
        total_duration += duration
        if total_duration > MAX_SAFE_INTEGER:
            _fail("transition sequence duration exceeds exact JSON integer range")
        segments.append({
            "segment_id": segment_id,
            "source_sha256": source_hash,
            "duration_ms": duration,
            **handles,
            "dialogue_at_start": _boolean(
                item["dialogue_at_start"], f"{label}.dialogue_at_start"
            ),
            "dialogue_at_end": _boolean(
                item["dialogue_at_end"], f"{label}.dialogue_at_end"
            ),
        })

    return copy.deepcopy({
        "schema_version": TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
        "sequence_plan_sha256": plan_hash,
        "sequence_compile_receipt_sha256": receipt_hash,
        "frame_rate": frame_rate,
        "segments": segments,
    })


def canonical_transition_sequence_manifest_json(manifest: object) -> str:
    return _canonical_json(
        validate_transition_sequence_manifest(manifest),
        "transition sequence manifest",
    )


def transition_sequence_manifest_sha256(manifest: object) -> str:
    return hashlib.sha256(
        canonical_transition_sequence_manifest_json(manifest).encode("utf-8")
    ).hexdigest()


def derive_boundary_id(
    left_segment_id: object,
    right_segment_id: object,
    left_source_sha256: object,
    right_source_sha256: object,
    cumulative_boundary_ms: object,
) -> str:
    """Derive a stable id from the complete immutable adjacency binding."""
    binding = {
        "cumulative_boundary_ms": _integer(
            cumulative_boundary_ms, "boundary binding.cumulative_boundary_ms",
            minimum=1,
        ),
        "left_segment_id": _identifier(
            left_segment_id, _SEGMENT_ID, "boundary binding.left_segment_id"
        ),
        "left_source_sha256": _sha256(
            left_source_sha256, "boundary binding.left_source_sha256"
        ),
        "right_segment_id": _identifier(
            right_segment_id, _SEGMENT_ID, "boundary binding.right_segment_id"
        ),
        "right_source_sha256": _sha256(
            right_source_sha256, "boundary binding.right_source_sha256"
        ),
    }
    digest = hashlib.sha256(
        _canonical_json(binding, "boundary binding").encode("utf-8")
    ).hexdigest()
    return "boundary-" + digest


def _manifest_boundaries(
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    boundaries = []
    cumulative = 0
    segments = manifest["segments"]
    for index, left in enumerate(segments[:-1]):
        cumulative += left["duration_ms"]
        right = segments[index + 1]
        boundaries.append({
            "boundary_id": derive_boundary_id(
                left["segment_id"], right["segment_id"],
                left["source_sha256"], right["source_sha256"], cumulative,
            ),
            "left_segment_id": left["segment_id"],
            "right_segment_id": right["segment_id"],
            "left_source_sha256": left["source_sha256"],
            "right_source_sha256": right["source_sha256"],
            "cumulative_boundary_ms": cumulative,
        })
    return boundaries


def _normalize_plan(plan: object) -> dict[str, Any]:
    raw = _exact_dict(plan, _PLAN_KEYS, "transition plan")
    if raw["schema_version"] != TRANSITION_PLAN_SCHEMA_VERSION:
        _fail("transition plan schema_version is unsupported")
    manifest_hash = _sha256(
        raw["sequence_manifest_sha256"],
        "transition plan.sequence_manifest_sha256",
    )
    policy_hash = _sha256(
        raw["edit_policy_sha256"], "transition plan.edit_policy_sha256"
    )
    frame_rate = _normalize_frame_rate(raw["frame_rate"],
                                       "transition plan.frame_rate")
    policy = _normalize_policy(raw["policy"], "transition plan.policy")
    raw_boundaries = raw["boundaries"]
    if type(raw_boundaries) is not list or len(raw_boundaries) > MAX_SEGMENTS - 1:
        _fail(f"transition plan.boundaries must contain 0-{MAX_SEGMENTS - 1} entries")

    boundaries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    previous_boundary_ms = 0
    for index, raw_boundary in enumerate(raw_boundaries):
        label = f"transition plan.boundaries[{index}]"
        item = _exact_dict(raw_boundary, _BOUNDARY_KEYS, label)
        left_id = _identifier(item["left_segment_id"], _SEGMENT_ID,
                              f"{label}.left_segment_id")
        right_id = _identifier(item["right_segment_id"], _SEGMENT_ID,
                               f"{label}.right_segment_id")
        left_hash = _sha256(item["left_source_sha256"],
                            f"{label}.left_source_sha256")
        right_hash = _sha256(item["right_source_sha256"],
                             f"{label}.right_source_sha256")
        boundary_ms = _integer(
            item["cumulative_boundary_ms"],
            f"{label}.cumulative_boundary_ms", minimum=1,
        )
        if boundary_ms <= previous_boundary_ms:
            _fail("transition plan boundaries must be in increasing sequence order")
        previous_boundary_ms = boundary_ms
        expected_id = derive_boundary_id(
            left_id, right_id, left_hash, right_hash, boundary_ms
        )
        boundary_id = _identifier(item["boundary_id"], _BOUNDARY_ID,
                                  f"{label}.boundary_id")
        if boundary_id != expected_id:
            _fail(f"{label}.boundary_id does not bind its exact adjacency")
        if boundary_id in seen_ids:
            _fail(f"{label}.boundary_id must be unique")
        seen_ids.add(boundary_id)

        kind = _enum(item["kind"], TRANSITION_KINDS, f"{label}.kind")
        motivation = _enum(item["motivation"], MOTIVATIONS,
                           f"{label}.motivation")
        duration = _integer(
            item["duration_ms"], f"{label}.duration_ms",
            maximum=MAX_TRANSITION_DURATION_MS,
        )
        audio_behavior = _enum(
            item["audio_behavior"], AUDIO_BEHAVIORS,
            f"{label}.audio_behavior",
        )
        motivation_verified = _boolean(
            item["motivation_verified"], f"{label}.motivation_verified"
        )
        semantic_verified = _boolean(
            item["semantic_safety_verified"],
            f"{label}.semantic_safety_verified",
        )
        dialogue_verified = _boolean(
            item["dialogue_preservation_verified"],
            f"{label}.dialogue_preservation_verified",
        )

        if kind == "hard_cut":
            if duration != 0:
                _fail(f"{label}.duration_ms must be 0 for a hard cut")
            if audio_behavior != "hard_cut":
                _fail(f"{label}.audio_behavior must be hard_cut for a hard cut")
        else:
            if duration == 0:
                _fail(f"{label}.duration_ms must be positive for a transition")
            if audio_behavior != "equal_power_crossfade":
                _fail(
                    f"{label}.audio_behavior must be equal_power_crossfade "
                    "for a timed video transition"
                )
            if not motivation_verified:
                _fail(f"{label}.motivation_verified must be true")
        # Every cut is a semantic operation, including a nominal hard cut.
        # False/missing evidence cannot silently pass merely because duration=0.
        if not semantic_verified:
            _fail(f"{label}.semantic_safety_verified must be true")
        if not dialogue_verified:
            _fail(f"{label}.dialogue_preservation_verified must be true")

        boundaries.append({
            "boundary_id": boundary_id,
            "left_segment_id": left_id,
            "right_segment_id": right_id,
            "left_source_sha256": left_hash,
            "right_source_sha256": right_hash,
            "cumulative_boundary_ms": boundary_ms,
            "kind": kind,
            "motivation": motivation,
            "duration_ms": duration,
            "audio_behavior": audio_behavior,
            "motivation_verified": motivation_verified,
            "semantic_safety_verified": True,
            "dialogue_preservation_verified": True,
        })

    return {
        "schema_version": TRANSITION_PLAN_SCHEMA_VERSION,
        "sequence_manifest_sha256": manifest_hash,
        "edit_policy_sha256": policy_hash,
        "frame_rate": frame_rate,
        "policy": policy,
        "boundaries": boundaries,
    }


def canonical_transition_plan_json(plan: object) -> str:
    """Return key-sorted, whitespace-free canonical JSON for a closed plan."""
    return _canonical_json(_normalize_plan(plan), "transition plan")


def transition_plan_sha256(plan: object) -> str:
    return hashlib.sha256(
        canonical_transition_plan_json(plan).encode("utf-8")
    ).hexdigest()


def density_transition_limit(density: str, boundary_count: int) -> int:
    """Return a conservative non-hard-transition ceiling for a policy density.

    Density is an upper bound, never a quota: the contract never forces a
    decorative transition merely to hit a target count.
    """
    density = _enum(density, POLICY_DENSITIES, "transition density")
    boundary_count = _integer(
        boundary_count, "boundary_count", maximum=MAX_SEGMENTS - 1
    )
    if density == "none" or boundary_count == 0:
        return 0
    divisor = {"sparse": 4, "medium": 2, "dense": 1}[density]
    return (boundary_count + divisor - 1) // divisor


def validate_transition_plan(
    plan: object,
    sequence_manifest: object,
    edit_policy: object,
) -> dict[str, Any]:
    """Validate, normalize, and bind all transition decisions.

    The boundary list must be an exhaustive, ordered, one-to-one match for the
    manifest's real adjacencies.  This rejects missing, duplicate, reordered,
    first/last phantom, and source/timeline-tampered boundaries.
    """
    normalized = _normalize_plan(plan)
    manifest = validate_transition_sequence_manifest(sequence_manifest)
    try:
        policy = validate_edit_policy(edit_policy)
        expected_policy_hash = edit_policy_sha256(policy)
    except EditPolicyError as error:
        raise TransitionPlanError("edit policy is invalid") from error

    manifest_hash = transition_sequence_manifest_sha256(manifest)
    if normalized["sequence_manifest_sha256"] != manifest_hash:
        _fail("transition plan does not bind the transition sequence manifest")
    if normalized["edit_policy_sha256"] != expected_policy_hash:
        _fail("transition plan does not bind the resolved edit policy")
    if normalized["frame_rate"] != manifest["frame_rate"]:
        _fail("transition plan frame_rate does not match the sequence manifest")

    expected_rule = policy["rules"]["transitions"]
    if normalized["policy"] != expected_rule:
        _fail("transition plan policy density/usage does not match edit policy")

    expected_boundaries = _manifest_boundaries(manifest)
    if len(normalized["boundaries"]) != len(expected_boundaries):
        _fail("transition plan must decide every and only real sequence boundary")

    non_hard_count = 0
    segment_by_id = {item["segment_id"]: item for item in manifest["segments"]}
    expected_motivation = (
        "motivated_only"
        if expected_rule["usage"] == "hard_cut_only"
        else expected_rule["usage"]
    )
    minimum_frame_ms = _minimum_frame_ms(manifest["frame_rate"])

    for index, (boundary, expected) in enumerate(zip(
        normalized["boundaries"], expected_boundaries
    )):
        label = f"transition plan.boundaries[{index}]"
        for key, expected_value in expected.items():
            if boundary[key] != expected_value:
                _fail(f"{label}.{key} does not match the exact sequence boundary")
        if boundary["motivation"] != expected_motivation:
            _fail(f"{label}.motivation does not match policy usage")

        duration = boundary["duration_ms"]
        if boundary["kind"] != "hard_cut":
            non_hard_count += 1
            if expected_rule["density"] == "none" or (
                expected_rule["usage"] == "hard_cut_only"
            ):
                _fail(f"{label} violates the cut-only transition policy")

            frames = _duration_frames(duration, manifest["frame_rate"])
            if frames < MIN_TRANSITION_FRAMES:
                _fail(f"{label}.duration_ms is shorter than two output frames")
            if _canonical_frame_duration_ms(frames, manifest["frame_rate"]) != duration:
                _fail(f"{label}.duration_ms is not aligned to an output frame")
            if boundary["kind"] == "dip_to_black" and (
                frames < MIN_DIP_TO_BLACK_FRAMES or frames % 2 != 0
            ):
                _fail(
                    f"{label}.duration_ms must span an even number of at least "
                    f"{MIN_DIP_TO_BLACK_FRAMES} frames for dip_to_black"
                )

            left = segment_by_id[boundary["left_segment_id"]]
            right = segment_by_id[boundary["right_segment_id"]]
            if duration + minimum_frame_ms > left["duration_ms"] or (
                duration + minimum_frame_ms > right["duration_ms"]
            ):
                _fail(
                    f"{label}.duration_ms must leave at least one complete "
                    "untransformed frame in each adjacent segment"
                )
            handle_checks = (
                (left, "video_trailing_handle_ms"),
                (right, "video_leading_handle_ms"),
                (left, "audio_trailing_handle_ms"),
                (right, "audio_leading_handle_ms"),
            )
            for segment, handle_key in handle_checks:
                if duration > segment[handle_key]:
                    _fail(
                        f"{label}.duration_ms exceeds decoded {handle_key} "
                        f"for segment {segment['segment_id']}"
                    )
        left = segment_by_id[boundary["left_segment_id"]]
        right = segment_by_id[boundary["right_segment_id"]]
        dialogue_crossing = left["dialogue_at_end"] or right["dialogue_at_start"]
        if dialogue_crossing and not boundary["dialogue_preservation_verified"]:
            _fail(f"{label} could silently damage dialogue")

    limit = density_transition_limit(
        expected_rule["density"], len(expected_boundaries)
    )
    if non_hard_count > limit:
        _fail(
            f"transition plan has {non_hard_count} timed transitions but "
            f"policy density permits at most {limit}"
        )

    # Edge transition windows on an interior segment must not overlap.  The
    # manifest handles are checked independently because large handles alone do
    # not prove two effects fit simultaneously inside one selected segment.
    for segment_index in range(1, len(manifest["segments"]) - 1):
        incoming = normalized["boundaries"][segment_index - 1]["duration_ms"]
        outgoing = normalized["boundaries"][segment_index]["duration_ms"]
        segment = manifest["segments"][segment_index]
        if incoming + outgoing + minimum_frame_ms > segment["duration_ms"]:
            _fail(
                "transition windows must leave at least one complete "
                f"untransformed frame inside segment {segment['segment_id']}"
            )

    return copy.deepcopy(normalized)


def _normalize_receipt(receipt: object) -> dict[str, Any]:
    raw = _exact_dict(receipt, _RECEIPT_KEYS, "transition compile receipt")
    if raw["schema_version"] != TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION:
        _fail("transition compile receipt schema_version is unsupported")
    hashes = {
        key: _sha256(raw[key], f"transition compile receipt.{key}")
        for key in (
            "transition_plan_sha256",
            "sequence_manifest_sha256",
            "edit_policy_sha256",
            "sequence_plan_sha256",
            "sequence_compile_receipt_sha256",
            "compiled_boundaries_sha256",
        )
    }
    ordered = raw["ordered_boundary_ids"]
    if type(ordered) is not list or len(ordered) > MAX_SEGMENTS - 1:
        _fail("transition compile receipt.ordered_boundary_ids has invalid cardinality")
    normalized_ids = []
    seen_ids: set[str] = set()
    for index, value in enumerate(ordered):
        boundary_id = _identifier(
            value, _BOUNDARY_ID,
            f"transition compile receipt.ordered_boundary_ids[{index}]",
        )
        if boundary_id in seen_ids:
            _fail("transition compile receipt boundary ids must be unique")
        seen_ids.add(boundary_id)
        normalized_ids.append(boundary_id)
    count = _integer(
        raw["boundary_count"], "transition compile receipt.boundary_count",
        maximum=MAX_SEGMENTS - 1,
    )
    if count != len(normalized_ids):
        _fail("transition compile receipt.boundary_count does not match ids")
    non_hard = _integer(
        raw["non_hard_transition_count"],
        "transition compile receipt.non_hard_transition_count",
        maximum=count,
    )
    source_duration = _integer(
        raw["source_duration_ms"],
        "transition compile receipt.source_duration_ms", minimum=1,
    )
    output_duration = _integer(
        raw["output_duration_ms"],
        "transition compile receipt.output_duration_ms", minimum=1,
        maximum=source_duration,
    )
    time_base = _exact_dict(
        raw["time_base"], _TIME_BASE_KEYS,
        "transition compile receipt.time_base",
    )
    if time_base != {"numerator": 1, "denominator": 1_000}:
        _fail("transition compile receipt.time_base must be exact 1/1000")
    frame_rate = _normalize_frame_rate(
        raw["frame_rate"], "transition compile receipt.frame_rate"
    )
    policy = _normalize_policy(raw["policy"],
                               "transition compile receipt.policy")
    return {
        "schema_version": TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION,
        **hashes,
        "ordered_boundary_ids": normalized_ids,
        "boundary_count": count,
        "non_hard_transition_count": non_hard,
        "source_duration_ms": source_duration,
        "output_duration_ms": output_duration,
        "time_base": {"numerator": 1, "denominator": 1_000},
        "frame_rate": frame_rate,
        "policy": policy,
    }


def transition_compile_receipt_sha256(receipt: object) -> str:
    canonical = _canonical_json(
        _normalize_receipt(receipt), "transition compile receipt"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compile_transition_plan(
    plan: object,
    sequence_manifest: object,
    edit_policy: object,
) -> dict[str, Any]:
    """Compile a validated transition plan into inert primitive tokens."""
    validated = validate_transition_plan(plan, sequence_manifest, edit_policy)
    manifest = validate_transition_sequence_manifest(sequence_manifest)
    source_duration = sum(item["duration_ms"] for item in manifest["segments"])
    segment_by_id = {item["segment_id"]: item for item in manifest["segments"]}

    compiled = []
    cumulative_overlap_ms = 0
    non_hard_count = 0
    for index, boundary in enumerate(validated["boundaries"]):
        duration = boundary["duration_ms"]
        output_boundary_ms = (
            boundary["cumulative_boundary_ms"] - cumulative_overlap_ms
        )
        dialogue_crossing = (
            segment_by_id[boundary["left_segment_id"]]["dialogue_at_end"]
            or segment_by_id[boundary["right_segment_id"]]["dialogue_at_start"]
        )
        if boundary["kind"] == "hard_cut":
            duration_frames = 0
            video_tokens = ["concat=n=2:v=1:a=0"]
            audio_tokens = ["concat=n=2:v=0:a=1"]
        else:
            non_hard_count += 1
            duration_frames = _duration_frames(duration, manifest["frame_rate"])
            xfade_name = (
                "fade" if boundary["kind"] == "cross_dissolve" else "fadeblack"
            )
            offset_ms = output_boundary_ms - duration
            if offset_ms < 0:  # Defensive; adjacent-duration checks should imply this.
                _fail("compiled transition offset would be negative")
            video_tokens = [
                "xfade=transition=" + xfade_name
                + ":duration=" + _ffmpeg_seconds(duration)
                + ":offset=" + _ffmpeg_seconds(offset_ms)
            ]
            audio_tokens = [
                "acrossfade=d=" + _ffmpeg_seconds(duration)
                + ":o=1:c1=qsin:c2=qsin"
            ]
        compiled.append({
            "boundary_index": index,
            "boundary_id": boundary["boundary_id"],
            "left_segment_id": boundary["left_segment_id"],
            "right_segment_id": boundary["right_segment_id"],
            "left_source_sha256": boundary["left_source_sha256"],
            "right_source_sha256": boundary["right_source_sha256"],
            "cumulative_boundary_ms": boundary["cumulative_boundary_ms"],
            "output_boundary_ms": output_boundary_ms,
            "kind": boundary["kind"],
            "motivation": boundary["motivation"],
            "duration_ms": duration,
            "duration_frames": duration_frames,
            "audio_behavior": boundary["audio_behavior"],
            "dialogue_crossing": dialogue_crossing,
            "video_ffmpeg_primitive_tokens": video_tokens,
            "audio_ffmpeg_primitive_tokens": audio_tokens,
        })
        cumulative_overlap_ms += duration

    compiled_hash = hashlib.sha256(
        _canonical_json(compiled, "compiled transition boundaries").encode("utf-8")
    ).hexdigest()
    receipt = _normalize_receipt({
        "schema_version": TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION,
        "transition_plan_sha256": transition_plan_sha256(validated),
        "sequence_manifest_sha256": transition_sequence_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(edit_policy),
        "sequence_plan_sha256": manifest["sequence_plan_sha256"],
        "sequence_compile_receipt_sha256": (
            manifest["sequence_compile_receipt_sha256"]
        ),
        "compiled_boundaries_sha256": compiled_hash,
        "ordered_boundary_ids": [item["boundary_id"] for item in compiled],
        "boundary_count": len(compiled),
        "non_hard_transition_count": non_hard_count,
        "source_duration_ms": source_duration,
        "output_duration_ms": source_duration - cumulative_overlap_ms,
        "time_base": {"numerator": 1, "denominator": 1_000},
        "frame_rate": manifest["frame_rate"],
        "policy": validated["policy"],
    })
    return {
        "compiled_boundaries": copy.deepcopy(compiled),
        "receipt": copy.deepcopy(receipt),
        "receipt_sha256": transition_compile_receipt_sha256(receipt),
    }
