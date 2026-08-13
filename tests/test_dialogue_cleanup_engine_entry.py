from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autoeditor import dialogue_cleanup_runtime_probe
from autoeditor.asr_runtime_probe import (
    ASR_RUNTIME_PROBE_FIXTURE_BYTES,
    ASR_RUNTIME_PROBE_FIXTURE_NAME,
    ASR_RUNTIME_PROBE_FIXTURE_SHA256,
    ASR_RUNTIME_PROBE_SOURCE_REVISION,
)


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "autoeditor-dialogue-cleanup-runtime-probe/v1"
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
EVENT = "autoeditor-engine-dialogue-cleanup-capability-self-test"


def _identity(digit: str, size: int) -> dict:
    return {"sha256": digit * 64, "bytes": size}


def _probe_result(output: Path) -> dict:
    expected_take = "and so my fellow americans"
    source = {
        **_identity("4", 100_000),
        "video": {
            "codec": "h264",
            "width": 320,
            "height": 180,
            "pixel_format": "yuv420p",
            "fps": 30,
            "frames": 165,
            "duration_ms": 5_500,
        },
        "audio": {
            "codec": "aac",
            "sample_rate": 48_000,
            "channels": 2,
            "duration_ms": 5_500,
        },
        "av_duration_drift_ms": 0,
    }
    edited = {
        **_identity("5", 80_000),
        "video": {
            "codec": "h264",
            "width": 320,
            "height": 180,
            "pixel_format": "yuv420p",
            "fps": 30,
            "frames": 92,
            "duration_ms": 3_067,
        },
        "audio": {
            "codec": "aac",
            "sample_rate": 48_000,
            "channels": 2,
            "duration_ms": 3_066,
        },
        "av_duration_drift_ms": 1,
    }
    result = {
        "schema_version": SCHEMA,
        "checks": {name: True for name in sorted(CHECK_NAMES)},
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
            "pause_ms": 500,
            "filter_graph_sha256": "6" * 64,
            "false_start_timeline_sha256": "7" * 64,
        },
        "runtime": {
            "model": {
                "name": "faster-whisper-small",
                "tree_sha256": "8" * 64,
                "bytes": 500_000_000,
                "files": 8,
            },
            "tools": {
                "ffmpeg": _identity("9", 1_000_000),
                "ffprobe": _identity("a", 900_000),
            },
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
            "retake": {
                "cuts": [{
                    "start_ms": 30,
                    "end_ms": 2_460,
                    "why": "retake (5-word repeat)",
                }],
            },
            "false_start": {
                "cuts": [{
                    "start_ms": 130,
                    "end_ms": 1_200,
                    "why": "false start (2-word prefix repeat)",
                }],
            },
        },
        "transcripts": {
            "before": {
                "normalized_text": f"{expected_take} {expected_take}",
                "take_count": 2,
                "word_count": 10,
                "word_timing_sha256": "b" * 64,
            },
            "after": {
                "normalized_text": expected_take,
                "take_count": 1,
                "word_count": 5,
                "word_timing_sha256": "c" * 64,
            },
        },
        "edit": {
            "start_frame": 1,
            "end_frame": 74,
            "removed_frames": 73,
            "removed_ms": 2_433,
            "kept_take_start_ms": 2_560,
            "cut_end_ms": 2_460,
            "gap_before_kept_take_ms": 100,
        },
        "media": {"source": source, "edited": edited},
    }
    receipt_bytes = (
        json.dumps(
            result,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
    ).encode("ascii")
    output.write_bytes(receipt_bytes)
    result["receipt"] = {
        "file": output.name,
        "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "bytes": len(receipt_bytes),
    }
    return result


class DialogueCleanupEngineEntryTests(unittest.TestCase):
    def test_cli_projects_only_the_strict_closed_probe_result(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(
            prefix="dialogue-cleanup-engine-entry-"
        ) as raw:
            root = Path(raw).resolve()
            work = root / "work"
            work.mkdir()
            receipt_name = (
                dialogue_cleanup_runtime_probe
                .DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE
            )
            output = work / receipt_name
            result = _probe_result(output)
            ffmpeg = root / "ffmpeg.exe"
            ffprobe = root / "ffprobe.exe"
            model = root / "faster-whisper-small"
            environment = {
                "AUTOEDITOR_FFMPEG": str(ffmpeg),
                "AUTOEDITOR_FFPROBE": str(ffprobe),
                "AUTOEDITOR_WHISPER_SMALL": str(model),
            }
            probe = mock.Mock(return_value=result)
            argv = [
                "autoeditor-engine",
                "--dialogue-cleanup-capability-self-test",
                str(output),
                str(work),
            ]
            stdout = io.StringIO()
            with mock.patch.object(
                    dialogue_cleanup_runtime_probe,
                    "run_dialogue_cleanup_runtime_probe",
                    probe), \
                    mock.patch.dict(os.environ, environment, clear=False), \
                    mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(stdout), \
                    self.assertRaises(SystemExit) as stopped:
                entry["main"]()
            self.assertEqual(stopped.exception.code, 0)
            probe.assert_called_once_with(
                output_path=str(output),
                work_dir=str(work),
                model_path=str(model),
                ffmpeg_path=str(ffmpeg),
                ffprobe_path=str(ffprobe),
            )
            event = json.loads(stdout.getvalue())
            self.assertEqual(set(event), {
                "event", "schema_version", "checks", "errors", "result",
            })
            self.assertEqual(event["event"], EVENT)
            self.assertEqual(event["schema_version"], SCHEMA)
            self.assertEqual(set(event["checks"]), CHECK_NAMES)
            self.assertTrue(all(event["checks"].values()))
            self.assertEqual(event["errors"], {})
            self.assertEqual(set(event["result"]), {
                "scope", "fixture", "runtime", "production_functions",
                "detectors", "transcripts", "edit", "media", "receipt",
            })
            self.assertEqual(
                event["result"],
                {key: result[key] for key in event["result"]},
            )
            self.assertNotIn(str(root), stdout.getvalue())

    def test_missing_runtime_identity_fails_closed(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        stdout = io.StringIO()
        environment = {
            "AUTOEDITOR_FFMPEG": "",
            "AUTOEDITOR_FFPROBE": "",
            "AUTOEDITOR_WHISPER_SMALL": "small",
        }
        with mock.patch.dict(os.environ, environment, clear=False), \
                contextlib.redirect_stdout(stdout):
            status = entry["_dialogue_cleanup_capability_self_test"](
                "out", "work"
            )
        self.assertEqual(status, 1)
        event = json.loads(stdout.getvalue())
        self.assertEqual(event["event"], EVENT)
        self.assertEqual(event["result"], None)
        self.assertEqual(
            event["errors"],
            {"dialogue_cleanup_runtime_probe": "RuntimeError"},
        )
        self.assertFalse(any(event["checks"].values()))

    def test_nested_media_or_canonical_receipt_tamper_fails_closed(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(
            prefix="dialogue-cleanup-engine-tamper-"
        ) as raw:
            root = Path(raw).resolve()
            work = root / "work"
            work.mkdir()
            receipt_name = (
                dialogue_cleanup_runtime_probe
                .DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE
            )
            output = work / receipt_name
            result = _probe_result(output)
            result["media"]["edited"]["video"]["frames"] = 93
            environment = {
                "AUTOEDITOR_FFMPEG": str(root / "ffmpeg.exe"),
                "AUTOEDITOR_FFPROBE": str(root / "ffprobe.exe"),
                "AUTOEDITOR_WHISPER_SMALL": str(root / "model"),
            }
            stdout = io.StringIO()
            with mock.patch.object(
                    dialogue_cleanup_runtime_probe,
                    "run_dialogue_cleanup_runtime_probe",
                    return_value=result), \
                    mock.patch.dict(os.environ, environment, clear=False), \
                    contextlib.redirect_stdout(stdout):
                status = entry["_dialogue_cleanup_capability_self_test"](
                    str(output), str(work)
                )
            self.assertEqual(status, 1)
            event = json.loads(stdout.getvalue())
            self.assertEqual(event["result"], None)
            self.assertEqual(
                event["errors"],
                {"dialogue_cleanup_runtime_probe": "RuntimeError"},
            )
            self.assertFalse(any(event["checks"].values()))


if __name__ == "__main__":
    unittest.main()
