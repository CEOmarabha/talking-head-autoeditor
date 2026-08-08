"""PyInstaller entry point for the frozen AutoEditor engine.

The desktop app spawns this binary with the same CLI as
`python -m autoeditor`. Keeping the entry file separate from the package
lets PyInstaller resolve imports cleanly.
"""
from __future__ import annotations

import importlib
import json
import os
import sys


def _model(name: str) -> str:
    """Use installer-bundled ASR weights when present, never redownload."""
    return os.environ.get(f"AUTOEDITOR_WHISPER_{name.upper()}", name)


def _asr_words(media: str, output: str) -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel(_model("small"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(media, word_timestamps=True)
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
    from faster_whisper import WhisperModel

    model = WhisperModel(_model("medium"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        media,
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
        "av", "ctranslate2", "faster_whisper", "huggingface_hub",
        "numpy", "onnxruntime", "PIL", "tokenizers",
    )
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    checks["utf8_mode"] = (
        not getattr(sys, "frozen", False) or sys.flags.utf8_mode == 1
    )
    if not checks["utf8_mode"]:
        errors["utf8_mode"] = "frozen Python did not start with -X utf8"
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


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(_self_test())
    if len(sys.argv) == 4 and sys.argv[1] == "--asr-words":
        _asr_words(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--asr-secondary":
        _asr_secondary(sys.argv[2], sys.argv[3])
        return

    from autoeditor.pipeline import main as pipeline_main

    pipeline_main()

if __name__ == "__main__":
    main()
