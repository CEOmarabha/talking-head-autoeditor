import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autoeditor import pipeline
from autoeditor.sequence_plan import (
    SEQUENCE_PLAN_SCHEMA_VERSION, SOURCE_MANIFEST_SCHEMA_VERSION,
    compile_sequence_plan,
)
from autoeditor.sequence_render import (
    SOURCE_RENDER_MANIFEST_SCHEMA_VERSION, build_sequence_render,
)
from autoeditor.story_qa import check_final_duration


_DAEMON_PATH = Path(__file__).resolve().parents[1] / "packaging" / (
    "helper_daemon_entry.py"
)
_DAEMON_SPEC = importlib.util.spec_from_file_location(
    "autoeditor_helper_daemon_entry", _DAEMON_PATH
)
assert _DAEMON_SPEC and _DAEMON_SPEC.loader
helper_daemon_entry = importlib.util.module_from_spec(_DAEMON_SPEC)
_DAEMON_SPEC.loader.exec_module(helper_daemon_entry)


SOURCE_DURATION = 174.9

_DECLARED_BT709_VIDEO = {
    "codec_name": "h264", "pix_fmt": "yuv420p", "color_range": "tv",
    "color_space": "bt709", "color_transfer": "bt709",
    "color_primaries": "bt709",
}
_UNTAGGED_H264_PROBE = {
    "codec_name": "h264", "pix_fmt": "yuv420p",
}


def _words():
    return [
        {
            "w": f"word{index}",
            "s": round(index * 0.4, 3),
            "e": round((index + 1) * 0.4, 3),
        }
        for index in range(417)
    ]


def _anchor(words, start, end):
    return " ".join(word["w"] for word in words[start:end + 1])


def _plan():
    words = _words()
    return {
        "schema_version": "autoeditor-story-edit/v1",
        "timeline": "source_seconds",
        "target_duration": {"min_seconds": 35.0, "max_seconds": 45.0},
        "hook_anchor_id": "hook",
        "closer_anchor_id": "closer",
        "keep_ranges": [
            {
                "anchor_id": "hook",
                "anchor_text": _anchor(words, 50, 99),
                "source_start_word": 50,
                "source_end_word": 99,
                "source_start_seconds": 20.0,
                "source_end_seconds": 40.0,
            },
            {
                "anchor_id": "closer",
                "anchor_text": _anchor(words, 300, 349),
                "source_start_word": 300,
                "source_end_word": 349,
                "source_start_seconds": 120.0,
                "source_end_seconds": 140.0,
            },
        ],
    }


def _creative_constraints():
    return {
        "schema_version": "autoeditor-creative-constraints/v1",
        "opener": {
            "exact_text": "word50 word51 word52",
            "max_start_seconds": 3.0,
        },
        "visual_policy": {
            "graphics_exact": 1,
            "broll_exact": 0,
            "opening_punch_required": True,
            "opening_visual_required": False,
            "max_visual_gap_seconds": None,
        },
        "required_graphic": {
            "kind": "callout",
            "text": "WORD300 VS WORD301",
            "anchor_text": "word300 word301 word302 word303 word304",
        },
        "music_allowed": False,
    }


def _discover_ffmpeg_pair() -> tuple[str, str] | None:
    ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "").strip()
    ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "").strip()
    ffmpeg = ffmpeg if ffmpeg and Path(ffmpeg).is_file() else (
        shutil.which("ffmpeg") or ""
    )
    ffprobe = ffprobe if ffprobe and Path(ffprobe).is_file() else (
        shutil.which("ffprobe") or ""
    )
    if ffmpeg and not ffprobe:
        suffix = ".exe" if Path(ffmpeg).suffix.lower() == ".exe" else ""
        adjacent = Path(ffmpeg).with_name(f"ffprobe{suffix}")
        if adjacent.is_file():
            ffprobe = str(adjacent)
    if not ffmpeg or not ffprobe:
        return None
    return str(Path(ffmpeg).resolve()), str(Path(ffprobe).resolve())


