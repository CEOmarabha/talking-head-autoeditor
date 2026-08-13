"""Offline proof for the production color and transition render capabilities.

The probe deliberately makes four narrow claims and no others:

* one declared 8-bit SDR BT.470BG source is converted by the
  production color contract into BT.709 limited-range delivery pixels;
* the production transition planner and executor render one frame-aligned
  400 ms ``xfade=fade`` cross-dissolve at 30000/1001 fps;
* the same boundary renders the production equal-power qsin ``acrossfade``
  into decoded 48 kHz stereo audio; and
* fixed decoded frames across that boundary progress continuously and contain
  no black flash.

It does not claim HDR support, arbitrary transition aesthetics, optical-flow
interpolation, or quality on media outside this fixed fixture.  All media is
generated locally by the supplied FFmpeg, no network or cache is consulted,
and only a path-free canonical receipt survives the work directory.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .color_contract import (
    ColorContractError,
    DETERMINISTIC_COLOR_FILTER_ARGS,
    source_color_conversion_filter,
    source_color_normalization_mode,
)
from .edit_policy import (
    CAPABILITIES,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    edit_policy_sha256,
    resolve_edit_policy,
)
from .sequence_plan import (
    SEQUENCE_PLAN_SCHEMA_VERSION,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    compile_sequence_plan,
)
from .sequence_render import SOURCE_RENDER_MANIFEST_SCHEMA_VERSION
from .transition_plan import (
    TRANSITION_PLAN_SCHEMA_VERSION,
    TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
    compile_transition_plan,
    derive_boundary_id,
    transition_sequence_manifest_sha256,
)
from .transition_render import (
    build_transition_render,
    transition_render_receipt_sha256,
)


RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION = (
    "autoeditor-render-capability-runtime-probe/v1"
)
RENDER_CAPABILITY_RUNTIME_PROBE_EVENT = (
    "autoeditor-engine-render-capability-self-test"
)
RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE = (
    "RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT.json"
)
RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE = (
    "render-capability-bt470-source.mp4"
)
RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_B_FILE = (
    "render-capability-bt709-source.mp4"
)
RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE = (
    "render-capability-artifact.mp4"
)
RENDER_CAPABILITY_RUNTIME_PROBE_FILTER_FILE = (
    "render-capability-artifact-filter.txt"
)
RENDER_CAPABILITY_RUNTIME_PROBE_FIXTURE_SCHEMA_VERSION = (
    "autoeditor-render-capability-fixture/v1"
)

RENDER_CAPABILITY_CHECK_NAMES = frozenset({
    "audio_crossfades",
    "color_normalization",
    "cross_dissolves",
    "motion_quality_analysis",
})

FRAME_RATE_NUMERATOR = 30_000
FRAME_RATE_DENOMINATOR = 1_001
WIDTH = 160
HEIGHT = 90
SOURCE_SELECTION_MS = 3_000
SOURCE_GENERATOR_MS = 3_003
TRANSITION_DURATION_MS = 400
EXPECTED_OUTPUT_MS = 5_600
AUDIO_SAMPLE_RATE = 48_000
AUDIO_CHANNELS = 2
SOURCE_A_FREQUENCY_HZ = 440
SOURCE_B_FREQUENCY_HZ = 880
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_TOOL_BYTES = 1024 * 1024 * 1024

SOURCE_A_COLOR = {
    "codec_name": "h264",
    "pix_fmt": "yuv420p",
    "color_range": "tv",
    "color_space": "bt470bg",
    "color_transfer": "bt470bg",
    "color_primaries": "bt470bg",
}
SOURCE_B_COLOR = {
    "codec_name": "h264",
    "pix_fmt": "yuv420p",
    "color_range": "tv",
    "color_space": "bt709",
    "color_transfer": "bt709",
    "color_primaries": "bt709",
}

_SCOPE = {
    "audio": "fixed-440hz-to-880hz-qsin-overlap-48000hz-stereo",
    "color": "declared-bt470bg-tv-sdr-to-bt709-tv-yuv420p",
    "motion": "fixed-decoded-frame-blend-progression-and-no-black-flash",
    "transition": "single-400ms-xfade-fade-at-30000-1001fps",
    "unsupported": ["hdr", "optical_flow", "arbitrary_transition_quality"],
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", re.ASCII)


class RenderCapabilityRuntimeProbeError(ValueError):
    """The fixed production render proof could not be established safely."""


def _fail(message: str) -> None:
    raise RenderCapabilityRuntimeProbeError(message)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise RenderCapabilityRuntimeProbeError(
            "render capability receipt is not canonical JSON"
        ) from error


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def _integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = 9_007_199_254_740_991,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _safe_file_name(value: object, label: str) -> str:
    if type(value) is not str or _SAFE_FILE_NAME.fullmatch(value) is None:
        _fail(f"{label} must be a bounded path-free file name")
    return value


def _absolute_existing_dir(value: str | os.PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _fail(f"{label} path is invalid")
    text = os.fspath(value)
    if not text or "\0" in text:
        _fail(f"{label} path is invalid")
    path = Path(os.path.realpath(Path(text)))
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        _fail(f"{label} is unavailable")
    return path


def _absolute_existing_file(value: str | os.PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _fail(f"{label} path is invalid")
    text = os.fspath(value)
    if not text or "\0" in text:
        _fail(f"{label} path is invalid")
    path = Path(os.path.realpath(Path(text)))
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        _fail(f"{label} is unavailable")
    return path


def _new_receipt_path(
    value: str | os.PathLike[str], root: Path,
) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _fail("render capability receipt path is invalid")
    text = os.fspath(value)
    if not text or "\0" in text:
        _fail("render capability receipt path is invalid")
    path = Path(os.path.realpath(Path(text)))
    if (
        not path.is_absolute()
        or path.parent != root
        or path.name != RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE
        or path.exists()
        or path.is_symlink()
    ):
        _fail(
            "render capability receipt must be a new fixed file inside its "
            "work directory"
        )
    return path


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags, 0o600)
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count < 1:
                raise OSError("short render capability receipt write")
            written += count
        os.fsync(descriptor)
        os.chmod(path, 0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def _file_identity(path: Path, label: str) -> tuple[dict[str, Any], os.stat_result]:
    before = path.stat()
    if before.st_size < 1 or before.st_size > MAX_TOOL_BYTES:
        _fail(f"{label} has an invalid bounded size")
    digest = _sha256_file(path)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
    ):
        _fail(f"{label} changed while its identity was measured")
    return {
        "file": _safe_file_name(path.name, f"{label} file"),
        "sha256": digest,
        "bytes": before.st_size,
    }, before


def _verify_file_identity(
    path: Path,
    expected: dict[str, Any],
    prior_stat: os.stat_result,
    label: str,
) -> None:
    after = path.stat()
    if (
        after.st_size != prior_stat.st_size
        or after.st_mtime_ns != prior_stat.st_mtime_ns
        or getattr(after, "st_ino", None) != getattr(prior_stat, "st_ino", None)
        or _sha256_file(path) != expected["sha256"]
    ):
        _fail(f"{label} identity changed during the probe")


def _run(
    command: list[str],
    *,
    stage: str,
    cwd: Path | None = None,
    timeout: int = 120,
    execute: Callable[..., object] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    runner = execute or subprocess.run
    try:
        completed = runner(
            command,
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            timeout=timeout,
        )
    except Exception as error:
        raise RenderCapabilityRuntimeProbeError(
            f"{stage} process failed: {type(error).__name__}"
        ) from error
    if type(getattr(completed, "returncode", None)) is not int:
        _fail(f"{stage} returned an invalid process result")
    if completed.returncode != 0:
        _fail(f"{stage} failed with exit code {completed.returncode}")
    stdout = completed.stdout
    stderr = completed.stderr
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        _fail(f"{stage} returned non-binary process output")
    return completed


def _source_video_filter(source: str) -> str:
    rate = f"{FRAME_RATE_NUMERATOR}/{FRAME_RATE_DENOMINATOR}"
    duration = f"{SOURCE_GENERATOR_MS // 1000}.{SOURCE_GENERATOR_MS % 1000:03d}"
    if source == "a":
        background = "0xd6421f"
        horizontal = "mod(t*52\\,128)"
        vertical = "15"
    else:
        background = "0x185bd2"
        horizontal = "128-mod(t*47\\,128)"
        vertical = "43"
    return (
        f"color=c={background}:s={WIDTH}x{HEIGHT}:r={rate}:d={duration}[bg];"
        f"testsrc2=s=32x32:r={rate}:d={duration}[sprite];"
        f"[bg][sprite]overlay=x={horizontal}:y={vertical}:shortest=1,"
        "format=yuv420p"
    )


def _generate_source(
    ffmpeg: Path,
    output: Path,
    *,
    source: str,
    color: dict[str, str],
    frequency_hz: int,
    execute: Callable[..., object] | None,
) -> None:
    duration = f"{SOURCE_GENERATOR_MS // 1000}.{SOURCE_GENERATOR_MS % 1000:03d}"
    command = [
        str(ffmpeg),
        "-hide_banner", "-nostdin", "-loglevel", "error", "-n",
        "-f", "lavfi", "-i", _source_video_filter(source),
        "-f", "lavfi", "-i",
        f"sine=frequency={frequency_hz}:sample_rate={AUDIO_SAMPLE_RATE}:"
        f"duration={duration}",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
        "-pix_fmt", "yuv420p",
        "-color_range", color["color_range"],
        "-color_primaries", color["color_primaries"],
        "-color_trc", color["color_transfer"],
        "-colorspace", color["color_space"],
        "-bsf:v", (
            "h264_metadata=colour_primaries=5:transfer_characteristics=5:"
            "matrix_coefficients=5"
            if source == "a" else
            "h264_metadata=colour_primaries=1:transfer_characteristics=1:"
            "matrix_coefficients=1"
        ),
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE),
        "-ac", str(AUDIO_CHANNELS),
        "-movflags", "+faststart", str(output),
    ]
    _run(
        command,
        stage=f"fixed source {source} generation",
        timeout=90,
        execute=execute,
    )
    if not output.is_file() or output.stat().st_size < 1:
        _fail(f"fixed source {source} generation produced no artifact")


def _parse_rate(value: object, label: str) -> tuple[int, int]:
    if type(value) is not str or "/" not in value:
        _fail(f"{label} is invalid")
    left, right = value.split("/", 1)
    try:
        numerator = int(left)
        denominator = int(right)
    except ValueError as error:
        raise RenderCapabilityRuntimeProbeError(f"{label} is invalid") from error
    if numerator < 1 or denominator < 1:
        _fail(f"{label} is invalid")
    divisor = math.gcd(numerator, denominator)
    return numerator // divisor, denominator // divisor


def _duration_ms(value: object, label: str) -> int:
    if type(value) is not str:
        _fail(f"{label} is invalid")
    try:
        milliseconds = round(float(value) * 1000)
    except (ValueError, OverflowError) as error:
        raise RenderCapabilityRuntimeProbeError(f"{label} is invalid") from error
    if milliseconds < 1 or milliseconds > 60_000:
        _fail(f"{label} is outside the fixed probe bound")
    return milliseconds


def _probe_media(
    ffprobe: Path,
    path: Path,
    *,
    stage: str,
    execute: Callable[..., object] | None,
) -> dict[str, Any]:
    command = [
        str(ffprobe), "-v", "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,pix_fmt,"
        "width,height,avg_frame_rate,duration,sample_rate,channels,"
        "color_range,color_space,color_transfer,color_primaries",
        "-of", "json", str(path),
    ]
    payload = _run(
        command, stage=stage, timeout=30, execute=execute,
    ).stdout
    if len(payload) > 1024 * 1024:
        _fail(f"{stage} returned oversized metadata")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RenderCapabilityRuntimeProbeError(
            f"{stage} returned invalid JSON"
        ) from error
    if type(value) is not dict or type(value.get("streams")) is not list:
        _fail(f"{stage} returned invalid media metadata")
    video_items = [
        item for item in value["streams"]
        if type(item) is dict and item.get("codec_type") == "video"
    ]
    audio_items = [
        item for item in value["streams"]
        if type(item) is dict and item.get("codec_type") == "audio"
    ]
    if len(video_items) != 1 or len(audio_items) != 1:
        _fail(f"{stage} must contain exactly one video and one audio stream")
    video = video_items[0]
    audio = audio_items[0]
    format_value = value.get("format")
    if type(format_value) is not dict:
        _fail(f"{stage} omitted format metadata")
    return {
        "format_duration_ms": _duration_ms(
            format_value.get("duration"), f"{stage} format duration"
        ),
        "video": {
            "codec_name": video.get("codec_name"),
            "pix_fmt": video.get("pix_fmt"),
            "width": video.get("width"),
            "height": video.get("height"),
            "frame_rate": _parse_rate(
                video.get("avg_frame_rate"), f"{stage} video frame rate"
            ),
            "duration_ms": _duration_ms(
                video.get("duration"), f"{stage} video duration"
            ),
            "color_range": video.get("color_range"),
            "color_space": video.get("color_space"),
            "color_transfer": video.get("color_transfer"),
            "color_primaries": video.get("color_primaries"),
        },
        "audio": {
            "codec_name": audio.get("codec_name"),
            "sample_rate": int(audio.get("sample_rate", 0)),
            "channels": audio.get("channels"),
            "duration_ms": _duration_ms(
                audio.get("duration"), f"{stage} audio duration"
            ),
        },
    }


def _validate_source_probe(
    facts: dict[str, Any], expected_color: dict[str, str], label: str,
) -> int:
    video = facts["video"]
    audio = facts["audio"]
    exact_video = {
        key: video[key]
        for key in (
            "codec_name", "pix_fmt", "color_range", "color_space",
            "color_transfer", "color_primaries",
        )
    }
    if exact_video != expected_color:
        _fail(f"{label} color declaration does not match its fixed fixture")
    if (
        video["width"] != WIDTH
        or video["height"] != HEIGHT
        or video["frame_rate"]
        != (FRAME_RATE_NUMERATOR, FRAME_RATE_DENOMINATOR)
        or video["duration_ms"] < SOURCE_SELECTION_MS
    ):
        _fail(f"{label} video geometry, rate, or duration is invalid")
    if (
        audio["sample_rate"] != AUDIO_SAMPLE_RATE
        or audio["channels"] != AUDIO_CHANNELS
        or audio["duration_ms"] < SOURCE_SELECTION_MS
    ):
        _fail(f"{label} audio format or duration is invalid")
    return min(
        facts["format_duration_ms"],
        video["duration_ms"],
        audio["duration_ms"],
    )


def _auto_values() -> dict[str, str]:
    return {
        "cut_density": "auto",
        "sfx_density": "auto",
        "transition_density": "auto",
        "dialogue_rule": "auto",
        "music_rule": "auto",
        "caption_rule": "auto",
        "visualization_rule": "auto",
    }


def _policy() -> dict[str, Any]:
    explicit = _auto_values()
    explicit["transition_density"] = "dense"
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": "commercial_product",
        "duration_ms": SOURCE_SELECTION_MS * 2,
        "delivery": {"platform": "youtube", "aspect": "auto"},
        "explicit_intent": explicit,
        "consented_preferences": {
            "consented": False,
            "values": _auto_values(),
        },
        "available_capabilities": sorted(CAPABILITIES),
    })


def _segment(index: int, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": f"probe-segment-{index}",
        "source_id": source["source_id"],
        "source_sha256": source["sha256"],
        "source_start_ms": 0,
        "source_end_ms": SOURCE_SELECTION_MS,
        "role": "development",
        "reason": "Fixed offline production render capability proof.",
        "speech_anchor": None,
        "transition": {"kind": "hard_cut"},
    }


def _build_production_render(
    *,
    source_a: Path,
    source_b: Path,
    source_a_facts: dict[str, Any],
    source_b_facts: dict[str, Any],
    source_a_color: dict[str, str],
    output: Path,
    ffmpeg: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        source_color_conversion_filter(source_a_color)
    except ColorContractError as error:
        raise RenderCapabilityRuntimeProbeError(
            "fixed source A color is unsupported or HDR"
        ) from error
    source_paths = (source_a, source_b)
    facts = (source_a_facts, source_b_facts)
    sources = []
    for index, (path, item_facts) in enumerate(zip(source_paths, facts)):
        duration_ms = min(
            item_facts["format_duration_ms"],
            item_facts["video"]["duration_ms"],
            item_facts["audio"]["duration_ms"],
        )
        sources.append({
            "source_id": f"probe-source-{index}",
            "sha256": _sha256_file(path),
            "duration_ms": duration_ms,
        })
    source_manifest = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sources": copy.deepcopy(sources),
    }
    sequence_plan = {
        "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
        "sources": copy.deepcopy(sources),
        "target_duration": {
            "min_ms": SOURCE_SELECTION_MS * 2,
            "max_ms": SOURCE_SELECTION_MS * 2,
        },
        "segments": [
            _segment(index, source) for index, source in enumerate(sources)
        ],
    }
    compiled_sequence = compile_sequence_plan(sequence_plan, source_manifest)
    transition_manifest = {
        "schema_version": TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
        "sequence_plan_sha256": compiled_sequence["receipt"][
            "sequence_plan_sha256"
        ],
        "sequence_compile_receipt_sha256": compiled_sequence["receipt_sha256"],
        "frame_rate": {
            "numerator": FRAME_RATE_NUMERATOR,
            "denominator": FRAME_RATE_DENOMINATOR,
        },
        "segments": [{
            "segment_id": item["segment_id"],
            "source_sha256": item["source_sha256"],
            "duration_ms": item["duration_ms"],
            "video_leading_handle_ms": TRANSITION_DURATION_MS,
            "video_trailing_handle_ms": TRANSITION_DURATION_MS,
            "audio_leading_handle_ms": TRANSITION_DURATION_MS,
            "audio_trailing_handle_ms": TRANSITION_DURATION_MS,
            "dialogue_at_start": False,
            "dialogue_at_end": False,
        } for item in compiled_sequence["ffmpeg_segments"]],
    }
    policy = _policy()
    left, right = transition_manifest["segments"]
    boundary = {
        "boundary_id": derive_boundary_id(
            left["segment_id"], right["segment_id"],
            left["source_sha256"], right["source_sha256"],
            SOURCE_SELECTION_MS,
        ),
        "left_segment_id": left["segment_id"],
        "right_segment_id": right["segment_id"],
        "left_source_sha256": left["source_sha256"],
        "right_source_sha256": right["source_sha256"],
        "cumulative_boundary_ms": SOURCE_SELECTION_MS,
        "kind": "cross_dissolve",
        "motivation": policy["rules"]["transitions"]["usage"],
        "duration_ms": TRANSITION_DURATION_MS,
        "audio_behavior": "equal_power_crossfade",
        "motivation_verified": True,
        "semantic_safety_verified": True,
        "dialogue_preservation_verified": True,
    }
    transition_plan = {
        "schema_version": TRANSITION_PLAN_SCHEMA_VERSION,
        "sequence_manifest_sha256": transition_sequence_manifest_sha256(
            transition_manifest
        ),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "frame_rate": copy.deepcopy(transition_manifest["frame_rate"]),
        "policy": copy.deepcopy(policy["rules"]["transitions"]),
        "boundaries": [boundary],
    }
    compiled_transition = compile_transition_plan(
        transition_plan, transition_manifest, policy
    )

    render_sources = []
    for index, (source, path, item_facts) in enumerate(
        zip(sources, source_paths, facts)
    ):
        color = source_a_color if index == 0 else SOURCE_B_COLOR
        render_sources.append({
            **copy.deepcopy(source),
            "path": str(path),
            "video": {
                "width": WIDTH,
                "height": HEIGHT,
                "fps_numerator": FRAME_RATE_NUMERATOR,
                "fps_denominator": FRAME_RATE_DENOMINATOR,
                "start_offset_ms": 0,
                "duration_ms": source["duration_ms"],
                "end_offset_ms": source["duration_ms"],
                **copy.deepcopy(color),
            },
            "audio": {
                "present": True,
                "sample_rate": AUDIO_SAMPLE_RATE,
                "channels": AUDIO_CHANNELS,
                "start_offset_ms": 0,
                "duration_ms": source["duration_ms"],
                "end_offset_ms": source["duration_ms"],
            },
        })
    render_manifest = {
        "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
        "output": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps_numerator": FRAME_RATE_NUMERATOR,
            "fps_denominator": FRAME_RATE_DENOMINATOR,
        },
        "sources": render_sources,
    }
    render = build_transition_render(
        compiled_sequence,
        {source["source_id"]: str(path)
         for source, path in zip(sources, source_paths)},
        render_manifest,
        compiled_transition,
        output,
        ffmpeg_path=ffmpeg,
    )
    production = {
        "edit_policy_sha256": edit_policy_sha256(policy),
        "sequence_plan_sha256": compiled_sequence["receipt"][
            "sequence_plan_sha256"
        ],
        "sequence_compile_receipt_sha256": compiled_sequence["receipt_sha256"],
        "transition_plan_sha256": compiled_transition["receipt"][
            "transition_plan_sha256"
        ],
        "transition_compile_receipt_sha256": compiled_transition["receipt_sha256"],
        "transition_render_receipt_sha256": transition_render_receipt_sha256(
            render["executor_receipt"]
        ),
        "topology_sha256": render["topology_sha256"],
        "filter_complex_sha256": render["executor_receipt"][
            "filter_complex_sha256"
        ],
    }
    return render, production


def _normalization_filter(color: dict[str, str]) -> str:
    fps = f"{FRAME_RATE_NUMERATOR}/{FRAME_RATE_DENOMINATOR}"
    return (
        f"trim=duration={SOURCE_SELECTION_MS // 1000}."
        f"{SOURCE_SELECTION_MS % 1000:03d},setpts=PTS-STARTPTS,"
        f"{source_color_conversion_filter(color)},"
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:"
        "flags=lanczos,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps=fps={fps}:round=near,setsar=1,format=yuv420p,"
        "setparams=range=tv:color_primaries=bt709:"
        "color_trc=bt709:colorspace=bt709"
    )


def _decode_raw_video(
    ffmpeg: Path,
    path: Path,
    *,
    pixel_format: str,
    video_filter: str | None,
    stage: str,
    execute: Callable[..., object] | None,
) -> bytes:
    command = [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if video_filter is not None:
        command.extend(DETERMINISTIC_COLOR_FILTER_ARGS)
    command.extend([
        "-i", str(path), "-map", "0:v:0", "-an", "-sn", "-dn",
    ])
    if video_filter is not None:
        command.extend(["-vf", video_filter])
    command.extend([
        "-pix_fmt", pixel_format, "-f", "rawvideo", "pipe:1",
    ])
    return _run(
        command, stage=stage, timeout=90, execute=execute,
    ).stdout


def _video_frames(payload: bytes, pixel_format: str) -> list[bytes]:
    if pixel_format == "rgb24":
        frame_bytes = WIDTH * HEIGHT * 3
    elif pixel_format == "yuv420p":
        frame_bytes = WIDTH * HEIGHT * 3 // 2
    else:
        _fail("fixed raw pixel format is unsupported")
    if not payload or len(payload) % frame_bytes:
        _fail("decoded raw video has a partial or empty frame")
    return [
        payload[index:index + frame_bytes]
        for index in range(0, len(payload), frame_bytes)
    ]


def _decode_pcm(
    ffmpeg: Path,
    path: Path,
    *,
    execute: Callable[..., object] | None,
) -> list[int]:
    command = [
        str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(path), "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ar", str(AUDIO_SAMPLE_RATE), "-ac", str(AUDIO_CHANNELS),
        "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ]
    payload = _run(
        command, stage="artifact PCM decode", timeout=90, execute=execute,
    ).stdout
    if not payload or len(payload) % 2:
        _fail("decoded artifact audio is empty or partial")
    return [item[0] for item in struct.iter_unpack("<h", payload)]


def _mean_absolute_error_millionths(left: bytes, right: bytes) -> int:
    if len(left) != len(right) or not left:
        _fail("pixel evidence frame cardinality does not match")
    difference = sum(abs(a - b) for a, b in zip(left, right))
    return round(difference * 1_000_000 / (len(left) * 255))


def _frame_summary(frame: bytes, index: int) -> dict[str, Any]:
    pixels = len(frame) // 3
    if pixels != WIDTH * HEIGHT:
        _fail("RGB frame geometry is invalid")
    red = green = blue = black = luma_total = 0
    for offset in range(0, len(frame), 3):
        r, g, b = frame[offset], frame[offset + 1], frame[offset + 2]
        red += r
        green += g
        blue += b
        luma_total += 54 * r + 183 * g + 19 * b
        if r <= 8 and g <= 8 and b <= 8:
            black += 1
    return {
        "frame_index": index,
        "sha256": _sha256_bytes(frame),
        "mean_rgb": [
            round(red * 1_000_000 / (pixels * 255)),
            round(green * 1_000_000 / (pixels * 255)),
            round(blue * 1_000_000 / (pixels * 255)),
        ],
        "mean_luma_millionths": round(
            luma_total * 1_000_000 / (pixels * 255 * 256)
        ),
        "black_pixel_ratio_millionths": round(black * 1_000_000 / pixels),
    }


def _estimated_blend(
    candidate: bytes, left: bytes, right: bytes,
) -> tuple[int, int]:
    if not candidate or len(candidate) != len(left) or len(left) != len(right):
        _fail("cross-dissolve frame cardinality does not match")
    numerator = 0
    denominator = 0
    for output_value, left_value, right_value in zip(candidate, left, right):
        delta = right_value - left_value
        numerator += (output_value - left_value) * delta
        denominator += delta * delta
    if denominator < len(candidate):
        _fail("fixed cross-dissolve endpoints are not visually distinct")
    weight = max(0.0, min(1.0, numerator / denominator))
    residual = 0.0
    for output_value, left_value, right_value in zip(candidate, left, right):
        expected = left_value + (right_value - left_value) * weight
        residual += abs(output_value - expected)
    return (
        round(weight * 1_000_000),
        round(residual * 1_000_000 / (len(candidate) * 255)),
    )


def _mono_window(
    interleaved: list[int], start_ms: int, duration_ms: int,
) -> list[float]:
    first = round(start_ms * AUDIO_SAMPLE_RATE / 1000)
    count = round(duration_ms * AUDIO_SAMPLE_RATE / 1000)
    total_frames = len(interleaved) // AUDIO_CHANNELS
    if first < 0 or count < 1 or first + count > total_frames:
        _fail("audio evidence window exceeds decoded artifact audio")
    return [
        sum(interleaved[(first + index) * AUDIO_CHANNELS:
                        (first + index + 1) * AUDIO_CHANNELS])
        / (AUDIO_CHANNELS * 32768.0)
        for index in range(count)
    ]


def _tone_amplitude(samples: list[float], frequency_hz: int) -> float:
    count = len(samples)
    real = imaginary = 0.0
    for index, sample in enumerate(samples):
        phase = 2.0 * math.pi * frequency_hz * index / AUDIO_SAMPLE_RATE
        real += sample * math.cos(phase)
        imaginary -= sample * math.sin(phase)
    return 2.0 * math.hypot(real, imaginary) / count


def _audio_window_evidence(
    interleaved: list[int], start_ms: int,
) -> dict[str, int]:
    samples = _mono_window(interleaved, start_ms, 100)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    return {
        "start_ms": start_ms,
        "duration_ms": 100,
        "tone_440_millionths": round(
            _tone_amplitude(samples, SOURCE_A_FREQUENCY_HZ) * 1_000_000
        ),
        "tone_880_millionths": round(
            _tone_amplitude(samples, SOURCE_B_FREQUENCY_HZ) * 1_000_000
        ),
        "rms_millionths": round(rms * 1_000_000),
    }


def _artifact_evidence(
    *,
    ffmpeg: Path,
    ffprobe: Path,
    artifact: Path,
    source_a: Path,
    source_b: Path,
    source_a_color: dict[str, str],
    execute: Callable[..., object] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = _probe_media(
        ffprobe, artifact, stage="rendered artifact probe", execute=execute
    )
    video = facts["video"]
    audio = facts["audio"]
    if (
        video["codec_name"] != "h264"
        or video["pix_fmt"] != "yuv420p"
        or video["width"] != WIDTH
        or video["height"] != HEIGHT
        or video["frame_rate"]
        != (FRAME_RATE_NUMERATOR, FRAME_RATE_DENOMINATOR)
        or {key: video[key] for key in (
            "color_range", "color_space", "color_transfer", "color_primaries"
        )} != {
            "color_range": "tv",
            "color_space": "bt709",
            "color_transfer": "bt709",
            "color_primaries": "bt709",
        }
    ):
        _fail("rendered artifact video delivery format is invalid")
    if audio["sample_rate"] != AUDIO_SAMPLE_RATE or audio["channels"] != 2:
        _fail("rendered artifact audio is not decoded 48 kHz stereo")

    artifact_rgb = _video_frames(_decode_raw_video(
        ffmpeg, artifact, pixel_format="rgb24", video_filter=None,
        stage="artifact RGB frame decode", execute=execute,
    ), "rgb24")
    artifact_yuv = _video_frames(_decode_raw_video(
        ffmpeg, artifact, pixel_format="yuv420p", video_filter=None,
        stage="artifact YUV frame decode", execute=execute,
    ), "yuv420p")
    reference_a_rgb = _video_frames(_decode_raw_video(
        ffmpeg, source_a, pixel_format="rgb24",
        video_filter=_normalization_filter(source_a_color),
        stage="BT.470 normalized RGB reference decode", execute=execute,
    ), "rgb24")
    reference_b_rgb = _video_frames(_decode_raw_video(
        ffmpeg, source_b, pixel_format="rgb24",
        video_filter=_normalization_filter(SOURCE_B_COLOR),
        stage="BT.709 normalized RGB reference decode", execute=execute,
    ), "rgb24")
    reference_a_yuv = _video_frames(_decode_raw_video(
        ffmpeg, source_a, pixel_format="yuv420p",
        video_filter=_normalization_filter(source_a_color),
        stage="BT.470 normalized YUV reference decode", execute=execute,
    ), "yuv420p")
    unnormalized_a_yuv = _video_frames(_decode_raw_video(
        ffmpeg, source_a, pixel_format="yuv420p",
        video_filter=(
            f"trim=duration={SOURCE_SELECTION_MS / 1000:.3f},"
            "setpts=PTS-STARTPTS,format=yuv420p"
        ),
        stage="BT.470 unnormalized YUV decode", execute=execute,
    ), "yuv420p")

    expected_frames = round(
        EXPECTED_OUTPUT_MS * FRAME_RATE_NUMERATOR
        / (1000 * FRAME_RATE_DENOMINATOR)
    )
    if len(artifact_rgb) != len(artifact_yuv) or abs(
        len(artifact_rgb) - expected_frames
    ) > 1:
        _fail("rendered artifact video frame extent is invalid")
    if min(len(reference_a_rgb), len(reference_a_yuv), len(unnormalized_a_yuv)) < 90:
        _fail("BT.470 reference did not decode the fixed selected extent")
    if len(reference_b_rgb) < 14:
        _fail("BT.709 reference did not decode enough transition frames")

    color_index = 30
    color_transform_delta = _mean_absolute_error_millionths(
        unnormalized_a_yuv[color_index], reference_a_yuv[color_index]
    )
    color_reference_error = _mean_absolute_error_millionths(
        artifact_yuv[color_index], reference_a_yuv[color_index]
    )
    if color_transform_delta < 5_000:
        _fail("fixed BT.470 fixture did not require a real pixel conversion")
    if color_reference_error > 35_000:
        _fail("color normalization pixels do not match the BT.709 reference")

    transition_start_frame = round(
        (SOURCE_SELECTION_MS - TRANSITION_DURATION_MS)
        * FRAME_RATE_NUMERATOR
        / (1000 * FRAME_RATE_DENOMINATOR)
    )
    transition_frames = round(
        TRANSITION_DURATION_MS * FRAME_RATE_NUMERATOR
        / (1000 * FRAME_RATE_DENOMINATOR)
    )
    before_index = transition_start_frame - 1
    middle_index = transition_start_frame + transition_frames // 2
    after_index = transition_start_frame + transition_frames + 1
    if after_index >= len(artifact_rgb):
        _fail("rendered artifact omitted transition evidence frames")

    weights: list[int] = []
    residuals: list[int] = []
    for local_index in range(transition_frames):
        output_index = transition_start_frame + local_index
        weight, residual = _estimated_blend(
            artifact_rgb[output_index],
            reference_a_rgb[output_index],
            reference_b_rgb[local_index],
        )
        weights.append(weight)
        residuals.append(residual)
    if (
        weights[0] > 200_000
        or weights[-1] < 700_000
        or weights[transition_frames // 2] < 300_000
        or weights[transition_frames // 2] > 750_000
        or any(right + 70_000 < left for left, right in zip(weights, weights[1:]))
        or max(residuals) > 75_000
    ):
        _fail("cross-dissolve blend progression is absent or discontinuous")

    continuity_indices = list(range(
        transition_start_frame - 1,
        transition_start_frame + transition_frames + 2,
    ))
    summaries = {
        index: _frame_summary(artifact_rgb[index], index)
        for index in continuity_indices
    }
    adjacent_errors = [
        _mean_absolute_error_millionths(
            artifact_rgb[left], artifact_rgb[right]
        )
        for left, right in zip(continuity_indices, continuity_indices[1:])
    ]
    max_black_ratio = max(
        item["black_pixel_ratio_millionths"] for item in summaries.values()
    )
    min_luma = min(
        item["mean_luma_millionths"] for item in summaries.values()
    )
    if (
        max_black_ratio > 100_000
        or min_luma < 80_000
        or max(adjacent_errors) > 250_000
        or len({item["sha256"] for item in summaries.values()})
        != len(summaries)
    ):
        _fail("motion continuity or no-black-flash evidence failed")

    interleaved = _decode_pcm(ffmpeg, artifact, execute=execute)
    if len(interleaved) % AUDIO_CHANNELS:
        _fail("decoded artifact audio channel alignment is invalid")
    audio_frames = len(interleaved) // AUDIO_CHANNELS
    before_audio = _audio_window_evidence(interleaved, 2_450)
    middle_audio = _audio_window_evidence(interleaved, 2_750)
    after_audio = _audio_window_evidence(interleaved, 3_050)
    if (
        before_audio["tone_440_millionths"] < 40_000
        or before_audio["tone_880_millionths"]
        > before_audio["tone_440_millionths"] // 5
        or after_audio["tone_880_millionths"] < 40_000
        or after_audio["tone_440_millionths"]
        > after_audio["tone_880_millionths"] // 5
        or middle_audio["tone_440_millionths"]
        < before_audio["tone_440_millionths"] // 4
        or middle_audio["tone_880_millionths"]
        < after_audio["tone_880_millionths"] // 4
        or middle_audio["rms_millionths"]
        < min(before_audio["rms_millionths"], after_audio["rms_millionths"])
        * 3 // 4
    ):
        _fail("equal-power audio overlap is absent from the fixed boundary")

    video_duration_us = round(
        len(artifact_rgb) * FRAME_RATE_DENOMINATOR * 1_000_000
        / FRAME_RATE_NUMERATOR
    )
    audio_duration_us = round(audio_frames * 1_000_000 / AUDIO_SAMPLE_RATE)
    av_drift_us = abs(video_duration_us - audio_duration_us)
    if (
        abs(video_duration_us - EXPECTED_OUTPUT_MS * 1000) > 34_000
        or abs(audio_duration_us - EXPECTED_OUTPUT_MS * 1000) > 25_000
        or av_drift_us > 34_000
    ):
        _fail("rendered artifact A/V extent or drift is outside one frame")

    artifact_identity = {
        "file": RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE,
        "sha256": _sha256_file(artifact),
        "bytes": artifact.stat().st_size,
        "expected_duration_ms": EXPECTED_OUTPUT_MS,
        "video_frames": len(artifact_rgb),
        "audio_sample_frames": audio_frames,
        "video_duration_us": video_duration_us,
        "audio_duration_us": audio_duration_us,
        "av_drift_us": av_drift_us,
        "width": WIDTH,
        "height": HEIGHT,
        "frame_rate": {
            "numerator": FRAME_RATE_NUMERATOR,
            "denominator": FRAME_RATE_DENOMINATOR,
        },
        "audio": {"sample_rate": AUDIO_SAMPLE_RATE, "channels": 2},
        "delivery_color": {
            "range": "tv",
            "space": "bt709",
            "transfer": "bt709",
            "primaries": "bt709",
            "pixel_format": "yuv420p",
        },
    }
    evidence = {
        "color": {
            "source_declaration": copy.deepcopy(source_a_color),
            "normalization_mode": source_color_normalization_mode(source_a_color),
            "conversion_filter_sha256": _sha256_bytes(
                source_color_conversion_filter(source_a_color).encode("ascii")
            ),
            "frame_index": color_index,
            "source_yuv_sha256": _sha256_bytes(
                unnormalized_a_yuv[color_index]
            ),
            "normalized_reference_yuv_sha256": _sha256_bytes(
                reference_a_yuv[color_index]
            ),
            "artifact_yuv_sha256": _sha256_bytes(artifact_yuv[color_index]),
            "source_to_normalized_mae_millionths": color_transform_delta,
            "artifact_to_reference_mae_millionths": color_reference_error,
        },
        "transition": {
            "kind": "cross_dissolve",
            "duration_ms": TRANSITION_DURATION_MS,
            "duration_frames": transition_frames,
            "start_frame": transition_start_frame,
            "estimated_right_weights_millionths": weights,
            "blend_residuals_millionths": residuals,
            "before": summaries[before_index],
            "middle": summaries[middle_index],
            "after": summaries[after_index],
            "max_adjacent_rgb_mae_millionths": max(adjacent_errors),
            "max_black_pixel_ratio_millionths": max_black_ratio,
            "min_mean_luma_millionths": min_luma,
        },
        "audio_crossfade": {
            "behavior": "equal_power_qsin",
            "transition_start_ms": SOURCE_SELECTION_MS - TRANSITION_DURATION_MS,
            "duration_ms": TRANSITION_DURATION_MS,
            "before": before_audio,
            "middle": middle_audio,
            "after": after_audio,
        },
    }
    return artifact_identity, evidence


def _validate_probe_result(value: object) -> dict[str, Any]:
    raw = _exact_dict(value, frozenset({
        "schema_version", "checks", "scope", "fixture", "runtime",
        "production", "artifact", "evidence",
    }), "render capability receipt")
    if raw["schema_version"] != RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION:
        _fail("render capability receipt schema_version is unsupported")
    checks = _exact_dict(
        raw["checks"], RENDER_CAPABILITY_CHECK_NAMES,
        "render capability receipt checks",
    )
    if any(value is not True for value in checks.values()):
        _fail("render capability receipt contains an unproved capability")
    if raw["scope"] != _SCOPE:
        _fail("render capability receipt scope is unsupported")

    fixture = _exact_dict(raw["fixture"], frozenset({
        "schema_version", "sha256", "frame_rate", "geometry",
        "source_selection_ms", "transition_duration_ms", "audio",
        "sources",
    }), "render capability receipt fixture")
    if fixture["schema_version"] != RENDER_CAPABILITY_RUNTIME_PROBE_FIXTURE_SCHEMA_VERSION:
        _fail("render capability fixture schema_version is unsupported")
    supplied_fixture_hash = _digest(
        fixture["sha256"], "render capability fixture sha256"
    )
    fixture_without_hash = {
        key: copy.deepcopy(item) for key, item in fixture.items()
        if key != "sha256"
    }
    if _canonical_sha256(fixture_without_hash) != supplied_fixture_hash:
        _fail("render capability fixture hash does not match")
    if fixture["frame_rate"] != {
        "numerator": FRAME_RATE_NUMERATOR,
        "denominator": FRAME_RATE_DENOMINATOR,
    } or fixture["geometry"] != {"width": WIDTH, "height": HEIGHT}:
        _fail("render capability fixture rate or geometry changed")
    if (
        fixture["source_selection_ms"] != SOURCE_SELECTION_MS
        or fixture["transition_duration_ms"] != TRANSITION_DURATION_MS
        or fixture["audio"] != {
            "sample_rate": AUDIO_SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
            "source_a_frequency_hz": SOURCE_A_FREQUENCY_HZ,
            "source_b_frequency_hz": SOURCE_B_FREQUENCY_HZ,
        }
    ):
        _fail("render capability fixture timing or audio changed")
    sources = fixture["sources"]
    if type(sources) is not list or len(sources) != 2:
        _fail("render capability fixture source inventory changed")
    expected_sources = (
        (
            "source-a-bt470bg",
            RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE,
            SOURCE_A_COLOR,
        ),
        (
            "source-b-bt709",
            RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_B_FILE,
            SOURCE_B_COLOR,
        ),
    )
    for index, (item, expected_source) in enumerate(
        zip(sources, expected_sources)
    ):
        source = _exact_dict(item, frozenset({
            "id", "file", "sha256", "bytes", "duration_ms", "color",
            "generator_filter_sha256",
        }), f"render capability fixture source {index}")
        expected_id, expected_file, expected_color = expected_source
        if (
            source["id"] != expected_id
            or _safe_file_name(
                source["file"], f"render capability fixture source {index} file"
            ) != expected_file
            or source["color"] != expected_color
        ):
            _fail("render capability fixture source identity changed")
        _digest(source["sha256"],
                f"render capability fixture source {index} sha256")
        _digest(
            source["generator_filter_sha256"],
            f"render capability fixture source {index} generator sha256",
        )
        _integer(
            source["bytes"], f"render capability fixture source {index} bytes",
            minimum=1,
        )
        _integer(
            source["duration_ms"],
            f"render capability fixture source {index} duration",
            minimum=SOURCE_SELECTION_MS,
            maximum=5_000,
        )

    runtime = _exact_dict(
        raw["runtime"], frozenset({"host", "ffmpeg", "ffprobe", "contract"}),
        "render capability receipt runtime",
    )
    for name in ("host", "ffmpeg", "ffprobe"):
        item = _exact_dict(runtime[name], frozenset({"file", "sha256", "bytes"}),
                           f"render capability runtime {name}")
        _safe_file_name(item["file"], f"render capability runtime {name} file")
        _digest(item["sha256"], f"render capability runtime {name} sha256")
        _integer(item["bytes"], f"render capability runtime {name} bytes",
                 minimum=1, maximum=MAX_TOOL_BYTES)
    contract = _exact_dict(runtime["contract"], frozenset({
        "sha256", "schemas",
    }), "render capability runtime contract")
    expected_schemas = [
        RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION,
        RENDER_CAPABILITY_RUNTIME_PROBE_FIXTURE_SCHEMA_VERSION,
        SEQUENCE_PLAN_SCHEMA_VERSION,
        SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
        TRANSITION_PLAN_SCHEMA_VERSION,
    ]
    if contract["schemas"] != expected_schemas:
        _fail("render capability runtime contract schemas changed")
    if _canonical_sha256(contract["schemas"]) != _digest(
        contract["sha256"], "render capability runtime contract sha256"
    ):
        _fail("render capability runtime contract hash does not match")

    production = _exact_dict(raw["production"], frozenset({
        "edit_policy_sha256", "sequence_plan_sha256",
        "sequence_compile_receipt_sha256", "transition_plan_sha256",
        "transition_compile_receipt_sha256",
        "transition_render_receipt_sha256", "topology_sha256",
        "filter_complex_sha256",
    }), "render capability receipt production")
    for key, item in production.items():
        _digest(item, f"render capability production {key}")

    artifact = _exact_dict(raw["artifact"], frozenset({
        "file", "sha256", "bytes", "expected_duration_ms", "video_frames",
        "audio_sample_frames", "video_duration_us", "audio_duration_us",
        "av_drift_us", "width", "height", "frame_rate", "audio",
        "delivery_color",
    }), "render capability receipt artifact")
    if _safe_file_name(artifact["file"], "render capability artifact file") != (
        RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE
    ):
        _fail("render capability artifact file is unsupported")
    _digest(artifact["sha256"], "render capability artifact sha256")
    _integer(artifact["bytes"], "render capability artifact bytes", minimum=1)
    if (
        artifact["expected_duration_ms"] != EXPECTED_OUTPUT_MS
        or artifact["width"] != WIDTH
        or artifact["height"] != HEIGHT
        or artifact["frame_rate"] != fixture["frame_rate"]
        or artifact["audio"] != {
            "sample_rate": AUDIO_SAMPLE_RATE, "channels": AUDIO_CHANNELS,
        }
        or artifact["delivery_color"] != {
            "range": "tv", "space": "bt709", "transfer": "bt709",
            "primaries": "bt709", "pixel_format": "yuv420p",
        }
    ):
        _fail("render capability artifact delivery contract changed")
    if _integer(artifact["av_drift_us"], "render capability artifact drift") > 34_000:
        _fail("render capability artifact drift exceeds one frame")
    if (
        not 167 <= _integer(
            artifact["video_frames"], "render capability artifact video frames"
        ) <= 169
        or not 268_000 <= _integer(
            artifact["audio_sample_frames"],
            "render capability artifact audio frames",
        ) <= 270_500
        or not 5_570_000 <= _integer(
            artifact["video_duration_us"],
            "render capability artifact video duration",
        ) <= 5_634_000
        or not 5_575_000 <= _integer(
            artifact["audio_duration_us"],
            "render capability artifact audio duration",
        ) <= 5_625_000
    ):
        _fail("render capability artifact decoded extent changed")

    evidence = _exact_dict(raw["evidence"], frozenset({
        "color", "transition", "audio_crossfade",
    }), "render capability receipt evidence")
    color = _exact_dict(evidence["color"], frozenset({
        "source_declaration", "normalization_mode", "conversion_filter_sha256",
        "frame_index", "source_yuv_sha256",
        "normalized_reference_yuv_sha256", "artifact_yuv_sha256",
        "source_to_normalized_mae_millionths",
        "artifact_to_reference_mae_millionths",
    }), "render capability color evidence")
    if color["source_declaration"] != SOURCE_A_COLOR:
        _fail("render capability color source declaration changed")
    if color["normalization_mode"] != "declared_sdr_to_bt709_tv":
        _fail("render capability color normalization mode is unsupported")
    if _integer(
        color["source_to_normalized_mae_millionths"],
        "render capability color transform delta",
    ) < 5_000 or _integer(
        color["artifact_to_reference_mae_millionths"],
        "render capability color reference error",
    ) > 35_000:
        _fail("render capability color pixel evidence is insufficient")
    if color["frame_index"] != 30:
        _fail("render capability color evidence frame changed")
    for key in (
        "conversion_filter_sha256", "source_yuv_sha256",
        "normalized_reference_yuv_sha256", "artifact_yuv_sha256",
    ):
        _digest(color[key], f"render capability color evidence {key}")
    expected_filter_hash = _sha256_bytes(
        source_color_conversion_filter(SOURCE_A_COLOR).encode("ascii")
    )
    if color["conversion_filter_sha256"] != expected_filter_hash:
        _fail("render capability production color filter identity changed")
    if color["source_yuv_sha256"] == color["normalized_reference_yuv_sha256"]:
        _fail("render capability color evidence is a relabel-only result")

    transition = _exact_dict(evidence["transition"], frozenset({
        "kind", "duration_ms", "duration_frames", "start_frame",
        "estimated_right_weights_millionths", "blend_residuals_millionths",
        "before", "middle", "after", "max_adjacent_rgb_mae_millionths",
        "max_black_pixel_ratio_millionths", "min_mean_luma_millionths",
    }), "render capability transition evidence")
    weights = transition["estimated_right_weights_millionths"]
    residuals = transition["blend_residuals_millionths"]
    if (
        transition["kind"] != "cross_dissolve"
        or transition["duration_ms"] != TRANSITION_DURATION_MS
        or transition["duration_frames"] != 12
        or transition["start_frame"] != 78
        or type(weights) is not list
        or len(weights) != 12
        or any(type(item) is not int or not 0 <= item <= 1_000_000
               for item in weights)
        or weights[0] > 200_000
        or weights[-1] < 700_000
        or weights[6] < 300_000
        or weights[6] > 750_000
        or any(right + 70_000 < left
               for left, right in zip(weights, weights[1:]))
        or type(residuals) is not list
        or len(residuals) != 12
        or any(type(item) is not int or not 0 <= item <= 75_000
               for item in residuals)
        or type(transition["max_adjacent_rgb_mae_millionths"]) is not int
        or not 0 < transition["max_adjacent_rgb_mae_millionths"] <= 250_000
        or transition["max_black_pixel_ratio_millionths"] > 100_000
        or transition["min_mean_luma_millionths"] < 80_000
    ):
        _fail("render capability transition evidence is insufficient")
    for name, expected_index in (
        ("before", 77), ("middle", 84), ("after", 91),
    ):
        summary = _exact_dict(transition[name], frozenset({
            "frame_index", "sha256", "mean_rgb", "mean_luma_millionths",
            "black_pixel_ratio_millionths",
        }), f"render capability transition {name} frame")
        if summary["frame_index"] != expected_index:
            _fail("render capability transition sample frame changed")
        _digest(summary["sha256"],
                f"render capability transition {name} frame sha256")
        if (type(summary["mean_rgb"]) is not list
                or len(summary["mean_rgb"]) != 3
                or any(type(item) is not int or not 0 <= item <= 1_000_000
                       for item in summary["mean_rgb"])
                or type(summary["mean_luma_millionths"]) is not int
                or not 80_000 <= summary["mean_luma_millionths"] <= 1_000_000
                or type(summary["black_pixel_ratio_millionths"]) is not int
                or not 0 <= summary["black_pixel_ratio_millionths"] <= 100_000):
            _fail("render capability transition frame evidence changed")
    if len({transition[name]["sha256"]
            for name in ("before", "middle", "after")}) != 3:
        _fail("render capability transition sample frames are not distinct")

    audio_evidence = _exact_dict(
        evidence["audio_crossfade"], frozenset({
            "behavior", "transition_start_ms", "duration_ms",
            "before", "middle", "after",
        }), "render capability audio-crossfade evidence",
    )
    if (
        audio_evidence["behavior"] != "equal_power_qsin"
        or audio_evidence["transition_start_ms"]
        != SOURCE_SELECTION_MS - TRANSITION_DURATION_MS
        or audio_evidence["duration_ms"] != TRANSITION_DURATION_MS
    ):
        _fail("render capability audio-crossfade evidence is insufficient")
    audio_windows = {}
    for name, expected_start in (
        ("before", 2_450), ("middle", 2_750), ("after", 3_050),
    ):
        window = _exact_dict(audio_evidence[name], frozenset({
            "start_ms", "duration_ms", "tone_440_millionths",
            "tone_880_millionths", "rms_millionths",
        }), f"render capability audio {name} window")
        if window["start_ms"] != expected_start or window["duration_ms"] != 100:
            _fail("render capability audio evidence window changed")
        for key in (
            "tone_440_millionths", "tone_880_millionths", "rms_millionths",
        ):
            _integer(window[key], f"render capability audio {name} {key}",
                     maximum=1_000_000)
        audio_windows[name] = window
    before = audio_windows["before"]
    middle = audio_windows["middle"]
    after = audio_windows["after"]
    if (
        before["tone_440_millionths"] < 40_000
        or before["tone_880_millionths"]
        > before["tone_440_millionths"] // 5
        or after["tone_880_millionths"] < 40_000
        or after["tone_440_millionths"]
        > after["tone_880_millionths"] // 5
        or middle["tone_440_millionths"]
        < before["tone_440_millionths"] // 4
        or middle["tone_880_millionths"]
        < after["tone_880_millionths"] // 4
        or middle["rms_millionths"]
        < min(before["rms_millionths"], after["rms_millionths"]) * 3 // 4
    ):
        _fail("render capability audio overlap evidence is insufficient")

    # Canonical round-trip also rejects non-finite values or non-JSON types.
    _canonical_json(raw)
    return copy.deepcopy(raw)


def verify_render_capability_runtime_probe_receipt(
    payload: bytes,
    expected_sha256: str,
) -> dict[str, Any]:
    """Verify canonical persisted bytes against an independently held hash."""
    expected = _digest(expected_sha256, "render capability receipt expected sha256")
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_RECEIPT_BYTES:
        _fail("render capability receipt bytes are invalid or oversized")
    if _sha256_bytes(payload) != expected:
        _fail("render capability receipt hash does not match")
    try:
        text = payload.decode("ascii")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RenderCapabilityRuntimeProbeError(
            "render capability receipt bytes are invalid JSON"
        ) from error
    clean = _validate_probe_result(value)
    if payload != (_canonical_json(clean) + "\n").encode("ascii"):
        _fail("render capability receipt bytes are not canonical")
    return clean


def run_render_capability_runtime_probe(
    *,
    output_path: str | os.PathLike[str],
    work_dir: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    ffprobe_path: str | os.PathLike[str],
    _source_a_color: dict[str, str] | None = None,
    _filter_graph_mutator: Callable[[str], str] | None = None,
    _execute: Callable[..., object] | None = None,
    _runtime_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Run the fixed local production render and decoded-evidence proof."""
    root = _absolute_existing_dir(work_dir, "render capability work directory")
    output = _new_receipt_path(output_path, root)
    ffmpeg = _absolute_existing_file(ffmpeg_path, "render capability FFmpeg")
    ffprobe = _absolute_existing_file(ffprobe_path, "render capability FFprobe")
    host = _absolute_existing_file(
        _runtime_path or sys.executable, "render capability host runtime"
    )
    if ffmpeg == ffprobe:
        _fail("render capability FFmpeg and FFprobe must be distinct tools")

    owned = [
        root / RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE,
        root / RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_B_FILE,
        root / RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE,
        root / RENDER_CAPABILITY_RUNTIME_PROBE_FILTER_FILE,
    ]
    if any(path.exists() or path.is_symlink() for path in owned):
        _fail("render capability reserved probe file already exists")

    host_identity, host_stat = _file_identity(host, "render capability host")
    ffmpeg_identity, ffmpeg_stat = _file_identity(
        ffmpeg, "render capability FFmpeg"
    )
    ffprobe_identity, ffprobe_stat = _file_identity(
        ffprobe, "render capability FFprobe"
    )
    source_a, source_b, artifact, filter_script = owned
    selected_source_a_color = copy.deepcopy(
        SOURCE_A_COLOR if _source_a_color is None else _source_a_color
    )
    result: dict[str, Any] | None = None
    try:
        _generate_source(
            ffmpeg, source_a, source="a", color=SOURCE_A_COLOR,
            frequency_hz=SOURCE_A_FREQUENCY_HZ, execute=_execute,
        )
        _generate_source(
            ffmpeg, source_b, source="b", color=SOURCE_B_COLOR,
            frequency_hz=SOURCE_B_FREQUENCY_HZ, execute=_execute,
        )
        source_a_facts = _probe_media(
            ffprobe, source_a, stage="fixed source A probe", execute=_execute
        )
        source_b_facts = _probe_media(
            ffprobe, source_b, stage="fixed source B probe", execute=_execute
        )
        source_a_duration = _validate_source_probe(
            source_a_facts, SOURCE_A_COLOR, "fixed source A"
        )
        source_b_duration = _validate_source_probe(
            source_b_facts, SOURCE_B_COLOR, "fixed source B"
        )

        render, production = _build_production_render(
            source_a=source_a,
            source_b=source_b,
            source_a_facts=source_a_facts,
            source_b_facts=source_b_facts,
            source_a_color=selected_source_a_color,
            output=artifact,
            ffmpeg=ffmpeg,
        )
        graph = render["filter_complex"]
        if _filter_graph_mutator is not None:
            try:
                mutated = _filter_graph_mutator(graph)
            except Exception as error:
                raise RenderCapabilityRuntimeProbeError(
                    "render capability test mutation failed"
                ) from error
            if type(mutated) is not str or not mutated or mutated == graph:
                _fail("render capability test mutation did not change the graph")
            graph = mutated
        _write_exclusive(filter_script, graph.encode("utf-8"))
        _run(
            render["argv"],
            stage="production transition render",
            cwd=Path(render["working_directory"]),
            timeout=180,
            execute=_execute,
        )
        if not artifact.is_file() or artifact.stat().st_size < 1:
            _fail("production transition render produced no artifact")

        artifact_identity, evidence = _artifact_evidence(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            artifact=artifact,
            source_a=source_a,
            source_b=source_b,
            source_a_color=selected_source_a_color,
            execute=_execute,
        )
        if _sha256_bytes(graph.encode("utf-8")) != production[
            "filter_complex_sha256"
        ]:
            _fail("executed transition filter graph does not match its receipt")

        source_items = [{
            "id": "source-a-bt470bg",
            "file": RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE,
            "sha256": _sha256_file(source_a),
            "bytes": source_a.stat().st_size,
            "duration_ms": source_a_duration,
            "color": copy.deepcopy(SOURCE_A_COLOR),
            "generator_filter_sha256": _sha256_bytes(
                _source_video_filter("a").encode("ascii")
            ),
        }, {
            "id": "source-b-bt709",
            "file": RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_B_FILE,
            "sha256": _sha256_file(source_b),
            "bytes": source_b.stat().st_size,
            "duration_ms": source_b_duration,
            "color": copy.deepcopy(SOURCE_B_COLOR),
            "generator_filter_sha256": _sha256_bytes(
                _source_video_filter("b").encode("ascii")
            ),
        }]
        fixture_without_hash = {
            "schema_version": RENDER_CAPABILITY_RUNTIME_PROBE_FIXTURE_SCHEMA_VERSION,
            "frame_rate": {
                "numerator": FRAME_RATE_NUMERATOR,
                "denominator": FRAME_RATE_DENOMINATOR,
            },
            "geometry": {"width": WIDTH, "height": HEIGHT},
            "source_selection_ms": SOURCE_SELECTION_MS,
            "transition_duration_ms": TRANSITION_DURATION_MS,
            "audio": {
                "sample_rate": AUDIO_SAMPLE_RATE,
                "channels": AUDIO_CHANNELS,
                "source_a_frequency_hz": SOURCE_A_FREQUENCY_HZ,
                "source_b_frequency_hz": SOURCE_B_FREQUENCY_HZ,
            },
            "sources": source_items,
        }
        fixture = {
            **copy.deepcopy(fixture_without_hash),
            "sha256": _canonical_sha256(fixture_without_hash),
        }
        contract_schemas = [
            RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION,
            RENDER_CAPABILITY_RUNTIME_PROBE_FIXTURE_SCHEMA_VERSION,
            SEQUENCE_PLAN_SCHEMA_VERSION,
            SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
            TRANSITION_PLAN_SCHEMA_VERSION,
        ]
        result = {
            "schema_version": RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION,
            "checks": {
                name: True for name in sorted(RENDER_CAPABILITY_CHECK_NAMES)
            },
            "scope": copy.deepcopy(_SCOPE),
            "fixture": fixture,
            "runtime": {
                "host": host_identity,
                "ffmpeg": ffmpeg_identity,
                "ffprobe": ffprobe_identity,
                "contract": {
                    "schemas": contract_schemas,
                    "sha256": _canonical_sha256(contract_schemas),
                },
            },
            "production": production,
            "artifact": artifact_identity,
            "evidence": evidence,
        }
        result = _validate_probe_result(result)
        _verify_file_identity(
            host, host_identity, host_stat, "render capability host"
        )
        _verify_file_identity(
            ffmpeg, ffmpeg_identity, ffmpeg_stat, "render capability FFmpeg"
        )
        _verify_file_identity(
            ffprobe, ffprobe_identity, ffprobe_stat, "render capability FFprobe"
        )
    finally:
        for path in owned:
            path.unlink(missing_ok=True)

    if result is None:
        _fail("render capability proof produced no result")
    receipt_bytes = (_canonical_json(result) + "\n").encode("ascii")
    if len(receipt_bytes) > MAX_RECEIPT_BYTES:
        _fail("render capability receipt exceeds its bounded size")
    _write_exclusive(output, receipt_bytes)
    returned = copy.deepcopy(result)
    returned["receipt"] = {
        "file": RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE,
        "sha256": _sha256_bytes(receipt_bytes),
        "bytes": len(receipt_bytes),
    }
    return returned


__all__ = [
    "RENDER_CAPABILITY_CHECK_NAMES",
    "RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE",
    "RENDER_CAPABILITY_RUNTIME_PROBE_EVENT",
    "RENDER_CAPABILITY_RUNTIME_PROBE_FILTER_FILE",
    "RENDER_CAPABILITY_RUNTIME_PROBE_FIXTURE_SCHEMA_VERSION",
    "RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE",
    "RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION",
    "RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE",
    "RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_B_FILE",
    "RenderCapabilityRuntimeProbeError",
    "run_render_capability_runtime_probe",
    "verify_render_capability_runtime_probe_receipt",
]
