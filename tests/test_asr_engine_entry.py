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

from autoeditor import asr_runtime_probe


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "autoeditor-asr-runtime-probe/v1"
CHECK_NAMES = {
    "offline_small_model", "production_asr", "expected_transcript",
    "ordered_word_timestamps", "fixture_identity", "model_identity",
}


class AsrEngineEntryTests(unittest.TestCase):
    def test_cli_projects_only_the_closed_offline_probe_result(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(prefix="asr-engine-entry-") as raw:
            root = Path(raw).resolve()
            output = root / "ASR_RUNTIME_PROBE_RECEIPT.json"
            work = root / "work"
            work.mkdir()
            ffmpeg = root / "ffmpeg.exe"
            model = root / "faster-whisper-small"
            result = {
                "schema_version": SCHEMA,
                "checks": {name: True for name in sorted(CHECK_NAMES)},
                "fixture": {
                    "name": asr_runtime_probe.ASR_RUNTIME_PROBE_FIXTURE_NAME,
                    "sha256":
                        asr_runtime_probe.ASR_RUNTIME_PROBE_FIXTURE_SHA256,
                    "bytes": asr_runtime_probe.ASR_RUNTIME_PROBE_FIXTURE_BYTES,
                    "source_revision":
                        asr_runtime_probe.ASR_RUNTIME_PROBE_SOURCE_REVISION,
                },
                "model": {
                    "name": "faster-whisper-small",
                    "tree_sha256": "2" * 64,
                    "bytes": 500_000_000, "files": 8,
                },
                "transcript": {
                    "language": "en", "text": "fixed transcript",
                    "normalized_text": "fixed transcript",
                },
                "words": [
                    {"text": "My", "start_ms": 0, "end_ms": 300,
                     "probability_millionths": 990_000},
                    {"text": "fellow", "start_ms": 300, "end_ms": 700,
                     "probability_millionths": 980_000},
                    {"text": "Americans", "start_ms": 700, "end_ms": 1200,
                     "probability_millionths": 970_000},
                ],
            }
            receipt_contract = dict(result)
            receipt_bytes = (
                json.dumps(
                    receipt_contract, ensure_ascii=True, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ) + "\n"
            ).encode("ascii")
            output.write_bytes(receipt_bytes)
            result["receipt"] = {
                "file": output.name,
                "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                "bytes": len(receipt_bytes),
            }
            probe = mock.Mock(return_value=result)
            environment = {
                "AUTOEDITOR_FFMPEG": str(ffmpeg),
                "AUTOEDITOR_WHISPER_SMALL": str(model),
            }
            argv = [
                "autoeditor-engine", "--asr-capability-self-test",
                str(output), str(work),
            ]
            stdout = io.StringIO()
            with mock.patch.object(
                    asr_runtime_probe, "run_asr_runtime_probe", probe), \
                    mock.patch.dict(os.environ, environment, clear=False), \
                    mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(stdout), \
                    self.assertRaises(SystemExit) as stopped:
                entry["main"]()
            self.assertEqual(stopped.exception.code, 0)
            probe.assert_called_once_with(
                output_path=str(output), work_dir=str(work),
                model_path=str(model), ffmpeg_path=str(ffmpeg),
            )
            event = json.loads(stdout.getvalue())
            self.assertEqual(set(event), {
                "event", "schema_version", "checks", "errors", "result",
            })
            self.assertEqual(
                event["event"],
                "autoeditor-engine-asr-capability-self-test",
            )
            self.assertEqual(event["schema_version"], SCHEMA)
            self.assertEqual(set(event["checks"]), CHECK_NAMES)
            self.assertTrue(all(event["checks"].values()))
            self.assertEqual(event["errors"], {})
            self.assertEqual(set(event["result"]), {
                "fixture", "model", "transcript", "words", "receipt",
            })
            self.assertEqual(event["result"], {
                key: result[key] for key in event["result"]
            })
            self.assertNotIn(str(root), stdout.getvalue())

    def test_missing_ffmpeg_identity_fails_closed(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"AUTOEDITOR_FFMPEG": ""},
                             clear=False), contextlib.redirect_stdout(stdout):
            status = entry["_asr_capability_self_test"]("out", "work")
        self.assertEqual(status, 1)
        event = json.loads(stdout.getvalue())
        self.assertEqual(event["result"], None)
        self.assertEqual(
            event["errors"], {"asr_runtime_probe": "RuntimeError"}
        )
        self.assertFalse(any(event["checks"].values()))


if __name__ == "__main__":
    unittest.main()
