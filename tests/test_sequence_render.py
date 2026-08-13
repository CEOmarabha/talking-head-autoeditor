from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from autoeditor.sequence_plan import (
    MAX_SEGMENTS,
    SEQUENCE_PLAN_SCHEMA_VERSION,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    compile_sequence_plan,
)
from autoeditor.sequence_render import (
    SEQUENCE_RENDER_SCHEMA_VERSION,
    SEQUENCE_TIMING_RECEIPT_SCHEMA_VERSION,
    SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
    SequenceRenderError,
    build_sequence_render,
    build_sequence_render_argv,
)


def _absolute(name: str) -> str:
    return str((Path.cwd() / "sequence-render-fixtures" / name).resolve())


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


def _source(source_id: str, digest: str, duration_ms: int) -> dict:
    return {"source_id": source_id, "sha256": digest,
            "duration_ms": duration_ms}


def _source_manifest() -> dict:
    return {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sources": [
            _source("cam-a", "a" * 64, 10_000),
            _source("screen-b", "b" * 64, 20_000),
            _source("silent-c", "c" * 64, 5_000),
        ],
    }


def _segment(segment_id: str, source_id: str, digest: str,
             start: int, end: int) -> dict:
    return {
        "segment_id": segment_id,
        "source_id": source_id,
        "source_sha256": digest,
        "source_start_ms": start,
        "source_end_ms": end,
        "role": "development",
        "reason": f"Use {segment_id} for the deterministic sequence.",
        "speech_anchor": None,
        "transition": {"kind": "hard_cut"},
    }


def _plan(*, use_silent: bool = False) -> dict:
    segments = [
        _segment("screen-first", "screen-b", "b" * 64, 1_250, 3_000),
        _segment("camera-middle", "cam-a", "a" * 64, 500, 2_500),
        # Repeated and overlapping selection from screen-b is intentional.
        _segment("screen-repeat", "screen-b", "b" * 64, 1_500, 2_750),
    ]
    if use_silent:
        segments.append(
            _segment("silent-close", "silent-c", "c" * 64, 0, 1_000)
        )
    total = sum(item["source_end_ms"] - item["source_start_ms"]
                for item in segments)
    return {
        "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
        "sources": copy.deepcopy(_source_manifest()["sources"]),
        "target_duration": {"min_ms": total, "max_ms": total},
        "segments": segments,
    }


def _plan_for_segments(segments: list[dict]) -> dict:
    total = sum(item["source_end_ms"] - item["source_start_ms"]
                for item in segments)
    if total < 5_000:
        used = {item["source_id"] for item in segments}
        # Keep the source under test's input index/occurrence count stable.
        filler_id, filler_hash = (
            ("silent-c", "c" * 64) if "screen-b" in used
            else ("screen-b", "b" * 64)
        )
        segments = [*segments, _segment(
            "minimum-runtime-padding", filler_id, filler_hash,
            0, 5_000 - total,
        )]
        total = 5_000
    return {
        "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
        "sources": copy.deepcopy(_source_manifest()["sources"]),
        "target_duration": {"min_ms": total, "max_ms": total},
        "segments": copy.deepcopy(segments),
    }


def _render_source(source: dict, *, present: bool = True,
                   path: str | None = None,
                   video_start_offset_ms: int = 0,
                   audio_start_offset_ms: int = 0,
                   video_duration_ms: int | None = None,
                   audio_duration_ms: int | None = None) -> dict:
    resolved_video_duration = (
        source["duration_ms"] - video_start_offset_ms
        if video_duration_ms is None else video_duration_ms
    )
    resolved_audio_duration = (
        source["duration_ms"] - audio_start_offset_ms
        if audio_duration_ms is None else audio_duration_ms
    ) if present else None
    return {
        **copy.deepcopy(source),
        "path": path or _absolute(f"{source['source_id']}.mp4"),
        "video": {
            "width": 3840,
            "height": 2160,
            "fps_numerator": 30_000,
            "fps_denominator": 1_001,
            "start_offset_ms": video_start_offset_ms,
            "duration_ms": resolved_video_duration,
            "end_offset_ms": video_start_offset_ms + resolved_video_duration,
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "color_range": "tv",
            "color_space": "bt709",
            "color_transfer": "bt709",
            "color_primaries": "bt709",
        },
        "audio": {
            "present": present,
            "sample_rate": 44_100 if present else None,
            "channels": 1 if present else None,
            "start_offset_ms": audio_start_offset_ms if present else None,
            "duration_ms": resolved_audio_duration,
            "end_offset_ms": (
                audio_start_offset_ms + resolved_audio_duration
                if present else None
            ),
        },
    }


