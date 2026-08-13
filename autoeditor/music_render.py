"""Trusted local execution for a validated :mod:`autoeditor.music_plan`.

The music planner is intentionally inert.  This module is the byte boundary:
it revalidates and recompiles the closed plan, resolves only exact caller-owned
asset/evidence inventories, snapshots and re-hashes every input, constructs
its own label-safe FFmpeg graph, and returns a closed receipt for the delivered
artifact.  No model-provided path, stream label, or filter fragment executes.

Music contract v1 deliberately supports only once-through regions without
crossfades, looping, dialogue ducking, or source-music removal.  Those features
remain fail-closed until a later executable topology is independently proven.

Mixed output uses a deterministic two-pass EBU R128/true-peak normalization.
The first-pass analysis, exact applied parameters, final filter topology, and
post-encode delivered measurement are all closed receipt fields.  Requested
targets alone are never treated as evidence that mastering passed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from autoeditor.music_plan import (
    MusicPlanError,
    compile_music_plan,
    music_compile_receipt_sha256,
    validate_music_asset_manifest,
)


MUSIC_RENDER_RECEIPT_SCHEMA_VERSION = "autoeditor-music-render-receipt/v2"
MUSIC_MASTERING_SCHEMA_VERSION = "autoeditor-music-two-pass-loudnorm/v1"
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 16 * 1024 * 1024 * 1024
MAX_TOTAL_EVIDENCE_BYTES = 512 * 1024 * 1024
MIN_WORK_FREE_BYTES = 512 * 1024 * 1024
MAX_CAPTURE_CHARS = 16_000

_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ASSET_ID = re.compile(r"^musicasset-[0-9a-f]{64}$", re.ASCII)
_REGION_ID = re.compile(r"^musicregion-[0-9a-f]{64}$", re.ASCII)
_SAFE_OUTPUT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.mp4$", re.ASCII)
_EVIDENCE_ROLES = frozenset({
    "license", "rights", "beat_analysis", "source_music_analysis",
    "source_music_region",
})

_RECEIPT_KEYS = frozenset({
    "schema_version", "music_compile_receipt_sha256", "music_plan_sha256",
    "music_asset_manifest_sha256", "edit_policy_sha256",
    "output_timeline_sha256", "ordered_region_ids", "ordered_asset_ids",
    "region_count", "source_music_action", "output_duration_ms",
    "target_loudness_millilufs", "true_peak_ceiling_millidbtp",
    "render_timeout_seconds", "program_input", "runtime_tools",
    "asset_inputs", "evidence_inputs", "filter_complex_sha256",
    "render_mode", "mastering", "output",
})
_PROGRAM_KEYS = frozenset({"sha256", "bytes", "duration_ms", "audio_present"})
_TOOL_KEYS = frozenset({"name", "sha256", "bytes"})
_ASSET_KEYS = frozenset({
    "asset_id", "sha256", "bytes", "duration_ms", "sample_rate_hz",
    "channels", "source_ref", "provenance", "license_evidence_sha256",
    "rights_receipt_sha256",
})
_EVIDENCE_KEYS = frozenset({"sha256", "bytes", "roles"})
_OUTPUT_KEYS = frozenset({
    "file", "sha256", "bytes", "duration_ms", "sample_rate_hz", "channels",
})
_MASTERING_KEYS = frozenset({
    "schema_version", "analysis_filter_complex_sha256", "analysis",
    "applied_parameters", "render_filter_complex_sha256",
    "render_measurement", "delivered_measurement",
    "loudness_tolerance_millilufs", "passed",
})
_LOUDNESS_KEYS = frozenset({
    "input_integrated_loudness_millilufs", "input_true_peak_millidbtp",
    "input_loudness_range_millilu", "input_threshold_millilufs",
    "output_integrated_loudness_millilufs", "output_true_peak_millidbtp",
    "output_loudness_range_millilu", "output_threshold_millilufs",
    "target_offset_millilu", "normalization_type",
})
_APPLIED_KEYS = frozenset({
    "target_loudness_millilufs", "true_peak_ceiling_millidbtp",
    "loudness_range_millilu", "measured_integrated_loudness_millilufs",
    "measured_true_peak_millidbtp", "measured_loudness_range_millilu",
    "measured_threshold_millilufs", "offset_millilu", "linear",
})
_DELIVERED_KEYS = frozenset({
    "integrated_loudness_millilufs", "true_peak_millidbtp",
})
_LOUDNESS_TOLERANCE_MILLILUFS = 1_000


class MusicRenderError(RuntimeError):
    """The trusted music execution request or rendered artifact is invalid."""


def _fail(message: str) -> None:
    raise MusicRenderError(message)


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MusicRenderError(f"{label} is not canonical JSON") from error


def _exact_dict(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict or set(value) != set(keys):
        _fail(f"{label} does not match the closed contract")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label} must be an integer of at least {minimum}")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a full lowercase SHA-256 digest")
    return value


def _seconds(value: object) -> str:
    milliseconds = _integer(value, "music duration")
    return f"{milliseconds // 1000}.{milliseconds % 1000:03d}"


def _millidb(value: object) -> str:
    amount = _integer(abs(value) if type(value) is int else value, "music gain")
    sign = "-" if type(value) is int and value < 0 else ""
    return f"{sign}{amount // 1000}.{amount % 1000:03d}"


def _signed_integer(value: object, label: str,
                    minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} is outside its closed integer range")
    return value


def _millivalue(value: object, label: str,
                minimum: float, maximum: float) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise MusicRenderError(f"{label} is not a finite measurement") from error
    if not math.isfinite(number) or not minimum <= number <= maximum:
        _fail(f"{label} is outside its measured range")
    return round(number * 1000)


def _render_timeout_seconds(duration_ms: int, region_count: int) -> int:
    # Video is stream-copied while audio is filtered.  Scale with timeline and
    # topology while retaining a finite 12-hour fail-safe for the 24-hour plan
    # contract ceiling.
    return min(43_200, max(
        180, 120 + (duration_ms + 3_999) // 4_000 + region_count * 8,
    ))


def _validate_command_length(command: list[str]) -> None:
    if len(subprocess.list2cmdline(command)) + 1 > 30_000:
        _fail("music render command exceeds the cross-platform argv bound")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_existing_file(value: object, label: str) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail(f"{label} path is invalid")
    raw = Path(value)
    if not raw.is_absolute():
        _fail(f"{label} path must be absolute")
    try:
        real = Path(os.path.realpath(raw))
        stat = real.stat()
    except OSError as error:
        raise MusicRenderError(f"{label} is unavailable") from error
    if not real.is_file() or stat.st_size < 1:
        _fail(f"{label} is not a nonempty file")
    return real


def _safe_work_dir(value: object) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail("music work directory is invalid")
    raw = Path(value)
    if not raw.is_absolute():
        _fail("music work directory must be absolute")
    try:
        real = Path(os.path.realpath(raw))
        real.stat()
    except OSError as error:
        raise MusicRenderError("music work directory is unavailable") from error
    if not real.is_dir():
        _fail("music work directory is not a directory")
    return real


def _safe_output(value: object, work: Path) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail("music output path is invalid")
    raw = Path(value)
    if not raw.is_absolute() or _SAFE_OUTPUT.fullmatch(raw.name) is None:
        _fail("music output path must be an absolute safe MP4 filename")
    parent = Path(os.path.realpath(raw.parent))
    if parent != work:
        _fail("music output must stay inside its private work directory")
    output = parent / raw.name
    if output.exists():
        _fail("music output already exists")
    return output


def _path_map(value: object, pattern: re.Pattern[str], label: str) -> dict[str, str]:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    normalized: dict[str, str] = {}
    for key, path in value.items():
        if type(key) is not str or pattern.fullmatch(key) is None:
            _fail(f"{label} contains an invalid key")
        if type(path) is not str:
            _fail(f"{label} contains an invalid path")
        normalized[key] = path
    return normalized


def _snapshot(source: Path, target: Path, expected_sha256: str,
              expected_bytes: int, label: str) -> dict[str, Any]:
    if target.exists():
        _fail(f"private {label} snapshot already exists")
    try:
        with source.open("rb") as input_stream, target.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
    except OSError as error:
        target.unlink(missing_ok=True)
        raise MusicRenderError(f"{label} could not be snapshotted") from error
    measured_bytes = target.stat().st_size
    measured_sha256 = _sha256_file(target)
    if measured_bytes != expected_bytes or measured_sha256 != expected_sha256:
        target.unlink(missing_ok=True)
        _fail(f"{label} bytes do not match their trusted binding")
    return {"path": target, "sha256": measured_sha256, "bytes": measured_bytes}


def _run(command: list[str], *, cwd: Path, label: str,
         timeout_seconds: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, cwd=str(cwd), check=False, shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MusicRenderError(f"{label} could not run") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:MAX_CAPTURE_CHARS]
        raise MusicRenderError(
            f"{label} failed" + (f": {detail}" if detail else "")
        )
    return result


def _parse_loudnorm_measurement(stderr: str, label: str) -> dict[str, Any]:
    matches = re.findall(r"\{\s*\"input_i\".*?\}", stderr, re.DOTALL)
    if not matches:
        _fail(f"{label} did not emit closed loudnorm JSON")
    try:
        payload = json.loads(matches[-1])
    except json.JSONDecodeError as error:
        raise MusicRenderError(f"{label} emitted invalid loudnorm JSON") from error
    expected = {
        "input_i", "input_tp", "input_lra", "input_thresh", "output_i",
        "output_tp", "output_lra", "output_thresh", "normalization_type",
        "target_offset",
    }
    if type(payload) is not dict or set(payload) != expected:
        _fail(f"{label} loudnorm measurement contract changed")
    normalization_type = payload["normalization_type"]
    if normalization_type not in {"dynamic", "linear"}:
        _fail(f"{label} loudnorm normalization type is invalid")
    return {
        "input_integrated_loudness_millilufs": _millivalue(
            payload["input_i"], f"{label} input_i", -100.0, 12.0),
        "input_true_peak_millidbtp": _millivalue(
            payload["input_tp"], f"{label} input_tp", -100.0, 24.0),
        "input_loudness_range_millilu": _millivalue(
            payload["input_lra"], f"{label} input_lra", 0.0, 100.0),
        "input_threshold_millilufs": _millivalue(
            payload["input_thresh"], f"{label} input_thresh", -120.0, 12.0),
        "output_integrated_loudness_millilufs": _millivalue(
            payload["output_i"], f"{label} output_i", -100.0, 12.0),
        "output_true_peak_millidbtp": _millivalue(
            payload["output_tp"], f"{label} output_tp", -100.0, 24.0),
        "output_loudness_range_millilu": _millivalue(
            payload["output_lra"], f"{label} output_lra", 0.0, 100.0),
        "output_threshold_millilufs": _millivalue(
            payload["output_thresh"], f"{label} output_thresh", -120.0, 12.0),
        "target_offset_millilu": _millivalue(
            payload["target_offset"], f"{label} target_offset", -99.0, 99.0),
        "normalization_type": normalization_type,
    }


def _normalize_loudness_measurement(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _LOUDNESS_KEYS, label)
    normalization_type = raw["normalization_type"]
    if normalization_type not in {"dynamic", "linear"}:
        _fail(f"{label}.normalization_type is invalid")
    return {
        "input_integrated_loudness_millilufs": _signed_integer(
            raw["input_integrated_loudness_millilufs"],
            f"{label}.input integrated loudness", -100_000, 12_000),
        "input_true_peak_millidbtp": _signed_integer(
            raw["input_true_peak_millidbtp"], f"{label}.input true peak",
            -100_000, 24_000),
        "input_loudness_range_millilu": _integer(
            raw["input_loudness_range_millilu"], f"{label}.input LRA"),
        "input_threshold_millilufs": _signed_integer(
            raw["input_threshold_millilufs"], f"{label}.input threshold",
            -120_000, 12_000),
        "output_integrated_loudness_millilufs": _signed_integer(
            raw["output_integrated_loudness_millilufs"],
            f"{label}.output integrated loudness", -100_000, 12_000),
        "output_true_peak_millidbtp": _signed_integer(
            raw["output_true_peak_millidbtp"], f"{label}.output true peak",
            -100_000, 24_000),
        "output_loudness_range_millilu": _integer(
            raw["output_loudness_range_millilu"], f"{label}.output LRA"),
        "output_threshold_millilufs": _signed_integer(
            raw["output_threshold_millilufs"], f"{label}.output threshold",
            -120_000, 12_000),
        "target_offset_millilu": _signed_integer(
            raw["target_offset_millilu"], f"{label}.target offset",
            -99_000, 99_000),
        "normalization_type": normalization_type,
    }


def _normalize_mastering(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = _exact_dict(value, _MASTERING_KEYS, "music render mastering")
    if raw["schema_version"] != MUSIC_MASTERING_SCHEMA_VERSION:
        _fail("music render mastering schema is unsupported")
    analysis = _normalize_loudness_measurement(
        raw["analysis"], "music mastering analysis")
    render_measurement = _normalize_loudness_measurement(
        raw["render_measurement"], "music mastering render measurement")
    applied_raw = _exact_dict(
        raw["applied_parameters"], _APPLIED_KEYS,
        "music mastering applied parameters")
    applied = {
        "target_loudness_millilufs": _signed_integer(
            applied_raw["target_loudness_millilufs"],
            "music mastering target", -40_000, -5_000),
        "true_peak_ceiling_millidbtp": _signed_integer(
            applied_raw["true_peak_ceiling_millidbtp"],
            "music mastering peak ceiling", -9_000, -100),
        "loudness_range_millilu": _integer(
            applied_raw["loudness_range_millilu"], "music mastering LRA", 1),
        "measured_integrated_loudness_millilufs": _signed_integer(
            applied_raw["measured_integrated_loudness_millilufs"],
            "music mastering measured I", -100_000, 12_000),
        "measured_true_peak_millidbtp": _signed_integer(
            applied_raw["measured_true_peak_millidbtp"],
            "music mastering measured TP", -100_000, 24_000),
        "measured_loudness_range_millilu": _integer(
            applied_raw["measured_loudness_range_millilu"],
            "music mastering measured LRA"),
        "measured_threshold_millilufs": _signed_integer(
            applied_raw["measured_threshold_millilufs"],
            "music mastering measured threshold", -120_000, 12_000),
        "offset_millilu": _signed_integer(
            applied_raw["offset_millilu"], "music mastering offset",
            -99_000, 99_000),
        "linear": applied_raw["linear"],
    }
    if applied["linear"] is not True:
        _fail("music two-pass mastering must request deterministic linear mode")
    expected_from_analysis = {
        "measured_integrated_loudness_millilufs": (
            analysis["input_integrated_loudness_millilufs"]),
        "measured_true_peak_millidbtp": analysis["input_true_peak_millidbtp"],
        "measured_loudness_range_millilu": (
            analysis["input_loudness_range_millilu"]),
        "measured_threshold_millilufs": analysis["input_threshold_millilufs"],
        "offset_millilu": analysis["target_offset_millilu"],
    }
    if any(applied[key] != expected
           for key, expected in expected_from_analysis.items()):
        _fail("music applied mastering parameters do not bind first-pass analysis")
    delivered_raw = _exact_dict(
        raw["delivered_measurement"], _DELIVERED_KEYS,
        "music delivered loudness measurement")
    delivered = {
        "integrated_loudness_millilufs": _signed_integer(
            delivered_raw["integrated_loudness_millilufs"],
            "delivered integrated loudness", -100_000, 12_000),
        "true_peak_millidbtp": _signed_integer(
            delivered_raw["true_peak_millidbtp"],
            "delivered true peak", -100_000, 24_000),
    }
    tolerance = _integer(
        raw["loudness_tolerance_millilufs"], "music loudness tolerance", 1)
    passed = raw["passed"]
    if type(passed) is not bool:
        _fail("music mastering pass state is invalid")
    expected_pass = (
        abs(delivered["integrated_loudness_millilufs"]
            - applied["target_loudness_millilufs"]) <= tolerance
        and delivered["true_peak_millidbtp"]
        <= applied["true_peak_ceiling_millidbtp"] + 100
    )
    if passed != expected_pass:
        _fail("music mastering pass state contradicts delivered measurements")
    return {
        "schema_version": MUSIC_MASTERING_SCHEMA_VERSION,
        "analysis_filter_complex_sha256": _digest(
            raw["analysis_filter_complex_sha256"],
            "music analysis filter digest"),
        "analysis": analysis, "applied_parameters": applied,
        "render_filter_complex_sha256": _digest(
            raw["render_filter_complex_sha256"],
            "music render filter digest"),
        "render_measurement": render_measurement,
        "delivered_measurement": delivered,
        "loudness_tolerance_millilufs": tolerance, "passed": passed,
    }


def _probe(path: Path, ffprobe: Path, work: Path, label: str,
           *, require_audio: bool = True) -> dict[str, Any]:
    result = _run([
        str(ffprobe), "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,sample_rate,channels",
        "-of", "json", str(path),
    ], cwd=work, label=f"{label} probe", timeout_seconds=60)
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        duration = float(payload["format"]["duration"])
        audio = next((item for item in streams
                      if item.get("codec_type") == "audio"), None)
        video_present = any(item.get("codec_type") == "video" for item in streams)
        if require_audio and audio is None:
            _fail(f"{label} has no audio stream")
        sample_rate = int(audio["sample_rate"]) if audio is not None else None
        channels = int(audio["channels"]) if audio is not None else None
    except (KeyError, TypeError, ValueError, StopIteration,
            json.JSONDecodeError) as error:
        raise MusicRenderError(f"{label} technical metadata is invalid") from error
    duration_ms = round(duration * 1000)
    if (duration_ms < 1 or (audio is not None and (
            sample_rate is None or sample_rate < 1
            or channels is None or channels < 1))):
        _fail(f"{label} technical metadata is invalid")
    return {
        "duration_ms": duration_ms,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "audio_present": audio is not None,
        "video_present": video_present,
    }


def derive_music_output_timeline_sha256(
    *, program_sha256: object, program_bytes: object, duration_ms: object,
) -> str:
    binding = {
        "schema_version": "autoeditor-music-output-timeline/v1",
        "program_sha256": _digest(program_sha256, "music timeline program sha256"),
        "program_bytes": _integer(program_bytes, "music timeline program bytes", 1),
        "duration_ms": _integer(duration_ms, "music timeline duration", 1),
        "time_base": {"numerator": 1, "denominator": 1_000},
    }
    return hashlib.sha256(
        _canonical_json(binding, "music output timeline").encode("utf-8")
    ).hexdigest()


def _required_evidence(compiled: dict, manifest: dict) -> dict[str, list[str]]:
    roles: dict[str, set[str]] = {}

    def add(digest: str, role: str) -> None:
        roles.setdefault(digest, set()).add(role)

    add(manifest["source_music"]["evidence_sha256"], "source_music_analysis")
    for region in manifest["source_music"]["regions"]:
        add(region["evidence_sha256"], "source_music_region")
    assets = {item["asset_id"]: item for item in manifest["assets"]}
    grids = {item["beat_grid_id"]: item for item in manifest["beat_grids"]}
    for region in compiled["compiled_regions"]:
        asset = assets[region["asset_id"]]
        add(asset["license"]["evidence_sha256"], "license")
        add(asset["rights_receipt"]["receipt_sha256"], "rights")
        if region["beat_sync"] is not None:
            grid = grids[region["beat_sync"]["beat_grid_id"]]
            add(grid["analysis_receipt_sha256"], "beat_analysis")
    return {digest: sorted(values) for digest, values in sorted(roles.items())}


def _build_filter(
    compiled: dict,
    *,
    program_audio_present: bool,
    mastering_parameters: dict[str, Any] | None = None,
    analysis_pass: bool = False,
) -> str:
    regions = compiled["compiled_regions"]
    if not regions:
        return ""
    duration = compiled["receipt"]["output_duration_ms"]
    duration_token = _seconds(duration)
    program_source = "[0:a:0]" if program_audio_present else (
        "anullsrc=channel_layout=stereo:sample_rate=48000:d="
        + duration_token + ","
    )
    filters = [
        program_source
        + "aresample=48000,"
        + "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        + "apad=whole_dur=" + duration_token + ","
        + "atrim=start=0.000:duration=" + duration_token + ","
        + "asetpts=PTS-STARTPTS[program]"
    ]

    asset_ids = sorted({item["asset_id"] for item in regions})
    input_by_asset = {
        asset_id: index for index, asset_id in enumerate(asset_ids, 1)
    }
    region_sources: dict[int, str] = {}
    for asset_id in asset_ids:
        indexes = [index for index, item in enumerate(regions, 1)
                   if item["asset_id"] == asset_id]
        input_index = input_by_asset[asset_id]
        if len(indexes) == 1:
            region_sources[indexes[0]] = f"{input_index}:a:0"
            continue
        labels = []
        for index in indexes:
            label = f"music{index:04d}src"
            region_sources[index] = label
            labels.append(f"[{label}]")
        filters.append(
            f"[{input_index}:a:0]asplit=outputs={len(indexes)}"
            + "".join(labels)
        )

    track_outputs: dict[int, list[str]] = {}
    for index, region in enumerate(regions, 1):
        if (region["playback_mode"] != "once"
                or region["loop_ffmpeg_primitive_tokens"]
                or region["dialogue_sidechain_ffmpeg_primitive_tokens"]):
            _fail("music contract v1 contains an unsupported render topology")
        label = f"music{index:04d}out"
        tokens = [
            *region["source_ffmpeg_primitive_tokens"],
            *region["edge_ffmpeg_primitive_tokens"],
            *region["timeline_ffmpeg_primitive_tokens"],
            "apad=whole_dur=" + duration_token,
        ]
        filters.append(
            f"[{region_sources[index]}]" + ",".join(tokens) + f"[{label}]"
        )
        track_outputs.setdefault(region["track_index"], []).append(label)

    mixed_tracks: list[str] = []
    for track_index in sorted(track_outputs):
        labels = track_outputs[track_index]
        output = f"musictrack{track_index:02d}"
        if len(labels) == 1:
            filters.append(f"[{labels[0]}]anull[{output}]")
        else:
            filters.append(
                "".join(f"[{label}]" for label in labels)
                + f"amix=inputs={len(labels)}:duration=longest:"
                + "dropout_transition=0:normalize=0,"
                + "apad=whole_dur=" + duration_token + ","
                + f"anull[{output}]"
            )
        mixed_tracks.append(output)

    if len(mixed_tracks) == 1:
        filters.append(f"[{mixed_tracks[0]}]anull[musicbus]")
    else:
        filters.append(
            "".join(f"[{label}]" for label in mixed_tracks)
            + f"amix=inputs={len(mixed_tracks)}:duration=longest:"
            + "dropout_transition=0:normalize=0,"
            + "apad=whole_dur=" + duration_token + ","
            + "anull[musicbus]"
        )
    receipt = compiled["receipt"]
    loudnorm = (
        "loudnorm=I=" + _millidb(receipt["target_loudness_millilufs"])
        + ":TP=" + _millidb(receipt["true_peak_ceiling_millidbtp"])
        + ":LRA=11.000"
    )
    if analysis_pass:
        if mastering_parameters is not None:
            _fail("music analysis filter cannot accept measured parameters")
        loudnorm += ":print_format=json"
    else:
        if mastering_parameters is None:
            _fail("music render filter requires first-pass mastering parameters")
        parameters = _exact_dict(
            mastering_parameters, _APPLIED_KEYS,
            "music render mastering parameters")
        loudnorm += (
            ":measured_I="
            + _millidb(parameters["measured_integrated_loudness_millilufs"])
            + ":measured_TP="
            + _millidb(parameters["measured_true_peak_millidbtp"])
            + ":measured_LRA="
            + _millidb(parameters["measured_loudness_range_millilu"])
            + ":measured_thresh="
            + _millidb(parameters["measured_threshold_millilufs"])
            + ":offset=" + _millidb(parameters["offset_millilu"])
            + ":linear=true:print_format=json"
        )
    filters.append(
        "[program][musicbus]"
        + "amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        + loudnorm + ","
        + "apad=whole_dur=" + duration_token + ","
        + "atrim=start=0.000:duration=" + duration_token + ","
        + "asetpts=PTS-STARTPTS[aout]"
    )
    return ";".join(filters)


def _normalize_receipt(value: object) -> dict[str, Any]:
    raw = _exact_dict(value, _RECEIPT_KEYS, "music render receipt")
    if raw["schema_version"] != MUSIC_RENDER_RECEIPT_SCHEMA_VERSION:
        _fail("music render receipt schema is unsupported")
    hashes = {
        key: _digest(raw[key], f"music render receipt.{key}")
        for key in (
            "music_compile_receipt_sha256", "music_plan_sha256",
            "music_asset_manifest_sha256", "edit_policy_sha256",
            "output_timeline_sha256", "filter_complex_sha256",
        )
    }
    region_ids = raw["ordered_region_ids"]
    asset_ids = raw["ordered_asset_ids"]
    if (type(region_ids) is not list
            or any(type(item) is not str or _REGION_ID.fullmatch(item) is None
                   for item in region_ids)
            or len(set(region_ids)) != len(region_ids)):
        _fail("music render receipt region ids are invalid")
    if (type(asset_ids) is not list or len(asset_ids) != len(region_ids)
            or any(type(item) is not str or _ASSET_ID.fullmatch(item) is None
                   for item in asset_ids)):
        _fail("music render receipt ordered asset ids are invalid")
    region_count = _integer(raw["region_count"], "music render region count")
    if region_count != len(region_ids):
        _fail("music render receipt region count does not match")
    if raw["source_music_action"] not in {"none", "preserve"}:
        _fail("music render receipt source-music action is invalid")

    program = _exact_dict(
        raw["program_input"], _PROGRAM_KEYS, "music render receipt.program_input")
    normalized_program = {
        "sha256": _digest(program["sha256"], "music program sha256"),
        "bytes": _integer(program["bytes"], "music program bytes", 1),
        "duration_ms": _integer(
            program["duration_ms"], "music program duration", 1),
        "audio_present": program["audio_present"],
    }
    if type(normalized_program["audio_present"]) is not bool:
        _fail("music program audio presence is invalid")

    tools = raw["runtime_tools"]
    if type(tools) is not list or len(tools) != 2:
        _fail("music render receipt runtime tools are invalid")
    normalized_tools = []
    for index, tool in enumerate(tools):
        item = _exact_dict(
            tool, _TOOL_KEYS, f"music render receipt.runtime_tools[{index}]")
        if item["name"] not in {"ffmpeg", "ffprobe"}:
            _fail("music runtime tool name is invalid")
        normalized_tools.append({
            "name": item["name"],
            "sha256": _digest(item["sha256"], "music runtime tool sha256"),
            "bytes": _integer(item["bytes"], "music runtime tool bytes", 1),
        })
    if (normalized_tools != sorted(normalized_tools, key=lambda item: item["name"])
            or {item["name"] for item in normalized_tools}
            != {"ffmpeg", "ffprobe"}):
        _fail("music runtime tools are not exact and sorted")

    assets = raw["asset_inputs"]
    if type(assets) is not list:
        _fail("music render receipt asset inputs are invalid")
    normalized_assets = []
    for index, value_raw in enumerate(assets):
        item = _exact_dict(
            value_raw, _ASSET_KEYS,
            f"music render receipt.asset_inputs[{index}]",
        )
        asset_id = item["asset_id"]
        if type(asset_id) is not str or _ASSET_ID.fullmatch(asset_id) is None:
            _fail("music render receipt asset id is invalid")
        if type(item["source_ref"]) is not str or type(item["provenance"]) is not str:
            _fail("music render receipt asset provenance is invalid")
        normalized_assets.append({
            "asset_id": asset_id,
            "sha256": _digest(item["sha256"], "music asset sha256"),
            "bytes": _integer(item["bytes"], "music asset bytes", 1),
            "duration_ms": _integer(item["duration_ms"], "music asset duration", 1),
            "sample_rate_hz": _integer(
                item["sample_rate_hz"], "music asset sample rate", 1),
            "channels": _integer(item["channels"], "music asset channels", 1),
            "source_ref": item["source_ref"],
            "provenance": item["provenance"],
            "license_evidence_sha256": _digest(
                item["license_evidence_sha256"], "music license evidence"),
            "rights_receipt_sha256": _digest(
                item["rights_receipt_sha256"], "music rights receipt"),
        })
    if (normalized_assets != sorted(normalized_assets,
                                    key=lambda item: item["asset_id"])
            or len({item["asset_id"] for item in normalized_assets})
            != len(normalized_assets)):
        _fail("music render receipt asset inputs are not unique and sorted")
    if {item["asset_id"] for item in normalized_assets} != set(asset_ids):
        _fail("music render receipt asset inventory contradicts its regions")

    evidence = raw["evidence_inputs"]
    if type(evidence) is not list:
        _fail("music render receipt evidence inputs are invalid")
    normalized_evidence = []
    for index, value_raw in enumerate(evidence):
        item = _exact_dict(
            value_raw, _EVIDENCE_KEYS,
            f"music render receipt.evidence_inputs[{index}]",
        )
        roles = item["roles"]
        if (type(roles) is not list or not roles or roles != sorted(roles)
                or len(set(roles)) != len(roles)
                or any(type(role) is not str or role not in _EVIDENCE_ROLES
                       for role in roles)):
            _fail("music evidence roles are invalid")
        normalized_evidence.append({
            "sha256": _digest(item["sha256"], "music evidence sha256"),
            "bytes": _integer(item["bytes"], "music evidence bytes", 1),
            "roles": list(roles),
        })
    if (normalized_evidence != sorted(
            normalized_evidence, key=lambda item: item["sha256"])
            or len({item["sha256"] for item in normalized_evidence})
            != len(normalized_evidence)):
        _fail("music render receipt evidence inputs are not unique and sorted")

    if raw["render_mode"] not in {
            "mixed", "no_regions_copy", "no_regions_normalized"}:
        _fail("music render receipt mode is invalid")
    if (raw["render_mode"] == "mixed") != bool(region_count):
        _fail("music render receipt mode contradicts its region count")
    if (raw["render_mode"] == "no_regions_copy"
            and not normalized_program["audio_present"]):
        _fail("music byte-copy mode cannot claim missing program audio")

    duration = _integer(
        raw["output_duration_ms"], "music render output duration", 1)
    timeout = _integer(
        raw["render_timeout_seconds"], "music render timeout", 180)
    if timeout != _render_timeout_seconds(duration, region_count):
        _fail("music render timeout does not bind its workload")
    target_loudness = raw["target_loudness_millilufs"]
    peak = raw["true_peak_ceiling_millidbtp"]
    if (type(target_loudness) is not int or not -40_000 <= target_loudness <= -5_000
            or type(peak) is not int or not -9_000 <= peak <= -100):
        _fail("music render receipt mastering target is invalid")
    mastering = _normalize_mastering(raw["mastering"])
    if bool(region_count) != (mastering is not None):
        _fail("music render mastering evidence contradicts its region count")
    if mastering is not None:
        applied = mastering["applied_parameters"]
        if (applied["target_loudness_millilufs"] != target_loudness
                or applied["true_peak_ceiling_millidbtp"] != peak
                or mastering["render_filter_complex_sha256"]
                != hashes["filter_complex_sha256"]
                or mastering["passed"] is not True
                or mastering["loudness_tolerance_millilufs"]
                != _LOUDNESS_TOLERANCE_MILLILUFS):
            _fail("music render mastering does not prove the delivery target")

    output = _exact_dict(raw["output"], _OUTPUT_KEYS,
                         "music render receipt.output")
    if type(output["file"]) is not str or _SAFE_OUTPUT.fullmatch(
            output["file"]) is None:
        _fail("music render receipt output filename is invalid")
    normalized_output = {
        "file": output["file"],
        "sha256": _digest(output["sha256"], "music output sha256"),
        "bytes": _integer(output["bytes"], "music output bytes", 1),
        "duration_ms": _integer(
            output["duration_ms"], "music output duration", 1),
        "sample_rate_hz": _integer(
            output["sample_rate_hz"], "music output sample rate", 1),
        "channels": _integer(output["channels"], "music output channels", 1),
    }
    if (normalized_output["sample_rate_hz"] != 48_000
            or normalized_output["channels"] != 2):
        _fail("music output is not exact 48000 Hz stereo delivery audio")
    if not region_count:
        if (normalized_assets or mastering is not None
                or hashes["filter_complex_sha256"] != hashlib.sha256(
                    b"").hexdigest()):
            _fail("no-region music receipt contains an unexpected render topology")
    if raw["render_mode"] == "no_regions_copy" and (
            normalized_output["sha256"] != normalized_program["sha256"]
            or normalized_output["bytes"] != normalized_program["bytes"]):
        _fail("music byte-copy mode does not preserve program bytes")
    if (abs(normalized_program["duration_ms"] - duration) > 100
            or abs(normalized_output["duration_ms"] - duration) > 100):
        _fail("music render input/output timelines contradict")
    expected_timeline = derive_music_output_timeline_sha256(
        program_sha256=normalized_program["sha256"],
        program_bytes=normalized_program["bytes"], duration_ms=duration,
    )
    if hashes["output_timeline_sha256"] != expected_timeline:
        _fail("music render timeline does not bind its program input")
    return {
        "schema_version": MUSIC_RENDER_RECEIPT_SCHEMA_VERSION,
        **hashes,
        "ordered_region_ids": list(region_ids),
        "ordered_asset_ids": list(asset_ids),
        "region_count": region_count,
        "source_music_action": raw["source_music_action"],
        "output_duration_ms": duration,
        "target_loudness_millilufs": target_loudness,
        "true_peak_ceiling_millidbtp": peak,
        "render_timeout_seconds": timeout,
        "program_input": normalized_program,
        "runtime_tools": normalized_tools,
        "asset_inputs": normalized_assets,
        "evidence_inputs": normalized_evidence,
        "filter_complex_sha256": hashes["filter_complex_sha256"],
        "render_mode": raw["render_mode"],
        "mastering": mastering,
        "output": normalized_output,
    }


def canonical_music_render_receipt_json(receipt: object) -> str:
    return _canonical_json(_normalize_receipt(receipt), "music render receipt")


def music_render_receipt_sha256(receipt: object) -> str:
    return hashlib.sha256(
        canonical_music_render_receipt_json(receipt).encode("utf-8")
    ).hexdigest()


def execute_music_render(
    *,
    program_path: str,
    output_path: str,
    plan: object,
    asset_manifest: object,
    edit_policy: object,
    asset_paths: Mapping[str, str],
    evidence_paths: Mapping[str, str],
    work_dir: str,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> dict[str, Any]:
    """Render an exact validated music mix and return byte-bound receipts."""
    work = _safe_work_dir(work_dir)
    program_source = _safe_existing_file(program_path, "music program input")
    output = _safe_output(output_path, work)
    ffmpeg = _safe_existing_file(ffmpeg_path, "FFmpeg")
    ffprobe = _safe_existing_file(ffprobe_path, "FFprobe")
    if output == program_source:
        _fail("music output cannot overwrite its program input")
    try:
        tools = []
        tool_paths = {"ffmpeg": ffmpeg, "ffprobe": ffprobe}
        for name in sorted(tool_paths):
            path = tool_paths[name]
            tools.append({
                "name": name, "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            })
        manifest = validate_music_asset_manifest(asset_manifest)
        compiled = compile_music_plan(plan, manifest, edit_policy)
    except MusicPlanError as error:
        raise MusicRenderError(
            f"music execution contract is invalid: {error}") from error

    assets_by_id = {item["asset_id"]: item for item in manifest["assets"]}
    used_asset_ids = sorted({
        item["asset_id"] for item in compiled["compiled_regions"]
    })
    normalized_asset_paths = _path_map(
        asset_paths, _ASSET_ID, "music asset paths")
    if set(normalized_asset_paths) != set(used_asset_ids):
        _fail("music asset path inventory does not exactly match used assets")
    required_evidence = _required_evidence(compiled, manifest)
    normalized_evidence_paths = _path_map(
        evidence_paths, _SHA256, "music evidence paths")
    if set(normalized_evidence_paths) != set(required_evidence):
        _fail("music evidence path inventory is incomplete or excessive")

    created: list[Path] = []
    snapshots: list[dict[str, Any]] = []
    try:
        total_asset_bytes = sum(
            assets_by_id[asset_id]["byte_length"] for asset_id in used_asset_ids
        )
        evidence_sizes: dict[str, int] = {}
        for digest in required_evidence:
            source = _safe_existing_file(
                normalized_evidence_paths[digest], f"music evidence {digest}")
            evidence_sizes[digest] = source.stat().st_size
        total_evidence_bytes = sum(evidence_sizes.values())
        if (total_asset_bytes > MAX_TOTAL_ASSET_BYTES
                or total_evidence_bytes > MAX_TOTAL_EVIDENCE_BYTES
                or any(size > MAX_EVIDENCE_BYTES
                       for size in evidence_sizes.values())):
            _fail("music execution inputs exceed aggregate byte bounds")
        try:
            free_bytes = shutil.disk_usage(work).free
        except OSError as error:
            raise MusicRenderError("music work volume could not be measured") from error
        required_free = (
            program_source.stat().st_size * 3 + total_asset_bytes
            + total_evidence_bytes + MIN_WORK_FREE_BYTES
        )
        if free_bytes < required_free:
            _fail("music work volume lacks space for snapshots and output")

        program_stat = program_source.stat()
        program_hash = _sha256_file(program_source)
        program_snapshot = work / "music-program-input.mp4"
        program_binding = _snapshot(
            program_source, program_snapshot, program_hash,
            program_stat.st_size, "music program input",
        )
        created.append(program_snapshot)
        snapshots.append(program_binding)
        program_probe = _probe(
            program_snapshot, ffprobe, work, "music program input",
            require_audio=False,
        )
        if not program_probe["video_present"]:
            _fail("music program input has no video stream")
        if abs(program_probe["duration_ms"] - manifest["output_duration_ms"]) > 100:
            _fail("music program duration does not bind the output timeline")
        if (manifest["source_music"]["status"] == "present"
                and not program_probe["audio_present"]):
            _fail("source-music evidence contradicts a silent program input")
        measured_timeline = derive_music_output_timeline_sha256(
            program_sha256=program_binding["sha256"],
            program_bytes=program_binding["bytes"],
            duration_ms=manifest["output_duration_ms"],
        )
        if manifest["output_timeline_sha256"] != measured_timeline:
            _fail("music asset manifest does not bind the exact program timeline")

        asset_snapshots: dict[str, dict[str, Any]] = {}
        asset_receipts: list[dict[str, Any]] = []
        for index, asset_id in enumerate(used_asset_ids, 1):
            asset = assets_by_id[asset_id]
            source = _safe_existing_file(
                normalized_asset_paths[asset_id], f"music asset {asset_id}")
            target = work / f"music-asset-{index:04d}.bin"
            binding = _snapshot(
                source, target, asset["sha256"], asset["byte_length"],
                f"music asset {asset_id}",
            )
            created.append(target)
            snapshots.append(binding)
            facts = _probe(target, ffprobe, work, f"music asset {asset_id}")
            if (facts["video_present"]
                    or abs(facts["duration_ms"]
                           - asset["decoded_duration_ms"]) > 50
                    or facts["sample_rate_hz"] != asset["sample_rate_hz"]
                    or facts["channels"] != asset["channels"]):
                _fail(f"music asset {asset_id} decoded facts changed")
            asset_snapshots[asset_id] = {**binding, "facts": facts}
            asset_receipts.append({
                "asset_id": asset_id,
                "sha256": binding["sha256"], "bytes": binding["bytes"],
                "duration_ms": facts["duration_ms"],
                "sample_rate_hz": facts["sample_rate_hz"],
                "channels": facts["channels"],
                "source_ref": asset["source_ref"],
                "provenance": asset["provenance"],
                "license_evidence_sha256": asset["license"]["evidence_sha256"],
                "rights_receipt_sha256": asset["rights_receipt"]["receipt_sha256"],
            })

        evidence_receipts: list[dict[str, Any]] = []
        for index, digest in enumerate(sorted(required_evidence), 1):
            source = _safe_existing_file(
                normalized_evidence_paths[digest], f"music evidence {digest}")
            target = work / f"music-evidence-{index:04d}.bin"
            binding = _snapshot(
                source, target, digest, evidence_sizes[digest],
                f"music evidence {digest}",
            )
            created.append(target)
            snapshots.append(binding)
            evidence_receipts.append({
                "sha256": binding["sha256"], "bytes": binding["bytes"],
                "roles": required_evidence[digest],
            })

        timeout = _render_timeout_seconds(
            manifest["output_duration_ms"], len(compiled["compiled_regions"]))
        filter_complex = ""
        filter_hash = hashlib.sha256(b"").hexdigest()
        mastering = None
        created.append(output)
        if compiled["compiled_regions"]:
            aliases: list[str] = []
            for asset_id in used_asset_ids:
                target = asset_snapshots[asset_id]["path"]
                aliases.extend(["-i", f".{os.sep}{target.name}"])
            analysis_filter = _build_filter(
                compiled, program_audio_present=program_probe["audio_present"],
                analysis_pass=True)
            analysis_filter_hash = hashlib.sha256(
                analysis_filter.encode("utf-8")).hexdigest()
            analysis_script = work / "music-analysis-filter.txt"
            if analysis_script.exists():
                _fail("private music analysis filter already exists")
            created.append(analysis_script)
            try:
                with analysis_script.open(
                        "x", encoding="utf-8", errors="strict",
                        newline="\n") as stream:
                    stream.write(analysis_filter)
            except OSError as error:
                raise MusicRenderError(
                    "private music analysis filter could not be created") from error
            analysis_command = [
                str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "info",
                "-i", f".{os.sep}{program_snapshot.name}", *aliases,
                "-filter_complex_script", f".{os.sep}{analysis_script.name}",
                "-map", "[aout]", "-f", "null", "-",
            ]
            _validate_command_length(analysis_command)
            analysis_result = _run(
                analysis_command, cwd=work, label="music mastering analysis",
                timeout_seconds=timeout)
            analysis = _parse_loudnorm_measurement(
                analysis_result.stderr, "music mastering analysis")
            applied = {
                "target_loudness_millilufs": compiled["receipt"][
                    "target_loudness_millilufs"],
                "true_peak_ceiling_millidbtp": compiled["receipt"][
                    "true_peak_ceiling_millidbtp"],
                "loudness_range_millilu": 11_000,
                "measured_integrated_loudness_millilufs": analysis[
                    "input_integrated_loudness_millilufs"],
                "measured_true_peak_millidbtp": analysis[
                    "input_true_peak_millidbtp"],
                "measured_loudness_range_millilu": analysis[
                    "input_loudness_range_millilu"],
                "measured_threshold_millilufs": analysis[
                    "input_threshold_millilufs"],
                "offset_millilu": analysis["target_offset_millilu"],
                "linear": True,
            }
            filter_complex = _build_filter(
                compiled, program_audio_present=program_probe["audio_present"],
                mastering_parameters=applied)
            filter_hash = hashlib.sha256(
                filter_complex.encode("utf-8")).hexdigest()
            filter_script = work / "music-filter.txt"
            if filter_script.exists():
                _fail("private music filter script already exists")
            created.append(filter_script)
            try:
                with filter_script.open(
                        "x", encoding="utf-8", errors="strict",
                        newline="\n") as stream:
                    stream.write(filter_complex)
            except OSError as error:
                raise MusicRenderError(
                    "private music filter script could not be created") from error
            command = [
                str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "info",
                "-n", "-i", f".{os.sep}{program_snapshot.name}", *aliases,
                "-filter_complex_script", f".{os.sep}{filter_script.name}",
                "-map", "0:v:0", "-map", "[aout]", "-map_metadata", "-1",
                "-map_chapters", "-1", "-sn", "-dn", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-t", _seconds(manifest["output_duration_ms"]),
                "-movflags", "+faststart", f".{os.sep}{output.name}",
            ]
            _validate_command_length(command)
            render_result = _run(
                command, cwd=work, label="music render", timeout_seconds=timeout)
            render_measurement = _parse_loudnorm_measurement(
                render_result.stderr, "music render")
            render_mode = "mixed"
        elif (program_probe["audio_present"]
              and program_probe["sample_rate_hz"] == 48_000
              and program_probe["channels"] == 2):
            with program_snapshot.open("rb") as source_stream, output.open("xb") as out:
                shutil.copyfileobj(source_stream, out, 1024 * 1024)
            render_mode = "no_regions_copy"
        else:
            command = [
                str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
                "-n", "-i", f".{os.sep}{program_snapshot.name}",
            ]
            if program_probe["audio_present"]:
                command.extend(["-map", "0:v:0", "-map", "0:a:0"])
            else:
                command.extend([
                    "-f", "lavfi", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000:d="
                    + _seconds(manifest["output_duration_ms"]),
                    "-map", "0:v:0", "-map", "1:a:0",
                ])
            command.extend([
                "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-ar", "48000", "-ac", "2",
                "-t", _seconds(manifest["output_duration_ms"]),
                "-movflags", "+faststart", f".{os.sep}{output.name}",
            ])
            _validate_command_length(command)
            _run(command, cwd=work, label="music normalization",
                 timeout_seconds=timeout)
            render_mode = "no_regions_normalized"

        for binding in snapshots:
            path = binding["path"]
            if (path.stat().st_size != binding["bytes"]
                    or _sha256_file(path) != binding["sha256"]):
                output.unlink(missing_ok=True)
                _fail("a music execution input changed during rendering")
        for binding in tools:
            path = tool_paths[binding["name"]]
            if (path.stat().st_size != binding["bytes"]
                    or _sha256_file(path) != binding["sha256"]):
                output.unlink(missing_ok=True)
                _fail("a music runtime tool changed during rendering")
        output_probe = _probe(output, ffprobe, work, "music output")
        if (not output_probe["video_present"]
                or abs(output_probe["duration_ms"]
                       - manifest["output_duration_ms"]) > 100
                or output_probe["sample_rate_hz"] != 48_000
                or output_probe["channels"] != 2):
            output.unlink(missing_ok=True)
            _fail("music output failed its exact delivery probe")
        if compiled["compiled_regions"]:
            delivered_result = _run([
                str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "info",
                "-i", str(output), "-map", "0:a:0", "-vn", "-af",
                "loudnorm=I="
                + _millidb(compiled["receipt"]["target_loudness_millilufs"])
                + ":TP="
                + _millidb(compiled["receipt"]["true_peak_ceiling_millidbtp"])
                + ":LRA=11.000:print_format=json", "-f", "null", "-",
            ], cwd=work, label="music delivered loudness measurement",
                timeout_seconds=timeout)
            delivered_analysis = _parse_loudnorm_measurement(
                delivered_result.stderr, "music delivered loudness measurement")
            delivered = {
                "integrated_loudness_millilufs": delivered_analysis[
                    "input_integrated_loudness_millilufs"],
                "true_peak_millidbtp": delivered_analysis[
                    "input_true_peak_millidbtp"],
            }
            passed = (
                abs(delivered["integrated_loudness_millilufs"]
                    - compiled["receipt"]["target_loudness_millilufs"])
                <= _LOUDNESS_TOLERANCE_MILLILUFS
                and delivered["true_peak_millidbtp"]
                <= compiled["receipt"]["true_peak_ceiling_millidbtp"] + 100
            )
            mastering = _normalize_mastering({
                "schema_version": MUSIC_MASTERING_SCHEMA_VERSION,
                "analysis_filter_complex_sha256": analysis_filter_hash,
                "analysis": analysis, "applied_parameters": applied,
                "render_filter_complex_sha256": filter_hash,
                "render_measurement": render_measurement,
                "delivered_measurement": delivered,
                "loudness_tolerance_millilufs": (
                    _LOUDNESS_TOLERANCE_MILLILUFS),
                "passed": passed,
            })
            if mastering is None or mastering["passed"] is not True:
                output.unlink(missing_ok=True)
                _fail("music output missed measured loudness or true-peak delivery")
        receipt = _normalize_receipt({
            "schema_version": MUSIC_RENDER_RECEIPT_SCHEMA_VERSION,
            "music_compile_receipt_sha256": music_compile_receipt_sha256(
                compiled["receipt"]),
            "music_plan_sha256": compiled["receipt"]["music_plan_sha256"],
            "music_asset_manifest_sha256": compiled["receipt"][
                "music_asset_manifest_sha256"],
            "edit_policy_sha256": compiled["receipt"]["edit_policy_sha256"],
            "output_timeline_sha256": compiled["receipt"][
                "output_timeline_sha256"],
            "ordered_region_ids": compiled["receipt"]["ordered_region_ids"],
            "ordered_asset_ids": compiled["receipt"]["ordered_asset_ids"],
            "region_count": compiled["receipt"]["region_count"],
            "source_music_action": compiled["receipt"]["source_music_action"],
            "output_duration_ms": manifest["output_duration_ms"],
            "target_loudness_millilufs": compiled["receipt"][
                "target_loudness_millilufs"],
            "true_peak_ceiling_millidbtp": compiled["receipt"][
                "true_peak_ceiling_millidbtp"],
            "render_timeout_seconds": timeout,
            "program_input": {
                "sha256": program_binding["sha256"],
                "bytes": program_binding["bytes"],
                "duration_ms": program_probe["duration_ms"],
                "audio_present": program_probe["audio_present"],
            },
            "runtime_tools": tools,
            "asset_inputs": asset_receipts,
            "evidence_inputs": evidence_receipts,
            "filter_complex_sha256": filter_hash,
            "render_mode": render_mode,
            "mastering": mastering,
            "output": {
                "file": output.name, "sha256": _sha256_file(output),
                "bytes": output.stat().st_size,
                "duration_ms": output_probe["duration_ms"],
                "sample_rate_hz": output_probe["sample_rate_hz"],
                "channels": output_probe["channels"],
            },
        })
        return {
            "output_path": str(output),
            "filter_complex": filter_complex,
            "receipt": copy.deepcopy(receipt),
            "receipt_sha256": music_render_receipt_sha256(receipt),
            "compile_receipt": copy.deepcopy(compiled["receipt"]),
            "compile_receipt_sha256": compiled["receipt_sha256"],
        }
    except Exception:
        for path in reversed(created):
            try:
                if path.parent == work:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


__all__ = [
    "MUSIC_RENDER_RECEIPT_SCHEMA_VERSION",
    "MusicRenderError",
    "canonical_music_render_receipt_json",
    "derive_music_output_timeline_sha256",
    "execute_music_render",
    "music_render_receipt_sha256",
]
