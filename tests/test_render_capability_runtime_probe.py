from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from autoeditor.color_contract import source_color_conversion_filter
from autoeditor.render_capability_runtime_probe import (
    RENDER_CAPABILITY_CHECK_NAMES,
    RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE,
    RENDER_CAPABILITY_RUNTIME_PROBE_FILTER_FILE,
    RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE,
    RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION,
    RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE,
    RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_B_FILE,
    RenderCapabilityRuntimeProbeError,
    SOURCE_A_COLOR,
    run_render_capability_runtime_probe,
    verify_render_capability_runtime_probe_receipt,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discover_ffmpeg_pair() -> tuple[Path, Path] | None:
    configured_ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "").strip()
    configured_ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "").strip()
    ffmpeg = Path(configured_ffmpeg) if configured_ffmpeg else None
    ffprobe = Path(configured_ffprobe) if configured_ffprobe else None
    if ffmpeg is None:
        system = shutil.which("ffmpeg")
        ffmpeg = Path(system) if system else None
    if ffprobe is None:
        system = shutil.which("ffprobe")
        ffprobe = Path(system) if system else None

    portable_root = (
        Path.home()
        / "Downloads"
        / "AutoEditor-Helper-0.1.2-Windows-x64-PORTABLE"
        / "resources"
        / "bin"
    )
    if ffmpeg is None and (portable_root / "ffmpeg.exe").is_file():
        ffmpeg = portable_root / "ffmpeg.exe"
    if ffprobe is None and (portable_root / "ffprobe.exe").is_file():
        ffprobe = portable_root / "ffprobe.exe"
    if ffmpeg is not None and ffprobe is None:
        suffix = ".exe" if ffmpeg.suffix.lower() == ".exe" else ""
        adjacent = ffmpeg.with_name(f"ffprobe{suffix}")
        if adjacent.is_file():
            ffprobe = adjacent
    if (
        ffmpeg is None
        or ffprobe is None
        or not ffmpeg.is_file()
        or not ffprobe.is_file()
    ):
        return None
    return ffmpeg.resolve(), ffprobe.resolve()


class RenderCapabilityRuntimeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pair = _discover_ffmpeg_pair()
        if pair is None:
            raise unittest.SkipTest(
                "shipped/system FFmpeg and FFprobe were not discoverable"
            )
        cls.ffmpeg, cls.ffprobe = pair

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="render-capability-probe-")
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_probe(self, **overrides):
        values = {
            "output_path": self.output,
            "work_dir": self.root,
            "ffmpeg_path": self.ffmpeg,
            "ffprobe_path": self.ffprobe,
        }
        values.update(overrides)
        return run_render_capability_runtime_probe(**values)

    def assert_workdir_clean(self) -> None:
        self.assertEqual(list(self.root.iterdir()), [])

    def test_real_production_render_proves_narrow_capabilities_and_receipt(self):
        commands: list[list[str]] = []

        def execute(command, **kwargs):
            commands.append(list(command))
            return subprocess.run(command, **kwargs)

        result = self.run_probe(_execute=execute)
        production = [
            command for command in commands
            if "-filter_complex_script" in command
        ]
        self.assertEqual(len(production), 1)
        complex_position = production[0].index("-filter_complex_threads")
        self.assertEqual(
            production[0][complex_position:complex_position + 2],
            ["-filter_complex_threads", "1"],
        )
        self.assertLess(complex_position, production[0].index("-i"))
        normalized_decodes = [
            command for command in commands
            if "-vf" in command
            and "dither=fsb" in command[command.index("-vf") + 1]
        ]
        self.assertEqual(len(normalized_decodes), 3)
        for command in normalized_decodes:
            thread_position = command.index("-filter_threads")
            self.assertEqual(command[thread_position:thread_position + 2], [
                "-filter_threads", "1",
            ])
            self.assertEqual(command.count("-filter_threads"), 1)
            self.assertLess(thread_position, command.index("-i"))
        self.assertEqual(
            result["schema_version"],
            RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION,
        )
        self.assertEqual(set(result["checks"]), RENDER_CAPABILITY_CHECK_NAMES)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["scope"], {
            "audio": "fixed-440hz-to-880hz-qsin-overlap-48000hz-stereo",
            "color": "declared-bt470bg-tv-sdr-to-bt709-tv-yuv420p",
            "motion": (
                "fixed-decoded-frame-blend-progression-and-no-black-flash"
            ),
            "transition": "single-400ms-xfade-fade-at-30000-1001fps",
            "unsupported": [
                "hdr", "optical_flow", "arbitrary_transition_quality",
            ],
        })

        fixture = result["fixture"]
        self.assertEqual(fixture["frame_rate"], {
            "numerator": 30_000, "denominator": 1_001,
        })
        self.assertEqual(fixture["geometry"], {"width": 160, "height": 90})
        self.assertEqual(fixture["source_selection_ms"], 3_000)
        self.assertEqual(fixture["transition_duration_ms"], 400)
        self.assertEqual(
            fixture["sources"][0]["color"],
            {
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "color_range": "tv",
                "color_space": "bt470bg",
                "color_transfer": "bt470bg",
                "color_primaries": "bt470bg",
            },
        )
        fixture_without_hash = {
            key: value for key, value in fixture.items() if key != "sha256"
        }
        self.assertEqual(
            fixture["sha256"],
            hashlib.sha256(json.dumps(
                fixture_without_hash,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("ascii")).hexdigest(),
        )

        artifact = result["artifact"]
        self.assertEqual(artifact["file"],
                         RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE)
        self.assertEqual(artifact["video_frames"], 168)
        self.assertEqual(artifact["frame_rate"], {
            "numerator": 30_000, "denominator": 1_001,
        })
        self.assertEqual(artifact["audio"], {
            "sample_rate": 48_000, "channels": 2,
        })
        self.assertLessEqual(artifact["av_drift_us"], 34_000)
        self.assertEqual(artifact["delivery_color"], {
            "range": "tv",
            "space": "bt709",
            "transfer": "bt709",
            "primaries": "bt709",
            "pixel_format": "yuv420p",
        })

        color = result["evidence"]["color"]
        self.assertEqual(color["normalization_mode"],
                         "declared_sdr_to_bt709_tv")
        self.assertGreater(color["source_to_normalized_mae_millionths"],
                           5_000)
        self.assertLess(color["artifact_to_reference_mae_millionths"],
                        35_000)
        self.assertNotEqual(color["source_yuv_sha256"],
                            color["normalized_reference_yuv_sha256"])

        transition = result["evidence"]["transition"]
        self.assertEqual(
            (transition["kind"], transition["duration_ms"],
             transition["duration_frames"], transition["start_frame"]),
            ("cross_dissolve", 400, 12, 78),
        )
        weights = transition["estimated_right_weights_millionths"]
        self.assertLess(weights[0], 200_000)
        self.assertGreater(weights[-1], 700_000)
        self.assertLess(transition["max_black_pixel_ratio_millionths"],
                        100_000)
        self.assertEqual(
            len({
                transition["before"]["sha256"],
                transition["middle"]["sha256"],
                transition["after"]["sha256"],
            }),
            3,
        )

        audio = result["evidence"]["audio_crossfade"]
        self.assertEqual(audio["behavior"], "equal_power_qsin")
        self.assertGreater(audio["middle"]["tone_440_millionths"], 20_000)
        self.assertGreater(audio["middle"]["tone_880_millionths"], 20_000)
        self.assertLess(
            audio["before"]["tone_880_millionths"],
            audio["before"]["tone_440_millionths"] // 5,
        )
        self.assertLess(
            audio["after"]["tone_440_millionths"],
            audio["after"]["tone_880_millionths"] // 5,
        )

        self.assertEqual(result["runtime"]["ffmpeg"]["sha256"],
                         _sha256_file(self.ffmpeg))
        self.assertEqual(result["runtime"]["ffprobe"]["sha256"],
                         _sha256_file(self.ffprobe))
        receipt_bytes = self.output.read_bytes()
        self.assertEqual(result["receipt"], {
            "file": RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE,
            "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "bytes": len(receipt_bytes),
        })
        clean = verify_render_capability_runtime_probe_receipt(
            receipt_bytes, result["receipt"]["sha256"]
        )
        self.assertEqual(clean, {
            key: value for key, value in result.items() if key != "receipt"
        })
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(str(self.ffmpeg), serialized)
        self.assertNotIn(str(self.ffprobe), serialized)
        self.assertEqual([item.name for item in self.root.iterdir()], [
            RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE,
        ])

    def test_relabel_only_color_graph_is_rejected_by_decoded_pixels(self):
        token = source_color_conversion_filter(SOURCE_A_COLOR)

        def relabel_only(graph: str) -> str:
            self.assertEqual(graph.count(token), 1)
            return graph.replace(token, "null", 1)

        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "color normalization pixels",
        ):
            self.run_probe(_filter_graph_mutator=relabel_only)
        self.assert_workdir_clean()

    def test_omitted_xfade_is_rejected_by_blend_progression(self):
        token = "xfade=transition=fade:duration=0.400:offset=2.600"

        def omit_xfade(graph: str) -> str:
            self.assertEqual(graph.count(token), 1)
            return graph.replace(token, "concat=n=2:v=1:a=0", 1)

        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "cross-dissolve blend progression",
        ):
            self.run_probe(_filter_graph_mutator=omit_xfade)
        self.assert_workdir_clean()

    def test_omitted_acrossfade_is_rejected_by_decoded_tone_overlap(self):
        token = "acrossfade=d=0.400:o=1:c1=qsin:c2=qsin"

        def omit_acrossfade(graph: str) -> str:
            self.assertEqual(graph.count(token), 1)
            return graph.replace(token, "concat=n=2:v=0:a=1", 1)

        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "equal-power audio overlap",
        ):
            self.run_probe(_filter_graph_mutator=omit_acrossfade)
        self.assert_workdir_clean()

    def test_unsupported_hdr_source_declaration_fails_before_render(self):
        hdr = copy.deepcopy(SOURCE_A_COLOR)
        hdr.update({
            "pix_fmt": "yuv420p10le",
            "color_space": "bt2020nc",
            "color_transfer": "smpte2084",
            "color_primaries": "bt2020",
        })
        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "unsupported or HDR",
        ):
            self.run_probe(_source_a_color=hdr)
        self.assert_workdir_clean()

    def test_tampered_receipt_fails_hash_and_semantic_checks(self):
        result = self.run_probe()
        original = self.output.read_bytes()
        tampered = original.replace(
            b'"color_normalization":true',
            b'"color_normalization":false',
            1,
        )
        self.assertNotEqual(tampered, original)
        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "receipt hash does not match",
        ):
            verify_render_capability_runtime_probe_receipt(
                tampered, result["receipt"]["sha256"]
            )
        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "unproved capability",
        ):
            verify_render_capability_runtime_probe_receipt(
                tampered, hashlib.sha256(tampered).hexdigest()
            )

    def test_receipt_and_reserved_files_are_exclusive_and_never_overwritten(self):
        self.output.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "new fixed file",
        ):
            self.run_probe()
        self.assertEqual(self.output.read_bytes(), b"do-not-overwrite")
        self.output.unlink()

        reserved = self.root / RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE
        reserved.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "reserved probe file",
        ):
            self.run_probe()
        self.assertEqual(reserved.read_bytes(), b"do-not-overwrite")

        reserved.unlink()
        wrong_output = self.root / "other.json"
        with self.assertRaisesRegex(
            RenderCapabilityRuntimeProbeError,
            "new fixed file",
        ):
            self.run_probe(output_path=wrong_output)
        self.assertFalse(wrong_output.exists())

        for file_name in (
            RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_A_FILE,
            RENDER_CAPABILITY_RUNTIME_PROBE_SOURCE_B_FILE,
            RENDER_CAPABILITY_RUNTIME_PROBE_ARTIFACT_FILE,
            RENDER_CAPABILITY_RUNTIME_PROBE_FILTER_FILE,
        ):
            self.assertFalse((self.root / file_name).exists())


if __name__ == "__main__":
    unittest.main()