def _set_stream_start_preserving_end(stream: dict, start_offset_ms: int) -> None:
    stream["start_offset_ms"] = start_offset_ms
    stream["duration_ms"] = stream["end_offset_ms"] - start_offset_ms


def _render_manifest(*, silent_audio: bool = True) -> dict:
    sources = _source_manifest()["sources"]
    return {
        "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
        "output": {
            "width": 1920,
            "height": 1080,
            "fps_numerator": 30_000,
            "fps_denominator": 1_001,
        },
        "sources": [
            _render_source(source, present=(
                source["source_id"] != "silent-c" or silent_audio
            ))
            for source in sources
        ],
    }


def _paths(manifest: dict) -> dict[str, str]:
    return {source["source_id"]: source["path"]
            for source in manifest["sources"]}


class SequenceRenderContractTests(unittest.TestCase):
    def build(self, *, use_silent: bool = False,
              silent_audio: bool = True,
              synthesis: object = ()) -> dict:
        source_manifest = _source_manifest()
        compiled = compile_sequence_plan(
            _plan(use_silent=use_silent), source_manifest)
        manifest = _render_manifest(silent_audio=silent_audio)
        return build_sequence_render(
            compiled,
            _paths(manifest),
            manifest,
            _absolute("finished.mp4"),
            ffmpeg_path="ffmpeg",
            synthesize_silence_for=synthesis,
        )

    def render_plan(self, plan: dict, manifest: dict) -> dict:
        compiled = compile_sequence_plan(plan, _source_manifest())
        return build_sequence_render(
            compiled,
            _paths(manifest),
            manifest,
            _absolute("offset-finished.mp4"),
            ffmpeg_path="ffmpeg",
        )

    def test_reorder_repeat_and_overlap_generate_exact_hard_cut_graph(self):
        render = self.build()

        self.assertEqual(render["schema_version"], SEQUENCE_RENDER_SCHEMA_VERSION)
        self.assertEqual(render["ordered_segment_ids"], [
            "screen-first", "camera-middle", "screen-repeat",
        ])
        self.assertEqual(render["source_input_order"], [
            "screen-b", "cam-a", "screen-b",
        ])
        self.assertEqual(render["segment_count"], 3)
        self.assertEqual(render["total_duration_ms"], 5_000)
        graph = render["filter_complex"]
        self.assertNotIn("split=", graph)
        self.assertNotIn("asplit=", graph)
        self.assertIn(
            "[0:v:0]trim=duration=1.750,setpts=PTS-STARTPTS",
            graph,
        )
        self.assertIn(
            "[1:v:0]trim=duration=2.000,setpts=PTS-STARTPTS",
            graph,
        )
        self.assertIn(
            "[2:v:0]trim=duration=1.250,setpts=PTS-STARTPTS",
            graph,
        )
        argv = render["argv"]
        self.assertEqual(argv.count("-i"), 3)
        self.assertEqual(argv.count("-threads"), 3)
        self.assertEqual(
            [argv[index + 1] for index, token in enumerate(argv) if token == "-ss"],
            ["1.250", "0.500", "1.500"],
        )
        self.assertEqual(
            [item["audio_mode"]
             for item in render["timing_receipt"]["segment_timing"]],
            ["source", "source", "source"],
        )
        first_timing = render["timing_receipt"]["segment_timing"][0]
        self.assertEqual(first_timing["common_start_ms"], 1_250)
        self.assertEqual(first_timing["video_local_start_ms"], 1_250)
        self.assertEqual(first_timing["audio_local_start_ms"], 1_250)
        self.assertTrue(all(
            source["video_start_offset_ms"] == 0
            and source["audio_start_offset_ms"] == 0
            for source in render["timing_receipt"]["source_timing"]
        ))
        self.assertTrue(graph.endswith(
            "[v000][a000][v001][a001][v002][a002]"
            "concat=n=3:v=1:a=1[vout][aout]"
        ))

    def test_positive_500ms_audio_lag_is_preserved_with_leading_silence(self):
        plan = _plan_for_segments([
            _segment("lagged", "cam-a", "a" * 64, 0, 2_000),
        ])
        manifest = _render_manifest()
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        _set_stream_start_preserving_end(cam["audio"], 500)

        render = self.render_plan(plan, manifest)
        graph = render["filter_complex"]
        self.assertIn(
            "[0:v:0]trim=duration=2.000,setpts=PTS-STARTPTS",
            graph,
        )
        self.assertIn(
            "[0:a:0]atrim=duration=1.500,asetpts=PTS-STARTPTS,"
            "aresample=48000:async=0:first_pts=0,"
            "aformat=sample_rates=48000:channel_layouts=stereo,"
            "adelay=500:all=1,apad,atrim=duration=2.000,"
            "asetpts=PTS-STARTPTS[a000]",
            graph,
        )
        timing = render["timing_receipt"]["segment_timing"][0]
        self.assertEqual(timing, {
            "sequence_index": 0,
            "segment_id": "lagged",
            "source_id": "cam-a",
            "common_start_ms": 0,
            "common_end_ms": 2_000,
            "video_local_start_ms": 0,
            "video_local_end_ms": 2_000,
            "audio_local_start_ms": 0,
            "audio_local_end_ms": 1_500,
            "audio_lead_silence_ms": 500,
            "audio_tail_silence_ms": 0,
            "audio_mode": "delayed_source",
        })
        self.assertEqual(
            render["timing_receipt"]["schema_version"],
            SEQUENCE_TIMING_RECEIPT_SCHEMA_VERSION,
        )
        canonical_receipt = json.dumps(
            render["timing_receipt"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.assertEqual(
            render["timing_receipt_sha256"],
            hashlib.sha256(canonical_receipt.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            render["timing_receipt_sha256"],
            "d777351a465e9ddf9cdf324c99e4ac73"
            "00527e4b51f82a9df9967fc076c4be7c",
        )
        filter_position = render["argv"].index("-filter_complex_script")
        thread_position = render["argv"].index("-filter_complex_threads")
        self.assertEqual(render["argv"][thread_position:thread_position + 2], [
            "-filter_complex_threads", "1",
        ])
        self.assertEqual(render["argv"].count("-filter_complex_threads"), 1)
        self.assertLess(thread_position, render["argv"].index("-i"))
        self.assertEqual(
            render["argv"][filter_position + 1],
            f".{os.sep}{Path(render['filter_script_path']).name}",
        )

    def test_negative_stream_offsets_translate_to_common_timeline(self):
        plan = _plan_for_segments([
            _segment("negative-offsets", "cam-a", "a" * 64, 0, 2_000),
        ])
        manifest = _render_manifest()
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        _set_stream_start_preserving_end(cam["video"], -250)
        _set_stream_start_preserving_end(cam["audio"], -500)

        render = self.render_plan(plan, manifest)
        graph = render["filter_complex"]
        self.assertIn("[0:v:0]trim=duration=2.000", graph)
        self.assertIn("[0:a:0]atrim=duration=2.000", graph)
        argv = render["argv"]
        self.assertEqual(argv[argv.index("-ss") + 1], "0.000")
        self.assertNotIn("adelay=", graph)
        timing = render["timing_receipt"]["segment_timing"][0]
        self.assertEqual(timing["video_local_start_ms"], 250)
        self.assertEqual(timing["video_local_end_ms"], 2_250)
        self.assertEqual(timing["audio_local_start_ms"], 500)
        self.assertEqual(timing["audio_local_end_ms"], 2_500)
        self.assertEqual(timing["audio_mode"], "source")
        source_timing = next(
            source for source in render["timing_receipt"]["source_timing"]
            if source["source_id"] == "cam-a"
        )
        self.assertEqual(source_timing["video_start_offset_ms"], -250)
        self.assertEqual(source_timing["audio_start_offset_ms"], -500)

    def test_reused_source_computes_offset_per_selected_segment(self):
        plan = _plan_for_segments([
            _segment("before-audio", "screen-b", "b" * 64, 0, 1_000),
            _segment("after-audio", "screen-b", "b" * 64, 1_000, 2_500),
        ])
        manifest = _render_manifest()
        screen = next(source for source in manifest["sources"]
                      if source["source_id"] == "screen-b")
        _set_stream_start_preserving_end(screen["audio"], 500)

        render = self.render_plan(plan, manifest)
        graph = render["filter_complex"]
        self.assertNotIn("asplit=", graph)
        self.assertIn("[0:a:0]atrim=duration=0.500", graph)
        self.assertIn("adelay=500:all=1,apad,atrim=duration=1.000", graph)
        self.assertIn("[1:a:0]atrim=duration=1.500", graph)
        timings = render["timing_receipt"]["segment_timing"]
        self.assertEqual(
            [(item["audio_mode"], item["audio_lead_silence_ms"])
             for item in timings[:2]],
            [("delayed_source", 500), ("source", 0)],
        )

    def test_short_audio_is_clipped_and_trailing_padding_is_exactly_receipted(self):
        plan = _plan_for_segments([
            _segment("short-audio", "cam-a", "a" * 64, 0, 2_000),
        ])
        manifest = _render_manifest()
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        cam["audio"]["duration_ms"] = 1_250
        cam["audio"]["end_offset_ms"] = 1_250

        render = self.render_plan(plan, manifest)
        timing = render["timing_receipt"]["segment_timing"][0]
        self.assertEqual(timing["audio_mode"], "source")
        self.assertEqual(timing["audio_local_start_ms"], 0)
        self.assertEqual(timing["audio_local_end_ms"], 1_250)
        self.assertEqual(timing["audio_lead_silence_ms"], 0)
        self.assertEqual(timing["audio_tail_silence_ms"], 750)
        self.assertIn(
            "atrim=duration=1.250,asetpts=PTS-STARTPTS,"
            "aresample=48000:async=0:first_pts=0,"
            "aformat=sample_rates=48000:channel_layouts=stereo,"
            "apad,atrim=duration=2.000",
            render["filter_complex"],
        )
        source_timing = next(
            source for source in render["timing_receipt"]["source_timing"]
            if source["source_id"] == "cam-a"
        )
        self.assertEqual(source_timing["audio_duration_ms"], 1_250)
        self.assertEqual(source_timing["audio_end_offset_ms"], 1_250)

    def test_interval_after_audio_is_receipted_as_trailing_timeline_silence(self):
        plan = _plan_for_segments([
            _segment("after-audio", "cam-a", "a" * 64, 2_000, 3_000),
        ])
        manifest = _render_manifest()
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        cam["audio"]["duration_ms"] = 1_500
        cam["audio"]["end_offset_ms"] = 1_500

        render = self.render_plan(plan, manifest)
        timing = render["timing_receipt"]["segment_timing"][0]
        self.assertEqual(timing["audio_mode"], "timeline_silence")
        self.assertIsNone(timing["audio_local_start_ms"])
        self.assertIsNone(timing["audio_local_end_ms"])
        self.assertEqual(timing["audio_lead_silence_ms"], 0)
        self.assertEqual(timing["audio_tail_silence_ms"], 1_000)
        self.assertNotIn("[0:a:0]", render["filter_complex"])

    def test_segment_past_decoded_video_end_fails_even_with_long_container(self):
        plan = _plan_for_segments([
            _segment("past-video", "cam-a", "a" * 64, 800, 1_500),
        ])
        manifest = _render_manifest()
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        cam["video"]["duration_ms"] = 1_000
        cam["video"]["end_offset_ms"] = 1_000

        with self.assertRaisesRegex(
                SequenceRenderError, "ends after its decoded video"):
            self.render_plan(plan, manifest)

    def test_ranges_before_video_fail_and_ranges_before_audio_are_silent(self):
        plan = _plan_for_segments([
            _segment("early", "cam-a", "a" * 64, 0, 400),
        ])
        manifest = _render_manifest()
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        _set_stream_start_preserving_end(cam["video"], 100)
        with self.assertRaisesRegex(SequenceRenderError, "fabricated leading"):
            self.render_plan(plan, manifest)

        manifest = _render_manifest()
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        _set_stream_start_preserving_end(cam["audio"], 500)
        render = self.render_plan(plan, manifest)
        self.assertNotIn("[0:a:0]", render["filter_complex"])
        self.assertIn(
            "anullsrc=channel_layout=stereo:sample_rate=48000,"
            "atrim=duration=0.400,asetpts=PTS-STARTPTS[a000]",
            render["filter_complex"],
        )
        timing = render["timing_receipt"]["segment_timing"][0]
        self.assertEqual(timing["audio_mode"], "timeline_silence")
        self.assertEqual(timing["audio_lead_silence_ms"], 400)
        self.assertEqual(timing["audio_tail_silence_ms"], 0)

    def test_argv_is_stable_across_mapping_and_manifest_enumeration(self):
        source_manifest = _source_manifest()
        compiled = compile_sequence_plan(_plan(), source_manifest)
        manifest = _render_manifest()
        paths = _paths(manifest)
        first = build_sequence_render(
            compiled, paths, manifest, _absolute("stable.mp4"))

        reversed_manifest = copy.deepcopy(manifest)
        reversed_manifest["sources"].reverse()
        reversed_paths = dict(reversed(list(paths.items())))
        second = build_sequence_render(
            copy.deepcopy(compiled), reversed_paths, reversed_manifest,
            _absolute("stable.mp4"))
        self.assertEqual(first, second)
        self.assertEqual(build_sequence_render_argv(
            compiled, paths, manifest, _absolute("stable.mp4")), first["argv"])

    def test_maximum_unique_segments_use_independent_bounded_inputs(self):
        segments = []
        for index in range(MAX_SEGMENTS):
            start = index * 34
            segments.append(_segment(
                f"micro-{index:03d}", "screen-b", "b" * 64,
                start, start + 34,
            ))
        plan = _plan_for_segments(segments)
        render = self.render_plan(plan, _render_manifest())

        self.assertEqual(render["segment_count"], MAX_SEGMENTS)
        self.assertEqual(render["argv"].count("-i"), MAX_SEGMENTS)
        self.assertEqual(render["argv"].count("-threads"), MAX_SEGMENTS)
        self.assertNotIn("split=", render["filter_complex"])
        self.assertNotIn("asplit=", render["filter_complex"])
        self.assertLess(len(subprocess.list2cmdline(render["argv"])), 30_000)
        self.assertEqual(
            render["source_input_order"], ["screen-b"] * MAX_SEGMENTS
        )

    def test_mapping_must_have_exact_ids_and_exact_manifest_paths(self):
        source_manifest = _source_manifest()
        compiled = compile_sequence_plan(_plan(), source_manifest)
        manifest = _render_manifest()
        paths = _paths(manifest)

        variants = []
        missing = dict(paths)
        missing.pop("silent-c")
        variants.append(missing)
        extra = dict(paths, extra=_absolute("extra.mp4"))
        variants.append(extra)
        mismatched = dict(paths)
        mismatched["cam-a"] = _absolute("different.mp4")
        variants.append(mismatched)
        relative = dict(paths)
        relative["cam-a"] = "relative.mp4"
        variants.append(relative)
        for index, invalid in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(SequenceRenderError):
                build_sequence_render(
                    compiled, invalid, manifest, _absolute("out.mp4"))

    def test_manifest_inventory_is_hash_bound_to_compile_receipt(self):
        compiled = compile_sequence_plan(_plan(), _source_manifest())
        for mutation in ("sha256", "duration_ms", "source_id"):
            manifest = _render_manifest()
            if mutation == "sha256":
                manifest["sources"][0][mutation] = "d" * 64
            elif mutation == "duration_ms":
                manifest["sources"][0][mutation] += 1
            else:
                manifest["sources"][0][mutation] = "renamed"
            with self.subTest(mutation=mutation), self.assertRaises(
                    SequenceRenderError):
                build_sequence_render(
                    compiled, _paths(manifest), manifest, _absolute("out.mp4"))

    def test_no_audio_fails_unless_exact_source_is_safely_synthesized(self):
        with self.assertRaisesRegex(SequenceRenderError, "explicit silence"):
            self.build(use_silent=True, silent_audio=False)

        render = self.build(
            use_silent=True,
            silent_audio=False,
            synthesis=["silent-c"],
        )
        self.assertIn(
            "anullsrc=channel_layout=stereo:sample_rate=48000,"
            "atrim=duration=1.000,asetpts=PTS-STARTPTS[a003]",
            render["filter_complex"],
        )
        self.assertNotIn("[3:a:0]", render["filter_complex"])

        with self.assertRaisesRegex(SequenceRenderError, "has audio or is unused"):
            self.build(synthesis=["cam-a"])

    def test_invalid_technical_data_and_output_paths_fail_closed(self):
        compiled = compile_sequence_plan(_plan(), _source_manifest())
        mutators = (
            lambda value: value["output"].update(width=1919),
            lambda value: value["output"].update(fps_denominator=0),
            lambda value: value["sources"][0]["video"].update(height=0),
            lambda value: value["sources"][0]["video"].pop(
                "start_offset_ms"
            ),
            lambda value: value["sources"][0]["video"].update(
                start_offset_ms=True
            ),
            lambda value: value["sources"][0]["video"].update(
                duration_ms=0
            ),
            lambda value: value["sources"][0]["video"].update(
                end_offset_ms=value["sources"][0]["video"]["end_offset_ms"] + 1
            ),
            lambda value: value["sources"][0]["video"].update(
                start_offset_ms=value["sources"][0]["duration_ms"]
            ),
            lambda value: value["sources"][0]["audio"].update(channels=0),
            lambda value: value["sources"][0]["audio"].update(present="yes"),
            lambda value: value["sources"][0]["audio"].update(
                start_offset_ms=1.5
            ),
            lambda value: value["sources"][0]["audio"].update(
                duration_ms=0
            ),
            lambda value: value["sources"][0]["audio"].update(
                end_offset_ms=value["sources"][0]["audio"]["end_offset_ms"] + 1
            ),
            lambda value: value["sources"][0]["audio"].update(
                start_offset_ms=value["sources"][0]["duration_ms"]
            ),
            lambda value: value["sources"][0].update(debug=True),
        )
        for mutator in mutators:
            manifest = _render_manifest()
            mutator(manifest)
            with self.subTest(mutator=mutator), self.assertRaises(
                    SequenceRenderError):
                build_sequence_render(
                    compiled, _paths(manifest), manifest, _absolute("out.mp4"))

        manifest = _render_manifest(silent_audio=False)
        silent = next(source for source in manifest["sources"]
                      if source["source_id"] == "silent-c")
        silent["audio"]["start_offset_ms"] = 0
        with self.assertRaisesRegex(SequenceRenderError, "null technical"):
            build_sequence_render(
                compiled, _paths(manifest), manifest, _absolute("out.mp4"))

        manifest = _render_manifest()
        manifest["schema_version"] = "autoeditor-source-render-manifest/v2"
        with self.assertRaisesRegex(SequenceRenderError, "unsupported"):
            build_sequence_render(
                compiled, _paths(manifest), manifest, _absolute("out.mp4"))

        manifest = _render_manifest()
        with self.assertRaises(SequenceRenderError):
            build_sequence_render(
                compiled, _paths(manifest), manifest, _absolute("out.mov"))
        with self.assertRaises(SequenceRenderError):
            build_sequence_render(
                compiled, _paths(manifest), manifest,
                manifest["sources"][0]["path"])

    def test_paths_are_inert_argv_tokens_not_filter_or_shell_fragments(self):
        compiled = compile_sequence_plan(_plan(), _source_manifest())
        manifest = _render_manifest()
        hostile = _absolute("source;$(touch SHOULD_NOT_EXIST)&`whoami`.mp4")
        for source in manifest["sources"]:
            if source["source_id"] == "screen-b":
                source["path"] = hostile
        render = build_sequence_render(
            compiled, _paths(manifest), manifest,
            _absolute("output;$(echo NO).mp4"))

        self.assertIsInstance(render["argv"], list)
        hostile_alias = f".{os.sep}{Path(hostile).name}"
        input_position = render["argv"].index(hostile_alias)
        self.assertEqual(render["argv"][input_position - 1], "-i")
        self.assertNotIn(hostile, render["filter_complex"])
        self.assertNotIn("command", render)
        self.assertNotIn("shell", render)
        source = inspect.getsource(build_sequence_render)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("shell=True", source)
        self.assertFalse(Path("SHOULD_NOT_EXIST").exists())

    def test_times_are_fixed_milliseconds_and_outputs_are_normalized(self):
        render = self.build()
        graph = render["filter_complex"]
        decimals = re.findall(r"(?:start|end|duration)=([^,:;]+)", graph)
        self.assertTrue(decimals)
        self.assertTrue(all(re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{3}", value)
                            for value in decimals))
        for fragment in (
            "colorspace=ispace=bt709:itrc=bt709:iprimaries=bt709:"
            "irange=tv:all=bt709:range=tv:format=yuv420p:"
            "fast=0:dither=fsb",
            "scale=1920:1080:force_original_aspect_ratio=decrease",
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
            "fps=fps=30000/1001:round=near",
            "format=yuv420p",
            "setparams=range=tv:color_primaries=bt709:color_trc=bt709:"
            "colorspace=bt709",
            "aresample=48000",
            "channel_layouts=stereo",
        ):
            self.assertIn(fragment, graph)
        conversion = graph.index("colorspace=ispace=bt709")
        relabel = graph.index(
            "setparams=range=tv:color_primaries=bt709:color_trc=bt709"
        )
        concat = graph.index("concat=n=3:v=1:a=1")
        self.assertLess(conversion, relabel)
        self.assertLess(relabel, concat)
        argv = render["argv"]
        for pair in (
            ("-pix_fmt", "yuv420p"),
            ("-fps_mode", "cfr"),
            ("-r", "30000/1001"),
            ("-color_range", "tv"),
            ("-color_primaries", "bt709"),
            ("-color_trc", "bt709"),
            ("-colorspace", "bt709"),
            ("-ar", "48000"),
            ("-ac", "2"),
        ):
            position = argv.index(pair[0])
            self.assertEqual(argv[position + 1], pair[1])
        final_t = len(argv) - 1 - argv[::-1].index("-t")
        self.assertEqual(argv[final_t], "-t")
        self.assertEqual(argv[final_t + 1], "5.000")

    def test_declared_inferred_and_legacy_mjpeg_sources_get_explicit_conversion(self):
        manifest = _render_manifest()
        screen = next(source for source in manifest["sources"]
                      if source["source_id"] == "screen-b")
        screen["video"].update({
            "color_range": "pc",
            "color_space": "bt470bg",
            "color_transfer": "gamma28",
            "color_primaries": "bt470bg",
        })
        cam = next(source for source in manifest["sources"]
                   if source["source_id"] == "cam-a")
        cam["video"].update({
            "color_range": "unknown",
            "color_space": "unknown",
            "color_transfer": "unknown",
            "color_primaries": "unknown",
        })
        render = self.render_plan(_plan(), manifest)
        graph = render["filter_complex"]
        declared = (
            "colorspace=ispace=bt470bg:itrc=gamma28:"
            "iprimaries=bt470bg:irange=pc:all=bt709:range=tv:"
            "format=yuv420p:fast=0:dither=fsb"
        )
        inferred = (
            "colorspace=ispace=bt709:itrc=bt709:iprimaries=bt709:"
            "irange=tv:all=bt709:range=tv:format=yuv420p:"
            "fast=0:dither=fsb"
        )
        self.assertEqual(graph.count(declared), 2)
        self.assertEqual(graph.count(inferred), 1)

        mjpeg_manifest = _render_manifest()
        mjpeg = next(source for source in mjpeg_manifest["sources"]
                     if source["source_id"] == "cam-a")
        mjpeg["video"].update({
            "codec_name": "mjpeg",
            "pix_fmt": "yuvj422p",
            "color_range": "pc",
            "color_space": "smpte170m",
            "color_transfer": "unknown",
            "color_primaries": "unknown",
        })
        mjpeg_render = self.render_plan(
            _plan_for_segments([
                _segment("legacy-jpeg", "cam-a", "a" * 64, 0, 5_000),
            ]),
            mjpeg_manifest,
        )
        self.assertIn(
            "colorspace=ispace=smpte170m:itrc=smpte170m:"
            "iprimaries=smpte170m:irange=pc:all=bt709:range=tv:"
            "format=yuv420p:fast=0:dither=fsb",
            mjpeg_render["filter_complex"],
        )

    def test_real_sequence_render_converts_each_source_and_tags_bt709(self):
        tools = _discover_ffmpeg_pair()
        if tools is None:
            self.skipTest("bundled/system FFmpeg and FFprobe are unavailable")
        ffmpeg, ffprobe = tools
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bt470 = root / "bt470.mp4"
            untagged = root / "untagged.mp4"
            output = root / "sequence.mp4"
            commands = [
                [
                    ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=160x90:r=30:d=2.500", "-an",
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
                    "smptebars=s=160x90:r=30:d=2.500", "-an",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", str(untagged),
                ],
            ]
            for command in commands:
                generated = subprocess.run(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", shell=False,
                )
                self.assertEqual(generated.returncode, 0, generated.stderr)

            source_a = {
                "source_id": "bt470", "sha256": hashlib.sha256(
                    bt470.read_bytes()).hexdigest(), "duration_ms": 2_500,
            }
            source_b = {
                "source_id": "untagged", "sha256": hashlib.sha256(
                    untagged.read_bytes()).hexdigest(), "duration_ms": 2_500,
            }
            source_manifest = {
                "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
                "sources": [source_a, source_b],
            }
            plan = {
                "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
                "sources": copy.deepcopy(source_manifest["sources"]),
                "target_duration": {"min_ms": 5_000, "max_ms": 5_000},
                "segments": [
                    _segment(
                        "declared-first", "bt470", source_a["sha256"],
                        0, 2_500,
                    ),
                    _segment(
                        "inferred-second", "untagged", source_b["sha256"],
                        0, 2_500,
                    ),
                ],
            }

            def render_source(source: dict, path: Path, color: dict) -> dict:
                return {
                    **source, "path": str(path),
                    "video": {
                        "width": 160, "height": 90,
                        "fps_numerator": 30, "fps_denominator": 1,
                        "start_offset_ms": 0, "duration_ms": 2_500,
                        "end_offset_ms": 2_500, "codec_name": "h264",
                        "pix_fmt": "yuv420p", **color,
                    },
                    "audio": {
                        "present": False, "sample_rate": None,
                        "channels": None, "start_offset_ms": None,
                        "duration_ms": None, "end_offset_ms": None,
                    },
                }

            manifest = {
                "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
                "output": {
                    "width": 320, "height": 180,
                    "fps_numerator": 30, "fps_denominator": 1,
                },
                "sources": [
                    render_source(source_a, bt470, {
                        "color_range": "tv", "color_space": "bt470bg",
                        "color_transfer": "bt470bg",
                        "color_primaries": "bt470bg",
                    }),
                    render_source(source_b, untagged, {
                        "color_range": "unknown", "color_space": "unknown",
                        "color_transfer": "unknown",
                        "color_primaries": "unknown",
                    }),
                ],
            }
            compiled = compile_sequence_plan(plan, source_manifest)
            render = build_sequence_render(
                compiled, _paths(manifest), manifest, str(output),
                ffmpeg_path=ffmpeg,
                synthesize_silence_for=["bt470", "untagged"],
            )
            Path(render["filter_script_path"]).write_text(
                render["filter_complex"], encoding="utf-8"
            )
            completed = subprocess.run(
                render["argv"], cwd=render["working_directory"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", shell=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            probed = subprocess.run(
                [
                    ffprobe, "-v", "error", "-show_entries",
                    "stream=codec_name,pix_fmt,color_range,color_space,"
                    "color_transfer,color_primaries:format=duration",
                    "-of", "json", str(output),
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", shell=False,
            )
            self.assertEqual(probed.returncode, 0, probed.stderr)
            facts = json.loads(probed.stdout)

        video = next(stream for stream in facts["streams"]
                     if stream["codec_name"] == "h264")
        self.assertEqual(video["pix_fmt"], "yuv420p")
        self.assertEqual(video["color_range"], "tv")
        self.assertEqual(video["color_space"], "bt709")
        self.assertEqual(video["color_transfer"], "bt709")
        self.assertEqual(video["color_primaries"], "bt709")
        self.assertAlmostEqual(float(facts["format"]["duration"]), 5.0, delta=0.1)
        self.assertIn("colorspace=ispace=bt470bg", render["filter_complex"])
        self.assertIn("colorspace=ispace=bt709", render["filter_complex"])

    def test_hdr_partial_high_bit_depth_and_broad_mjpeg_inference_fail_closed(self):
        mutations = (
            {
                "color_space": "bt709", "color_transfer": "unknown",
                "color_primaries": "bt709",
            },
            {
                "color_space": "bt2020nc", "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
            },
            {"pix_fmt": "yuv420p10le"},
            {
                "codec_name": "mjpeg", "pix_fmt": "yuvj420p",
                "color_range": "tv", "color_space": "bt470bg",
                "color_transfer": "unknown", "color_primaries": "unknown",
            },
            {
                "codec_name": "mjpeg", "pix_fmt": "yuvj420p",
                "color_range": "pc", "color_space": "bt709",
                "color_transfer": "unknown", "color_primaries": "unknown",
            },
        )
        for index, mutation in enumerate(mutations):
            manifest = _render_manifest()
            manifest["sources"][0]["video"].update(mutation)
            with self.subTest(index=index), self.assertRaises(
                    SequenceRenderError):
                self.render_plan(_plan(), manifest)

    def test_compiled_payload_is_closed_hash_bound_and_bounded(self):
        compiled = compile_sequence_plan(_plan(), _source_manifest())
        manifest = _render_manifest()

        extra = copy.deepcopy(compiled)
        extra["shell"] = True
        with self.assertRaises(SequenceRenderError):
            build_sequence_render(
                extra, _paths(manifest), manifest, _absolute("out.mp4"))

        changed = copy.deepcopy(compiled)
        changed["ffmpeg_segments"][0]["source_start_ms"] += 1
        with self.assertRaises(SequenceRenderError):
            build_sequence_render(
                changed, _paths(manifest), manifest, _absolute("out.mp4"))

        too_many = copy.deepcopy(compiled)
        template = too_many["ffmpeg_segments"][0]
        too_many["ffmpeg_segments"] = [
            {**copy.deepcopy(template), "sequence_index": index,
             "segment_id": f"segment-{index}"}
            for index in range(MAX_SEGMENTS + 1)
        ]
        with self.assertRaisesRegex(SequenceRenderError, "1-256 segments"):
            build_sequence_render(
                too_many, _paths(manifest), manifest, _absolute("out.mp4"))

        empty = copy.deepcopy(compiled)
        empty["ffmpeg_segments"] = []
        with self.assertRaisesRegex(SequenceRenderError, "1-256 segments"):
            build_sequence_render(
                empty, _paths(manifest), manifest, _absolute("out.mp4"))


if __name__ == "__main__":
    unittest.main()
