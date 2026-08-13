"""Trusted execution boundary for a validated :mod:`autoeditor.sfx_plan`.

The planner contract deliberately emits inert filter primitives.  This module
is the corresponding local executor: it resolves only caller-supplied asset
IDs, snapshots and re-hashes every used asset and evidence file, probes the
decoded audio facts, constructs a label-safe FFmpeg graph without a shell, and
binds the delivered bytes in a closed receipt.

No model-provided path, stream label, or raw filter expression is executed.
All filter fragments originate from ``compile_sfx_plan`` in this process after
the plan, manifest, policy, rights, timeline, and speech-ducking rules pass.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from autoeditor.sfx_plan import (
    SfxPlanError,
    compile_sfx_plan,
    sfx_compile_receipt_sha256,
    validate_sfx_cue_manifest,
)


SFX_RENDER_RECEIPT_SCHEMA_VERSION = "autoeditor-sfx-render-receipt/v1"
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 4 * 1024 * 1024 * 1024
MAX_TOTAL_EVIDENCE_BYTES = 256 * 1024 * 1024
MIN_WORK_FREE_BYTES = 512 * 1024 * 1024
MAX_CAPTURE_CHARS = 16_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ASSET_ID = re.compile(r"^sfxasset-[0-9a-f]{64}$", re.ASCII)
_CUE_ID = re.compile(r"^sfxcue-[0-9a-f]{64}$", re.ASCII)
_SAFE_OUTPUT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.mp4$", re.ASCII)

_RECEIPT_KEYS = frozenset({
    "schema_version",
    "sfx_compile_receipt_sha256",
    "sfx_plan_sha256",
    "cue_manifest_sha256",
    "edit_policy_sha256",
    "output_timeline_sha256",
    "ordered_cue_ids",
    "ordered_asset_ids",
    "cue_count",
    "output_duration_ms",
    "render_timeout_seconds",
    "program_input",
    "runtime_tools",
    "asset_inputs",
    "evidence_inputs",
    "filter_complex_sha256",
    "render_mode",
    "output",
})
_PROGRAM_KEYS = frozenset({"sha256", "bytes", "duration_ms", "audio_present"})
_TOOL_KEYS = frozenset({"name", "sha256", "bytes"})
_ASSET_KEYS = frozenset({"asset_id", "sha256", "bytes", "duration_ms",
                         "sample_rate_hz", "channels"})
_EVIDENCE_KEYS = frozenset({"sha256", "bytes"})
_OUTPUT_KEYS = frozenset({"file", "sha256", "bytes", "duration_ms",
                          "sample_rate_hz", "channels"})


class SfxRenderError(RuntimeError):
    """The trusted SFX execution request or rendered artifact is invalid."""


def _fail(message: str) -> None:
    raise SfxRenderError(message)


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise SfxRenderError(f"{label} is not canonical JSON") from error


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
    milliseconds = _integer(value, "SFX duration", 0)
    return f"{milliseconds // 1000}.{milliseconds % 1000:03d}"


def _render_timeout_seconds(duration_ms: int, cue_count: int) -> int:
    # Audio filtering and video stream-copy are normally much faster than real
    # time, but long-form/large-cue contracts must not inherit a fixed 3-minute
    # wall clock.  The upper bound still prevents a wedged FFmpeg child from
    # living forever.
    return min(43_200, max(180, 120 + (duration_ms + 3_999) // 4_000
                           + cue_count * 5))


def _validate_command_length(command: list[str]) -> None:
    # Windows CreateProcess has a 32,767 UTF-16-character command-line bound.
    # Keep margin for Python/runtime quoting details and apply the same
    # deterministic contract on every platform so CI can exercise it.
    if len(subprocess.list2cmdline(command)) + 1 > 30_000:
        _fail("SFX render command exceeds the cross-platform argv bound")


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
        raise SfxRenderError(f"{label} is unavailable") from error
    if not real.is_file() or stat.st_size < 1:
        _fail(f"{label} is not a nonempty file")
    return real


def _safe_work_dir(value: object) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail("SFX work directory is invalid")
    raw = Path(value)
    if not raw.is_absolute():
        _fail("SFX work directory must be absolute")
    try:
        real = Path(os.path.realpath(raw))
        real.stat()
    except OSError as error:
        raise SfxRenderError("SFX work directory is unavailable") from error
    if not real.is_dir():
        _fail("SFX work directory is not a directory")
    return real


def _safe_output(value: object, work: Path) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail("SFX output path is invalid")
    raw = Path(value)
    if not raw.is_absolute() or _SAFE_OUTPUT.fullmatch(raw.name) is None:
        _fail("SFX output path must be an absolute safe MP4 filename")
    parent = Path(os.path.realpath(raw.parent))
    if parent != work:
        _fail("SFX output must stay inside its private work directory")
    output = parent / raw.name
    if output.exists():
        _fail("SFX output already exists")
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
        raise SfxRenderError(f"{label} could not be snapshotted") from error
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
            command, cwd=str(cwd), shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SfxRenderError(f"{label} could not complete") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-MAX_CAPTURE_CHARS:]
        raise SfxRenderError(
            f"{label} failed" + (f": {detail}" if detail else "")
        )
    return result


def _probe(path: Path, ffprobe: Path, work: Path, label: str,
           *, require_audio: bool = True) -> dict[str, Any]:
    result = _run([
        str(ffprobe), "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,sample_rate,channels", "-of", "json",
        str(path),
    ], cwd=work, label=f"{label} probe", timeout_seconds=30)
    try:
        value = json.loads(result.stdout)
        duration = float(value["format"]["duration"])
        streams = value["streams"]
        audio = next(
            (item for item in streams if item.get("codec_type") == "audio"),
            None,
        )
        video_present = any(item.get("codec_type") == "video" for item in streams)
        if audio is None:
            if require_audio:
                _fail(f"{label} has no audio stream")
            sample_rate = None
            channels = None
        else:
            sample_rate = int(audio["sample_rate"])
            channels = int(audio["channels"])
    except (KeyError, TypeError, ValueError,
            json.JSONDecodeError) as error:
        raise SfxRenderError(f"{label} technical metadata is invalid") from error
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


def _required_evidence_hashes(compiled: dict, manifest: dict) -> set[str]:
    required: set[str] = set()
    speech = manifest["speech_windows"]
    for cue in compiled["compiled_cues"]:
        required.add(cue["license"]["evidence_sha256"])
        required.add(cue["motivation"]["evidence_sha256"])
        if cue["ducking"] is not None:
            start = cue["output_start_ms"]
            end = cue["output_end_ms"]
            required.update(
                item["evidence_sha256"] for item in speech
                if item["end_ms"] > start and item["start_ms"] < end
            )
    return required


def _build_filter(compiled: dict, *, program_audio_present: bool = True) -> str:
    cues = compiled["compiled_cues"]
    if not cues:
        return ""
    program_source = "[0:a:0]" if program_audio_present else (
        "anullsrc=channel_layout=stereo:sample_rate=48000:"
        "d=" + _seconds(compiled["receipt"]["output_duration_ms"]) + ","
    )
    filters = [program_source + ",".join(
        compiled["program_input_ffmpeg_primitive_tokens"]
    ) + "[program]"]
    # Bind one decoder input to each unique, sorted asset.  Repeated cues fan
    # out from that trusted input inside the filter script; expanding one
    # ``-i`` per cue would exceed Windows CreateProcess limits at the closed
    # 2,048-cue contract ceiling and would open thousands of duplicate
    # decoders for a single sound.
    asset_ids = sorted({cue["asset_id"] for cue in cues})
    input_by_asset = {
        asset_id: index for index, asset_id in enumerate(asset_ids, 1)
    }
    cue_sources: dict[int, str] = {}
    for asset_id in asset_ids:
        cue_indexes = [
            index for index, cue in enumerate(cues, 1)
            if cue["asset_id"] == asset_id
        ]
        input_index = input_by_asset[asset_id]
        if len(cue_indexes) == 1:
            cue_sources[cue_indexes[0]] = f"{input_index}:a:0"
            continue
        labels = []
        for cue_index in cue_indexes:
            label = f"cue{cue_index:04d}src"
            cue_sources[cue_index] = label
            labels.append(f"[{label}]")
        filters.append(
            f"[{input_index}:a:0]asplit=outputs={len(cue_indexes)}"
            + "".join(labels)
        )
    cue_outputs: list[str] = []
    for index, cue in enumerate(cues, 1):
        pre = f"cue{index:04d}pre"
        ducked = f"cue{index:04d}duck"
        output = f"cue{index:04d}out"
        filters.append(
            f"[{cue_sources[index]}]" + ",".join(
                cue["cue_ffmpeg_primitive_tokens"]
            ) + f"[{pre}]"
        )
        input_label = pre
        if cue["ducking"] is not None:
            gate = f"cue{index:04d}gate"
            gate_tokens = cue["duck_sidechain_gate_ffmpeg_primitive_tokens"]
            compressor = cue["sidechaincompress_ffmpeg_primitive_tokens"]
            if len(gate_tokens) != 1 or len(compressor) != 1:
                _fail("compiled SFX duck topology is incomplete")
            filters.append(gate_tokens[0] + f"[{gate}]")
            filters.append(f"[{pre}][{gate}]" + compressor[0] + f"[{ducked}]")
            input_label = ducked
        filters.append(
            f"[{input_label}]" + ",".join(
                cue["timeline_ffmpeg_primitive_tokens"]
            ) + f"[{output}]"
        )
        cue_outputs.append(f"[{output}]")
    filters.append(
        "".join(cue_outputs) + ",".join(
            compiled["sfx_bus_ffmpeg_primitive_tokens"]
        ) + "[sfxbus]"
    )
    filters.append(
        "[program][sfxbus]" + ",".join(
            compiled["program_mix_ffmpeg_primitive_tokens"]
        ) + "[aout]"
    )
    return ";".join(filters)


def _normalize_receipt(value: object) -> dict[str, Any]:
    raw = _exact_dict(value, _RECEIPT_KEYS, "SFX render receipt")
    if raw["schema_version"] != SFX_RENDER_RECEIPT_SCHEMA_VERSION:
        _fail("SFX render receipt schema is unsupported")
    hashes = {
        key: _digest(raw[key], f"SFX render receipt.{key}")
        for key in (
            "sfx_compile_receipt_sha256", "sfx_plan_sha256",
            "cue_manifest_sha256", "edit_policy_sha256",
            "output_timeline_sha256", "filter_complex_sha256",
        )
    }
    cue_ids = raw["ordered_cue_ids"]
    if type(cue_ids) is not list or any(
        type(item) is not str or _CUE_ID.fullmatch(item) is None
        for item in cue_ids
    ) or len(set(cue_ids)) != len(cue_ids):
        _fail("SFX render receipt cue ids are invalid")
    cue_count = _integer(raw["cue_count"], "SFX render receipt.cue_count")
    if cue_count != len(cue_ids):
        _fail("SFX render receipt cue count does not match")
    ordered_asset_ids = raw["ordered_asset_ids"]
    if (type(ordered_asset_ids) is not list
            or len(ordered_asset_ids) != cue_count
            or any(type(item) is not str or _ASSET_ID.fullmatch(item) is None
                   for item in ordered_asset_ids)):
        _fail("SFX render receipt ordered asset ids are invalid")
    program = _exact_dict(raw["program_input"], _PROGRAM_KEYS,
                          "SFX render receipt.program_input")
    normalized_program = {
        "sha256": _digest(program["sha256"], "program input sha256"),
        "bytes": _integer(program["bytes"], "program input bytes", 1),
        "duration_ms": _integer(program["duration_ms"],
                                "program input duration", 1),
        "audio_present": program["audio_present"],
    }
    if type(normalized_program["audio_present"]) is not bool:
        _fail("SFX render receipt program audio presence is invalid")
    tools = raw["runtime_tools"]
    if type(tools) is not list or len(tools) != 2:
        _fail("SFX render receipt runtime tools are invalid")
    normalized_tools = []
    for index, tool in enumerate(tools):
        item = _exact_dict(
            tool, _TOOL_KEYS, f"SFX render receipt.runtime_tools[{index}]")
        if item["name"] not in {"ffmpeg", "ffprobe"}:
            _fail("SFX render receipt runtime tool name is invalid")
        normalized_tools.append({
            "name": item["name"],
            "sha256": _digest(item["sha256"], "SFX runtime tool sha256"),
            "bytes": _integer(item["bytes"], "SFX runtime tool bytes", 1),
        })
    if (normalized_tools != sorted(normalized_tools, key=lambda item: item["name"])
            or {item["name"] for item in normalized_tools} != {"ffmpeg", "ffprobe"}):
        _fail("SFX render receipt runtime tools are not exact and sorted")
    assets = raw["asset_inputs"]
    if type(assets) is not list:
        _fail("SFX render receipt asset inputs are invalid")
    normalized_assets = []
    for index, asset in enumerate(assets):
        item = _exact_dict(asset, _ASSET_KEYS,
                           f"SFX render receipt.asset_inputs[{index}]")
        asset_id = item["asset_id"]
        if type(asset_id) is not str or _ASSET_ID.fullmatch(asset_id) is None:
            _fail("SFX render receipt asset id is invalid")
        normalized_assets.append({
            "asset_id": asset_id,
            "sha256": _digest(item["sha256"], "SFX asset sha256"),
            "bytes": _integer(item["bytes"], "SFX asset bytes", 1),
            "duration_ms": _integer(item["duration_ms"], "SFX asset duration", 1),
            "sample_rate_hz": _integer(item["sample_rate_hz"],
                                       "SFX asset sample rate", 1),
            "channels": _integer(item["channels"], "SFX asset channels", 1),
        })
    if normalized_assets != sorted(normalized_assets,
                                   key=lambda item: item["asset_id"]):
        _fail("SFX render receipt asset inputs are not sorted")
    if len({item["asset_id"] for item in normalized_assets}) != len(
            normalized_assets):
        _fail("SFX render receipt asset inputs contain duplicates")
    if {item["asset_id"] for item in normalized_assets} != set(
            ordered_asset_ids):
        _fail("SFX render receipt asset inventory contradicts its cues")
    evidence = raw["evidence_inputs"]
    if type(evidence) is not list:
        _fail("SFX render receipt evidence inputs are invalid")
    normalized_evidence = []
    for index, item_raw in enumerate(evidence):
        item = _exact_dict(item_raw, _EVIDENCE_KEYS,
                           f"SFX render receipt.evidence_inputs[{index}]")
        normalized_evidence.append({
            "sha256": _digest(item["sha256"], "SFX evidence sha256"),
            "bytes": _integer(item["bytes"], "SFX evidence bytes", 1),
        })
    if normalized_evidence != sorted(normalized_evidence,
                                     key=lambda item: item["sha256"]):
        _fail("SFX render receipt evidence inputs are not sorted")
    if len({item["sha256"] for item in normalized_evidence}) != len(
            normalized_evidence):
        _fail("SFX render receipt evidence inputs contain duplicates")
    if raw["render_mode"] not in {
            "mixed", "no_cues_copy", "no_cues_normalized"}:
        _fail("SFX render receipt mode is invalid")
    if (raw["render_mode"] == "mixed") != bool(cue_count):
        _fail("SFX render receipt mode contradicts its cue count")
    if (raw["render_mode"] == "no_cues_copy"
            and not normalized_program["audio_present"]):
        _fail("SFX byte-copy mode cannot claim a missing program audio stream")
    output_duration_ms = _integer(
        raw["output_duration_ms"], "SFX render receipt output duration", 1)
    render_timeout_seconds = _integer(
        raw["render_timeout_seconds"], "SFX render receipt timeout", 180)
    if render_timeout_seconds != _render_timeout_seconds(
            output_duration_ms, cue_count):
        _fail("SFX render receipt timeout does not bind its workload")
    output = _exact_dict(raw["output"], _OUTPUT_KEYS,
                         "SFX render receipt.output")
    if type(output["file"]) is not str or _SAFE_OUTPUT.fullmatch(
            output["file"]) is None:
        _fail("SFX render receipt output filename is invalid")
    normalized_output = {
        "file": output["file"],
        "sha256": _digest(output["sha256"], "SFX output sha256"),
        "bytes": _integer(output["bytes"], "SFX output bytes", 1),
        "duration_ms": _integer(output["duration_ms"], "SFX output duration", 1),
        "sample_rate_hz": _integer(output["sample_rate_hz"],
                                   "SFX output sample rate", 1),
        "channels": _integer(output["channels"], "SFX output channels", 1),
    }
    if (normalized_output["sample_rate_hz"] != 48_000
            or normalized_output["channels"] != 2):
        _fail("SFX output is not exact 48000 Hz stereo delivery audio")
    if cue_count == 0:
        empty_filter_hash = hashlib.sha256(b"").hexdigest()
        if (ordered_asset_ids or normalized_assets or normalized_evidence
                or hashes["filter_complex_sha256"] != empty_filter_hash):
            _fail("no-cue SFX receipt contains an unexpected render topology")
    if raw["render_mode"] == "no_cues_copy" and (
            normalized_output["sha256"] != normalized_program["sha256"]
            or normalized_output["bytes"] != normalized_program["bytes"]):
        _fail("SFX byte-copy mode does not preserve the program bytes")
    if (abs(normalized_program["duration_ms"] - output_duration_ms) > 100
            or abs(normalized_output["duration_ms"] - output_duration_ms) > 100):
        _fail("SFX render receipt input/output timelines contradict")
    expected_timeline = derive_sfx_output_timeline_sha256(
        program_sha256=normalized_program["sha256"],
        program_bytes=normalized_program["bytes"],
        duration_ms=output_duration_ms,
    )
    if hashes["output_timeline_sha256"] != expected_timeline:
        _fail("SFX render receipt timeline does not bind its program input")
    return {
        "schema_version": SFX_RENDER_RECEIPT_SCHEMA_VERSION,
        **hashes,
        "ordered_cue_ids": list(cue_ids),
        "ordered_asset_ids": list(ordered_asset_ids),
        "cue_count": cue_count,
        "output_duration_ms": output_duration_ms,
        "render_timeout_seconds": render_timeout_seconds,
        "program_input": normalized_program,
        "runtime_tools": normalized_tools,
        "asset_inputs": normalized_assets,
        "evidence_inputs": normalized_evidence,
        "filter_complex_sha256": hashes["filter_complex_sha256"],
        "render_mode": raw["render_mode"],
        "output": normalized_output,
    }


def canonical_sfx_render_receipt_json(receipt: object) -> str:
    return _canonical_json(_normalize_receipt(receipt), "SFX render receipt")


def sfx_render_receipt_sha256(receipt: object) -> str:
    return hashlib.sha256(
        canonical_sfx_render_receipt_json(receipt).encode("utf-8")
    ).hexdigest()


def derive_sfx_output_timeline_sha256(
    *, program_sha256: object, program_bytes: object, duration_ms: object,
) -> str:
    """Bind a cue timeline to the exact program artifact it will modify."""
    binding = {
        "schema_version": "autoeditor-sfx-output-timeline/v1",
        "program_sha256": _digest(program_sha256, "SFX timeline program sha256"),
        "program_bytes": _integer(program_bytes, "SFX timeline program bytes", 1),
        "duration_ms": _integer(duration_ms, "SFX timeline duration", 1),
        "time_base": {"numerator": 1, "denominator": 1_000},
    }
    return hashlib.sha256(
        _canonical_json(binding, "SFX output timeline").encode("utf-8")
    ).hexdigest()


def execute_sfx_render(
    *,
    program_path: str,
    output_path: str,
    plan: object,
    cue_manifest: object,
    edit_policy: object,
    asset_paths: Mapping[str, str],
    evidence_paths: Mapping[str, str],
    work_dir: str,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> dict[str, Any]:
    """Render the exact validated SFX mix and return a closed byte receipt."""
    work = _safe_work_dir(work_dir)
    program_source = _safe_existing_file(program_path, "program input")
    output = _safe_output(output_path, work)
    ffmpeg = _safe_existing_file(ffmpeg_path, "FFmpeg")
    ffprobe = _safe_existing_file(ffprobe_path, "FFprobe")
    if output == program_source:
        _fail("SFX output cannot overwrite the program input")
    try:
        tool_bindings = []
        tool_paths = {"ffmpeg": ffmpeg, "ffprobe": ffprobe}
        for name in sorted(tool_paths):
            tool_path = tool_paths[name]
            tool_bindings.append({
                "name": name,
                "sha256": _sha256_file(tool_path),
                "bytes": tool_path.stat().st_size,
            })
        manifest = validate_sfx_cue_manifest(cue_manifest)
        compiled = compile_sfx_plan(plan, manifest, edit_policy)
    except SfxPlanError as error:
        raise SfxRenderError(f"SFX execution contract is invalid: {error}") from error

    assets_by_id = {item["asset_id"]: item for item in manifest["assets"]}
    used_asset_ids = sorted({
        item["asset_id"] for item in compiled["compiled_cues"]
    })
    normalized_asset_paths = _path_map(asset_paths, _ASSET_ID, "SFX asset paths")
    if set(normalized_asset_paths) != set(used_asset_ids):
        _fail("SFX asset path inventory does not exactly match used assets")
    required_evidence = _required_evidence_hashes(compiled, manifest)
    normalized_evidence_paths = _path_map(
        evidence_paths, _SHA256, "SFX evidence paths"
    )
    if set(normalized_evidence_paths) != required_evidence:
        _fail("SFX evidence path inventory is incomplete or excessive")

    created: list[Path] = []
    snapshots: list[dict[str, Any]] = []
    try:
        total_asset_bytes = sum(
            assets_by_id[asset_id]["byte_length"] for asset_id in used_asset_ids
        )
        evidence_sizes: dict[str, int] = {}
        for digest in required_evidence:
            evidence_source = _safe_existing_file(
                normalized_evidence_paths[digest], f"SFX evidence {digest}"
            )
            evidence_sizes[digest] = evidence_source.stat().st_size
        total_evidence_bytes = sum(evidence_sizes.values())
        if (total_asset_bytes > MAX_TOTAL_ASSET_BYTES
                or total_evidence_bytes > MAX_TOTAL_EVIDENCE_BYTES
                or any(size > MAX_EVIDENCE_BYTES
                       for size in evidence_sizes.values())):
            _fail("SFX execution inputs exceed their aggregate byte bounds")
        try:
            free_bytes = shutil.disk_usage(work).free
        except OSError as error:
            raise SfxRenderError("SFX work volume could not be measured") from error
        required_free = (
            program_source.stat().st_size * 3 + total_asset_bytes
            + total_evidence_bytes + MIN_WORK_FREE_BYTES
        )
        if free_bytes < required_free:
            _fail("SFX work volume lacks space for private snapshots and output")
        program_stat = program_source.stat()
        program_hash = _sha256_file(program_source)
        program_snapshot = work / "sfx-program-input.mp4"
        program_binding = _snapshot(
            program_source, program_snapshot, program_hash,
            program_stat.st_size, "program input",
        )
        created.append(program_snapshot)
        program_probe = _probe(
            program_snapshot, ffprobe, work, "program input",
            require_audio=False,
        )
        if not program_probe["video_present"]:
            _fail("SFX program input has no video stream")
        if abs(program_probe["duration_ms"] - manifest["output_duration_ms"]) > 100:
            _fail("SFX program duration does not bind the output timeline")
        measured_timeline_hash = derive_sfx_output_timeline_sha256(
            program_sha256=program_binding["sha256"],
            program_bytes=program_binding["bytes"],
            duration_ms=manifest["output_duration_ms"],
        )
        if manifest["output_timeline_sha256"] != measured_timeline_hash:
            _fail("SFX cue manifest does not bind the exact program timeline")
        snapshots.append(program_binding)

        asset_snapshots: dict[str, dict[str, Any]] = {}
        asset_receipts: list[dict[str, Any]] = []
        for index, asset_id in enumerate(used_asset_ids, 1):
            asset = assets_by_id[asset_id]
            source = _safe_existing_file(
                normalized_asset_paths[asset_id], f"SFX asset {asset_id}"
            )
            snapshot_path = work / f"sfx-asset-{index:04d}.bin"
            binding = _snapshot(
                source, snapshot_path, asset["sha256"], asset["byte_length"],
                f"SFX asset {asset_id}",
            )
            created.append(snapshot_path)
            facts = _probe(snapshot_path, ffprobe, work, f"SFX asset {asset_id}")
            if facts["video_present"] or (
                abs(facts["duration_ms"] - asset["duration_ms"]) > 50
                or facts["sample_rate_hz"] != asset["sample_rate_hz"]
                or facts["channels"] != asset["channels"]
            ):
                _fail(f"SFX asset {asset_id} decoded facts changed")
            asset_snapshots[asset_id] = {**binding, "facts": facts}
            snapshots.append(binding)
            asset_receipts.append({
                "asset_id": asset_id,
                "sha256": binding["sha256"],
                "bytes": binding["bytes"],
                "duration_ms": facts["duration_ms"],
                "sample_rate_hz": facts["sample_rate_hz"],
                "channels": facts["channels"],
            })

        evidence_receipts: list[dict[str, Any]] = []
        for index, digest in enumerate(sorted(required_evidence), 1):
            source = _safe_existing_file(
                normalized_evidence_paths[digest], f"SFX evidence {digest}"
            )
            snapshot_path = work / f"sfx-evidence-{index:04d}.bin"
            binding = _snapshot(
                source, snapshot_path, digest, evidence_sizes[digest],
                f"SFX evidence {digest}",
            )
            created.append(snapshot_path)
            snapshots.append(binding)
            evidence_receipts.append({
                "sha256": binding["sha256"], "bytes": binding["bytes"],
            })

        filter_complex = _build_filter(
            compiled, program_audio_present=program_probe["audio_present"])
        filter_hash = hashlib.sha256(filter_complex.encode("utf-8")).hexdigest()
        render_timeout = _render_timeout_seconds(
            manifest["output_duration_ms"], len(compiled["compiled_cues"]))
        # From this point onward an error must remove any partial final output.
        # The target was already validated as a fixed safe child of ``work``.
        created.append(output)
        if compiled["compiled_cues"]:
            filter_script = work / "sfx-filter.txt"
            if filter_script.exists():
                _fail("private SFX filter script already exists")
            created.append(filter_script)
            try:
                with filter_script.open(
                        "x", encoding="utf-8", errors="strict", newline="\n") as stream:
                    stream.write(filter_complex)
            except OSError as error:
                raise SfxRenderError(
                    "private SFX filter script could not be created") from error
            asset_input_aliases: list[str] = []
            for asset_id in used_asset_ids:
                snapshot = asset_snapshots[asset_id]["path"]
                asset_input_aliases.extend(["-i", f".{os.sep}{snapshot.name}"])
            command = [
                str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
                "-n", "-i", f".{os.sep}{program_snapshot.name}",
                *asset_input_aliases,
                "-filter_complex_script", f".{os.sep}{filter_script.name}",
                "-map", "0:v:0", "-map", "[aout]", "-map_metadata", "-1",
                "-map_chapters", "-1", "-sn", "-dn", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-t", f"{manifest['output_duration_ms'] // 1000}."
                f"{manifest['output_duration_ms'] % 1000:03d}",
                "-movflags", "+faststart", f".{os.sep}{output.name}",
            ]
            _validate_command_length(command)
            _run(
                command, cwd=work, label="SFX render",
                timeout_seconds=render_timeout,
            )
            render_mode = "mixed"
        elif (program_probe["audio_present"]
              and program_probe["sample_rate_hz"] == 48_000
              and program_probe["channels"] == 2):
            # A no-cue policy is a byte-preserving, exclusive copy.  This makes
            # the receipt useful without invoking a filter graph or pretending
            # an effect was rendered.
            with program_snapshot.open("rb") as source_stream, output.open("xb") as out:
                shutil.copyfileobj(source_stream, out, 1024 * 1024)
            render_mode = "no_cues_copy"
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
                "-map_metadata", "-1",
                "-map_chapters", "-1", "-sn", "-dn", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-t", _seconds(manifest["output_duration_ms"]),
                "-movflags", "+faststart", f".{os.sep}{output.name}",
            ])
            _validate_command_length(command)
            _run(
                command, cwd=work, label="SFX silence normalization",
                timeout_seconds=render_timeout,
            )
            render_mode = "no_cues_normalized"

        for snapshot in snapshots:
            path = snapshot["path"]
            if (path.stat().st_size != snapshot["bytes"]
                    or _sha256_file(path) != snapshot["sha256"]):
                output.unlink(missing_ok=True)
                _fail("an SFX execution input changed during rendering")
        for binding in tool_bindings:
            tool_path = tool_paths[binding["name"]]
            if (tool_path.stat().st_size != binding["bytes"]
                    or _sha256_file(tool_path) != binding["sha256"]):
                output.unlink(missing_ok=True)
                _fail("an SFX runtime tool changed during rendering")
        output_probe = _probe(output, ffprobe, work, "SFX output")
        if (not output_probe["video_present"]
                or abs(output_probe["duration_ms"]
                       - manifest["output_duration_ms"]) > 100
                or output_probe["sample_rate_hz"] != 48_000
                or output_probe["channels"] != 2):
            output.unlink(missing_ok=True)
            _fail("SFX output failed its exact delivery probe")
        receipt = _normalize_receipt({
            "schema_version": SFX_RENDER_RECEIPT_SCHEMA_VERSION,
            "sfx_compile_receipt_sha256": sfx_compile_receipt_sha256(
                compiled["receipt"]
            ),
            "sfx_plan_sha256": compiled["receipt"]["sfx_plan_sha256"],
            "cue_manifest_sha256": compiled["receipt"]["cue_manifest_sha256"],
            "edit_policy_sha256": compiled["receipt"]["edit_policy_sha256"],
            "output_timeline_sha256": compiled["receipt"][
                "output_timeline_sha256"
            ],
            "ordered_cue_ids": compiled["receipt"]["ordered_cue_ids"],
            "ordered_asset_ids": compiled["receipt"]["ordered_asset_ids"],
            "cue_count": compiled["receipt"]["cue_count"],
            "output_duration_ms": manifest["output_duration_ms"],
            "render_timeout_seconds": render_timeout,
            "program_input": {
                "sha256": program_binding["sha256"],
                "bytes": program_binding["bytes"],
                "duration_ms": program_probe["duration_ms"],
                "audio_present": program_probe["audio_present"],
            },
            "runtime_tools": tool_bindings,
            "asset_inputs": asset_receipts,
            "evidence_inputs": evidence_receipts,
            "filter_complex_sha256": filter_hash,
            "render_mode": render_mode,
            "output": {
                "file": output.name,
                "sha256": _sha256_file(output),
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
            "receipt_sha256": sfx_render_receipt_sha256(receipt),
            "compile_receipt": copy.deepcopy(compiled["receipt"]),
            "compile_receipt_sha256": compiled["receipt_sha256"],
        }
    except Exception:
        # Only private, fixed-name files inside the validated work directory
        # are cleaned.  Caller-owned sources and evidence are never mutated.
        for path in reversed(created):
            try:
                if path.parent == work:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


__all__ = [
    "SFX_RENDER_RECEIPT_SCHEMA_VERSION",
    "SfxRenderError",
    "canonical_sfx_render_receipt_json",
    "derive_sfx_output_timeline_sha256",
    "execute_sfx_render",
    "sfx_render_receipt_sha256",
]