class ApprovedStoryPipelineContractTests(unittest.TestCase):
    def test_baseline_join_normalizes_mixed_audio_and_exact_silence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ffmpeg = root / "ffmpeg.exe"
            ffprobe = root / "ffprobe.exe"
            ffmpeg.write_bytes(b"stub")
            ffprobe.write_bytes(b"stub")
            audible = root / "audible.mov"
            silent = root / "silent.webm"
            audible.write_bytes(b"audible")
            silent.write_bytes(b"silent")
            facts = [
                {
                    "duration_ms": 1_250,
                    "video": {
                        **_DECLARED_BT709_VIDEO,
                        "width": 640, "height": 360,
                        "fps_numerator": 24, "fps_denominator": 1,
                        "start_offset_ms": 0, "duration_ms": 1_250,
                        "end_offset_ms": 1_250,
                    },
                    "audio": {
                        "present": True, "sample_rate": 44_100, "channels": 1,
                        "start_offset_ms": 250, "duration_ms": 750,
                        "end_offset_ms": 1_000,
                    },
                },
                {
                    "duration_ms": 1_750,
                    "video": {
                        **_DECLARED_BT709_VIDEO,
                        "width": 1280, "height": 720,
                        "fps_numerator": 60, "fps_denominator": 1,
                        "start_offset_ms": 0, "duration_ms": 1_750,
                        "end_offset_ms": 1_750,
                    },
                    "audio": {
                        "present": False, "sample_rate": None, "channels": None,
                        "start_offset_ms": None, "duration_ms": None,
                        "end_offset_ms": None,
                    },
                },
            ]
            facts[0]["video"].update({
                "color_space": "bt470bg",
                "color_transfer": "bt470bg",
                "color_primaries": "bt470bg",
            })
            captured: list[list[str]] = []

            def render(argv, **kwargs):
                captured.append(list(argv))
                Path(argv[-1]).write_bytes(b"joined")
                self.assertIs(kwargs["shell"], False)
                return mock.Mock(returncode=0, stderr="")

            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {
                        "AUTOEDITOR_FFMPEG": str(ffmpeg),
                        "AUTOEDITOR_FFPROBE": str(ffprobe),
                    }), mock.patch.object(
                        helper_daemon_entry, "_probe_sequence_source",
                        side_effect=copy.deepcopy(facts)) as probe, mock.patch.object(
                            helper_daemon_entry.subprocess, "run",
                            side_effect=render):
                output = helper_daemon_entry._join_local_inputs(
                    [audible, silent], "commercial", root
                )

        self.assertEqual(output.name, "joined-input.mp4")
        self.assertEqual(probe.call_args_list, [mock.call(audible), mock.call(silent)])
        self.assertEqual(len(captured), 1)
        argv = captured[0]
        thread_position = argv.index("-filter_complex_threads")
        self.assertEqual(argv[thread_position:thread_position + 2], [
            "-filter_complex_threads", "1",
        ])
        self.assertEqual(argv.count("-filter_complex_threads"), 1)
        self.assertLess(thread_position, argv.index("-i"))
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn(
            "[0:v:0]setpts=PTS-STARTPTS,trim=duration=1.250,"
            "setpts=PTS-STARTPTS,"
            "colorspace=ispace=bt470bg:itrc=bt470bg:iprimaries=bt470bg:"
            "irange=tv:all=bt709:range=tv:format=yuv420p:"
            "fast=0:dither=fsb,scale=1080:1920:",
            graph,
        )
        self.assertIn(
            "[1:v:0]setpts=PTS-STARTPTS,trim=duration=1.750,"
            "setpts=PTS-STARTPTS,"
            "colorspace=ispace=bt709:itrc=bt709:iprimaries=bt709:"
            "irange=tv:all=bt709:range=tv:format=yuv420p:"
            "fast=0:dither=fsb",
            graph,
        )
        self.assertIn(
            "[0:a:0]asetpts=PTS-STARTPTS,atrim=start=0.000:duration=0.750,"
            "asetpts=PTS-STARTPTS,aresample=48000:async=0:first_pts=0,"
            "aformat=sample_rates=48000:channel_layouts=stereo,"
            "adelay=250:all=1,apad=whole_len=60000,"
            "atrim=end_sample=60000,asetpts=PTS-STARTPTS[a0]",
            graph,
        )
        self.assertIn(
            "anullsrc=channel_layout=stereo:sample_rate=48000,"
            "atrim=end_sample=84000,asetpts=PTS-STARTPTS[a1]",
            graph,
        )
        self.assertNotIn("[1:a", graph)
        self.assertIn("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]", graph)
        self.assertEqual(argv[argv.index("-ar") + 1], "48000")
        self.assertEqual(argv[argv.index("-ac") + 1], "2")
        self.assertEqual(argv[argv.index("-color_range") + 1], "tv")
        self.assertEqual(argv[argv.index("-color_primaries") + 1], "bt709")
        self.assertEqual(argv[argv.index("-color_trc") + 1], "bt709")
        self.assertEqual(argv[argv.index("-colorspace") + 1], "bt709")

    def test_baseline_join_trims_early_audio_to_the_video_timeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ffmpeg = root / "ffmpeg.exe"
            ffprobe = root / "ffprobe.exe"
            ffmpeg.write_bytes(b"stub")
            ffprobe.write_bytes(b"stub")
            inputs = [root / "first.mp4", root / "second.mp4"]
            for path in inputs:
                path.write_bytes(path.name.encode("ascii"))
            early_audio = {
                "duration_ms": 2_000,
                "video": {
                    **_DECLARED_BT709_VIDEO,
                    "width": 640, "height": 360,
                    "fps_numerator": 30, "fps_denominator": 1,
                    "start_offset_ms": 500, "duration_ms": 1_000,
                    "end_offset_ms": 1_500,
                },
                "audio": {
                    "present": True, "sample_rate": 48_000, "channels": 6,
                    "start_offset_ms": 0, "duration_ms": 2_000,
                    "end_offset_ms": 2_000,
                },
            }
            graphs: list[str] = []

            def render(argv, **_kwargs):
                graphs.append(argv[argv.index("-filter_complex") + 1])
                Path(argv[-1]).write_bytes(b"joined")
                return mock.Mock(returncode=0, stderr="")

            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {
                        "AUTOEDITOR_FFMPEG": str(ffmpeg),
                        "AUTOEDITOR_FFPROBE": str(ffprobe),
                    }), mock.patch.object(
                        helper_daemon_entry, "_probe_sequence_source",
                        side_effect=[copy.deepcopy(early_audio),
                                     copy.deepcopy(early_audio)]), mock.patch.object(
                            helper_daemon_entry.subprocess, "run",
                            side_effect=render):
                helper_daemon_entry._join_local_inputs(inputs, "long", root)

        self.assertIn(
            "atrim=start=0.500:duration=1.000,asetpts=PTS-STARTPTS,"
            "aresample=48000:async=0:first_pts=0,"
            "aformat=sample_rates=48000:channel_layouts=stereo,"
            "apad=whole_len=48000,atrim=end_sample=48000",
            graphs[0],
        )
        self.assertNotIn("adelay=", graphs[0])

    def test_real_baseline_join_handles_audio_then_no_audio(self):
        tools = _discover_ffmpeg_pair()
        if tools is None:
            self.skipTest("bundled/system FFmpeg and FFprobe are unavailable")
        ffmpeg, ffprobe = tools
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audible = root / "audible.mp4"
            silent = root / "silent.mp4"
            generation_commands = [
                [
                    ffmpeg, "-y", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=0.400",
                    "-f", "lavfi", "-i",
                    "sine=frequency=1000:sample_rate=44100:duration=0.400",
                    "-map", "0:v:0", "-map", "1:a:0", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(audible),
                ],
                [
                    ffmpeg, "-y", "-v", "error",
                    "-f", "lavfi", "-i",
                    "color=c=blue:s=320x180:r=30:d=0.500",
                    "-an", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", str(silent),
                ],
            ]
            for command in generation_commands:
                generated = subprocess.run(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", shell=False,
                )
                self.assertEqual(generated.returncode, 0, generated.stderr)
            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {
                        "AUTOEDITOR_FFMPEG": ffmpeg,
                        "AUTOEDITOR_FFPROBE": ffprobe,
                    }):
                input_duration = sum(
                    helper_daemon_entry._probe_sequence_source(path)["video"][
                        "duration_ms"
                    ]
                    for path in (audible, silent)
                )
                output = helper_daemon_entry._join_local_inputs(
                    [audible, silent], "long", root
                )
                output_facts = helper_daemon_entry._probe_sequence_source(output)

            self.assertEqual(output_facts["video"]["width"], 1920)
            self.assertEqual(output_facts["video"]["height"], 1080)
            self.assertTrue(output_facts["audio"]["present"])
            self.assertEqual(output_facts["audio"]["sample_rate"], 48_000)
            self.assertEqual(output_facts["audio"]["channels"], 2)
            self.assertLessEqual(
                abs(output_facts["duration_ms"] - input_duration), 100
            )

            silence_start = 0.5
            measured = subprocess.run(
                [
                    ffmpeg, "-v", "info", "-ss", f"{silence_start:.3f}",
                    "-i", str(output), "-t", "0.200", "-map", "0:a:0",
                    "-af", "volumedetect", "-f", "null", "-",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", shell=False,
            )
            self.assertEqual(measured.returncode, 0, measured.stderr)
            match = re.search(
                r"max_volume:\s+(-inf|-?[0-9]+(?:\.[0-9]+)?)\s+dB",
                measured.stderr,
            )
            self.assertIsNotNone(match, measured.stderr)
            if match and match.group(1) != "-inf":
                self.assertLessEqual(float(match.group(1)), -60.0)

    def test_real_color_probe_join_and_hdr_rejection(self):
        tools = _discover_ffmpeg_pair()
        if tools is None:
            self.skipTest("bundled/system FFmpeg and FFprobe are unavailable")
        ffmpeg, ffprobe = tools
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bt470 = root / "bt470.mp4"
            bt709 = root / "bt709.mp4"
            legacy_mjpeg = root / "legacy.mov"
            hdr = root / "hdr.mp4"
            commands = [
                [
                    ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=0.350", "-an",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-color_range", "tv",
                    "-color_primaries", "bt470bg", "-color_trc", "bt470bg",
                    "-colorspace", "bt470bg", "-bsf:v",
                    "h264_metadata=colour_primaries=5:"
                    "transfer_characteristics=5:matrix_coefficients=5:"
                    "video_full_range_flag=0", str(bt470),
                ],
                [
                    ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=0.450", "-an",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-color_range", "tv",
                    "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-colorspace", "bt709", "-bsf:v",
                    "h264_metadata=colour_primaries=1:"
                    "transfer_characteristics=1:matrix_coefficients=1:"
                    "video_full_range_flag=0", str(bt709),
                ],
                [
                    ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=0.300", "-an",
                    "-c:v", "mjpeg", "-q:v", "3", "-pix_fmt", "yuvj420p",
                    "-color_range", "pc", "-colorspace", "bt470bg",
                    str(legacy_mjpeg),
                ],
                [
                    ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=0.300", "-an",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-color_range", "tv",
                    "-color_primaries", "bt2020", "-color_trc", "smpte2084",
                    "-colorspace", "bt2020nc", "-bsf:v",
                    "h264_metadata=colour_primaries=9:"
                    "transfer_characteristics=16:matrix_coefficients=9:"
                    "video_full_range_flag=0", str(hdr),
                ],
            ]
            for command in commands:
                generated = subprocess.run(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", shell=False,
                )
                self.assertEqual(generated.returncode, 0, generated.stderr)

            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {
                        "AUTOEDITOR_FFMPEG": ffmpeg,
                        "AUTOEDITOR_FFPROBE": ffprobe,
                    }):
                bt470_facts = helper_daemon_entry._probe_sequence_source(bt470)
                self.assertEqual(bt470_facts["video"]["color_space"], "bt470bg")
                self.assertEqual(
                    bt470_facts["video"]["color_transfer"], "bt470bg"
                )
                jpeg_facts = helper_daemon_entry._probe_sequence_source(
                    legacy_mjpeg
                )
                self.assertEqual(jpeg_facts["video"]["codec_name"], "mjpeg")
                self.assertEqual(jpeg_facts["video"]["pix_fmt"], "yuvj420p")
                self.assertEqual(jpeg_facts["video"]["color_space"], "bt470bg")
                self.assertEqual(jpeg_facts["video"]["color_transfer"], "unknown")
                self.assertEqual(jpeg_facts["video"]["color_primaries"], "unknown")
                with self.assertRaisesRegex(
                        RuntimeError, "invalid technical metadata"):
                    helper_daemon_entry._probe_sequence_source(hdr)

                output = helper_daemon_entry._join_local_inputs(
                    [bt470, bt709], "long", root
                )
                output_facts = helper_daemon_entry._probe_sequence_source(output)

            self.assertEqual(output_facts["video"]["codec_name"], "h264")
            self.assertEqual(output_facts["video"]["pix_fmt"], "yuv420p")
            self.assertEqual(output_facts["video"]["color_range"], "tv")
            self.assertEqual(output_facts["video"]["color_space"], "bt709")
            self.assertEqual(output_facts["video"]["color_transfer"], "bt709")
            self.assertEqual(output_facts["video"]["color_primaries"], "bt709")
            self.assertLessEqual(abs(output_facts["duration_ms"] - 800), 100)

    def test_pipeline_rejects_silence_claim_for_sources_with_real_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "approved-sequence.mp4"
            source.write_bytes(b"compiled-artifact")
            source_a = {
                "source_id": "a", "sha256": "a" * 64,
                "duration_ms": 5_000,
            }
            source_b = {
                "source_id": "b", "sha256": "b" * 64,
                "duration_ms": 5_000,
            }
            source_manifest = {
                "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
                "sources": [source_a, source_b],
            }
            plan = {
                "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
                "sources": [source_a, source_b],
                "target_duration": {"min_ms": 5_000, "max_ms": 5_000},
                "segments": [
                    {
                        "segment_id": "a-part", "source_id": "a",
                        "source_sha256": "a" * 64,
                        "source_start_ms": 0, "source_end_ms": 2_500,
                        "role": "hook", "reason": "First approved source.",
                        "speech_anchor": None,
                        "transition": {"kind": "hard_cut"},
                    },
                    {
                        "segment_id": "b-part", "source_id": "b",
                        "source_sha256": "b" * 64,
                        "source_start_ms": 0, "source_end_ms": 2_500,
                        "role": "closer", "reason": "Second approved source.",
                        "speech_anchor": None,
                        "transition": {"kind": "hard_cut"},
                    },
                ],
            }
            compiled = compile_sequence_plan(plan, source_manifest)
            render_manifest = {
                "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
                "output": {
                    "width": 1920, "height": 1080,
                    "fps_numerator": 30, "fps_denominator": 1,
                },
                "sources": [
                    {
                        **source_a, "path": str(root / "a.mp4"),
                        "video": {
                            **_DECLARED_BT709_VIDEO,
                            "width": 1920, "height": 1080,
                            "fps_numerator": 30, "fps_denominator": 1,
                            "start_offset_ms": 0, "duration_ms": 5_000,
                            "end_offset_ms": 5_000,
                        },
                        "audio": {
                            "present": True, "sample_rate": 48_000,
                            "channels": 2, "start_offset_ms": 0,
                            "duration_ms": 5_000, "end_offset_ms": 5_000,
                        },
                    },
                    {
                        **source_b, "path": str(root / "b.mp4"),
                        "video": {
                            **_DECLARED_BT709_VIDEO,
                            "width": 1920, "height": 1080,
                            "fps_numerator": 30, "fps_denominator": 1,
                            "start_offset_ms": 0, "duration_ms": 5_000,
                            "end_offset_ms": 5_000,
                        },
                        "audio": {
                            "present": True, "sample_rate": 48_000,
                            "channels": 2, "start_offset_ms": 0,
                            "duration_ms": 5_000, "end_offset_ms": 5_000,
                        },
                    },
                ],
            }
            render = build_sequence_render(
                compiled, {"a": str(root / "a.mp4"),
                           "b": str(root / "b.mp4")},
                render_manifest, str(source), ffmpeg_path="ffmpeg",
            )
            durations = [2_500, 2_500]
            receipt = {
                "schema_version": "autoeditor-sequence-handoff-receipt/v1",
                "sequence_compile_receipt": compiled["receipt"],
                "sequence_compile_receipt_sha256": compiled["receipt_sha256"],
                "sequence_compile": compiled,
                "sequence_timing_receipt": render["timing_receipt"],
                "sequence_timing_receipt_sha256": render[
                    "timing_receipt_sha256"],
                "ordered_segment_ids": ["a-part", "b-part"],
                "segment_durations_ms": durations,
                "hard_cut_boundaries_ms": [2_500],
                "total_duration_ms": 5_000,
                "synthesized_silence_source_ids": [],
                "used_audio_source_ids": ["a", "b"],
                "output_sha256": pipeline._sha256_file(source),
                "output_bytes": source.stat().st_size,
                "output_file": source.name,
            }
            receipt_path = root / "sequence-receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with mock.patch.object(pipeline, "_dur", return_value=5.0):
                accepted = pipeline.validate_sequence_handoff_receipt(
                    receipt_path, source
                )
            self.assertEqual(accepted["used_audio_source_ids"], ["a", "b"])

            receipt["used_audio_source_ids"] = []
            receipt["synthesized_silence_source_ids"] = ["a", "b"]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with mock.patch.object(pipeline, "_dur", return_value=5.0), \
                    self.assertRaisesRegex(
                        ValueError, "does not bind selected timing"):
                pipeline.validate_sequence_handoff_receipt(receipt_path, source)

    def test_pipeline_accepts_unused_inventory_timing_but_classifies_used_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "approved-sequence.mp4"
            source.write_bytes(b"used-subset-artifact")
            source_a = {
                "source_id": "a", "sha256": "a" * 64,
                "duration_ms": 5_000,
            }
            source_b = {
                "source_id": "b", "sha256": "b" * 64,
                "duration_ms": 5_000,
            }
            manifest = {
                "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
                "sources": [source_a, source_b],
            }
            plan = {
                "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
                "sources": [source_a, source_b],
                "target_duration": {"min_ms": 5_000, "max_ms": 5_000},
                "segments": [{
                    "segment_id": "only-a", "source_id": "a",
                    "source_sha256": "a" * 64,
                    "source_start_ms": 0, "source_end_ms": 5_000,
                    "role": "development", "reason": "Use only source A.",
                    "speech_anchor": None,
                    "transition": {"kind": "hard_cut"},
                }],
            }
            compiled = compile_sequence_plan(plan, manifest)

            def render_source(item, path):
                return {
                    **item, "path": str(path),
                    "video": {
                        **_DECLARED_BT709_VIDEO,
                        "width": 1920, "height": 1080,
                        "fps_numerator": 30, "fps_denominator": 1,
                        "start_offset_ms": 0, "duration_ms": 5_000,
                        "end_offset_ms": 5_000,
                    },
                    "audio": {
                        "present": True, "sample_rate": 48_000,
                        "channels": 2, "start_offset_ms": 0,
                        "duration_ms": 5_000, "end_offset_ms": 5_000,
                    },
                }

            render = build_sequence_render(
                compiled, {"a": str(root / "a.mp4"),
                           "b": str(root / "b.mp4")},
                {
                    "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
                    "output": {
                        "width": 1920, "height": 1080,
                        "fps_numerator": 30, "fps_denominator": 1,
                    },
                    "sources": [
                        render_source(source_a, root / "a.mp4"),
                        render_source(source_b, root / "b.mp4"),
                    ],
                }, str(source), ffmpeg_path="ffmpeg",
            )
            receipt = {
                "schema_version": "autoeditor-sequence-handoff-receipt/v1",
                "sequence_compile_receipt": compiled["receipt"],
                "sequence_compile_receipt_sha256": compiled["receipt_sha256"],
                "sequence_compile": compiled,
                "sequence_timing_receipt": render["timing_receipt"],
                "sequence_timing_receipt_sha256": render[
                    "timing_receipt_sha256"],
                "ordered_segment_ids": ["only-a"],
                "segment_durations_ms": [5_000],
                "hard_cut_boundaries_ms": [],
                "total_duration_ms": 5_000,
                "synthesized_silence_source_ids": [],
                "used_audio_source_ids": ["a"],
                "output_sha256": pipeline._sha256_file(source),
                "output_bytes": source.stat().st_size,
                "output_file": source.name,
            }
            receipt_path = root / "sequence-receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with mock.patch.object(pipeline, "_dur", return_value=5.0):
                accepted = pipeline.validate_sequence_handoff_receipt(
                    receipt_path, source
                )
            self.assertEqual(accepted["used_audio_source_ids"], ["a"])

    def test_sequence_probe_records_unequal_video_and_audio_stream_extents(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffprobe = Path(temporary) / "ffprobe.exe"
            ffprobe.write_bytes(b"stub")
            probed = {
                "format": {"duration": "3.000000", "start_time": "0.000000"},
                "streams": [
                    {
                        **_UNTAGGED_H264_PROBE,
                        "codec_type": "video", "width": 1920, "height": 1080,
                        "avg_frame_rate": "30/1", "start_time": "0.000000",
                        "duration_ts": "1000", "time_base": "1/1000",
                    },
                    {
                        "codec_type": "audio", "sample_rate": "48000",
                        "channels": 2, "start_time": "0.000000",
                        "duration": "3.000000",
                    },
                ],
            }
            completed = mock.Mock(
                returncode=0, stdout=json.dumps(probed), stderr=""
            )
            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {"AUTOEDITOR_FFPROBE": str(ffprobe)}), mock.patch.object(
                        helper_daemon_entry.subprocess, "run",
                        return_value=completed):
                facts = helper_daemon_entry._probe_sequence_source(
                    Path(temporary) / "unequal.mp4"
                )

        self.assertEqual(facts["duration_ms"], 3_000)
        self.assertEqual(facts["video"]["start_offset_ms"], 0)
        self.assertEqual(facts["video"]["duration_ms"], 1_000)
        self.assertEqual(facts["video"]["end_offset_ms"], 1_000)
        self.assertEqual(facts["video"]["codec_name"], "h264")
        self.assertEqual(facts["video"]["pix_fmt"], "yuv420p")
        self.assertEqual(facts["video"]["color_range"], "unknown")
        self.assertEqual(facts["video"]["color_space"], "unknown")
        self.assertEqual(facts["video"]["color_transfer"], "unknown")
        self.assertEqual(facts["video"]["color_primaries"], "unknown")
        self.assertEqual(facts["audio"]["start_offset_ms"], 0)
        self.assertEqual(facts["audio"]["duration_ms"], 3_000)
        self.assertEqual(facts["audio"]["end_offset_ms"], 3_000)

    def test_sequence_probe_accepts_only_narrow_legacy_mjpeg_color_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffprobe = Path(temporary) / "ffprobe.exe"
            ffprobe.write_bytes(b"stub")
            base_video = {
                "codec_type": "video", "codec_name": "mjpeg",
                "width": 1920, "height": 1080,
                "avg_frame_rate": "30/1", "start_time": "0.000000",
                "duration": "1.000000", "pix_fmt": "yuvj420p",
                "color_range": "pc", "color_space": "bt470bg",
            }

            def probe(video: dict) -> dict:
                payload = {
                    "format": {
                        "duration": "1.000000", "start_time": "0.000000",
                    },
                    "streams": [video],
                }
                completed = mock.Mock(
                    returncode=0, stdout=json.dumps(payload), stderr=""
                )
                with mock.patch.object(
                        helper_daemon_entry.subprocess, "run",
                        return_value=completed):
                    return helper_daemon_entry._probe_sequence_source(
                        Path(temporary) / "legacy.mov"
                    )

            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {"AUTOEDITOR_FFPROBE": str(ffprobe)}):
                facts = probe(copy.deepcopy(base_video))
                self.assertEqual(facts["video"]["codec_name"], "mjpeg")
                self.assertEqual(facts["video"]["pix_fmt"], "yuvj420p")
                self.assertEqual(facts["video"]["color_range"], "pc")
                self.assertEqual(facts["video"]["color_space"], "bt470bg")
                self.assertEqual(facts["video"]["color_transfer"], "unknown")
                self.assertEqual(facts["video"]["color_primaries"], "unknown")

                mutations = (
                    {"color_range": "tv"},
                    {"color_space": "bt709"},
                    {"codec_name": "h264"},
                    {"pix_fmt": "yuv420p"},
                    {"color_transfer": "bt709"},
                )
                for index, mutation in enumerate(mutations):
                    video = copy.deepcopy(base_video)
                    video.update(mutation)
                    with self.subTest(index=index), self.assertRaisesRegex(
                            RuntimeError, "invalid technical metadata"):
                        probe(video)

    def test_sequence_probe_derives_missing_container_origin_from_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffprobe = Path(temporary) / "ffprobe.exe"
            ffprobe.write_bytes(b"stub")
            base = {
                "format": {"duration": "4.000000"},
                "streams": [
                    {
                        **_UNTAGGED_H264_PROBE,
                        "codec_type": "video", "width": 1920, "height": 1080,
                        "avg_frame_rate": "30/1", "start_time": "1.000000",
                        "duration": "2.500000",
                    },
                    {
                        "codec_type": "audio", "sample_rate": "48000",
                        "channels": 2, "start_time": "1.500000",
                        "duration": "2.000000",
                    },
                ],
            }
            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {"AUTOEDITOR_FFPROBE": str(ffprobe)}):
                for case, format_start in (("missing", None), ("n-a", "N/A")):
                    probed = copy.deepcopy(base)
                    if format_start is not None:
                        probed["format"]["start_time"] = format_start
                    completed = mock.Mock(
                        returncode=0, stdout=json.dumps(probed), stderr=""
                    )
                    with self.subTest(case=case), mock.patch.object(
                            helper_daemon_entry.subprocess, "run",
                            return_value=completed):
                        facts = helper_daemon_entry._probe_sequence_source(
                            Path(temporary) / "derived-origin.mkv"
                        )
                    self.assertEqual(facts["video"]["start_offset_ms"], 0)
                    self.assertEqual(facts["audio"]["start_offset_ms"], 500)
                    self.assertEqual(facts["video"]["end_offset_ms"], 2_500)
                    self.assertEqual(facts["audio"]["end_offset_ms"], 2_500)

                no_origin = copy.deepcopy(base)
                for stream in no_origin["streams"]:
                    stream.pop("start_time")
                completed = mock.Mock(
                    returncode=0, stdout=json.dumps(no_origin), stderr=""
                )
                with mock.patch.object(
                        helper_daemon_entry.subprocess, "run",
                        return_value=completed), self.assertRaisesRegex(
                            RuntimeError, "invalid technical metadata"):
                    helper_daemon_entry._probe_sequence_source(
                        Path(temporary) / "no-origin.mkv"
                    )

    def test_sequence_probe_derives_missing_container_duration_from_stream_ends(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffprobe = Path(temporary) / "ffprobe.exe"
            ffprobe.write_bytes(b"stub")
            base = {
                "format": {"start_time": "1.000000"},
                "streams": [
                    {
                        **_UNTAGGED_H264_PROBE,
                        "codec_type": "video", "width": 1920, "height": 1080,
                        "avg_frame_rate": "30/1", "start_time": "1.000000",
                        "duration": "2.000000",
                    },
                    {
                        "codec_type": "audio", "sample_rate": "48000",
                        "channels": 2, "start_time": "1.500000",
                        "duration": "3.000000",
                    },
                ],
            }
            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {"AUTOEDITOR_FFPROBE": str(ffprobe)}):
                for case, format_duration in (
                    ("missing", None), ("n-a", "N/A"),
                    ("malformed", "not-a-duration"),
                ):
                    probed = copy.deepcopy(base)
                    if format_duration is not None:
                        probed["format"]["duration"] = format_duration
                    completed = mock.Mock(
                        returncode=0, stdout=json.dumps(probed), stderr=""
                    )
                    with self.subTest(case=case), mock.patch.object(
                            helper_daemon_entry.subprocess, "run",
                            return_value=completed):
                        facts = helper_daemon_entry._probe_sequence_source(
                            Path(temporary) / "derived-duration.webm"
                        )
                    self.assertEqual(facts["duration_ms"], 3_500)
                    self.assertEqual(facts["video"]["end_offset_ms"], 2_000)
                    self.assertEqual(facts["audio"]["end_offset_ms"], 3_500)

    def test_sequence_probe_accepts_only_strict_bounded_stream_duration_tags(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffprobe = Path(temporary) / "ffprobe.exe"
            ffprobe.write_bytes(b"stub")
            probed = {
                "format": {
                    "format_name": "matroska,webm", "duration": "3.250000",
                    "start_time": "0.000000",
                },
                "streams": [
                    {
                        **_UNTAGGED_H264_PROBE,
                        "codec_type": "video", "width": 1920, "height": 1080,
                        "avg_frame_rate": "30/1", "start_time": "0.000000",
                        "tags": {"DURATION": "00:00:01.250000000"},
                    },
                    {
                        "codec_type": "audio", "sample_rate": "48000",
                        "channels": 2, "start_time": "0.000000",
                        "tags": {"DURATION": "00:00:03.250000000"},
                    },
                ],
            }

            def probe(payload: dict) -> dict:
                completed = mock.Mock(
                    returncode=0, stdout=json.dumps(payload), stderr=""
                )
                with mock.patch.object(
                        helper_daemon_entry.subprocess, "run",
                        return_value=completed):
                    return helper_daemon_entry._probe_sequence_source(
                        Path(temporary) / "tag-duration.webm"
                    )

            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {"AUTOEDITOR_FFPROBE": str(ffprobe)}):
                facts = probe(probed)
                self.assertEqual(facts["video"]["duration_ms"], 1_250)
                self.assertEqual(facts["video"]["end_offset_ms"], 1_250)
                self.assertEqual(facts["audio"]["duration_ms"], 3_250)
                self.assertEqual(facts["audio"]["end_offset_ms"], 3_250)

                malformed = copy.deepcopy(probed)
                malformed["streams"][0]["tags"]["DURATION"] = "1.250"
                with self.subTest(case="malformed"), self.assertRaisesRegex(
                        RuntimeError, "invalid technical metadata"):
                    probe(malformed)

                missing = copy.deepcopy(probed)
                missing["streams"][0]["tags"] = {"TITLE": "unknown"}
                with self.subTest(case="missing"), self.assertRaisesRegex(
                        RuntimeError, "invalid technical metadata"):
                    probe(missing)

                ambiguous = copy.deepcopy(probed)
                ambiguous["streams"][0]["tags"]["duration"] = (
                    "00:00:01.250000000"
                )
                with self.subTest(case="ambiguous"), self.assertRaisesRegex(
                        RuntimeError, "invalid technical metadata"):
                    probe(ambiguous)

                malformed_primary = copy.deepcopy(probed)
                malformed_primary["streams"][0]["duration"] = "NaN"
                with self.subTest(case="malformed-primary"), self.assertRaisesRegex(
                        RuntimeError, "invalid technical metadata"):
                    probe(malformed_primary)

    def test_daemon_to_renderer_rejects_selection_past_video_stream_end(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.mp4"
            second = root / "second.mp4"
            first.write_bytes(b"first-source")
            second.write_bytes(b"second-source")
            first_hash = helper_daemon_entry._sha256_file(first)
            second_hash = helper_daemon_entry._sha256_file(second)
            sources = [
                {"source_id": "first", "sha256": first_hash,
                 "duration_ms": 3_000},
                {"source_id": "second", "sha256": second_hash,
                 "duration_ms": 5_000},
            ]
            source_manifest = {
                "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
                "sources": sources,
            }
            plan = {
                "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
                "sources": copy.deepcopy(sources),
                "target_duration": {"min_ms": 5_000, "max_ms": 5_000},
                "segments": [
                    {
                        "segment_id": "past-video", "source_id": "first",
                        "source_sha256": first_hash,
                        "source_start_ms": 800, "source_end_ms": 1_500,
                        "role": "development",
                        "reason": "Exercises the unequal stream boundary.",
                        "speech_anchor": None,
                        "transition": {"kind": "hard_cut"},
                    },
                    {
                        "segment_id": "filler", "source_id": "second",
                        "source_sha256": second_hash,
                        "source_start_ms": 0, "source_end_ms": 4_300,
                        "role": "development",
                        "reason": "Keeps the strict sequence duration valid.",
                        "speech_anchor": None,
                        "transition": {"kind": "hard_cut"},
                    },
                ],
            }
            probe_by_snapshot = {
                "sequence-source-01.mp4": {
                    "duration_ms": 3_000,
                    "video": {
                        **_DECLARED_BT709_VIDEO,
                        "width": 1920, "height": 1080,
                        "fps_numerator": 30, "fps_denominator": 1,
                        "start_offset_ms": 0, "duration_ms": 1_000,
                        "end_offset_ms": 1_000,
                    },
                    "audio": {
                        "present": True, "sample_rate": 48_000, "channels": 2,
                        "start_offset_ms": 0, "duration_ms": 3_000,
                        "end_offset_ms": 3_000,
                    },
                },
                "sequence-source-02.mp4": {
                    "duration_ms": 5_000,
                    "video": {
                        **_DECLARED_BT709_VIDEO,
                        "width": 1920, "height": 1080,
                        "fps_numerator": 30, "fps_denominator": 1,
                        "start_offset_ms": 0, "duration_ms": 5_000,
                        "end_offset_ms": 5_000,
                    },
                    "audio": {
                        "present": True, "sample_rate": 48_000, "channels": 2,
                        "start_offset_ms": 0, "duration_ms": 5_000,
                        "end_offset_ms": 5_000,
                    },
                },
            }
            work = root / "work"
            work.mkdir()
            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {"AUTOEDITOR_FFMPEG": "ffmpeg"}), mock.patch.object(
                        helper_daemon_entry, "_probe_sequence_source",
                        side_effect=lambda path: copy.deepcopy(
                            probe_by_snapshot[path.name]
                        )):
                with self.assertRaisesRegex(
                        ValueError, "ends after its decoded video"):
                    helper_daemon_entry._build_approved_sequence(
                        [first, second], "custom", work, plan, source_manifest
                    )

    def test_handoff_classifies_present_but_unselected_audio_as_silence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.mp4"
            second = root / "second.mp4"
            first.write_bytes(b"first-source")
            second.write_bytes(b"second-source")
            first_hash = helper_daemon_entry._sha256_file(first)
            second_hash = helper_daemon_entry._sha256_file(second)
            sources = [
                {"source_id": "first", "sha256": first_hash,
                 "duration_ms": 4_000},
                {"source_id": "second", "sha256": second_hash,
                 "duration_ms": 4_000},
            ]
            source_manifest = {
                "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
                "sources": sources,
            }
            plan = {
                "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
                "sources": copy.deepcopy(sources),
                "target_duration": {"min_ms": 5_000, "max_ms": 5_000},
                "segments": [
                    {
                        "segment_id": "first-before-audio", "source_id": "first",
                        "source_sha256": first_hash,
                        "source_start_ms": 0, "source_end_ms": 2_500,
                        "role": "development",
                        "reason": "Use the silent interval before audio begins.",
                        "speech_anchor": None,
                        "transition": {"kind": "hard_cut"},
                    },
                    {
                        "segment_id": "second-before-audio", "source_id": "second",
                        "source_sha256": second_hash,
                        "source_start_ms": 0, "source_end_ms": 2_500,
                        "role": "development",
                        "reason": "Use the other silent interval before audio begins.",
                        "speech_anchor": None,
                        "transition": {"kind": "hard_cut"},
                    },
                ],
            }

            def source_probe(duration_ms: int) -> dict:
                return {
                    "duration_ms": duration_ms,
                    "video": {
                        **_DECLARED_BT709_VIDEO,
                        "width": 1920, "height": 1080,
                        "fps_numerator": 30, "fps_denominator": 1,
                        "start_offset_ms": 0, "duration_ms": duration_ms,
                        "end_offset_ms": duration_ms,
                    },
                    "audio": {
                        "present": True, "sample_rate": 48_000, "channels": 2,
                        "start_offset_ms": 3_000,
                        "duration_ms": duration_ms - 3_000,
                        "end_offset_ms": duration_ms,
                    },
                }

            probe_by_name = {
                "sequence-source-01.mp4": source_probe(4_000),
                "sequence-source-02.mp4": source_probe(4_000),
                "approved-sequence.mp4": source_probe(5_000),
            }

            def render(argv, **_kwargs):
                workdir = Path(_kwargs["cwd"])
                (workdir / argv[-1]).write_bytes(b"rendered-sequence")
                return mock.Mock(returncode=0, stderr="")

            work = root / "work"
            work.mkdir()
            with mock.patch.dict(
                    helper_daemon_entry.os.environ,
                    {"AUTOEDITOR_FFMPEG": "ffmpeg"}), mock.patch.object(
                        helper_daemon_entry, "_probe_sequence_source",
                        side_effect=lambda path: copy.deepcopy(
                            probe_by_name[path.name]
                        )), mock.patch.object(
                            helper_daemon_entry.subprocess, "run",
                            side_effect=render):
                _output, receipt = helper_daemon_entry._build_approved_sequence(
                    [first, second], "custom", work, plan, source_manifest
                )
            receipt_path = root / "silent-sequence-receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with mock.patch.object(pipeline, "_dur", return_value=5.0):
                validated = pipeline.validate_sequence_handoff_receipt(
                    receipt_path, _output
                )

        self.assertEqual(receipt["used_audio_source_ids"], [])
        self.assertEqual(
            receipt["synthesized_silence_source_ids"], ["first", "second"]
        )
        self.assertEqual(
            {item["audio_mode"] for item in
             receipt["sequence_timing_receipt"]["segment_timing"]},
            {"timeline_silence"},
        )
        self.assertTrue(pipeline.intentional_silent_sequence_mode(
            validated, [], [], None
        ))

    def test_maximum_unicode_sequence_fits_every_daemon_bound(self):
        source = {
            "source_id": "source-a", "sha256": "a" * 64,
            "duration_ms": 10_000,
        }
        reason = "a" + "\U0001f600" * 199
        anchor_text = "a" + "\U0001f600" * 499
        segments = [{
            "segment_id": f"segment-{index}",
            "source_id": source["source_id"],
            "source_sha256": source["sha256"],
            "source_start_ms": 0, "source_end_ms": 34,
            "role": "development", "reason": reason,
            "speech_anchor": {
                "start_word": 0, "end_word": 0, "text": anchor_text,
            },
            "transition": {"kind": "hard_cut"},
        } for index in range(256)]
        plan = {
            "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
            "sources": [source],
            "target_duration": {"min_ms": 8_704, "max_ms": 8_704},
            "segments": segments,
        }
        manifest = {
            "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
            "sources": [source],
        }
        wire = json.dumps({
            "proposal": {
                "sequencePlan": plan,
                "sequenceSourceManifest": manifest,
            }
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(
            len(wire), helper_daemon_entry.MAX_LOCAL_REQUEST_BYTES
        )
        normalized, normalized_manifest = (
            helper_daemon_entry._sequence_from_proposal({
                "sequencePlan": plan,
                "sequenceSourceManifest": manifest,
            })
        )
        self.assertEqual(len(normalized["segments"]), 256)
        self.assertEqual(normalized_manifest, manifest)

    def test_approved_plan_binds_source_transcript_and_exact_complement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source-bytes")
            plan_path = root / "approved-story-plan.json"
            plan_path.write_text(json.dumps(_plan()), encoding="utf-8")

            plan, cuts, receipt = pipeline._approved_story_cut(
                source, SOURCE_DURATION, _words(), plan_path
            )

        self.assertEqual(plan["hook_anchor_id"], "hook")
        self.assertEqual(plan["keep_ranges"][0]["source_start_word"], 50)
        self.assertEqual(cuts, [
            {"s": 0.0, "e": 20.0},
            {"s": 40.0, "e": 120.0},
            {"s": 140.0, "e": SOURCE_DURATION},
        ])
        self.assertEqual(receipt["kept_duration_seconds"], 40.0)
        self.assertEqual(receipt["source"], "deepseek")
        self.assertEqual(len(receipt["story_plan_sha256"]), 64)

    def test_hook_text_must_be_literal_source_transcript(self):
        plan = _plan()
        plan["keep_ranges"][0]["anchor_text"] = "invented hook"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source-bytes")
            plan_path = root / "approved-story-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "source-transcript validation"):
                pipeline._approved_story_cut(
                    source, SOURCE_DURATION, _words(), plan_path
                )

    def test_158_second_output_cannot_pass_35_to_45_second_approval(self):
        result = check_final_duration(
            158.0, _plan()["target_duration"]
        )
        self.assertFalse(result["ok"])
        self.assertIn("outside the required", result["errors"][0])

    def test_daemon_rejects_duration_promise_without_story_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source")
            request = {
                "inputs": [str(source)],
                "outputDir": str(root),
                "projectType": "short",
                "script": "",
                "cachedTranscript": "",
                "creativeBrief": "",
                "creativeBriefSha256": "",
                "proposal": {
                    "summary": "Premium hook-first edit lasting 35-45 seconds",
                    "operations": [
                        {"op": "set_edit_style", "style": "short"}
                    ],
                },
            }
            with self.assertRaisesRegex(
                    ValueError, "requires a transcript-grounded story plan"):
                helper_daemon_entry._local_render_request(request)

            request["proposal"] = {
                **request["proposal"], "storyPlan": copy.deepcopy(_plan()),
                "creativeConstraints": _creative_constraints(),
            }
            normalized = helper_daemon_entry._local_render_request(request)
            self.assertEqual(
                normalized["story_plan"]["target_duration"],
                {"min_seconds": 35.0, "max_seconds": 45.0},
            )
            self.assertEqual(
                normalized["creative_constraints"]["visual_policy"][
                    "graphics_exact"
                ], 1,
            )

    def test_daemon_rejects_story_plan_without_typed_creative_constraints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source")
            request = {
                "inputs": [str(source)], "outputDir": str(root),
                "projectType": "short", "script": "",
                "cachedTranscript": "", "creativeBrief": "",
                "creativeBriefSha256": "",
                "proposal": {
                    "summary": "approved edit",
                    "operations": [{"op": "set_edit_style", "style": "short"}],
                    "storyPlan": _plan(),
                },
            }
            with self.assertRaisesRegex(
                    ValueError, "requires typed creative constraints"):
                helper_daemon_entry._local_render_request(request)


if __name__ == "__main__":
    unittest.main()
