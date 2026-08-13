"""Trusted FFmpeg executor for compiled sequence-transition contracts.

The transition planner emits inert evidence.  This module is the only layer
that turns that evidence into executable filter topology.  It deliberately
does not evaluate planner-provided filter strings.  Instead it revalidates the
compiled transition receipt and every adjacency, then emits one of three
constant-shape primitives selected by the validated transition kind.

Per-segment decoding and normalization are delegated to
``sequence_render.build_sequence_render``.  The executor replaces only that
builder's final N-way concat node with an ordered binary chain.  Consequently
source-path binding, one seek input per segment occurrence, source color
conversion, A/V stream-origin handling, explicit silence, CFR geometry, and
48 kHz stereo normalization remain exactly the production sequence-render
contract rather than a second approximation of it.

The returned argv is suitable only for ``subprocess.run(argv, shell=False)``.
The filter graph is returned separately for a caller to write to the private
``filter_script_path`` already bound by the sequence renderer.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .sequence_plan import MAX_SAFE_INTEGER, compile_receipt_sha256
from .sequence_render import (
    SEQUENCE_RENDER_SCHEMA_VERSION,
    SequenceRenderError,
    build_sequence_render,
    validate_compiled_sequence,
)
from .transition_plan import (
    AUDIO_BEHAVIORS,
    MAX_SEGMENTS,
    MAX_TRANSITION_DURATION_MS,
    MIN_DIP_TO_BLACK_FRAMES,
    MIN_TRANSITION_FRAMES,
    MOTIVATIONS,
    TRANSITION_KINDS,
    TransitionPlanError,
    density_transition_limit,
    derive_boundary_id,
    transition_compile_receipt_sha256,
)


TRANSITION_RENDER_SCHEMA_VERSION = "autoeditor-transition-render/v1"
TRANSITION_RENDER_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-transition-render-receipt/v1"
)
MAX_WINDOWS_COMMAND_LINE_CHARACTERS = 32_767

_COMPILED_RESULT_KEYS = frozenset({
    "compiled_boundaries", "receipt", "receipt_sha256",
})
_COMPILED_BOUNDARY_KEYS = frozenset({
    "boundary_index",
    "boundary_id",
    "left_segment_id",
    "right_segment_id",
    "left_source_sha256",
    "right_source_sha256",
    "cumulative_boundary_ms",
    "output_boundary_ms",
    "kind",
    "motivation",
    "duration_ms",
    "duration_frames",
    "audio_behavior",
    "dialogue_crossing",
    "video_ffmpeg_primitive_tokens",
    "audio_ffmpeg_primitive_tokens",
})
_RECEIPT_KEYS = frozenset({
    "schema_version",
    "artifact_target",
    "sequence_plan_sha256",
    "sequence_compile_receipt_sha256",
    "source_manifest_sha256",
    "compiled_segments_sha256",
    "ordered_segment_ids",
    "segment_count",
    "source_duration_ms",
    "transition_plan_sha256",
    "transition_sequence_manifest_sha256",
    "transition_compile_receipt_sha256",
    "compiled_boundaries_sha256",
    "ordered_boundary_ids",
    "boundary_count",
    "non_hard_transition_count",
    "expected_output_duration_ms",
    "frame_rate",
    "topology_sha256",
    "filter_complex_sha256",
    "timing_receipt_sha256",
    "argv_sha256",
})
_FRAME_RATE_KEYS = frozenset({"numerator", "denominator"})

_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$", re.ASCII)
_BOUNDARY_ID = re.compile(r"^boundary-[0-9a-f]{64}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class TransitionRenderError(ValueError):
    """The compiled transition evidence or render binding is unsafe."""


def _fail(message: str) -> None:
    raise TransitionRenderError(message)


def _exact_dict(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys, key=str)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unsupported " + ", ".join(map(str, extra)))
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


def _identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(f"{label} has an invalid ASCII identifier")
    return value


def _digest(value: object, label: str) -> str:
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
        raise TransitionRenderError(f"{label} is not canonical JSON") from error


def _canonical_sha256(value: object, label: str) -> str:
    return hashlib.sha256(_canonical_json(value, label).encode("utf-8")).hexdigest()


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds // 1_000}.{milliseconds % 1_000:03d}"


def _frame_rate(value: object, label: str) -> dict[str, int]:
    raw = _exact_dict(value, _FRAME_RATE_KEYS, label)
    numerator = _integer(
        raw["numerator"], f"{label}.numerator", minimum=1, maximum=240_000
    )
    denominator = _integer(
        raw["denominator"], f"{label}.denominator", minimum=1, maximum=10_000
    )
    if math.gcd(numerator, denominator) != 1:
        _fail(f"{label} must be a reduced rational")
    if numerator < denominator or numerator > 240 * denominator:
        _fail(f"{label} must be from 1 to 240 frames per second")
    return {"numerator": numerator, "denominator": denominator}


def _duration_frames(duration_ms: int, frame_rate: dict[str, int]) -> int:
    numerator = duration_ms * frame_rate["numerator"]
    denominator = 1_000 * frame_rate["denominator"]
    return (2 * numerator + denominator) // (2 * denominator)


def _canonical_frame_duration_ms(frames: int, frame_rate: dict[str, int]) -> int:
    numerator = frames * 1_000 * frame_rate["denominator"]
    denominator = frame_rate["numerator"]
    return (2 * numerator + denominator) // (2 * denominator)


def _minimum_frame_ms(frame_rate: dict[str, int]) -> int:
    numerator = 1_000 * frame_rate["denominator"]
    return (numerator + frame_rate["numerator"] - 1) // frame_rate["numerator"]


def _artifact_path(value: object) -> str:
    if type(value) is not str or not value or len(value) > 32_767:
        _fail("transition render receipt.artifact_target must be a bounded path")
    if "\0" in value or any(ord(character) < 32 for character in value):
        _fail("transition render receipt.artifact_target contains a control character")
    if not os.path.isabs(value):
        _fail("transition render receipt.artifact_target must be absolute")
    normalized = os.path.normpath(value)
    if Path(normalized).suffix.lower() != ".mp4":
        _fail("transition render receipt.artifact_target must have an .mp4 suffix")
    return normalized


def _validate_compiled_transitions(
    value: object,
    sequence_receipt: dict[str, Any],
    segments: list[dict[str, Any]],
    output_frame_rate: dict[str, int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _exact_dict(value, _COMPILED_RESULT_KEYS, "compiled transition result")
    receipt = raw["receipt"]
    try:
        measured_receipt_hash = transition_compile_receipt_sha256(receipt)
    except TransitionPlanError as error:
        raise TransitionRenderError("transition compile receipt is invalid") from error
    supplied_receipt_hash = _digest(
        raw["receipt_sha256"], "compiled transition result.receipt_sha256"
    )
    if supplied_receipt_hash != measured_receipt_hash:
        _fail("transition compile receipt hash does not match")

    sequence_receipt_hash = compile_receipt_sha256(sequence_receipt)
    if receipt["sequence_plan_sha256"] != sequence_receipt["sequence_plan_sha256"]:
        _fail("transition receipt does not bind this sequence plan")
    if receipt["sequence_compile_receipt_sha256"] != sequence_receipt_hash:
        _fail("transition receipt does not bind this sequence compile receipt")
    if receipt["source_duration_ms"] != sequence_receipt["total_duration_ms"]:
        _fail("transition receipt source duration does not match the sequence")
    if receipt["frame_rate"] != output_frame_rate:
        _fail("transition receipt frame rate does not match render output")

    raw_boundaries = raw["compiled_boundaries"]
    expected_count = len(segments) - 1
    if type(raw_boundaries) is not list or len(raw_boundaries) != expected_count:
        _fail("compiled transitions must decide every sequence boundary")

    boundaries: list[dict[str, Any]] = []
    cumulative_source_ms = 0
    cumulative_overlap_ms = 0
    non_hard_count = 0
    minimum_frame_ms = _minimum_frame_ms(output_frame_rate)
    for index, value_boundary in enumerate(raw_boundaries):
        label = f"compiled transition result.compiled_boundaries[{index}]"
        item = _exact_dict(value_boundary, _COMPILED_BOUNDARY_KEYS, label)
        if _integer(item["boundary_index"], f"{label}.boundary_index",
                    maximum=MAX_SEGMENTS - 2) != index:
            _fail(f"{label}.boundary_index is not contiguous")

        left = segments[index]
        right = segments[index + 1]
        cumulative_source_ms += left["duration_ms"]
        expected_id = derive_boundary_id(
            left["segment_id"], right["segment_id"],
            left["source_sha256"], right["source_sha256"],
            cumulative_source_ms,
        )
        boundary_id = _identifier(
            item["boundary_id"], _BOUNDARY_ID, f"{label}.boundary_id"
        )
        if boundary_id != expected_id:
            _fail(f"{label}.boundary_id does not bind this exact adjacency")
        exact_bindings = {
            "left_segment_id": left["segment_id"],
            "right_segment_id": right["segment_id"],
            "left_source_sha256": left["source_sha256"],
            "right_source_sha256": right["source_sha256"],
            "cumulative_boundary_ms": cumulative_source_ms,
            "output_boundary_ms": cumulative_source_ms - cumulative_overlap_ms,
        }
        for key, expected in exact_bindings.items():
            if item[key] != expected:
                _fail(f"{label}.{key} does not match the exact sequence boundary")

        kind = item["kind"]
        if type(kind) is not str or kind not in TRANSITION_KINDS:
            _fail(f"{label}.kind is unsupported")
        motivation = item["motivation"]
        if type(motivation) is not str or motivation not in MOTIVATIONS:
            _fail(f"{label}.motivation is unsupported")
        duration = _integer(
            item["duration_ms"], f"{label}.duration_ms",
            maximum=MAX_TRANSITION_DURATION_MS,
        )
        duration_frames = _integer(
            item["duration_frames"], f"{label}.duration_frames",
            maximum=240,
        )
        audio_behavior = item["audio_behavior"]
        if type(audio_behavior) is not str or audio_behavior not in AUDIO_BEHAVIORS:
            _fail(f"{label}.audio_behavior is unsupported")
        if type(item["dialogue_crossing"]) is not bool:
            _fail(f"{label}.dialogue_crossing must be a boolean")

        expected_output_boundary_ms = cumulative_source_ms - cumulative_overlap_ms
        if kind == "hard_cut":
            if duration != 0 or duration_frames != 0 or audio_behavior != "hard_cut":
                _fail(f"{label} has inconsistent hard-cut primitives")
            video_primitive = "concat=n=2:v=1:a=0"
            audio_primitive = "concat=n=2:v=0:a=1"
        else:
            non_hard_count += 1
            measured_frames = _duration_frames(duration, output_frame_rate)
            if measured_frames < MIN_TRANSITION_FRAMES:
                _fail(f"{label}.duration_ms is shorter than two output frames")
            if _canonical_frame_duration_ms(measured_frames, output_frame_rate) != duration:
                _fail(f"{label}.duration_ms is not output-frame aligned")
            if duration_frames != measured_frames:
                _fail(f"{label}.duration_frames does not match duration_ms")
            if kind == "dip_to_black" and (
                duration_frames < MIN_DIP_TO_BLACK_FRAMES
                or duration_frames % 2 != 0
            ):
                _fail(f"{label} has an invalid dip-to-black frame window")
            if duration + minimum_frame_ms > left["duration_ms"] or (
                duration + minimum_frame_ms > right["duration_ms"]
            ):
                _fail(f"{label} does not leave one frame in each adjacent segment")
            if audio_behavior != "equal_power_crossfade":
                _fail(f"{label} timed transition must use equal-power audio")
            offset_ms = expected_output_boundary_ms - duration
            if offset_ms < 0:
                _fail(f"{label} transition offset would be negative")
            transition_name = "fade" if kind == "cross_dissolve" else "fadeblack"
            video_primitive = (
                f"xfade=transition={transition_name}:duration={_seconds(duration)}:"
                f"offset={_seconds(offset_ms)}"
            )
            audio_primitive = (
                f"acrossfade=d={_seconds(duration)}:o=1:c1=qsin:c2=qsin"
            )

        if item["video_ffmpeg_primitive_tokens"] != [video_primitive]:
            _fail(f"{label}.video_ffmpeg_primitive_tokens are not canonical")
        if item["audio_ffmpeg_primitive_tokens"] != [audio_primitive]:
            _fail(f"{label}.audio_ffmpeg_primitive_tokens are not canonical")

        normalized = {
            "boundary_index": index,
            "boundary_id": boundary_id,
            **exact_bindings,
            "kind": kind,
            "motivation": motivation,
            "duration_ms": duration,
            "duration_frames": duration_frames,
            "audio_behavior": audio_behavior,
            "dialogue_crossing": item["dialogue_crossing"],
            "video_ffmpeg_primitive_tokens": [video_primitive],
            "audio_ffmpeg_primitive_tokens": [audio_primitive],
        }
        boundaries.append(normalized)
        cumulative_overlap_ms += duration

    for segment_index in range(1, len(segments) - 1):
        incoming = boundaries[segment_index - 1]["duration_ms"]
        outgoing = boundaries[segment_index]["duration_ms"]
        if incoming + outgoing + minimum_frame_ms > segments[segment_index]["duration_ms"]:
            _fail("transition windows overlap inside an interior segment")

    compiled_hash = _canonical_sha256(boundaries, "compiled transition boundaries")
    if receipt["compiled_boundaries_sha256"] != compiled_hash:
        _fail("transition receipt compiled boundary hash does not match")
    ordered_ids = [item["boundary_id"] for item in boundaries]
    if receipt["ordered_boundary_ids"] != ordered_ids:
        _fail("transition receipt boundary order does not match")
    if receipt["boundary_count"] != expected_count:
        _fail("transition receipt boundary count does not match")
    if receipt["non_hard_transition_count"] != non_hard_count:
        _fail("transition receipt timed-transition count does not match")
    expected_motivation = (
        "motivated_only"
        if receipt["policy"]["usage"] == "hard_cut_only"
        else receipt["policy"]["usage"]
    )
    if any(item["motivation"] != expected_motivation for item in boundaries):
        _fail("compiled transition motivation does not match receipt policy")
    if non_hard_count > density_transition_limit(
        receipt["policy"]["density"], expected_count
    ):
        _fail("compiled timed-transition count exceeds receipt policy density")
    if receipt["policy"]["usage"] == "hard_cut_only" and non_hard_count:
        _fail("compiled timed transition violates hard-cut-only receipt policy")
    expected_duration = sequence_receipt["total_duration_ms"] - cumulative_overlap_ms
    if receipt["output_duration_ms"] != expected_duration:
        _fail("transition receipt output duration does not match its boundaries")
    return copy.deepcopy(receipt), copy.deepcopy(boundaries)


def validate_transition_render_receipt(value: object) -> dict[str, Any]:
    """Validate and detach a persisted executor receipt."""
    raw = _exact_dict(value, _RECEIPT_KEYS, "transition render receipt")
    if raw["schema_version"] != TRANSITION_RENDER_RECEIPT_SCHEMA_VERSION:
        _fail("transition render receipt schema_version is unsupported")
    hashes = {
        key: _digest(raw[key], f"transition render receipt.{key}")
        for key in (
            "sequence_plan_sha256",
            "sequence_compile_receipt_sha256",
            "source_manifest_sha256",
            "compiled_segments_sha256",
            "transition_plan_sha256",
            "transition_sequence_manifest_sha256",
            "transition_compile_receipt_sha256",
            "compiled_boundaries_sha256",
            "topology_sha256",
            "filter_complex_sha256",
            "timing_receipt_sha256",
            "argv_sha256",
        )
    }
    ordered_segments = raw["ordered_segment_ids"]
    if type(ordered_segments) is not list or not 1 <= len(ordered_segments) <= MAX_SEGMENTS:
        _fail("transition render receipt.ordered_segment_ids has invalid cardinality")
    segment_ids = [
        _identifier(value_id, _SEGMENT_ID,
                    f"transition render receipt.ordered_segment_ids[{index}]")
        for index, value_id in enumerate(ordered_segments)
    ]
    if len(set(segment_ids)) != len(segment_ids):
        _fail("transition render receipt segment ids must be unique")
    segment_count = _integer(
        raw["segment_count"], "transition render receipt.segment_count",
        minimum=1, maximum=MAX_SEGMENTS,
    )
    if segment_count != len(segment_ids):
        _fail("transition render receipt.segment_count does not match order")

    ordered_boundaries = raw["ordered_boundary_ids"]
    if type(ordered_boundaries) is not list or len(ordered_boundaries) != segment_count - 1:
        _fail("transition render receipt.ordered_boundary_ids has invalid cardinality")
    boundary_ids = [
        _identifier(value_id, _BOUNDARY_ID,
                    f"transition render receipt.ordered_boundary_ids[{index}]")
        for index, value_id in enumerate(ordered_boundaries)
    ]
    if len(set(boundary_ids)) != len(boundary_ids):
        _fail("transition render receipt boundary ids must be unique")
    boundary_count = _integer(
        raw["boundary_count"], "transition render receipt.boundary_count",
        maximum=MAX_SEGMENTS - 1,
    )
    if boundary_count != len(boundary_ids):
        _fail("transition render receipt.boundary_count does not match order")
    non_hard = _integer(
        raw["non_hard_transition_count"],
        "transition render receipt.non_hard_transition_count",
        maximum=boundary_count,
    )
    source_duration = _integer(
        raw["source_duration_ms"], "transition render receipt.source_duration_ms",
        minimum=1,
    )
    output_duration = _integer(
        raw["expected_output_duration_ms"],
        "transition render receipt.expected_output_duration_ms",
        minimum=1, maximum=source_duration,
    )
    return {
        "schema_version": TRANSITION_RENDER_RECEIPT_SCHEMA_VERSION,
        "artifact_target": _artifact_path(raw["artifact_target"]),
        **hashes,
        "ordered_segment_ids": segment_ids,
        "segment_count": segment_count,
        "source_duration_ms": source_duration,
        "ordered_boundary_ids": boundary_ids,
        "boundary_count": boundary_count,
        "non_hard_transition_count": non_hard,
        "expected_output_duration_ms": output_duration,
        "frame_rate": _frame_rate(
            raw["frame_rate"], "transition render receipt.frame_rate"
        ),
    }


def transition_render_receipt_sha256(value: object) -> str:
    """Return the canonical hash of a closed executor receipt."""
    return _canonical_sha256(
        validate_transition_render_receipt(value), "transition render receipt"
    )


def build_transition_render(
    compiled_sequence: object,
    source_paths: object,
    source_render_manifest: object,
    compiled_transition_result: object,
    output_path: str | os.PathLike[str],
    *,
    ffmpeg_path: str | os.PathLike[str] = "ffmpeg",
    synthesize_silence_for: object = (),
) -> dict[str, Any]:
    """Build a deterministic, shell-free render for every exact boundary."""
    try:
        sequence_receipt, segments = validate_compiled_sequence(compiled_sequence)
        base = build_sequence_render(
            compiled_sequence,
            source_paths,
            source_render_manifest,
            output_path,
            ffmpeg_path=ffmpeg_path,
            synthesize_silence_for=synthesize_silence_for,
        )
    except SequenceRenderError as error:
        raise TransitionRenderError(str(error)) from error

    manifest = source_render_manifest
    if type(manifest) is not dict or type(manifest.get("output")) is not dict:
        _fail("source render manifest output is invalid")
    output_fps = {
        "numerator": manifest["output"].get("fps_numerator"),
        "denominator": manifest["output"].get("fps_denominator"),
    }
    output_fps = _frame_rate(output_fps, "source render manifest output frame rate")
    transition_receipt, boundaries = _validate_compiled_transitions(
        compiled_transition_result, sequence_receipt, segments, output_fps
    )

    base_filters = base["filter_complex"].split(";")
    expected_concat = (
        "".join(
            f"[v{index:03d}][a{index:03d}]" for index in range(len(segments))
        )
        + f"concat=n={len(segments)}:v=1:a=1[vout][aout]"
    )
    if not base_filters or base_filters[-1] != expected_concat:
        _fail("sequence render topology is incompatible with transition execution")
    base_filters.pop()

    filter_script_identity = os.path.normcase(os.path.normpath(
        base["filter_script_path"]
    ))
    source_path_identities = {
        os.path.normcase(os.path.normpath(os.fspath(path)))
        for path in source_paths.values()
    }
    if filter_script_identity in source_path_identities:
        _fail("private filter script must not overwrite a source")
    if os.path.normcase(str(Path(base["filter_script_path"]).parent)) != (
        os.path.normcase(os.path.normpath(base["working_directory"]))
    ):
        _fail("private filter script must remain inside the render work directory")

    # xfade requires identical video time bases.  The production sequence
    # filters already normalize rate/geometry/color and every stream starts at
    # zero; these lightweight wrappers additionally place every occurrence on
    # an explicit execution time base.  Accumulators are normalized again
    # after each binary primitive because concat selects its own output base.
    for index in range(len(segments)):
        base_filters.extend([
            f"[v{index:03d}]settb=AVTB,setpts=PTS-STARTPTS[vn{index:03d}]",
            (
                f"[a{index:03d}]asettb=1/48000,"
                f"asetpts=PTS-STARTPTS[an{index:03d}]"
            ),
        ])

    topology: list[dict[str, Any]] = []
    if not boundaries:
        base_filters.extend(["[vn000]null[vout]", "[an000]anull[aout]"])
    else:
        left_video = "vn000"
        left_audio = "an000"
        cumulative_output_ms = segments[0]["duration_ms"]
        for index, boundary in enumerate(boundaries):
            right_video = f"vn{index + 1:03d}"
            right_audio = f"an{index + 1:03d}"
            raw_video = f"vraw{index:03d}"
            raw_audio = f"araw{index:03d}"
            output_video = f"vtr{index:03d}"
            output_audio = f"atr{index:03d}"
            if boundary["kind"] == "hard_cut":
                video_primitive = "concat=n=2:v=1:a=0"
                audio_primitive = "concat=n=2:v=0:a=1"
            else:
                offset_ms = boundary["output_boundary_ms"] - boundary["duration_ms"]
                transition_name = (
                    "fade" if boundary["kind"] == "cross_dissolve" else "fadeblack"
                )
                video_primitive = (
                    f"xfade=transition={transition_name}:"
                    f"duration={_seconds(boundary['duration_ms'])}:"
                    f"offset={_seconds(offset_ms)}"
                )
                audio_primitive = (
                    f"acrossfade=d={_seconds(boundary['duration_ms'])}:"
                    "o=1:c1=qsin:c2=qsin"
                )
            base_filters.append(
                f"[{left_video}][{right_video}]{video_primitive}[{raw_video}]"
            )
            base_filters.append(
                f"[{left_audio}][{right_audio}]{audio_primitive}[{raw_audio}]"
            )
            base_filters.extend([
                (
                    f"[{raw_video}]settb=AVTB,"
                    f"setpts=PTS-STARTPTS[{output_video}]"
                ),
                (
                    f"[{raw_audio}]asettb=1/48000,"
                    f"asetpts=PTS-STARTPTS[{output_audio}]"
                ),
            ])
            cumulative_output_ms += (
                segments[index + 1]["duration_ms"] - boundary["duration_ms"]
            )
            topology.append({
                "boundary_index": index,
                "boundary_id": boundary["boundary_id"],
                "left_node": (
                    f"segment:{segments[0]['segment_id']}"
                    if index == 0 else f"boundary:{boundaries[index - 1]['boundary_id']}"
                ),
                "right_segment_id": segments[index + 1]["segment_id"],
                "kind": boundary["kind"],
                "duration_ms": boundary["duration_ms"],
                "output_boundary_ms": boundary["output_boundary_ms"],
                "video_primitive": video_primitive,
                "audio_primitive": audio_primitive,
                "output_duration_ms": cumulative_output_ms,
            })
            left_video = output_video
            left_audio = output_audio
        base_filters.extend([
            f"[{left_video}]null[vout]",
            f"[{left_audio}]anull[aout]",
        ])

    filter_complex = ";".join(base_filters)
    expected_duration = transition_receipt["output_duration_ms"]
    argv = list(base["argv"])
    delivery_t_positions = [
        index for index, token in enumerate(argv[:-1]) if token == "-t"
    ]
    if not delivery_t_positions:
        _fail("sequence render argv does not bind an output duration")
    delivery_t_index = delivery_t_positions[-1]
    if argv[delivery_t_index + 1] != _seconds(sequence_receipt["total_duration_ms"]):
        _fail("sequence render argv output duration is not canonical")
    argv[delivery_t_index + 1] = _seconds(expected_duration)
    if len(subprocess.list2cmdline(argv)) + 1 > MAX_WINDOWS_COMMAND_LINE_CHARACTERS:
        _fail("transition render argv exceeds the Windows command-line bound")

    topology_hash = _canonical_sha256(topology, "transition render topology")
    transition_receipt_hash = transition_compile_receipt_sha256(transition_receipt)
    executor_receipt = {
        "schema_version": TRANSITION_RENDER_RECEIPT_SCHEMA_VERSION,
        "artifact_target": base["output_path"],
        "sequence_plan_sha256": sequence_receipt["sequence_plan_sha256"],
        "sequence_compile_receipt_sha256": compile_receipt_sha256(sequence_receipt),
        "source_manifest_sha256": sequence_receipt["source_manifest_sha256"],
        "compiled_segments_sha256": sequence_receipt["compiled_segments_sha256"],
        "ordered_segment_ids": list(sequence_receipt["ordered_segment_ids"]),
        "segment_count": len(segments),
        "source_duration_ms": sequence_receipt["total_duration_ms"],
        "transition_plan_sha256": transition_receipt["transition_plan_sha256"],
        "transition_sequence_manifest_sha256": (
            transition_receipt["sequence_manifest_sha256"]
        ),
        "transition_compile_receipt_sha256": transition_receipt_hash,
        "compiled_boundaries_sha256": transition_receipt["compiled_boundaries_sha256"],
        "ordered_boundary_ids": list(transition_receipt["ordered_boundary_ids"]),
        "boundary_count": len(boundaries),
        "non_hard_transition_count": transition_receipt[
            "non_hard_transition_count"
        ],
        "expected_output_duration_ms": expected_duration,
        "frame_rate": output_fps,
        "topology_sha256": topology_hash,
        "filter_complex_sha256": hashlib.sha256(
            filter_complex.encode("utf-8")
        ).hexdigest(),
        "timing_receipt_sha256": base["timing_receipt_sha256"],
        "argv_sha256": _canonical_sha256(argv, "transition render argv"),
    }
    executor_receipt = validate_transition_render_receipt(executor_receipt)
    return {
        "schema_version": TRANSITION_RENDER_SCHEMA_VERSION,
        "argv": argv,
        "filter_complex": filter_complex,
        "source_input_order": list(base["source_input_order"]),
        "working_directory": base["working_directory"],
        "filter_script_path": base["filter_script_path"],
        "ordered_segment_ids": list(sequence_receipt["ordered_segment_ids"]),
        "ordered_boundary_ids": list(transition_receipt["ordered_boundary_ids"]),
        "segment_count": len(segments),
        "boundary_count": len(boundaries),
        "expected_output_duration_ms": expected_duration,
        "output_path": base["output_path"],
        "timing_receipt": copy.deepcopy(base["timing_receipt"]),
        "timing_receipt_sha256": base["timing_receipt_sha256"],
        "transition_compile_receipt": copy.deepcopy(transition_receipt),
        "transition_compile_receipt_sha256": transition_receipt_hash,
        "topology": copy.deepcopy(topology),
        "topology_sha256": topology_hash,
        "executor_receipt": copy.deepcopy(executor_receipt),
        "executor_receipt_sha256": transition_render_receipt_sha256(
            executor_receipt
        ),
    }


def build_transition_render_argv(*args: Any, **kwargs: Any) -> list[str]:
    """Convenience wrapper returning only the trusted argv token list."""
    return build_transition_render(*args, **kwargs)["argv"]
