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

from autoeditor.edit_policy import (
    CAPABILITIES,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    edit_policy_sha256,
    resolve_edit_policy,
)
from autoeditor.sequence_plan import (
    SEQUENCE_PLAN_SCHEMA_VERSION,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    compile_sequence_plan,
)
from autoeditor.sequence_render import SOURCE_RENDER_MANIFEST_SCHEMA_VERSION
from autoeditor.transition_plan import (
    TRANSITION_PLAN_SCHEMA_VERSION,
    TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
    compile_transition_plan,
    derive_boundary_id,
    transition_compile_receipt_sha256,
    transition_sequence_manifest_sha256,
)
from autoeditor.transition_render import (
    MAX_WINDOWS_COMMAND_LINE_CHARACTERS,
    TRANSITION_RENDER_RECEIPT_SCHEMA_VERSION,
    TRANSITION_RENDER_SCHEMA_VERSION,
    TransitionRenderError,
    build_transition_render,
    build_transition_render_argv,
    transition_render_receipt_sha256,
    validate_transition_render_receipt,
)


def _fixture_dir() -> Path:
    return (Path.cwd() / "transition-render-fixtures").resolve()


def _auto_values() -> dict[str, str]:
    return {
        "cut_density": "auto",
        "sfx_density": "auto",
        "transition_density": "auto",
        "dialogue_rule": "auto",
        "music_rule": "auto",
        "caption_rule": "auto",
        "visualization_rule": "auto",
    }


def _policy(duration_ms: int) -> dict:
    explicit = _auto_values()
    explicit["transition_density"] = "dense"
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": "commercial_product",
        "duration_ms": duration_ms,
        "delivery": {"platform": "youtube", "aspect": "auto"},
        "explicit_intent": explicit,
        "consented_preferences": {
            "consented": False,
            "values": _auto_values(),
        },
        "available_capabilities": sorted(CAPABILITIES),
    })


def _source(source_id: str, character: str, duration_ms: int) -> dict:
    return {
        "source_id": source_id,
        "sha256": character * 64,
        "duration_ms": duration_ms,
    }


def _segment(
    index: int,
    source: dict,
    start_ms: int,
    duration_ms: int,
) -> dict:
    return {
        "segment_id": f"seg-{index:03d}",
        "source_id": source["source_id"],
        "source_sha256": source["sha256"],
        "source_start_ms": start_ms,
        "source_end_ms": start_ms + duration_ms,
        "role": "development",
        "reason": f"Deterministic transition-render segment {index}.",
        "speech_anchor": None,
        "transition": {"kind": "hard_cut"},
    }


def _render_source(
    source: dict,
    path: Path,
    fps: tuple[int, int],
    *,
    audio_present: bool = True,
    video_start_offset_ms: int = 0,
    audio_start_offset_ms: int = 0,
    color: dict[str, str] | None = None,
) -> dict:
    selected_color = color or {
        "codec_name": "h264",
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }
    return {
        **copy.deepcopy(source),
        "path": str(path.resolve()),
        "video": {
            "width": 1920,
            "height": 1080,
            "fps_numerator": fps[0],
            "fps_denominator": fps[1],
            "start_offset_ms": video_start_offset_ms,
            "duration_ms": source["duration_ms"] - video_start_offset_ms,
            "end_offset_ms": source["duration_ms"],
            **selected_color,
        },
        "audio": {
            "present": audio_present,
            "sample_rate": 44_100 if audio_present else None,
            "channels": 1 if audio_present else None,
            "start_offset_ms": audio_start_offset_ms if audio_present else None,
            "duration_ms": (
                source["duration_ms"] - audio_start_offset_ms
                if audio_present else None
            ),
            "end_offset_ms": source["duration_ms"] if audio_present else None,
        },
    }


