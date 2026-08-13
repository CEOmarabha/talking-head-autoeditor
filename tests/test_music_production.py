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
from unittest import mock

from autoeditor import music_production
from autoeditor.edit_policy import CAPABILITIES, edit_policy_sha256
from autoeditor.project_intent_authority import (
    build_project_intent_engine_envelope,
    project_intent_engine_envelope_sha256,
)
from autoeditor.project_intent_policy_bridge import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_MANIFEST_SOURCE,
    PROJECT_INTENT_SCHEMA_VERSION,
    ProjectIntentPolicyBridgeError,
    resolve_project_intent_policy,
)
from autoeditor.music_production import (
    MusicProductionError,
    execute_project_intent_music,
    specialize_music_edit_policy_for_program,
    verify_music_production_evidence,
    write_music_production_probe,
)


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _tool_pair() -> tuple[str, str] | None:
    ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "").strip()
    ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "").strip()
    ffmpeg = ffmpeg if ffmpeg and Path(ffmpeg).is_file() else (
        shutil.which("ffmpeg") or "")
    ffprobe = ffprobe if ffprobe and Path(ffprobe).is_file() else (
        shutil.which("ffprobe") or "")
    if not ffmpeg:
        candidates = sorted(
            Path("C:/Users/MyEye/Documents/Codex/2026-08-11").glob(
                "*/outputs/AutoEditor-*-Private-Beta/"
                "AutoEditor-Helper-*-windows-x64-portable/"
                "resources/bin/ffmpeg.exe"
            ), reverse=True,
        )
        if candidates:
            ffmpeg = str(candidates[0])
    if ffmpeg and not ffprobe:
        suffix = ".exe" if Path(ffmpeg).suffix.lower() == ".exe" else ""
        adjacent = Path(ffmpeg).with_name(f"ffprobe{suffix}")
        if adjacent.is_file():
            ffprobe = str(adjacent)
    if not ffmpeg or not ffprobe:
        return None
    return str(Path(ffmpeg).resolve()), str(Path(ffprobe).resolve())


def _run(command: list[str], timeout: int = 120) -> None:
    subprocess.run(
        command, shell=False, check=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
    )


def _project_intent(preference: str, *, profile: str = "dialogue_talking_head") -> dict:
    preferences = {
        "captions": "none", "graphics": "none", "music": preference,
        "sfx": "none", "transitions": "none",
    }
    return {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": profile,
        "delivery": {"platform": "youtube", "aspect": "16:9"},
        "target_duration": {"min_ms": 3_800, "max_ms": 4_200},
        "preferences": {
            name: {"enabled": value != "none", "preference": value}
            for name, value in preferences.items()
        },
    }


def _envelope(
    preference: str,
    *,
    profile: str = "dialogue_talking_head",
    capabilities: set[str] | None = None,
) -> dict:
    project = _project_intent(preference, profile=profile)
    available = set(CAPABILITIES) if capabilities is None else capabilities
    manifest = {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": "a" * 64,
        "available_capabilities": sorted(available),
    }
    policy = resolve_project_intent_policy(project, manifest)
    proposal = {
        "schema_version": "autoeditor-fixed-music-test-proposal/v1",
        "project_intent_sha256": _digest(project),
    }
    authority = {
        "schema_version": "autoeditor-project-intent-authority/v2",
        "authorization_id": "2" * 32,
        "approved_proposal_sha256": _digest(proposal),
        "project_intent": project,
        "project_intent_sha256": _digest(project),
        "edit_policy": policy,
        "edit_policy_sha256": edit_policy_sha256(policy),
        "capability_manifest": manifest,
        "capability_manifest_sha256": _digest(manifest),
        "authorization_hmac_sha256": "f" * 64,
    }
    return build_project_intent_engine_envelope(authority)


def _words() -> list[dict]:
    return [
        {"w": "fixed", "s": 1.45, "e": 1.85},
        {"w": "dialogue", "s": 1.90, "e": 2.30},
        {"w": "window", "s": 2.35, "e": 2.55},
    ]


class MusicProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = _tool_pair()
        cls.fixture = tempfile.TemporaryDirectory(prefix="music-production-media-")
        cls.program = Path(cls.fixture.name) / "program.mp4"
        cls.continuous = Path(cls.fixture.name) / "continuous.mp4"
        if cls.tools is not None:
            ffmpeg, _ = cls.tools
            _run([
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=0x203050:s=160x90:r=30:d=4",
                "-f", "lavfi", "-i",
                "sine=frequency=880:sample_rate=48000:duration=1.1",
                "-filter_complex",
                "[1:a]adelay=1450:all=1,apad=whole_dur=4,atrim=duration=4[a]",
                "-map", "0:v:0", "-map", "[a]", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-t", "4", str(cls.program),
            ])
            _run([
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=0x203050:s=160x90:r=30:d=4",
                "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=4",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-t", "4", str(cls.continuous),
            ])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def _request(
        self,
        root: Path,
        *,
        preference: str = "supporting",
        profile: str = "dialogue_talking_head",
        program: Path | None = None,
        capabilities: set[str] | None = None,
    ) -> dict:
        work = root / "work"
        evidence = root / "evidence"
        work.mkdir()
        evidence.mkdir()
        envelope = _envelope(
            preference, profile=profile, capabilities=capabilities)
        assert self.tools is not None
        ffmpeg, ffprobe = self.tools
        return {
            "program_path": str((program or self.program).resolve()),
            "project_intent_envelope": envelope,
            "project_intent_envelope_sha256": (
                project_intent_engine_envelope_sha256(envelope)),
            "speech_words": _words(), "work_dir": str(work.resolve()),
            "evidence_dir": str(evidence.resolve()),
            "ffmpeg_path": ffmpeg, "ffprobe_path": ffprobe,
        }

    def _verify(self, request: dict, result: dict) -> dict:
        envelope = request["project_intent_envelope"]
        return verify_music_production_evidence(
            result["receipt"], program_input_path=request["program_path"],
            output_path=result["output_path"],
            evidence_dir=request["evidence_dir"],
            expected_engine_envelope_sha256=(
                request["project_intent_envelope_sha256"]),
            expected_project_intent_sha256=envelope["project_intent_sha256"],
            expected_parent_edit_policy_sha256=envelope["edit_policy_sha256"],
            ffmpeg_path=request["ffmpeg_path"],
            ffprobe_path=request["ffprobe_path"],
        )

    def test_actual_duration_specialization_preserves_range_authority(self):
        parent = _envelope("supporting")["edit_policy"]
        child = specialize_music_edit_policy_for_program(
            parent, target_duration={"min_ms": 3_800, "max_ms": 4_200},
            actual_duration_ms=4_000)
        self.assertEqual(child["duration"], {
            "duration_ms": 4_000, "band": "micro"})
        parent_copy = copy.deepcopy(parent)
        child_copy = copy.deepcopy(child)
        parent_copy.pop("duration")
        child_copy.pop("duration")
        self.assertEqual(parent_copy, child_copy)
        self.assertNotEqual(edit_policy_sha256(parent), edit_policy_sha256(child))
        for target, actual in (
            ({"min_ms": 3_800, "max_ms": 4_200}, 3_799),
            ({"min_ms": 3_800, "max_ms": 61_000}, 4_000),
        ):
            with self.subTest(target=target, actual=actual):
                with self.assertRaises(MusicProductionError):
                    specialize_music_edit_policy_for_program(
                        parent, target_duration=target,
                        actual_duration_ms=actual)

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_none_is_byte_exact_and_never_invokes_renderer(self):
        with tempfile.TemporaryDirectory(prefix="music-production-none-") as raw:
            request = self._request(Path(raw), preference="none")
            with mock.patch.object(
                    music_production, "execute_music_render") as executor:
                result = execute_project_intent_music(**request)
            self.assertFalse(result["executed"])
            self.assertEqual(result["receipt"]["mode"], "no_music_requested")
            self.assertEqual(result["receipt"]["program_input"],
                             result["receipt"]["output"])
            self.assertIsNone(result["receipt"]["capability_used"])
            executor.assert_not_called()
            self.assertTrue(self._verify(request, result)["ok"])

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_real_supporting_render_reopens_rights_plan_masking_and_measured_qa(self):
        with tempfile.TemporaryDirectory(prefix="music-production-real-") as raw:
            request = self._request(Path(raw))
            result = execute_project_intent_music(**request)
            check = self._verify(request, result)
            receipt = result["receipt"]
            self.assertTrue(result["executed"])
            self.assertTrue(check["ok"], check["note"])
            self.assertTrue(check["rights_verified"])
            self.assertTrue(check["dialogue_masking_verified"])
            self.assertTrue(check["loudness_verified"])
            self.assertEqual(receipt["capability_used"], "project_generated_music")
            self.assertEqual(receipt["rights"], {
                "basis": "project_owned",
                "generator": "autoeditor-deterministic-musical-pcm/v1",
                "external_service_used": False,
            })
            self.assertTrue(receipt["audio_qa"]["passed"])
            self.assertLessEqual(
                abs(receipt["audio_qa"]["integrated_loudness_millilufs"]
                    - receipt["audio_qa"]["target_loudness_millilufs"]),
                1_000)
            region = result["plan"]["regions"][0]
            for window in result["manifest"]["dialogue_windows"]:
                self.assertTrue(
                    region["start_ms"] + region["duration_ms"]
                    <= window["start_ms"]
                    or region["start_ms"] >= window["end_ms"])
            sidecars = {item["file"] for item in receipt["sidecars"]}
            self.assertEqual(sidecars, {
                "MUSIC_ASSET_MANIFEST.json", "MUSIC_AUDIO_QA.json",
                "MUSIC_COMPILE_RECEIPT.json", "MUSIC_EXECUTION_EDIT_POLICY.json",
                "MUSIC_GENERATION_EVIDENCE.json", "MUSIC_PLAN.json",
                "MUSIC_PROJECT_BED.wav", "MUSIC_RENDER_RECEIPT.json",
                "MUSIC_SOURCE_ANALYSIS.json", "MUSIC_SPEECH_EVIDENCE.json",
            })

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_auto_with_no_decoded_safe_gap_is_noop(self):
        with tempfile.TemporaryDirectory(prefix="music-production-gap-") as raw:
            request = self._request(
                Path(raw), preference="auto", program=self.continuous)
            with mock.patch.object(
                    music_production, "execute_music_render") as executor:
                result = execute_project_intent_music(**request)
            self.assertFalse(result["executed"])
            self.assertEqual(result["receipt"]["mode"], "no_safe_gap")
            executor.assert_not_called()
            self.assertTrue(self._verify(request, result)["ok"])

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_primary_and_missing_project_generated_capability_fail_closed(self):
        with tempfile.TemporaryDirectory(
                prefix="music-production-primary-") as raw:
            request = self._request(Path(raw), preference="primary")
            with self.assertRaises(MusicProductionError):
                execute_project_intent_music(**request)
        with self.assertRaises(ProjectIntentPolicyBridgeError):
            _envelope(
                "supporting",
                capabilities=set(CAPABILITIES) - {"project_generated_music"})

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_output_missing_sidecar_rights_source_speech_and_qa_tamper_fail(self):
        mutations = ("output", "missing", "rights", "source", "speech", "qa")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                    prefix=f"music-production-tamper-{mutation}-") as raw:
                request = self._request(Path(raw))
                result = execute_project_intent_music(**request)
                receipt = copy.deepcopy(result["receipt"])
                evidence = Path(request["evidence_dir"])
                if mutation == "output":
                    Path(result["output_path"]).write_bytes(
                        Path(result["output_path"]).read_bytes() + b"tamper")
                elif mutation == "missing":
                    (evidence / "MUSIC_PLAN.json").unlink()
                else:
                    names = {
                        "rights": "MUSIC_GENERATION_EVIDENCE.json",
                        "source": "MUSIC_SOURCE_ANALYSIS.json",
                        "speech": "MUSIC_SPEECH_EVIDENCE.json",
                        "qa": "MUSIC_AUDIO_QA.json",
                    }
                    path = evidence / names[mutation]
                    value = json.loads(path.read_text(encoding="ascii"))
                    if mutation == "rights":
                        value["rights"]["external_service_used"] = True
                    elif mutation == "source":
                        value["analysis"]["active_frame_count"] += 1
                    elif mutation == "speech":
                        value["words"][0]["start_ms"] += 10
                    else:
                        value["measurement"][
                            "integrated_loudness_millilufs"] += 100
                    path.write_text(_canonical(value) + "\n", encoding="ascii")
                    binding = next(
                        item for item in receipt["sidecars"]
                        if item["file"] == path.name)
                    binding["bytes"] = path.stat().st_size
                    binding["sha256"] = hashlib.sha256(
                        path.read_bytes()).hexdigest()
                check = self._verify(request, {**result, "receipt": receipt})
                self.assertFalse(check["ok"])

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_fixed_probe_decodes_placement_and_rejects_tamper_and_omission(self):
        assert self.tools is not None
        ffmpeg, ffprobe = self.tools
        with tempfile.TemporaryDirectory(prefix="music-production-probe-") as raw:
            root = Path(raw)
            output = root / "probe-output.mp4"
            result = write_music_production_probe(
                str(self.program), str(output), str(root), ffmpeg, ffprobe)
            self.assertEqual(
                result["schema_version"],
                "autoeditor-music-production-self-test/v1")
            self.assertTrue(all(result["checks"].values()))
            self.assertEqual(
                result["artifact"]["sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(result["artifact"]["duration_ms"], 4_000)
            self.assertGreater(
                result["decoded_placement"]["bed_music_tone_millionths"],
                result["decoded_placement"][
                    "dialogue_music_tone_millionths"] * 8)
            self.assertTrue(result["measured_audio"]["passed"])
            self.assertEqual(result["evidence"]["rights_basis"], "project_owned")
            self.assertIs(result["evidence"]["external_service_used"], False)
            self.assertEqual(result["evidence"]["sidecar_count"], 10)


if __name__ == "__main__":
    unittest.main()
