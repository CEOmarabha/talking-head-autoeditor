"""ProjectIntent-authorized production SFX orchestration.

This module is the trusted producer above :mod:`autoeditor.sfx_plan` and
:mod:`autoeditor.sfx_render`.  It specializes an authenticated, same-band
edit policy to the exact rendered program duration, derives cue anchors only
from hash-bound EDL/renderer/boundary evidence, creates deterministic local
project-owned cue bytes, executes the closed FFmpeg renderer, and persists a
complete receipt chain.

It intentionally does not resolve legacy tuple SFX, contact a sound-generation
service, or infer rights to user/external audio.  A caller may keep the legacy
path only when no ProjectIntent envelope was supplied.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import wave
from typing import Any, Iterable

from autoeditor import creative_contract
from autoeditor.edit_policy import (
    CAPABILITIES,
    duration_band,
    edit_policy_sha256,
    validate_edit_policy,
)
from autoeditor.project_intent_authority import (
    build_project_intent_engine_envelope,
    canonical_project_intent_engine_envelope_bytes,
    project_intent_engine_envelope_sha256,
    validate_project_intent_engine_envelope,
)
from autoeditor.project_intent_policy_bridge import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_MANIFEST_SOURCE,
    PROJECT_INTENT_SCHEMA_VERSION,
    resolve_project_intent_policy,
)
from autoeditor.sfx_plan import (
    SFX_CUE_MANIFEST_SCHEMA_VERSION,
    SFX_PLAN_SCHEMA_VERSION,
    compile_sfx_plan,
    derive_sfx_anchor_id,
    derive_sfx_asset_id,
    derive_sfx_cue_id,
    derive_sfx_policy_limits,
    derive_speech_window_id,
    sfx_compile_receipt_sha256,
    sfx_cue_manifest_sha256,
    sfx_plan_sha256,
    validate_sfx_cue_manifest,
    validate_sfx_plan,
)
from autoeditor.sfx_render import (
    canonical_sfx_render_receipt_json,
    derive_sfx_output_timeline_sha256,
    execute_sfx_render,
    sfx_render_receipt_sha256,
)


SFX_PRODUCTION_RECEIPT_SCHEMA_VERSION = "autoeditor-sfx-production-receipt/v1"
SFX_PRODUCTION_SELF_TEST_SCHEMA_VERSION = (
    "autoeditor-sfx-production-self-test/v1"
)
SFX_GENERATION_EVIDENCE_SCHEMA_VERSION = "autoeditor-sfx-generation-evidence/v1"
SFX_ANCHOR_EVIDENCE_SCHEMA_VERSION = "autoeditor-sfx-anchor-evidence/v1"
SFX_SPEECH_EVIDENCE_SCHEMA_VERSION = "autoeditor-sfx-speech-evidence/v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SAFE_FILE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}\.(?:json|wav)$", re.ASCII)
_PRODUCTION_KEYS = frozenset({
    "schema_version", "mode", "authorization_id",
    "engine_envelope_sha256", "project_intent_sha256",
    "parent_edit_policy_sha256", "execution_edit_policy_sha256",
    "target_duration", "actual_duration_ms", "duration_band",
    "requested_preference", "policy", "cue_count",
    "output_timeline_sha256", "program_input", "output",
    "cue_manifest_sha256", "sfx_plan_sha256",
    "sfx_compile_receipt_sha256", "sfx_render_receipt_sha256",
    "sidecars",
})
_TARGET_KEYS = frozenset({"min_ms", "max_ms"})
_POLICY_KEYS = frozenset({"density", "usage"})
_MEDIA_KEYS = frozenset({"sha256", "bytes", "duration_ms"})
_SIDECAR_KEYS = frozenset({"file", "sha256", "bytes"})
_MODES = frozenset({"rendered", "no_sfx_requested", "no_motivated_anchor"})
_SAMPLE_RATE = 48_000
_CHANNELS = 2
_MAX_CAPTURE_CHARS = 12_000


class SfxProductionError(RuntimeError):
    """Typed SFX authority, production evidence, or output was invalid."""


def _fail(message: str) -> None:
    raise SfxProductionError(message)


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise SfxProductionError(f"{label} is not canonical JSON") from error


def _canonical_bytes(value: object, label: str) -> bytes:
    return (_canonical_json(value, label) + "\n").encode("ascii")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _exact_dict(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict or set(value) != set(keys):
        _fail(f"{label} does not match the closed contract")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{label} must be an integer of at least {minimum}")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be a full lowercase SHA-256 digest")
    return value


def _absolute_file(value: object, label: str) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute():
        _fail(f"{label} path must be absolute")
    try:
        path = Path(os.path.realpath(path))
        size = path.stat().st_size
    except OSError as error:
        raise SfxProductionError(f"{label} is unavailable") from error
    if not path.is_file() or size < 1:
        _fail(f"{label} must be a nonempty file")
    return path


def _absolute_dir(value: object, label: str) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute():
        _fail(f"{label} path must be absolute")
    try:
        path = Path(os.path.realpath(path))
        path.stat()
    except OSError as error:
        raise SfxProductionError(f"{label} is unavailable") from error
    if not path.is_dir():
        _fail(f"{label} must be a directory")
    return path


def _run(command: list[str], *, cwd: Path, label: str,
         timeout_seconds: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, cwd=str(cwd), shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SfxProductionError(f"{label} could not complete") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-_MAX_CAPTURE_CHARS:]
        raise SfxProductionError(
            f"{label} failed" + (f": {detail}" if detail else "")
        )
    return result


def _probe_program(program: Path, ffprobe: Path, cwd: Path) -> dict[str, Any]:
    result = _run([
        str(ffprobe), "-v", "error", "-show_entries",
        "format=duration:stream=codec_type", "-of", "json", str(program),
    ], cwd=cwd, label="typed SFX program probe", timeout_seconds=30)
    try:
        value = json.loads(result.stdout)
        duration_ms = round(float(value["format"]["duration"]) * 1000)
        streams = value["streams"]
        video = any(item.get("codec_type") == "video" for item in streams)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SfxProductionError("typed SFX program facts are invalid") from error
    if duration_ms < 1 or not video:
        _fail("typed SFX program must contain a positive video timeline")
    return {
        "sha256": _sha256_file(program),
        "bytes": program.stat().st_size,
        "duration_ms": duration_ms,
    }


def specialize_edit_policy_for_program(
    parent_policy: object,
    *,
    target_duration: object,
    actual_duration_ms: object,
) -> dict[str, Any]:
    """Create an exact-duration child policy without changing any rule.

    ProjectIntent ranges are required by the bridge to stay inside one policy
    band.  The parent is resolved at the conservative maximum.  This child
    changes only ``duration.duration_ms`` so SFX density is calculated against
    the exact program; its parent and child hashes are both retained later.
    """
    try:
        parent = validate_edit_policy(parent_policy)
    except Exception as error:
        raise SfxProductionError("parent edit policy is invalid") from error
    target = _exact_dict(target_duration, _TARGET_KEYS, "target duration")
    minimum = _integer(target["min_ms"], "target duration minimum", 1)
    maximum = _integer(target["max_ms"], "target duration maximum", 1)
    actual = _integer(actual_duration_ms, "actual duration", 1)
    if minimum > maximum or not minimum <= actual <= maximum:
        _fail("actual program duration is outside ProjectIntent bounds")
    if (duration_band(minimum) != duration_band(maximum)
            or duration_band(actual) != parent["duration"]["band"]
            or actual > parent["duration"]["duration_ms"]):
        _fail("actual program duration is outside the authorized policy band")
    child = copy.deepcopy(parent)
    child["duration"]["duration_ms"] = actual
    try:
        child = validate_edit_policy(child)
    except Exception as error:
        raise SfxProductionError(
            "exact-duration edit policy specialization is invalid"
        ) from error
    parent_without_duration = copy.deepcopy(parent)
    child_without_duration = copy.deepcopy(child)
    parent_without_duration.pop("duration")
    child_without_duration.pop("duration")
    if parent_without_duration != child_without_duration:
        _fail("exact-duration edit policy changed an unauthorized rule")
    return child


def _write_private(path: Path, data: bytes, label: str) -> Path:
    if path.exists():
        _fail(f"{label} already exists")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        path.unlink(missing_ok=True)
        raise SfxProductionError(f"{label} could not be written") from error
    return path


def _write_json(path: Path, value: object, label: str) -> Path:
    return _write_private(path, _canonical_bytes(value, label), label)


def _finite_milliseconds(value: object, label: str,
                         duration_ms: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{label} must be a finite number")
    milliseconds = round(number * 1000)
    if not 0 <= milliseconds <= duration_ms:
        _fail(f"{label} is outside the exact output timeline")
    return milliseconds


def _edl_evidence(
    edl: object,
    *,
    rendered_graphics: object,
    rendered_broll: object,
    duration_ms: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if type(edl) is not dict:
        _fail("typed SFX requires an exact validated EDL")
    public = creative_contract.public_edl(edl)
    receipt = edl.get("production_receipt")
    if type(receipt) is not dict:
        _fail("typed SFX EDL lacks a production receipt")
    measured = creative_contract.edl_sha256(edl)
    if (receipt.get("source") != "deepseek"
            or receipt.get("protocol_version") != creative_contract.PROTOCOL_VERSION
            or receipt.get("contract_sha256") != creative_contract.contract_sha256()
            or receipt.get("validated_plan_sha256") != measured):
        _fail("typed SFX EDL is not bound to its validated production plan")
    evidence = {
        "schema_version": SFX_ANCHOR_EVIDENCE_SCHEMA_VERSION,
        "kind": "validated_edl",
        "edl_sha256": measured,
        "protocol_version": creative_contract.PROTOCOL_VERSION,
        "public_edl": public,
        "rendered_graphics": [
            {"start_ms": start, "end_ms": end}
            for start, end in sorted(_rendered_event_set(
                rendered_graphics, "rendered graphics", duration_ms))
        ],
        "rendered_broll": [
            {"start_ms": start, "end_ms": end}
            for start, end in sorted(_rendered_event_set(
                rendered_broll, "rendered b-roll", duration_ms))
        ],
    }
    return public, evidence


def _rendered_event_set(events: object, label: str,
                        duration_ms: int) -> set[tuple[int, int]]:
    if type(events) is not list:
        _fail(f"{label} must be a list")
    result: set[tuple[int, int]] = set()
    for index, event in enumerate(events):
        if type(event) is not dict:
            _fail(f"{label}[{index}] must be an object")
        start = _finite_milliseconds(event.get("s"), f"{label}[{index}].s",
                                     duration_ms)
        end = _finite_milliseconds(event.get("e"), f"{label}[{index}].e",
                                   duration_ms)
        if end <= start:
            _fail(f"{label}[{index}] has no positive duration")
        result.add((start, end))
    return result


def _candidate_events(
    public_edl: dict[str, Any],
    *,
    rendered_graphics: object,
    rendered_broll: object,
    duration_ms: int,
    evidence_sha256: str,
) -> list[dict[str, Any]]:
    confirmed_graphics = _rendered_event_set(
        rendered_graphics, "rendered graphics", duration_ms)
    confirmed_broll = _rendered_event_set(
        rendered_broll, "rendered b-roll", duration_ms)
    candidates: list[dict[str, Any]] = []

    def add(layer: str, index: int, start: int, end: int,
            kind: str, cue_kind: str, anchor_ms: int) -> None:
        fingerprint = _sha256_bytes(_canonical_json({
            "edl_sha256": creative_contract.edl_sha256(public_edl),
            "layer": layer, "index": index, "start_ms": start,
            "end_ms": end, "kind": kind, "anchor_ms": anchor_ms,
        }, "SFX event anchor").encode("ascii"))
        payload = {
            "category": "event",
            "reference_id": "event-" + fingerprint[:32],
            "time_ms": anchor_ms,
            "evidence_start_ms": start,
            "evidence_end_ms": end,
            "evidence_sha256": evidence_sha256,
        }
        candidates.append({
            "anchor": {
                "anchor_id": derive_sfx_anchor_id(payload, duration_ms),
                **payload,
            },
            "cue_kind": cue_kind,
            "source_kind": kind,
        })

    for index, event in enumerate(public_edl.get("graphics", [])):
        start = _finite_milliseconds(event.get("s"),
                                     f"graphics[{index}].s", duration_ms)
        end = _finite_milliseconds(event.get("e"),
                                   f"graphics[{index}].e", duration_ms)
        if (start, end) not in confirmed_graphics:
            continue
        kind = str(event.get("kind", "keyword")).lower()
        if kind == "stat":
            landing = min(end, start + 1_450)
            add("graphics", index, start, end, kind, "impact", landing)
        else:
            add("graphics", index, start, end, kind, "whoosh", start)

    for index, event in enumerate(public_edl.get("broll", [])):
        start = _finite_milliseconds(event.get("s"),
                                     f"broll[{index}].s", duration_ms)
        end = _finite_milliseconds(event.get("e"),
                                   f"broll[{index}].e", duration_ms)
        if (start, end) not in confirmed_broll:
            continue
        viz = event.get("viz")
        if type(viz) is dict and str(viz.get("template", "")).lower() == "steps":
            add("broll", index, start, end, "steps", "whoosh", start)
    return sorted(
        candidates,
        key=lambda item: (item["anchor"]["time_ms"], item["anchor"]["anchor_id"]),
    )


def _boundary_anchors(boundaries: object, *, duration_ms: int,
                      evidence_sha256: str) -> list[dict[str, Any]]:
    if type(boundaries) is not dict or boundaries.get("timeline") != "post_cut_seconds":
        _fail("typed SFX requires a post-cut edit-boundary receipt")
    cuts = boundaries.get("cuts")
    if type(cuts) is not list:
        _fail("typed SFX boundary receipt has invalid cuts")
    anchors = []
    for index, cut in enumerate(cuts):
        if type(cut) is not dict:
            _fail(f"typed SFX boundary {index} is invalid")
        time_ms = _finite_milliseconds(
            cut.get("time_seconds"), f"boundary[{index}].time_seconds",
            duration_ms,
        )
        row_hash = _sha256_bytes(_canonical_json(
            {"index": index, "cut": cut}, f"typed SFX boundary {index}"
        ).encode("ascii"))
        payload = {
            "category": "boundary",
            "reference_id": "boundary-" + row_hash,
            "time_ms": time_ms,
            "evidence_start_ms": max(0, time_ms - 100),
            "evidence_end_ms": min(duration_ms, time_ms + 100),
            "evidence_sha256": evidence_sha256,
        }
        anchors.append({
            "anchor_id": derive_sfx_anchor_id(payload, duration_ms), **payload,
        })
    return anchors


def _speech_evidence(words: object, duration_ms: int) -> tuple[dict, list[dict]]:
    if type(words) is not list:
        _fail("typed SFX speech evidence must be a list")
    rows: list[dict[str, Any]] = []
    raw_windows: list[tuple[int, int]] = []
    previous_start = -1
    for index, word in enumerate(words):
        if type(word) is not dict:
            _fail(f"typed SFX speech word {index} is invalid")
        start = _finite_milliseconds(
            word.get("s"), f"speech_words[{index}].s", duration_ms)
        end = _finite_milliseconds(
            word.get("e"), f"speech_words[{index}].e", duration_ms)
        text = word.get("w")
        if type(text) is not str or not text or end <= start or start < previous_start:
            _fail(f"typed SFX speech word {index} is malformed")
        previous_start = start
        rows.append({"index": index, "start_ms": start, "end_ms": end,
                     "text": text})
        raw_windows.append((start, end))
    merged: list[list[int]] = []
    for start, end in raw_windows:
        if merged and start <= merged[-1][1] + 250:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    evidence = {
        "schema_version": SFX_SPEECH_EVIDENCE_SCHEMA_VERSION,
        "duration_ms": duration_ms,
        "words": rows,
    }
    digest = _sha256_bytes(_canonical_bytes(evidence, "SFX speech evidence"))
    windows = []
    for start, end in merged:
        payload = {
            "start_ms": start, "end_ms": end,
            "evidence_sha256": digest,
        }
        windows.append({
            "speech_id": derive_speech_window_id(payload, duration_ms), **payload,
        })
    return evidence, windows


def _cue_pcm(kind: str) -> tuple[bytes, int]:
    duration_ms = {"impact": 1_000, "whoosh": 800,
                   "interface_feedback": 300}[kind]
    frames = duration_ms * _SAMPLE_RATE // 1000
    pcm = bytearray(frames * _CHANNELS * 2)
    state = {"impact": 0x13579BDF, "whoosh": 0x2468ACE1,
             "interface_feedback": 0x10293847}[kind]
    smooth = 0.0
    for index in range(frames):
        progress = index / max(1, frames - 1)
        seconds = index / _SAMPLE_RATE
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        noise = ((state >> 8) / 0xFFFFFF) * 2.0 - 1.0
        smooth += 0.11 * (noise - smooth)
        attack = min(1.0, seconds / 0.006)
        if kind == "impact":
            envelope = attack * (1.0 - progress) ** 4
            phase = 2.0 * math.pi * (82.0 * seconds - 22.0 * seconds * seconds)
            sample = envelope * (0.46 * math.sin(phase) + 0.10 * smooth)
        elif kind == "whoosh":
            envelope = math.sin(math.pi * progress) ** 1.6
            phase = 2.0 * math.pi * (170.0 * seconds + 680.0 * seconds * progress)
            sample = envelope * (0.18 * noise + 0.06 * math.sin(phase))
        else:
            envelope = attack * (1.0 - progress) ** 8
            phase = 2.0 * math.pi * (920.0 * seconds - 300.0 * seconds * seconds)
            sample = envelope * (0.34 * math.sin(phase) + 0.04 * smooth)
        value = round(max(-0.72, min(0.72, sample)) * 32767)
        struct.pack_into("<hh", pcm, index * 4, value, value)
    return bytes(pcm), duration_ms


def _cue_wave_bytes(kind: str) -> tuple[bytes, int]:
    pcm, duration_ms = _cue_pcm(kind)
    output = io.BytesIO()
    try:
        with wave.open(output, "wb") as cue:
            cue.setnchannels(_CHANNELS)
            cue.setsampwidth(2)
            cue.setframerate(_SAMPLE_RATE)
            cue.writeframes(pcm)
    except wave.Error as error:
        raise SfxProductionError(
            "project-owned SFX bytes could not be generated"
        ) from error
    return output.getvalue(), duration_ms


def _generate_asset(kind: str, work: Path) -> tuple[Path, dict, Path]:
    wav_bytes, duration_ms = _cue_wave_bytes(kind)
    asset_path = work / f"generated-{kind}.wav"
    _write_private(asset_path, wav_bytes, "project-owned SFX asset")
    asset_sha = _sha256_file(asset_path)
    evidence = {
        "schema_version": SFX_GENERATION_EVIDENCE_SCHEMA_VERSION,
        "generator": "autoeditor-deterministic-pcm/v1",
        "kind": kind,
        "parameters": {
            "sample_rate_hz": _SAMPLE_RATE, "channels": _CHANNELS,
            "sample_width_bytes": 2, "duration_ms": duration_ms,
        },
        "asset": {"sha256": asset_sha, "bytes": asset_path.stat().st_size},
        "rights": {
            "basis": "project_owned", "license_id": "project-generated",
            "licensor": "project", "external_service_used": False,
        },
    }
    evidence_path = _write_json(
        work / f"SFX_GENERATION_{kind.upper()}.json", evidence,
        f"{kind} SFX generation evidence",
    )
    evidence_sha = _sha256_file(evidence_path)
    payload = {
        "sha256": asset_sha,
        "byte_length": asset_path.stat().st_size,
        "duration_ms": duration_ms,
        "sample_rate_hz": _SAMPLE_RATE,
        "channels": _CHANNELS,
        "source_ref": f"project-generated://autoeditor-sfx-v1/{kind}.wav",
        "provenance": "project_generated",
        "license": {
            "basis": "project_owned", "license_id": "project-generated",
            "licensor": "project", "evidence_sha256": evidence_sha,
        },
    }
    return asset_path, {"asset_id": derive_sfx_asset_id(payload), **payload}, evidence_path


def _speech_intersections(start: int, end: int,
                          windows: Iterable[dict]) -> list[tuple[int, int]]:
    return [
        (max(start, item["start_ms"]), min(end, item["end_ms"]))
        for item in windows
        if item["end_ms"] > start and item["start_ms"] < end
    ]


def _cue_from_candidate(candidate: dict, asset: dict,
                        speech_windows: list[dict], duration_ms: int,
                        maximum_gain_millidb: int) -> dict | None:
    anchor = candidate["anchor"]
    kind = candidate["cue_kind"]
    asset_duration = asset["duration_ms"]
    start = anchor["time_ms"] if kind == "impact" else max(
        0, anchor["time_ms"] - 150)
    if start + asset_duration > duration_ms:
        return None
    gain = min(-3_000, maximum_gain_millidb)
    intersections = _speech_intersections(
        start, start + asset_duration, speech_windows)
    ducking = None
    if intersections:
        duck_start = intersections[0][0]
        duck_end = intersections[-1][1]
        span = duck_end - duck_start
        if span < 2:
            return None
        attack = min(20, max(1, span // 4))
        release = min(100, max(1, span - attack))
        if attack + release > span:
            release = span - attack
        ducking = {
            "start_ms": duck_start, "end_ms": duck_end,
            "attenuation_millidb": 12_000,
            "attack_ms": attack, "release_ms": release,
        }
    motivation = {
        "category": anchor["category"], "anchor_id": anchor["anchor_id"],
        "reference_id": anchor["reference_id"],
        "anchor_ms": anchor["time_ms"],
        "evidence_start_ms": anchor["evidence_start_ms"],
        "evidence_end_ms": anchor["evidence_end_ms"],
        "evidence_sha256": anchor["evidence_sha256"],
    }
    payload = {
        "asset_id": asset["asset_id"], "asset_sha256": asset["sha256"],
        "kind": kind, "motivation": motivation,
        "placement": {
            "start_ms": start, "trim_start_ms": 0,
            "trim_duration_ms": asset_duration,
            "gain_millidb": gain,
            "attack_fade_ms": 20,
            "release_fade_ms": min(120, asset_duration - 20),
        },
        "ducking": ducking,
    }
    return {"cue_id": derive_sfx_cue_id(payload), **payload}


def _select_candidates(candidates: list[dict], policy_limits: dict) -> list[dict]:
    usage = policy_limits["usage"]
    if usage in {"forbidden", "source_only"}:
        return []
    if usage == "interface_feedback_only":
        return []
    allowed = [item for item in candidates if item["anchor"]["category"] == "event"]
    spacing = {"none": 86_400_000, "sparse": 10_000,
               "medium": 4_000, "dense": 2_000}[policy_limits["density"]]
    selected = []
    for item in allowed:
        if len(selected) >= policy_limits["max_cue_count"]:
            break
        if selected and item["anchor"]["time_ms"] - selected[-1]["anchor"]["time_ms"] < spacing:
            continue
        selected.append(item)
    return selected


def _sidecar_binding(path: Path) -> dict[str, Any]:
    return {"file": path.name, "sha256": _sha256_file(path),
            "bytes": path.stat().st_size}


def _persist_sidecars(source_paths: list[Path], evidence_dir: Path) -> list[Path]:
    names = [path.name for path in source_paths]
    if len(names) != len(set(names)) or any(
            _SAFE_FILE_RE.fullmatch(name) is None for name in names):
        _fail("typed SFX sidecar inventory is unsafe")
    destinations = [evidence_dir / name for name in names]
    if any(path.exists() for path in destinations):
        _fail("typed SFX sidecar already exists")
    created: list[Path] = []
    try:
        for source, destination in zip(source_paths, destinations):
            _write_private(destination, source.read_bytes(), destination.name)
            created.append(destination)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return created


def validate_sfx_production_receipt(value: object) -> dict[str, Any]:
    raw = _exact_dict(value, _PRODUCTION_KEYS, "SFX production receipt")
    if raw["schema_version"] != SFX_PRODUCTION_RECEIPT_SCHEMA_VERSION:
        _fail("SFX production receipt schema is unsupported")
    mode = raw["mode"]
    if type(mode) is not str or mode not in _MODES:
        _fail("SFX production receipt mode is unsupported")
    authorization_id = raw["authorization_id"]
    if (type(authorization_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", authorization_id) is None):
        _fail("SFX production receipt authorization id is invalid")
    hashes = {
        key: _digest(raw[key], f"SFX production receipt.{key}")
        for key in (
            "engine_envelope_sha256", "project_intent_sha256",
            "parent_edit_policy_sha256", "execution_edit_policy_sha256",
            "output_timeline_sha256",
        )
    }
    nullable_hashes = {}
    for key in (
        "cue_manifest_sha256", "sfx_plan_sha256",
        "sfx_compile_receipt_sha256", "sfx_render_receipt_sha256",
    ):
        nullable_hashes[key] = None if raw[key] is None else _digest(
            raw[key], f"SFX production receipt.{key}")
    target = _exact_dict(raw["target_duration"], _TARGET_KEYS,
                         "SFX production receipt target duration")
    normalized_target = {
        "min_ms": _integer(target["min_ms"], "target min", 1),
        "max_ms": _integer(target["max_ms"], "target max", 1),
    }
    actual = _integer(raw["actual_duration_ms"], "actual duration", 1)
    if not normalized_target["min_ms"] <= actual <= normalized_target["max_ms"]:
        _fail("SFX production receipt duration is outside its target")
    band = raw["duration_band"]
    if type(band) is not str or duration_band(actual) != band:
        _fail("SFX production receipt duration band is invalid")
    preference = raw["requested_preference"]
    if type(preference) is not str:
        _fail("SFX production receipt preference is invalid")
    policy = _exact_dict(raw["policy"], _POLICY_KEYS,
                         "SFX production receipt policy")
    if type(policy["density"]) is not str or type(policy["usage"]) is not str:
        _fail("SFX production receipt policy is invalid")
    cue_count = _integer(raw["cue_count"], "SFX cue count")
    media = []
    for name in ("program_input", "output"):
        raw_media = _exact_dict(raw[name], _MEDIA_KEYS, f"SFX {name}")
        media.append({
            "sha256": _digest(raw_media["sha256"], f"SFX {name} sha256"),
            "bytes": _integer(raw_media["bytes"], f"SFX {name} bytes", 1),
            "duration_ms": _integer(raw_media["duration_ms"],
                                     f"SFX {name} duration", 1),
        })
    sidecars = raw["sidecars"]
    if type(sidecars) is not list:
        _fail("SFX production receipt sidecars are invalid")
    normalized_sidecars = []
    for index, raw_item in enumerate(sidecars):
        item = _exact_dict(raw_item, _SIDECAR_KEYS,
                           f"SFX sidecar {index}")
        if (type(item["file"]) is not str
                or _SAFE_FILE_RE.fullmatch(item["file"]) is None):
            _fail("SFX production receipt sidecar filename is invalid")
        normalized_sidecars.append({
            "file": item["file"],
            "sha256": _digest(item["sha256"], "SFX sidecar sha256"),
            "bytes": _integer(item["bytes"], "SFX sidecar bytes", 1),
        })
    if (normalized_sidecars != sorted(normalized_sidecars,
                                      key=lambda item: item["file"])
            or len({item["file"] for item in normalized_sidecars})
            != len(normalized_sidecars)):
        _fail("SFX production receipt sidecars must be sorted and unique")
    rendered = mode == "rendered"
    if rendered != (cue_count > 0):
        _fail("SFX production mode contradicts its cue count")
    if rendered != all(value is not None for value in nullable_hashes.values()):
        _fail("SFX production mode contradicts its receipt chain")
    if not rendered and (media[0] != media[1]
                         or hashes["output_timeline_sha256"] !=
                         derive_sfx_output_timeline_sha256(
                             program_sha256=media[0]["sha256"],
                             program_bytes=media[0]["bytes"],
                             duration_ms=actual,
                         )):
        _fail("no-op SFX production receipt changed program bytes")
    return copy.deepcopy({
        "schema_version": SFX_PRODUCTION_RECEIPT_SCHEMA_VERSION,
        "mode": mode, "authorization_id": authorization_id,
        **hashes, "target_duration": normalized_target,
        "actual_duration_ms": actual, "duration_band": band,
        "requested_preference": preference,
        "policy": {"density": policy["density"], "usage": policy["usage"]},
        "cue_count": cue_count, "program_input": media[0], "output": media[1],
        **nullable_hashes,
        "sidecars": normalized_sidecars,
    })


def canonical_sfx_production_receipt_json(value: object) -> str:
    return _canonical_json(
        validate_sfx_production_receipt(value), "SFX production receipt"
    )


def sfx_production_receipt_sha256(value: object) -> str:
    return hashlib.sha256(
        canonical_sfx_production_receipt_json(value).encode("ascii")
    ).hexdigest()


def _load_json_sidecar(path: Path, label: str) -> object:
    def closed_pairs(pairs: list[tuple[str, object]]) -> dict:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise SfxProductionError(f"{label} contains duplicate keys")
            value[key] = item
        return value

    try:
        return json.loads(
            path.read_text(encoding="ascii", errors="strict"),
            object_pairs_hook=closed_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                SfxProductionError(f"{label} contains a non-finite number")
            ),
        )
    except SfxProductionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SfxProductionError(f"{label} is not valid evidence JSON") from error


def _verify_generation_evidence(value: object, asset: dict) -> None:
    raw = _exact_dict(value, frozenset({
        "schema_version", "generator", "kind", "parameters", "asset", "rights",
    }), "SFX generation evidence")
    if (raw["schema_version"] != SFX_GENERATION_EVIDENCE_SCHEMA_VERSION
            or raw["generator"] != "autoeditor-deterministic-pcm/v1"):
        _fail("SFX generation evidence identifies an unsupported generator")
    if raw["kind"] not in {"impact", "whoosh", "interface_feedback"}:
        _fail("SFX generation evidence kind is unsupported")
    expected_wave, expected_duration_ms = _cue_wave_bytes(raw["kind"])
    if (asset["sha256"] != _sha256_bytes(expected_wave)
            or asset["byte_length"] != len(expected_wave)
            or asset["duration_ms"] != expected_duration_ms):
        _fail("SFX asset bytes do not match the trusted local generator")
    parameters = _exact_dict(raw["parameters"], frozenset({
        "sample_rate_hz", "channels", "sample_width_bytes", "duration_ms",
    }), "SFX generation parameters")
    if parameters != {
        "sample_rate_hz": asset["sample_rate_hz"],
        "channels": asset["channels"],
        "sample_width_bytes": 2,
        "duration_ms": asset["duration_ms"],
    }:
        _fail("SFX generation parameters do not match the trusted asset")
    generated_asset = _exact_dict(
        raw["asset"], frozenset({"sha256", "bytes"}),
        "SFX generated asset binding")
    if generated_asset != {
        "sha256": asset["sha256"], "bytes": asset["byte_length"],
    }:
        _fail("SFX generation evidence does not bind the trusted asset bytes")
    rights = _exact_dict(raw["rights"], frozenset({
        "basis", "license_id", "licensor", "external_service_used",
    }), "SFX generation rights")
    if rights != {
        "basis": "project_owned", "license_id": "project-generated",
        "licensor": "project", "external_service_used": False,
    }:
        _fail("SFX generation evidence does not prove local project ownership")


def verify_sfx_production_evidence(
    receipt: object,
    *,
    output_path: str,
    evidence_dir: str,
    expected_engine_envelope_sha256: str,
    expected_project_intent_sha256: str,
    expected_parent_edit_policy_sha256: str,
) -> dict[str, Any]:
    """Independently re-open the SFX evidence chain for final QA.

    This verifier does not trust the in-memory producer result.  It re-hashes
    every persisted sidecar and final output, revalidates the specialized
    policy/manifest/plan, recompiles the plan, reconstructs EDL/boundary/speech
    anchors, and validates locally generated ownership evidence.
    """
    mode = None
    cue_count = 0
    policy_usage = "unverified"
    try:
        normalized = validate_sfx_production_receipt(receipt)
        mode = normalized["mode"]
        cue_count = normalized["cue_count"]
        policy_usage = normalized["policy"]["usage"]
        if (normalized["engine_envelope_sha256"] != _digest(
                expected_engine_envelope_sha256, "expected envelope digest")
                or normalized["project_intent_sha256"] != _digest(
                    expected_project_intent_sha256,
                    "expected project intent digest")
                or normalized["parent_edit_policy_sha256"] != _digest(
                    expected_parent_edit_policy_sha256,
                    "expected parent policy digest")):
            _fail("SFX production receipt is bound to different authority")
        output = _absolute_file(output_path, "SFX QA output")
        if (output.stat().st_size != normalized["output"]["bytes"]
                or _sha256_file(output) != normalized["output"]["sha256"]):
            _fail("SFX QA output bytes do not match the production receipt")
        root = _absolute_dir(evidence_dir, "SFX QA evidence directory")
        sidecars: dict[str, tuple[Path, object]] = {}
        for binding in normalized["sidecars"]:
            path = root / binding["file"]
            if (not path.is_file() or path.stat().st_size != binding["bytes"]
                    or _sha256_file(path) != binding["sha256"]):
                _fail(f"SFX QA sidecar {binding['file']} is missing or changed")
            sidecars[path.name] = (
                path, _load_json_sidecar(path, f"SFX sidecar {path.name}")
            )
        policy_item = sidecars.get("SFX_EXECUTION_EDIT_POLICY.json")
        if policy_item is None:
            _fail("SFX execution edit policy sidecar is missing")
        execution_policy = validate_edit_policy(policy_item[1])
        if (edit_policy_sha256(execution_policy)
                != normalized["execution_edit_policy_sha256"]
                or execution_policy["duration"]["duration_ms"]
                != normalized["actual_duration_ms"]
                or execution_policy["duration"]["band"]
                != normalized["duration_band"]
                or execution_policy["rules"]["sfx"] != normalized["policy"]):
            _fail("SFX execution policy sidecar contradicts production authority")
        if mode != "rendered":
            if set(sidecars) != {"SFX_EXECUTION_EDIT_POLICY.json"}:
                _fail("no-op SFX production persisted unexpected evidence")
            return {
                "ok": True, "mode": mode, "cue_count": 0,
                "policy_usage": policy_usage, "policy_bound": True,
                "receipt_sha256": sfx_production_receipt_sha256(normalized),
                "output_sha256": normalized["output"]["sha256"], "note": "",
            }

        required = {
            "SFX_CUE_MANIFEST.json", "SFX_PLAN.json",
            "SFX_COMPILE_RECEIPT.json", "SFX_RENDER_RECEIPT.json",
            "SFX_EDL_ANCHOR_EVIDENCE.json",
            "SFX_BOUNDARY_ANCHOR_EVIDENCE.json", "SFX_SPEECH_EVIDENCE.json",
        }
        if not required <= set(sidecars):
            _fail("rendered SFX production evidence is incomplete")
        manifest = validate_sfx_cue_manifest(
            sidecars["SFX_CUE_MANIFEST.json"][1])
        plan = validate_sfx_plan(
            sidecars["SFX_PLAN.json"][1], manifest, execution_policy)
        compiled = compile_sfx_plan(plan, manifest, execution_policy)
        persisted_compile = sidecars["SFX_COMPILE_RECEIPT.json"][1]
        if (manifest["output_timeline_sha256"]
                != normalized["output_timeline_sha256"]
                or sfx_cue_manifest_sha256(manifest)
                != normalized["cue_manifest_sha256"]
                or sfx_plan_sha256(plan) != normalized["sfx_plan_sha256"]
                or compiled["receipt"] != persisted_compile
                or sfx_compile_receipt_sha256(persisted_compile)
                != normalized["sfx_compile_receipt_sha256"]):
            _fail("SFX manifest, plan, or compile receipt chain changed")
        persisted_render = sidecars["SFX_RENDER_RECEIPT.json"][1]
        # Canonicalization is the render contract's public closed validator.
        render_receipt = json.loads(
            canonical_sfx_render_receipt_json(persisted_render)
        )
        if (sfx_render_receipt_sha256(render_receipt)
                != normalized["sfx_render_receipt_sha256"]
                or render_receipt["sfx_compile_receipt_sha256"]
                != normalized["sfx_compile_receipt_sha256"]
                or render_receipt["sfx_plan_sha256"]
                != normalized["sfx_plan_sha256"]
                or render_receipt["cue_manifest_sha256"]
                != normalized["cue_manifest_sha256"]
                or render_receipt["edit_policy_sha256"]
                != normalized["execution_edit_policy_sha256"]
                or render_receipt["output_timeline_sha256"]
                != normalized["output_timeline_sha256"]
                or render_receipt["ordered_cue_ids"]
                != compiled["receipt"]["ordered_cue_ids"]
                or render_receipt["ordered_asset_ids"]
                != compiled["receipt"]["ordered_asset_ids"]
                or render_receipt["program_input"]["sha256"]
                != normalized["program_input"]["sha256"]
                or render_receipt["program_input"]["bytes"]
                != normalized["program_input"]["bytes"]
                or render_receipt["program_input"]["duration_ms"]
                != normalized["program_input"]["duration_ms"]
                or render_receipt["output"]["sha256"]
                != normalized["output"]["sha256"]
                or render_receipt["output"]["bytes"]
                != normalized["output"]["bytes"]
                or render_receipt["output"]["duration_ms"]
                != normalized["output"]["duration_ms"]
                or render_receipt["output"]["sample_rate_hz"] != _SAMPLE_RATE
                or render_receipt["output"]["channels"] != _CHANNELS
                or render_receipt["cue_count"] != cue_count):
            _fail("SFX render receipt does not bind the final output")

        expected_asset_inputs = sorted(({
            "asset_id": asset["asset_id"],
            "sha256": asset["sha256"],
            "bytes": asset["byte_length"],
            "duration_ms": asset["duration_ms"],
            "sample_rate_hz": asset["sample_rate_hz"],
            "channels": asset["channels"],
        } for asset in manifest["assets"]), key=lambda item: item["asset_id"])
        if render_receipt["asset_inputs"] != expected_asset_inputs:
            _fail("SFX renderer decoded a different asset inventory")

        evidence_hashes = set()
        assets_by_id = {
            asset["asset_id"]: asset for asset in manifest["assets"]
        }
        for cue in plan["cues"]:
            evidence_hashes.add(cue["motivation"]["evidence_sha256"])
            evidence_hashes.add(
                assets_by_id[cue["asset_id"]]["license"]["evidence_sha256"]
            )
            if cue["ducking"] is not None:
                cue_start = cue["placement"]["start_ms"]
                cue_end = cue_start + cue["placement"]["trim_duration_ms"]
                evidence_hashes.update(
                    window["evidence_sha256"]
                    for window in manifest["speech_windows"]
                    if window["end_ms"] > cue_start
                    and window["start_ms"] < cue_end
                )
        binding_by_hash = {
            binding["sha256"]: binding for binding in normalized["sidecars"]
        }
        if not evidence_hashes <= set(binding_by_hash):
            _fail("SFX renderer evidence preimages are not persisted")
        expected_evidence_inputs = sorted(({
            "sha256": digest,
            "bytes": binding_by_hash[digest]["bytes"],
        } for digest in evidence_hashes), key=lambda item: item["sha256"])
        if render_receipt["evidence_inputs"] != expected_evidence_inputs:
            _fail("SFX renderer consumed a different evidence inventory")

        edl_path, edl_raw = sidecars["SFX_EDL_ANCHOR_EVIDENCE.json"]
        edl_evidence = _exact_dict(edl_raw, frozenset({
            "schema_version", "kind", "edl_sha256", "protocol_version",
            "public_edl", "rendered_graphics", "rendered_broll",
        }), "SFX EDL evidence")
        if (edl_evidence["schema_version"] != SFX_ANCHOR_EVIDENCE_SCHEMA_VERSION
                or edl_evidence["kind"] != "validated_edl"
                or edl_evidence["protocol_version"]
                != creative_contract.PROTOCOL_VERSION
                or creative_contract.edl_sha256(edl_evidence["public_edl"])
                != edl_evidence["edl_sha256"]):
            _fail("SFX EDL evidence is invalid")
        event_candidates = _candidate_events(
            edl_evidence["public_edl"],
            rendered_graphics=[{
                "s": item["start_ms"] / 1000,
                "e": item["end_ms"] / 1000,
            } for item in edl_evidence["rendered_graphics"]],
            rendered_broll=[{
                "s": item["start_ms"] / 1000,
                "e": item["end_ms"] / 1000,
            } for item in edl_evidence["rendered_broll"]],
            duration_ms=normalized["actual_duration_ms"],
            evidence_sha256=_sha256_file(edl_path),
        )
        boundary_path, boundary_raw = sidecars[
            "SFX_BOUNDARY_ANCHOR_EVIDENCE.json"]
        boundary_evidence = _exact_dict(boundary_raw, frozenset({
            "schema_version", "kind", "receipt",
        }), "SFX boundary evidence")
        if (boundary_evidence["schema_version"]
                != SFX_ANCHOR_EVIDENCE_SCHEMA_VERSION
                or boundary_evidence["kind"] != "edit_boundaries"):
            _fail("SFX boundary evidence is invalid")
        boundary_anchors = _boundary_anchors(
            boundary_evidence["receipt"],
            duration_ms=normalized["actual_duration_ms"],
            evidence_sha256=_sha256_file(boundary_path),
        )
        expected_anchors = sorted(
            [item["anchor"] for item in event_candidates] + boundary_anchors,
            key=lambda item: (item["time_ms"], item["anchor_id"]),
        )
        if manifest["anchors"] != expected_anchors:
            _fail("SFX manifest anchors do not match exact renderer evidence")

        _speech_path, speech_raw = sidecars["SFX_SPEECH_EVIDENCE.json"]
        speech_evidence = _exact_dict(speech_raw, frozenset({
            "schema_version", "duration_ms", "words",
        }), "SFX speech evidence")
        reconstructed_evidence, reconstructed_windows = _speech_evidence(
            [{
                "w": item["text"], "s": item["start_ms"] / 1000,
                "e": item["end_ms"] / 1000,
            } for item in speech_evidence["words"]],
            normalized["actual_duration_ms"],
        )
        if (speech_evidence != reconstructed_evidence
                or manifest["speech_windows"] != reconstructed_windows):
            _fail("SFX speech windows do not match exact word evidence")

        generation_by_hash = {
            binding["sha256"]: sidecars[binding["file"]][1]
            for binding in normalized["sidecars"]
            if binding["file"].startswith("SFX_GENERATION_")
        }
        for asset in manifest["assets"]:
            license_evidence = asset["license"]["evidence_sha256"]
            generation = generation_by_hash.get(license_evidence)
            if generation is None:
                _fail("SFX project-owned asset generation evidence is missing")
            _verify_generation_evidence(generation, asset)
        return {
            "ok": True, "mode": mode, "cue_count": cue_count,
            "policy_usage": policy_usage, "policy_bound": True,
            "receipt_sha256": sfx_production_receipt_sha256(normalized),
            "output_sha256": normalized["output"]["sha256"], "note": "",
        }
    except Exception as error:
        return {
            "ok": False, "mode": mode, "cue_count": cue_count,
            "policy_usage": policy_usage, "policy_bound": False,
            "receipt_sha256": None, "output_sha256": None,
            "note": f"typed SFX evidence failed: {type(error).__name__}: {error}",
        }


def execute_project_intent_sfx(
    *,
    program_path: str,
    project_intent_envelope: object,
    project_intent_envelope_sha256: str,
    edl: object,
    rendered_graphics: object,
    rendered_broll: object,
    edit_boundaries_receipt: object,
    speech_words: object,
    work_dir: str,
    evidence_dir: str,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> dict[str, Any]:
    """Build and execute the exact typed SFX program, or prove a no-op.

    The returned output never overwrites ``program_path``.  The caller may
    replace its private master only after this function succeeds and after it
    verifies the returned hash against the persisted production receipt.
    """
    program = _absolute_file(program_path, "typed SFX program")
    ffmpeg = _absolute_file(ffmpeg_path, "typed SFX FFmpeg")
    ffprobe = _absolute_file(ffprobe_path, "typed SFX FFprobe")
    parent_work = _absolute_dir(work_dir, "typed SFX work directory")
    evidence_root = _absolute_dir(evidence_dir, "typed SFX evidence directory")
    try:
        envelope = validate_project_intent_engine_envelope(
            project_intent_envelope)
    except Exception as error:
        raise SfxProductionError("ProjectIntent engine envelope is invalid") from error
    expected_envelope_hash = _digest(
        project_intent_envelope_sha256, "ProjectIntent engine envelope digest")
    measured_envelope_hash = project_intent_engine_envelope_sha256(envelope)
    if (measured_envelope_hash != expected_envelope_hash
            or hashlib.sha256(
                canonical_project_intent_engine_envelope_bytes(envelope)
            ).hexdigest() != expected_envelope_hash):
        _fail("ProjectIntent engine envelope digest does not match")

    private = parent_work / "typed-sfx-production"
    try:
        private.mkdir(mode=0o700)
    except FileExistsError as error:
        raise SfxProductionError("private typed SFX directory already exists") from error
    except OSError as error:
        raise SfxProductionError("private typed SFX directory is unavailable") from error

    program_binding = _probe_program(program, ffprobe, private)
    target = copy.deepcopy(envelope["project_intent"]["target_duration"])
    execution_policy = specialize_edit_policy_for_program(
        envelope["edit_policy"], target_duration=target,
        actual_duration_ms=program_binding["duration_ms"],
    )
    parent_policy_hash = edit_policy_sha256(envelope["edit_policy"])
    execution_policy_hash = edit_policy_sha256(execution_policy)
    if parent_policy_hash != envelope["edit_policy_sha256"]:
        _fail("ProjectIntent parent edit policy digest changed")
    preference = envelope["project_intent"]["preferences"]["sfx"]["preference"]
    rule = execution_policy["rules"]["sfx"]
    if preference == "none":
        if rule["density"] != "none":
            _fail("disabled typed SFX preference resolved to a nonzero density")
    elif preference not in {"auto", rule["usage"]}:
        _fail("requested typed SFX usage is unsupported by the resolved profile")
    elif rule["density"] == "none" or rule["usage"] in {"forbidden", "source_only"}:
        _fail("requested typed SFX usage is forbidden by the resolved policy")

    timeline_hash = derive_sfx_output_timeline_sha256(
        program_sha256=program_binding["sha256"],
        program_bytes=program_binding["bytes"],
        duration_ms=program_binding["duration_ms"],
    )
    execution_policy_path = _write_json(
        private / "SFX_EXECUTION_EDIT_POLICY.json", execution_policy,
        "SFX execution edit policy",
    )

    def persist_noop(mode: str) -> dict[str, Any]:
        persisted = _persist_sidecars([execution_policy_path], evidence_root)
        receipt = validate_sfx_production_receipt({
            "schema_version": SFX_PRODUCTION_RECEIPT_SCHEMA_VERSION,
            "mode": mode,
            "authorization_id": envelope["authorization_id"],
            "engine_envelope_sha256": expected_envelope_hash,
            "project_intent_sha256": envelope["project_intent_sha256"],
            "parent_edit_policy_sha256": parent_policy_hash,
            "execution_edit_policy_sha256": execution_policy_hash,
            "target_duration": target,
            "actual_duration_ms": program_binding["duration_ms"],
            "duration_band": execution_policy["duration"]["band"],
            "requested_preference": preference,
            "policy": {"density": rule["density"], "usage": rule["usage"]},
            "cue_count": 0,
            "output_timeline_sha256": timeline_hash,
            "program_input": program_binding,
            "output": program_binding,
            "cue_manifest_sha256": None,
            "sfx_plan_sha256": None,
            "sfx_compile_receipt_sha256": None,
            "sfx_render_receipt_sha256": None,
            "sidecars": sorted(
                (_sidecar_binding(path) for path in persisted),
                key=lambda item: item["file"],
            ),
        })
        receipt_path = _write_json(
            evidence_root / "SFX_PRODUCTION_RECEIPT.json", receipt,
            "SFX production receipt",
        )
        return {
            "executed": False,
            "output_path": str(program),
            "receipt": receipt,
            "receipt_path": str(receipt_path),
            "receipt_sha256": sfx_production_receipt_sha256(receipt),
            "sidecar_paths": [str(path) for path in persisted],
        }

    if preference == "none":
        return persist_noop("no_sfx_requested")

    public_edl, edl_evidence = _edl_evidence(
        edl, rendered_graphics=rendered_graphics,
        rendered_broll=rendered_broll,
        duration_ms=program_binding["duration_ms"],
    )
    edl_evidence_path = _write_json(
        private / "SFX_EDL_ANCHOR_EVIDENCE.json", edl_evidence,
        "SFX EDL anchor evidence",
    )
    edl_evidence_sha = _sha256_file(edl_evidence_path)
    boundary_evidence = {
        "schema_version": SFX_ANCHOR_EVIDENCE_SCHEMA_VERSION,
        "kind": "edit_boundaries",
        "receipt": edit_boundaries_receipt,
    }
    boundary_evidence_path = _write_json(
        private / "SFX_BOUNDARY_ANCHOR_EVIDENCE.json", boundary_evidence,
        "SFX boundary anchor evidence",
    )
    boundary_evidence_sha = _sha256_file(boundary_evidence_path)
    candidates = _candidate_events(
        public_edl, rendered_graphics=rendered_graphics,
        rendered_broll=rendered_broll,
        duration_ms=program_binding["duration_ms"],
        evidence_sha256=edl_evidence_sha,
    )
    boundary_anchors = _boundary_anchors(
        edit_boundaries_receipt, duration_ms=program_binding["duration_ms"],
        evidence_sha256=boundary_evidence_sha,
    )
    speech_evidence, speech_windows = _speech_evidence(
        speech_words, program_binding["duration_ms"])
    speech_evidence_path = _write_json(
        private / "SFX_SPEECH_EVIDENCE.json", speech_evidence,
        "SFX speech evidence",
    )
    speech_digest = _sha256_file(speech_evidence_path)
    if any(item["evidence_sha256"] != speech_digest for item in speech_windows):
        _fail("typed SFX speech evidence digest changed")

    limits = derive_sfx_policy_limits(
        execution_policy, program_binding["duration_ms"])
    selected = _select_candidates(candidates, limits)
    if not selected:
        if preference != "auto":
            _fail("requested typed SFX usage has no verified motivated anchor")
        return persist_noop("no_motivated_anchor")

    asset_paths: dict[str, str] = {}
    evidence_paths: dict[str, str] = {
        edl_evidence_sha: str(edl_evidence_path),
        boundary_evidence_sha: str(boundary_evidence_path),
        speech_digest: str(speech_evidence_path),
    }
    generation_paths: list[Path] = []
    assets_by_kind: dict[str, dict] = {}
    for kind in sorted({item["cue_kind"] for item in selected}):
        asset_path, asset, generation_path = _generate_asset(kind, private)
        assets_by_kind[kind] = asset
        asset_paths[asset["asset_id"]] = str(asset_path)
        evidence_paths[asset["license"]["evidence_sha256"]] = str(generation_path)
        generation_paths.append(generation_path)

    cues = []
    for candidate in selected:
        cue = _cue_from_candidate(
            candidate, assets_by_kind[candidate["cue_kind"]], speech_windows,
            program_binding["duration_ms"], limits["max_gain_millidb"],
        )
        if cue is not None:
            cues.append(cue)
    cues.sort(key=lambda item: (item["placement"]["start_ms"], item["cue_id"]))
    if not cues:
        if preference != "auto":
            _fail("requested typed SFX cues cannot fit the exact timeline")
        return persist_noop("no_motivated_anchor")
    used_assets = sorted(
        {cue["asset_id"] for cue in cues}
    )
    assets = sorted(
        (asset for asset in assets_by_kind.values()
         if asset["asset_id"] in used_assets),
        key=lambda item: item["asset_id"],
    )
    anchors = sorted(
        [item["anchor"] for item in candidates] + boundary_anchors,
        key=lambda item: (item["time_ms"], item["anchor_id"]),
    )
    manifest = {
        "schema_version": SFX_CUE_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": timeline_hash,
        "output_duration_ms": program_binding["duration_ms"],
        "output_sample_rate_hz": _SAMPLE_RATE,
        "output_channels": _CHANNELS,
        "assets": assets,
        "anchors": anchors,
        "speech_windows": speech_windows,
    }
    manifest_hash = sfx_cue_manifest_sha256(manifest)
    plan = {
        "schema_version": SFX_PLAN_SCHEMA_VERSION,
        "cue_manifest_sha256": manifest_hash,
        "edit_policy_sha256": execution_policy_hash,
        "output_timeline_sha256": timeline_hash,
        "output_duration_ms": program_binding["duration_ms"],
        "policy": limits,
        "cues": cues,
    }
    plan_hash = sfx_plan_sha256(plan)
    compiled = compile_sfx_plan(plan, manifest, execution_policy)
    manifest_path = _write_json(
        private / "SFX_CUE_MANIFEST.json", manifest, "SFX cue manifest")
    plan_path = _write_json(private / "SFX_PLAN.json", plan, "SFX plan")
    compile_path = _write_json(
        private / "SFX_COMPILE_RECEIPT.json", compiled["receipt"],
        "SFX compile receipt",
    )
    result = execute_sfx_render(
        program_path=str(program),
        output_path=str(private / "strict-sfx-output.mp4"),
        plan=plan, cue_manifest=manifest, edit_policy=execution_policy,
        asset_paths={key: value for key, value in asset_paths.items()
                     if key in used_assets},
        evidence_paths={
            digest: path for digest, path in evidence_paths.items()
            if digest in {
                *(cue["motivation"]["evidence_sha256"] for cue in cues),
                *(asset["license"]["evidence_sha256"] for asset in assets),
                *(speech["evidence_sha256"] for speech in speech_windows
                  if any(
                      speech["end_ms"] > cue["placement"]["start_ms"]
                      and speech["start_ms"] < cue["placement"]["start_ms"]
                          + cue["placement"]["trim_duration_ms"]
                      and cue["ducking"] is not None
                      for cue in cues
                  )),
            }
        },
        work_dir=str(private), ffmpeg_path=str(ffmpeg),
        ffprobe_path=str(ffprobe),
    )
    if (result["compile_receipt"] != compiled["receipt"]
            or result["compile_receipt_sha256"]
            != sfx_compile_receipt_sha256(compiled["receipt"])):
        _fail("SFX executor recompiled a different cue program")
    render_path = _write_json(
        private / "SFX_RENDER_RECEIPT.json", result["receipt"],
        "SFX render receipt",
    )
    source_sidecars = [
        execution_policy_path, manifest_path, plan_path, compile_path,
        render_path, edl_evidence_path, boundary_evidence_path,
        speech_evidence_path, *generation_paths,
    ]
    persisted = _persist_sidecars(source_sidecars, evidence_root)
    output_binding = {
        "sha256": result["receipt"]["output"]["sha256"],
        "bytes": result["receipt"]["output"]["bytes"],
        "duration_ms": result["receipt"]["output"]["duration_ms"],
    }
    receipt = validate_sfx_production_receipt({
        "schema_version": SFX_PRODUCTION_RECEIPT_SCHEMA_VERSION,
        "mode": "rendered",
        "authorization_id": envelope["authorization_id"],
        "engine_envelope_sha256": expected_envelope_hash,
        "project_intent_sha256": envelope["project_intent_sha256"],
        "parent_edit_policy_sha256": parent_policy_hash,
        "execution_edit_policy_sha256": execution_policy_hash,
        "target_duration": target,
        "actual_duration_ms": program_binding["duration_ms"],
        "duration_band": execution_policy["duration"]["band"],
        "requested_preference": preference,
        "policy": {"density": rule["density"], "usage": rule["usage"]},
        "cue_count": len(cues),
        "output_timeline_sha256": timeline_hash,
        "program_input": program_binding,
        "output": output_binding,
        "cue_manifest_sha256": manifest_hash,
        "sfx_plan_sha256": plan_hash,
        "sfx_compile_receipt_sha256": result["compile_receipt_sha256"],
        "sfx_render_receipt_sha256": result["receipt_sha256"],
        "sidecars": sorted(
            (_sidecar_binding(path) for path in persisted),
            key=lambda item: item["file"],
        ),
    })
    receipt_path = _write_json(
        evidence_root / "SFX_PRODUCTION_RECEIPT.json", receipt,
        "SFX production receipt",
    )
    if (sfx_render_receipt_sha256(result["receipt"])
            != receipt["sfx_render_receipt_sha256"]):
        _fail("persisted SFX render receipt digest changed")
    return {
        "executed": True,
        "output_path": result["output_path"],
        "receipt": receipt,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sfx_production_receipt_sha256(receipt),
        "sidecar_paths": [str(path) for path in persisted],
        "render_receipt": result["receipt"],
        "compile_receipt": result["compile_receipt"],
        "manifest": manifest,
        "plan": plan,
    }


def _copy_file_exclusive(source: Path, destination: Path, label: str) -> None:
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise SfxProductionError(f"{label} could not be persisted")


def _run_audio_decode(
    ffmpeg: Path,
    media: Path,
    *,
    start_ms: int,
    duration_ms: int,
    cwd: Path,
) -> bytes:
    command = [
        str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(media), "-ss", f"{start_ms / 1000:.3f}",
        "-t", f"{duration_ms / 1000:.3f}", "-map", "0:a:0", "-vn",
        "-ac", "2", "-ar", str(_SAMPLE_RATE), "-c:a", "pcm_s16le",
        "-f", "s16le", "-",
    ]
    try:
        result = subprocess.run(
            command, cwd=str(cwd), shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SfxProductionError("decoded SFX placement check could not complete") from error
    if result.returncode != 0 or not result.stdout or len(result.stdout) > 2_000_000:
        detail = result.stderr.decode("utf-8", errors="replace")[
            -_MAX_CAPTURE_CHARS:
        ].strip()
        raise SfxProductionError(
            "decoded SFX placement check failed"
            + (f": {detail}" if detail else "")
        )
    return result.stdout


def _delta_rms_millionths(left: bytes, right: bytes) -> int:
    usable = min(len(left), len(right))
    usable -= usable % 2
    if usable < 2_000:
        _fail("decoded SFX placement window is too short")
    left_samples = struct.iter_unpack("<h", left[:usable])
    right_samples = struct.iter_unpack("<h", right[:usable])
    squares = 0
    count = 0
    for (left_value,), (right_value,) in zip(left_samples, right_samples):
        difference = right_value - left_value
        squares += difference * difference
        count += 1
    if count < 1:
        _fail("decoded SFX placement window has no samples")
    return round(math.sqrt(squares / count) / 32768 * 1_000_000)


def _decoded_placement_evidence(
    *,
    source: Path,
    output: Path,
    ffmpeg: Path,
    plan: dict,
    duration_ms: int,
    cwd: Path,
) -> dict[str, int]:
    cues = plan.get("cues")
    if type(cues) is not list or len(cues) != 1:
        _fail("fixed SFX probe did not produce exactly one cue")
    placement = cues[0].get("placement")
    if type(placement) is not dict:
        _fail("fixed SFX probe cue placement is absent")
    start_ms = placement.get("start_ms")
    trim_duration_ms = placement.get("trim_duration_ms")
    if start_ms != 460 or trim_duration_ms != 800:
        _fail("fixed SFX probe cue placement drifted")
    end_ms = start_ms + trim_duration_ms
    cue_start = start_ms + 100
    cue_duration = 500
    control_start = end_ms + 300
    control_duration = 500
    if control_start + control_duration > duration_ms:
        _fail("fixed SFX probe lacks a decoded control window")

    source_cue = _run_audio_decode(
        ffmpeg, source, start_ms=cue_start, duration_ms=cue_duration, cwd=cwd)
    output_cue = _run_audio_decode(
        ffmpeg, output, start_ms=cue_start, duration_ms=cue_duration, cwd=cwd)
    source_control = _run_audio_decode(
        ffmpeg, source, start_ms=control_start,
        duration_ms=control_duration, cwd=cwd,
    )
    output_control = _run_audio_decode(
        ffmpeg, output, start_ms=control_start,
        duration_ms=control_duration, cwd=cwd,
    )
    cue_delta = _delta_rms_millionths(source_cue, output_cue)
    control_delta = _delta_rms_millionths(source_control, output_control)
    if cue_delta < max(500, control_delta * 8 + 100):
        _fail(
            "decoded output did not prove the fixed SFX cue placement "
            f"(cue={cue_delta}, control={control_delta})"
        )
    return {
        "expected_start_ms": start_ms,
        "expected_end_ms": end_ms,
        "cue_window_start_ms": cue_start,
        "cue_window_duration_ms": cue_duration,
        "control_window_start_ms": control_start,
        "control_window_duration_ms": control_duration,
        "cue_delta_rms_millionths": cue_delta,
        "control_delta_rms_millionths": control_delta,
    }


def _fixed_sfx_probe_authority() -> tuple[dict[str, Any], list[dict[str, Any]], dict]:
    preferences = {
        "captions": "none",
        "graphics": "auto",
        "music": "none",
        "sfx": "motivated_only",
        "transitions": "none",
    }
    project = {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": "dialogue_talking_head",
        "delivery": {"platform": "youtube", "aspect": "16:9"},
        "target_duration": {"min_ms": 2_800, "max_ms": 3_200},
        "preferences": {
            name: {"enabled": value != "none", "preference": value}
            for name, value in preferences.items()
        },
    }
    manifest = {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": _sha256_bytes(
            b"autoeditor-fixed-project-generated-sfx-probe/v1"
        ),
        # This is a fixed self-test precondition, not a runtime availability
        # claim. The live capability manifest is derived only after this probe
        # passes and is never accepted from this internal authority object.
        "available_capabilities": sorted(CAPABILITIES),
    }
    policy = resolve_project_intent_policy(project, manifest)
    project_hash = _sha256_bytes(
        _canonical_json(project, "fixed SFX project intent").encode("ascii")
    )
    manifest_hash = _sha256_bytes(
        _canonical_json(manifest, "fixed SFX capability manifest").encode("ascii")
    )
    proposal = {
        "schema_version": "autoeditor-fixed-sfx-probe-proposal/v1",
        "project_intent_sha256": project_hash,
    }
    authority = {
        "schema_version": "autoeditor-project-intent-authority/v2",
        "authorization_id": _sha256_bytes(
            b"autoeditor-fixed-project-generated-sfx-authorization/v1"
        )[:32],
        "approved_proposal_sha256": _sha256_bytes(
            _canonical_json(proposal, "fixed SFX proposal").encode("ascii")
        ),
        "project_intent": project,
        "project_intent_sha256": project_hash,
        "edit_policy": policy,
        "edit_policy_sha256": edit_policy_sha256(policy),
        "capability_manifest": manifest,
        "capability_manifest_sha256": manifest_hash,
        "authorization_hmac_sha256": _sha256_bytes(
            b"fixed-local-self-test-hmac-not-a-live-authorization"
        ),
    }
    envelope = build_project_intent_engine_envelope(authority)

    words = [
        {
            "w": word,
            "s": round(0.15 + index * 0.28, 3),
            "e": round(0.35 + index * 0.28, 3),
        }
        for index, word in enumerate(
            "make every exact sound cue land clearly now".split()
        )
    ]
    raw_edl = {
        "protocol_version": creative_contract.PROTOCOL_VERSION,
        "timeline_space": creative_contract.TIMELINE_SPACE,
        "punch_ins": [{
            "s": 0.15, "e": 0.95, "scale": 1.1,
            "anchor_quote": "make every exact sound cue",
            "reason": "fixed opening emphasis",
        }],
        "broll": [],
        "graphics": [{
            "s": 0.71, "e": 2.01, "kind": "keyword",
            "text": "SOUND CUE",
            "anchor_quote": "exact sound cue land clearly",
            "reason": "fixed cue placement anchor",
        }],
    }
    try:
        edl, report = creative_contract.validate_edl(
            raw_edl, words, [], 3.0, "long"
        )
    except Exception as error:
        raise SfxProductionError("fixed SFX EDL failed validation") from error
    if report.get("score") != 100 or report.get("errors") != []:
        _fail("fixed SFX EDL did not pass its complete creative contract")
    edl["production_receipt"] = {
        "source": "deepseek",
        "protocol_version": creative_contract.PROTOCOL_VERSION,
        "contract_sha256": creative_contract.contract_sha256(),
        "validated_plan_sha256": creative_contract.edl_sha256(edl),
    }
    return envelope, words, edl


def write_sfx_production_probe(
    source_path: str,
    output_path: str,
    work_dir: str,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> dict[str, Any]:
    """Execute and independently verify the fixed project-generated SFX path.

    This entry point exists only for the trusted local runtime-capability
    producer. It does not accept a model plan or capability list. The source
    must be its fixed three-second audio/video fixture, and the requested
    output must be a new direct child of ``work_dir``.
    """
    source = _absolute_file(source_path, "fixed SFX probe source")
    root = _absolute_dir(work_dir, "fixed SFX probe work directory")
    ffmpeg = _absolute_file(ffmpeg_path, "fixed SFX probe FFmpeg")
    ffprobe = _absolute_file(ffprobe_path, "fixed SFX probe FFprobe")
    if type(output_path) is not str or not output_path or "\x00" in output_path:
        _fail("fixed SFX probe output path is invalid")
    output = Path(os.path.realpath(Path(output_path)))
    if (not output.is_absolute() or output.suffix.lower() != ".mp4"
            or Path(os.path.realpath(output.parent)) != root
            or output.exists() or output == source):
        _fail("fixed SFX probe output must be a new MP4 inside its work directory")

    private = root / "SFX_PRODUCTION_SELF_TEST"
    try:
        private.mkdir(mode=0o700)
        producer_work = private / "work"
        evidence_root = private / "evidence"
        producer_work.mkdir(mode=0o700)
        evidence_root.mkdir(mode=0o700)
    except (OSError, FileExistsError) as error:
        raise SfxProductionError(
            "fixed SFX probe private directory is unavailable"
        ) from error

    envelope, _grounding_words, edl = _fixed_sfx_probe_authority()
    envelope_hash = project_intent_engine_envelope_sha256(envelope)
    rendered_graphics = [
        {"s": item["s"], "e": item["e"]}
        for item in creative_contract.public_edl(edl)["graphics"]
    ]
    result = execute_project_intent_sfx(
        program_path=str(source),
        project_intent_envelope=envelope,
        project_intent_envelope_sha256=envelope_hash,
        edl=edl,
        rendered_graphics=rendered_graphics,
        rendered_broll=[],
        edit_boundaries_receipt={
            "schema": "autoeditor-edit-boundaries/v1",
            "timeline": "post_cut_seconds",
            "cuts": [], "transitions": [],
            "transition_support": "not_implemented",
        },
        # The fixed media fixture is intentionally silent. The grounding
        # words validate the EDL above; no decoded dialogue exists to duck.
        speech_words=[],
        work_dir=str(producer_work),
        evidence_dir=str(evidence_root),
        ffmpeg_path=str(ffmpeg),
        ffprobe_path=str(ffprobe),
    )
    if not result.get("executed"):
        _fail("fixed SFX probe did not execute the production renderer")
    _copy_file_exclusive(
        _absolute_file(result["output_path"], "fixed SFX private output"),
        output,
        "fixed SFX probe output",
    )

    receipt_path = _absolute_file(
        result["receipt_path"], "fixed SFX production receipt"
    )
    persisted_receipt = validate_sfx_production_receipt(
        _load_json_sidecar(receipt_path, "fixed SFX production receipt")
    )
    if persisted_receipt != result["receipt"]:
        _fail("fixed SFX production receipt changed after persistence")
    if (persisted_receipt["mode"] != "rendered"
            or persisted_receipt["cue_count"] != 1
            or persisted_receipt["requested_preference"] != "motivated_only"
            or persisted_receipt["policy"]["usage"] != "motivated_only"
            or persisted_receipt["program_input"]["sha256"]
            == persisted_receipt["output"]["sha256"]
            or _sha256_file(output) != persisted_receipt["output"]["sha256"]
            or output.stat().st_size != persisted_receipt["output"]["bytes"]):
        _fail("fixed SFX production output bindings are invalid")

    qa = verify_sfx_production_evidence(
        persisted_receipt,
        output_path=str(output),
        evidence_dir=str(evidence_root),
        expected_engine_envelope_sha256=envelope_hash,
        expected_project_intent_sha256=envelope["project_intent_sha256"],
        expected_parent_edit_policy_sha256=envelope["edit_policy_sha256"],
    )
    if qa.get("ok") is not True or qa.get("policy_bound") is not True:
        _fail("fixed SFX production evidence failed independent verification")

    sidecars = {
        item["file"]: _load_json_sidecar(
            evidence_root / item["file"], f"fixed SFX {item['file']}"
        )
        for item in persisted_receipt["sidecars"]
    }
    manifest = validate_sfx_cue_manifest(sidecars["SFX_CUE_MANIFEST.json"])
    plan = validate_sfx_plan(
        sidecars["SFX_PLAN.json"], manifest,
        sidecars["SFX_EXECUTION_EDIT_POLICY.json"],
    )
    generation_names = sorted(
        name for name in sidecars if name.startswith("SFX_GENERATION_")
    )
    if len(manifest["assets"]) != 1 or len(generation_names) != 1:
        _fail("fixed SFX probe generation evidence is incomplete")
    generation = sidecars[generation_names[0]]
    _verify_generation_evidence(generation, manifest["assets"][0])
    rights = generation["rights"]
    if rights != {
        "basis": "project_owned", "license_id": "project-generated",
        "licensor": "project", "external_service_used": False,
    }:
        _fail("fixed SFX probe did not prove project-generated ownership")

    placement = _decoded_placement_evidence(
        source=source, output=output, ffmpeg=ffmpeg, plan=plan,
        duration_ms=persisted_receipt["actual_duration_ms"], cwd=private,
    )

    tamper_root = private / "rights-tamper-negative"
    tamper_root.mkdir(mode=0o700)
    for binding in persisted_receipt["sidecars"]:
        _copy_file_exclusive(
            evidence_root / binding["file"], tamper_root / binding["file"],
            "fixed SFX tamper fixture",
        )
    tampered_generation = copy.deepcopy(generation)
    tampered_generation["rights"]["external_service_used"] = True
    replacement = _write_json(
        tamper_root / "RIGHTS_TAMPER_TMP.json", tampered_generation,
        "fixed SFX rights tamper",
    )
    try:
        os.replace(replacement, tamper_root / generation_names[0])
    except OSError as error:
        raise SfxProductionError(
            "fixed SFX rights tamper fixture could not be rebound"
        ) from error
    tampered_receipt = copy.deepcopy(persisted_receipt)
    for binding in tampered_receipt["sidecars"]:
        if binding["file"] == generation_names[0]:
            tampered_path = tamper_root / generation_names[0]
            binding["sha256"] = _sha256_file(tampered_path)
            binding["bytes"] = tampered_path.stat().st_size
    tamper_qa = verify_sfx_production_evidence(
        tampered_receipt,
        output_path=str(output),
        evidence_dir=str(tamper_root),
        expected_engine_envelope_sha256=envelope_hash,
        expected_project_intent_sha256=envelope["project_intent_sha256"],
        expected_parent_edit_policy_sha256=envelope["edit_policy_sha256"],
    )
    tamper_note = str(tamper_qa.get("note", ""))
    if (tamper_qa.get("ok") is not False
            or not any(marker in tamper_note for marker in (
                "generation evidence", "project ownership",
                "evidence preimages",
            ))):
        _fail("fixed SFX probe did not reject rebound rights tampering")

    receipt_file = {
        "file": receipt_path.name,
        "sha256": _sha256_file(receipt_path),
        "bytes": receipt_path.stat().st_size,
        "contract_sha256": sfx_production_receipt_sha256(persisted_receipt),
    }
    checks = {
        "decoded_cue_placement": True,
        "independent_evidence_verifier": True,
        "production_sfx_planner": True,
        "production_sfx_renderer": True,
        "project_generated_rights": True,
        "tamper_rejected": True,
    }
    return {
        "schema_version": SFX_PRODUCTION_SELF_TEST_SCHEMA_VERSION,
        "checks": checks,
        "artifact": {
            "file": output.name,
            "sha256": persisted_receipt["output"]["sha256"],
            "bytes": persisted_receipt["output"]["bytes"],
            "duration_ms": persisted_receipt["output"]["duration_ms"],
        },
        "production_receipt": receipt_file,
        "decoded_placement": placement,
        "evidence": {
            "sidecar_count": len(persisted_receipt["sidecars"]),
            "generation_sidecar_count": len(generation_names),
            "rights_basis": rights["basis"],
            "external_service_used": rights["external_service_used"],
        },
    }


__all__ = [
    "SFX_PRODUCTION_RECEIPT_SCHEMA_VERSION",
    "SFX_PRODUCTION_SELF_TEST_SCHEMA_VERSION",
    "SfxProductionError",
    "canonical_sfx_production_receipt_json",
    "execute_project_intent_sfx",
    "sfx_production_receipt_sha256",
    "specialize_edit_policy_for_program",
    "validate_sfx_production_receipt",
    "verify_sfx_production_evidence",
    "write_sfx_production_probe",
]