def _compiled_transitions(
    compiled_sequence: dict,
    fps: tuple[int, int],
    decisions: list[tuple[str, int]],
) -> dict:
    segments = compiled_sequence["ffmpeg_segments"]
    manifest = {
        "schema_version": TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
        "sequence_plan_sha256": compiled_sequence["receipt"][
            "sequence_plan_sha256"
        ],
        "sequence_compile_receipt_sha256": compiled_sequence["receipt_sha256"],
        "frame_rate": {"numerator": fps[0], "denominator": fps[1]},
        "segments": [{
            "segment_id": item["segment_id"],
            "source_sha256": item["source_sha256"],
            "duration_ms": item["duration_ms"],
            "video_leading_handle_ms": min(1_000, item["duration_ms"]),
            "video_trailing_handle_ms": min(1_000, item["duration_ms"]),
            "audio_leading_handle_ms": min(1_000, item["duration_ms"]),
            "audio_trailing_handle_ms": min(1_000, item["duration_ms"]),
            "dialogue_at_start": False,
            "dialogue_at_end": False,
        } for item in segments],
    }
    policy = _policy(compiled_sequence["receipt"]["total_duration_ms"])
    motivation = policy["rules"]["transitions"]["usage"]
    cumulative_ms = 0
    boundaries = []
    for index, left in enumerate(manifest["segments"][:-1]):
        cumulative_ms += left["duration_ms"]
        right = manifest["segments"][index + 1]
        kind, duration_ms = decisions[index]
        boundaries.append({
            "boundary_id": derive_boundary_id(
                left["segment_id"], right["segment_id"],
                left["source_sha256"], right["source_sha256"], cumulative_ms,
            ),
            "left_segment_id": left["segment_id"],
            "right_segment_id": right["segment_id"],
            "left_source_sha256": left["source_sha256"],
            "right_source_sha256": right["source_sha256"],
            "cumulative_boundary_ms": cumulative_ms,
            "kind": kind,
            "motivation": motivation,
            "duration_ms": duration_ms,
            "audio_behavior": (
                "hard_cut" if kind == "hard_cut" else "equal_power_crossfade"
            ),
            "motivation_verified": kind != "hard_cut",
            "semantic_safety_verified": True,
            "dialogue_preservation_verified": True,
        })
    plan = {
        "schema_version": TRANSITION_PLAN_SCHEMA_VERSION,
        "sequence_manifest_sha256": transition_sequence_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "frame_rate": copy.deepcopy(manifest["frame_rate"]),
        "policy": copy.deepcopy(policy["rules"]["transitions"]),
        "boundaries": boundaries,
    }
    return compile_transition_plan(plan, manifest, policy)


def _case(
    count: int = 4,
    *,
    segment_duration_ms: int | None = None,
    fps: tuple[int, int] = (30, 1),
    decisions: list[tuple[str, int]] | None = None,
    source_order: list[int] | None = None,
    base_dir: Path | None = None,
    path_names: list[str] | None = None,
    selection_start_ms: int = 0,
    video_start_offset_ms: int = 0,
    audio_start_offset_ms: int = 0,
    audio_present: bool = True,
    color: dict[str, str] | None = None,
) -> dict:
    if segment_duration_ms is None:
        segment_duration_ms = max(34, (5_000 + count - 1) // count)
    if source_order is None:
        source_order = [0] * count
    source_count = max(source_order) + 1
    source_duration_ms = max(10_000, selection_start_ms + segment_duration_ms)
    sources = [
        _source(f"source-{index:02d}", chr(ord("a") + index), source_duration_ms)
        for index in range(source_count)
    ]
    source_manifest = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sources": copy.deepcopy(sources),
    }
    segments = [
        _segment(index, sources[source_order[index]], selection_start_ms,
                 segment_duration_ms)
        for index in range(count)
    ]
    total_duration_ms = count * segment_duration_ms
    plan = {
        "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
        "sources": copy.deepcopy(sources),
        "target_duration": {
            "min_ms": total_duration_ms,
            "max_ms": total_duration_ms,
        },
        "segments": segments,
    }
    compiled_sequence = compile_sequence_plan(plan, source_manifest)
    work = (base_dir or _fixture_dir()).resolve()
    if path_names is None:
        path_names = [f"source-{index:02d}.mp4" for index in range(source_count)]
    render_sources = [
        _render_source(
            source,
            work / path_names[index],
            fps,
            audio_present=audio_present,
            video_start_offset_ms=video_start_offset_ms,
            audio_start_offset_ms=audio_start_offset_ms,
            color=color,
        )
        for index, source in enumerate(sources)
    ]
    render_manifest = {
        "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
        "output": {
            "width": 1280,
            "height": 720,
            "fps_numerator": fps[0],
            "fps_denominator": fps[1],
        },
        "sources": render_sources,
    }
    if decisions is None:
        decisions = [("hard_cut", 0)] * (count - 1)
    transitions = _compiled_transitions(compiled_sequence, fps, decisions)
    return {
        "compiled_sequence": compiled_sequence,
        "source_paths": {
            source["source_id"]: source["path"] for source in render_sources
        },
        "render_manifest": render_manifest,
        "transitions": transitions,
        "output_path": str((work / "finished.mp4").resolve()),
        "synthesize_silence_for": (
            [source["source_id"] for source in sources]
            if not audio_present else []
        ),
    }


