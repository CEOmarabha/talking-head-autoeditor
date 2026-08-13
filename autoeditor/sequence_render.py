"""Pure, closed FFmpeg command builder for compiled multi-source sequences.

The sequence planner deliberately stops at inert source identifiers.  This
module is the execution boundary that binds those identifiers to exact paths
and probed technical facts, then produces an argv list suitable for
``subprocess.run(argv, shell=False)``.  It never invokes FFmpeg and never
constructs a shell command.

All edit times remain integer milliseconds until they are formatted as fixed
three-decimal FFmpeg tokens.  Arbitrary ordering, repetition, and overlap are
supported.  Every segment gets an independently seeked, single-thread decoder
input.  This avoids the unbounded buffering/backpressure produced when a
single ``split``/``asplit`` fan-out feeds many temporal branches that concat
does not consume concurrently.

Each probed stream declares a signed ``start_offset_ms`` on the same source
timeline used by sequence-plan segment bounds.  Filters first normalize a
stream to its own first decoded sample, then translate the common segment
bounds into stream-local trim bounds.  This preserves audio/video start deltas
even when FFmpeg has normalized input timestamps.  A late audio stream is
truthfully represented with leading silence; a late video stream is rejected
when a selected range would require fabricated frames.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .color_contract import (
    ColorContractError,
    DETERMINISTIC_COLOR_COMPLEX_FILTER_ARGS,
    source_color_conversion_filter,
    validate_source_color,
)
from .sequence_plan import (
    MAX_SAFE_INTEGER,
    MAX_SEGMENTS,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    SequencePlanError,
    compile_receipt_sha256,
    source_manifest_sha256,
)


SOURCE_RENDER_MANIFEST_SCHEMA_VERSION = "autoeditor-source-render-manifest/v4"
SEQUENCE_RENDER_SCHEMA_VERSION = "autoeditor-sequence-render/v5"
SEQUENCE_TIMING_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-sequence-render-timing-receipt/v2"
)

MAX_RENDER_SOURCES = 20
MAX_PATH_CHARACTERS = 32_767
MAX_DIMENSION = 16_384
MAX_FRAME_RATE_COMPONENT = 1_000_000
MAX_FRAME_RATE = 240
MIN_AUDIO_SAMPLE_RATE = 8_000
MAX_AUDIO_SAMPLE_RATE = 384_000
MAX_AUDIO_CHANNELS = 32

_COMPILED_KEYS = frozenset({"receipt", "receipt_sha256", "ffmpeg_segments"})
_COMPILED_SEGMENT_KEYS = frozenset({
    "sequence_index",
    "segment_id",
    "source_id",
    "source_sha256",
    "source_start_ms",
    "source_end_ms",
    "duration_ms",
    "transition",
    "ffmpeg_trim_args",
})
_RENDER_MANIFEST_KEYS = frozenset({"schema_version", "output", "sources"})
_OUTPUT_KEYS = frozenset({
    "width", "height", "fps_numerator", "fps_denominator",
})
_RENDER_SOURCE_KEYS = frozenset({
    "source_id", "path", "sha256", "duration_ms", "video", "audio",
})
_VIDEO_KEYS = frozenset({
    "width", "height", "fps_numerator", "fps_denominator",
    "start_offset_ms", "duration_ms", "end_offset_ms",
    "codec_name", "pix_fmt", "color_range", "color_space", "color_transfer",
    "color_primaries",
})
_AUDIO_KEYS = frozenset({
    "present", "sample_rate", "channels", "start_offset_ms",
    "duration_ms", "end_offset_ms",
})
_TRANSITION_KEYS = frozenset({"kind"})

_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)
_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class SequenceRenderError(ValueError):
    """Compiled sequence, path binding, or render facts are unsafe."""


def _fail(message: str) -> None:
    raise SequenceRenderError(message)


def _exact_dict(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    actual = set(value)
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


def _milliseconds(value: object, label: str, *, minimum: int = 0) -> int:
    return _integer(value, label, minimum=minimum)


def _signed_milliseconds(value: object, label: str) -> int:
    if type(value) is not int or not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
        _fail(
            f"{label} must be an integer from "
            f"{-MAX_SAFE_INTEGER} to {MAX_SAFE_INTEGER}"
        )
    return value


def _safe_timeline_difference(end: int, start: int, label: str) -> int:
    value = end - start
    if not 0 <= value <= MAX_SAFE_INTEGER:
        _fail(f"{label} exceeds the exact integer timeline range")
    return value


def _stream_extent(
    start: int,
    duration_value: object,
    end_value: object,
    label: str,
) -> tuple[int, int]:
    """Validate a closed, exact millisecond stream extent."""
    duration = _milliseconds(duration_value, f"{label}.duration_ms", minimum=1)
    end = _signed_milliseconds(end_value, f"{label}.end_offset_ms")
    measured_end = start + duration
    if not -MAX_SAFE_INTEGER <= measured_end <= MAX_SAFE_INTEGER:
        _fail(f"{label} extent exceeds the exact integer timeline range")
    if end != measured_end:
        _fail(
            f"{label}.end_offset_ms must equal start_offset_ms + duration_ms"
        )
    return duration, end


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds // 1_000}.{milliseconds % 1_000:03d}"


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
        raise SequenceRenderError(f"{label} is not canonical JSON") from error


def _path_text(value: object, label: str) -> str:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise SequenceRenderError(f"{label} must be a filesystem path") from error
    if type(raw) is not str or not raw or len(raw) > MAX_PATH_CHARACTERS:
        _fail(f"{label} must be a bounded text path")
    if "\0" in raw or any(ord(character) < 32 for character in raw):
        _fail(f"{label} contains a control character")
    if not os.path.isabs(raw):
        _fail(f"{label} must be absolute")
    return os.path.normpath(raw)


def _path_identity(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _executable(value: object) -> str:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise SequenceRenderError("ffmpeg_path must be a path or executable name") from error
    if type(raw) is not str or not raw or len(raw) > MAX_PATH_CHARACTERS:
        _fail("ffmpeg_path is invalid")
    if "\0" in raw or any(ord(character) < 32 for character in raw):
        _fail("ffmpeg_path contains a control character")
    has_separator = os.sep in raw or bool(os.altsep and os.altsep in raw)
    if has_separator and not os.path.isabs(raw):
        _fail("ffmpeg_path with directories must be absolute")
    return os.path.normpath(raw) if os.path.isabs(raw) else raw


def _frame_rate(raw: dict, label: str) -> tuple[int, int]:
    numerator = _integer(
        raw["fps_numerator"],
        f"{label}.fps_numerator",
        minimum=1,
        maximum=MAX_FRAME_RATE_COMPONENT,
    )
    denominator = _integer(
        raw["fps_denominator"],
        f"{label}.fps_denominator",
        minimum=1,
        maximum=MAX_FRAME_RATE_COMPONENT,
    )
    if numerator / denominator > MAX_FRAME_RATE:
        _fail(f"{label} frame rate exceeds {MAX_FRAME_RATE} fps")
    return numerator, denominator


def _video_facts(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _VIDEO_KEYS, label)
    width = _integer(raw["width"], f"{label}.width", minimum=1,
                     maximum=MAX_DIMENSION)
    height = _integer(raw["height"], f"{label}.height", minimum=1,
                      maximum=MAX_DIMENSION)
    numerator, denominator = _frame_rate(raw, label)
    start_offset = _signed_milliseconds(
        raw["start_offset_ms"], f"{label}.start_offset_ms"
    )
    duration, end_offset = _stream_extent(
        start_offset, raw["duration_ms"], raw["end_offset_ms"], label
    )
    try:
        color = validate_source_color(raw, label)
    except ColorContractError as error:
        raise SequenceRenderError(str(error)) from error
    return {
        "width": width,
        "height": height,
        "fps_numerator": numerator,
        "fps_denominator": denominator,
        "start_offset_ms": start_offset,
        "duration_ms": duration,
        "end_offset_ms": end_offset,
        "codec_name": color["codec_name"],
        "pix_fmt": color["pix_fmt"],
        "color_range": color["color_range"],
        "color_space": color["color_space"],
        "color_transfer": color["color_transfer"],
        "color_primaries": color["color_primaries"],
    }


def _output_video_facts(value: object, label: str) -> dict[str, int]:
    raw = _exact_dict(value, _OUTPUT_KEYS, label)
    width = _integer(raw["width"], f"{label}.width", minimum=1,
                     maximum=MAX_DIMENSION)
    height = _integer(raw["height"], f"{label}.height", minimum=1,
                      maximum=MAX_DIMENSION)
    numerator, denominator = _frame_rate(raw, label)
    return {
        "width": width,
        "height": height,
        "fps_numerator": numerator,
        "fps_denominator": denominator,
    }


def _audio_facts(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _AUDIO_KEYS, label)
    if type(raw["present"]) is not bool:
        _fail(f"{label}.present must be a boolean")
    if not raw["present"]:
        if (raw["sample_rate"] is not None or raw["channels"] is not None
                or raw["start_offset_ms"] is not None
                or raw["duration_ms"] is not None
                or raw["end_offset_ms"] is not None):
            _fail(f"{label} absent audio must use null technical values")
        return {
            "present": False,
            "sample_rate": None,
            "channels": None,
            "start_offset_ms": None,
            "duration_ms": None,
            "end_offset_ms": None,
        }
    sample_rate = _integer(
        raw["sample_rate"],
        f"{label}.sample_rate",
        minimum=MIN_AUDIO_SAMPLE_RATE,
        maximum=MAX_AUDIO_SAMPLE_RATE,
    )
    channels = _integer(
        raw["channels"],
        f"{label}.channels",
        minimum=1,
        maximum=MAX_AUDIO_CHANNELS,
    )
    start_offset = _signed_milliseconds(
        raw["start_offset_ms"], f"{label}.start_offset_ms"
    )
    duration, end_offset = _stream_extent(
        start_offset, raw["duration_ms"], raw["end_offset_ms"], label
    )
    return {
        "present": True,
        "sample_rate": sample_rate,
        "channels": channels,
        "start_offset_ms": start_offset,
        "duration_ms": duration,
        "end_offset_ms": end_offset,
    }


def _render_manifest(value: object) -> dict[str, Any]:
    raw = _exact_dict(value, _RENDER_MANIFEST_KEYS, "source render manifest")
    if raw["schema_version"] != SOURCE_RENDER_MANIFEST_SCHEMA_VERSION:
        _fail("source render manifest schema_version is unsupported")

    output = _output_video_facts(raw["output"], "render output")
    if output["width"] % 2 or output["height"] % 2:
        _fail("render output dimensions must be even for yuv420p")

    sources_raw = raw["sources"]
    if type(sources_raw) is not list or not 1 <= len(sources_raw) <= MAX_RENDER_SOURCES:
        _fail(f"source render manifest must contain 1-{MAX_RENDER_SOURCES} sources")
    sources = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()
    for index, value_source in enumerate(sources_raw):
        label = f"source render manifest.sources[{index}]"
        source = _exact_dict(value_source, _RENDER_SOURCE_KEYS, label)
        source_id = _identifier(source["source_id"], _SOURCE_ID,
                                f"{label}.source_id")
        digest = _digest(source["sha256"], f"{label}.sha256")
        duration = _milliseconds(source["duration_ms"], f"{label}.duration_ms",
                                 minimum=1)
        source_path = _path_text(source["path"], f"{label}.path")
        path_key = _path_identity(source_path)
        if source_id in seen_ids:
            _fail(f"{label}.source_id must be unique")
        if path_key in seen_paths:
            _fail(f"{label}.path must bind one unique source")
        if digest in seen_hashes:
            _fail(f"{label}.sha256 must bind one unique source")
        seen_ids.add(source_id)
        seen_paths.add(path_key)
        seen_hashes.add(digest)
        video = _video_facts(source["video"], f"{label}.video")
        audio = _audio_facts(source["audio"], f"{label}.audio")
        if video["start_offset_ms"] >= duration:
            _fail(f"{label}.video starts outside the source timeline")
        if video["end_offset_ms"] <= 0:
            _fail(f"{label}.video ends outside the source timeline")
        if audio["present"] and audio["start_offset_ms"] >= duration:
            _fail(f"{label}.audio starts outside the source timeline")
        if audio["present"] and audio["end_offset_ms"] <= 0:
            _fail(f"{label}.audio ends outside the source timeline")
        sources.append({
            "source_id": source_id,
            "path": source_path,
            "sha256": digest,
            "duration_ms": duration,
            "video": video,
            "audio": audio,
        })
    sources.sort(key=lambda item: item["source_id"])
    return {
        "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
        "output": output,
        "sources": sources,
    }


def _compiled_output(value: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _exact_dict(value, _COMPILED_KEYS, "compiled sequence")
    receipt = raw["receipt"]
    try:
        measured_receipt_hash = compile_receipt_sha256(receipt)
    except SequencePlanError as error:
        raise SequenceRenderError("compiled sequence receipt is invalid") from error
    supplied_receipt_hash = _digest(
        raw["receipt_sha256"], "compiled sequence.receipt_sha256")
    if measured_receipt_hash != supplied_receipt_hash:
        _fail("compiled sequence receipt hash does not match")

    segments_raw = raw["ffmpeg_segments"]
    if type(segments_raw) is not list or not 1 <= len(segments_raw) <= MAX_SEGMENTS:
        _fail(f"compiled sequence must contain 1-{MAX_SEGMENTS} segments")
    segments = []
    seen_ids: set[str] = set()
    total_duration = 0
    for index, value_segment in enumerate(segments_raw):
        label = f"compiled sequence.ffmpeg_segments[{index}]"
        segment = _exact_dict(value_segment, _COMPILED_SEGMENT_KEYS, label)
        sequence_index = _integer(
            segment["sequence_index"], f"{label}.sequence_index",
            maximum=MAX_SEGMENTS - 1)
        if sequence_index != index:
            _fail(f"{label}.sequence_index is not contiguous")
        segment_id = _identifier(segment["segment_id"], _SEGMENT_ID,
                                 f"{label}.segment_id")
        if segment_id in seen_ids:
            _fail(f"{label}.segment_id must be unique")
        seen_ids.add(segment_id)
        source_id = _identifier(segment["source_id"], _SOURCE_ID,
                                f"{label}.source_id")
        digest = _digest(segment["source_sha256"], f"{label}.source_sha256")
        start = _milliseconds(segment["source_start_ms"],
                              f"{label}.source_start_ms")
        end = _milliseconds(segment["source_end_ms"],
                            f"{label}.source_end_ms", minimum=1)
        duration = _milliseconds(segment["duration_ms"],
                                 f"{label}.duration_ms", minimum=1)
        if start >= end or duration != end - start:
            _fail(f"{label} has inconsistent millisecond bounds")
        transition = _exact_dict(segment["transition"], _TRANSITION_KEYS,
                                 f"{label}.transition")
        if transition["kind"] != "hard_cut":
            _fail(f"{label}.transition.kind must be hard_cut")
        expected_trim = ["-ss", _seconds(start), "-t", _seconds(duration)]
        if segment["ffmpeg_trim_args"] != expected_trim:
            _fail(f"{label}.ffmpeg_trim_args do not match exact milliseconds")
        total_duration += duration
        if total_duration > MAX_SAFE_INTEGER:
            _fail("compiled sequence duration exceeds the exact integer range")
        segments.append({
            "sequence_index": index,
            "segment_id": segment_id,
            "source_id": source_id,
            "source_sha256": digest,
            "source_start_ms": start,
            "source_end_ms": end,
            "duration_ms": duration,
            "transition": {"kind": "hard_cut"},
            "ffmpeg_trim_args": expected_trim,
        })

    if receipt["segment_count"] != len(segments):
        _fail("compiled sequence receipt segment_count does not match")
    if receipt["ordered_segment_ids"] != [item["segment_id"] for item in segments]:
        _fail("compiled sequence receipt order does not match segments")
    if receipt["total_duration_ms"] != total_duration:
        _fail("compiled sequence receipt duration does not match segments")
    measured_segments_hash = hashlib.sha256(
        _canonical_json(segments, "compiled segments").encode("utf-8")
    ).hexdigest()
    if receipt["compiled_segments_sha256"] != measured_segments_hash:
        _fail("compiled sequence segment hash does not match")
    return receipt, segments


def validate_compiled_sequence(
    value: object,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Publicly revalidate persisted compiled sequence evidence."""
    receipt, segments = _compiled_output(value)
    return dict(receipt), [dict(segment) for segment in segments]


