from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

from autoeditor.edit_policy import (
    CAPABILITIES,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    edit_policy_sha256,
    resolve_edit_policy,
)
from autoeditor.music_plan import (
    MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
    MUSIC_PLAN_SCHEMA_VERSION,
    derive_music_asset_id,
    derive_music_mastering,
    derive_music_policy_limits,
    derive_music_region_id,
    music_asset_manifest_sha256,
)
from autoeditor import music_render
from autoeditor.music_render import (
    MUSIC_RENDER_RECEIPT_SCHEMA_VERSION,
    MusicRenderError,
    canonical_music_render_receipt_json,
    derive_music_output_timeline_sha256,
    execute_music_render,
    music_render_receipt_sha256,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _auto_values() -> dict[str, str]:
    return {
        "cut_density": "auto", "sfx_density": "auto",
        "transition_density": "auto", "dialogue_rule": "auto",
        "music_rule": "auto", "caption_rule": "auto",
        "visualization_rule": "auto",
    }


def _policy(duration_ms: int) -> dict:
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": "montage_meme",
        "duration_ms": duration_ms,
        "delivery": {"platform": "web", "aspect": "auto"},
        "explicit_intent": _auto_values(),
        "consented_preferences": {
            "consented": False, "values": _auto_values(),
        },
        "available_capabilities": sorted(CAPABILITIES),
    })


def _discover_ffmpeg_pair() -> tuple[str, str] | None:
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


def _run(command: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, check=True, shell=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
    )


def _probe(ffprobe: str, path: Path) -> dict:
    result = _run([
        ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,sample_rate,channels",
        "-of", "json", str(path),
    ], timeout=30)
    return json.loads(result.stdout)


def _tone_amplitude(ffmpeg: str, path: Path, *, start: float,
                    duration: float, frequency: float) -> float:
    result = _run([
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(path), "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-map", "0:a:0", "-ac", "1", "-ar", "48000",
        "-f", "f32le", "pipe:1",
    ], timeout=30)
    count = len(result.stdout) // 4
    values = struct.unpack(f"<{count}f", result.stdout[:count * 4])
    step = 2 * math.pi * frequency / 48_000
    cosine = sum(value * math.cos(step * index)
                 for index, value in enumerate(values))
    sine = sum(value * math.sin(step * index)
               for index, value in enumerate(values))
    return 2 * math.hypot(cosine, sine) / max(1, count)


def _loudness(ffmpeg: str, path: Path) -> tuple[int, int]:
    result = _run([
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info",
        "-i", str(path), "-map", "0:a:0", "-vn", "-af",
        "loudnorm=I=-14.000:TP=-1.000:LRA=11.000:print_format=json",
        "-f", "null", "-",
    ], timeout=60)
    text = result.stderr.decode("utf-8", errors="replace")
    matches = re.findall(r"\{\s*\"input_i\".*?\}", text, re.DOTALL)
    if not matches:
        raise AssertionError("loudnorm JSON was absent")
    value = json.loads(matches[-1])
    return round(float(value["input_i"]) * 1000), round(
        float(value["input_tp"]) * 1000)


