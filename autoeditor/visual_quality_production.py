"""Production bridge for bounded deterministic visual-quality evidence.

The analyzer in :mod:`autoeditor.visual_quality_deterministic` deliberately
accepts bytes, not paths or decoders.  This module owns the narrower trusted
production boundary: it probes an exact quarantined artifact, decodes a fixed
set of zero-based frames with an identified FFmpeg binary, builds closed
decoder/timeline receipts, and persists the analyzer result before promotion.

No semantic, OCR, identity, narrative, or aesthetic claim is made here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from .visual_quality_deterministic import (
    MAX_DECODED_BYTES,
    MAX_FRAMES,
    VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION,
    VisualQualityDeterministicError,
    analyze_visual_quality_deterministic,
    verify_visual_quality_deterministic_result,
)


PRODUCTION_VISUAL_QA_SCHEMA_VERSION = (
    "autoeditor-production-deterministic-visual-qa/v1"
)
PRODUCTION_VISUAL_INTENT_SCHEMA_VERSION = (
    "autoeditor-production-visual-timeline-intent/v1"
)
RGB24_DECODER_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-ffmpeg-rgb24-decoder-receipt/v1"
)
DECODED_TIMELINE_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-decoded-frame-timeline-receipt/v1"
)
PRODUCTION_VISUAL_QA_FILE = "DETERMINISTIC_VISUAL_QA.json"

_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_MAX_SIDECAR_BYTES = 4 * 1024 * 1024
_MAX_SOURCE_FRAMES = 20_000_000
_MAX_DURATION_MS = 86_400_000
_NON_BLANK_SAMPLES = 12
_TEMPORAL_WINDOWS = 3
_TEMPORAL_WINDOW_FRAMES = 9
_DECODE_MAX_WIDTH = 640
_DECODE_MAX_HEIGHT = 360
_FFPROBE_TIMEOUT_SECONDS = 30
_FFMPEG_TIMEOUT_SECONDS = 900

_INTENT_KEYS = frozenset({
    "schema_version", "intentional_dark_intervals_ms", "transitions",
    "transition_receipt_sha256",
})
_DARK_INTERVAL_KEYS = frozenset({"start_ms", "end_ms"})
_TRANSITION_KEYS = frozenset({
    "boundary_index", "kind", "output_start_ms", "output_end_ms",
    "overlap_ms",
})
_SUPPORTED_TRANSITIONS = frozenset({"cross_dissolve", "dip_to_black"})
_TRANSITION_KINDS = frozenset({"hard_cut", *_SUPPORTED_TRANSITIONS})

_RECORD_KEYS = frozenset({
    "schema_version", "artifact", "runtime", "intent", "intent_sha256",
    "decoder_receipt", "decoder_receipt_sha256", "timeline_receipt",
    "timeline_receipt_sha256", "analysis", "coverage", "pass",
})
_ARTIFACT_KEYS = frozenset({"sha256", "bytes"})
_RUNTIME_KEYS = frozenset({"offline", "ffmpeg", "ffprobe"})
_TOOL_KEYS = frozenset({"sha256", "bytes"})
_DECODER_KEYS = frozenset({
    "schema_version", "artifact_sha256", "artifact_bytes", "ffmpeg_sha256",
    "source_geometry", "decoded_geometry", "frame_rate",
    "source_frame_count", "source_duration_ms", "filter", "frames",
})
_GEOMETRY_KEYS = frozenset({"width", "height", "pixel_format"})
_FRAME_RATE_KEYS = frozenset({"numerator", "denominator"})
_FILTER_KEYS = frozenset({
    "selection", "scale_width", "scale_height", "scale_flags",
    "pixel_format", "fps_mode",
})
_FRAME_KEYS = frozenset({
    "frame_id", "frame_index", "timestamp_us", "rgb24_sha256", "bytes",
})
_TIMELINE_KEYS = frozenset({
    "schema_version", "artifact_sha256", "decoder_receipt_sha256",
    "intent_sha256", "frame_rate", "frames", "check_plan",
    "check_plan_sha256",
})
_COVERAGE_KEYS = frozenset({
    "artifact_frame_count", "decoded_frame_count", "non_blank_sample_count",
    "temporal_window_count", "declared_transition_count",
    "analyzed_transition_count",
})


class ProductionVisualQualityError(RuntimeError):
    """A production decoder, binding, or persisted receipt was invalid."""


def _fail(message: str) -> None:
    raise ProductionVisualQualityError(message)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ProductionVisualQualityError(
            "production visual evidence is not canonical JSON"
        ) from error


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _exact_dict(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict or frozenset(value) != keys:
        _fail(f"{label} does not match its closed schema")
    return value


def _stable_file_identity(path: Path, label: str) -> dict[str, Any]:
    try:
        resolved = Path(path).resolve(strict=True)
        before = resolved.stat()
        if not resolved.is_file() or before.st_size < 1:
            _fail(f"{label} is not a non-empty regular file")
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            descriptor = os.fstat(handle.fileno())
        after = resolved.stat()
    except (OSError, RuntimeError) as error:
        if isinstance(error, ProductionVisualQualityError):
            raise
        raise ProductionVisualQualityError(f"{label} could not be read") from error
    identity_fields = (
        before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino,
    )
    if identity_fields != (
        descriptor.st_size, descriptor.st_mtime_ns,
        descriptor.st_dev, descriptor.st_ino,
    ) or identity_fields != (
        after.st_size, after.st_mtime_ns, after.st_dev, after.st_ino,
    ):
        _fail(f"{label} changed while it was hashed")
    return {
        "path": resolved,
        "sha256": digest.hexdigest(),
        "bytes": before.st_size,
        "stat": identity_fields,
    }


def _same_file_identity(left: Mapping[str, Any], right: Mapping[str, Any],
                        label: str) -> None:
    if any(left[key] != right[key] for key in ("sha256", "bytes", "stat")):
        _fail(f"{label} changed while deterministic visual QA ran")


def _subprocess_kwargs() -> dict[str, Any]:
    result: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": False,
        "shell": False,
    }
    if os.name == "nt":
        result["creationflags"] = subprocess.CREATE_NO_WINDOW
    return result


def _run(argv: Sequence[object], *, timeout: int, label: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            [str(item) for item in argv], timeout=timeout, **_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ProductionVisualQualityError(f"{label} did not complete") from error
    if result.returncode != 0:
        _fail(f"{label} failed")
    return result


def _rational(value: object, label: str) -> dict[str, int]:
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", value):
        _fail(f"{label} is not a positive rational")
    numerator_text, denominator_text = value.split("/", 1)
    fraction = Fraction(int(numerator_text), int(denominator_text))
    if fraction < 1 or fraction > 240:
        _fail(f"{label} is outside the supported frame-rate range")
    return {"numerator": fraction.numerator, "denominator": fraction.denominator}


def _probe_artifact(artifact: Mapping[str, Any], ffprobe: Mapping[str, Any]) -> dict:
    result = _run([
        ffprobe["path"], "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames:format=duration,size",
        "-of", "json", artifact["path"],
    ], timeout=_FFPROBE_TIMEOUT_SECONDS, label="deterministic visual ffprobe")
    try:
        report = json.loads(result.stdout.decode("utf-8", errors="strict"))
        if type(report) is not dict:
            _fail("deterministic visual ffprobe returned an open schema")
        # FFprobe 8 adds empty top-level collection names even when
        # ``-show_entries`` requests only streams and format.  Accept those
        # exact empty containers, but no content and no other open fields.
        for optional in ("programs", "stream_groups"):
            if optional in report and report.pop(optional) != []:
                _fail("deterministic visual ffprobe returned unexpected groups")
        if set(report) != {"streams", "format"}:
            _fail("deterministic visual ffprobe returned an open schema")
        streams = report["streams"]
        if type(streams) is not list or len(streams) != 1:
            _fail("deterministic visual artifact lacks exactly one selected video stream")
        stream = streams[0]
        if type(stream) is not dict:
            _fail("deterministic visual stream metadata is invalid")
        width = int(stream["width"])
        height = int(stream["height"])
        source_frames = int(stream["nb_frames"])
        duration_seconds = float(report["format"]["duration"])
        reported_bytes = int(report["format"]["size"])
        rate = _rational(stream["r_frame_rate"], "artifact r_frame_rate")
        average = _rational(stream["avg_frame_rate"], "artifact avg_frame_rate")
        pixel_format = str(stream["pix_fmt"])
    except (KeyError, TypeError, ValueError, UnicodeError,
            json.JSONDecodeError, OverflowError) as error:
        if isinstance(error, ProductionVisualQualityError):
            raise
        raise ProductionVisualQualityError(
            "deterministic visual stream metadata is invalid"
        ) from error
    if rate != average:
        _fail("deterministic visual QA requires an exact CFR artifact")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        _fail("deterministic visual artifact duration is invalid")
    duration_ms = round(duration_seconds * 1000)
    if not 1 <= duration_ms <= _MAX_DURATION_MS:
        _fail("deterministic visual artifact duration is outside bounds")
    if not 16 <= width <= 4096 or not 16 <= height <= 4096:
        _fail("deterministic visual artifact geometry is outside bounds")
    if width * height > 3840 * 2160:
        _fail("deterministic visual artifact pixel count is outside bounds")
    if not 1 <= source_frames <= _MAX_SOURCE_FRAMES:
        _fail("deterministic visual artifact frame count is outside bounds")
    if reported_bytes != artifact["bytes"]:
        _fail("ffprobe artifact size does not match the stable file identity")
    expected_duration_ms = round(
        source_frames * 1000 * rate["denominator"] / rate["numerator"]
    )
    frame_ms = 1000 * rate["denominator"] / rate["numerator"]
    if abs(expected_duration_ms - duration_ms) > max(100, math.ceil(frame_ms * 2)):
        _fail("artifact duration does not match its CFR frame count")
    return {
        "width": width,
        "height": height,
        "pixel_format": pixel_format,
        "frame_rate": rate,
        "frame_count": source_frames,
        "duration_ms": duration_ms,
    }


def _validate_intent(value: object, duration_ms: int) -> dict[str, Any]:
    raw = _exact_dict(value, _INTENT_KEYS, "production visual intent")
    if raw["schema_version"] != PRODUCTION_VISUAL_INTENT_SCHEMA_VERSION:
        _fail("production visual intent schema is unsupported")
    intervals_raw = raw["intentional_dark_intervals_ms"]
    if type(intervals_raw) is not list or len(intervals_raw) > 128:
        _fail("production visual dark intervals are outside bounds")
    intervals = []
    previous_start = -1
    for index, value_interval in enumerate(intervals_raw):
        item = _exact_dict(
            value_interval, _DARK_INTERVAL_KEYS,
            f"production visual dark interval {index}",
        )
        start = _integer(item["start_ms"], "dark interval start", 0, duration_ms)
        end = _integer(item["end_ms"], "dark interval end", 1, duration_ms)
        if end <= start or start < previous_start:
            _fail("production visual dark intervals are not ordered ranges")
        intervals.append({"start_ms": start, "end_ms": end})
        previous_start = start

    transitions_raw = raw["transitions"]
    if type(transitions_raw) is not list or len(transitions_raw) > 128:
        _fail("production visual transitions are outside bounds")
    transitions = []
    previous_index = -1
    previous_start = -1
    for position, value_transition in enumerate(transitions_raw):
        item = _exact_dict(
            value_transition, _TRANSITION_KEYS,
            f"production visual transition {position}",
        )
        boundary_index = _integer(
            item["boundary_index"], "transition boundary_index", 0, 127,
        )
        kind = item["kind"]
        if type(kind) is not str or kind not in _TRANSITION_KINDS:
            _fail("production visual transition kind is unsupported")
        start = _integer(item["output_start_ms"], "transition start", 0, duration_ms)
        end = _integer(item["output_end_ms"], "transition end", 0, duration_ms)
        overlap = _integer(item["overlap_ms"], "transition overlap", 0, duration_ms)
        if boundary_index <= previous_index or start < previous_start:
            _fail("production visual transitions are not ordered")
        if kind == "hard_cut":
            if start != end or overlap != 0:
                _fail("hard-cut visual intent has an invalid interval")
        elif end <= start or overlap != end - start:
            _fail("non-hard visual intent has an invalid overlap interval")
        transitions.append({
            "boundary_index": boundary_index,
            "kind": kind,
            "output_start_ms": start,
            "output_end_ms": end,
            "overlap_ms": overlap,
        })
        previous_index = boundary_index
        previous_start = start
    supported = [item for item in transitions if item["kind"] in _SUPPORTED_TRANSITIONS]
    digest = raw["transition_receipt_sha256"]
    if supported:
        digest = _digest(digest, "production visual transition receipt")
    elif digest is not None:
        _fail("transition receipt digest must be null without supported transitions")
    return {
        "schema_version": PRODUCTION_VISUAL_INTENT_SCHEMA_VERSION,
        "intentional_dark_intervals_ms": intervals,
        "transitions": transitions,
        "transition_receipt_sha256": digest,
    }


def build_production_visual_intent(
    *, intentional_dark_intervals_ms: Sequence[Mapping[str, int]] = (),
    transitions: Sequence[Mapping[str, Any]] = (),
    transition_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the closed intent object consumed by the production decoder."""
    return {
        "schema_version": PRODUCTION_VISUAL_INTENT_SCHEMA_VERSION,
        "intentional_dark_intervals_ms": [dict(item) for item in intentional_dark_intervals_ms],
        "transitions": [dict(item) for item in transitions],
        "transition_receipt_sha256": transition_receipt_sha256,
    }


