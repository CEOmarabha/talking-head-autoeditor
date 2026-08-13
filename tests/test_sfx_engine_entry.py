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

from autoeditor import sfx_production


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "autoeditor-sfx-production-self-test/v1"
CHECK_NAMES = {
    "decoded_cue_placement", "independent_evidence_verifier",
    "production_sfx_planner", "production_sfx_renderer",
    "project_generated_rights", "tamper_rejected",
}


class SfxEngineEntryTests(unittest.TestCase):
    def test_cli_projects_only_the_closed_production_probe_result(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(prefix="sfx-engine-entry-") as raw:
            root = Path(raw).resolve()
            source = root / "source.wav"
            output = root / "output.wav"
            source.write_bytes(b"fixed source")
            result = {
                "schema_version": SCHEMA,
                "checks": {name: True for name in sorted(CHECK_NAMES)},
                "artifact": {
                    "file": output.name, "sha256": "1" * 64, "bytes": 100,
                    "duration_ms": 1000,
                },
                "production_receipt": {
                    "file": "SFX_PRODUCTION_RECEIPT.json",
                    "sha256": "2" * 64, "bytes": 200,
                    "contract_sha256": "3" * 64,
                },
                "decoded_placement": {
                    "cue_start_ms": 500, "detected_start_ms": 500,
                    "tolerance_ms": 30,
                },
                "evidence": {
                    "sidecar_count": 8,
                    "rights_basis": "project_owned",
                    "generator": "autoeditor-deterministic-pcm/v1",
                },
            }
            stdout = io.StringIO()
            argv = [
                "autoeditor-engine", "--sfx-production-self-test",
                str(source), str(output), str(root),
            ]
            environment = {
                "AUTOEDITOR_FFMPEG": str(root / "ffmpeg.exe"),
                "AUTOEDITOR_FFPROBE": str(root / "ffprobe.exe"),
            }
            with mock.patch.object(
                    sfx_production, "write_sfx_production_probe",
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
            self.assertEqual(
                event["event"],
                "autoeditor-engine-sfx-production-self-test",
            )
            self.assertEqual(event["schema_version"], SCHEMA)
            self.assertEqual(set(event["checks"]), CHECK_NAMES)
            self.assertTrue(all(event["checks"].values()))
            self.assertEqual(event["errors"], {})
            self.assertEqual(set(event["result"]), {
                "artifact", "production_receipt", "decoded_placement",
                "evidence",
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
            status = entry["_sfx_production_self_test"]("a", "b", "c")
        self.assertEqual(status, 1)
        event = json.loads(stdout.getvalue())
        self.assertEqual(event["result"], None)
        self.assertEqual(event["errors"], {"sfx_production": "RuntimeError"})
        self.assertFalse(any(event["checks"].values()))


if __name__ == "__main__":
    unittest.main()
