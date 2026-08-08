"""PyInstaller entry point for the frozen AutoEditor engine.

The desktop app spawns this binary with the same CLI as
`python -m autoeditor`. Keeping the entry file separate from the package
lets PyInstaller resolve imports cleanly.
"""
from __future__ import annotations

import array
import importlib
import json
import math
import multiprocessing
import os
import sys
import tempfile
import wave
from pathlib import Path


def _model(name: str) -> str:
    """Use installer-bundled ASR weights when present, never redownload."""
    return os.environ.get(f"AUTOEDITOR_WHISPER_{name.upper()}", name)


def _asr_words(media: str, output: str) -> None:
    from autoeditor.asr import create_model, transcribe

    model = create_model(_model("small"), device="cpu", compute_type="int8")
    segments, _ = transcribe(model, media, word_timestamps=True)
    words = [
        {
            "w": word.word.strip(),
            "s": round(word.start, 3),
            "e": round(word.end, 3),
            "p": round(word.probability, 2),
        }
        for segment in segments
        for word in (segment.words or [])
    ]
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(words, handle)


def _asr_secondary(media: str, output: str) -> None:
    from autoeditor.asr import create_model, transcribe

    model = create_model(_model("medium"), device="cpu", compute_type="int8")
    segments, _ = transcribe(
        model, media,
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    text = " ".join(segment.text.strip() for segment in segments)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump({"text": text}, handle)


def _self_test() -> int:
    """Prove required native backends survived the PyInstaller freeze."""
    required = (
        "ctranslate2", "faster_whisper", "huggingface_hub",
        "numpy", "onnxruntime", "PIL", "tokenizers",
    )
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    checks["utf8_mode"] = (
        not getattr(sys, "frozen", False) or sys.flags.utf8_mode == 1
    )
    if not checks["utf8_mode"]:
        errors["utf8_mode"] = "frozen Python did not start with -X utf8"
    try:
        from autoeditor import asr

        checks["ffmpeg_audio_decoder"] = asr.decoder_contract_check()
        checks["pyav_not_bundled"] = asr.pyav_payload_absent()
        if not checks["ffmpeg_audio_decoder"]:
            errors["ffmpeg_audio_decoder"] = "decoder shim contract failed"
        if not checks["pyav_not_bundled"]:
            errors["pyav_not_bundled"] = (
                "PyAV package or native libraries were found in frozen engine"
            )
    except Exception as exc:
        checks["ffmpeg_audio_decoder"] = False
        checks["pyav_not_bundled"] = False
        errors["ffmpeg_audio_decoder"] = type(exc).__name__
        errors["pyav_not_bundled"] = type(exc).__name__
    for name in required:
        try:
            importlib.import_module(name)
            checks[name] = True
        except Exception as exc:  # pragma: no cover - exercised frozen in CI
            checks[name] = False
            errors[name] = type(exc).__name__
    try:
        from autoeditor.pipeline import low_speech_cutter_self_test

        checks["in_process_low_speech_cutter"] = bool(
            low_speech_cutter_self_test()
        )
        if not checks["in_process_low_speech_cutter"]:
            errors["in_process_low_speech_cutter"] = "contract returned false"
    except Exception as exc:  # pragma: no cover - exercised frozen in CI
        checks["in_process_low_speech_cutter"] = False
        errors["in_process_low_speech_cutter"] = type(exc).__name__
    try:
        from autoeditor import creative_contract

        contract_hash = creative_contract.contract_sha256()
        checks["creative_contract_sha256"] = (
            isinstance(contract_hash, str)
            and len(contract_hash) == 64
            and all(
                character in "0123456789abcdef"
                for character in contract_hash
            )
        )
        if not checks["creative_contract_sha256"]:
            errors["creative_contract_sha256"] = (
                "contract returned invalid hash"
            )
    except Exception as exc:  # pragma: no cover - exercised frozen in CI
        checks["creative_contract_sha256"] = False
        errors["creative_contract_sha256"] = type(exc).__name__
    print(json.dumps({"event": "autoeditor-engine-self-test",
                      "checks": checks, "errors": errors}, sort_keys=True))
    return 0 if all(checks.values()) else 1


def _audio_decoder_self_test() -> int:
    """Exercise the frozen FFmpeg waveform decoder against real PCM input."""
    from autoeditor.asr import decode_audio

    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    try:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "tone.wav"
            samples = array.array(
                "h",
                (
                    round(12_000 * math.sin(2 * math.pi * 440 * i / 16_000))
                    for i in range(16_000)
                ),
            )
            with wave.open(str(source), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(samples.tobytes())
            decoded = decode_audio(source)
            checks["ffmpeg_waveform_decode"] = (
                decoded.dtype.name == "float32"
                and 15_900 <= decoded.size <= 16_100
                and bool((abs(decoded) > 0.1).any())
            )
            if not checks["ffmpeg_waveform_decode"]:
                errors["ffmpeg_waveform_decode"] = "unexpected PCM output"
    except Exception as exc:
        checks["ffmpeg_waveform_decode"] = False
        errors["ffmpeg_waveform_decode"] = type(exc).__name__
    print(json.dumps({"event": "autoeditor-engine-media-self-test",
                      "checks": checks, "errors": errors}, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(_self_test())
    if len(sys.argv) == 2 and sys.argv[1] == "--audio-decoder-self-test":
        raise SystemExit(_audio_decoder_self_test())
    if len(sys.argv) == 4 and sys.argv[1] == "--asr-words":
        _asr_words(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--asr-secondary":
        _asr_secondary(sys.argv[2], sys.argv[3])
        return

    from autoeditor.pipeline import main as pipeline_main

    pipeline_main()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
