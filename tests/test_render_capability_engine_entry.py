from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from autoeditor import render_capability_runtime_probe


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "autoeditor-render-capability-runtime-probe/v1"
EVENT = "autoeditor-engine-render-capability-self-test"
CHECK_NAMES = {
    "audio_crossfades",
    "color_normalization",
    "cross_dissolves",
    "motion_quality_analysis",
}


def _discover_ffmpeg_pair() -> tuple[Path, Path] | None:
    raw_ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "").strip()
    raw_ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "").strip()
    ffmpeg = Path(raw_ffmpeg).resolve() if raw_ffmpeg else None
    ffprobe = Path(raw_ffprobe).resolve() if raw_ffprobe else None
    if ffmpeg is None:
        system = shutil.which("ffmpeg")
        ffmpeg = Path(system).resolve() if system else None
    if ffprobe is None:
        system = shutil.which("ffprobe")
        ffprobe = Path(system).resolve() if system else None
    portable = (
        Path.home()
        / "Downloads"
        / "AutoEditor-Helper-0.1.2-Windows-x64-PORTABLE"
        / "resources"
        / "bin"
    )
    if ffmpeg is None and (portable / "ffmpeg.exe").is_file():
        ffmpeg = (portable / "ffmpeg.exe").resolve()
    if ffprobe is None and (portable / "ffprobe.exe").is_file():
        ffprobe = (portable / "ffprobe.exe").resolve()
    if ffmpeg is not None and ffprobe is None:
        suffix = ".exe" if ffmpeg.suffix.lower() == ".exe" else ""
        adjacent = ffmpeg.with_name(f"ffprobe{suffix}")
        if adjacent.is_file():
            ffprobe = adjacent.resolve()
    if (
        ffmpeg is None
        or ffprobe is None
        or not ffmpeg.is_file()
        or not ffprobe.is_file()
    ):
        return None
    return ffmpeg, ffprobe


class RenderCapabilityEngineEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pair = _discover_ffmpeg_pair()

    def real_probe(self, work: Path) -> tuple[dict, Path]:
        if self.pair is None:
            self.skipTest(
                "shipped/system FFmpeg and FFprobe were not discoverable"
            )
        ffmpeg, ffprobe = self.pair
        output = (
            work
            / render_capability_runtime_probe
            .RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE
        )
        result = (
            render_capability_runtime_probe
            .run_render_capability_runtime_probe(
                output_path=output,
                work_dir=work,
                ffmpeg_path=ffmpeg,
                ffprobe_path=ffprobe,
            )
        )
        return result, output

    def test_exact_cli_event_projects_only_verified_path_free_result(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(
            prefix="render-capability-engine-entry-"
        ) as raw:
            root = Path(raw).resolve()
            work = root / "work"
            work.mkdir()
            result, output = self.real_probe(work)
            ffmpeg, ffprobe = self.pair
            probe = mock.Mock(return_value=result)
            argv = [
                "autoeditor-engine",
                "--render-capability-self-test",
                str(output),
                str(work),
            ]
            environment = {
                "AUTOEDITOR_FFMPEG": str(ffmpeg),
                "AUTOEDITOR_FFPROBE": str(ffprobe),
            }
            stdout = io.StringIO()
            with mock.patch.object(
                    render_capability_runtime_probe,
                    "run_render_capability_runtime_probe", probe), \
                    mock.patch.dict(os.environ, environment, clear=False), \
                    mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(stdout), \
                    self.assertRaises(SystemExit) as stopped:
                entry["main"]()
            self.assertEqual(stopped.exception.code, 0)
            probe.assert_called_once_with(
                output_path=str(output),
                work_dir=str(work),
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
                "scope", "fixture", "runtime", "production", "artifact",
                "evidence", "receipt",
            })
            self.assertEqual(event["result"], {
                key: result[key] for key in event["result"]
            })
            self.assertNotIn(str(root), stdout.getvalue())

    def test_missing_tool_identity_fails_closed_with_all_checks_false(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {
            "AUTOEDITOR_FFMPEG": "",
            "AUTOEDITOR_FFPROBE": "",
        }, clear=False), contextlib.redirect_stdout(stdout):
            status = entry["_render_capability_self_test"]("out", "work")
        self.assertEqual(status, 1)
        event = json.loads(stdout.getvalue())
        self.assertEqual(set(event), {
            "event", "schema_version", "checks", "errors", "result",
        })
        self.assertEqual(event["event"], EVENT)
        self.assertEqual(event["schema_version"], SCHEMA)
        self.assertEqual(set(event["checks"]), CHECK_NAMES)
        self.assertFalse(any(event["checks"].values()))
        self.assertEqual(event["result"], None)
        self.assertEqual(event["errors"], {
            "render_capability_runtime_probe": "RuntimeError",
        })

    def test_result_or_receipt_tamper_fails_closed(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging" / "engine_entry.py"))
        with tempfile.TemporaryDirectory(
            prefix="render-capability-engine-tamper-"
        ) as raw:
            root = Path(raw).resolve()
            work = root / "work"
            work.mkdir()
            result, output = self.real_probe(work)
            changed = {
                key: value for key, value in result.items()
            }
            changed["artifact"] = dict(result["artifact"])
            changed["artifact"]["video_frames"] += 1
            ffmpeg, ffprobe = self.pair
            environment = {
                "AUTOEDITOR_FFMPEG": str(ffmpeg),
                "AUTOEDITOR_FFPROBE": str(ffprobe),
            }
            stdout = io.StringIO()
            with mock.patch.object(
                    render_capability_runtime_probe,
                    "run_render_capability_runtime_probe",
                    return_value=changed), \
                    mock.patch.dict(os.environ, environment, clear=False), \
                    contextlib.redirect_stdout(stdout):
                status = entry["_render_capability_self_test"](
                    str(output), str(work)
                )
            self.assertEqual(status, 1)
            event = json.loads(stdout.getvalue())
            self.assertFalse(any(event["checks"].values()))
            self.assertEqual(event["result"], None)
            self.assertEqual(event["errors"], {
                "render_capability_runtime_probe": "RuntimeError",
            })


if __name__ == "__main__":
    unittest.main()
