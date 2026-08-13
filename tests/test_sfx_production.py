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

from autoeditor import creative_contract, sfx_production
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
from autoeditor.sfx_production import (
    SfxProductionError,
    execute_project_intent_sfx,
    specialize_edit_policy_for_program,
    verify_sfx_production_evidence,
    write_sfx_production_probe,
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


def _project_intent(sfx: str) -> dict:
    preferences = {
        "captions": "auto", "graphics": "auto", "music": "auto",
        "sfx": sfx, "transitions": "auto",
    }
    return {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": "dialogue_talking_head",
        "delivery": {"platform": "youtube", "aspect": "16:9"},
        "target_duration": {"min_ms": 30_000, "max_ms": 45_000},
        "preferences": {
            name: {"enabled": value != "none", "preference": value}
            for name, value in preferences.items()
        },
    }


def _envelope(sfx: str) -> dict:
    project = _project_intent(sfx)
    manifest = {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": "a" * 64,
        "available_capabilities": sorted(CAPABILITIES),
    }
    policy = resolve_project_intent_policy(project, manifest)
    proposal = {
        "schema_version": "autoeditor-fixed-sfx-test-proposal/v1",
        "project_intent_sha256": _digest(project),
    }
    authority = {
        "schema_version": "autoeditor-project-intent-authority/v2",
        "authorization_id": "1" * 32,
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


def _edl() -> dict:
    value = {
        "protocol_version": creative_contract.PROTOCOL_VERSION,
        "timeline_space": creative_contract.TIMELINE_SPACE,
        "punch_ins": [],
        "broll": [],
        "graphics": [{
            "s": 10.0, "e": 13.0, "kind": "stat",
            "text": "Exact result", "value": "42%", "items": [],
            "anchor_quote": "exact result forty two percent",
            "reason": "verified statistic reveal",
        }],
    }
    value["production_receipt"] = {
        "source": "deepseek",
        "protocol_version": creative_contract.PROTOCOL_VERSION,
        "contract_sha256": creative_contract.contract_sha256(),
        "validated_plan_sha256": creative_contract.edl_sha256(value),
    }
    return value


def _boundaries() -> dict:
    return {
        "schema": "autoeditor-edit-boundaries/v1",
        "timeline": "post_cut_seconds",
        "cuts": [{
            "index": 0, "time_seconds": 20.0, "removed_seconds": 0.8,
        }],
        "transitions": [],
        "transition_support": "not_implemented",
    }


def _words() -> list[dict]:
    return [
        {"w": "exact", "s": 11.0, "e": 11.5},
        {"w": "result", "s": 11.55, "e": 12.1},
    ]


class SfxProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = _tool_pair()
        cls.fixture = tempfile.TemporaryDirectory(prefix="sfx-production-media-")
        cls.program = Path(cls.fixture.name) / "program.mp4"
        cls.probe_program = Path(cls.fixture.name) / "probe-program.mp4"
        if cls.tools is not None:
            ffmpeg, _ = cls.tools
            _run([
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "color=c=0x203050:s=160x90:r=30:d=36",
                "-f", "lavfi", "-i",
                "sine=frequency=220:sample_rate=48000:duration=36",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-shortest", str(cls.program),
            ])
            _run([
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "color=c=0x142238:s=160x90:r=30:d=3",
                "-f", "lavfi", "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000:d=3",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-shortest", str(cls.probe_program),
            ])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def _request(self, root: Path, preference: str = "motivated_only",
                 *, rendered: bool = True) -> dict:
        work = root / "work"
        evidence = root / "evidence"
        work.mkdir()
        evidence.mkdir()
        envelope = _envelope(preference)
        assert self.tools is not None
        ffmpeg, ffprobe = self.tools
        return {
            "program_path": str(self.program.resolve()),
            "project_intent_envelope": envelope,
            "project_intent_envelope_sha256": (
                project_intent_engine_envelope_sha256(envelope)),
            "edl": _edl(),
            "rendered_graphics": ([{"s": 10.0, "e": 13.0}]
                                  if rendered else []),
            "rendered_broll": [],
            "edit_boundaries_receipt": _boundaries(),
            "speech_words": _words(),
            "work_dir": str(work.resolve()),
            "evidence_dir": str(evidence.resolve()),
            "ffmpeg_path": ffmpeg,
            "ffprobe_path": ffprobe,
        }

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_real_fixed_production_probe_decodes_placement_and_rejects_tamper(
            self) -> None:
        assert self.tools is not None
        ffmpeg, ffprobe = self.tools
        with tempfile.TemporaryDirectory(prefix="sfx-production-probe-") as raw:
            root = Path(raw)
            output = root / "probe-output.mp4"
            result = write_sfx_production_probe(
                str(self.probe_program), str(output), str(root),
                ffmpeg, ffprobe,
            )
            self.assertEqual(
                result["schema_version"],
                "autoeditor-sfx-production-self-test/v1",
            )
            self.assertTrue(all(result["checks"].values()))
            self.assertEqual(
                result["artifact"]["sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )
            self.assertEqual(result["artifact"]["duration_ms"], 3_000)
            self.assertEqual(result["decoded_placement"]["expected_start_ms"], 460)
            self.assertGreater(
                result["decoded_placement"]["cue_delta_rms_millionths"],
                result["decoded_placement"]["control_delta_rms_millionths"] * 8,
            )
            self.assertEqual(result["evidence"]["rights_basis"], "project_owned")
            self.assertIs(result["evidence"]["external_service_used"], False)
            self.assertGreaterEqual(result["evidence"]["sidecar_count"], 9)
            with self.assertRaises(SfxProductionError):
                write_sfx_production_probe(
                    str(self.probe_program), str(output), str(root),
                    ffmpeg, ffprobe,
                )

    def _verify(self, request: dict, result: dict) -> dict:
        envelope = request["project_intent_envelope"]
        return verify_sfx_production_evidence(
            result["receipt"], output_path=result["output_path"],
            evidence_dir=request["evidence_dir"],
            expected_engine_envelope_sha256=(
                request["project_intent_envelope_sha256"]),
            expected_project_intent_sha256=envelope["project_intent_sha256"],
            expected_parent_edit_policy_sha256=envelope["edit_policy_sha256"],
        )

    def test_actual_duration_specialization_preserves_range_authority(self):
        parent = _envelope("motivated_only")["edit_policy"]
        child = specialize_edit_policy_for_program(
            parent, target_duration={"min_ms": 30_000, "max_ms": 45_000},
            actual_duration_ms=36_000,
        )
        self.assertEqual(child["duration"], {
            "duration_ms": 36_000, "band": "short",
        })
        parent_copy = copy.deepcopy(parent)
        child_copy = copy.deepcopy(child)
        parent_copy.pop("duration")
        child_copy.pop("duration")
        self.assertEqual(parent_copy, child_copy)
        self.assertNotEqual(edit_policy_sha256(parent), edit_policy_sha256(child))

        for target, actual in (
            ({"min_ms": 30_000, "max_ms": 45_000}, 29_999),
            ({"min_ms": 30_000, "max_ms": 61_000}, 40_000),
        ):
            with self.subTest(target=target, actual=actual):
                with self.assertRaises(SfxProductionError):
                    specialize_edit_policy_for_program(
                        parent, target_duration=target,
                        actual_duration_ms=actual,
                    )

    def test_profile_mismatched_explicit_usage_fails_before_engine_authority(self):
        project = _project_intent("event_accent_only")
        manifest = {
            "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
            "source": CAPABILITY_MANIFEST_SOURCE,
            "probe_receipt_sha256": "a" * 64,
            "available_capabilities": sorted(CAPABILITIES),
        }
        with self.assertRaises(ProjectIntentPolicyBridgeError):
            resolve_project_intent_policy(project, manifest)

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_real_typed_render_persists_and_reopens_complete_evidence(self):
        with tempfile.TemporaryDirectory(prefix="sfx-production-real-") as raw:
            request = self._request(Path(raw))
            result = execute_project_intent_sfx(**request)
            check = self._verify(request, result)
            receipt = result["receipt"]

            self.assertTrue(result["executed"])
            self.assertTrue(check["ok"], check["note"])
            self.assertGreater(receipt["cue_count"], 0)
            self.assertEqual(receipt["actual_duration_ms"], 36_000)
            self.assertEqual(receipt["target_duration"], {
                "min_ms": 30_000, "max_ms": 45_000,
            })
            self.assertNotEqual(
                receipt["parent_edit_policy_sha256"],
                receipt["execution_edit_policy_sha256"],
            )
            self.assertNotEqual(
                hashlib.sha256(self.program.read_bytes()).hexdigest(),
                receipt["output"]["sha256"],
            )
            sidecars = {item["file"] for item in receipt["sidecars"]}
            self.assertTrue({
                "SFX_CUE_MANIFEST.json", "SFX_PLAN.json",
                "SFX_COMPILE_RECEIPT.json", "SFX_RENDER_RECEIPT.json",
                "SFX_EDL_ANCHOR_EVIDENCE.json",
                "SFX_BOUNDARY_ANCHOR_EVIDENCE.json",
                "SFX_SPEECH_EVIDENCE.json", "SFX_GENERATION_IMPACT.json",
            } <= sidecars)

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_none_and_auto_without_anchor_never_invoke_renderer(self):
        cases = (("none", True, "no_sfx_requested"),
                 ("auto", False, "no_motivated_anchor"))
        for preference, rendered, expected_mode in cases:
            with self.subTest(preference=preference), tempfile.TemporaryDirectory(
                    prefix="sfx-production-noop-") as raw:
                request = self._request(
                    Path(raw), preference=preference, rendered=rendered)
                with mock.patch.object(
                        sfx_production, "execute_sfx_render") as executor:
                    result = execute_project_intent_sfx(**request)
                self.assertFalse(result["executed"])
                self.assertEqual(result["receipt"]["mode"], expected_mode)
                self.assertEqual(result["receipt"]["cue_count"], 0)
                self.assertEqual(Path(result["output_path"]), self.program.resolve())
                executor.assert_not_called()
                self.assertTrue(self._verify(request, result)["ok"])

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_tampered_output_missing_sidecar_and_rights_fail_qa(self):
        mutations = ("output", "missing", "rights")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                    prefix=f"sfx-production-tamper-{mutation}-") as raw:
                request = self._request(Path(raw))
                result = execute_project_intent_sfx(**request)
                receipt = copy.deepcopy(result["receipt"])
                evidence = Path(request["evidence_dir"])
                if mutation == "output":
                    Path(result["output_path"]).write_bytes(
                        Path(result["output_path"]).read_bytes() + b"tamper")
                elif mutation == "missing":
                    (evidence / "SFX_PLAN.json").unlink()
                else:
                    path = evidence / "SFX_GENERATION_IMPACT.json"
                    value = json.loads(path.read_text(encoding="ascii"))
                    value["rights"]["external_service_used"] = True
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
    def test_anchor_receipt_tamper_fails_even_when_sidecar_hash_is_rebound(self):
        with tempfile.TemporaryDirectory(prefix="sfx-production-anchor-") as raw:
            request = self._request(Path(raw))
            result = execute_project_intent_sfx(**request)
            receipt = copy.deepcopy(result["receipt"])
            path = Path(request["evidence_dir"]) / "SFX_EDL_ANCHOR_EVIDENCE.json"
            value = json.loads(path.read_text(encoding="ascii"))
            value["rendered_graphics"][0]["start_ms"] += 500
            path.write_text(_canonical(value) + "\n", encoding="ascii")
            binding = next(
                item for item in receipt["sidecars"] if item["file"] == path.name)
            binding["bytes"] = path.stat().st_size
            binding["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            check = self._verify(request, {**result, "receipt": receipt})
            self.assertFalse(check["ok"])

    @unittest.skipUnless(_tool_pair() is not None, "real FFmpeg is unavailable")
    def test_render_asset_tamper_fails_even_when_both_hashes_are_rebound(self):
        with tempfile.TemporaryDirectory(prefix="sfx-production-render-") as raw:
            request = self._request(Path(raw))
            result = execute_project_intent_sfx(**request)
            receipt = copy.deepcopy(result["receipt"])
            path = Path(request["evidence_dir"]) / "SFX_RENDER_RECEIPT.json"
            value = json.loads(path.read_text(encoding="ascii"))
            value["asset_inputs"][0]["sha256"] = "f" * 64
            path.write_text(_canonical(value) + "\n", encoding="ascii")
            receipt["sfx_render_receipt_sha256"] = (
                sfx_production.sfx_render_receipt_sha256(value)
            )
            binding = next(
                item for item in receipt["sidecars"] if item["file"] == path.name)
            binding["bytes"] = path.stat().st_size
            binding["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            check = self._verify(request, {**result, "receipt": receipt})
            self.assertFalse(check["ok"])
            self.assertIn("asset inventory", check["note"])


if __name__ == "__main__":
    unittest.main()
