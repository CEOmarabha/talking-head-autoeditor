from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autoeditor import music_production


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "autoeditor-music-production-self-test/v1"
CHECK_NAMES = {
    "decoded_music_placement", "dialogue_masking",
    "independent_evidence_verifier", "measured_loudness",
    "omission_rejected", "production_music_planner",
    "production_music_renderer", "project_generated_rights",
    "tamper_rejected",
}


def _probe_result(output: Path) -> dict:
    return {
        "schema_version": SCHEMA,
        "checks": {name: True for name in sorted(CHECK_NAMES)},
        "artifact": {
            "file": output.name, "sha256": "1" * 64, "bytes": 100,
            "duration_ms": 3_000,
        },
        "production_receipt": {
            "file": "MUSIC_PRODUCTION_RECEIPT.json",
            "sha256": "2" * 64, "bytes": 200,
            "contract_sha256": "3" * 64,
        },
        "decoded_placement": {
            "expected_start_ms": 500, "expected_end_ms": 1_500,
            "bed_window_start_ms": 600, "bed_window_duration_ms": 500,
            "dialogue_window_start_ms": 1_900,
            "dialogue_window_duration_ms": 500,
            "bed_delta_rms_millionths": 20_000,
            "dialogue_delta_rms_millionths": 0,
            "bed_music_tone_millionths": 15_000,
            "dialogue_music_tone_millionths": 0,
        },
        "measured_audio": {
            "integrated_loudness_millilufs": -14_100,
            "true_peak_millidbtp": -1_100,
            "target_loudness_millilufs": -14_000,
            "true_peak_ceiling_millidbtp": -1_000,
            "loudness_tolerance_millilufs": 1_000,
            "passed": True,
        },
        "evidence": {
            "sidecar_count": 10,
            "generation_sidecar_count": 1,
            "rights_basis": "project_owned",
            "external_service_used": False,
        },
    }


class MusicEngineEntryTests(unittest.TestCase):
    def test_cli_projects_only_the_closed_production_probe_result(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(prefix="music-engine-entry-") as raw:
            root = Path(raw).resolve()
            source = root / "source.wav"
            output = root / "output.mp4"
            source.write_bytes(b"fixed source")
            result = _probe_result(output)
            stdout = io.StringIO()
            argv = [
                "autoeditor-engine", "--music-production-self-test",
                str(source), str(output), str(root),
            ]
            environment = {
                "AUTOEDITOR_FFMPEG": str(root / "ffmpeg.exe"),
                "AUTOEDITOR_FFPROBE": str(root / "ffprobe.exe"),
            }
            with mock.patch.object(
                    music_production, "write_music_production_probe",
                    return_value=result) as probe, \
                    mock.patch.object(sys, "argv", argv), \
                    mock.patch.dict(os.environ, environment, clear=False), \
                    contextlib.redirect_stdout(stdout), \
                    self.assertRaises(SystemExit) as stopped:
                entry["main"]()
            self.assertEqual(stopped.exception.code, 0)
            probe.assert_called_once_with(
                str(source), str(output), str(root),
                environment["AUTOEDITOR_FFMPEG"],
                environment["AUTOEDITOR_FFPROBE"],
            )
            event = json.loads(stdout.getvalue())
            self.assertEqual(set(event), {
                "event", "schema_version", "checks", "errors", "result",
            })
            self.assertEqual(
                event["event"],
                "autoeditor-engine-music-production-self-test",
            )
            self.assertEqual(event["schema_version"], SCHEMA)
            self.assertEqual(set(event["checks"]), CHECK_NAMES)
            self.assertTrue(all(event["checks"].values()))
            self.assertEqual(event["errors"], {})
            self.assertEqual(set(event["result"]), {
                "artifact", "production_receipt", "decoded_placement",
                "measured_audio", "evidence",
            })
            self.assertEqual(event["result"], {
                key: result[key] for key in event["result"]
            })

    def test_missing_media_tool_identity_fails_closed(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {
                "AUTOEDITOR_FFMPEG": "", "AUTOEDITOR_FFPROBE": "",
        }, clear=False), contextlib.redirect_stdout(stdout):
            status = entry["_music_production_self_test"]("a", "b", "c")
        self.assertEqual(status, 1)
        event = json.loads(stdout.getvalue())
        self.assertEqual(event["result"], None)
        self.assertEqual(event["errors"], {
            "music_production": "RuntimeError",
        })
        self.assertFalse(any(event["checks"].values()))

    def test_schema_check_or_unknown_result_drift_fails_closed(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(prefix="music-engine-drift-") as raw:
            root = Path(raw).resolve()
            environment = {
                "AUTOEDITOR_FFMPEG": str(root / "ffmpeg.exe"),
                "AUTOEDITOR_FFPROBE": str(root / "ffprobe.exe"),
            }
            candidates = []
            wrong_schema = _probe_result(root / "out.mp4")
            wrong_schema["schema_version"] = "music-probe/v2"
            candidates.append(wrong_schema)
            failed_check = _probe_result(root / "out.mp4")
            failed_check["checks"]["measured_loudness"] = False
            candidates.append(failed_check)
            unknown_key = _probe_result(root / "out.mp4")
            unknown_key["untrusted"] = True
            candidates.append(unknown_key)
            for candidate in candidates:
                with self.subTest(candidate=candidate), \
                        mock.patch.object(
                            music_production, "write_music_production_probe",
                            return_value=candidate), \
                        mock.patch.dict(
                            os.environ, environment, clear=False), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        entry["_music_production_self_test"](
                            "source", "output", str(root)),
                        1,
                    )


if __name__ == "__main__":
    unittest.main()
