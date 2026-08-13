from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from autoeditor import pipeline as production_pipeline
from autoeditor.asr_runtime_probe import (
    ASR_RUNTIME_PROBE_FIXTURE_BYTES,
    ASR_RUNTIME_PROBE_FIXTURE_NAME,
    ASR_RUNTIME_PROBE_FIXTURE_SHA256,
    ASR_RUNTIME_PROBE_SOURCE_REVISION,
    asr_runtime_probe_fixture_bytes,
)
from autoeditor.dialogue_cleanup_runtime_probe import (
    DIALOGUE_CLEANUP_RUNTIME_PROBE_EDITED_FILE,
    DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE,
    DIALOGUE_CLEANUP_RUNTIME_PROBE_FILTER_FILE,
    DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE,
    DIALOGUE_CLEANUP_RUNTIME_PROBE_SCHEMA_VERSION,
    DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE,
    DialogueCleanupRuntimeProbeError,
    run_dialogue_cleanup_runtime_probe,
)


CHECK_NAMES = {
    "artifact_identity",
    "expected_single_take_after",
    "false_start_detector",
    "fixture_identity",
    "frame_sample_accurate_av_cut",
    "model_identity",
    "no_retake_residue",
    "normalized_av_before_after",
    "offline_small_model",
    "production_asr_before_after",
    "production_dialogue_pipeline",
    "repeated_take_detected",
    "tool_identity",
    "word_safe_kept_take_boundary",
}


def _word(text: str, start: float, end: float, probability: float = 0.99):
    return types.SimpleNamespace(
        word=text,
        start=start,
        end=end,
        probability=probability,
    )


def _before_words():
    return [
        _word("And", 0.00, 0.52, 0.61),
        _word("so,", 0.52, 0.84, 0.97),
        _word("my", 1.06, 1.20, 0.98),
        _word("fellow", 1.20, 1.52, 1.00),
        _word("Americans,", 1.52, 2.14, 0.86),
        _word("and", 2.56, 3.52, 0.67),
        _word("so,", 3.52, 3.88, 1.00),
        _word("my", 4.06, 4.18, 1.00),
        _word("fellow", 4.18, 4.54, 1.00),
        _word("Americans...", 4.54, 5.48, 0.60),
    ]


def _after_words():
    return [
        _word("And", 0.00, 1.08, 0.68),
        _word("so,", 1.08, 1.40, 0.98),
        _word("my", 1.62, 1.76, 0.98),
        _word("fellow", 1.76, 2.08, 0.99),
        _word("Americans.", 2.08, 2.58, 0.91),
    ]


def _transcription(words):
    return (
        iter([types.SimpleNamespace(text="", words=words)]),
        types.SimpleNamespace(language="en"),
    )


def _stream_payload(source: bool) -> bytes:
    if source:
        video_duration = "5.500000"
        audio_duration = "5.500000"
        frames = "165"
    else:
        video_duration = "3.066667"
        audio_duration = "3.066000"
        frames = "92"
    return json.dumps({
        "streams": [
            {
                "codec_name": "h264",
                "codec_type": "video",
                "width": 320,
                "height": 180,
                "pix_fmt": "yuv420p",
                "avg_frame_rate": "30/1",
                "duration": video_duration,
                "nb_frames": frames,
            },
            {
                "codec_name": "aac",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
                "duration": audio_duration,
            },
        ],
    }).encode("utf-8")


class _PipelineHarness:
    def __init__(self):
        self.FFMPEG = "original-ffmpeg"
        self.FFPROBE = "original-ffprobe"
        self.CUT_BOUNDARIES = [(1.0, 0.5)]
        self.calls: list[str] = []

    def detect_retakes(self, words):
        self.calls.append("detect_retakes")
        return production_pipeline.detect_retakes(words)

    def detect_false_starts(self, words):
        self.calls.append("detect_false_starts")
        return production_pipeline.detect_false_starts(words)

    def apply_cuts(self, source, cuts, workdir):
        self.calls.append("apply_cuts")
        self.applied_source = source
        self.applied_cuts = cuts
        output = Path(workdir) / DIALOGUE_CLEANUP_RUNTIME_PROBE_EDITED_FILE
        output.write_bytes(b"fixed-edited-media")
        return output

    def verify_no_retakes(self, words):
        self.calls.append("verify_no_retakes")
        return production_pipeline.verify_no_retakes(words)


class DialogueCleanupRuntimeProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="dialogue-cleanup-runtime-probe-"
        )
        self.root = Path(self.temporary.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.output = self.work / DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE
        self.ffmpeg = self.root / "ffmpeg.exe"
        self.ffprobe = self.root / "ffprobe.exe"
        self.ffmpeg.write_bytes(b"fixed-ffmpeg")
        self.ffprobe.write_bytes(b"fixed-ffprobe")
        self.model = self.root / "faster-whisper-small"
        self.model.mkdir()
        (self.model / "config.json").write_bytes(b'{"model":"small"}')
        (self.model / "model.bin").write_bytes(b"fixed-small-model")
        self.pipeline = _PipelineHarness()
        self.execute_calls: list[tuple[list[str], dict]] = []
        self.create_calls: list[tuple[str, dict]] = []
        self.transcribe_calls: list[tuple[str, dict]] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fake_execute(self, command, **kwargs):
        command = list(command)
        self.execute_calls.append((command, kwargs))
        if command[0] == str(self.ffmpeg):
            Path(command[-1]).write_bytes(b"fixed-source-media")
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if command[0] == str(self.ffprobe):
            source = Path(command[-1]).name == DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE
            return types.SimpleNamespace(
                returncode=0,
                stdout=_stream_payload(source),
                stderr=b"",
            )
        raise AssertionError(f"unexpected executable: {command[0]}")

    def create_model(self, path, **kwargs):
        self.create_calls.append((path, kwargs))
        return object()

    def transcribe(self, model, media, **kwargs):
        self.transcribe_calls.append((media, kwargs))
        if len(self.transcribe_calls) == 1:
            return _transcription(_before_words())
        return _transcription(_after_words())

    def run_probe(self, **overrides):
        values = {
            "output_path": self.output,
            "work_dir": self.work,
            "model_path": self.model,
            "ffmpeg_path": self.ffmpeg,
            "ffprobe_path": self.ffprobe,
            "_create_model": self.create_model,
            "_transcribe": self.transcribe,
            "_pipeline_module": self.pipeline,
            "_execute": self.fake_execute,
        }
        values.update(overrides)
        return run_dialogue_cleanup_runtime_probe(**values)

    def test_reuses_public_identity_checked_asr_fixture(self):
        payload = asr_runtime_probe_fixture_bytes()
        self.assertEqual(len(payload), ASR_RUNTIME_PROBE_FIXTURE_BYTES)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            ASR_RUNTIME_PROBE_FIXTURE_SHA256,
        )
        self.assertEqual(
            DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE,
            ("and", "so", "my", "fellow", "americans"),
        )

    def test_probe_crosses_detectors_cut_asr_and_residue_gate(self):
        previous_ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG")
        previous_ffprobe = os.environ.get("AUTOEDITOR_FFPROBE")
        os.environ["AUTOEDITOR_FFMPEG"] = "sentinel-ffmpeg"
        os.environ["AUTOEDITOR_FFPROBE"] = "sentinel-ffprobe"
        try:
            result = self.run_probe()
            self.assertEqual(os.environ["AUTOEDITOR_FFMPEG"], "sentinel-ffmpeg")
            self.assertEqual(os.environ["AUTOEDITOR_FFPROBE"], "sentinel-ffprobe")
        finally:
            if previous_ffmpeg is None:
                os.environ.pop("AUTOEDITOR_FFMPEG", None)
            else:
                os.environ["AUTOEDITOR_FFMPEG"] = previous_ffmpeg
            if previous_ffprobe is None:
                os.environ.pop("AUTOEDITOR_FFPROBE", None)
            else:
                os.environ["AUTOEDITOR_FFPROBE"] = previous_ffprobe

        self.assertEqual(
            result["schema_version"],
            DIALOGUE_CLEANUP_RUNTIME_PROBE_SCHEMA_VERSION,
        )
        self.assertEqual(set(result["checks"]), CHECK_NAMES)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(self.pipeline.calls, [
            "detect_retakes",
            "detect_false_starts",
            "apply_cuts",
            "verify_no_retakes",
        ])
        self.assertEqual(
            [item["why"] for item in result["detectors"]["retake"]["cuts"]],
            ["retake (5-word repeat)"],
        )
        self.assertEqual(
            [item["why"] for item in result["detectors"]["false_start"]["cuts"]],
            ["false start (2-word prefix repeat)"],
        )
        self.assertEqual(result["edit"], {
            "start_frame": 1,
            "end_frame": 74,
            "removed_frames": 73,
            "removed_ms": 2433,
            "kept_take_start_ms": 2560,
            "cut_end_ms": 2460,
            "gap_before_kept_take_ms": 100,
        })
        self.assertEqual(result["media"]["source"]["video"]["frames"], 165)
        self.assertEqual(result["media"]["edited"]["video"]["frames"], 92)
        self.assertEqual(result["transcripts"]["before"]["take_count"], 2)
        self.assertEqual(result["transcripts"]["after"]["take_count"], 1)
        self.assertEqual(self.create_calls, [(str(self.model), {
            "device": "cpu",
            "compute_type": "int8",
            "local_files_only": True,
        })])
        self.assertEqual(len(self.transcribe_calls), 2)
        expected_transcribe_options = {
            "language": "en",
            "temperature": 0.0,
            "beam_size": 1,
            "best_of": 1,
            "vad_filter": False,
            "condition_on_previous_text": False,
            "word_timestamps": True,
        }
        self.assertEqual(self.transcribe_calls[0][1], expected_transcribe_options)
        self.assertEqual(self.transcribe_calls[1][1], expected_transcribe_options)
        self.assertEqual(
            (self.pipeline.FFMPEG, self.pipeline.FFPROBE, self.pipeline.CUT_BOUNDARIES),
            ("original-ffmpeg", "original-ffprobe", [(1.0, 0.5)]),
        )

        ffmpeg_command, ffmpeg_kwargs = self.execute_calls[0]
        self.assertIsInstance(ffmpeg_command, list)
        self.assertNotIn("shell", ffmpeg_kwargs)
        self.assertIn("-n", ffmpeg_command)
        self.assertIn("-filter_complex_script", ffmpeg_command)
        self.assertNotIn("-filter_complex", ffmpeg_command)
        self.assertEqual(ffmpeg_command[-1], str(
            self.work / DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE
        ))
        self.assertEqual(
            result["fixture"],
            {
                "name": ASR_RUNTIME_PROBE_FIXTURE_NAME,
                "sha256": ASR_RUNTIME_PROBE_FIXTURE_SHA256,
                "bytes": ASR_RUNTIME_PROBE_FIXTURE_BYTES,
                "source_revision": ASR_RUNTIME_PROBE_SOURCE_REVISION,
                "take_count": 2,
                "pause_ms": 500,
                "filter_graph_sha256": result["fixture"]["filter_graph_sha256"],
                "false_start_timeline_sha256": result["fixture"][
                    "false_start_timeline_sha256"
                ],
            },
        )

        receipt_bytes = self.output.read_bytes()
        expected_receipt = {key: result[key] for key in result if key != "receipt"}
        self.assertEqual(
            receipt_bytes,
            (
                json.dumps(
                    expected_receipt,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("ascii"),
        )
        self.assertEqual(result["receipt"], {
            "file": DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE,
            "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "bytes": len(receipt_bytes),
        })
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(str(self.model), serialized)
        self.assertNotIn(str(self.ffmpeg), serialized)
        self.assertNotIn(str(self.ffprobe), serialized)
        self.assertEqual(
            sorted(item.name for item in self.work.iterdir()),
            [DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE],
        )

    def test_wrong_before_or_surviving_after_take_fails_closed_and_cleans(self):
        wrong_before = _before_words()[:-1]
        surviving_after = _before_words()
        for before, after in (
            (wrong_before, _after_words()),
            (_before_words(), surviving_after),
        ):
            calls = []

            def transcribe(_model, _media, **_kwargs):
                words = before if not calls else after
                calls.append(True)
                return _transcription(words)

            with self.subTest(after_words=len(after)), self.assertRaises(
                DialogueCleanupRuntimeProbeError
            ):
                self.run_probe(_transcribe=transcribe)
            self.assertFalse(self.output.exists())
            for name in (
                ASR_RUNTIME_PROBE_FIXTURE_NAME,
                DIALOGUE_CLEANUP_RUNTIME_PROBE_FILTER_FILE,
                DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE,
                DIALOGUE_CLEANUP_RUNTIME_PROBE_EDITED_FILE,
            ):
                self.assertFalse((self.work / name).exists())
            self.pipeline.calls.clear()
            self.execute_calls.clear()

    def test_output_and_reserved_files_are_exclusive_and_not_overwritten(self):
        self.output.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(
            DialogueCleanupRuntimeProbeError,
            "new fixed file",
        ):
            self.run_probe()
        self.assertEqual(self.output.read_bytes(), b"do-not-overwrite")
        self.output.unlink()
        reserved = self.work / DIALOGUE_CLEANUP_RUNTIME_PROBE_SOURCE_FILE
        reserved.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(
            DialogueCleanupRuntimeProbeError,
            "reserved probe file",
        ):
            self.run_probe()
        self.assertEqual(reserved.read_bytes(), b"do-not-overwrite")
        with self.assertRaisesRegex(
            DialogueCleanupRuntimeProbeError,
            "new fixed file",
        ):
            self.run_probe(output_path=self.root / "other.json")

    def test_model_and_tool_tampering_fail_closed(self):
        (self.model / "model.bin").unlink()
        with self.assertRaisesRegex(
            DialogueCleanupRuntimeProbeError,
            "model inventory",
        ):
            self.run_probe()
        (self.model / "model.bin").write_bytes(b"fixed-small-model")

        original_execute = self.fake_execute
        changed = False

        def tampering_execute(command, **kwargs):
            nonlocal changed
            result = original_execute(command, **kwargs)
            if command[0] == str(self.ffprobe) and not changed:
                changed = True
                self.ffmpeg.write_bytes(b"changed-ffmpeg")
            return result

        with self.assertRaisesRegex(
            DialogueCleanupRuntimeProbeError,
            "tool identity changed",
        ):
            self.run_probe(_execute=tampering_execute)
        self.assertFalse(self.output.exists())
        self.assertEqual(
            sorted(item.name for item in self.work.iterdir()),
            [],
        )

    def test_real_ffmpeg_and_production_cutter_when_available(self):
        ffmpeg = Path(os.environ.get("AUTOEDITOR_FFMPEG", ""))
        ffprobe = Path(os.environ.get("AUTOEDITOR_FFPROBE", ""))
        if not (ffmpeg.is_file() and ffprobe.is_file()):
            self.skipTest("bundled FFmpeg and FFprobe are unavailable")
        result = self.run_probe(
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            _pipeline_module=production_pipeline,
            _execute=None,
        )
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["media"]["source"]["video"]["frames"], 165)
        self.assertEqual(result["media"]["edited"]["video"]["frames"], 92)
        self.assertLessEqual(result["media"]["edited"]["av_duration_drift_ms"], 1)

    def test_real_bundled_asr_before_and_after_when_available(self):
        engine = Path(os.environ.get("AUTOEDITOR_ENGINE", ""))
        ffmpeg = Path(os.environ.get("AUTOEDITOR_FFMPEG", ""))
        ffprobe = Path(os.environ.get("AUTOEDITOR_FFPROBE", ""))
        model = Path(os.environ.get("AUTOEDITOR_WHISPER_SMALL", ""))
        if not (
            engine.is_file()
            and ffmpeg.is_file()
            and ffprobe.is_file()
            and model.is_dir()
            and (model / "model.bin").is_file()
        ):
            self.skipTest("frozen engine, small model, and media tools are unavailable")

        def frozen_transcribe(_model, media, **_kwargs):
            output = self.work / (Path(media).stem + "-frozen-words.json")
            environment = os.environ.copy()
            environment["AUTOEDITOR_FFMPEG"] = str(ffmpeg)
            environment["AUTOEDITOR_WHISPER_SMALL"] = str(model)
            completed = subprocess.run(
                [str(engine), "--asr-words", str(media), str(output)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=120,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr[-500:])
            try:
                payload = json.loads(output.read_text(encoding="utf-8"))
            finally:
                output.unlink(missing_ok=True)
            words = [
                _word(item["w"], item["s"], item["e"], item["p"])
                for item in payload
            ]
            return _transcription(words)

        result = self.run_probe(
            model_path=model,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            _create_model=lambda *_args, **_kwargs: object(),
            _transcribe=frozen_transcribe,
            _pipeline_module=production_pipeline,
            _execute=None,
        )
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["transcripts"]["before"]["take_count"], 2)
        self.assertEqual(result["transcripts"]["after"]["take_count"], 1)
        self.assertEqual(result["edit"]["removed_frames"], 73)


if __name__ == "__main__":
    unittest.main()
