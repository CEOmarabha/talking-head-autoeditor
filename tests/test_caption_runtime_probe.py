from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autoeditor import pipeline


ROOT = Path(__file__).resolve().parents[1]
WORK_SANS = ROOT / "desktop/helper/renderer/WorkSans-Variable.ttf"


def _tool(environment_name: str, executable: str) -> str | None:
    configured = os.environ.get(environment_name)
    if configured and Path(configured).is_file():
        return configured
    return shutil.which(executable)


class CaptionRuntimeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffmpeg = _tool("AUTOEDITOR_FFMPEG", "ffmpeg")
        cls.ffprobe = _tool("AUTOEDITOR_FFPROBE", "ffprobe")
        try:
            from PIL import Image  # noqa: F401
            cls.pillow_available = True
        except ImportError:
            cls.pillow_available = False

    def setUp(self) -> None:
        if not self.ffmpeg or not self.ffprobe or not self.pillow_available:
            self.skipTest("caption probe requires FFmpeg, FFprobe, and Pillow")
        self.old_ffmpeg = pipeline.FFMPEG
        self.old_ffprobe = pipeline.FFPROBE
        pipeline.FFMPEG = self.ffmpeg
        pipeline.FFPROBE = self.ffprobe

    def tearDown(self) -> None:
        if hasattr(self, "old_ffmpeg"):
            pipeline.FFMPEG = self.old_ffmpeg
            pipeline.FFPROBE = self.old_ffprobe

    def _source(self, root: Path) -> Path:
        source = root / "caption-source.mp4"
        subprocess.run([
            self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-y", "-f", "lavfi", "-i",
            "color=c=0x203040:s=180x320:r=30:d=2.000",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", source,
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return source

    def test_real_fixed_word_overlay_receipt_and_pixels(self) -> None:
        with tempfile.TemporaryDirectory(prefix="caption-probe-test-") as raw:
            root = Path(raw)
            source = self._source(root)
            output = root / "caption-rendered.mp4"
            result = pipeline.write_caption_render_probe(
                source, output, root, WORK_SANS
            )
            self.assertEqual(
                (result["duration_ms"], result["width"], result["height"],
                 result["fps_milli"], result["caption_y"],
                 result["band_height"]),
                (2000, 180, 320, 30000, 26, 61),
            )
            self.assertEqual(
                result["output_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )
            receipt_path = Path(result["caption_receipt"])
            self.assertEqual(
                result["caption_receipt_sha256"],
                hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema"],
                             "autoeditor-caption-render-receipt/v1")
            self.assertEqual(receipt["renderer"], "karaoke-band")
            self.assertEqual(receipt["events"], [{
                "index": 1, "start_seconds": 0.35,
                "end_seconds": 1.25, "text": "CUT IT NOW",
                "state_count": 3,
            }])
            hashes = result["pixel_evidence"]["frame_sha256"]
            self.assertEqual(hashes["blank_before"], hashes["blank_after"])
            self.assertEqual(len(set(hashes.values())), 4)
            self.assertTrue(receipt["mechanical_qa"]["pixel_quality"]["ok"])

    def test_omitted_or_blank_overlay_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="caption-blank-test-") as raw:
            source = self._source(Path(raw))
            with self.assertRaisesRegex(
                    RuntimeError, "did not prove the burned timed overlay"):
                pipeline.verify_caption_render_probe_pixels(
                    source, caption_y=26, band_height=61
                )

    def test_missing_bundled_font_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="caption-font-test-") as raw:
            root = Path(raw)
            source = root / "caption-source.mp4"
            source.write_bytes(b"not reached because font validation is first")
            with self.assertRaisesRegex(RuntimeError, "WorkSans"):
                pipeline.write_caption_render_probe(
                    source, root / "caption-rendered.mp4", root,
                    root / "WorkSans-Variable.ttf",
                )

    def test_engine_event_binds_output_receipt_font_and_pixel_evidence(self) -> None:
        entry = runpy.run_path(str(ROOT / "packaging/engine_entry.py"))
        with tempfile.TemporaryDirectory(prefix="caption-engine-test-") as raw:
            root = Path(raw)
            source = self._source(root)
            output = root / "caption-rendered.mp4"
            stream = io.StringIO()
            with mock.patch.dict(os.environ, {
                    "AUTOEDITOR_BUNDLED_FONTS": str(WORK_SANS.parent),
                    "AUTOEDITOR_PROGRESS_JSON": "1",
            }, clear=False), contextlib.redirect_stdout(stream):
                status = entry["_caption_render_self_test"](
                    str(source), str(output), str(root)
                )
            self.assertEqual(status, 0)
            events = []
            for line in stream.getvalue().splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if value.get("event") == \
                        "autoeditor-engine-caption-render-self-test":
                    events.append(value)
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertTrue(all(event["checks"].values()))
            self.assertEqual(event["errors"], {})
            self.assertEqual(event["result"]["artifact"]["sha256"],
                             hashlib.sha256(output.read_bytes()).hexdigest())
            receipt = root / "CAPTION_RENDER_RECEIPT.json"
            self.assertEqual(
                event["result"]["caption_receipt"]["sha256"],
                hashlib.sha256(receipt.read_bytes()).hexdigest(),
            )
            self.assertEqual(event["result"]["font"]["file"],
                             "WorkSans-Variable.ttf")


if __name__ == "__main__":
    unittest.main()
