from __future__ import annotations

import hashlib
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from autoeditor.asr_runtime_probe import (
    ASR_RUNTIME_PROBE_EXPECTED_TERMS,
    ASR_RUNTIME_PROBE_FIXTURE_BYTES,
    ASR_RUNTIME_PROBE_FIXTURE_NAME,
    ASR_RUNTIME_PROBE_FIXTURE_SHA256,
    ASR_RUNTIME_PROBE_RECEIPT_FILE,
    ASR_RUNTIME_PROBE_SCHEMA_VERSION,
    ASR_RUNTIME_PROBE_SOURCE_REVISION,
    AsrRuntimeProbeError,
    asr_runtime_probe_fixture_bytes,
    run_asr_runtime_probe,
)


CHECK_NAMES = {
    "expected_transcript", "fixture_identity", "model_identity",
    "offline_small_model", "ordered_word_timestamps", "production_asr",
}


def _word(text: str, start: float, end: float, probability: float = 0.99):
    return types.SimpleNamespace(
        word=text, start=start, end=end, probability=probability,
    )


def _valid_transcription():
    segment = types.SimpleNamespace(
        text=" And so, my fellow Americans!",
        words=[
            _word("And", 0.00, 0.52), _word("so,", 0.52, 0.84),
            _word("my", 1.04, 1.20), _word("fellow", 1.20, 1.52),
            _word("Americans!", 1.52, 2.08),
        ],
    )
    return iter([segment]), types.SimpleNamespace(language="en")


class AsrRuntimeProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="asr-runtime-probe-")
        self.root = Path(self.temporary.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.output = self.work / ASR_RUNTIME_PROBE_RECEIPT_FILE
        self.ffmpeg = self.root / "ffmpeg.exe"
        self.ffmpeg.write_bytes(b"fixed-ffmpeg")
        self.model = self.root / "faster-whisper-small"
        self.model.mkdir()
        (self.model / "config.json").write_bytes(b'{"model":"small"}')
        (self.model / "model.bin").write_bytes(b"fixed-small-model")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_probe(self, **overrides):
        create_calls = []
        transcribe_calls = []

        def create_model(path, **kwargs):
            create_calls.append((path, kwargs))
            return object()

        def transcribe(model, media, **kwargs):
            transcribe_calls.append((model, media, kwargs))
            return _valid_transcription()

        values = {
            "output_path": self.output,
            "work_dir": self.work,
            "model_path": self.model,
            "ffmpeg_path": self.ffmpeg,
            "_create_model": create_model,
            "_transcribe": transcribe,
        }
        values.update(overrides)
        result = run_asr_runtime_probe(**values)
        return result, create_calls, transcribe_calls

    def test_fixed_fixture_identity_matches_official_whisper_excerpt(self):
        payload = asr_runtime_probe_fixture_bytes()
        self.assertEqual(len(payload), ASR_RUNTIME_PROBE_FIXTURE_BYTES)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         ASR_RUNTIME_PROBE_FIXTURE_SHA256)
        self.assertEqual(ASR_RUNTIME_PROBE_EXPECTED_TERMS,
                         ("my", "fellow", "americans"))
        self.assertEqual(
            ASR_RUNTIME_PROBE_SOURCE_REVISION,
            "openai/whisper@6e3be77e1a105e59086e3e21ff5f609fd6fa89a5:tests/jfk.flac",
        )

    def test_probe_executes_production_contract_offline_and_persists_receipt(self):
        previous = os.environ.get("AUTOEDITOR_FFMPEG")
        os.environ["AUTOEDITOR_FFMPEG"] = "sentinel"
        try:
            result, create_calls, transcribe_calls = self.run_probe()
            self.assertEqual(os.environ["AUTOEDITOR_FFMPEG"], "sentinel")
        finally:
            if previous is None:
                os.environ.pop("AUTOEDITOR_FFMPEG", None)
            else:
                os.environ["AUTOEDITOR_FFMPEG"] = previous
        self.assertEqual(set(result), {
            "schema_version", "checks", "fixture", "model", "transcript",
            "words", "receipt",
        })
        self.assertEqual(result["schema_version"],
                         ASR_RUNTIME_PROBE_SCHEMA_VERSION)
        self.assertEqual(set(result["checks"]), CHECK_NAMES)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["fixture"], {
            "name": ASR_RUNTIME_PROBE_FIXTURE_NAME,
            "sha256": ASR_RUNTIME_PROBE_FIXTURE_SHA256,
            "bytes": ASR_RUNTIME_PROBE_FIXTURE_BYTES,
            "source_revision": ASR_RUNTIME_PROBE_SOURCE_REVISION,
        })
        self.assertEqual(create_calls, [(str(self.model), {
            "device": "cpu", "compute_type": "int8", "local_files_only": True,
        })])
        self.assertEqual(len(transcribe_calls), 1)
        _, fixture_path, kwargs = transcribe_calls[0]
        self.assertEqual(Path(fixture_path).name, ASR_RUNTIME_PROBE_FIXTURE_NAME)
        self.assertFalse(Path(fixture_path).exists())
        self.assertEqual(kwargs, {
            "language": "en", "temperature": 0.0, "beam_size": 1,
            "best_of": 1, "vad_filter": False,
            "condition_on_previous_text": False, "word_timestamps": True,
        })
        self.assertEqual(
            [item["text"].casefold().strip("!,") for item in result["words"]][2:],
            ["my", "fellow", "americans"],
        )
        receipt_bytes = self.output.read_bytes()
        expected_contract = {
            key: result[key] for key in (
                "schema_version", "checks", "fixture", "model", "transcript",
                "words",
            )
        }
        self.assertEqual(receipt_bytes, (
            json.dumps(expected_contract, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n"
        ).encode("ascii"))
        self.assertEqual(result["receipt"], {
            "file": ASR_RUNTIME_PROBE_RECEIPT_FILE,
            "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "bytes": len(receipt_bytes),
        })
        canonical = json.dumps(result, sort_keys=True)
        self.assertNotIn(str(self.root), canonical)
        self.assertNotIn(str(self.model), canonical)
        self.assertNotIn(str(self.ffmpeg), canonical)

    def test_wrong_phrase_overlap_and_missing_model_fail_closed(self):
        cases = []
        wrong_phrase = (iter([types.SimpleNamespace(
            text="my fellow citizens",
            words=[_word("my", 0.1, 0.3), _word("fellow", 0.3, 0.6),
                   _word("citizens", 0.6, 1.0)],
        )]), types.SimpleNamespace(language="en"))
        cases.append(wrong_phrase)
        overlap = (iter([types.SimpleNamespace(
            text="my fellow Americans",
            words=[_word("my", 0.1, 0.5), _word("fellow", 0.4, 0.7),
                   _word("Americans", 0.7, 1.1)],
        )]), types.SimpleNamespace(language="en"))
        cases.append(overlap)
        for index, transcription in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(AsrRuntimeProbeError):
                self.run_probe(_transcribe=lambda *_args, result=transcription,
                               **_kwargs: result)
            self.output.unlink(missing_ok=True)
        (self.model / "model.bin").unlink()
        with self.assertRaisesRegex(AsrRuntimeProbeError, "model inventory"):
            self.run_probe()

    def test_output_is_exclusive_and_fixed_inside_work_directory(self):
        self.output.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(AsrRuntimeProbeError, "new fixed receipt"):
            self.run_probe()
        self.assertEqual(self.output.read_bytes(), b"do-not-overwrite")
        with self.assertRaisesRegex(AsrRuntimeProbeError, "new fixed receipt"):
            self.run_probe(output_path=self.root / "other.json")

    def test_real_small_model_probe_when_bundled_runtime_is_available(self):
        ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "")
        model = os.environ.get("AUTOEDITOR_WHISPER_SMALL", "")
        if not (Path(ffmpeg).is_file() and Path(model).is_dir()
                and (Path(model) / "model.bin").is_file()):
            self.skipTest("bundled small Whisper model and FFmpeg are unavailable")
        result = run_asr_runtime_probe(
            output_path=self.output, work_dir=self.work,
            model_path=model, ffmpeg_path=ffmpeg,
        )
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(
            [item["text"].casefold().strip("!,.") for item in result["words"]][2:],
            ["my", "fellow", "americans"],
        )


if __name__ == "__main__":
    unittest.main()
