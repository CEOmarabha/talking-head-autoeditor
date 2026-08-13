"""Offline end-to-end proof for transcript-driven dialogue cleanup.

The probe turns the public fixed audio exposed by
``autoeditor.asr_runtime_probe`` into a normalized 30 fps H.264 / 48 kHz
stereo program containing the same spoken take twice.  It then crosses the
production boundaries used by the editor:

* bundled small-model word-timestamp ASR before and after the edit;
* ``pipeline.detect_retakes`` and ``pipeline.detect_false_starts``;
* ``pipeline.apply_cuts`` for frame/sample-aligned A/V rendering; and
* ``pipeline.verify_no_retakes`` on the rendered artifact.

This is deliberately a narrow capability proof.  It certifies repeated-take
and false-start cleanup mechanics on fixed fixtures.  It does not certify
cough classification, dead-air policy quality, arbitrary semantic repair, or
general ASR accuracy.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import unicodedata
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from .asr_runtime_probe import (
    ASR_RUNTIME_PROBE_FIXTURE_BYTES,
    ASR_RUNTIME_PROBE_FIXTURE_NAME,
    ASR_RUNTIME_PROBE_FIXTURE_SHA256,
    ASR_RUNTIME_PROBE_SOURCE_REVISION,
    asr_runtime_probe_fixture_bytes,
)


DIALOGUE_CLEANUP_RUNTIME_PROBE_SCHEMA_VERSION = (
    "autoeditor-dialogue-cleanup-runtime-probe/v1"
)
DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE = (
    "DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT.json"
)
DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE = "dialogue-cleanup-source.mp4"
DIALOGUE_CLEANUP_RUNTIME_PROBE_EDITED_FILE = "retakes_cut0.mp4"
DIALOGUE_CLEANUP_RUNTIME_PROBE_FILTER_FILE = "dialogue-cleanup-filter.txt"
DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE = (
    "and", "so", "my", "fellow", "americans",
)
DIALOGUE_CLEANUP_RUNTIME_PROBE_PAUSE_MS = 500
DIALOGUE_CLEANUP_RUNTIME_PROBE_DURATION_MS = 5_500
DIALOGUE_CLEANUP_RUNTIME_PROBE_WIDTH = 320
DIALOGUE_CLEANUP_RUNTIME_PROBE_HEIGHT = 180
DIALOGUE_CLEANUP_RUNTIME_PROBE_FPS = 30
DIALOGUE_CLEANUP_RUNTIME_PROBE_SAMPLE_RATE = 48_000
DIALOGUE_CLEANUP_RUNTIME_PROBE_CHANNELS = 2
DIALOGUE_CLEANUP_RUNTIME_PROBE_MAX_MODEL_FILES = 64
DIALOGUE_CLEANUP_RUNTIME_PROBE_MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024

_FILTER_GRAPH = (
    "[0:a:0]atrim=start=0:end=2.5,aresample=48000,"
    "aformat=sample_fmts=fltp:channel_layouts=stereo,"
    "asetpts=PTS-STARTPTS,asplit=2[take0][take1];"
    "anullsrc=r=48000:cl=stereo:d=0.5[pause];"
    "[take0][pause][take1]concat=n=3:v=0:a=1[aout]\n"
).encode("ascii")

_FALSE_START_WORDS = (
    {"w": "We", "s": 0.20, "e": 0.40, "p": 0.99},
    {"w": "need", "s": 0.40, "e": 0.70, "p": 0.99},
    {"w": "clear.", "s": 0.70, "e": 1.00, "p": 0.99},
    {"w": "We", "s": 1.30, "e": 1.50, "p": 0.99},
    {"w": "need", "s": 1.50, "e": 1.80, "p": 0.99},
    {"w": "clarity.", "s": 1.80, "e": 2.20, "p": 0.99},
)


class DialogueCleanupRuntimeProbeError(ValueError):
    """The fixed dialogue-cleanup proof could not be produced safely."""


def _fail(message: str) -> None:
    raise DialogueCleanupRuntimeProbeError(message)


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
        raise DialogueCleanupRuntimeProbeError(
            "dialogue-cleanup receipt is not canonical JSON"
        ) from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_path(value: str | os.PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _fail(f"{label} path is invalid")
    text = os.fspath(value)
    if not text or "\x00" in text:
        _fail(f"{label} path is invalid")
    raw = Path(text)
    if not raw.is_absolute():
        _fail(f"{label} must be absolute")
    return raw


def _existing_file(value: str | os.PathLike[str], label: str) -> Path:
    raw = _raw_path(value, label)
    if raw.is_symlink() or not raw.is_file():
        _fail(f"{label} is unavailable")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as error:
        raise DialogueCleanupRuntimeProbeError(f"{label} is unavailable") from error
    if resolved.is_symlink() or not resolved.is_file():
        _fail(f"{label} is unavailable")
    return resolved


def _existing_dir(value: str | os.PathLike[str], label: str) -> Path:
    raw = _raw_path(value, label)
    if raw.is_symlink() or not raw.is_dir():
        _fail(f"{label} is unavailable")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as error:
        raise DialogueCleanupRuntimeProbeError(f"{label} is unavailable") from error
    if resolved.is_symlink() or not resolved.is_dir():
        _fail(f"{label} is unavailable")
    return resolved


def _new_receipt_path(
    value: str | os.PathLike[str], root: Path,
) -> Path:
    raw = _raw_path(value, "dialogue-cleanup receipt")
    try:
        parent = raw.parent.resolve(strict=True)
    except OSError as error:
        raise DialogueCleanupRuntimeProbeError(
            "dialogue-cleanup receipt parent is unavailable"
        ) from error
    if (
        parent != root
        or raw.name != DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE
        or raw.exists()
        or raw.is_symlink()
    ):
        _fail(
            "dialogue-cleanup receipt must be a new fixed file inside its "
            "work directory"
        )
    return raw


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
                raise OSError("short dialogue-cleanup probe write")
            written += count
        os.fsync(descriptor)
        os.chmod(path, 0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def _file_identity(path: Path) -> dict[str, Any]:
    before = path.stat()
    if before.st_size < 1:
        _fail("dialogue-cleanup runtime file is empty")
    digest = _sha256_file(path)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
    ):
        _fail("dialogue-cleanup runtime file changed while measured")
    return {"sha256": digest, "bytes": before.st_size}


def _model_identity(model_path: Path) -> dict[str, Any]:
    files = sorted(
        (
            item
            for item in model_path.iterdir()
            if item.is_file() and not item.is_symlink()
        ),
        key=lambda item: item.name.encode("utf-8"),
    )
    if (
        not files
        or len(files) > DIALOGUE_CLEANUP_RUNTIME_PROBE_MAX_MODEL_FILES
        or not any(item.name == "model.bin" for item in files)
    ):
        _fail("small ASR model inventory is invalid")
    digest = hashlib.sha256()
    total = 0
    for item in files:
        if (
            item.name in {".", ".."}
            or "/" in item.name
            or "\\" in item.name
            or "\x00" in item.name
        ):
            _fail("small ASR model inventory is invalid")
        identity = _file_identity(item)
        total += identity["bytes"]
        if total > DIALOGUE_CLEANUP_RUNTIME_PROBE_MAX_MODEL_BYTES:
            _fail("small ASR model exceeds the bounded probe size")
        digest.update(item.name.encode("utf-8") + b"\0")
        digest.update(str(identity["bytes"]).encode("ascii") + b"\0")
        digest.update(identity["sha256"].encode("ascii") + b"\n")
    return {
        "name": "faster-whisper-small",
        "tree_sha256": digest.hexdigest(),
        "bytes": total,
        "files": len(files),
    }


def _default_execute(command: list[str], **kwargs: object):
    if os.name == "nt":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(command, **kwargs)


def _run_checked(
    command: list[str],
    *,
    execute: Callable[..., object],
    timeout: int,
    label: str,
) -> object:
    try:
        result = execute(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DialogueCleanupRuntimeProbeError(
            f"{label} execution failed: {type(error).__name__}"
        ) from error
    returncode = getattr(result, "returncode", None)
    if not isinstance(returncode, int) or returncode != 0:
        _fail(f"{label} execution failed")
    return result


def _result_stdout(result: object, label: str) -> bytes:
    value = getattr(result, "stdout", b"")
    if isinstance(value, str):
        return value.encode("utf-8")
    if not isinstance(value, (bytes, bytearray)):
        _fail(f"{label} returned invalid output")
    return bytes(value)


def _fraction(value: object, label: str) -> Fraction:
    if not isinstance(value, str) or not value or len(value) > 32:
        _fail(f"{label} is invalid")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise DialogueCleanupRuntimeProbeError(f"{label} is invalid") from error
    if result <= 0:
        _fail(f"{label} is invalid")
    return result


def _positive_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        _fail(f"{label} is invalid")
    try:
        result = float(value)
    except ValueError as error:
        raise DialogueCleanupRuntimeProbeError(f"{label} is invalid") from error
    if not math.isfinite(result) or result <= 0:
        _fail(f"{label} is invalid")
    return result


def _media_contract(
    path: Path,
    *,
    ffprobe: Path,
    execute: Callable[..., object],
    source: bool,
) -> dict[str, Any]:
    identity_before = _file_identity(path)
    result = _run_checked(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            (
                "stream=codec_name,codec_type,width,height,pix_fmt,"
                "avg_frame_rate,duration,nb_frames,sample_rate,channels"
            ),
            "-of",
            "json",
            str(path),
        ],
        execute=execute,
        timeout=30,
        label="dialogue-cleanup FFprobe",
    )
    try:
        payload = json.loads(_result_stdout(result, "FFprobe").decode("utf-8"))
        streams = payload["streams"]
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next(item for item in streams if item.get("codec_type") == "audio")
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, StopIteration, TypeError) as error:
        raise DialogueCleanupRuntimeProbeError(
            "dialogue-cleanup media inventory is invalid"
        ) from error
    if not isinstance(streams, list) or len(streams) != 2:
        _fail("dialogue-cleanup media must contain exactly one video and one audio stream")
    video_duration = _positive_float(video.get("duration"), "video duration")
    audio_duration = _positive_float(audio.get("duration"), "audio duration")
    frame_rate = _fraction(video.get("avg_frame_rate"), "video frame rate")
    try:
        frames = int(video.get("nb_frames"))
        width = int(video.get("width"))
        height = int(video.get("height"))
        sample_rate = int(audio.get("sample_rate"))
        channels = int(audio.get("channels"))
    except (TypeError, ValueError) as error:
        raise DialogueCleanupRuntimeProbeError(
            "dialogue-cleanup media stream fields are invalid"
        ) from error
    if (
        video.get("codec_name") != "h264"
        or video.get("pix_fmt") != "yuv420p"
        or width != DIALOGUE_CLEANUP_RUNTIME_PROBE_WIDTH
        or height != DIALOGUE_CLEANUP_RUNTIME_PROBE_HEIGHT
        or frame_rate != DIALOGUE_CLEANUP_RUNTIME_PROBE_FPS
        or frames < 2
        or audio.get("codec_name") != "aac"
        or sample_rate != DIALOGUE_CLEANUP_RUNTIME_PROBE_SAMPLE_RATE
        or channels != DIALOGUE_CLEANUP_RUNTIME_PROBE_CHANNELS
        or abs(video_duration - audio_duration) > 0.034
    ):
        _fail("dialogue-cleanup media normalization contract failed")
    if source and (
        frames != (
            DIALOGUE_CLEANUP_RUNTIME_PROBE_DURATION_MS
            * DIALOGUE_CLEANUP_RUNTIME_PROBE_FPS // 1000
        )
        or abs(video_duration * 1000 - DIALOGUE_CLEANUP_RUNTIME_PROBE_DURATION_MS) > 34
    ):
        _fail("dialogue-cleanup source duration contract failed")
    identity_after = _file_identity(path)
    if identity_before != identity_after:
        _fail("dialogue-cleanup media changed while inspected")
    return {
        **identity_after,
        "video": {
            "codec": "h264",
            "width": width,
            "height": height,
            "pixel_format": "yuv420p",
            "fps": int(frame_rate),
            "frames": frames,
            "duration_ms": round(video_duration * 1000),
        },
        "audio": {
            "codec": "aac",
            "sample_rate": sample_rate,
            "channels": channels,
            "duration_ms": round(audio_duration * 1000),
        },
        "av_duration_drift_ms": abs(
            round((video_duration - audio_duration) * 1000)
        ),
    }


def _word_value(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _normalize_word(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9']+", "", normalized)


def _transcribe_words(
    model: object,
    media: Path,
    *,
    transcribe: Callable[..., object],
    maximum_end_ms: int,
) -> list[dict[str, Any]]:
    try:
        result = transcribe(
            model,
            str(media),
            language="en",
            temperature=0.0,
            beam_size=1,
            best_of=1,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=True,
        )
    except Exception as error:
        raise DialogueCleanupRuntimeProbeError(
            f"dialogue-cleanup ASR failed: {type(error).__name__}"
        ) from error
    if not isinstance(result, tuple) or len(result) != 2:
        _fail("dialogue-cleanup ASR returned an invalid result")
    segments, info = result
    language = _word_value(info, "language")
    if language not in {None, "en"}:
        _fail("dialogue-cleanup ASR did not identify English")
    try:
        segment_items = list(segments)
    except TypeError as error:
        raise DialogueCleanupRuntimeProbeError(
            "dialogue-cleanup ASR segments are invalid"
        ) from error
    words: list[dict[str, Any]] = []
    prior_end_ms = 0
    for segment in segment_items:
        raw_words = _word_value(segment, "words")
        if raw_words is None:
            continue
        try:
            word_items = list(raw_words)
        except TypeError as error:
            raise DialogueCleanupRuntimeProbeError(
                "dialogue-cleanup ASR words are invalid"
            ) from error
        for word in word_items:
            text = _word_value(word, "word")
            start = _word_value(word, "start")
            end = _word_value(word, "end")
            probability = _word_value(word, "probability")
            if (
                not isinstance(text, str)
                or not text.strip()
                or isinstance(start, bool)
                or not isinstance(start, (int, float))
                or isinstance(end, bool)
                or not isinstance(end, (int, float))
                or isinstance(probability, bool)
                or not isinstance(probability, (int, float))
            ):
                _fail("dialogue-cleanup ASR word is invalid")
            start_ms = round(float(start) * 1000)
            end_ms = round(float(end) * 1000)
            probability_millionths = round(float(probability) * 1_000_000)
            if (
                start_ms < prior_end_ms
                or end_ms <= start_ms
                or end_ms > maximum_end_ms + 250
                or not 0 <= probability_millionths <= 1_000_000
            ):
                _fail("dialogue-cleanup ASR word timing is invalid")
            words.append({
                "w": text.strip(),
                "s": start_ms / 1000,
                "e": end_ms / 1000,
                "p": probability_millionths / 1_000_000,
            })
            prior_end_ms = end_ms
    if not words:
        _fail("dialogue-cleanup ASR returned no words")
    return words


def _normalized_words(words: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(_normalize_word(item["w"]) for item in words if _normalize_word(item["w"]))


def _take_indexes(words: list[dict[str, Any]]) -> list[int]:
    normalized = _normalized_words(words)
    take = DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE
    return [
        index
        for index in range(0, len(normalized) - len(take) + 1)
        if normalized[index:index + len(take)] == take
    ]


def _cut_payload(cuts: object, duration_ms: int, label: str) -> list[dict[str, Any]]:
    if not isinstance(cuts, list) or not cuts:
        _fail(f"{label} returned no cut")
    result: list[dict[str, Any]] = []
    for cut in cuts:
        if not isinstance(cut, dict):
            _fail(f"{label} returned an invalid cut")
        start = cut.get("s")
        end = cut.get("e")
        why = cut.get("why")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or not isinstance(why, str)
            or not why
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
        ):
            _fail(f"{label} returned an invalid cut")
        start_ms = round(float(start) * 1000)
        end_ms = round(float(end) * 1000)
        if start_ms < 0 or end_ms <= start_ms or end_ms > duration_ms:
            _fail(f"{label} returned an out-of-range cut")
        result.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "why": why,
        })
    return result


def _word_summary(words: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = _normalized_words(words)
    timing = [
        {
            "word": _normalize_word(item["w"]),
            "start_ms": round(item["s"] * 1000),
            "end_ms": round(item["e"] * 1000),
            "probability_millionths": round(item["p"] * 1_000_000),
        }
        for item in words
    ]
    return {
        "normalized_text": " ".join(normalized),
        "take_count": len(_take_indexes(words)),
        "word_count": len(words),
        "word_timing_sha256": _sha256_bytes(
            _canonical_json(timing).encode("ascii")
        ),
    }


def _fixed_false_start_words() -> list[dict[str, Any]]:
    return [dict(item) for item in _FALSE_START_WORDS]


def _clean_staged_files(paths: list[Path]) -> None:
    errors = []
    for path in reversed(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            errors.append(type(error).__name__)
    if errors:
        _fail("dialogue-cleanup staged-file cleanup failed")


def run_dialogue_cleanup_runtime_probe(
    *,
    output_path: str | os.PathLike[str],
    work_dir: str | os.PathLike[str],
    model_path: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    ffprobe_path: str | os.PathLike[str],
    _create_model: Callable[..., object] | None = None,
    _transcribe: Callable[..., object] | None = None,
    _pipeline_module: object | None = None,
    _execute: Callable[..., object] | None = None,
) -> dict[str, Any]:
    """Run the fixed offline repeated-take cleanup and delivery-gate proof."""
    root = _existing_dir(work_dir, "dialogue-cleanup work directory")
    output = _new_receipt_path(output_path, root)
    ffmpeg = _existing_file(ffmpeg_path, "dialogue-cleanup FFmpeg")
    ffprobe = _existing_file(ffprobe_path, "dialogue-cleanup FFprobe")
    model_root = _existing_dir(model_path, "small ASR model")
    execute = _execute or _default_execute

    fixture = root / ASR_RUNTIME_PROBE_FIXTURE_NAME
    filter_file = root / DIALOGUE_CLEANUP_RUNTIME_PROBE_FILTER_FILE
    source_file = root / DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE
    edited_file = root / DIALOGUE_CLEANUP_RUNTIME_PROBE_EDITED_FILE
    staged = [fixture, filter_file, source_file, edited_file]
    if any(path.exists() or path.is_symlink() for path in staged):
        _fail("dialogue-cleanup work directory contains a reserved probe file")

    fixture_payload = asr_runtime_probe_fixture_bytes()
    if (
        len(fixture_payload) != ASR_RUNTIME_PROBE_FIXTURE_BYTES
        or _sha256_bytes(fixture_payload) != ASR_RUNTIME_PROBE_FIXTURE_SHA256
    ):
        _fail("dialogue-cleanup source fixture identity changed")
    tool_identity_before = {
        "ffmpeg": _file_identity(ffmpeg),
        "ffprobe": _file_identity(ffprobe),
    }
    model_identity_before = _model_identity(model_root)
    previous_ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG")
    previous_ffprobe = os.environ.get("AUTOEDITOR_FFPROBE")
    pipeline_state: tuple[object, object, object] | None = None
    probe_result: dict[str, Any] | None = None
    execution_error: BaseException | None = None

    try:
        _write_exclusive(fixture, fixture_payload)
        _write_exclusive(filter_file, _FILTER_GRAPH)
        _run_checked(
            [
                str(ffmpeg),
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-i",
                str(fixture),
                "-f",
                "lavfi",
                "-i",
                (
                    "color=c=0x203040:s="
                    f"{DIALOGUE_CLEANUP_RUNTIME_PROBE_WIDTH}x"
                    f"{DIALOGUE_CLEANUP_RUNTIME_PROBE_HEIGHT}:"
                    f"r={DIALOGUE_CLEANUP_RUNTIME_PROBE_FPS}:d=5.5"
                ),
                "-filter_complex_script",
                str(filter_file),
                "-map",
                "1:v:0",
                "-map",
                "[aout]",
                "-frames:v",
                "165",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                "-movflags",
                "+faststart",
                str(source_file),
            ],
            execute=execute,
            timeout=120,
            label="dialogue-cleanup fixture render",
        )
        if source_file.is_symlink() or not source_file.is_file():
            _fail("dialogue-cleanup source render is unavailable")
        if _file_identity(fixture) != {
            "sha256": ASR_RUNTIME_PROBE_FIXTURE_SHA256,
            "bytes": ASR_RUNTIME_PROBE_FIXTURE_BYTES,
        }:
            _fail("dialogue-cleanup source fixture changed during rendering")
        source_media = _media_contract(
            source_file,
            ffprobe=ffprobe,
            execute=execute,
            source=True,
        )

        os.environ["AUTOEDITOR_FFMPEG"] = str(ffmpeg)
        os.environ["AUTOEDITOR_FFPROBE"] = str(ffprobe)
        if _create_model is None or _transcribe is None:
            from . import asr

        create_model = _create_model or asr.create_model
        transcribe = _transcribe or asr.transcribe
        if _pipeline_module is None:
            from . import pipeline
        else:
            pipeline = _pipeline_module
        required_pipeline_names = (
            "detect_retakes",
            "detect_false_starts",
            "apply_cuts",
            "verify_no_retakes",
            "FFMPEG",
            "FFPROBE",
            "CUT_BOUNDARIES",
        )
        if any(not hasattr(pipeline, name) for name in required_pipeline_names):
            _fail("production dialogue-cleanup pipeline is incomplete")
        pipeline_state = (
            getattr(pipeline, "FFMPEG"),
            getattr(pipeline, "FFPROBE"),
            getattr(pipeline, "CUT_BOUNDARIES"),
        )
        setattr(pipeline, "FFMPEG", str(ffmpeg))
        setattr(pipeline, "FFPROBE", str(ffprobe))
        setattr(pipeline, "CUT_BOUNDARIES", [])

        try:
            model = create_model(
                str(model_root),
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
        except Exception as error:
            raise DialogueCleanupRuntimeProbeError(
                f"offline small-model load failed: {type(error).__name__}"
            ) from error
        before_words = _transcribe_words(
            model,
            source_file,
            transcribe=transcribe,
            maximum_end_ms=DIALOGUE_CLEANUP_RUNTIME_PROBE_DURATION_MS,
        )
        if _normalized_words(before_words) != (
            DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE * 2
        ):
            _fail("dialogue-cleanup source ASR did not contain exactly two fixed takes")
        take_indexes = _take_indexes(before_words)
        if take_indexes != [0, len(DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE)]:
            _fail("dialogue-cleanup fixed takes are not contiguous and ordered")

        try:
            raw_retake_cuts = pipeline.detect_retakes(before_words)
            raw_false_start_cuts = pipeline.detect_false_starts(
                _fixed_false_start_words()
            )
        except Exception as error:
            raise DialogueCleanupRuntimeProbeError(
                f"production dialogue detector failed: {type(error).__name__}"
            ) from error
        retake_cuts = _cut_payload(
            raw_retake_cuts,
            DIALOGUE_CLEANUP_RUNTIME_PROBE_DURATION_MS,
            "production retake detector",
        )
        false_start_cuts = _cut_payload(
            raw_false_start_cuts,
            2_200,
            "production false-start detector",
        )
        if (
            len(retake_cuts) != 1
            or not retake_cuts[0]["why"].startswith("retake (")
            or len(false_start_cuts) != 1
            or not false_start_cuts[0]["why"].startswith("false start (")
        ):
            _fail("production dialogue detectors returned unexpected fixed-fixture cuts")

        cut = retake_cuts[0]
        kept_take_start = before_words[take_indexes[1]]["s"]
        bad_take_end = before_words[take_indexes[1] - 1]["e"]
        first_bad_start = before_words[0]["s"]
        if (
            cut["start_ms"] > round((first_bad_start + 1 / 30 + 0.001) * 1000)
            or cut["end_ms"] <= round(bad_take_end * 1000)
            or cut["end_ms"] >= round(kept_take_start * 1000)
        ):
            _fail("production retake cut is not word-safe at the kept-take boundary")
        start_frame = round(cut["start_ms"] * 30 / 1000)
        end_frame = round(cut["end_ms"] * 30 / 1000)
        removed_frames = end_frame - start_frame
        if removed_frames < 60:
            _fail("production retake cut removed too little of the fixed bad take")

        try:
            edited = pipeline.apply_cuts(
                source_file,
                raw_retake_cuts,
                root,
            )
        except Exception as error:
            raise DialogueCleanupRuntimeProbeError(
                f"production dialogue cut failed: {type(error).__name__}"
            ) from error
        try:
            edited = Path(edited).resolve(strict=True)
        except (OSError, TypeError) as error:
            raise DialogueCleanupRuntimeProbeError(
                "production dialogue cut returned an invalid artifact"
            ) from error
        if (
            edited != edited_file
            or edited.is_symlink()
            or not edited.is_file()
            or edited == source_file
        ):
            _fail("production dialogue cut escaped its fixed work artifact")
        edited_media = _media_contract(
            edited,
            ffprobe=ffprobe,
            execute=execute,
            source=False,
        )
        expected_frames = source_media["video"]["frames"] - removed_frames
        if (
            edited_media["video"]["frames"] != expected_frames
            or abs(
                (source_media["video"]["duration_ms"]
                 - edited_media["video"]["duration_ms"])
                - round(removed_frames * 1000 / 30)
            ) > 34
        ):
            _fail("production dialogue cut duration does not match removed frames")

        after_words = _transcribe_words(
            model,
            edited,
            transcribe=transcribe,
            maximum_end_ms=edited_media["video"]["duration_ms"],
        )
        if _normalized_words(after_words) != (
            DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE
        ):
            _fail("dialogue-cleanup edited ASR did not contain exactly one fixed take")
        try:
            residue = pipeline.verify_no_retakes(after_words)
        except Exception as error:
            raise DialogueCleanupRuntimeProbeError(
                f"production retake residue gate failed: {type(error).__name__}"
            ) from error
        if (
            not isinstance(residue, dict)
            or residue.get("ok") is not True
            or residue.get("survivors") != []
        ):
            _fail("production retake residue gate found a surviving bad take")
        if _file_identity(source_file) != {
            "sha256": source_media["sha256"],
            "bytes": source_media["bytes"],
        } or _file_identity(edited_file) != {
            "sha256": edited_media["sha256"],
            "bytes": edited_media["bytes"],
        }:
            _fail("dialogue-cleanup media changed after ASR or delivery QA")

        false_start_fixture = _fixed_false_start_words()
        false_start_fixture_hash = _sha256_bytes(
            _canonical_json(false_start_fixture).encode("ascii")
        )
        checks = {
            "artifact_identity": True,
            "expected_single_take_after": True,
            "false_start_detector": True,
            "fixture_identity": True,
            "frame_sample_accurate_av_cut": True,
            "model_identity": True,
            "no_retake_residue": True,
            "normalized_av_before_after": True,
            "offline_small_model": True,
            "production_asr_before_after": True,
            "production_dialogue_pipeline": True,
            "repeated_take_detected": True,
            "tool_identity": True,
            "word_safe_kept_take_boundary": True,
        }
        probe_result = {
            "schema_version": DIALOGUE_CLEANUP_RUNTIME_PROBE_SCHEMA_VERSION,
            "checks": checks,
            "scope": {
                "certified": [
                    "repeated_take_detection",
                    "false_start_detection",
                    "frame_sample_accurate_av_cut",
                    "post_render_retake_residue_gate",
                ],
                "not_certified": [
                    "cough_classification",
                    "dead_air_policy_quality",
                    "garbled_speech_semantics",
                    "general_asr_accuracy",
                ],
            },
            "fixture": {
                "name": ASR_RUNTIME_PROBE_FIXTURE_NAME,
                "sha256": ASR_RUNTIME_PROBE_FIXTURE_SHA256,
                "bytes": ASR_RUNTIME_PROBE_FIXTURE_BYTES,
                "source_revision": ASR_RUNTIME_PROBE_SOURCE_REVISION,
                "take_count": 2,
                "pause_ms": DIALOGUE_CLEANUP_RUNTIME_PROBE_PAUSE_MS,
                "filter_graph_sha256": _sha256_bytes(_FILTER_GRAPH),
                "false_start_timeline_sha256": false_start_fixture_hash,
            },
            "runtime": {
                "model": model_identity_before,
                "tools": tool_identity_before,
            },
            "production_functions": [
                "autoeditor.asr.create_model",
                "autoeditor.asr.transcribe",
                "autoeditor.pipeline.detect_retakes",
                "autoeditor.pipeline.detect_false_starts",
                "autoeditor.pipeline.apply_cuts",
                "autoeditor.pipeline.verify_no_retakes",
            ],
            "detectors": {
                "retake": {"cuts": retake_cuts},
                "false_start": {"cuts": false_start_cuts},
            },
            "transcripts": {
                "before": _word_summary(before_words),
                "after": _word_summary(after_words),
            },
            "edit": {
                "start_frame": start_frame,
                "end_frame": end_frame,
                "removed_frames": removed_frames,
                "removed_ms": round(removed_frames * 1000 / 30),
                "kept_take_start_ms": round(kept_take_start * 1000),
                "cut_end_ms": cut["end_ms"],
                "gap_before_kept_take_ms": (
                    round(kept_take_start * 1000) - cut["end_ms"]
                ),
            },
            "media": {
                "source": source_media,
                "edited": edited_media,
            },
        }
    except BaseException as error:
        execution_error = error
    finally:
        if pipeline_state is not None:
            setattr(pipeline, "FFMPEG", pipeline_state[0])
            setattr(pipeline, "FFPROBE", pipeline_state[1])
            setattr(pipeline, "CUT_BOUNDARIES", pipeline_state[2])
        if previous_ffmpeg is None:
            os.environ.pop("AUTOEDITOR_FFMPEG", None)
        else:
            os.environ["AUTOEDITOR_FFMPEG"] = previous_ffmpeg
        if previous_ffprobe is None:
            os.environ.pop("AUTOEDITOR_FFPROBE", None)
        else:
            os.environ["AUTOEDITOR_FFPROBE"] = previous_ffprobe
        try:
            _clean_staged_files(staged)
        except BaseException as cleanup_error:
            if execution_error is None:
                execution_error = cleanup_error
    if execution_error is not None:
        if isinstance(execution_error, DialogueCleanupRuntimeProbeError):
            raise execution_error
        raise DialogueCleanupRuntimeProbeError(
            f"dialogue-cleanup probe failed: {type(execution_error).__name__}"
        ) from execution_error
    if probe_result is None:
        _fail("dialogue-cleanup probe produced no result")

    if tool_identity_before != {
        "ffmpeg": _file_identity(ffmpeg),
        "ffprobe": _file_identity(ffprobe),
    }:
        _fail("dialogue-cleanup tool identity changed during execution")
    if model_identity_before != _model_identity(model_root):
        _fail("small ASR model identity changed during execution")
    receipt_bytes = (_canonical_json(probe_result) + "\n").encode("ascii")
    _write_exclusive(output, receipt_bytes)
    result = dict(probe_result)
    result["receipt"] = {
        "file": output.name,
        "sha256": _sha256_bytes(receipt_bytes),
        "bytes": len(receipt_bytes),
    }
    return result


__all__ = [
    "DIALOGUE_CLEANUP_RUNTIME_PROBE_EDITED_FILE",
    "DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE",
    "DIALOGUE_CLEANUP_RUNTIME_PROBE_FILTER_FILE",
    "DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE",
    "DIALOGUE_CLEANUP_RUNTIME_PROBE_SCHEMA_VERSION",
    "DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE",
    "DialogueCleanupRuntimeProbeError",
    "run_dialogue_cleanup_runtime_probe",
]
