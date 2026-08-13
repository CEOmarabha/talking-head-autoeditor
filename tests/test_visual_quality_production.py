from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from autoeditor import pipeline
from autoeditor.visual_quality_production import (
    PRODUCTION_VISUAL_QA_FILE,
    ProductionVisualQualityError,
    build_production_visual_intent,
    run_production_deterministic_visual_qa,
    verify_production_visual_qa_file,
)


def _tool(name: str) -> str | None:
    configured = os.environ.get(f"AUTOEDITOR_{name.upper()}")
    if configured and Path(configured).is_file():
        return configured
    return shutil.which(name)


def _run(argv: list[object]) -> subprocess.CompletedProcess:
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": False,
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run([str(item) for item in argv], **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result


class ProductionVisualQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = _tool("ffmpeg")
        cls.ffprobe = _tool("ffprobe")

    def require_tools(self):
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("real FFmpeg/FFprobe tools are unavailable")

    def render(self, root: Path, name: str, source: str) -> Path:
        self.require_tools()
        output = root / name
        _run([
            self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", source, "-t", "3", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", output,
        ])
        return output

    def test_real_cfr_decode_is_hash_bound_and_reverified_before_promotion(self):
        with tempfile.TemporaryDirectory(prefix="production-visual-qa-") as raw:
            root = Path(raw)
            artifact = self.render(
                root, "sample.UNVERIFIED.mp4",
                "testsrc2=size=320x180:rate=30",
            )
            sidecar = root / PRODUCTION_VISUAL_QA_FILE

            record = run_production_deterministic_visual_qa(
                artifact_path=artifact,
                output_path=sidecar,
                ffmpeg_path=self.ffmpeg,
                ffprobe_path=self.ffprobe,
                intent=build_production_visual_intent(),
            )
            verified = verify_production_visual_qa_file(
                sidecar, artifact, require_pass=True,
            )

            self.assertTrue(record["pass"])
            self.assertEqual(verified, record)
            self.assertEqual(record["coverage"], {
                "artifact_frame_count": 90,
                "decoded_frame_count": 24,
                "non_blank_sample_count": 12,
                "temporal_window_count": 3,
                "declared_transition_count": 0,
                "analyzed_transition_count": 0,
            })
            self.assertEqual(
                record["analysis"]["receipt"]["summary"]["check_count"], 15,
            )
            payload = sidecar.read_bytes()
            self.assertEqual(payload.count(b"\n"), 1)
            self.assertTrue(payload.endswith(b"\n"))
            self.assertNotIn(str(root).encode("utf-8"), payload)

            artifact.write_bytes(artifact.read_bytes() + b"changed")
            with self.assertRaisesRegex(
                ProductionVisualQualityError, "expected artifact",
            ):
                verify_production_visual_qa_file(
                    sidecar, artifact, require_pass=True,
                )

    def test_black_artifact_persists_failed_evidence_and_cannot_promote(self):
        with tempfile.TemporaryDirectory(prefix="production-visual-black-") as raw:
            root = Path(raw)
            artifact = self.render(
                root, "black.UNVERIFIED.mp4",
                "color=c=black:size=320x180:rate=30",
            )
            sidecar = root / PRODUCTION_VISUAL_QA_FILE

            record = run_production_deterministic_visual_qa(
                artifact_path=artifact,
                output_path=sidecar,
                ffmpeg_path=self.ffmpeg,
                ffprobe_path=self.ffprobe,
                intent=build_production_visual_intent(),
            )

            self.assertFalse(record["pass"])
            self.assertEqual(
                record["analysis"]["receipt"]["summary"]["failed_count"], 12,
            )
            verify_production_visual_qa_file(
                sidecar, artifact, require_pass=False,
            )
            with self.assertRaisesRegex(
                ProductionVisualQualityError, "visual QA failed",
            ):
                verify_production_visual_qa_file(
                    sidecar, artifact, require_pass=True,
                )

    def test_final_artifact_transition_limit_is_explicit_not_faked(self):
        with tempfile.TemporaryDirectory(prefix="production-visual-xfade-") as raw:
            root = Path(raw)
            self.require_tools()
            artifact = root / "xfade.UNVERIFIED.mp4"
            _run([
                self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=2",
                "-f", "lavfi", "-i",
                "smptebars=size=320x180:rate=30:duration=2",
                "-filter_complex",
                "[0:v][1:v]xfade=transition=fade:duration=0.5:offset=1.5,format=yuv420p[v]",
                "-map", "[v]", "-an", "-t", "3.5", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", artifact,
            ])
            intent = build_production_visual_intent(
                transitions=[{
                    "boundary_index": 0,
                    "kind": "cross_dissolve",
                    "output_start_ms": 1500,
                    "output_end_ms": 2000,
                    "overlap_ms": 500,
                }],
                transition_receipt_sha256="a" * 64,
            )

            record = run_production_deterministic_visual_qa(
                artifact_path=artifact,
                output_path=root / PRODUCTION_VISUAL_QA_FILE,
                ffmpeg_path=self.ffmpeg,
                ffprobe_path=self.ffprobe,
                intent=intent,
            )

            self.assertTrue(record["pass"])
            self.assertEqual(record["coverage"]["declared_transition_count"], 1)
            self.assertEqual(record["coverage"]["analyzed_transition_count"], 0)
            self.assertEqual(
                record["analysis"]["receipt"]["checks"]["transition"], [],
            )
            self.assertIn(
                "arbitrary-transition-quality",
                record["analysis"]["receipt"]["scope"]["unsupported"],
            )

    def test_canonical_sidecar_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="production-visual-tamper-") as raw:
            root = Path(raw)
            artifact = self.render(
                root, "sample.UNVERIFIED.mp4",
                "testsrc2=size=320x180:rate=30",
            )
            sidecar = root / PRODUCTION_VISUAL_QA_FILE
            run_production_deterministic_visual_qa(
                artifact_path=artifact,
                output_path=sidecar,
                ffmpeg_path=self.ffmpeg,
                ffprobe_path=self.ffprobe,
                intent=build_production_visual_intent(),
            )
            value = json.loads(sidecar.read_text(encoding="ascii"))
            changed = copy.deepcopy(value)
            changed["coverage"]["decoded_frame_count"] -= 1
            sidecar.write_bytes((
                json.dumps(
                    changed, ensure_ascii=True, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ) + "\n"
            ).encode("ascii"))

            with self.assertRaisesRegex(
                ProductionVisualQualityError, "coverage",
            ):
                verify_production_visual_qa_file(
                    sidecar, artifact, require_pass=False,
                )

    def test_timeline_intent_and_artifact_contract_are_closed_and_compatible(self):
        receipt_sha256 = "b" * 64
        handoff = {
            "boundaries": [{
                "boundary_index": 0,
                "kind": "cross_dissolve",
                "output_start_ms": 900,
                "output_end_ms": 1100,
                "overlap_ms": 200,
            }],
            "transition_artifact_receipt_sha256": receipt_sha256,
        }
        intent = pipeline.build_production_visual_timeline_intent(
            {"graphics": [{"s": 0.2, "e": 0.6}], "broll": []}, handoff,
        )
        self.assertEqual(intent, {
            "schema_version": "autoeditor-production-visual-timeline-intent/v1",
            "intentional_dark_intervals_ms": [{"start_ms": 200, "end_ms": 600}],
            "transitions": handoff["boundaries"],
            "transition_receipt_sha256": receipt_sha256,
        })

        with tempfile.TemporaryDirectory(prefix="visual-artifact-contract-") as raw:
            root = Path(raw)
            names = {
                "delivery": "pending.UNVERIFIED.mp4",
                "final": "final.mp4",
                "boundaries": "EDIT_BOUNDARIES.json",
                "mix": "AUDIO_MIX_RECEIPT.json",
                "visual": PRODUCTION_VISUAL_QA_FILE,
                "intent": "PROJECT_INTENT_RENDER_RECEIPT.json",
                "music": "MUSIC_PRODUCTION_RECEIPT.json",
                "sfx": "SFX_PRODUCTION_RECEIPT.json",
            }
            paths = {key: root / name for key, name in names.items()}
            for key, path in paths.items():
                if key != "final":
                    path.write_bytes(key.encode("ascii"))
            legacy = pipeline.build_engine_artifact_contract(
                mode="generic-baseline", delivery=paths["delivery"],
                final_file=paths["final"], edl=None, captions=None,
                caption_render=None, edit_boundaries=paths["boundaries"],
                audio_mix=paths["mix"], sequence=None,
                deterministic_visual_qa=paths["visual"],
            )
            governed = pipeline.build_engine_artifact_contract(
                mode="generic-baseline", delivery=paths["delivery"],
                final_file=paths["final"], edl=None, captions=None,
                caption_render=None, edit_boundaries=paths["boundaries"],
                audio_mix=paths["mix"], sequence=None,
                project_intent=paths["intent"],
                music_production=paths["music"],
                sfx_production=paths["sfx"],
                deterministic_visual_qa=paths["visual"],
            )

        self.assertEqual(legacy["schema"], "autoeditor-engine-artifact-contract/v3")
        self.assertEqual(governed["schema"], "autoeditor-engine-artifact-contract/v5")
        self.assertEqual(
            legacy["deterministic_visual_qa"], {
                "file": PRODUCTION_VISUAL_QA_FILE,
                "bytes": len(b"visual"),
                "sha256": hashlib.sha256(b"visual").hexdigest(),
            },
        )
        self.assertEqual(
            governed["deterministic_visual_qa"],
            legacy["deterministic_visual_qa"],
        )


if __name__ == "__main__":
    unittest.main()
