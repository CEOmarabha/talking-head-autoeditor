from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
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
from autoeditor.sfx_plan import (
    SFX_CUE_MANIFEST_SCHEMA_VERSION,
    SFX_PLAN_SCHEMA_VERSION,
    compile_sfx_plan,
    derive_sfx_anchor_id,
    derive_sfx_asset_id,
    derive_sfx_cue_id,
    derive_sfx_policy_limits,
    derive_speech_window_id,
    sfx_cue_manifest_sha256,
)
from autoeditor import sfx_render
from autoeditor.sfx_render import (
    SFX_RENDER_RECEIPT_SCHEMA_VERSION,
    SfxRenderError,
    canonical_sfx_render_receipt_json,
    derive_sfx_output_timeline_sha256,
    execute_sfx_render,
    sfx_render_receipt_sha256,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


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


def _policy(
    duration_ms: int,
    *,
    profile: str = "dialogue_talking_head",
    sfx_density: str = "auto",
) -> dict:
    explicit = _auto_values()
    explicit["sfx_density"] = sfx_density
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": profile,
        "duration_ms": duration_ms,
        "delivery": {"platform": "web", "aspect": "auto"},
        "explicit_intent": explicit,
        "consented_preferences": {
            "consented": False,
            "values": _auto_values(),
        },
        "available_capabilities": sorted(CAPABILITIES),
    })