def _source_paths(value: object, sources: list[dict[str, Any]]) -> dict[str, str]:
    if type(value) is not dict:
        _fail("source_paths must be an exact source_id-to-path object")
    expected_ids = {source["source_id"] for source in sources}
    if set(value) != expected_ids:
        _fail("source_paths must exactly match the render manifest source ids")
    by_id = {source["source_id"]: source for source in sources}
    normalized: dict[str, str] = {}
    for source_id in sorted(expected_ids):
        mapped = _path_text(value[source_id], f"source_paths[{source_id!r}]")
        declared = by_id[source_id]["path"]
        if _path_identity(mapped) != _path_identity(declared):
            _fail(f"source_paths[{source_id!r}] does not match the render manifest")
        normalized[source_id] = declared
    return normalized


def _synthesis_ids(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if type(value) not in {list, tuple, set, frozenset}:
        _fail("synthesize_silence_for must be an explicit source-id collection")
    identifiers = []
    for index, item in enumerate(value):
        identifiers.append(_identifier(
            item, _SOURCE_ID, f"synthesize_silence_for[{index}]"))
    if len(set(identifiers)) != len(identifiers):
        _fail("synthesize_silence_for must not contain duplicates")
    return frozenset(identifiers)


def _segment_timing(
    segment: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    """Translate one common-timeline interval into stream-local bounds."""
    common_start = segment["source_start_ms"]
    common_end = segment["source_end_ms"]
    segment_duration = segment["duration_ms"]
    video_start = source["video"]["start_offset_ms"]
    if common_start < video_start:
        _fail(
            f"segment {segment['segment_id']!r} begins before its video stream; "
            "fabricated leading frames are not supported"
        )
    video_end = source["video"]["end_offset_ms"]
    if common_end > video_end:
        _fail(
            f"segment {segment['segment_id']!r} ends after its decoded video "
            "stream; fabricated trailing frames are not supported"
        )
    video_local_start = _safe_timeline_difference(
        common_start, video_start, "video local start"
    )
    video_local_end = _safe_timeline_difference(
        common_end, video_start, "video local end"
    )

    audio = source["audio"]
    if not audio["present"]:
        audio_local_start = None
        audio_local_end = None
        audio_lead_silence = segment_duration
        audio_tail_silence = 0
        audio_mode = "declared_silence"
    else:
        audio_start = audio["start_offset_ms"]
        audio_end = audio["end_offset_ms"]
        overlap_start = max(common_start, audio_start)
        overlap_end = min(common_end, audio_end)
        if overlap_start >= overlap_end:
            audio_local_start = None
            audio_local_end = None
            if audio_start >= common_end:
                audio_lead_silence = segment_duration
                audio_tail_silence = 0
            else:
                audio_lead_silence = 0
                audio_tail_silence = segment_duration
            audio_mode = "timeline_silence"
        else:
            audio_local_start = _safe_timeline_difference(
                overlap_start, audio_start, "audio local start"
            )
            audio_local_end = _safe_timeline_difference(
                overlap_end, audio_start, "audio local end"
            )
            audio_lead_silence = _safe_timeline_difference(
                overlap_start, common_start, "audio lead silence"
            )
            audio_tail_silence = _safe_timeline_difference(
                common_end, overlap_end, "audio tail silence"
            )
            audio_mode = "delayed_source" if audio_lead_silence else "source"

    if audio_lead_silence > segment_duration:
        _fail("audio lead silence exceeds its selected segment")
    if audio_tail_silence > segment_duration:
        _fail("audio tail silence exceeds its selected segment")
    source_audio_duration = (
        0 if audio_local_start is None else
        _safe_timeline_difference(
            audio_local_end, audio_local_start, "selected audio duration"
        )
    )
    if (audio_lead_silence + source_audio_duration + audio_tail_silence
            != segment_duration):
        _fail("selected audio and receipted silence do not cover the segment")
    return {
        "sequence_index": segment["sequence_index"],
        "segment_id": segment["segment_id"],
        "source_id": segment["source_id"],
        "common_start_ms": common_start,
        "common_end_ms": common_end,
        "video_local_start_ms": video_local_start,
        "video_local_end_ms": video_local_end,
        "audio_local_start_ms": audio_local_start,
        "audio_local_end_ms": audio_local_end,
        "audio_lead_silence_ms": audio_lead_silence,
        "audio_tail_silence_ms": audio_tail_silence,
        "audio_mode": audio_mode,
    }


def build_sequence_render(
    compiled_sequence: object,
    source_paths: object,
    source_render_manifest: object,
    output_path: str | os.PathLike[str],
    *,
    ffmpeg_path: str | os.PathLike[str] = "ffmpeg",
    synthesize_silence_for: object = (),
) -> dict[str, Any]:
    """Return a deterministic, shell-free FFmpeg render description.

    ``compiled_sequence`` must be the exact output of
    :func:`autoeditor.sequence_plan.compile_sequence_plan`.  The auxiliary
    render manifest repeats that source inventory with canonical paths and
    probed video/audio facts, including a closed five-field source-color
    declaration.  Its stripped inventory hash must equal the compile receipt,
    and ``source_paths`` must exactly match every manifest source.

    A selected source without audio fails closed unless its id is explicitly
    listed in ``synthesize_silence_for``.  Such segments receive bounded
    48 kHz stereo ``anullsrc`` audio of exactly the segment duration.  Every
    video and present audio object must also supply a closed stream extent:
    signed ``start_offset_ms``, positive ``duration_ms``, and exact derived
    ``end_offset_ms`` relative to the sequence plan's source timeline origin.
    Video selections never extend beyond that decoded extent. Short audio is
    padded only when the timing receipt explicitly records the exact trailing
    silence in ``audio_tail_silence_ms``.
    """
    receipt, segments = _compiled_output(compiled_sequence)
    manifest = _render_manifest(source_render_manifest)
    paths = _source_paths(source_paths, manifest["sources"])
    output = _path_text(output_path, "output_path")
    if Path(output).suffix.lower() != ".mp4":
        _fail("output_path must have an .mp4 suffix")
    if _path_identity(output) in {
        _path_identity(path) for path in paths.values()
    }:
        _fail("output_path must not overwrite a source")
    ffmpeg = _executable(ffmpeg_path)

    base_manifest = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sources": [{
            "source_id": source["source_id"],
            "sha256": source["sha256"],
            "duration_ms": source["duration_ms"],
        } for source in manifest["sources"]],
    }
    try:
        measured_manifest_hash = source_manifest_sha256(base_manifest)
    except SequencePlanError as error:
        raise SequenceRenderError("render manifest source inventory is invalid") from error
    if measured_manifest_hash != receipt["source_manifest_sha256"]:
        _fail("render manifest does not match the compiled source inventory")

    source_by_id = {source["source_id"]: source for source in manifest["sources"]}
    used_ids = {segment["source_id"] for segment in segments}
    for segment in segments:
        source = source_by_id.get(segment["source_id"])
        if source is None:
            _fail("compiled segment source is absent from render manifest")
        if segment["source_sha256"] != source["sha256"]:
            _fail("compiled segment hash does not match render manifest")
        if segment["source_end_ms"] > source["duration_ms"]:
            _fail("compiled segment exceeds render source duration")

    synthesis = _synthesis_ids(synthesize_silence_for)
    missing_audio = {
        source_id for source_id in used_ids
        if not source_by_id[source_id]["audio"]["present"]
    }
    if synthesis != missing_audio:
        if missing_audio - synthesis:
            _fail("selected no-audio sources require explicit silence synthesis")
        _fail("silence synthesis was requested for a source that has audio or is unused")

    segment_timing = [
        _segment_timing(segment, source_by_id[segment["source_id"]])
        for segment in segments
    ]
    timing_by_index = {
        timing["sequence_index"]: timing for timing in segment_timing
    }

    # The daemon snapshots every approved source into one private work
    # directory.  Use short, relative aliases from that directory so 256
    # segment occurrences remain safely below Windows' CreateProcess command
    # line limit even when the user selected sources through long paths.
    input_parents = {
        _path_identity(str(Path(paths[source_id]).parent)) for source_id in used_ids
    }
    output_parent = _path_identity(str(Path(output).parent))
    if len(input_parents) != 1 or output_parent not in input_parents:
        _fail("sequence sources and output must share one private work directory")
    working_directory = str(Path(next(paths[source_id] for source_id in used_ids)).parent)
    input_alias_by_id = {
        source_id: f".{os.sep}{Path(paths[source_id]).name}"
        for source_id in used_ids
    }

    filters: list[str] = []

    target = manifest["output"]
    width = target["width"]
    height = target["height"]
    fps = f"{target['fps_numerator']}/{target['fps_denominator']}"
    concat_inputs = []
    for segment in segments:
        sequence_index = segment["sequence_index"]
        timing = timing_by_index[sequence_index]
        source = source_by_id[segment["source_id"]]
        duration = _seconds(segment["duration_ms"])
        video_output = f"v{sequence_index:03d}"
        audio_output = f"a{sequence_index:03d}"
        color_filter = source_color_conversion_filter(source["video"])
        filters.append(
            f"[{sequence_index}:v:0]"
            f"trim=duration={duration},"
            "setpts=PTS-STARTPTS,"
            f"{color_filter},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
            "flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps=fps={fps}:round=near,setsar=1,format=yuv420p,"
            "setparams=range=tv:color_primaries=bt709:"
            "color_trc=bt709:colorspace=bt709"
            f"[{video_output}]"
        )
        if timing["audio_mode"] in {"source", "delayed_source"}:
            selected_audio_duration_ms = (
                timing["audio_local_end_ms"] - timing["audio_local_start_ms"]
            )
            selected_audio_duration = _seconds(selected_audio_duration_ms)
            audio_filter = (
                f"[{sequence_index}:a:0]"
                f"atrim=duration={selected_audio_duration},"
                "asetpts=PTS-STARTPTS,"
                "aresample=48000:async=0:first_pts=0,"
                "aformat=sample_rates=48000:channel_layouts=stereo"
            )
            if timing["audio_lead_silence_ms"]:
                audio_filter += (
                    f",adelay={timing['audio_lead_silence_ms']}:all=1"
                )
            audio_filter += (
                f",apad,atrim=duration={duration},"
                f"asetpts=PTS-STARTPTS[{audio_output}]"
            )
            filters.append(audio_filter)
        else:
            filters.append(
                "anullsrc=channel_layout=stereo:sample_rate=48000,"
                f"atrim=duration={duration},asetpts=PTS-STARTPTS[{audio_output}]"
            )
        concat_inputs.extend([f"[{video_output}]", f"[{audio_output}]"])
    filters.append(
        "".join(concat_inputs)
        + f"concat=n={len(segments)}:v=1:a=1[vout][aout]"
    )
    filter_complex = ";".join(filters)
    total_duration = receipt["total_duration_ms"]
    filter_script_path = str(
        Path(output).with_name(f"{Path(output).stem}-filter.txt")
    )

    source_timing = [{
        "source_id": source["source_id"],
        "source_sha256": source["sha256"],
        "video_start_offset_ms": source["video"]["start_offset_ms"],
        "video_duration_ms": source["video"]["duration_ms"],
        "video_end_offset_ms": source["video"]["end_offset_ms"],
        "audio_start_offset_ms": source["audio"]["start_offset_ms"],
        "audio_duration_ms": source["audio"]["duration_ms"],
        "audio_end_offset_ms": source["audio"]["end_offset_ms"],
    } for source in manifest["sources"]]
    timing_receipt = {
        "schema_version": SEQUENCE_TIMING_RECEIPT_SCHEMA_VERSION,
        "compiled_receipt_sha256": compile_receipt_sha256(receipt),
        "source_timing": source_timing,
        "segment_timing": segment_timing,
    }
    timing_receipt_sha256 = hashlib.sha256(
        _canonical_json(timing_receipt, "sequence timing receipt").encode("utf-8")
    ).hexdigest()

    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel", "error",
        *DETERMINISTIC_COLOR_COMPLEX_FILTER_ARGS,
        "-y",
    ]
    segment_input_source_ids = []
    for segment in segments:
        source_id = segment["source_id"]
        segment_input_source_ids.append(source_id)
        argv.extend([
            "-threads", "1",
            "-ss", _seconds(segment["source_start_ms"]),
            "-t", _seconds(segment["duration_ms"]),
            "-i", input_alias_by_id[source_id],
        ])
    argv.extend([
        "-filter_complex_script", f".{os.sep}{Path(filter_script_path).name}",
        "-map", "[vout]",
        "-map", "[aout]",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        "-sn",
        "-dn",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-color_range", "tv",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-bsf:v",
        "h264_metadata=colour_primaries=1:transfer_characteristics=1:"
        "matrix_coefficients=1",
        "-fps_mode", "cfr",
        "-r", fps,
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-t", _seconds(total_duration),
        "-movflags", "+faststart",
        f".{os.sep}{Path(output).name}",
    ])
    return {
        "schema_version": SEQUENCE_RENDER_SCHEMA_VERSION,
        "argv": argv,
        "filter_complex": filter_complex,
        "source_input_order": segment_input_source_ids,
        "working_directory": working_directory,
        "filter_script_path": filter_script_path,
        "ordered_segment_ids": [segment["segment_id"] for segment in segments],
        "segment_count": len(segments),
        "total_duration_ms": total_duration,
        "output_path": output,
        "timing_receipt": timing_receipt,
        "timing_receipt_sha256": timing_receipt_sha256,
    }


def build_sequence_render_argv(*args: Any, **kwargs: Any) -> list[str]:
    """Convenience wrapper returning only the safe argv token list."""
    return build_sequence_render(*args, **kwargs)["argv"]