def _build(case: dict, *, ffmpeg_path: str = "ffmpeg") -> dict:
    return build_transition_render(
        case["compiled_sequence"],
        case["source_paths"],
        case["render_manifest"],
        case["transitions"],
        case["output_path"],
        ffmpeg_path=ffmpeg_path,
        synthesize_silence_for=case["synthesize_silence_for"],
    )


def _resign_compiled_transitions(value: dict) -> None:
    canonical = json.dumps(
        value["compiled_boundaries"], ensure_ascii=True, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    value["receipt"]["compiled_boundaries_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    value["receipt_sha256"] = transition_compile_receipt_sha256(value["receipt"])


def _discover_ffmpeg_pair() -> tuple[str, str] | None:
    ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "").strip()
    ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "").strip()
    if not ffmpeg:
        ffmpeg = shutil.which("ffmpeg") or ""
    if not ffprobe:
        ffprobe = shutil.which("ffprobe") or ""
    if not ffmpeg:
        date_root = next(
            (parent for parent in Path.cwd().parents
             if parent.name.count("-") == 2 and parent.name[:4].isdigit()),
            None,
        )
        if date_root is not None:
            candidates = sorted(
                date_root.glob("*/outputs/*/*/resources/bin/ffmpeg.exe"),
                reverse=True,
            )
            if candidates:
                ffmpeg = str(candidates[0])
    if ffmpeg and not ffprobe:
        suffix = ".exe" if Path(ffmpeg).suffix.lower() == ".exe" else ""
        adjacent = Path(ffmpeg).with_name(f"ffprobe{suffix}")
        if adjacent.is_file():
            ffprobe = str(adjacent)
    if not ffmpeg or not ffprobe or not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
        return None
    return str(Path(ffmpeg).resolve()), str(Path(ffprobe).resolve())


