from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from autoeditor import calibrate, pipeline


class SafetyContracts(unittest.TestCase):
    def test_calibration_is_bound_to_raw_hash(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "take.mov"
            raw.write_bytes(b"original raw bytes")
            sidecar = calibrate.write_certification(raw, -100)
            payload = json.loads(sidecar.read_text())
            self.assertEqual(payload["offset_ms"], -100)
            self.assertEqual(
                payload["source_sha256"],
                hashlib.sha256(raw.read_bytes()).hexdigest(),
            )
            self.assertEqual(pipeline.certified_av_offset(raw)[0], -100)
            raw.write_bytes(b"replacement under the same filename")
            offset, note = pipeline.certified_av_offset(raw)
            self.assertEqual(offset, 0)
            self.assertIn("does not match", note)

    def test_gate_rejects_applied_value_that_is_not_certified(self):
        with tempfile.TemporaryDirectory() as td:
            result = pipeline.verify_sync_source(
                Path(td) / "master.mp4",
                Path(td) / "raw.mov",
                {},
                applied_ms=-200,
                certified_ms=0,
                final_words=[],
                workdir=Path(td),
            )
        self.assertFalse(result["ok"])
        self.assertIn("not the certified", result["note"])

    def test_uncertified_offset_is_rejected_before_render(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "recording.mov"
            raw.write_bytes(b"original source")
            with self.assertRaisesRegex(ValueError, r"requested \+100ms"):
                pipeline.resolve_av_offset(raw, 100)
            applied, certified, note = pipeline.resolve_av_offset(raw, 0)
        self.assertEqual((applied, certified), (0, 0))
        self.assertIn("certified default is 0ms", note)

    def test_outputs_are_quarantined_until_explicit_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            final = Path(td) / "PSE_MASTER_16x9.mp4"
            final.write_bytes(b"completed but ungated")
            quarantined, final_paths = pipeline.quarantine_outputs(
                {"16x9": final}
            )
            held = quarantined["16x9"]
            self.assertFalse(final.exists())
            self.assertTrue(held.exists())
            self.assertIn(".UNVERIFIED", held.name)
            promoted = pipeline.promote_outputs(quarantined, final_paths)
            self.assertEqual(promoted["16x9"], final)
            self.assertTrue(final.exists())
            self.assertFalse(held.exists())

    def test_backward_raw_mapping_is_a_hard_failure(self):
        matches = [
            (5.0, 10.0),
            (10.0, 15.0),
            (15.0, 14.5),
            (20.0, 25.0),
        ]
        failures = pipeline._nonmonotonic_matches(matches)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["from_raw_t"], 15.0)
        self.assertEqual(failures[0]["to_raw_t"], 14.5)

    def test_multi_aspect_release_is_not_supported(self):
        self.assertNotIn("all", pipeline.SUPPORTED_ASPECTS)

    def test_container_stream_start_delta_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            media = Path(td) / "offset.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=160x90:rate=30:duration=3",
                "-itsoffset", "0.125", "-f", "lavfi", "-i",
                "sine=frequency=733:sample_rate=48000:duration=2.8",
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(media),
            ], check=True)
            delta = pipeline._stream_start_delta(media)
        self.assertGreater(delta, 0.08)
        self.assertLess(delta, 0.14)

    def test_failed_qa_cannot_reach_video_send(self):
        source = Path(pipeline.__file__).read_text()
        qa_guard = source.index('if not qa["pass"]:')
        send = source.index("providers.send_video(")
        self.assertLess(qa_guard, send)

    def test_main_builds_final_transcript_before_artifact_gates(self):
        source = Path(pipeline.__file__).read_text()
        assignment = source.index("final_words = transcribe(main_out_v, work)")
        retake_gate = source.index("residue = verify_no_retakes(final_words")
        source_gate = source.index("ssync = verify_sync_source(main_out_v")
        self.assertLess(assignment, retake_gate)
        self.assertLess(assignment, source_gate)

    def test_cleanup_loop_cuts_and_retranscribes_inside_each_pass(self):
        tree = ast.parse(Path(pipeline.__file__).read_text())
        main = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        loops = [
            node for node in ast.walk(main)
            if isinstance(node, ast.For)
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and any(
                isinstance(arg, ast.Constant) and arg.value == 6
                for arg in node.iter.args
            )
        ]
        self.assertEqual(len(loops), 1)
        calls = {
            node.func.id
            for statement in loops[0].body
            for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("apply_cuts", calls)
        self.assertIn("transcribe", calls)

    def test_incomplete_semantic_judgment_blocks_cut_implicated_sentence(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            script = work / "script.txt"
            tokens = "one two three four five six seven eight nine ten"
            script.write_text(tokens + ".")
            final_words = [
                {"w": word, "s": i * 0.4, "e": i * 0.4 + 0.25, "p": 0.99}
                for i, word in enumerate(tokens.split()[:8])
            ]
            old_run = pipeline.run
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = [(1.5, 0.5)]
            pipeline.run = lambda *args, **kwargs: types.SimpleNamespace(
                stdout=b'{"verdicts":[]}', stderr=b""
            )
            try:
                result = pipeline.script_integrity(final_words, script, work)
            finally:
                pipeline.run = old_run
                pipeline.CUT_BOUNDARIES = old_boundaries
        self.assertFalse(result["ok"])
        self.assertEqual(result["judge"], "mechanical")
        self.assertEqual(len(result["damaged"]), 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg and ffprobe are required")
    def test_integer_cut_graph_keeps_stream_durations_aligned(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "input.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-f", "lavfi", "-i",
                "anoisesrc=color=white:sample_rate=48000:duration=3:seed=7",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", str(src),
            ], check=True)
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = []
            try:
                out = pipeline.apply_cuts(
                    src,
                    [{"s": 0.067, "e": 0.133},
                     {"s": 0.267, "e": 0.333}],
                    work,
                )
            finally:
                pipeline.CUT_BOUNDARIES = old_boundaries
            probe = subprocess.run([
                pipeline.FFPROBE, "-v", "error",
                "-show_entries", "stream=codec_type,duration",
                "-of", "json", str(out),
            ], check=True, capture_output=True, text=True)
            streams = json.loads(probe.stdout)["streams"]
            video = next(float(s["duration"]) for s in streams
                         if s["codec_type"] == "video")
            audio = next(float(s["duration"]) for s in streams
                         if s["codec_type"] == "audio")
            self.assertLessEqual(abs(video - audio), 0.002)


if __name__ == "__main__":
    unittest.main()