def _decode_geometry(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, _DECODE_MAX_WIDTH / width, _DECODE_MAX_HEIGHT / height)
    if scale == 1.0:
        return width, height
    decoded_width = max(16, int(width * scale) // 2 * 2)
    decoded_height = max(16, int(height * scale) // 2 * 2)
    return decoded_width, decoded_height


def _frame_timestamp_us(index: int, rate: Mapping[str, int]) -> int:
    numerator = index * rate["denominator"] * 1_000_000
    return (numerator + rate["numerator"] // 2) // rate["numerator"]


def _index_is_excluded(index: int, intervals: Sequence[tuple[int, int]],
                       rate: Mapping[str, int]) -> bool:
    timestamp_ms = (_frame_timestamp_us(index, rate) + 500) // 1000
    return any(start <= timestamp_ms <= end for start, end in intervals)


def _sample_plan(media: Mapping[str, Any], intent: Mapping[str, Any]) -> dict[str, Any]:
    rate = media["frame_rate"]
    frame_count = media["frame_count"]
    supported = [
        item for item in intent["transitions"]
        if item["kind"] in _SUPPORTED_TRANSITIONS
    ]
    one_frame_ms = math.ceil(1000 * rate["denominator"] / rate["numerator"])
    excluded = [
        (item["start_ms"], item["end_ms"])
        for item in intent["intentional_dark_intervals_ms"]
    ]
    excluded.extend(
        (max(0, item["output_start_ms"] - one_frame_ms),
         min(media["duration_ms"], item["output_end_ms"] + one_frame_ms))
        for item in supported
    )

    sample_indices: list[int] = []
    for position in range(_NON_BLANK_SAMPLES * 3):
        fraction = (position + 1) / (_NON_BLANK_SAMPLES * 3 + 1)
        index = min(frame_count - 1, max(0, round((frame_count - 1) * fraction)))
        if index not in sample_indices and not _index_is_excluded(index, excluded, rate):
            sample_indices.append(index)
        if len(sample_indices) == _NON_BLANK_SAMPLES:
            break
    required_samples = min(3, frame_count)
    if len(sample_indices) < required_samples:
        _fail("trusted timeline intent leaves too few non-blank frame probes")

    temporal_windows: list[list[int]] = []
    half = _TEMPORAL_WINDOW_FRAMES // 2
    for position in range(_TEMPORAL_WINDOWS * 5):
        fraction = (position + 1) / (_TEMPORAL_WINDOWS * 5 + 1)
        center = round((frame_count - 1) * fraction)
        start = min(max(0, center - half), max(0, frame_count - _TEMPORAL_WINDOW_FRAMES))
        window = list(range(start, min(frame_count, start + _TEMPORAL_WINDOW_FRAMES)))
        if len(window) != _TEMPORAL_WINDOW_FRAMES:
            continue
        if any(_index_is_excluded(index, excluded, rate) for index in window):
            continue
        if window not in temporal_windows:
            temporal_windows.append(window)
        if len(temporal_windows) == _TEMPORAL_WINDOWS:
            break

    # A final-artifact before/middle/after triple is insufficient to prove a
    # cross-dissolve when either source is moving: the midpoint is not a linear
    # blend of the two temporally different endpoint frames.  The analyzer can
    # verify transitions when exact component-frame receipts are supplied, but
    # this production bridge does not have those bytes.  Keep the declared
    # transition count in coverage and deliberately emit no pixel-transition
    # check instead of creating false failures or false assurance.
    transition_frames: list[dict[str, Any]] = []

    all_indices = sorted({
        *sample_indices,
        *(index for window in temporal_windows for index in window),
        *(index for item in transition_frames for index in item["indices"]),
    })
    if len(all_indices) > MAX_FRAMES:
        _fail("deterministic production sample plan exceeds its frame bound")
    return {
        "indices": all_indices,
        "non_blank": sample_indices,
        "temporal_windows": temporal_windows,
        "transitions": transition_frames,
        "declared_transition_count": len(supported),
    }


def _decode_frames(artifact: Mapping[str, Any], ffmpeg: Mapping[str, Any],
                   media: Mapping[str, Any], indices: Sequence[int]) -> tuple[
                       dict[str, bytes], list[dict[str, Any]], dict[str, int]]:
    decoded_width, decoded_height = _decode_geometry(media["width"], media["height"])
    frame_bytes = decoded_width * decoded_height * 3
    expected_bytes = frame_bytes * len(indices)
    if expected_bytes > MAX_DECODED_BYTES:
        _fail("deterministic production decode exceeds its byte budget")
    selection = "+".join(f"eq(n\\,{index})" for index in indices)
    filter_graph = (
        f"select='{selection}',"
        f"scale={decoded_width}:{decoded_height}:flags=bilinear,format=rgb24"
    )
    result = _run([
        ffmpeg["path"], "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", artifact["path"], "-map", "0:v:0", "-vf", filter_graph,
        "-fps_mode", "passthrough", "-an", "-sn", "-dn",
        "-f", "rawvideo", "pipe:1",
    ], timeout=_FFMPEG_TIMEOUT_SECONDS, label="deterministic visual rgb24 decode")
    if len(result.stdout) != expected_bytes:
        _fail("deterministic visual decoder returned incomplete or extra frames")
    decoded: dict[str, bytes] = {}
    frames = []
    rate = media["frame_rate"]
    for position, index in enumerate(indices):
        frame_id = f"frame-{index:08d}"
        payload = bytes(result.stdout[position * frame_bytes:(position + 1) * frame_bytes])
        digest = hashlib.sha256(payload).hexdigest()
        decoded[frame_id] = payload
        frames.append({
            "frame_id": frame_id,
            "frame_index": index,
            "timestamp_us": _frame_timestamp_us(index, rate),
            "rgb24_sha256": digest,
            "bytes": frame_bytes,
        })
    return decoded, frames, {
        "width": decoded_width, "height": decoded_height,
        "pixel_format": "rgb24",
    }


def _checks(plan: Mapping[str, Any],
            frame_ids: Mapping[int, str]) -> dict[str, list[dict[str, Any]]]:
    frame_state = [{
        "check_id": f"non-blank-{position:03d}",
        "frame_id": frame_ids[index],
        "expected_state": "non_blank_content",
    } for position, index in enumerate(plan["non_blank"])]
    temporal = [{
        "check_id": f"technical-window-{position:03d}",
        "frame_ids": [frame_ids[index] for index in window],
        "expected_state": "observe",
    } for position, window in enumerate(plan["temporal_windows"])]
    return {
        "frame_state": frame_state,
        "temporal_window": temporal,
        "geometry": [],
        "overlay": [],
        "transition": [],
    }


def _validate_record(value: object, expected_artifact: Mapping[str, Any] | None,
                     *, require_pass: bool) -> dict[str, Any]:
    record = _exact_dict(value, _RECORD_KEYS, "production visual QA record")
    if record["schema_version"] != PRODUCTION_VISUAL_QA_SCHEMA_VERSION:
        _fail("production visual QA record schema is unsupported")
    artifact = _exact_dict(record["artifact"], _ARTIFACT_KEYS, "visual QA artifact")
    _digest(artifact["sha256"], "visual QA artifact sha256")
    _integer(artifact["bytes"], "visual QA artifact bytes", 1, 2**63 - 1)
    if expected_artifact is not None and any(
        artifact[key] != expected_artifact[key] for key in ("sha256", "bytes")
    ):
        _fail("production visual QA does not bind the expected artifact")
    runtime = _exact_dict(record["runtime"], _RUNTIME_KEYS, "visual QA runtime")
    if runtime["offline"] is not True:
        _fail("production visual QA runtime is not offline")
    for name in ("ffmpeg", "ffprobe"):
        tool = _exact_dict(runtime[name], _TOOL_KEYS, f"visual QA {name}")
        _digest(tool["sha256"], f"visual QA {name} sha256")
        _integer(tool["bytes"], f"visual QA {name} bytes", 1, 2**63 - 1)
    decoder = _exact_dict(
        record["decoder_receipt"], _DECODER_KEYS, "visual QA decoder receipt",
    )
    decoder_sha256 = _digest(
        record["decoder_receipt_sha256"], "visual QA decoder receipt sha256",
    )
    if decoder_sha256 != _canonical_sha256(decoder):
        _fail("production visual QA decoder receipt hash does not match")
    if (decoder["schema_version"] != RGB24_DECODER_RECEIPT_SCHEMA_VERSION
            or decoder["artifact_sha256"] != artifact["sha256"]
            or decoder["artifact_bytes"] != artifact["bytes"]
            or decoder["ffmpeg_sha256"] != runtime["ffmpeg"]["sha256"]):
        _fail("production visual QA decoder receipt binding drifted")
    source_geometry = _exact_dict(
        decoder["source_geometry"], _GEOMETRY_KEYS, "decoder source geometry",
    )
    decoded_geometry = _exact_dict(
        decoder["decoded_geometry"], _GEOMETRY_KEYS, "decoder output geometry",
    )
    if decoded_geometry["pixel_format"] != "rgb24":
        _fail("production visual QA decoder output is not rgb24")
    for geometry in (source_geometry, decoded_geometry):
        _integer(geometry["width"], "decoder geometry width", 16, 4096)
        _integer(geometry["height"], "decoder geometry height", 16, 4096)
        if type(geometry["pixel_format"]) is not str or not geometry["pixel_format"]:
            _fail("decoder geometry pixel format is invalid")
    rate = _exact_dict(decoder["frame_rate"], _FRAME_RATE_KEYS, "decoder frame rate")
    numerator = _integer(rate["numerator"], "decoder fps numerator", 1, 240_000)
    denominator = _integer(rate["denominator"], "decoder fps denominator", 1, 10_000)
    if math.gcd(numerator, denominator) != 1:
        _fail("decoder frame rate is not reduced")
    source_count = _integer(
        decoder["source_frame_count"], "decoder source frame count",
        1, _MAX_SOURCE_FRAMES,
    )
    source_duration_ms = _integer(
        decoder["source_duration_ms"], "decoder source duration",
        1, _MAX_DURATION_MS,
    )
    expected_duration_ms = round(
        source_count * 1000 * denominator / numerator
    )
    if abs(source_duration_ms - expected_duration_ms) > max(
        100, math.ceil(2000 * denominator / numerator),
    ):
        _fail("decoder source duration does not match its CFR frame count")
    intent = _validate_intent(record["intent"], source_duration_ms)
    intent_sha256 = _digest(record["intent_sha256"], "visual QA intent sha256")
    if intent_sha256 != _canonical_sha256(intent):
        _fail("production visual QA intent hash does not match")
    filter_receipt = _exact_dict(decoder["filter"], _FILTER_KEYS, "decoder filter")
    if filter_receipt != {
        "selection": "zero_based_frame_index",
        "scale_width": decoded_geometry["width"],
        "scale_height": decoded_geometry["height"],
        "scale_flags": "bilinear",
        "pixel_format": "rgb24",
        "fps_mode": "passthrough",
    }:
        _fail("production visual QA decoder filter contract drifted")
    frames = decoder["frames"]
    if type(frames) is not list or not 1 <= len(frames) <= MAX_FRAMES:
        _fail("production visual QA decoder frame list is outside bounds")
    previous_index = -1
    expected_frame_bytes = decoded_geometry["width"] * decoded_geometry["height"] * 3
    for position, value_frame in enumerate(frames):
        frame = _exact_dict(value_frame, _FRAME_KEYS, f"decoder frame {position}")
        index = _integer(frame["frame_index"], "decoder frame index", 0, source_count - 1)
        if index <= previous_index or frame["frame_id"] != f"frame-{index:08d}":
            _fail("production visual QA decoder frames are not canonically ordered")
        if frame["timestamp_us"] != _frame_timestamp_us(index, rate):
            _fail("production visual QA decoder frame clock drifted")
        _digest(frame["rgb24_sha256"], "decoder frame sha256")
        if frame["bytes"] != expected_frame_bytes:
            _fail("production visual QA decoder frame byte count drifted")
        previous_index = index

    timeline = _exact_dict(
        record["timeline_receipt"], _TIMELINE_KEYS, "visual QA timeline receipt",
    )
    timeline_sha256 = _digest(
        record["timeline_receipt_sha256"], "visual QA timeline receipt sha256",
    )
    if timeline_sha256 != _canonical_sha256(timeline):
        _fail("production visual QA timeline receipt hash does not match")
    timeline_frames = [{key: frame[key] for key in (
        "frame_id", "frame_index", "timestamp_us", "rgb24_sha256",
    )} for frame in frames]
    if (timeline["schema_version"] != DECODED_TIMELINE_RECEIPT_SCHEMA_VERSION
            or timeline["artifact_sha256"] != artifact["sha256"]
            or timeline["decoder_receipt_sha256"] != decoder_sha256
            or timeline["intent_sha256"] != intent_sha256
            or timeline["frame_rate"] != rate
            or timeline["frames"] != timeline_frames):
        _fail("production visual QA timeline receipt binding drifted")
    check_plan = timeline["check_plan"]
    if (type(check_plan) is not dict
            or set(check_plan) != {
                "frame_state", "temporal_window", "geometry", "overlay",
                "transition",
            }
            or any(type(check_plan[name]) is not list for name in check_plan)
            or check_plan["geometry"] != [] or check_plan["overlay"] != []):
        _fail("production visual QA check plan is outside its bounded scope")
    check_plan_sha256 = _digest(
        timeline["check_plan_sha256"], "visual QA check plan sha256",
    )
    if check_plan_sha256 != _canonical_sha256(check_plan):
        _fail("production visual QA check plan hash does not match")

    analysis = record["analysis"]
    try:
        receipt = verify_visual_quality_deterministic_result(analysis)
    except VisualQualityDeterministicError as error:
        raise ProductionVisualQualityError(
            "production visual analyzer receipt is invalid"
        ) from error
    binding = receipt["binding"]
    measured_plan = {
        "frame_state": [{key: item[key] for key in (
            "check_id", "frame_id", "expected_state",
        )} for item in receipt["checks"]["frame_state"]],
        "temporal_window": [{key: item[key] for key in (
            "check_id", "frame_ids", "expected_state",
        )} for item in receipt["checks"]["temporal_window"]],
        "geometry": [],
        "overlay": [],
        "transition": [{
            "check_id": item["check_id"],
            "transition_kind": item["transition_kind"],
            "transition_receipt_sha256": item["transition_receipt_sha256"],
            "before_frame_id": item["frame_ids"][0],
            "middle_frame_id": item["frame_ids"][1],
            "after_frame_id": item["frame_ids"][2],
        } for item in receipt["checks"]["transition"]],
    }
    analyzer_request = {
        "schema_version": VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION,
        "artifact_sha256": artifact["sha256"],
        "decoder_receipt_sha256": decoder_sha256,
        "timeline_receipt_sha256": timeline_sha256,
        "geometry": decoded_geometry,
        "timeline": {"frame_rate": rate, "frames": timeline_frames},
        "checks": check_plan,
    }
    decoded_identities = [{
        "frame_id": frame["frame_id"],
        "rgb24_sha256": frame["rgb24_sha256"],
        "bytes": frame["bytes"],
    } for frame in frames]
    referenced_receipts = sorted({
        item["transition_receipt_sha256"]
        for item in check_plan["transition"]
    })
    if (binding["artifact_sha256"] != artifact["sha256"]
            or binding["decoder_receipt_sha256"] != decoder_sha256
            or binding["timeline_receipt_sha256"] != timeline_sha256
            or binding["request_sha256"] != _canonical_sha256(analyzer_request)
            or binding["decoded_frames_sha256"]
            != _canonical_sha256(decoded_identities)
            or binding["geometry_sha256"] != _canonical_sha256(decoded_geometry)
            or binding["timeline_sha256"]
            != _canonical_sha256(analyzer_request["timeline"])
            or binding["renderer_receipt_sha256s"] != referenced_receipts
            or measured_plan != check_plan):
        _fail("production visual analyzer bindings drifted")
    coverage = _exact_dict(record["coverage"], _COVERAGE_KEYS, "visual QA coverage")
    for key in _COVERAGE_KEYS:
        _integer(coverage[key], f"visual QA coverage {key}", 0, _MAX_SOURCE_FRAMES)
    if (coverage["artifact_frame_count"] != source_count
            or coverage["decoded_frame_count"] != len(frames)
            or coverage["non_blank_sample_count"]
            != len(receipt["checks"]["frame_state"])
            or coverage["temporal_window_count"]
            != len(receipt["checks"]["temporal_window"])
            or coverage["analyzed_transition_count"]
            != len(receipt["checks"]["transition"])
            or coverage["declared_transition_count"]
            != len([item for item in intent["transitions"]
                    if item["kind"] in _SUPPORTED_TRANSITIONS])):
        _fail("production visual QA coverage does not match its evidence")
    measured_pass = receipt["summary"]["all_passed"]
    if type(record["pass"]) is not bool or record["pass"] != measured_pass:
        _fail("production visual QA pass flag does not match its checks")
    if require_pass and not measured_pass:
        _fail("production deterministic visual QA failed")
    return record


def run_production_deterministic_visual_qa(
    *, artifact_path: str | Path, output_path: str | Path,
    ffmpeg_path: str | Path, ffprobe_path: str | Path,
    intent: object,
) -> dict[str, Any]:
    """Decode, analyze, verify, and persist one quarantined artifact receipt."""
    artifact = _stable_file_identity(Path(artifact_path), "visual QA artifact")
    ffmpeg = _stable_file_identity(Path(ffmpeg_path), "visual QA ffmpeg")
    ffprobe = _stable_file_identity(Path(ffprobe_path), "visual QA ffprobe")
    output = Path(output_path)
    try:
        output_parent = output.parent.resolve(strict=True)
    except OSError as error:
        raise ProductionVisualQualityError(
            "production visual QA output parent is unavailable"
        ) from error
    if (output.name != PRODUCTION_VISUAL_QA_FILE
            or output_parent != artifact["path"].parent
            or output.exists() or output.is_symlink()):
        _fail("production visual QA output path is unsafe or stale")

    media = _probe_artifact(artifact, ffprobe)
    normalized_intent = _validate_intent(intent, media["duration_ms"])
    intent_sha256 = _canonical_sha256(normalized_intent)
    plan = _sample_plan(media, normalized_intent)
    decoded, decoder_frames, decoded_geometry = _decode_frames(
        artifact, ffmpeg, media, plan["indices"],
    )
    frame_ids = {frame["frame_index"]: frame["frame_id"] for frame in decoder_frames}
    checks = _checks(plan, frame_ids)
    decoder_receipt = {
        "schema_version": RGB24_DECODER_RECEIPT_SCHEMA_VERSION,
        "artifact_sha256": artifact["sha256"],
        "artifact_bytes": artifact["bytes"],
        "ffmpeg_sha256": ffmpeg["sha256"],
        "source_geometry": {
            "width": media["width"], "height": media["height"],
            "pixel_format": media["pixel_format"],
        },
        "decoded_geometry": decoded_geometry,
        "frame_rate": media["frame_rate"],
        "source_frame_count": media["frame_count"],
        "source_duration_ms": media["duration_ms"],
        "filter": {
            "selection": "zero_based_frame_index",
            "scale_width": decoded_geometry["width"],
            "scale_height": decoded_geometry["height"],
            "scale_flags": "bilinear",
            "pixel_format": "rgb24",
            "fps_mode": "passthrough",
        },
        "frames": decoder_frames,
    }
    decoder_sha256 = _canonical_sha256(decoder_receipt)
    analyzer_frames = [{key: frame[key] for key in (
        "frame_id", "frame_index", "timestamp_us", "rgb24_sha256",
    )} for frame in decoder_frames]
    timeline_receipt = {
        "schema_version": DECODED_TIMELINE_RECEIPT_SCHEMA_VERSION,
        "artifact_sha256": artifact["sha256"],
        "decoder_receipt_sha256": decoder_sha256,
        "intent_sha256": intent_sha256,
        "frame_rate": media["frame_rate"],
        "frames": analyzer_frames,
        "check_plan": checks,
        "check_plan_sha256": _canonical_sha256(checks),
    }
    timeline_sha256 = _canonical_sha256(timeline_receipt)
    request = {
        "schema_version": VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION,
        "artifact_sha256": artifact["sha256"],
        "decoder_receipt_sha256": decoder_sha256,
        "timeline_receipt_sha256": timeline_sha256,
        "geometry": decoded_geometry,
        "timeline": {
            "frame_rate": media["frame_rate"], "frames": analyzer_frames,
        },
        "checks": checks,
    }
    try:
        analysis = analyze_visual_quality_deterministic(request, decoded)
        receipt = verify_visual_quality_deterministic_result(analysis)
    except VisualQualityDeterministicError as error:
        raise ProductionVisualQualityError(
            "production visual analyzer rejected trusted decoded evidence"
        ) from error
    record = {
        "schema_version": PRODUCTION_VISUAL_QA_SCHEMA_VERSION,
        "artifact": {"sha256": artifact["sha256"], "bytes": artifact["bytes"]},
        "runtime": {
            "offline": True,
            "ffmpeg": {"sha256": ffmpeg["sha256"], "bytes": ffmpeg["bytes"]},
            "ffprobe": {"sha256": ffprobe["sha256"], "bytes": ffprobe["bytes"]},
        },
        "intent": normalized_intent,
        "intent_sha256": intent_sha256,
        "decoder_receipt": decoder_receipt,
        "decoder_receipt_sha256": decoder_sha256,
        "timeline_receipt": timeline_receipt,
        "timeline_receipt_sha256": timeline_sha256,
        "analysis": analysis,
        "coverage": {
            "artifact_frame_count": media["frame_count"],
            "decoded_frame_count": len(decoder_frames),
            "non_blank_sample_count": len(checks["frame_state"]),
            "temporal_window_count": len(checks["temporal_window"]),
            "declared_transition_count": plan["declared_transition_count"],
            "analyzed_transition_count": len(checks["transition"]),
        },
        "pass": receipt["summary"]["all_passed"],
    }
    _validate_record(record, artifact, require_pass=False)
    final_artifact = _stable_file_identity(artifact["path"], "visual QA artifact")
    final_ffmpeg = _stable_file_identity(ffmpeg["path"], "visual QA ffmpeg")
    final_ffprobe = _stable_file_identity(ffprobe["path"], "visual QA ffprobe")
    _same_file_identity(artifact, final_artifact, "visual QA artifact")
    _same_file_identity(ffmpeg, final_ffmpeg, "visual QA ffmpeg")
    _same_file_identity(ffprobe, final_ffprobe, "visual QA ffprobe")
    payload = (_canonical_json(record) + "\n").encode("ascii")
    try:
        with output.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise ProductionVisualQualityError(
            "production visual QA receipt could not be persisted"
        ) from error
    verify_production_visual_qa_file(
        output, artifact["path"], require_pass=False,
    )
    return record


def verify_production_visual_qa_file(
    receipt_path: str | Path, artifact_path: str | Path, *, require_pass: bool,
) -> dict[str, Any]:
    """Re-read and validate the exact persisted sidecar against artifact bytes."""
    receipt = _stable_file_identity(Path(receipt_path), "production visual QA receipt")
    if receipt["path"].name != PRODUCTION_VISUAL_QA_FILE:
        _fail("production visual QA receipt filename is invalid")
    if receipt["bytes"] > _MAX_SIDECAR_BYTES:
        _fail("production visual QA receipt exceeds its byte bound")
    artifact = _stable_file_identity(Path(artifact_path), "visual QA artifact")
    if receipt["path"].parent != artifact["path"].parent:
        _fail("production visual QA receipt is outside the artifact directory")
    try:
        payload = receipt["path"].read_bytes()
        after_receipt = _stable_file_identity(
            receipt["path"], "production visual QA receipt",
        )
        _same_file_identity(
            receipt, after_receipt, "production visual QA receipt",
        )
        if (len(payload) != receipt["bytes"]
                or hashlib.sha256(payload).hexdigest() != receipt["sha256"]):
            _fail("production visual QA receipt changed while it was read")
        if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
            _fail("production visual QA receipt is not canonical one-line JSON")
        value = json.loads(payload.decode("ascii", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        if isinstance(error, ProductionVisualQualityError):
            raise
        raise ProductionVisualQualityError(
            "production visual QA receipt could not be parsed"
        ) from error
    if payload != (_canonical_json(value) + "\n").encode("ascii"):
        _fail("production visual QA receipt bytes are not canonical")
    return _validate_record(value, artifact, require_pass=require_pass)


__all__ = [
    "DECODED_TIMELINE_RECEIPT_SCHEMA_VERSION",
    "PRODUCTION_VISUAL_INTENT_SCHEMA_VERSION",
    "PRODUCTION_VISUAL_QA_FILE",
    "PRODUCTION_VISUAL_QA_SCHEMA_VERSION",
    "RGB24_DECODER_RECEIPT_SCHEMA_VERSION",
    "ProductionVisualQualityError",
    "build_production_visual_intent",
    "run_production_deterministic_visual_qa",
    "verify_production_visual_qa_file",
]