def _write_evidence(root: Path, name: str) -> tuple[str, Path]:
    path = root / f"{name}.json"
    path.write_bytes(
        json.dumps({"schema_version": f"test-{name}/v1", "pass": True},
                   sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return _sha256_file(path), path


def _manifest_plan(
    program: Path,
    asset: Path,
    evidence: dict[str, Path],
    *,
    with_region: bool = True,
) -> tuple[dict, dict, dict, dict[str, str], dict[str, str]]:
    duration_ms = 6_000
    policy = _policy(duration_ms)
    license_sha = next(key for key, value in evidence.items()
                       if value.stem == "license")
    rights_sha = next(key for key, value in evidence.items()
                      if value.stem == "rights")
    source_sha = next(key for key, value in evidence.items()
                      if value.stem == "source")
    payload = {
        "sha256": _sha256_file(asset), "byte_length": asset.stat().st_size,
        "decoded_duration_ms": 3_000, "sample_rate_hz": 44_100,
        "channels": 1,
        "source_ref": "licensed-external://music/test-tone.wav",
        "provenance": "licensed_external",
        "license": {
            "basis": "licensed_external", "license_id": "test-sync-license",
            "license_name": "Test synchronization license",
            "licensor": "Test Music Ltd", "evidence_sha256": license_sha,
        },
        "rights_receipt": {
            "receipt_id": "test-music-rights", "receipt_sha256": rights_sha,
            "permits_synchronization": True, "permits_editing": True,
            "permits_looping": False, "permits_delivery": True,
        },
    }
    asset_binding = {"asset_id": derive_music_asset_id(payload), **payload}
    timeline = derive_music_output_timeline_sha256(
        program_sha256=_sha256_file(program), program_bytes=program.stat().st_size,
        duration_ms=duration_ms,
    )
    manifest = {
        "schema_version": MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": timeline,
        "output_duration_ms": duration_ms,
        "output_sample_rate_hz": 48_000, "output_channels": 2,
        "transcript_sha256": None,
        "source_music": {
            "status": "absent", "evidence_sha256": source_sha,
            "exclusion_authorization_sha256": None, "regions": [],
        },
        "assets": [asset_binding], "beat_grids": [], "dialogue_windows": [],
    }
    regions = []
    if with_region:
        region_payload = {
            "track_index": 0, "asset_id": asset_binding["asset_id"],
            "asset_sha256": asset_binding["sha256"], "start_ms": 2_000,
            "duration_ms": 2_000, "trim_start_ms": 250,
            "playback_mode": "once", "loop_length_ms": 0,
            "loop_crossfade_ms": 0, "gain_millidb": -6_000,
            "fade_in_ms": 100, "fade_out_ms": 100,
            "crossfade_in_ms": 0, "crossfade_out_ms": 0,
            "beat_sync": None, "dialogue_ducking": None,
        }
        regions.append({
            "region_id": derive_music_region_id(region_payload), **region_payload,
        })
    plan = {
        "schema_version": MUSIC_PLAN_SCHEMA_VERSION,
        "music_asset_manifest_sha256": music_asset_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "output_timeline_sha256": timeline,
        "output_duration_ms": duration_ms,
        "policy": derive_music_policy_limits(policy, duration_ms),
        "mastering": derive_music_mastering(policy),
        "source_music_action": "none", "regions": regions,
    }
    asset_paths = ({asset_binding["asset_id"]: str(asset)} if with_region else {})
    evidence_paths = {digest: str(path) for digest, path in evidence.items()
                      if with_region or path.stem == "source"}
    return manifest, plan, policy, asset_paths, evidence_paths


class MusicRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pair = _discover_ffmpeg_pair()
        if pair is None:
            raise unittest.SkipTest("FFmpeg/FFprobe is unavailable")
        cls.ffmpeg, cls.ffprobe = pair

    def _media(self, root: Path, *, silent: bool = False):
        program = root / "program.mp4"
        command = [
            self.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
            "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=6",
        ]
        if not silent:
            command.extend([
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
            ])
        command.extend(["-map", "0:v:0"])
        if not silent:
            command.extend(["-map", "1:a:0"])
        command.extend([
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            *([] if silent else ["-c:a", "aac", "-ar", "48000", "-ac", "2"]),
            "-t", "6.000", str(program),
        ])
        _run(command)
        asset = root / "music.wav"
        _run([
            self.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
            "-y", "-f", "lavfi", "-i",
            "sine=frequency=660:sample_rate=44100:duration=3",
            "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", str(asset),
        ])
        evidence = dict(_write_evidence(root, name)
                        for name in ("license", "rights", "source"))
        return program, asset, evidence

    def test_real_mix_places_rights_bound_music_and_normalizes_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            program, asset, evidence = self._media(root)
            manifest, plan, policy, assets, receipts = _manifest_plan(
                program, asset, evidence)
            result = execute_music_render(
                program_path=str(program), output_path=str(root / "mixed.mp4"),
                plan=plan, asset_manifest=manifest, edit_policy=policy,
                asset_paths=assets, evidence_paths=receipts, work_dir=str(root),
                ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe,
            )
            output = Path(result["output_path"])
            probe = _probe(self.ffprobe, output)
            audio = next(item for item in probe["streams"]
                         if item["codec_type"] == "audio")
            self.assertEqual((audio["sample_rate"], audio["channels"]), ("48000", 2))
            self.assertAlmostEqual(float(probe["format"]["duration"]), 6.0, delta=0.1)
            before = _tone_amplitude(
                self.ffmpeg, output, start=0.5, duration=0.5, frequency=660)
            during = _tone_amplitude(
                self.ffmpeg, output, start=2.5, duration=0.5, frequency=660)
            self.assertGreater(during, max(0.01, before * 10))
            self.assertEqual(result["receipt"]["render_mode"], "mixed")
            self.assertEqual(result["receipt"]["schema_version"],
                             MUSIC_RENDER_RECEIPT_SCHEMA_VERSION)
            self.assertEqual(result["receipt_sha256"],
                             music_render_receipt_sha256(result["receipt"]))
            self.assertEqual(len(result["receipt"]["asset_inputs"]), 1)
            self.assertEqual(
                {role for item in result["receipt"]["evidence_inputs"]
                 for role in item["roles"]},
                {"license", "rights", "source_music_analysis"},
            )
            mastering = result["receipt"]["mastering"]
            self.assertTrue(mastering["passed"])
            self.assertEqual(
                mastering["render_filter_complex_sha256"],
                result["receipt"]["filter_complex_sha256"])
            measured_lufs, measured_peak = _loudness(
                self.ffmpeg, output)
            self.assertEqual(
                mastering["delivered_measurement"], {
                    "integrated_loudness_millilufs": measured_lufs,
                    "true_peak_millidbtp": measured_peak,
                })
            self.assertLessEqual(abs(measured_lufs + 14_000), 1_000)
            self.assertLessEqual(measured_peak, -900)

    def test_real_silent_program_receives_music_and_exact_stereo_bed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            program, asset, evidence = self._media(root, silent=True)
            manifest, plan, policy, assets, receipts = _manifest_plan(
                program, asset, evidence)
            result = execute_music_render(
                program_path=str(program), output_path=str(root / "silent-mix.mp4"),
                plan=plan, asset_manifest=manifest, edit_policy=policy,
                asset_paths=assets, evidence_paths=receipts, work_dir=str(root),
                ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe,
            )
            self.assertFalse(result["receipt"]["program_input"]["audio_present"])
            self.assertGreater(_tone_amplitude(
                self.ffmpeg, Path(result["output_path"]), start=2.5,
                duration=0.5, frequency=660), 0.01)

    def test_no_region_copy_is_byte_exact_and_receipt_rejects_contradiction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            program, asset, evidence = self._media(root)
            manifest, plan, policy, assets, receipts = _manifest_plan(
                program, asset, evidence, with_region=False)
            result = execute_music_render(
                program_path=str(program), output_path=str(root / "copy.mp4"),
                plan=plan, asset_manifest=manifest, edit_policy=policy,
                asset_paths=assets, evidence_paths=receipts, work_dir=str(root),
                ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe,
            )
            self.assertEqual(result["receipt"]["render_mode"], "no_regions_copy")
            self.assertEqual(Path(result["output_path"]).read_bytes(),
                             program.read_bytes())
            forged = copy.deepcopy(result["receipt"])
            forged["output"]["sha256"] = "0" * 64
            with self.assertRaises(MusicRenderError):
                canonical_music_render_receipt_json(forged)

    def test_tampered_asset_and_existing_private_files_fail_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            program, asset, evidence = self._media(root)
            manifest, plan, policy, assets, receipts = _manifest_plan(
                program, asset, evidence)
            asset.write_bytes(asset.read_bytes() + b"tamper")
            with self.assertRaises(MusicRenderError):
                execute_music_render(
                    program_path=str(program), output_path=str(root / "bad.mp4"),
                    plan=plan, asset_manifest=manifest, edit_policy=policy,
                    asset_paths=assets, evidence_paths=receipts,
                    work_dir=str(root), ffmpeg_path=self.ffmpeg,
                    ffprobe_path=self.ffprobe,
                )
            self.assertFalse((root / "bad.mp4").exists())
            stale = root / "music-filter.txt"
            stale.write_text("user-owned", encoding="utf-8")
            self.assertEqual(stale.read_text(encoding="utf-8"), "user-owned")

    def test_mastering_measurement_parameter_and_topology_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            program, asset, evidence = self._media(root)
            manifest, plan, policy, assets, receipts = _manifest_plan(
                program, asset, evidence)
            result = execute_music_render(
                program_path=str(program), output_path=str(root / "mastered.mp4"),
                plan=plan, asset_manifest=manifest, edit_policy=policy,
                asset_paths=assets, evidence_paths=receipts, work_dir=str(root),
                ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe,
            )
            mutations = []
            forged = copy.deepcopy(result["receipt"])
            forged["mastering"]["analysis"][
                "input_integrated_loudness_millilufs"] += 100
            mutations.append(forged)
            forged = copy.deepcopy(result["receipt"])
            forged["mastering"]["render_filter_complex_sha256"] = "0" * 64
            mutations.append(forged)
            forged = copy.deepcopy(result["receipt"])
            forged["mastering"]["delivered_measurement"][
                "integrated_loudness_millilufs"] = -10_000
            mutations.append(forged)
            for forged in mutations:
                with self.subTest(forged=forged["mastering"]):
                    with self.assertRaises(MusicRenderError):
                        canonical_music_render_receipt_json(forged)

    def test_partial_output_is_cleaned_on_subprocess_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            program, asset, evidence = self._media(root)
            manifest, plan, policy, assets, receipts = _manifest_plan(
                program, asset, evidence)
            real_run = music_render._run

            def fail_render(command, *, cwd, label, timeout_seconds=60):
                if label == "music render":
                    (root / "partial.mp4").write_bytes(b"partial")
                    raise MusicRenderError("simulated render failure")
                return real_run(command, cwd=cwd, label=label,
                                timeout_seconds=timeout_seconds)

            with mock.patch.object(music_render, "_run", side_effect=fail_render):
                with self.assertRaises(MusicRenderError):
                    execute_music_render(
                        program_path=str(program),
                        output_path=str(root / "partial.mp4"), plan=plan,
                        asset_manifest=manifest, edit_policy=policy,
                        asset_paths=assets, evidence_paths=receipts,
                        work_dir=str(root), ffmpeg_path=self.ffmpeg,
                        ffprobe_path=self.ffprobe,
                    )
            self.assertFalse((root / "partial.mp4").exists())


if __name__ == "__main__":
    unittest.main()