def _discover_ffmpeg_pair() -> tuple[str, str] | None:
    ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "").strip()
    ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "").strip()
    ffmpeg = ffmpeg if ffmpeg and Path(ffmpeg).is_file() else (
        shutil.which("ffmpeg") or ""
    )
    ffprobe = ffprobe if ffprobe and Path(ffprobe).is_file() else (
        shutil.which("ffprobe") or ""
    )
    if not ffmpeg:
        # The repository's release-contract tests build and verify a pinned
        # portable helper.  Prefer that exact binary when the environment did
        # not explicitly choose a toolchain.
        candidates = sorted(
            Path("C:/Users/MyEye/Documents/Codex/2026-08-11").glob(
                "*/outputs/AutoEditor-*-Private-Beta/"
                "AutoEditor-Helper-*-windows-x64-portable/"
                "resources/bin/ffmpeg.exe"
            ),
            reverse=True,
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
    if not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
        return None
    return str(Path(ffmpeg).resolve()), str(Path(ffprobe).resolve())


def _run(command: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _probe(ffprobe: str, path: Path) -> dict:
    result = _run([
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,sample_rate,channels",
        "-of", "json",
        str(path),
    ], timeout=30)
    return json.loads(result.stdout)


def _tone_amplitude(
    ffmpeg: str,
    path: Path,
    *,
    start_seconds: float,
    duration_seconds: float,
    frequency_hz: float,
) -> float:
    result = _run([
        ffmpeg,
        "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", f"{start_seconds:.3f}",
        "-t", f"{duration_seconds:.3f}",
        "-i", str(path),
        "-map", "0:a:0", "-ac", "1", "-ar", "48000",
        "-f", "f32le", "pipe:1",
    ], timeout=30)
    count = len(result.stdout) // 4
    values = struct.unpack(f"<{count}f", result.stdout[:count * 4])
    angular_step = 2.0 * math.pi * frequency_hz / 48_000.0
    cosine = sum(
        value * math.cos(angular_step * index)
        for index, value in enumerate(values)
    )
    sine = sum(
        value * math.sin(angular_step * index)
        for index, value in enumerate(values)
    )
    return 2.0 * math.hypot(cosine, sine) / max(1, count)


def _asset_binding(path: Path, *, evidence_sha256: str) -> dict:
    payload = {
        "sha256": _sha256_file(path),
        "byte_length": path.stat().st_size,
        "duration_ms": 1_500,
        "sample_rate_hz": 48_000,
        "channels": 2,
        "source_ref": "project-generated://cues/placement-tone.wav",
        "provenance": "project_generated",
        "license": {
            "basis": "project_owned",
            "license_id": "project-generated",
            "licensor": "project",
            "evidence_sha256": evidence_sha256,
        },
    }
    return {"asset_id": derive_sfx_asset_id(payload), **payload}


def _event_anchor(*, evidence_sha256: str, duration_ms: int = 6_000) -> dict:
    payload = {
        "category": "event",
        "reference_id": "event-tone-placement",
        "time_ms": 2_000,
        "evidence_start_ms": 1_900,
        "evidence_end_ms": 2_100,
        "evidence_sha256": evidence_sha256,
    }
    return {
        "anchor_id": derive_sfx_anchor_id(payload, duration_ms),
        **payload,
    }


def _speech(*, evidence_sha256: str, duration_ms: int = 6_000) -> dict:
    payload = {
        "start_ms": 2_000,
        "end_ms": 2_500,
        "evidence_sha256": evidence_sha256,
    }
    return {
        "speech_id": derive_speech_window_id(payload, duration_ms),
        **payload,
    }


def _cue(asset: dict, anchor: dict) -> dict:
    payload = {
        "asset_id": asset["asset_id"],
        "asset_sha256": asset["sha256"],
        "kind": "impact",
        "motivation": {
            "category": anchor["category"],
            "anchor_id": anchor["anchor_id"],
            "reference_id": anchor["reference_id"],
            "anchor_ms": anchor["time_ms"],
            "evidence_start_ms": anchor["evidence_start_ms"],
            "evidence_end_ms": anchor["evidence_end_ms"],
            "evidence_sha256": anchor["evidence_sha256"],
        },
        "placement": {
            "start_ms": 2_000,
            "trim_start_ms": 0,
            "trim_duration_ms": 1_500,
            "gain_millidb": -3_000,
            "attack_fade_ms": 50,
            "release_fade_ms": 100,
        },
        "ducking": {
            "start_ms": 2_000,
            "end_ms": 2_500,
            "attenuation_millidb": 12_000,
            "attack_ms": 20,
            "release_ms": 200,
        },
    }
    return {"cue_id": derive_sfx_cue_id(payload), **payload}


def _manifest_and_plan(
    program: Path,
    asset_path: Path,
    evidence: dict[str, Path],
    *,
    with_cue: bool,
) -> tuple[dict, dict, dict, dict[str, str], dict[str, str]]:
    duration_ms = 6_000
    policy = _policy(
        duration_ms,
        profile="dialogue_talking_head" if with_cue else "podcast_interview",
    )
    license_digest = _sha256_file(evidence["license"])
    event_digest = _sha256_file(evidence["event"])
    speech_digest = _sha256_file(evidence["speech"])
    program_hash = _sha256_file(program)
    asset = _asset_binding(asset_path, evidence_sha256=license_digest)
    anchor = _event_anchor(evidence_sha256=event_digest)
    speech = _speech(evidence_sha256=speech_digest)
    manifest = {
        "schema_version": SFX_CUE_MANIFEST_SCHEMA_VERSION,
        "output_timeline_sha256": derive_sfx_output_timeline_sha256(
            program_sha256=program_hash,
            program_bytes=program.stat().st_size,
            duration_ms=duration_ms,
        ),
        "output_duration_ms": duration_ms,
        "output_sample_rate_hz": 48_000,
        "output_channels": 2,
        "assets": [asset],
        "anchors": [anchor],
        "speech_windows": [speech],
    }
    cues = [_cue(asset, anchor)] if with_cue else []
    plan = {
        "schema_version": SFX_PLAN_SCHEMA_VERSION,
        "cue_manifest_sha256": sfx_cue_manifest_sha256(manifest),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "output_timeline_sha256": manifest["output_timeline_sha256"],
        "output_duration_ms": duration_ms,
        "policy": derive_sfx_policy_limits(policy, duration_ms),
        "cues": cues,
    }
    asset_paths = {asset["asset_id"]: str(asset_path.resolve())} if with_cue else {}
    evidence_paths = ({
        license_digest: str(evidence["license"].resolve()),
        event_digest: str(evidence["event"].resolve()),
        speech_digest: str(evidence["speech"].resolve()),
    } if with_cue else {})
    return manifest, plan, policy, asset_paths, evidence_paths


def _valid_render_receipt(*, mixed: bool = True) -> dict:
    program_digest = _sha256_bytes(b"program")
    output_digest = _sha256_bytes(b"output") if mixed else program_digest
    duration_ms = 6_000
    cue_ids = ["sfxcue-" + "1" * 64] if mixed else []
    asset_ids = ["sfxasset-" + "2" * 64] if mixed else []
    assets = ([{
        "asset_id": asset_ids[0],
        "sha256": "3" * 64,
        "bytes": 100,
        "duration_ms": 1_500,
        "sample_rate_hz": 48_000,
        "channels": 2,
    }] if mixed else [])
    evidence = ([{"sha256": "4" * 64, "bytes": 50}] if mixed else [])
    return {
        "schema_version": SFX_RENDER_RECEIPT_SCHEMA_VERSION,
        "sfx_compile_receipt_sha256": "5" * 64,
        "sfx_plan_sha256": "6" * 64,
        "cue_manifest_sha256": "7" * 64,
        "edit_policy_sha256": "8" * 64,
        "output_timeline_sha256": derive_sfx_output_timeline_sha256(
            program_sha256=program_digest,
            program_bytes=len(b"program"),
            duration_ms=duration_ms,
        ),
        "ordered_cue_ids": cue_ids,
        "ordered_asset_ids": asset_ids,
        "cue_count": len(cue_ids),
        "output_duration_ms": duration_ms,
        "render_timeout_seconds": sfx_render._render_timeout_seconds(
            duration_ms, len(cue_ids)
        ),
        "program_input": {
            "sha256": program_digest,
            "bytes": len(b"program"),
            "duration_ms": duration_ms,
            "audio_present": True,
        },
        "runtime_tools": [
            {"name": "ffmpeg", "sha256": "9" * 64, "bytes": 100},
            {"name": "ffprobe", "sha256": "a" * 64, "bytes": 100},
        ],
        "asset_inputs": assets,
        "evidence_inputs": evidence,
        "filter_complex_sha256": (
            _sha256_bytes(b"graph") if mixed else _sha256_bytes(b"")
        ),
        "render_mode": "mixed" if mixed else "no_cues_copy",
        "output": {
            "file": "sfx-output.mp4",
            "sha256": output_digest,
            "bytes": 222 if mixed else len(b"program"),
            "duration_ms": duration_ms,
            "sample_rate_hz": 48_000,
            "channels": 2,
        },
    }


class SfxRenderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool_pair = _discover_ffmpeg_pair()
        cls.temp = tempfile.TemporaryDirectory(prefix="sfx-render-fixtures-")
        cls.root = Path(cls.temp.name).resolve()
        cls.program = cls.root / "program with spaces & [safe].mp4"
        cls.silent_program = cls.root / "silent program ; [safe].mp4"
        cls.mono_program = cls.root / "mono 44k program $safe.mp4"
        cls.asset = cls.root / "cue & calc ; [x] $dollar.wav"
        cls.evidence = {
            "license": cls.root / "license & ownership [proof].bin",
            "event": cls.root / "event ; anchor [proof].bin",
            "speech": cls.root / "speech $ window [proof].bin",
        }
        cls.evidence["license"].write_bytes(b"project-owned generation receipt\n")
        cls.evidence["event"].write_bytes(b"event anchor evidence\n")
        cls.evidence["speech"].write_bytes(b"speech interval evidence\n")
        if cls.tool_pair is None:
            return
        ffmpeg, _ = cls.tool_pair
        _run([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x183040:s=320x180:r=30:d=6",
            "-f", "lavfi", "-i",
            "sine=frequency=220:sample_rate=48000:duration=6",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
            "-ac", "2", "-filter:a", "volume=0.025", str(cls.program),
        ])
        _run([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x183040:s=320x180:r=30:d=6",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-pix_fmt", "yuv420p", str(cls.silent_program),
        ])
        _run([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x183040:s=320x180:r=30:d=6",
            "-f", "lavfi", "-i",
            "sine=frequency=220:sample_rate=44100:duration=6",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100",
            "-ac", "1", str(cls.mono_program),
        ])
        _run([
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            "sine=frequency=1000:sample_rate=48000:duration=1.5",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            str(cls.asset),
        ])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def require_real_media(self) -> tuple[str, str]:
        if self.tool_pair is None:
            self.skipTest("pinned/system FFmpeg and FFprobe were not discoverable")
        return self.tool_pair

    def _request(
        self,
        program: Path,
        work: Path,
        *,
        with_cue: bool,
        output_name: str = "sfx-output.mp4",
    ) -> dict:
        ffmpeg, ffprobe = self.require_real_media()
        manifest, plan, policy, assets, evidence = _manifest_and_plan(
            program, self.asset, self.evidence, with_cue=with_cue
        )
        return {
            "program_path": str(program.resolve()),
            "output_path": str((work / output_name).resolve()),
            "plan": plan,
            "cue_manifest": manifest,
            "edit_policy": policy,
            "asset_paths": assets,
            "evidence_paths": evidence,
            "work_dir": str(work.resolve()),
            "ffmpeg_path": ffmpeg,
            "ffprobe_path": ffprobe,
        }

    def test_render_receipt_is_canonical_closed_and_workload_bound(self) -> None:
        receipt = _valid_render_receipt()
        canonical = canonical_sfx_render_receipt_json(receipt)
        self.assertEqual(json.loads(canonical), receipt)
        self.assertEqual(
            sfx_render_receipt_sha256(receipt),
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
        mutations = []
        changed = copy.deepcopy(receipt)
        changed["planner_note"] = "execute this"
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["ordered_cue_ids"][0] = "sfxcue-not-a-hash"
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["ordered_asset_ids"][0] = "sfxasset-" + "9" * 64
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["asset_inputs"].append(copy.deepcopy(changed["asset_inputs"][0]))
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["evidence_inputs"].append(copy.deepcopy(changed["evidence_inputs"][0]))
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["render_timeout_seconds"] += 1
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["output_duration_ms"] += 101
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["output_timeline_sha256"] = "0" * 64
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["program_input"]["audio_present"] = 1
        mutations.append(changed)
        for index, value in enumerate(mutations):
            with self.subTest(index=index):
                with self.assertRaises(SfxRenderError):
                    canonical_sfx_render_receipt_json(value)

    def test_no_cue_copy_receipt_binds_exact_bytes_and_empty_topology(self) -> None:
        receipt = _valid_render_receipt(mixed=False)
        canonical_sfx_render_receipt_json(receipt)
        mutations = []
        changed = copy.deepcopy(receipt)
        changed["output"]["sha256"] = "f" * 64
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["output"]["bytes"] += 1
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["filter_complex_sha256"] = "f" * 64
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["asset_inputs"] = [{
            "asset_id": "sfxasset-" + "2" * 64,
            "sha256": "3" * 64,
            "bytes": 100,
            "duration_ms": 100,
            "sample_rate_hz": 48_000,
            "channels": 2,
        }]
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["evidence_inputs"] = [{"sha256": "4" * 64, "bytes": 50}]
        mutations.append(changed)
        changed = copy.deepcopy(receipt)
        changed["program_input"]["audio_present"] = False
        mutations.append(changed)
        for index, value in enumerate(mutations):
            with self.subTest(index=index):
                with self.assertRaises(SfxRenderError):
                    canonical_sfx_render_receipt_json(value)

    def test_maximum_supported_cue_topology_stays_out_of_windows_argv(self) -> None:
        cue_count = 2_048
        asset_id = "sfxasset-" + "a" * 64
        compiled = {
            "compiled_cues": [{
                "asset_id": asset_id,
                "ducking": None,
                "cue_ffmpeg_primitive_tokens": [
                    "atrim=start=0.000:duration=0.020",
                    "asetpts=PTS-STARTPTS",
                ],
                "duck_sidechain_gate_ffmpeg_primitive_tokens": [],
                "sidechaincompress_ffmpeg_primitive_tokens": [],
                "timeline_ffmpeg_primitive_tokens": [
                    f"adelay=delays={index * 3000}:all=1"
                ],
            } for index in range(cue_count)],
            "program_input_ffmpeg_primitive_tokens": ["anull"],
            "sfx_bus_ffmpeg_primitive_tokens": [
                f"amix=inputs={cue_count}:duration=longest:normalize=0"
            ],
            "program_mix_ffmpeg_primitive_tokens": [
                "amix=inputs=2:duration=first:normalize=0"
            ],
            "receipt": {"output_duration_ms": 6_144_000},
        }
        graph = sfx_render._build_filter(compiled)
        self.assertIn("[1:a:0]asplit=outputs=2048", graph)
        self.assertEqual(graph.count("[1:a:0]"), 1)
        self.assertNotIn("[2:a:0]", graph)
        self.assertEqual(graph.count("adelay=delays="), cue_count)
        command = [
            "C:\\AutoEditor\\ffmpeg.exe", "-n", "-i", ".\\sfx-program-input.mp4",
            "-i", ".\\sfx-asset-0001.bin", "-filter_complex_script",
            ".\\sfx-filter.txt", "-map", "0:v:0", "-map", "[aout]",
            ".\\sfx-output.mp4",
        ]
        sfx_render._validate_command_length(command)
        self.assertLess(len(subprocess.list2cmdline(command)) + 1, 30_000)
        with self.assertRaisesRegex(SfxRenderError, "argv bound"):
            sfx_render._validate_command_length(
                command + ["x" * 30_000]
            )

    def test_real_mixed_render_binds_bytes_stream_facts_and_audible_ducking(self) -> None:
        ffmpeg, ffprobe = self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-mixed-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            result = execute_sfx_render(**request)
            output = Path(result["output_path"])
            receipt = result["receipt"]
            self.assertEqual(receipt["render_mode"], "mixed")
            self.assertTrue(receipt["program_input"]["audio_present"])
            self.assertEqual(receipt["cue_count"], 1)
            self.assertEqual(receipt["ordered_asset_ids"], [
                request["plan"]["cues"][0]["asset_id"]
            ])
            self.assertEqual(receipt["output"]["sha256"], _sha256_file(output))
            self.assertEqual(receipt["output"]["bytes"], output.stat().st_size)
            self.assertEqual(
                result["receipt_sha256"], sfx_render_receipt_sha256(receipt)
            )
            self.assertEqual(
                result["compile_receipt_sha256"],
                result["compile_receipt"]["schema_version"]
                and compile_sfx_plan(
                    request["plan"], request["cue_manifest"], request["edit_policy"]
                )["receipt_sha256"],
            )
            facts = _probe(ffprobe, output)
            self.assertAlmostEqual(float(facts["format"]["duration"]), 6.0, delta=0.06)
            audio = next(
                stream for stream in facts["streams"]
                if stream["codec_type"] == "audio"
            )
            self.assertEqual((audio["sample_rate"], audio["channels"]), ("48000", 2))
            # The 1 kHz cue exists only at 2.0--3.5 s.  Its first 500 ms is
            # intentionally ducked beneath trusted speech, while the later
            # portion is un-ducked.  Correlation measures decoded placement,
            # not container metadata or the presence of a filter token.
            before = _tone_amplitude(
                ffmpeg, output, start_seconds=1.4, duration_seconds=0.3,
                frequency_hz=1_000,
            )
            ducked = _tone_amplitude(
                ffmpeg, output, start_seconds=2.15, duration_seconds=0.2,
                frequency_hz=1_000,
            )
            open_cue = _tone_amplitude(
                ffmpeg, output, start_seconds=2.75, duration_seconds=0.2,
                frequency_hz=1_000,
            )
            after = _tone_amplitude(
                ffmpeg, output, start_seconds=3.7, duration_seconds=0.3,
                frequency_hz=1_000,
            )
            self.assertGreater(ducked, max(before, after) * 5.0)
            self.assertGreater(open_cue, ducked * 2.0)
            self.assertIn("sidechaincompress=", result["filter_complex"])
            self.assertNotIn(str(self.asset), result["filter_complex"])

    def test_no_cue_copy_is_byte_exact_and_closed(self) -> None:
        self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-copy-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=False)
            result = execute_sfx_render(**request)
            output = Path(result["output_path"])
            receipt = result["receipt"]
            self.assertEqual(receipt["render_mode"], "no_cues_copy")
            self.assertEqual(output.read_bytes(), self.program.read_bytes())
            self.assertEqual(receipt["program_input"]["sha256"],
                             receipt["output"]["sha256"])
            self.assertEqual(receipt["program_input"]["bytes"],
                             receipt["output"]["bytes"])
            self.assertEqual(result["filter_complex"], "")
            self.assertEqual(receipt["asset_inputs"], [])
            self.assertEqual(receipt["evidence_inputs"], [])

    def test_silent_and_non_delivery_audio_are_normalized_to_48k_stereo(self) -> None:
        _, ffprobe = self.require_real_media()
        for name, program, expected_audio_present in (
            ("silent", self.silent_program, False),
            ("mono-44k", self.mono_program, True),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                    prefix=f"sfx-normalized-{name}-") as raw:
                work = Path(raw).resolve()
                result = execute_sfx_render(**self._request(
                    program, work, with_cue=False
                ))
                receipt = result["receipt"]
                self.assertEqual(receipt["render_mode"], "no_cues_normalized")
                self.assertIs(receipt["program_input"]["audio_present"],
                              expected_audio_present)
                facts = _probe(ffprobe, Path(result["output_path"]))
                self.assertAlmostEqual(
                    float(facts["format"]["duration"]), 6.0, delta=0.06
                )
                audio = next(
                    stream for stream in facts["streams"]
                    if stream["codec_type"] == "audio"
                )
                self.assertEqual(
                    (audio["sample_rate"], audio["channels"]), ("48000", 2)
                )

    def test_silent_program_accepts_real_motivated_cue(self) -> None:
        ffmpeg, _ = self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-silent-mix-") as raw:
            work = Path(raw).resolve()
            result = execute_sfx_render(**self._request(
                self.silent_program, work, with_cue=True
            ))
            self.assertEqual(result["receipt"]["render_mode"], "mixed")
            self.assertFalse(result["receipt"]["program_input"]["audio_present"])
            before = _tone_amplitude(
                ffmpeg, Path(result["output_path"]), start_seconds=1.4,
                duration_seconds=0.3, frequency_hz=1_000,
            )
            cue = _tone_amplitude(
                ffmpeg, Path(result["output_path"]), start_seconds=2.75,
                duration_seconds=0.2, frequency_hz=1_000,
            )
            self.assertGreater(cue, max(before, 1e-7) * 100.0)

    def test_exact_timeline_asset_and_evidence_bindings_reject_tampering(self) -> None:
        self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-bindings-") as raw:
            base = Path(raw).resolve()
            request = self._request(self.program, base, with_cue=True)

            bad_timeline = copy.deepcopy(request)
            bad_timeline["cue_manifest"]["output_timeline_sha256"] = "0" * 64
            bad_timeline["plan"]["cue_manifest_sha256"] = sfx_cue_manifest_sha256(
                bad_timeline["cue_manifest"]
            )
            bad_timeline["plan"]["output_timeline_sha256"] = "0" * 64
            with self.assertRaisesRegex(SfxRenderError, "exact program timeline"):
                execute_sfx_render(**bad_timeline)

        for field, value in (
            ("sha256", "0" * 64),
            ("byte_length", self.asset.stat().st_size + 1),
            ("sample_rate_hz", 44_100),
            ("channels", 1),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory(
                    prefix=f"sfx-asset-{field}-") as raw:
                work = Path(raw).resolve()
                request = self._request(self.program, work, with_cue=True)
                asset = request["cue_manifest"]["assets"][0]
                payload = {
                    key: copy.deepcopy(value2)
                    for key, value2 in asset.items() if key != "asset_id"
                }
                payload[field] = value
                changed_id = derive_sfx_asset_id(payload)
                request["cue_manifest"]["assets"][0] = {
                    "asset_id": changed_id, **payload,
                }
                cue = request["plan"]["cues"][0]
                cue["asset_id"] = changed_id
                cue["asset_sha256"] = payload["sha256"]
                cue_payload = {
                    key: copy.deepcopy(value2)
                    for key, value2 in cue.items() if key != "cue_id"
                }
                cue["cue_id"] = derive_sfx_cue_id(cue_payload)
                request["asset_paths"] = {changed_id: str(self.asset.resolve())}
                request["plan"]["cue_manifest_sha256"] = sfx_cue_manifest_sha256(
                    request["cue_manifest"]
                )
                with self.assertRaises(SfxRenderError):
                    execute_sfx_render(**request)

        with tempfile.TemporaryDirectory(prefix="sfx-evidence-bytes-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            digest = next(iter(request["evidence_paths"]))
            forged = work / "forged evidence.bin"
            forged.write_bytes(b"not the bound evidence")
            request["evidence_paths"][digest] = str(forged.resolve())
            with self.assertRaisesRegex(SfxRenderError, "trusted binding"):
                execute_sfx_render(**request)

    def test_asset_and_evidence_inventories_are_exact(self) -> None:
        self.require_real_media()
        fake_asset = "sfxasset-" + "f" * 64
        fake_evidence = "f" * 64
        for kind in ("asset-missing", "asset-excess", "evidence-missing", "evidence-excess"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                    prefix=f"sfx-inventory-{kind}-") as raw:
                work = Path(raw).resolve()
                request = self._request(self.program, work, with_cue=True)
                if kind == "asset-missing":
                    request["asset_paths"].clear()
                elif kind == "asset-excess":
                    request["asset_paths"][fake_asset] = str(self.asset.resolve())
                elif kind == "evidence-missing":
                    request["evidence_paths"].pop(next(iter(request["evidence_paths"])))
                else:
                    request["evidence_paths"][fake_evidence] = str(
                        self.evidence["event"].resolve()
                    )
                with self.assertRaisesRegex(SfxRenderError, "inventory"):
                    execute_sfx_render(**request)
                self.assertFalse(Path(request["output_path"]).exists())

    def test_paths_are_absolute_private_and_never_enter_the_filter_graph(self) -> None:
        self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-paths-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            result = execute_sfx_render(**request)
            graph = result["filter_complex"]
            self.assertNotIn(str(self.program), graph)
            self.assertNotIn(str(self.asset), graph)
            for value in request["evidence_paths"].values():
                self.assertNotIn(value, graph)
        with tempfile.TemporaryDirectory(prefix="sfx-relative-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            request["asset_paths"][next(iter(request["asset_paths"]))] = "relative.wav"
            with self.assertRaisesRegex(SfxRenderError, "absolute"):
                execute_sfx_render(**request)
        with tempfile.TemporaryDirectory(prefix="sfx-outside-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            request["output_path"] = str((self.root / "outside.mp4").resolve())
            with self.assertRaisesRegex(SfxRenderError, "inside"):
                execute_sfx_render(**request)

    def test_output_and_fixed_private_files_are_never_overwritten(self) -> None:
        self.require_real_media()
        for name, contents in (
            ("sfx-output.mp4", b"existing final"),
            ("sfx-program-input.mp4", b"existing snapshot"),
            ("sfx-filter.txt", b"existing filter"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                    prefix="sfx-no-overwrite-") as raw:
                work = Path(raw).resolve()
                sentinel = work / name
                sentinel.write_bytes(contents)
                request = self._request(self.program, work, with_cue=True)
                with self.assertRaises(SfxRenderError):
                    execute_sfx_render(**request)
                self.assertEqual(sentinel.read_bytes(), contents)

    def test_partial_final_output_is_removed_after_child_failure(self) -> None:
        self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-partial-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            output = Path(request["output_path"])
            original_run = sfx_render._run

            def failing_run(command, *, cwd, label, timeout_seconds=60):
                if label == "SFX render":
                    output.write_bytes(b"partial untrusted MP4")
                    raise SfxRenderError("forced child failure")
                return original_run(
                    command, cwd=cwd, label=label,
                    timeout_seconds=timeout_seconds,
                )

            with mock.patch.object(sfx_render, "_run", side_effect=failing_run):
                with self.assertRaisesRegex(SfxRenderError, "forced child failure"):
                    execute_sfx_render(**request)
            self.assertFalse(output.exists())

    def test_aggregate_input_and_work_volume_preflights_fail_before_snapshots(self) -> None:
        self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-aggregate-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            asset = request["cue_manifest"]["assets"][0]
            asset["byte_length"] = sfx_render.MAX_TOTAL_ASSET_BYTES + 1
            payload = {
                key: copy.deepcopy(value)
                for key, value in asset.items() if key != "asset_id"
            }
            asset_id = derive_sfx_asset_id(payload)
            request["cue_manifest"]["assets"][0] = {
                "asset_id": asset_id, **payload,
            }
            cue = request["plan"]["cues"][0]
            cue["asset_id"] = asset_id
            cue_payload = {
                key: copy.deepcopy(value)
                for key, value in cue.items() if key != "cue_id"
            }
            cue["cue_id"] = derive_sfx_cue_id(cue_payload)
            request["plan"]["cue_manifest_sha256"] = sfx_cue_manifest_sha256(
                request["cue_manifest"]
            )
            request["asset_paths"] = {asset_id: str(self.asset.resolve())}
            with self.assertRaisesRegex(SfxRenderError, "aggregate byte bounds"):
                execute_sfx_render(**request)
            self.assertEqual(list(work.iterdir()), [])

        with tempfile.TemporaryDirectory(prefix="sfx-free-space-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            fake_usage = shutil._ntuple_diskusage(total=1_000, used=999, free=1)
            with mock.patch.object(
                    sfx_render.shutil, "disk_usage", return_value=fake_usage):
                with self.assertRaisesRegex(SfxRenderError, "lacks space"):
                    execute_sfx_render(**request)
            self.assertEqual(list(work.iterdir()), [])

    def test_snapshot_closes_source_toctou_and_detects_pre_snapshot_race(self) -> None:
        self.require_real_media()
        with tempfile.TemporaryDirectory(prefix="sfx-snapshot-safe-") as raw:
            root = Path(raw).resolve()
            program = root / "caller program.mp4"
            asset = root / "caller cue.wav"
            shutil.copyfile(self.program, program)
            shutil.copyfile(self.asset, asset)
            evidence = {}
            for key, source in self.evidence.items():
                target = root / f"caller {key}.bin"
                shutil.copyfile(source, target)
                evidence[key] = target
            work = root / "work"
            work.mkdir()
            ffmpeg, ffprobe = self.require_real_media()
            manifest, plan, policy, assets, evidence_paths = _manifest_and_plan(
                program, asset, evidence, with_cue=True
            )
            request = {
                "program_path": str(program),
                "output_path": str(work / "sfx-output.mp4"),
                "plan": plan,
                "cue_manifest": manifest,
                "edit_policy": policy,
                "asset_paths": assets,
                "evidence_paths": evidence_paths,
                "work_dir": str(work),
                "ffmpeg_path": ffmpeg,
                "ffprobe_path": ffprobe,
            }
            original_run = sfx_render._run
            mutated = False

            def mutate_after_snapshot(command, *, cwd, label, timeout_seconds=60):
                nonlocal mutated
                if label == "SFX render" and not mutated:
                    program.write_bytes(b"attacker replaced caller program")
                    asset.write_bytes(b"attacker replaced caller asset")
                    mutated = True
                return original_run(
                    command, cwd=cwd, label=label,
                    timeout_seconds=timeout_seconds,
                )

            with mock.patch.object(
                    sfx_render, "_run", side_effect=mutate_after_snapshot):
                result = execute_sfx_render(**request)
            self.assertTrue(mutated)
            self.assertEqual(
                result["receipt"]["program_input"]["sha256"],
                request["cue_manifest"]["output_timeline_sha256"]
                and request["plan"]["cues"][0]["asset_sha256"]
                and manifest["output_timeline_sha256"]
                and _sha256_file(self.program),
            )
            self.assertTrue(Path(result["output_path"]).is_file())

        with tempfile.TemporaryDirectory(prefix="sfx-snapshot-race-") as raw:
            work = Path(raw).resolve()
            request = self._request(self.program, work, with_cue=True)
            original_snapshot = sfx_render._snapshot
            raced = False
            asset_id = next(iter(request["asset_paths"]))
            raced_asset = work / "raced.wav"
            shutil.copyfile(self.asset, raced_asset)
            request["asset_paths"][asset_id] = str(raced_asset)

            def race_before_copy(source, target, expected_sha256, expected_bytes, label):
                nonlocal raced
                if label.startswith("SFX asset") and not raced:
                    source.write_bytes(b"changed between validation and copy")
                    raced = True
                return original_snapshot(
                    source, target, expected_sha256, expected_bytes, label
                )

            with mock.patch.object(
                    sfx_render, "_snapshot", side_effect=race_before_copy):
                with self.assertRaisesRegex(SfxRenderError, "trusted binding"):
                    execute_sfx_render(**request)
            self.assertTrue(raced)
            self.assertFalse(Path(request["output_path"]).exists())


if __name__ == "__main__":
    unittest.main()