class TransitionRenderContractTests(unittest.TestCase):
    def test_mixed_binary_chain_binds_order_offsets_duration_and_receipts(self):
        case = _case(
            count=4,
            segment_duration_ms=2_000,
            source_order=[1, 0, 1, 2],
            decisions=[
                ("cross_dissolve", 400),
                ("hard_cut", 0),
                ("dip_to_black", 200),
            ],
        )
        render = _build(case)

        self.assertEqual(render["schema_version"], TRANSITION_RENDER_SCHEMA_VERSION)
        self.assertEqual(render["expected_output_duration_ms"], 7_400)
        self.assertEqual(render["source_input_order"], [
            "source-01", "source-00", "source-01", "source-02",
        ])
        self.assertEqual(
            [item["kind"] for item in render["topology"]],
            ["cross_dissolve", "hard_cut", "dip_to_black"],
        )
        graph = render["filter_complex"]
        self.assertIn(
            "xfade=transition=fade:duration=0.400:offset=1.600", graph
        )
        self.assertIn("concat=n=2:v=1:a=0", graph)
        self.assertIn(
            "xfade=transition=fadeblack:duration=0.200:offset=5.400", graph
        )
        self.assertEqual(graph.count("c1=qsin:c2=qsin"), 2)
        self.assertNotIn("concat=n=4:v=1:a=1", graph)
        self.assertEqual(render["argv"][-1], f".{os.sep}finished.mp4")
        thread_position = render["argv"].index("-filter_complex_threads")
        self.assertEqual(render["argv"][thread_position:thread_position + 2], [
            "-filter_complex_threads", "1",
        ])
        self.assertEqual(render["argv"].count("-filter_complex_threads"), 1)
        self.assertLess(thread_position, render["argv"].index("-i"))
        self.assertEqual(render["argv"][render["argv"].index("-filter_complex_script") + 1],
                         f".{os.sep}finished-filter.txt")
        self.assertEqual(render["argv"][-3:-1], ["-movflags", "+faststart"])
        self.assertIn("7.400", render["argv"])
        for option, expected in (
            ("-color_range", "tv"),
            ("-color_primaries", "bt709"),
            ("-color_trc", "bt709"),
            ("-colorspace", "bt709"),
            ("-ar", "48000"),
            ("-ac", "2"),
        ):
            self.assertEqual(render["argv"][render["argv"].index(option) + 1],
                             expected)

        receipt = validate_transition_render_receipt(render["executor_receipt"])
        self.assertEqual(
            receipt["schema_version"], TRANSITION_RENDER_RECEIPT_SCHEMA_VERSION
        )
        self.assertEqual(receipt["expected_output_duration_ms"], 7_400)
        self.assertEqual(
            transition_render_receipt_sha256(receipt),
            render["executor_receipt_sha256"],
        )
        self.assertEqual(
            receipt["transition_compile_receipt_sha256"],
            render["transition_compile_receipt_sha256"],
        )

    def test_exact_sequence_normalization_is_retained_for_offsets_color_and_silence(self):
        bt470 = {
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "color_range": "pc",
            "color_space": "bt470bg",
            "color_transfer": "gamma28",
            "color_primaries": "bt470bg",
        }
        delayed = _case(
            count=2,
            segment_duration_ms=2_500,
            selection_start_ms=500,
            video_start_offset_ms=500,
            audio_start_offset_ms=1_000,
            color=bt470,
        )
        render = _build(delayed)
        graph = render["filter_complex"]
        self.assertIn(
            "colorspace=ispace=bt470bg:itrc=gamma28:iprimaries=bt470bg:",
            graph,
        )
        self.assertIn("irange=pc:all=bt709:range=tv", graph)
        self.assertEqual(graph.count("adelay=500:all=1"), 2)
        self.assertIn("aresample=48000:async=0:first_pts=0", graph)
        self.assertIn("channel_layouts=stereo", graph)
        self.assertTrue(all(
            item["video_local_start_ms"] == 0
            and item["audio_lead_silence_ms"] == 500
            for item in render["timing_receipt"]["segment_timing"]
        ))

        silent = _case(count=2, segment_duration_ms=2_500, audio_present=False)
        silent_render = _build(silent)
        self.assertEqual(silent_render["filter_complex"].count(
            "anullsrc=channel_layout=stereo:sample_rate=48000"
        ), 2)
        self.assertNotIn("[0:a:0]", silent_render["filter_complex"])

    def test_transition_result_tamper_replay_and_missing_boundary_fail_closed(self):
        case = _case(
            count=3,
            segment_duration_ms=2_000,
            decisions=[("cross_dissolve", 200), ("hard_cut", 0)],
        )
        injected = copy.deepcopy(case)
        injected["transitions"]["compiled_boundaries"][0][
            "video_ffmpeg_primitive_tokens"
        ] = ["movie=/tmp/owned;null"]
        _resign_compiled_transitions(injected["transitions"])
        with self.assertRaises(TransitionRenderError):
            _build(injected)

        missing = copy.deepcopy(case)
        missing["transitions"]["compiled_boundaries"].pop()
        with self.assertRaises(TransitionRenderError):
            _build(missing)

        rebound = copy.deepcopy(case)
        rebound["transitions"]["receipt"][
            "sequence_compile_receipt_sha256"
        ] = "f" * 64
        rebound["transitions"]["receipt_sha256"] = (
            transition_compile_receipt_sha256(rebound["transitions"]["receipt"])
        )
        with self.assertRaises(TransitionRenderError):
            _build(rebound)

        other = _case(count=3, segment_duration_ms=2_100)
        other["transitions"] = copy.deepcopy(case["transitions"])
        with self.assertRaises(TransitionRenderError):
            _build(other)

        adjacency = copy.deepcopy(case)
        adjacency["transitions"]["compiled_boundaries"][0][
            "right_segment_id"
        ] = "seg-999"
        _resign_compiled_transitions(adjacency["transitions"])
        with self.assertRaises(TransitionRenderError):
            _build(adjacency)

        policy_replay = copy.deepcopy(case)
        policy_replay["transitions"]["receipt"]["policy"]["density"] = "none"
        policy_replay["transitions"]["receipt_sha256"] = (
            transition_compile_receipt_sha256(
                policy_replay["transitions"]["receipt"]
            )
        )
        with self.assertRaises(TransitionRenderError):
            _build(policy_replay)

    def test_paths_are_argv_aliases_never_filter_or_shell_programs(self):
        hostile_name = "clip & calc ; [movie] $(touch-owned).mp4"
        case = _case(
            count=2,
            segment_duration_ms=2_500,
            path_names=[hostile_name],
        )
        case["output_path"] = str(
            (_fixture_dir() / "output & harmless ; [x].mp4").resolve()
        )
        render = _build(case, ffmpeg_path="ffmpeg")
        self.assertNotIn(hostile_name, render["filter_complex"])
        self.assertNotIn(str(_fixture_dir()), render["argv"])
        input_alias = f".{os.sep}{hostile_name}"
        self.assertEqual(render["argv"].count(input_alias), 2)
        self.assertEqual(render["argv"][0], "ffmpeg")
        self.assertNotIn("-filter_complex", render["argv"])
        self.assertLessEqual(
            len(subprocess.list2cmdline(render["argv"])),
            MAX_WINDOWS_COMMAND_LINE_CHARACTERS,
        )
        self.assertEqual(
            build_transition_render_argv(
                case["compiled_sequence"], case["source_paths"],
                case["render_manifest"], case["transitions"],
                case["output_path"], ffmpeg_path="ffmpeg",
            ),
            render["argv"],
        )

        alias_mismatch = copy.deepcopy(case)
        alias_mismatch["source_paths"]["source-00"] = str(
            (_fixture_dir() / "different.mp4").resolve()
        )
        with self.assertRaises(TransitionRenderError):
            _build(alias_mismatch)

        script_collision = _case(
            count=2,
            segment_duration_ms=2_500,
            path_names=["finished-filter.txt"],
        )
        with self.assertRaisesRegex(TransitionRenderError, "filter script"):
            _build(script_collision)

    def test_frame_rational_controls_canonical_timed_tokens(self):
        for fps in ((30, 1), (30_000, 1_001)):
            with self.subTest(fps=fps):
                case = _case(
                    count=2,
                    segment_duration_ms=2_500,
                    fps=fps,
                    decisions=[("cross_dissolve", 200)],
                )
                render = _build(case)
                self.assertIn(
                    "xfade=transition=fade:duration=0.200:offset=2.300",
                    render["filter_complex"],
                )
                self.assertEqual(render["expected_output_duration_ms"], 4_800)
                self.assertEqual(render["executor_receipt"]["frame_rate"], {
                    "numerator": fps[0], "denominator": fps[1],
                })

    def test_one_61_121_and_256_segments_remain_linear_and_windows_bounded(self):
        for count in (1, 61, 121, 256):
            with self.subTest(count=count):
                case = _case(count=count)
                render = _build(case)
                self.assertEqual(render["segment_count"], count)
                self.assertEqual(render["boundary_count"], count - 1)
                self.assertEqual(len(render["topology"]), count - 1)
                self.assertEqual(render["argv"].count("-i"), count)
                self.assertEqual(render["argv"].count("-ss"), count)
                self.assertEqual(render["argv"].count("-t"), count + 1)
                self.assertEqual(len(render["source_input_order"]), count)
                self.assertEqual(
                    render["filter_complex"].count("concat=n=2:v=1:a=0"),
                    count - 1,
                )
                self.assertLessEqual(
                    len(subprocess.list2cmdline(render["argv"])),
                    MAX_WINDOWS_COMMAND_LINE_CHARACTERS,
                )
                self.assertNotIn(render["filter_complex"], render["argv"])

    def test_receipt_mutation_changes_hash_and_closed_shape_rejects_extras(self):
        render = _build(_case(count=2, segment_duration_ms=2_500))
        original = render["executor_receipt"]
        mutated = copy.deepcopy(original)
        mutated["artifact_target"] = str(
            (_fixture_dir() / "different.mp4").resolve()
        )
        self.assertNotEqual(
            transition_render_receipt_sha256(mutated),
            render["executor_receipt_sha256"],
        )
        extra = copy.deepcopy(original)
        extra["planner_note"] = "execute me"
        with self.assertRaises(TransitionRenderError):
            validate_transition_render_receipt(extra)

    def test_oversized_repeated_alias_is_rejected_before_process_creation(self):
        case = _case(
            count=256,
            path_names=[("x" * 180) + ".mp4"],
        )
        with self.assertRaisesRegex(TransitionRenderError, "Windows command-line"):
            _build(case)

    def test_real_ffmpeg_mixed_hard_and_timed_transition_has_exact_av_extent(self):
        pair = _discover_ffmpeg_pair()
        if pair is None:
            self.skipTest("shipped/system FFmpeg and FFprobe were not discoverable")
        ffmpeg, ffprobe = pair
        with tempfile.TemporaryDirectory(prefix="transition-render-") as raw_temp:
            work = Path(raw_temp).resolve()
            colors = ("red", "green", "blue")
            frequencies = (330, 440, 550)
            paths = []
            for index, (color_name, frequency) in enumerate(zip(colors, frequencies)):
                path = work / f"source-{index:02d}.mp4"
                command = [
                    ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i",
                    f"color=c={color_name}:s=320x180:r=30:d=2",
                    "-f", "lavfi", "-i",
                    f"sine=frequency={frequency}:sample_rate=48000:duration=2",
                    "-map", "0:v:0", "-map", "1:a:0", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-color_range", "tv",
                    "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-colorspace", "bt709", "-c:a", "aac", "-ar", "48000",
                    "-ac", "2", str(path),
                ]
                subprocess.run(command, check=True, shell=False, timeout=60)
                paths.append(path)

            sources = [{
                "source_id": f"source-{index:02d}",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "duration_ms": 2_000,
            } for index, path in enumerate(paths)]
            source_manifest = {
                "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
                "sources": copy.deepcopy(sources),
            }
            sequence_plan = {
                "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
                "sources": copy.deepcopy(sources),
                "target_duration": {"min_ms": 6_000, "max_ms": 6_000},
                "segments": [
                    _segment(index, source, 0, 2_000)
                    for index, source in enumerate(sources)
                ],
            }
            compiled = compile_sequence_plan(sequence_plan, source_manifest)
            render_sources = [
                _render_source(source, path, (30, 1))
                for source, path in zip(sources, paths)
            ]
            manifest = {
                "schema_version": SOURCE_RENDER_MANIFEST_SCHEMA_VERSION,
                "output": {
                    "width": 320, "height": 180,
                    "fps_numerator": 30, "fps_denominator": 1,
                },
                "sources": render_sources,
            }
            transitions = _compiled_transitions(
                compiled, (30, 1),
                [("hard_cut", 0), ("cross_dissolve", 200)],
            )
            output = work / "finished.mp4"
            repeated_output = work / "finished-repeat.mp4"
            for target in (output, repeated_output):
                render = build_transition_render(
                    compiled,
                    {source["source_id"]: str(path)
                     for source, path in zip(sources, paths)},
                    manifest,
                    transitions,
                    target,
                    ffmpeg_path=ffmpeg,
                )
                Path(render["filter_script_path"]).write_text(
                    render["filter_complex"], encoding="utf-8"
                )
                subprocess.run(
                    render["argv"], cwd=render["working_directory"],
                    check=True, shell=False, timeout=120,
                )
            self.assertEqual(
                hashlib.sha256(output.read_bytes()).hexdigest(),
                hashlib.sha256(repeated_output.read_bytes()).hexdigest(),
                "repeated production transition renders must be byte-identical",
            )

            probe = subprocess.run([
                ffprobe, "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,duration,sample_rate,channels,"
                "color_range,color_space,color_transfer,color_primaries",
                "-of", "json", str(output),
            ], check=True, capture_output=True, text=True, shell=False, timeout=30)
            facts = json.loads(probe.stdout)
            format_duration = float(facts["format"]["duration"])
            stream_durations = {
                stream["codec_type"]: float(stream["duration"])
                for stream in facts["streams"]
                if stream.get("duration") not in {None, "N/A"}
            }
            self.assertAlmostEqual(format_duration, 5.8, delta=0.04)
            self.assertAlmostEqual(stream_durations["video"], 5.8, delta=0.04)
            self.assertAlmostEqual(stream_durations["audio"], 5.8, delta=0.06)
            self.assertLess(
                abs(stream_durations["video"] - stream_durations["audio"]),
                0.06,
            )
            video = next(
                stream for stream in facts["streams"]
                if stream["codec_type"] == "video"
            )
            audio = next(
                stream for stream in facts["streams"]
                if stream["codec_type"] == "audio"
            )
            self.assertEqual(video["color_range"], "tv")
            self.assertEqual(video["color_space"], "bt709")
            self.assertEqual(video["color_transfer"], "bt709")
            self.assertEqual(video["color_primaries"], "bt709")
            self.assertEqual(audio["sample_rate"], "48000")
            self.assertEqual(audio["channels"], 2)

            black = subprocess.run([
                ffmpeg, "-hide_banner", "-nostdin", "-i", str(output),
                "-an", "-vf", "blackdetect=d=0.04:pix_th=0.02",
                "-f", "null", "-",
            ], capture_output=True, text=True, shell=False, timeout=60)
            self.assertEqual(black.returncode, 0, black.stderr)
            self.assertNotIn("black_start:", black.stderr)


if __name__ == "__main__":
    unittest.main()
