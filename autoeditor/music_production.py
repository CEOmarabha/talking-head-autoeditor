"""ProjectIntent-authorized production of deterministic project-owned music.

This is the trusted producer above :mod:`autoeditor.music_plan` and
:mod:`autoeditor.music_render`.  It never accepts a caller/model music path,
never contacts an external service, and never claims ``licensed_music``.
The only added asset is a closed local PCM bed whose exact bytes and rights
preimage are persisted and independently regenerated during final QA.

The v1 slice is intentionally narrow.  ``none`` proves a byte-exact no-op;
``auto`` and ``supporting`` may place one short bed only in a decoded-silent,
speech-free interval.  Primary, source-primary, external/user assets, looping,
and unverified dialogue ducking remain fail-closed.
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
from typing import Any

from autoeditor.edit_policy import (
    CAPABILITIES,
    duration_band,
    edit_policy_sha256,
    validate_edit_policy,
)
from autoeditor.music_plan import (
    MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
    MUSIC_PLAN_SCHEMA_VERSION,
    compile_music_plan,
    derive_dialogue_window_id,
    derive_music_asset_id,
    derive_music_mastering,
    derive_music_policy_limits,
    derive_music_region_id,
    derive_source_music_region_id,
    music_asset_manifest_sha256,
    music_compile_receipt_sha256,
    music_plan_sha256,
    validate_music_asset_manifest,
    validate_music_plan,
)
from autoeditor.music_render import (
    _build_filter,
    canonical_music_render_receipt_json,
    derive_music_output_timeline_sha256,
    execute_music_render,
    music_render_receipt_sha256,
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


MUSIC_PRODUCTION_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-music-production-receipt/v1"
)
MUSIC_PRODUCTION_SELF_TEST_SCHEMA_VERSION = (
    "autoeditor-music-production-self-test/v1"
)
MUSIC_GENERATION_EVIDENCE_SCHEMA_VERSION = (
    "autoeditor-music-generation-evidence/v1"
)
MUSIC_SOURCE_ANALYSIS_SCHEMA_VERSION = (
    "autoeditor-music-source-analysis/v1"
)
MUSIC_SPEECH_EVIDENCE_SCHEMA_VERSION = (
    "autoeditor-music-speech-evidence/v1"
)
MUSIC_AUDIO_QA_SCHEMA_VERSION = "autoeditor-music-audio-qa/v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SAFE_FILE_RE = re.compile(
    r"^[A-Z][A-Z0-9_]{0,95}\.(?:json|wav)$", re.ASCII
)
_PRODUCTION_KEYS = frozenset({
    "schema_version", "mode", "authorization_id", "capability_used",
    "engine_envelope_sha256", "project_intent_sha256",
    "parent_edit_policy_sha256", "execution_edit_policy_sha256",
    "target_duration", "actual_duration_ms", "duration_band",
    "requested_preference", "policy", "region_count", "added_coverage_ms",
    "output_timeline_sha256", "program_input", "output", "rights",
    "audio_qa", "music_asset_manifest_sha256", "music_plan_sha256",
    "music_compile_receipt_sha256", "music_render_receipt_sha256",
    "sidecars",
})
_TARGET_KEYS = frozenset({"min_ms", "max_ms"})
_POLICY_KEYS = frozenset({"usage", "duck_under_dialogue"})
_MEDIA_KEYS = frozenset({
    "sha256", "bytes", "duration_ms", "audio_present",
    "sample_rate_hz", "channels",
})
_RIGHTS_KEYS = frozenset({
    "basis", "generator", "external_service_used",
})
_AUDIO_QA_KEYS = frozenset({
    "integrated_loudness_millilufs", "true_peak_millidbtp",
    "target_loudness_millilufs", "true_peak_ceiling_millidbtp",
    "loudness_tolerance_millilufs", "passed",
})
_SIDECAR_KEYS = frozenset({"file", "sha256", "bytes"})
_MODES = frozenset({"rendered", "no_music_requested", "no_safe_gap"})
_SAMPLE_RATE = 48_000
_CHANNELS = 2
_ANALYSIS_RATE = 8_000
_ANALYSIS_FRAME_MS = 20
_ANALYSIS_THRESHOLD = 0
_PLACEMENT_MARGIN_MS = 120
_MIN_REGION_MS = 800
_MAX_REGION_MS = 8_000
_LOUDNESS_TOLERANCE_MILLILUFS = 1_000
_MAX_CAPTURE_CHARS = 16_000


class MusicProductionError(RuntimeError):
    """Typed music authority, production evidence, or output was invalid."""


def _fail(message: str) -> None:
    raise MusicProductionError(message)


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MusicProductionError(f"{label} is not canonical JSON") from error


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


def _signed_integer(value: object, label: str,
                    minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} is outside its closed integer range")
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
        real = Path(os.path.realpath(path))
        stat = real.stat()
    except OSError as error:
        raise MusicProductionError(f"{label} is unavailable") from error
    if not real.is_file() or stat.st_size < 1:
        _fail(f"{label} must be a nonempty file")
    return real


def _absolute_dir(value: object, label: str) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        _fail(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute():
        _fail(f"{label} path must be absolute")
    try:
        real = Path(os.path.realpath(path))
        real.stat()
    except OSError as error:
        raise MusicProductionError(f"{label} is unavailable") from error
    if not real.is_dir():
        _fail(f"{label} must be a directory")
    return real


def _run(command: list[str], *, cwd: Path, label: str,
         timeout_seconds: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, cwd=str(cwd), shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MusicProductionError(f"{label} could not complete") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[
            -_MAX_CAPTURE_CHARS:
        ]
        raise MusicProductionError(
            f"{label} failed" + (f": {detail}" if detail else "")
        )
    return result


def _probe_media(path: Path, ffprobe: Path, cwd: Path,
                 label: str) -> dict[str, Any]:
    result = _run([
        str(ffprobe), "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,sample_rate,channels",
        "-of", "json", str(path),
    ], cwd=cwd, label=f"{label} probe", timeout_seconds=60)
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        duration_ms = round(float(payload["format"]["duration"]) * 1000)
        video = any(item.get("codec_type") == "video" for item in streams)
        audio = next((item for item in streams
                      if item.get("codec_type") == "audio"), None)
        sample_rate = int(audio["sample_rate"]) if audio is not None else None
        channels = int(audio["channels"]) if audio is not None else None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MusicProductionError(f"{label} media facts are invalid") from error
    if duration_ms < 1 or not video:
        _fail(f"{label} must contain a positive video timeline")
    if audio is not None and (sample_rate is None or channels is None):
        _fail(f"{label} audio facts are invalid")
    return {
        "sha256": _sha256_file(path), "bytes": path.stat().st_size,
        "duration_ms": duration_ms, "audio_present": audio is not None,
        "sample_rate_hz": sample_rate, "channels": channels,
    }


def specialize_music_edit_policy_for_program(
    parent_policy: object,
    *,
    target_duration: object,
    actual_duration_ms: object,
) -> dict[str, Any]:
    """Specialize only duration within the authenticated same-band range."""
    try:
        parent = validate_edit_policy(parent_policy)
    except Exception as error:
        raise MusicProductionError("parent edit policy is invalid") from error
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
        raise MusicProductionError(
            "exact-duration music policy specialization is invalid"
        ) from error
    parent_rules = copy.deepcopy(parent)
    child_rules = copy.deepcopy(child)
    parent_rules.pop("duration")
    child_rules.pop("duration")
    if parent_rules != child_rules:
        _fail("music duration specialization changed an unauthorized rule")
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
        raise MusicProductionError(f"{label} could not be written") from error
    return path


def _write_json(path: Path, value: object, label: str) -> Path:
    return _write_private(path, _canonical_bytes(value, label), label)


def _sidecar_binding(path: Path) -> dict[str, Any]:
    return {
        "file": path.name, "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _persist_sidecars(source_paths: list[Path], evidence_dir: Path) -> list[Path]:
    names = [path.name for path in source_paths]
    if (len(names) != len(set(names))
            or any(_SAFE_FILE_RE.fullmatch(name) is None for name in names)):
        _fail("typed music sidecar inventory is unsafe")
    destinations = [evidence_dir / name for name in names]
    if any(path.exists() for path in destinations):
        _fail("typed music sidecar already exists")
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


def _speech_evidence(words: object, duration_ms: int) -> tuple[dict, list[dict]]:
    if type(words) is not list:
        _fail("typed music speech evidence must be a list")
    rows: list[dict[str, Any]] = []
    intervals: list[list[int]] = []
    previous_start = -1
    for index, word in enumerate(words):
        if type(word) is not dict:
            _fail(f"typed music speech word {index} is invalid")
        start = _finite_milliseconds(
            word.get("s"), f"speech_words[{index}].s", duration_ms)
        end = _finite_milliseconds(
            word.get("e"), f"speech_words[{index}].e", duration_ms)
        text = word.get("w")
        if (type(text) is not str or not text or end <= start
                or start < previous_start):
            _fail(f"typed music speech word {index} is malformed")
        previous_start = start
        rows.append({
            "index": index, "start_ms": start, "end_ms": end, "text": text,
        })
        if intervals and start <= intervals[-1][1] + 80:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([start, end])
    evidence = {
        "schema_version": MUSIC_SPEECH_EVIDENCE_SCHEMA_VERSION,
        "duration_ms": duration_ms, "words": rows,
    }
    digest = _sha256_bytes(_canonical_bytes(evidence, "music speech evidence"))
    windows = []
    for start, end in intervals:
        payload = {
            "start_ms": start, "end_ms": end,
            "evidence_kind": "transcript", "evidence_sha256": digest,
        }
        windows.append({
            "dialogue_window_id": derive_dialogue_window_id(
                payload, duration_ms, digest),
            **payload,
        })
    return evidence, windows


def _merge_intervals(intervals: list[tuple[int, int]],
                     duration_ms: int, gap_ms: int = 0) -> list[list[int]]:
    result: list[list[int]] = []
    for raw_start, raw_end in sorted(intervals):
        start = max(0, min(duration_ms, raw_start))
        end = max(0, min(duration_ms, raw_end))
        if end <= start:
            continue
        if result and start <= result[-1][1] + gap_ms:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def _analyze_program_audio(
    program: Path,
    *,
    ffmpeg: Path,
    cwd: Path,
    program_binding: dict,
) -> dict[str, Any]:
    """Conservatively treat every nonzero decoded frame as source music.

    This deliberately creates false positives rather than false negatives:
    added music may only occupy decoded-zero intervals.  It is not a semantic
    music classifier and never claims that audible source material is absent.
    """
    duration_ms = program_binding["duration_ms"]
    active: list[tuple[int, int]] = []
    decoded_samples = 0
    active_frames = 0
    if program_binding["audio_present"]:
        command = [
            str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-i", str(program), "-map", "0:a:0", "-vn", "-ac", "1",
            "-ar", str(_ANALYSIS_RATE), "-c:a", "pcm_s16le", "-f", "s16le",
            "-",
        ]
        try:
            process = subprocess.Popen(
                command, cwd=str(cwd), shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise MusicProductionError(
                "typed music source analysis could not start"
            ) from error
        assert process.stdout is not None
        frame_samples = _ANALYSIS_RATE * _ANALYSIS_FRAME_MS // 1000
        frame_bytes = frame_samples * 2
        frame_index = 0
        try:
            while True:
                block = process.stdout.read(frame_bytes)
                if not block:
                    break
                usable = len(block) - len(block) % 2
                samples = struct.iter_unpack("<h", block[:usable])
                peak = max((abs(item[0]) for item in samples), default=0)
                sample_count = usable // 2
                decoded_samples += sample_count
                start = frame_index * _ANALYSIS_FRAME_MS
                end = min(duration_ms, start + math.ceil(
                    sample_count * 1000 / _ANALYSIS_RATE))
                if peak > _ANALYSIS_THRESHOLD and end > start:
                    active.append((start, end))
                    active_frames += 1
                frame_index += 1
            returncode = process.wait(timeout=60)
        except Exception:
            process.kill()
            process.wait()
            raise
        finally:
            process.stdout.close()
        if returncode != 0:
            _fail("typed music source analysis decode failed")
    merged = _merge_intervals(active, duration_ms, gap_ms=_ANALYSIS_FRAME_MS)
    if len(merged) > 4_096:
        # Collapsing the whole active span can only remove eligible placement
        # space; it can never create a false silent gap.
        merged = [[merged[0][0], merged[-1][1]]]
    return {
        "schema_version": MUSIC_SOURCE_ANALYSIS_SCHEMA_VERSION,
        "method": "conservative-all-nonzero-pcm-as-potential-source-music/v1",
        "program": copy.deepcopy(program_binding),
        "analysis": {
            "sample_rate_hz": _ANALYSIS_RATE,
            "channels": 1,
            "sample_width_bytes": 2,
            "frame_duration_ms": _ANALYSIS_FRAME_MS,
            "absolute_sample_threshold": _ANALYSIS_THRESHOLD,
            "decoded_sample_count": decoded_samples,
            "active_frame_count": active_frames,
        },
        "potential_source_music_regions": [
            {"start_ms": start, "end_ms": end} for start, end in merged
        ],
        "absence_claimed": len(merged) == 0,
    }


def _bed_pcm(duration_ms: int) -> bytes:
    frames = duration_ms * _SAMPLE_RATE // 1000
    frequencies = (130.813, 164.814, 195.998, 261.626)
    pcm = bytearray(frames * _CHANNELS * 2)
    attack_frames = max(1, min(frames // 4, _SAMPLE_RATE * 80 // 1000))
    release_frames = attack_frames
    for index in range(frames):
        seconds = index / _SAMPLE_RATE
        attack = min(1.0, index / attack_frames)
        release = min(1.0, (frames - 1 - index) / release_frames)
        envelope = max(0.0, min(attack, release))
        pulse = 0.82 + 0.18 * math.sin(2.0 * math.pi * 1.6 * seconds)
        chord = sum(
            math.sin(2.0 * math.pi * frequency * seconds + note * 0.37)
            for note, frequency in enumerate(frequencies)
        ) / len(frequencies)
        sample = envelope * pulse * chord * 0.24
        value = round(max(-0.72, min(0.72, sample)) * 32767)
        struct.pack_into("<hh", pcm, index * 4, value, value)
    return bytes(pcm)


def _bed_wave_bytes(duration_ms: int) -> bytes:
    output = io.BytesIO()
    try:
        with wave.open(output, "wb") as bed:
            bed.setnchannels(_CHANNELS)
            bed.setsampwidth(2)
            bed.setframerate(_SAMPLE_RATE)
            bed.writeframes(_bed_pcm(duration_ms))
    except wave.Error as error:
        raise MusicProductionError(
            "project-owned music bytes could not be generated"
        ) from error
    return output.getvalue()


def _generate_bed(duration_ms: int, work: Path) -> tuple[Path, dict, Path]:
    wave_bytes = _bed_wave_bytes(duration_ms)
    asset_path = _write_private(
        work / "MUSIC_PROJECT_BED.wav", wave_bytes, "project-owned music bed")
    generation = {
        "schema_version": MUSIC_GENERATION_EVIDENCE_SCHEMA_VERSION,
        "generator": "autoeditor-deterministic-musical-pcm/v1",
        "parameters": {
            "sample_rate_hz": _SAMPLE_RATE,
            "channels": _CHANNELS,
            "sample_width_bytes": 2,
            "duration_ms": duration_ms,
            "tempo_millibpm": 96_000,
            "key": "C_major",
            "oscillator": "sine_chord",
            "frequencies_millihz": [130_813, 164_814, 195_998, 261_626],
            "peak_amplitude_millionths": 240_000,
        },
        "asset": {"sha256": _sha256_bytes(wave_bytes), "bytes": len(wave_bytes)},
        "rights": {
            "basis": "project_owned",
            "license_id": "project-generated",
            "license_name": "Project ownership",
            "licensor": "project",
            "external_service_used": False,
            "permits_synchronization": True,
            "permits_editing": True,
            "permits_looping": False,
            "permits_delivery": True,
        },
    }
    generation_path = _write_json(
        work / "MUSIC_GENERATION_EVIDENCE.json", generation,
        "music generation evidence",
    )
    evidence_sha = _sha256_file(generation_path)
    asset_payload = {
        "sha256": generation["asset"]["sha256"],
        "byte_length": generation["asset"]["bytes"],
        "decoded_duration_ms": duration_ms,
        "sample_rate_hz": _SAMPLE_RATE,
        "channels": _CHANNELS,
        "source_ref": "project-generated://music/closed-bed-v1.wav",
        "provenance": "project_generated",
        "license": {
            "basis": "project_owned",
            "license_id": "project-generated",
            "license_name": "Project ownership",
            "licensor": "project",
            "evidence_sha256": evidence_sha,
        },
        "rights_receipt": {
            "receipt_id": "project-generated-music-v1",
            "receipt_sha256": evidence_sha,
            "permits_synchronization": True,
            "permits_editing": True,
            "permits_looping": False,
            "permits_delivery": True,
        },
    }
    return asset_path, {
        "asset_id": derive_music_asset_id(asset_payload), **asset_payload,
    }, generation_path


def _safe_gap(
    *,
    source_regions: list[dict],
    dialogue_windows: list[dict],
    duration_ms: int,
    maximum_ms: int,
) -> tuple[int, int] | None:
    blockers = [
        (item["start_ms"] - _PLACEMENT_MARGIN_MS,
         item["end_ms"] + _PLACEMENT_MARGIN_MS)
        for item in [*source_regions, *dialogue_windows]
    ]
    merged = _merge_intervals(blockers, duration_ms)
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration_ms:
        gaps.append((cursor, duration_ms))
    eligible = [(start, end) for start, end in gaps
                if end - start >= _MIN_REGION_MS]
    if not eligible or maximum_ms < _MIN_REGION_MS:
        return None
    # Longest gap wins; an earlier gap breaks ties.  This is deterministic and
    # avoids making an aesthetic decision from untrusted model text.
    start, end = min(eligible, key=lambda item: (-(item[1] - item[0]), item[0]))
    return start, min(end - start, maximum_ms, _MAX_REGION_MS)


def _normalize_media(value: object, label: str) -> dict[str, Any]:
    raw = _exact_dict(value, _MEDIA_KEYS, label)
    audio_present = raw["audio_present"]
    if type(audio_present) is not bool:
        _fail(f"{label}.audio_present must be boolean")
    sample_rate = raw["sample_rate_hz"]
    channels = raw["channels"]
    if audio_present:
        sample_rate = _integer(sample_rate, f"{label}.sample_rate_hz", 1)
        channels = _integer(channels, f"{label}.channels", 1)
    elif sample_rate is not None or channels is not None:
        _fail(f"{label} silent media cannot claim audio facts")
    return {
        "sha256": _digest(raw["sha256"], f"{label}.sha256"),
        "bytes": _integer(raw["bytes"], f"{label}.bytes", 1),
        "duration_ms": _integer(
            raw["duration_ms"], f"{label}.duration_ms", 1),
        "audio_present": audio_present,
        "sample_rate_hz": sample_rate,
        "channels": channels,
    }


def _normalize_audio_qa(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = _exact_dict(value, _AUDIO_QA_KEYS, "music production audio QA")
    result = {
        "integrated_loudness_millilufs": _signed_integer(
            raw["integrated_loudness_millilufs"],
            "measured integrated loudness", -70_000, 0),
        "true_peak_millidbtp": _signed_integer(
            raw["true_peak_millidbtp"], "measured true peak", -100_000, 12_000),
        "target_loudness_millilufs": _signed_integer(
            raw["target_loudness_millilufs"], "target loudness", -40_000, -5_000),
        "true_peak_ceiling_millidbtp": _signed_integer(
            raw["true_peak_ceiling_millidbtp"], "true peak ceiling", -9_000, -100),
        "loudness_tolerance_millilufs": _integer(
            raw["loudness_tolerance_millilufs"], "loudness tolerance", 1),
        "passed": raw["passed"],
    }
    if type(result["passed"]) is not bool:
        _fail("music production audio QA pass state is invalid")
    expected_pass = (
        abs(result["integrated_loudness_millilufs"]
            - result["target_loudness_millilufs"])
        <= result["loudness_tolerance_millilufs"]
        and result["true_peak_millidbtp"]
        <= result["true_peak_ceiling_millidbtp"] + 100
    )
    if result["passed"] != expected_pass:
        _fail("music production audio QA result is inconsistent")
    return result


def validate_music_production_receipt(value: object) -> dict[str, Any]:
    raw = _exact_dict(value, _PRODUCTION_KEYS, "music production receipt")
    if raw["schema_version"] != MUSIC_PRODUCTION_RECEIPT_SCHEMA_VERSION:
        _fail("music production receipt schema is unsupported")
    mode = raw["mode"]
    if type(mode) is not str or mode not in _MODES:
        _fail("music production receipt mode is unsupported")
    authorization_id = raw["authorization_id"]
    if (type(authorization_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", authorization_id) is None):
        _fail("music production receipt authorization id is invalid")
    capability = raw["capability_used"]
    if capability not in {None, "project_generated_music"}:
        _fail("music production receipt capability is invalid")
    hashes = {
        key: _digest(raw[key], f"music production receipt.{key}")
        for key in (
            "engine_envelope_sha256", "project_intent_sha256",
            "parent_edit_policy_sha256", "execution_edit_policy_sha256",
            "output_timeline_sha256",
        )
    }
    nullable_hashes: dict[str, str | None] = {}
    for key in (
        "music_asset_manifest_sha256", "music_plan_sha256",
        "music_compile_receipt_sha256", "music_render_receipt_sha256",
    ):
        nullable_hashes[key] = None if raw[key] is None else _digest(
            raw[key], f"music production receipt.{key}")
    target = _exact_dict(
        raw["target_duration"], _TARGET_KEYS,
        "music production receipt target duration")
    normalized_target = {
        "min_ms": _integer(target["min_ms"], "target min", 1),
        "max_ms": _integer(target["max_ms"], "target max", 1),
    }
    actual = _integer(raw["actual_duration_ms"], "actual duration", 1)
    if not normalized_target["min_ms"] <= actual <= normalized_target["max_ms"]:
        _fail("music production receipt duration is outside its target")
    band = raw["duration_band"]
    if type(band) is not str or duration_band(actual) != band:
        _fail("music production receipt duration band is invalid")
    preference = raw["requested_preference"]
    if type(preference) is not str:
        _fail("music production receipt preference is invalid")
    policy = _exact_dict(
        raw["policy"], _POLICY_KEYS, "music production receipt policy")
    if (type(policy["usage"]) is not str
            or type(policy["duck_under_dialogue"]) is not bool):
        _fail("music production receipt policy is invalid")
    region_count = _integer(raw["region_count"], "music region count")
    added_coverage = _integer(
        raw["added_coverage_ms"], "music added coverage")
    if added_coverage > actual:
        _fail("music added coverage exceeds the exact timeline")
    program = _normalize_media(raw["program_input"], "music program input")
    output = _normalize_media(raw["output"], "music output")
    rights = _exact_dict(raw["rights"], _RIGHTS_KEYS, "music production rights")
    if (rights["basis"] not in {None, "project_owned"}
            or rights["generator"] not in {
                None, "autoeditor-deterministic-musical-pcm/v1"}
            or type(rights["external_service_used"]) is not bool):
        _fail("music production rights are invalid")
    audio_qa = _normalize_audio_qa(raw["audio_qa"])
    sidecars = raw["sidecars"]
    if type(sidecars) is not list:
        _fail("music production receipt sidecars are invalid")
    normalized_sidecars = []
    for index, raw_item in enumerate(sidecars):
        item = _exact_dict(
            raw_item, _SIDECAR_KEYS, f"music sidecar {index}")
        if (type(item["file"]) is not str
                or _SAFE_FILE_RE.fullmatch(item["file"]) is None):
            _fail("music production receipt sidecar filename is invalid")
        normalized_sidecars.append({
            "file": item["file"],
            "sha256": _digest(item["sha256"], "music sidecar sha256"),
            "bytes": _integer(item["bytes"], "music sidecar bytes", 1),
        })
    if (normalized_sidecars != sorted(
            normalized_sidecars, key=lambda item: item["file"])
            or len({item["file"] for item in normalized_sidecars})
            != len(normalized_sidecars)):
        _fail("music production sidecars must be sorted and unique")
    rendered = mode == "rendered"
    if rendered != (region_count > 0 and added_coverage > 0):
        _fail("music production mode contradicts its region counts")
    if rendered != all(item is not None for item in nullable_hashes.values()):
        _fail("music production mode contradicts its receipt chain")
    if rendered:
        if (capability != "project_generated_music"
                or rights != {
                    "basis": "project_owned",
                    "generator": "autoeditor-deterministic-musical-pcm/v1",
                    "external_service_used": False,
                }
                or audio_qa is None or audio_qa["passed"] is not True
                or not output["audio_present"]
                or output["sample_rate_hz"] != _SAMPLE_RATE
                or output["channels"] != _CHANNELS):
            _fail("rendered music production lacks truthful rights or measured QA")
    else:
        expected_capability = (
            None if mode == "no_music_requested" else "project_generated_music")
        if (capability != expected_capability or region_count != 0
                or added_coverage != 0 or audio_qa is not None
                or rights != {
                    "basis": None, "generator": None,
                    "external_service_used": False,
                }
                or program != output):
            _fail("no-op music production receipt changed program or rights")
    expected_timeline = derive_music_output_timeline_sha256(
        program_sha256=program["sha256"], program_bytes=program["bytes"],
        duration_ms=actual,
    )
    if hashes["output_timeline_sha256"] != expected_timeline:
        _fail("music production timeline does not bind its program input")
    return copy.deepcopy({
        "schema_version": MUSIC_PRODUCTION_RECEIPT_SCHEMA_VERSION,
        "mode": mode, "authorization_id": authorization_id,
        "capability_used": capability, **hashes,
        "target_duration": normalized_target,
        "actual_duration_ms": actual, "duration_band": band,
        "requested_preference": preference,
        "policy": {
            "usage": policy["usage"],
            "duck_under_dialogue": policy["duck_under_dialogue"],
        },
        "region_count": region_count, "added_coverage_ms": added_coverage,
        "program_input": program, "output": output,
        "rights": copy.deepcopy(rights), "audio_qa": audio_qa,
        **nullable_hashes, "sidecars": normalized_sidecars,
    })


def canonical_music_production_receipt_json(value: object) -> str:
    return _canonical_json(
        validate_music_production_receipt(value), "music production receipt")


def music_production_receipt_sha256(value: object) -> str:
    return hashlib.sha256(
        canonical_music_production_receipt_json(value).encode("ascii")
    ).hexdigest()


def _load_json_sidecar(path: Path, label: str) -> object:
    def closed_pairs(pairs: list[tuple[str, object]]) -> dict:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise MusicProductionError(f"{label} contains duplicate keys")
            value[key] = item
        return value

    try:
        return json.loads(
            path.read_text(encoding="ascii", errors="strict"),
            object_pairs_hook=closed_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                MusicProductionError(f"{label} contains a non-finite number")
            ),
        )
    except MusicProductionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MusicProductionError(f"{label} is not valid evidence JSON") from error


def _verify_generation_evidence(
    value: object,
    *,
    asset: dict,
    asset_path: Path,
) -> None:
    raw = _exact_dict(value, frozenset({
        "schema_version", "generator", "parameters", "asset", "rights",
    }), "music generation evidence")
    if (raw["schema_version"] != MUSIC_GENERATION_EVIDENCE_SCHEMA_VERSION
            or raw["generator"]
            != "autoeditor-deterministic-musical-pcm/v1"):
        _fail("music generation evidence identifies an unsupported generator")
    parameters = _exact_dict(raw["parameters"], frozenset({
        "sample_rate_hz", "channels", "sample_width_bytes", "duration_ms",
        "tempo_millibpm", "key", "oscillator", "frequencies_millihz",
        "peak_amplitude_millionths",
    }), "music generation parameters")
    expected_parameters = {
        "sample_rate_hz": _SAMPLE_RATE, "channels": _CHANNELS,
        "sample_width_bytes": 2, "duration_ms": asset["decoded_duration_ms"],
        "tempo_millibpm": 96_000, "key": "C_major",
        "oscillator": "sine_chord",
        "frequencies_millihz": [130_813, 164_814, 195_998, 261_626],
        "peak_amplitude_millionths": 240_000,
    }
    if parameters != expected_parameters:
        _fail("music generation parameters drifted from the closed generator")
    expected_wave = _bed_wave_bytes(parameters["duration_ms"])
    generated_asset = _exact_dict(
        raw["asset"], frozenset({"sha256", "bytes"}),
        "music generated asset binding")
    expected_binding = {
        "sha256": _sha256_bytes(expected_wave), "bytes": len(expected_wave),
    }
    if (generated_asset != expected_binding
            or asset["sha256"] != expected_binding["sha256"]
            or asset["byte_length"] != expected_binding["bytes"]
            or asset_path.stat().st_size != expected_binding["bytes"]
            or _sha256_file(asset_path) != expected_binding["sha256"]):
        _fail("music asset bytes do not match the trusted local generator")
    rights = _exact_dict(raw["rights"], frozenset({
        "basis", "license_id", "license_name", "licensor",
        "external_service_used", "permits_synchronization", "permits_editing",
        "permits_looping", "permits_delivery",
    }), "music generation rights")
    if rights != {
        "basis": "project_owned", "license_id": "project-generated",
        "license_name": "Project ownership", "licensor": "project",
        "external_service_used": False, "permits_synchronization": True,
        "permits_editing": True, "permits_looping": False,
        "permits_delivery": True,
    }:
        _fail("music generation evidence does not prove project ownership")


def _measure_audio_qa(
    media: Path,
    *,
    ffmpeg: Path,
    cwd: Path,
    target: dict[str, int],
) -> dict[str, Any]:
    target_lufs = target["target_loudness_millilufs"] / 1000
    peak_ceiling = target["true_peak_ceiling_millidbtp"] / 1000
    result = _run([
        str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "info",
        "-i", str(media), "-map", "0:a:0", "-vn", "-af",
        f"loudnorm=I={target_lufs:.3f}:TP={peak_ceiling:.3f}:"
        "LRA=11.000:print_format=json",
        "-f", "null", "-",
    ], cwd=cwd, label="typed music measured loudness", timeout_seconds=180)
    payload = result.stderr
    matches = re.findall(r"\{\s*\"input_i\".*?\}", payload, re.DOTALL)
    if not matches:
        _fail("typed music loudness measurement did not emit JSON facts")
    try:
        facts = json.loads(matches[-1])
        measured_lufs = round(float(facts["input_i"]) * 1000)
        measured_peak = round(float(facts["input_tp"]) * 1000)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MusicProductionError(
            "typed music loudness measurement is invalid") from error
    qa = {
        "integrated_loudness_millilufs": measured_lufs,
        "true_peak_millidbtp": measured_peak,
        "target_loudness_millilufs": target["target_loudness_millilufs"],
        "true_peak_ceiling_millidbtp": target["true_peak_ceiling_millidbtp"],
        "loudness_tolerance_millilufs": _LOUDNESS_TOLERANCE_MILLILUFS,
        "passed": (
            abs(measured_lufs - target["target_loudness_millilufs"])
            <= _LOUDNESS_TOLERANCE_MILLILUFS
            and measured_peak <= target["true_peak_ceiling_millidbtp"] + 100
        ),
    }
    return _normalize_audio_qa(qa) or {}


def _source_regions_from_analysis(
    analysis: dict,
    *,
    evidence_sha256: str,
    duration_ms: int,
) -> list[dict]:
    regions = []
    for item in analysis["potential_source_music_regions"]:
        payload = {
            "start_ms": item["start_ms"], "end_ms": item["end_ms"],
            "evidence_sha256": evidence_sha256,
        }
        regions.append({
            "source_region_id": derive_source_music_region_id(
                payload, duration_ms),
            **payload,
        })
    return regions


def verify_music_production_evidence(
    receipt: object,
    *,
    program_input_path: str,
    output_path: str,
    evidence_dir: str,
    expected_engine_envelope_sha256: str,
    expected_project_intent_sha256: str,
    expected_parent_edit_policy_sha256: str,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> dict[str, Any]:
    """Independently reopen, recompile, regenerate, decode, and remeasure.

    The verifier does not trust the producer's in-memory plan/result.  It
    re-hashes every sidecar and both media inputs, regenerates the local WAV,
    reruns conservative source-audio analysis, recompiles the music plan,
    reconstructs the renderer graph, and measures delivered loudness/peak.
    """
    mode = None
    region_count = 0
    policy_usage = "unverified"
    try:
        normalized = validate_music_production_receipt(receipt)
        mode = normalized["mode"]
        region_count = normalized["region_count"]
        policy_usage = normalized["policy"]["usage"]
        if (normalized["engine_envelope_sha256"] != _digest(
                expected_engine_envelope_sha256, "expected envelope digest")
                or normalized["project_intent_sha256"] != _digest(
                    expected_project_intent_sha256,
                    "expected project intent digest")
                or normalized["parent_edit_policy_sha256"] != _digest(
                    expected_parent_edit_policy_sha256,
                    "expected parent policy digest")):
            _fail("music production receipt is bound to different authority")
        program = _absolute_file(program_input_path, "music QA program input")
        output = _absolute_file(output_path, "music QA output")
        ffmpeg = _absolute_file(ffmpeg_path, "music QA FFmpeg")
        ffprobe = _absolute_file(ffprobe_path, "music QA FFprobe")
        root = _absolute_dir(evidence_dir, "music QA evidence directory")
        measured_program = _probe_media(program, ffprobe, root, "music QA program")
        measured_output = _probe_media(output, ffprobe, root, "music QA output")
        if measured_program != normalized["program_input"]:
            _fail("music QA program bytes do not match production authority")
        if measured_output != normalized["output"]:
            _fail("music QA output bytes do not match the production receipt")

        sidecars: dict[str, tuple[Path, object | None]] = {}
        for binding in normalized["sidecars"]:
            path = root / binding["file"]
            if (not path.is_file() or path.stat().st_size != binding["bytes"]
                    or _sha256_file(path) != binding["sha256"]):
                _fail(
                    f"music QA sidecar {binding['file']} is missing or changed")
            value = None if path.suffix.lower() == ".wav" else _load_json_sidecar(
                path, f"music sidecar {path.name}")
            sidecars[path.name] = (path, value)
        policy_item = sidecars.get("MUSIC_EXECUTION_EDIT_POLICY.json")
        if policy_item is None:
            _fail("music execution edit policy sidecar is missing")
        execution_policy = validate_edit_policy(policy_item[1])
        if (edit_policy_sha256(execution_policy)
                != normalized["execution_edit_policy_sha256"]
                or execution_policy["duration"]["duration_ms"]
                != normalized["actual_duration_ms"]
                or execution_policy["duration"]["band"]
                != normalized["duration_band"]
                or execution_policy["rules"]["music"]
                != normalized["policy"]):
            _fail("music execution policy contradicts production authority")

        if mode == "no_music_requested":
            if set(sidecars) != {"MUSIC_EXECUTION_EDIT_POLICY.json"}:
                _fail("disabled music production persisted unexpected evidence")
            return {
                "ok": True, "mode": mode, "region_count": 0,
                "policy_usage": policy_usage, "policy_bound": True,
                "rights_verified": True, "dialogue_masking_verified": True,
                "loudness_verified": True,
                "receipt_sha256": music_production_receipt_sha256(normalized),
                "output_sha256": normalized["output"]["sha256"], "note": "",
            }

        analysis_item = sidecars.get("MUSIC_SOURCE_ANALYSIS.json")
        speech_item = sidecars.get("MUSIC_SPEECH_EVIDENCE.json")
        if analysis_item is None or speech_item is None:
            _fail("music source/speech evidence is incomplete")
        reconstructed_analysis = _analyze_program_audio(
            program, ffmpeg=ffmpeg, cwd=root,
            program_binding=normalized["program_input"])
        if analysis_item[1] != reconstructed_analysis:
            _fail("music source analysis does not match decoded program audio")
        speech_raw = _exact_dict(speech_item[1], frozenset({
            "schema_version", "duration_ms", "words",
        }), "music speech evidence")
        if speech_raw["schema_version"] != MUSIC_SPEECH_EVIDENCE_SCHEMA_VERSION:
            _fail("music speech evidence schema is unsupported")
        reconstructed_speech, dialogue_windows = _speech_evidence([
            {
                "w": item["text"], "s": item["start_ms"] / 1000,
                "e": item["end_ms"] / 1000,
            }
            for item in speech_raw["words"]
        ], normalized["actual_duration_ms"])
        if speech_raw != reconstructed_speech:
            _fail("music speech windows do not match exact word evidence")
        if mode == "no_safe_gap":
            if set(sidecars) != {
                    "MUSIC_EXECUTION_EDIT_POLICY.json",
                    "MUSIC_SOURCE_ANALYSIS.json",
                    "MUSIC_SPEECH_EVIDENCE.json"}:
                _fail("no-gap music production persisted unexpected evidence")
            source_regions = _source_regions_from_analysis(
                reconstructed_analysis,
                evidence_sha256=_sha256_file(analysis_item[0]),
                duration_ms=normalized["actual_duration_ms"],
            )
            limits = derive_music_policy_limits(
                execution_policy, normalized["actual_duration_ms"])
            maximum = min(
                limits["max_added_coverage_ms"], _MAX_REGION_MS)
            if _safe_gap(
                    source_regions=source_regions,
                    dialogue_windows=dialogue_windows,
                    duration_ms=normalized["actual_duration_ms"],
                    maximum_ms=maximum) is not None:
                _fail("no-gap music receipt omitted an executable safe region")
            return {
                "ok": True, "mode": mode, "region_count": 0,
                "policy_usage": policy_usage, "policy_bound": True,
                "rights_verified": True, "dialogue_masking_verified": True,
                "loudness_verified": True,
                "receipt_sha256": music_production_receipt_sha256(normalized),
                "output_sha256": normalized["output"]["sha256"], "note": "",
            }

        required = {
            "MUSIC_ASSET_MANIFEST.json", "MUSIC_PLAN.json",
            "MUSIC_COMPILE_RECEIPT.json", "MUSIC_RENDER_RECEIPT.json",
            "MUSIC_GENERATION_EVIDENCE.json", "MUSIC_PROJECT_BED.wav",
            "MUSIC_AUDIO_QA.json",
        }
        if not required <= set(sidecars):
            _fail("rendered music production evidence is incomplete")
        manifest = validate_music_asset_manifest(
            sidecars["MUSIC_ASSET_MANIFEST.json"][1])
        plan = validate_music_plan(
            sidecars["MUSIC_PLAN.json"][1], manifest, execution_policy)
        compiled = compile_music_plan(plan, manifest, execution_policy)
        persisted_compile = sidecars["MUSIC_COMPILE_RECEIPT.json"][1]
        if (manifest["output_timeline_sha256"]
                != normalized["output_timeline_sha256"]
                or music_asset_manifest_sha256(manifest)
                != normalized["music_asset_manifest_sha256"]
                or music_plan_sha256(plan) != normalized["music_plan_sha256"]
                or compiled["receipt"] != persisted_compile
                or music_compile_receipt_sha256(persisted_compile)
                != normalized["music_compile_receipt_sha256"]):
            _fail("music manifest, plan, or compile receipt chain changed")
        if (manifest["transcript_sha256"] != _sha256_file(speech_item[0])
                or manifest["dialogue_windows"] != dialogue_windows):
            _fail("music manifest dialogue evidence changed")
        source_regions = _source_regions_from_analysis(
            reconstructed_analysis,
            evidence_sha256=_sha256_file(analysis_item[0]),
            duration_ms=normalized["actual_duration_ms"],
        )
        expected_source = {
            "status": "present" if source_regions else "absent",
            "evidence_sha256": _sha256_file(analysis_item[0]),
            "exclusion_authorization_sha256": None,
            "regions": source_regions,
        }
        if manifest["source_music"] != expected_source:
            _fail("music manifest source regions changed from decoded analysis")
        if len(manifest["assets"]) != 1:
            _fail("typed music manifest must contain one local project asset")
        asset = manifest["assets"][0]
        generation_path, generation_value = sidecars[
            "MUSIC_GENERATION_EVIDENCE.json"]
        asset_path = sidecars["MUSIC_PROJECT_BED.wav"][0]
        _verify_generation_evidence(
            generation_value, asset=asset, asset_path=asset_path)
        generation_hash = _sha256_file(generation_path)
        if (asset["provenance"] != "project_generated"
                or asset["license"]["basis"] != "project_owned"
                or asset["license"]["evidence_sha256"] != generation_hash
                or asset["rights_receipt"]["receipt_sha256"] != generation_hash
                or asset["rights_receipt"]["permits_looping"] is not False):
            _fail("music asset rights do not bind local generation evidence")

        render_receipt = json.loads(canonical_music_render_receipt_json(
            sidecars["MUSIC_RENDER_RECEIPT.json"][1]))
        if (music_render_receipt_sha256(render_receipt)
                != normalized["music_render_receipt_sha256"]
                or render_receipt["music_compile_receipt_sha256"]
                != normalized["music_compile_receipt_sha256"]
                or render_receipt["music_plan_sha256"]
                != normalized["music_plan_sha256"]
                or render_receipt["music_asset_manifest_sha256"]
                != normalized["music_asset_manifest_sha256"]
                or render_receipt["edit_policy_sha256"]
                != normalized["execution_edit_policy_sha256"]
                or render_receipt["output_timeline_sha256"]
                != normalized["output_timeline_sha256"]
                or render_receipt["ordered_region_ids"]
                != compiled["receipt"]["ordered_region_ids"]
                or render_receipt["ordered_asset_ids"]
                != compiled["receipt"]["ordered_asset_ids"]
                or render_receipt["region_count"] != region_count
                or render_receipt["program_input"]["sha256"]
                != normalized["program_input"]["sha256"]
                or render_receipt["program_input"]["bytes"]
                != normalized["program_input"]["bytes"]
                or render_receipt["output"]["sha256"]
                != normalized["output"]["sha256"]
                or render_receipt["output"]["bytes"]
                != normalized["output"]["bytes"]):
            _fail("music render receipt does not bind the final output")
        expected_analysis_filter = _build_filter(
            compiled,
            program_audio_present=normalized["program_input"]["audio_present"],
            analysis_pass=True)
        expected_filter = _build_filter(
            compiled,
            program_audio_present=normalized["program_input"]["audio_present"],
            mastering_parameters=render_receipt["mastering"][
                "applied_parameters"])
        if (render_receipt["filter_complex_sha256"]
                != _sha256_bytes(expected_filter.encode("utf-8"))
                or render_receipt["mastering"][
                    "analysis_filter_complex_sha256"]
                != _sha256_bytes(expected_analysis_filter.encode("utf-8"))):
            _fail("music render filter does not match independent compilation")
        expected_asset_inputs = [{
            "asset_id": asset["asset_id"], "sha256": asset["sha256"],
            "bytes": asset["byte_length"],
            "duration_ms": asset["decoded_duration_ms"],
            "sample_rate_hz": asset["sample_rate_hz"],
            "channels": asset["channels"], "source_ref": asset["source_ref"],
            "provenance": asset["provenance"],
            "license_evidence_sha256": generation_hash,
            "rights_receipt_sha256": generation_hash,
        }]
        if render_receipt["asset_inputs"] != expected_asset_inputs:
            _fail("music renderer consumed a different project asset")
        evidence_roles = {
            generation_hash: ["license", "rights"],
            _sha256_file(analysis_item[0]): (
                ["source_music_analysis", "source_music_region"]
                if source_regions else ["source_music_analysis"]),
        }
        expected_evidence = sorted(({
            "sha256": digest,
            "bytes": next(
                binding["bytes"] for binding in normalized["sidecars"]
                if binding["sha256"] == digest),
            "roles": roles,
        } for digest, roles in evidence_roles.items()), key=lambda item: item["sha256"])
        if render_receipt["evidence_inputs"] != expected_evidence:
            _fail("music renderer consumed a different rights/source inventory")
        if any(
                region["start_ms"] < window["end_ms"]
                and region["start_ms"] + region["duration_ms"]
                > window["start_ms"]
                for region in plan["regions"] for window in dialogue_windows):
            _fail("music plan overlaps a verified dialogue window")

        measured_qa = _measure_audio_qa(
            output, ffmpeg=ffmpeg, cwd=root,
            target=derive_music_mastering(execution_policy))
        persisted_qa = _exact_dict(
            sidecars["MUSIC_AUDIO_QA.json"][1], frozenset({
                "schema_version", "output_sha256", "measurement",
            }), "music audio QA evidence")
        if (persisted_qa["schema_version"] != MUSIC_AUDIO_QA_SCHEMA_VERSION
                or persisted_qa["output_sha256"]
                != normalized["output"]["sha256"]
                or persisted_qa["measurement"] != measured_qa
                or normalized["audio_qa"] != measured_qa
                or measured_qa["passed"] is not True):
            _fail("music output failed independent measured audio QA")
        tool_by_name = {item["name"]: item for item in render_receipt["runtime_tools"]}
        for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
            if (tool_by_name.get(name, {}).get("sha256") != _sha256_file(path)
                    or tool_by_name.get(name, {}).get("bytes")
                    != path.stat().st_size):
                _fail("music QA runtime differs from the bound render runtime")
        return {
            "ok": True, "mode": mode, "region_count": region_count,
            "policy_usage": policy_usage, "policy_bound": True,
            "rights_verified": True, "dialogue_masking_verified": True,
            "loudness_verified": True,
            "receipt_sha256": music_production_receipt_sha256(normalized),
            "output_sha256": normalized["output"]["sha256"], "note": "",
        }
    except Exception as error:
        return {
            "ok": False, "mode": mode, "region_count": region_count,
            "policy_usage": policy_usage, "policy_bound": False,
            "rights_verified": False, "dialogue_masking_verified": False,
            "loudness_verified": False, "receipt_sha256": None,
            "output_sha256": None,
            "note": (
                f"typed music evidence failed: {type(error).__name__}: {error}"
            ),
        }


def execute_project_intent_music(
    *,
    program_path: str,
    project_intent_envelope: object,
    project_intent_envelope_sha256: str,
    speech_words: object,
    work_dir: str,
    evidence_dir: str,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> dict[str, Any]:
    """Produce one governed project-owned music region or prove a no-op.

    The returned output never overwrites ``program_path``.  There is no input
    for legacy/user/external music bytes by design.  A caller may replace its
    private base master only after reopening the persisted receipt and running
    :func:`verify_music_production_evidence` successfully.
    """
    program = _absolute_file(program_path, "typed music program")
    ffmpeg = _absolute_file(ffmpeg_path, "typed music FFmpeg")
    ffprobe = _absolute_file(ffprobe_path, "typed music FFprobe")
    parent_work = _absolute_dir(work_dir, "typed music work directory")
    evidence_root = _absolute_dir(
        evidence_dir, "typed music evidence directory")
    try:
        envelope = validate_project_intent_engine_envelope(
            project_intent_envelope)
    except Exception as error:
        raise MusicProductionError(
            "ProjectIntent engine envelope is invalid") from error
    expected_envelope_hash = _digest(
        project_intent_envelope_sha256,
        "ProjectIntent engine envelope digest")
    measured_envelope_hash = project_intent_engine_envelope_sha256(envelope)
    if (measured_envelope_hash != expected_envelope_hash
            or hashlib.sha256(
                canonical_project_intent_engine_envelope_bytes(envelope)
            ).hexdigest() != expected_envelope_hash):
        _fail("ProjectIntent engine envelope digest does not match")

    private = parent_work / "typed-music-production"
    try:
        private.mkdir(mode=0o700)
    except FileExistsError as error:
        raise MusicProductionError(
            "private typed music directory already exists") from error
    except OSError as error:
        raise MusicProductionError(
            "private typed music directory is unavailable") from error

    program_binding = _probe_media(
        program, ffprobe, private, "typed music program")
    target = copy.deepcopy(envelope["project_intent"]["target_duration"])
    execution_policy = specialize_music_edit_policy_for_program(
        envelope["edit_policy"], target_duration=target,
        actual_duration_ms=program_binding["duration_ms"],
    )
    parent_policy_hash = edit_policy_sha256(envelope["edit_policy"])
    execution_policy_hash = edit_policy_sha256(execution_policy)
    if parent_policy_hash != envelope["edit_policy_sha256"]:
        _fail("ProjectIntent parent edit policy digest changed")
    preference = envelope["project_intent"]["preferences"]["music"][
        "preference"]
    rule = execution_policy["rules"]["music"]
    available = set(envelope["capability_manifest"]["available_capabilities"])
    if preference == "none":
        if rule["usage"] != "forbidden":
            _fail("disabled typed music preference resolved to added music")
    elif preference in {"primary", "source_primary"}:
        _fail("requested typed music mode is unsupported and remains fail-closed")
    elif preference == "supporting":
        if rule["usage"] != "supporting":
            _fail("supporting typed music preference changed in policy resolution")
    elif preference == "auto":
        if rule["usage"] not in {"optional", "supporting"}:
            _fail("auto typed music resolved to an unsupported production mode")
    else:
        _fail("requested typed music preference is unsupported")
    if preference != "none" and "project_generated_music" not in available:
        _fail("project-generated music capability is absent from authority")
    if preference != "none" and "licensed_music" in (
            set(execution_policy["required_capabilities"])):
        _fail("typed project-generated music cannot satisfy licensed_music")

    timeline_hash = derive_music_output_timeline_sha256(
        program_sha256=program_binding["sha256"],
        program_bytes=program_binding["bytes"],
        duration_ms=program_binding["duration_ms"],
    )
    execution_policy_path = _write_json(
        private / "MUSIC_EXECUTION_EDIT_POLICY.json", execution_policy,
        "music execution edit policy")

    def persist_noop(
        mode: str,
        extra_sidecars: list[Path],
    ) -> dict[str, Any]:
        persisted = _persist_sidecars(
            [execution_policy_path, *extra_sidecars], evidence_root)
        receipt = validate_music_production_receipt({
            "schema_version": MUSIC_PRODUCTION_RECEIPT_SCHEMA_VERSION,
            "mode": mode, "authorization_id": envelope["authorization_id"],
            "capability_used": (
                None if mode == "no_music_requested"
                else "project_generated_music"),
            "engine_envelope_sha256": expected_envelope_hash,
            "project_intent_sha256": envelope["project_intent_sha256"],
            "parent_edit_policy_sha256": parent_policy_hash,
            "execution_edit_policy_sha256": execution_policy_hash,
            "target_duration": target,
            "actual_duration_ms": program_binding["duration_ms"],
            "duration_band": execution_policy["duration"]["band"],
            "requested_preference": preference,
            "policy": copy.deepcopy(rule),
            "region_count": 0, "added_coverage_ms": 0,
            "output_timeline_sha256": timeline_hash,
            "program_input": program_binding, "output": program_binding,
            "rights": {
                "basis": None, "generator": None,
                "external_service_used": False,
            },
            "audio_qa": None,
            "music_asset_manifest_sha256": None,
            "music_plan_sha256": None,
            "music_compile_receipt_sha256": None,
            "music_render_receipt_sha256": None,
            "sidecars": sorted(
                (_sidecar_binding(path) for path in persisted),
                key=lambda item: item["file"]),
        })
        receipt_path = _write_json(
            evidence_root / "MUSIC_PRODUCTION_RECEIPT.json", receipt,
            "music production receipt")
        return {
            "executed": False, "output_path": str(program),
            "receipt": receipt, "receipt_path": str(receipt_path),
            "receipt_sha256": music_production_receipt_sha256(receipt),
            "sidecar_paths": [str(path) for path in persisted],
        }

    if preference == "none":
        return persist_noop("no_music_requested", [])

    source_analysis = _analyze_program_audio(
        program, ffmpeg=ffmpeg, cwd=private,
        program_binding=program_binding)
    source_path = _write_json(
        private / "MUSIC_SOURCE_ANALYSIS.json", source_analysis,
        "music source analysis")
    source_digest = _sha256_file(source_path)
    source_regions = _source_regions_from_analysis(
        source_analysis, evidence_sha256=source_digest,
        duration_ms=program_binding["duration_ms"])
    speech_evidence, dialogue_windows = _speech_evidence(
        speech_words, program_binding["duration_ms"])
    speech_path = _write_json(
        private / "MUSIC_SPEECH_EVIDENCE.json", speech_evidence,
        "music speech evidence")
    speech_digest = _sha256_file(speech_path)
    if any(item["evidence_sha256"] != speech_digest
           for item in dialogue_windows):
        _fail("typed music speech evidence digest changed")
    limits = derive_music_policy_limits(
        execution_policy, program_binding["duration_ms"])
    if limits["max_region_count"] < 1 or limits["max_added_track_count"] < 1:
        _fail("resolved typed music policy permits no project-generated region")
    maximum_region = min(limits["max_added_coverage_ms"], _MAX_REGION_MS)
    placement = _safe_gap(
        source_regions=source_regions,
        dialogue_windows=dialogue_windows,
        duration_ms=program_binding["duration_ms"],
        maximum_ms=maximum_region,
    )
    if placement is None:
        if preference != "auto":
            _fail("requested supporting music has no decoded-safe placement gap")
        return persist_noop("no_safe_gap", [source_path, speech_path])
    start_ms, region_duration_ms = placement
    asset_path, asset, generation_path = _generate_bed(
        region_duration_ms, private)
    manifest = {
        "schema_version": MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": timeline_hash,
        "output_duration_ms": program_binding["duration_ms"],
        "output_sample_rate_hz": _SAMPLE_RATE,
        "output_channels": _CHANNELS,
        "transcript_sha256": speech_digest,
        "source_music": {
            "status": "present" if source_regions else "absent",
            "evidence_sha256": source_digest,
            "exclusion_authorization_sha256": None,
            "regions": source_regions,
        },
        "assets": [asset], "beat_grids": [],
        "dialogue_windows": dialogue_windows,
    }
    manifest = validate_music_asset_manifest(manifest)
    manifest_hash = music_asset_manifest_sha256(manifest)
    fade_ms = min(120, region_duration_ms // 4)
    region_payload = {
        "track_index": 0, "asset_id": asset["asset_id"],
        "asset_sha256": asset["sha256"], "start_ms": start_ms,
        "duration_ms": region_duration_ms, "trim_start_ms": 0,
        "playback_mode": "once", "loop_length_ms": 0,
        "loop_crossfade_ms": 0,
        "gain_millidb": min(-12_000, limits["max_gain_millidb"]),
        "fade_in_ms": fade_ms, "fade_out_ms": fade_ms,
        "crossfade_in_ms": 0, "crossfade_out_ms": 0,
        "beat_sync": None, "dialogue_ducking": None,
    }
    region = {
        "region_id": derive_music_region_id(region_payload), **region_payload,
    }
    plan = {
        "schema_version": MUSIC_PLAN_SCHEMA_VERSION,
        "music_asset_manifest_sha256": manifest_hash,
        "edit_policy_sha256": execution_policy_hash,
        "output_timeline_sha256": timeline_hash,
        "output_duration_ms": program_binding["duration_ms"],
        "policy": limits,
        "mastering": derive_music_mastering(execution_policy),
        "source_music_action": "preserve" if source_regions else "none",
        "regions": [region],
    }
    plan = validate_music_plan(plan, manifest, execution_policy)
    plan_hash = music_plan_sha256(plan)
    compiled = compile_music_plan(plan, manifest, execution_policy)
    manifest_path = _write_json(
        private / "MUSIC_ASSET_MANIFEST.json", manifest,
        "music asset manifest")
    plan_path = _write_json(
        private / "MUSIC_PLAN.json", plan, "music plan")
    compile_path = _write_json(
        private / "MUSIC_COMPILE_RECEIPT.json", compiled["receipt"],
        "music compile receipt")
    render_result = execute_music_render(
        program_path=str(program),
        output_path=str(private / "strict-music-output.mp4"),
        plan=plan, asset_manifest=manifest, edit_policy=execution_policy,
        asset_paths={asset["asset_id"]: str(asset_path)},
        evidence_paths={
            source_digest: str(source_path),
            asset["license"]["evidence_sha256"]: str(generation_path),
        },
        work_dir=str(private), ffmpeg_path=str(ffmpeg),
        ffprobe_path=str(ffprobe),
    )
    if (render_result["compile_receipt"] != compiled["receipt"]
            or render_result["compile_receipt_sha256"]
            != music_compile_receipt_sha256(compiled["receipt"])):
        _fail("music executor recompiled a different region program")
    render_path = _write_json(
        private / "MUSIC_RENDER_RECEIPT.json", render_result["receipt"],
        "music render receipt")
    output = _absolute_file(render_result["output_path"], "typed music output")
    output_binding = _probe_media(
        output, ffprobe, private, "typed music output")
    audio_qa = _measure_audio_qa(
        output, ffmpeg=ffmpeg, cwd=private,
        target=derive_music_mastering(execution_policy))
    if audio_qa["passed"] is not True:
        _fail("typed music output missed measured loudness or true-peak policy")
    audio_qa_path = _write_json(
        private / "MUSIC_AUDIO_QA.json", {
            "schema_version": MUSIC_AUDIO_QA_SCHEMA_VERSION,
            "output_sha256": output_binding["sha256"],
            "measurement": audio_qa,
        }, "music audio QA evidence")
    source_sidecars = [
        execution_policy_path, source_path, speech_path, generation_path,
        asset_path, manifest_path, plan_path, compile_path, render_path,
        audio_qa_path,
    ]
    persisted = _persist_sidecars(source_sidecars, evidence_root)
    receipt = validate_music_production_receipt({
        "schema_version": MUSIC_PRODUCTION_RECEIPT_SCHEMA_VERSION,
        "mode": "rendered", "authorization_id": envelope["authorization_id"],
        "capability_used": "project_generated_music",
        "engine_envelope_sha256": expected_envelope_hash,
        "project_intent_sha256": envelope["project_intent_sha256"],
        "parent_edit_policy_sha256": parent_policy_hash,
        "execution_edit_policy_sha256": execution_policy_hash,
        "target_duration": target,
        "actual_duration_ms": program_binding["duration_ms"],
        "duration_band": execution_policy["duration"]["band"],
        "requested_preference": preference,
        "policy": copy.deepcopy(rule),
        "region_count": 1, "added_coverage_ms": region_duration_ms,
        "output_timeline_sha256": timeline_hash,
        "program_input": program_binding, "output": output_binding,
        "rights": {
            "basis": "project_owned",
            "generator": "autoeditor-deterministic-musical-pcm/v1",
            "external_service_used": False,
        },
        "audio_qa": audio_qa,
        "music_asset_manifest_sha256": manifest_hash,
        "music_plan_sha256": plan_hash,
        "music_compile_receipt_sha256": (
            render_result["compile_receipt_sha256"]),
        "music_render_receipt_sha256": render_result["receipt_sha256"],
        "sidecars": sorted(
            (_sidecar_binding(path) for path in persisted),
            key=lambda item: item["file"]),
    })
    receipt_path = _write_json(
        evidence_root / "MUSIC_PRODUCTION_RECEIPT.json", receipt,
        "music production receipt")
    if (music_render_receipt_sha256(render_result["receipt"])
            != receipt["music_render_receipt_sha256"]):
        _fail("persisted music render receipt digest changed")
    return {
        "executed": True, "output_path": str(output),
        "receipt": receipt, "receipt_path": str(receipt_path),
        "receipt_sha256": music_production_receipt_sha256(receipt),
        "sidecar_paths": [str(path) for path in persisted],
        "render_receipt": render_result["receipt"],
        "compile_receipt": render_result["compile_receipt"],
        "manifest": manifest, "plan": plan,
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
        raise MusicProductionError(f"{label} could not be persisted")


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
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MusicProductionError(
            "decoded music placement check could not complete") from error
    if result.returncode != 0 or not result.stdout or len(result.stdout) > 8_000_000:
        detail = result.stderr.decode("utf-8", errors="replace")[
            -_MAX_CAPTURE_CHARS:
        ].strip()
        raise MusicProductionError(
            "decoded music placement check failed"
            + (f": {detail}" if detail else ""))
    return result.stdout


def _delta_rms_millionths(left: bytes, right: bytes) -> int:
    usable = min(len(left), len(right))
    usable -= usable % 2
    if usable < 2_000:
        _fail("decoded music placement window is too short")
    squares = 0
    count = 0
    for (left_value,), (right_value,) in zip(
            struct.iter_unpack("<h", left[:usable]),
            struct.iter_unpack("<h", right[:usable])):
        difference = right_value - left_value
        squares += difference * difference
        count += 1
    return round(math.sqrt(squares / count) / 32768 * 1_000_000)


def _tone_amplitude_millionths(pcm: bytes, frequency_hz: float) -> int:
    usable = len(pcm) - len(pcm) % 4
    if usable < 4_000:
        _fail("decoded music tone window is too short")
    samples = [item[0] / 32768 for item in struct.iter_unpack("<hh", pcm[:usable])]
    step = 2.0 * math.pi * frequency_hz / _SAMPLE_RATE
    cosine = sum(value * math.cos(step * index)
                 for index, value in enumerate(samples))
    sine = sum(value * math.sin(step * index)
               for index, value in enumerate(samples))
    amplitude = 2.0 * math.hypot(cosine, sine) / len(samples)
    return round(amplitude * 1_000_000)


def _decoded_music_evidence(
    *,
    source: Path,
    output: Path,
    ffmpeg: Path,
    plan: dict,
    dialogue_start_ms: int,
    dialogue_end_ms: int,
    cwd: Path,
) -> dict[str, int]:
    regions = plan.get("regions")
    if type(regions) is not list or len(regions) != 1:
        _fail("fixed music probe did not produce exactly one region")
    region = regions[0]
    start_ms = region["start_ms"]
    end_ms = start_ms + region["duration_ms"]
    sample_duration = min(500, region["duration_ms"] - 160)
    if sample_duration < 300:
        _fail("fixed music probe region is too short for decoded evidence")
    bed_start = start_ms + 80
    dialogue_duration = min(500, dialogue_end_ms - dialogue_start_ms)
    dialogue_start = dialogue_start_ms + max(
        0, (dialogue_end_ms - dialogue_start_ms - dialogue_duration) // 2)
    source_bed = _run_audio_decode(
        ffmpeg, source, start_ms=bed_start,
        duration_ms=sample_duration, cwd=cwd)
    output_bed = _run_audio_decode(
        ffmpeg, output, start_ms=bed_start,
        duration_ms=sample_duration, cwd=cwd)
    source_dialogue = _run_audio_decode(
        ffmpeg, source, start_ms=dialogue_start,
        duration_ms=dialogue_duration, cwd=cwd)
    output_dialogue = _run_audio_decode(
        ffmpeg, output, start_ms=dialogue_start,
        duration_ms=dialogue_duration, cwd=cwd)
    bed_delta = _delta_rms_millionths(source_bed, output_bed)
    dialogue_delta = _delta_rms_millionths(source_dialogue, output_dialogue)
    bed_tone = _tone_amplitude_millionths(output_bed, 130.813)
    dialogue_tone = _tone_amplitude_millionths(output_dialogue, 130.813)
    if bed_delta < 500 or bed_tone < max(100, dialogue_tone * 8 + 25):
        _fail(
            "decoded output did not prove music placement/dialogue masking "
            f"(bed_delta={bed_delta}, bed_tone={bed_tone}, "
            f"dialogue_tone={dialogue_tone})")
    if not (end_ms <= dialogue_start_ms or start_ms >= dialogue_end_ms):
        _fail("fixed music region overlaps its exact dialogue window")
    return {
        "expected_start_ms": start_ms, "expected_end_ms": end_ms,
        "bed_window_start_ms": bed_start,
        "bed_window_duration_ms": sample_duration,
        "dialogue_window_start_ms": dialogue_start,
        "dialogue_window_duration_ms": dialogue_duration,
        "bed_delta_rms_millionths": bed_delta,
        "dialogue_delta_rms_millionths": dialogue_delta,
        "bed_music_tone_millionths": bed_tone,
        "dialogue_music_tone_millionths": dialogue_tone,
    }


def _fixed_music_probe_authority() -> dict[str, Any]:
    preferences = {
        "captions": "none", "graphics": "none", "music": "supporting",
        "sfx": "none", "transitions": "none",
    }
    project = {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": "dialogue_talking_head",
        "delivery": {"platform": "youtube", "aspect": "16:9"},
        "target_duration": {"min_ms": 3_800, "max_ms": 4_200},
        "preferences": {
            name: {"enabled": value != "none", "preference": value}
            for name, value in preferences.items()
        },
    }
    # Never include licensed_music/source preservation in this fixed local
    # precondition.  The live capability becomes available only after this
    # full producer/verifier probe passes.
    capabilities = set(CAPABILITIES) - {
        "licensed_music", "licensed_sfx", "source_music_preservation",
    }
    manifest = {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": _sha256_bytes(
            b"autoeditor-fixed-project-generated-music-probe/v1"),
        "available_capabilities": sorted(capabilities),
    }
    policy = resolve_project_intent_policy(project, manifest)
    project_hash = _sha256_bytes(
        _canonical_json(project, "fixed music project").encode("ascii"))
    manifest_hash = _sha256_bytes(
        _canonical_json(manifest, "fixed music manifest").encode("ascii"))
    proposal = {
        "schema_version": "autoeditor-fixed-music-probe-proposal/v1",
        "project_intent_sha256": project_hash,
    }
    authority = {
        "schema_version": "autoeditor-project-intent-authority/v2",
        "authorization_id": _sha256_bytes(
            b"autoeditor-fixed-project-generated-music-authorization/v1")[:32],
        "approved_proposal_sha256": _sha256_bytes(
            _canonical_json(proposal, "fixed music proposal").encode("ascii")),
        "project_intent": project, "project_intent_sha256": project_hash,
        "edit_policy": policy, "edit_policy_sha256": edit_policy_sha256(policy),
        "capability_manifest": manifest,
        "capability_manifest_sha256": manifest_hash,
        "authorization_hmac_sha256": _sha256_bytes(
            b"fixed-local-self-test-hmac-not-a-live-authorization"),
    }
    return build_project_intent_engine_envelope(authority)


def write_music_production_probe(
    source_path: str,
    output_path: str,
    work_dir: str,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> dict[str, Any]:
    """Execute the fixed real-media project-generated music capability probe."""
    source = _absolute_file(source_path, "fixed music probe source")
    root = _absolute_dir(work_dir, "fixed music probe work directory")
    ffmpeg = _absolute_file(ffmpeg_path, "fixed music probe FFmpeg")
    ffprobe = _absolute_file(ffprobe_path, "fixed music probe FFprobe")
    if type(output_path) is not str or not output_path or "\x00" in output_path:
        _fail("fixed music probe output path is invalid")
    output = Path(os.path.realpath(Path(output_path)))
    if (not output.is_absolute() or output.suffix.lower() != ".mp4"
            or Path(os.path.realpath(output.parent)) != root
            or output.exists() or output == source):
        _fail("fixed music probe output must be a new MP4 inside its work directory")
    private = root / "MUSIC_PRODUCTION_SELF_TEST"
    try:
        private.mkdir(mode=0o700)
        producer_work = private / "work"
        evidence_root = private / "evidence"
        producer_work.mkdir(mode=0o700)
        evidence_root.mkdir(mode=0o700)
    except (OSError, FileExistsError) as error:
        raise MusicProductionError(
            "fixed music probe private directory is unavailable") from error

    envelope = _fixed_music_probe_authority()
    envelope_hash = project_intent_engine_envelope_sha256(envelope)
    speech_words = [
        {"w": "fixed", "s": 1.45, "e": 1.85},
        {"w": "dialogue", "s": 1.90, "e": 2.30},
        {"w": "window", "s": 2.35, "e": 2.55},
    ]
    result = execute_project_intent_music(
        program_path=str(source), project_intent_envelope=envelope,
        project_intent_envelope_sha256=envelope_hash,
        speech_words=speech_words, work_dir=str(producer_work),
        evidence_dir=str(evidence_root), ffmpeg_path=str(ffmpeg),
        ffprobe_path=str(ffprobe),
    )
    if not result.get("executed"):
        _fail("fixed music probe did not execute the production renderer")
    _copy_file_exclusive(
        _absolute_file(result["output_path"], "fixed music private output"),
        output, "fixed music probe output")
    receipt_path = _absolute_file(
        result["receipt_path"], "fixed music production receipt")
    persisted_receipt = validate_music_production_receipt(
        _load_json_sidecar(receipt_path, "fixed music production receipt"))
    if persisted_receipt != result["receipt"]:
        _fail("fixed music production receipt changed after persistence")
    if (persisted_receipt["mode"] != "rendered"
            or persisted_receipt["region_count"] != 1
            or persisted_receipt["requested_preference"] != "supporting"
            or persisted_receipt["policy"]["usage"] != "supporting"
            or persisted_receipt["rights"]["basis"] != "project_owned"
            or persisted_receipt["rights"]["external_service_used"] is not False
            or persisted_receipt["program_input"]["sha256"]
            == persisted_receipt["output"]["sha256"]
            or _sha256_file(output) != persisted_receipt["output"]["sha256"]):
        _fail("fixed music production output bindings are invalid")
    qa = verify_music_production_evidence(
        persisted_receipt, program_input_path=str(source),
        output_path=str(output), evidence_dir=str(evidence_root),
        expected_engine_envelope_sha256=envelope_hash,
        expected_project_intent_sha256=envelope["project_intent_sha256"],
        expected_parent_edit_policy_sha256=envelope["edit_policy_sha256"],
        ffmpeg_path=str(ffmpeg), ffprobe_path=str(ffprobe),
    )
    if (qa.get("ok") is not True or qa.get("policy_bound") is not True
            or qa.get("rights_verified") is not True
            or qa.get("dialogue_masking_verified") is not True
            or qa.get("loudness_verified") is not True):
        _fail("fixed music production failed independent verification")
    sidecars = {
        item["file"]: (
            None if item["file"].endswith(".wav") else _load_json_sidecar(
                evidence_root / item["file"], f"fixed music {item['file']}"))
        for item in persisted_receipt["sidecars"]
    }
    manifest = validate_music_asset_manifest(
        sidecars["MUSIC_ASSET_MANIFEST.json"])
    plan = validate_music_plan(
        sidecars["MUSIC_PLAN.json"], manifest,
        sidecars["MUSIC_EXECUTION_EDIT_POLICY.json"])
    generation = sidecars["MUSIC_GENERATION_EVIDENCE.json"]
    _verify_generation_evidence(
        generation, asset=manifest["assets"][0],
        asset_path=evidence_root / "MUSIC_PROJECT_BED.wav")
    placement = _decoded_music_evidence(
        source=source, output=output, ffmpeg=ffmpeg, plan=plan,
        dialogue_start_ms=1_450, dialogue_end_ms=2_550, cwd=private)

    tamper_root = private / "rights-tamper-negative"
    tamper_root.mkdir(mode=0o700)
    for binding in persisted_receipt["sidecars"]:
        _copy_file_exclusive(
            evidence_root / binding["file"], tamper_root / binding["file"],
            "fixed music tamper fixture")
    tampered_generation = copy.deepcopy(generation)
    tampered_generation["rights"]["external_service_used"] = True
    replacement = _write_json(
        tamper_root / "RIGHTS_TAMPER_TMP.json", tampered_generation,
        "fixed music rights tamper")
    try:
        os.replace(replacement, tamper_root / "MUSIC_GENERATION_EVIDENCE.json")
    except OSError as error:
        raise MusicProductionError(
            "fixed music rights tamper fixture could not be rebound") from error
    tampered_receipt = copy.deepcopy(persisted_receipt)
    for binding in tampered_receipt["sidecars"]:
        if binding["file"] == "MUSIC_GENERATION_EVIDENCE.json":
            path = tamper_root / binding["file"]
            binding["sha256"] = _sha256_file(path)
            binding["bytes"] = path.stat().st_size
    tamper_qa = verify_music_production_evidence(
        tampered_receipt, program_input_path=str(source), output_path=str(output),
        evidence_dir=str(tamper_root),
        expected_engine_envelope_sha256=envelope_hash,
        expected_project_intent_sha256=envelope["project_intent_sha256"],
        expected_parent_edit_policy_sha256=envelope["edit_policy_sha256"],
        ffmpeg_path=str(ffmpeg), ffprobe_path=str(ffprobe))
    if tamper_qa.get("ok") is not False:
        _fail("fixed music probe did not reject rebound rights tampering")

    omission_root = private / "omission-negative"
    omission_root.mkdir(mode=0o700)
    for binding in persisted_receipt["sidecars"]:
        if binding["file"] != "MUSIC_PLAN.json":
            _copy_file_exclusive(
                evidence_root / binding["file"], omission_root / binding["file"],
                "fixed music omission fixture")
    omission_qa = verify_music_production_evidence(
        persisted_receipt, program_input_path=str(source), output_path=str(output),
        evidence_dir=str(omission_root),
        expected_engine_envelope_sha256=envelope_hash,
        expected_project_intent_sha256=envelope["project_intent_sha256"],
        expected_parent_edit_policy_sha256=envelope["edit_policy_sha256"],
        ffmpeg_path=str(ffmpeg), ffprobe_path=str(ffprobe))
    if omission_qa.get("ok") is not False:
        _fail("fixed music probe did not reject evidence omission")

    receipt_file = {
        "file": receipt_path.name, "sha256": _sha256_file(receipt_path),
        "bytes": receipt_path.stat().st_size,
        "contract_sha256": music_production_receipt_sha256(persisted_receipt),
    }
    checks = {
        "decoded_music_placement": True,
        "dialogue_masking": True,
        "independent_evidence_verifier": True,
        "measured_loudness": True,
        "omission_rejected": True,
        "production_music_planner": True,
        "production_music_renderer": True,
        "project_generated_rights": True,
        "tamper_rejected": True,
    }
    return {
        "schema_version": MUSIC_PRODUCTION_SELF_TEST_SCHEMA_VERSION,
        "checks": checks,
        "artifact": {
            "file": output.name, "sha256": persisted_receipt["output"]["sha256"],
            "bytes": persisted_receipt["output"]["bytes"],
            "duration_ms": persisted_receipt["output"]["duration_ms"],
        },
        "production_receipt": receipt_file,
        "decoded_placement": placement,
        "measured_audio": copy.deepcopy(persisted_receipt["audio_qa"]),
        "evidence": {
            "sidecar_count": len(persisted_receipt["sidecars"]),
            "generation_sidecar_count": 1,
            "rights_basis": "project_owned",
            "external_service_used": False,
        },
    }


__all__ = [
    "MUSIC_PRODUCTION_RECEIPT_SCHEMA_VERSION",
    "MUSIC_PRODUCTION_SELF_TEST_SCHEMA_VERSION",
    "MusicProductionError",
    "canonical_music_production_receipt_json",
    "execute_project_intent_music",
    "music_production_receipt_sha256",
    "specialize_music_edit_policy_for_program",
    "validate_music_production_receipt",
    "verify_music_production_evidence",
    "write_music_production_probe",
]
