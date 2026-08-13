"""Fixed offline proof for the bundled small-model ASR capability.

The embedded audio is a short AAC transcode of ``tests/jfk.flac`` from the
official OpenAI Whisper repository at revision
``6e3be77e1a105e59086e3e21ff5f609fd6fa89a5``. Whisper uses that file in its
own word-timestamp transcription test. The Whisper repository and model
weights are MIT licensed; see https://github.com/openai/whisper/blob/main/LICENSE.

This probe proves only offline speech transcription and word timestamps. It
does not claim dialogue cleanup, diarization, semantic quality, or general
accuracy beyond the fixed fixture.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable

ASR_RUNTIME_PROBE_SCHEMA_VERSION = "autoeditor-asr-runtime-probe/v1"
ASR_RUNTIME_PROBE_RECEIPT_FILE = "ASR_RUNTIME_PROBE_RECEIPT.json"
ASR_RUNTIME_PROBE_FIXTURE_NAME = "openai-whisper-jfk-excerpt.m4a"
ASR_RUNTIME_PROBE_SOURCE_REVISION = (
    "openai/whisper@6e3be77e1a105e59086e3e21ff5f609fd6fa89a5:tests/jfk.flac"
)
ASR_RUNTIME_PROBE_EXPECTED_TERMS = ("my", "fellow", "americans")
ASR_RUNTIME_PROBE_FIXTURE_SHA256 = (
    "b36ddd51100eca8b767f667e90d6d0200a943eb2e25c6c021609582a2dcf4c37"
)
ASR_RUNTIME_PROBE_FIXTURE_BYTES = 9_743
ASR_RUNTIME_PROBE_MAX_MODEL_FILES = 64
ASR_RUNTIME_PROBE_MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024

# 2.5 seconds, mono 16 kHz AAC at 24 kbit/s. The fixed bytes are deliberately
# embedded so capability discovery never downloads a fixture or touches a
# network/cache seam.
_FIXTURE_M4A_BASE64 = """
AAAAHGZ0eXBNNEEgAAACAE00QSBpc29taXNvMgAAA59tb292AAAAbG12aGQAAAAAAAAAAAAAAAAAAAPoAAAJxAABAAABAAAAAAAA
AAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAACyXRy
YWsAAABcdGtoZAAAAAMAAAAAAAAAAAAAAAEAAAAAAAAJxAAAAAAAAAAAAAAAAQEAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAA
AAAAAAAAAEAAAAAAAAAAAAAAAAAAACRlZHRzAAAAHGVsc3QAAAAAAAAAAQAACcQAAAQAAAEAAAAAAkFtZGlhAAAAIG1kaGQAAAAA
AAAAAAAAAAAAAD6AAACgQFXEAAAAAAAtaGRscgAAAAAAAAAAc291bgAAAAAAAAAAAAAAAFNvdW5kSGFuZGxlcgAAAAHsbWluZgAA
ABBzbWhkAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAGwc3RibAAAAGpzdHNkAAAAAAAAAAEA
AABabXA0YQAAAAAAAAABAAAAAAAAAAAAAQAQAAAAAD6AAAAAAAA2ZXNkcwAAAAADgICAJQABAASAgIAXQBUAAAAAAGrpAABq6QWA
gIAFFAhW5QAGgICAAQIAAAAgc3R0cwAAAAAAAAACAAAAKAAABAAAAAABAAAAQAAAABxzdHNjAAAAAAAAAAEAAAABAAAAKQAAAAEA
AAC4c3RzegAAAAAAAAAAAAAAKQAAAGEAAALmAAAArQAAAOsAAADuAAABiwAAAOkAAADYAAAA5gAAAOcAAADOAAAA2QAAANkAAADN
AAAAwwAAANYAAADRAAAA2AAAAMgAAADFAAAAvQAAAL8AAADIAAAAzQAAAMgAAAC6AAAAwAAAAMoAAAC9AAAA0AAAAMQAAACtAAAA
yQAAALAAAAC2AAAAqwAAALYAAAC2AAAAxQAAARcAAAAFAAAAFHN0Y28AAAAAAAAAAQAAA8sAAAAac2dwZAEAAAByb2xsAAAAAgAA
AAH//wAAABxzYmdwAAAAAHJvbGwAAAABAAAAKQAAAAEAAABidWR0YQAAAFptZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBw
bAAAAAAAAAAAAAAAAC1pbHN0AAAAJal0b28AAAAdZGF0YQAAAAEAAAAATGF2ZjYyLjEyLjEwMgAAAAhmcmVlAAAiTG1kYXTeAgBM
YXZjNjIuMjguMTAyAAFQoQesUBf+//4ADR06dOvZtbWtpz4E4k4nJdnY5CxkyGl1hDU6AhmMkQwceUUk5FUnUhkyCui0QzOPItaT
gOTOnV1dXt9vjvo7eViBOYfAAOSfmeX1Cv83+b/LilqvjiVun/jj28PrMquPab4//tZ1x1OeJrTqcf/xa9s81qc9a1q+ARPvPHND
H7z/kTr/v/Zmnr7PHMCDqCq/gBYY5LUwBrZOqnwB2KmNVAEASCLJ8bi2JdqXiKYUPPDnj9g8fgckMACjllFsGULIkNwQ+q4d1r6H
2pq4VGAg5bQploEFyYg7/ec0bM4UAhoAOA4yo9sSFEwHYm9wWQ2m23XYGiDOcBzlnAsqY5OnPPIk7e1634szv9F1Hx8JxnKAAznG
jrboYY5hlrydL3aPS1bVOOxuv2O3CWYTzmhgemf/mdAf2KIZq/6vk8WBi/j/V87jJkBk8GPwfZ+a6b48IAF947g/gY8CQjBusXc8
XrcRMApnH+fJhSTgLx+Td0+AICaQIMgU5AgCBBkBkx4EgIGOcv6L+153KTMMmMRM5qzDMVG4dVHRfO8iy2NqkDQ6pLwnF7yC1ZpD
1SwNh2ytxj0MX8l89m6pRZK0jv/X3Zv/EkQc+E3XtPL9WrWkv0PAJiZ0CLBzVEK2MpUQDqrWmBnvnlDtezie3/goGQIn7J/A+2fc
3R+VzVxdPoccfYZ+B+roQlN0ADjaZSZWJIFEBgWEEgGM1HULSADdHY9Frzwbl/7V6JzV+R+WQPdgVwXJ4NFXl6n4lRSeu+e/4HPm
9HYkoA/l/bvjPMP1X7/THipEY7PTnYlbFnwjBtuUYzlU2Pg478QqYfLpIYPcuuLUbku2P+ksFzH4hwGD7RmHQ+TzWYSogZ0BG3UH
+MoNlaDkMsk89YVSS66gW+KgTfU8fDxsZNKOSdf6u8xncuPVunykkEfj3iWz3NNkzCnc2bshi7vyCaWRZz/D619byADi3SH96sxd
IxlkwxEROMiYWECCnw5NaH3nYvMWGZ3PK5MmDswVni5rls1mHldRARf05ETviOu7aIwAkTgn4BNIuiftfQ9nk8klMEvEIDJQ5bcM
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
"""


class AsrRuntimeProbeError(ValueError):
    """The fixed ASR capability proof could not be produced safely."""


def _fail(message: str) -> None:
    raise AsrRuntimeProbeError(message)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise AsrRuntimeProbeError("ASR probe receipt is not canonical JSON") from error


def _absolute_existing_file(value: str | os.PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _fail(f"{label} path is invalid")
    text = os.fspath(value)
    if not text or "\x00" in text:
        _fail(f"{label} path is invalid")
    path = Path(os.path.realpath(Path(text)))
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        _fail(f"{label} is unavailable")
    return path


def _absolute_existing_dir(value: str | os.PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _fail(f"{label} path is invalid")
    text = os.fspath(value)
    if not text or "\x00" in text:
        _fail(f"{label} path is invalid")
    path = Path(os.path.realpath(Path(text)))
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        _fail(f"{label} is unavailable")
    return path


def _direct_new_output(value: str | os.PathLike[str], root: Path) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _fail("ASR probe output path is invalid")
    text = os.fspath(value)
    if not text or "\x00" in text:
        _fail("ASR probe output path is invalid")
    output = Path(os.path.realpath(Path(text)))
    if (not output.is_absolute() or output.parent != root or output.exists()
            or output.name != ASR_RUNTIME_PROBE_RECEIPT_FILE):
        _fail("ASR probe output must be a new fixed receipt inside its work directory")
    return output


def asr_runtime_probe_fixture_bytes() -> bytes:
    """Return the immutable, identity-checked official Whisper test excerpt."""
    try:
        payload = base64.b64decode(_FIXTURE_M4A_BASE64, validate=False)
    except (ValueError, binascii.Error) as error:
        raise AsrRuntimeProbeError("embedded ASR fixture is invalid") from error
    if (len(payload) != ASR_RUNTIME_PROBE_FIXTURE_BYTES
            or _sha256_bytes(payload) != ASR_RUNTIME_PROBE_FIXTURE_SHA256):
        _fail("embedded ASR fixture identity changed")
    return payload


def _model_identity(model_path: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]]:
    root = _absolute_existing_dir(model_path, "small ASR model")
    files = sorted(
        (item for item in root.iterdir() if item.is_file() and not item.is_symlink()),
        key=lambda item: item.name.encode("utf-8"),
    )
    if (not files or len(files) > ASR_RUNTIME_PROBE_MAX_MODEL_FILES
            or any(item.name in {".", ".."} or "/" in item.name
                   or "\\" in item.name or "\x00" in item.name
                   for item in files)
            or not any(item.name == "model.bin" for item in files)):
        _fail("small ASR model inventory is invalid")
    digest = hashlib.sha256()
    total = 0
    for item in files:
        before = item.stat()
        if before.st_size < 1:
            _fail("small ASR model contains an empty file")
        item_hash = _sha256_file(item)
        after = item.stat()
        if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)):
            _fail("small ASR model changed while it was measured")
        total += before.st_size
        if total > ASR_RUNTIME_PROBE_MAX_MODEL_BYTES:
            _fail("small ASR model exceeds the bounded probe size")
        digest.update(item.name.encode("utf-8") + b"\0")
        digest.update(str(before.st_size).encode("ascii") + b"\0")
        digest.update(item_hash.encode("ascii") + b"\n")
    return root, {
        "name": "faster-whisper-small",
        "tree_sha256": digest.hexdigest(),
        "bytes": total,
        "files": len(files),
    }


def _word_value(word: object, name: str) -> object:
    if isinstance(word, dict):
        return word.get(name)
    return getattr(word, name, None)


def _normalize_term(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9']+", "", value)


def _transcript_words(segments: object) -> tuple[list[dict[str, Any]], str]:
    try:
        segment_items = list(segments)
    except TypeError as error:
        raise AsrRuntimeProbeError("ASR returned invalid segments") from error
    words: list[dict[str, Any]] = []
    text_parts: list[str] = []
    prior_end = 0
    for segment in segment_items:
        segment_text = _word_value(segment, "text")
        if isinstance(segment_text, str) and segment_text.strip():
            text_parts.append(segment_text.strip())
        raw_words = _word_value(segment, "words")
        if raw_words is None:
            continue
        try:
            word_items = list(raw_words)
        except TypeError as error:
            raise AsrRuntimeProbeError("ASR word timestamps are invalid") from error
        for raw in word_items:
            raw_text = _word_value(raw, "word")
            start = _word_value(raw, "start")
            end = _word_value(raw, "end")
            probability = _word_value(raw, "probability")
            if (not isinstance(raw_text, str) or not raw_text.strip()
                    or isinstance(start, bool) or not isinstance(start, (int, float))
                    or isinstance(end, bool) or not isinstance(end, (int, float))
                    or isinstance(probability, bool)
                    or not isinstance(probability, (int, float))):
                _fail("ASR word timestamp item is invalid")
            start_ms = round(float(start) * 1000)
            end_ms = round(float(end) * 1000)
            probability_millionths = round(float(probability) * 1_000_000)
            if (start_ms < prior_end or end_ms <= start_ms or end_ms > 10_000
                    or not 0 <= probability_millionths <= 1_000_000):
                _fail("ASR word timestamps are unordered, overlapping, or invalid")
            words.append({
                "text": raw_text.strip(),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "probability_millionths": probability_millionths,
            })
            prior_end = end_ms
    if not words:
        _fail("ASR returned no word timestamps")
    return words, " ".join(text_parts)


def _ordered_expected_terms(words: list[dict[str, Any]]) -> bool:
    normalized = [_normalize_term(item["text"]) for item in words]
    cursor = 0
    for expected in ASR_RUNTIME_PROBE_EXPECTED_TERMS:
        try:
            cursor = normalized.index(expected, cursor) + 1
        except ValueError:
            return False
    return True


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
                raise OSError("short ASR probe receipt write")
            written += count
        os.fsync(descriptor)
        os.chmod(path, 0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def run_asr_runtime_probe(
    *,
    output_path: str | os.PathLike[str],
    work_dir: str | os.PathLike[str],
    model_path: str | os.PathLike[str],
    ffmpeg_path: str | os.PathLike[str],
    _create_model: Callable[..., object] | None = None,
    _transcribe: Callable[..., object] | None = None,
) -> dict[str, Any]:
    """Run the fixed offline small-model transcription and timestamp proof."""
    root = _absolute_existing_dir(work_dir, "ASR probe work directory")
    output = _direct_new_output(output_path, root)
    ffmpeg = _absolute_existing_file(ffmpeg_path, "ASR probe FFmpeg")
    model_root, model = _model_identity(model_path)
    fixture_payload = asr_runtime_probe_fixture_bytes()
    fixture = root / ASR_RUNTIME_PROBE_FIXTURE_NAME
    _write_exclusive(fixture, fixture_payload)

    if _create_model is None or _transcribe is None:
        # Import lazily so receipt validators and fixture identity checks do
        # not require NumPy/CTranslate2. Actual capability execution still
        # crosses the production autoeditor.asr boundary.
        from . import asr
    create_model = _create_model or asr.create_model
    transcribe = _transcribe or asr.transcribe
    previous_ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG")
    os.environ["AUTOEDITOR_FFMPEG"] = str(ffmpeg)
    try:
        runtime_model = create_model(
            str(model_root), device="cpu", compute_type="int8",
            local_files_only=True,
        )
        transcription = transcribe(
            runtime_model, str(fixture), language="en", temperature=0.0,
            beam_size=1, best_of=1, vad_filter=False,
            condition_on_previous_text=False, word_timestamps=True,
        )
    except Exception as error:
        raise AsrRuntimeProbeError(
            f"offline small-model ASR execution failed: {type(error).__name__}"
        ) from error
    finally:
        if previous_ffmpeg is None:
            os.environ.pop("AUTOEDITOR_FFMPEG", None)
        else:
            os.environ["AUTOEDITOR_FFMPEG"] = previous_ffmpeg
        fixture.unlink(missing_ok=True)

    if (not isinstance(transcription, tuple) or len(transcription) != 2):
        _fail("ASR returned an invalid transcription result")
    segments, info = transcription
    words, text = _transcript_words(segments)
    language = _word_value(info, "language")
    if language is None:
        language = "en"
    if language != "en":
        _fail("ASR did not identify the fixed English fixture")
    normalized_text = " ".join(_normalize_term(item["text"]) for item in words)
    if not _ordered_expected_terms(words):
        _fail("ASR transcript omitted the fixed expected terms")
    if not text:
        text = " ".join(item["text"] for item in words)

    checks = {
        "expected_transcript": True,
        "fixture_identity": True,
        "model_identity": True,
        "offline_small_model": True,
        "ordered_word_timestamps": True,
        "production_asr": True,
    }
    result = {
        "schema_version": ASR_RUNTIME_PROBE_SCHEMA_VERSION,
        "checks": checks,
        "fixture": {
            "name": ASR_RUNTIME_PROBE_FIXTURE_NAME,
            "sha256": ASR_RUNTIME_PROBE_FIXTURE_SHA256,
            "bytes": ASR_RUNTIME_PROBE_FIXTURE_BYTES,
            "source_revision": ASR_RUNTIME_PROBE_SOURCE_REVISION,
        },
        "model": model,
        "transcript": {
            "language": language,
            "text": text,
            "normalized_text": normalized_text,
        },
        "words": words,
    }
    receipt = dict(result)
    receipt_bytes = (_canonical_json(receipt) + "\n").encode("ascii")
    _write_exclusive(output, receipt_bytes)
    result["receipt"] = {
        "file": output.name,
        "sha256": _sha256_bytes(receipt_bytes),
        "bytes": len(receipt_bytes),
    }
    return result


__all__ = [
    "ASR_RUNTIME_PROBE_EXPECTED_TERMS",
    "ASR_RUNTIME_PROBE_FIXTURE_BYTES",
    "ASR_RUNTIME_PROBE_FIXTURE_NAME",
    "ASR_RUNTIME_PROBE_FIXTURE_SHA256",
    "ASR_RUNTIME_PROBE_RECEIPT_FILE",
    "ASR_RUNTIME_PROBE_SCHEMA_VERSION",
    "ASR_RUNTIME_PROBE_SOURCE_REVISION",
    "AsrRuntimeProbeError",
    "asr_runtime_probe_fixture_bytes",
    "run_asr_runtime_probe",
]
