"""PyInstaller entry point for the frozen AutoEditor engine.

The desktop app spawns this binary with the same CLI as
`python -m autoeditor`. Keeping the entry file separate from the package
lets PyInstaller resolve imports cleanly.
"""
from __future__ import annotations

import json
import sys


def _asr_words(media: str, output: str) -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8")
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

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        media,
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    text = " ".join(segment.text.strip() for segment in segments)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump({"text": text}, handle)


def main() -> None:
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
