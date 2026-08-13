from __future__ import annotations

import copy
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from autoeditor import pipeline
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
    sequence_plan_sha256,
    source_manifest_sha256,
)
from autoeditor.project_intent_policy_bridge import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_MANIFEST_SOURCE,
    PROJECT_INTENT_SCHEMA_VERSION,
    resolve_project_intent_policy,
)
from autoeditor.transition_plan import (
    TRANSITION_PLAN_SCHEMA_VERSION,
    TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
    derive_boundary_id,
    transition_plan_sha256,
    transition_sequence_manifest_sha256,
)


_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "transition_daemon_integration",
    _ROOT / "packaging" / "helper_daemon_entry.py",
)
assert _SPEC is not None and _SPEC.loader is not None
daemon = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(daemon)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _policy(duration_ms: int, *, transition_density: str = "auto") -> dict:
    explicit = _auto_values()
    explicit["transition_density"] = transition_density
    return resolve_edit_policy({
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": "commercial_product",
        "duration_ms": duration_ms,
        "delivery": {"platform": "youtube", "aspect": "16:9"},
        "explicit_intent": explicit,
        "consented_preferences": {
            "consented": False,
            "values": _auto_values(),
        },
        "available_capabilities": sorted(CAPABILITIES),
    })


def _contracts(sources: list[dict], *, segment_ms: int = 2_500,
               kind: str = "cross_dissolve",
               transition_ms: int = 200) -> dict:
    source_manifest = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sources": copy.deepcopy(sources),
    }
    segments = []
    for index, source in enumerate(sources):
        segments.append({
            "segment_id": f"segment-{index + 1}",
            "source_id": source["source_id"],
            "source_sha256": source["sha256"],
            "source_start_ms": 0,
            "source_end_ms": segment_ms,
            "role": "development",
            "reason": "Exact transition integration fixture.",
            "speech_anchor": None,
            "transition": {"kind": "hard_cut"},
        })
    total_ms = len(segments) * segment_ms
    sequence_plan = {
        "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
        "sources": copy.deepcopy(sources),
        "target_duration": {"min_ms": total_ms, "max_ms": total_ms},
        "segments": segments,
    }
    compiled = compile_sequence_plan(sequence_plan, source_manifest)
    transition_manifest = {
        "schema_version": TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
        "sequence_plan_sha256": compiled["receipt"]["sequence_plan_sha256"],
        "sequence_compile_receipt_sha256": compiled["receipt_sha256"],
        "frame_rate": {"numerator": 30, "denominator": 1},
        "segments": [{
            "segment_id": item["segment_id"],
            "source_sha256": item["source_sha256"],
            "duration_ms": item["duration_ms"],
            "video_leading_handle_ms": item["duration_ms"],
            "video_trailing_handle_ms": item["duration_ms"],
            "audio_leading_handle_ms": item["duration_ms"],
            "audio_trailing_handle_ms": item["duration_ms"],
            "dialogue_at_start": True,
            "dialogue_at_end": True,
        } for item in compiled["ffmpeg_segments"]],
    }
    policy = _policy(total_ms)
    cumulative_ms = 0
    boundaries = []
    for index, left in enumerate(transition_manifest["segments"][:-1]):
        cumulative_ms += left["duration_ms"]
        right = transition_manifest["segments"][index + 1]
        selected_kind = kind if index == 0 else "hard_cut"
        selected_duration = transition_ms if selected_kind != "hard_cut" else 0
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
            "kind": selected_kind,
            "motivation": policy["rules"]["transitions"]["usage"],
            "duration_ms": selected_duration,
            "audio_behavior": (
                "equal_power_crossfade"
                if selected_kind != "hard_cut" else "hard_cut"
            ),
            "motivation_verified": selected_kind != "hard_cut",
            "semantic_safety_verified": True,
            "dialogue_preservation_verified": True,
        })
    transition_plan = {
        "schema_version": TRANSITION_PLAN_SCHEMA_VERSION,
        "sequence_manifest_sha256": transition_sequence_manifest_sha256(
            transition_manifest
        ),
        "edit_policy_sha256": edit_policy_sha256(policy),
        "frame_rate": {"numerator": 30, "denominator": 1},
        "policy": copy.deepcopy(policy["rules"]["transitions"]),
        "boundaries": boundaries,
    }
    return {
        "sequence_plan": sequence_plan,
        "source_manifest": source_manifest,
        "transition_plan": transition_plan,
        "transition_manifest": transition_manifest,
        "edit_policy": policy,
    }


def _authority_carrier(contracts: dict) -> dict:
    return {
        "sequence_plan_sha256": sequence_plan_sha256(
            contracts["sequence_plan"]
        ),
        "source_manifest_sha256": source_manifest_sha256(
            contracts["source_manifest"]
        ),
        "transition_plan_sha256": transition_plan_sha256(
            contracts["transition_plan"]
        ),
        "transition_sequence_manifest_sha256": (
            transition_sequence_manifest_sha256(
                contracts["transition_manifest"]
            )
        ),
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
    if not ffmpeg:
        candidates = sorted(
            _ROOT.parents[2].glob(
                "*/outputs/*/*/resources/bin/ffmpeg.exe"
            ), reverse=True,
        )
        if candidates:
            ffmpeg = str(candidates[0])
            adjacent = candidates[0].with_name("ffprobe.exe")
            ffprobe = str(adjacent) if adjacent.is_file() else ffprobe
    if not ffmpeg or not ffprobe:
        return None
    return str(Path(ffmpeg).resolve()), str(Path(ffprobe).resolve())


class TransitionDaemonIntegrationTests(unittest.TestCase):
    def test_daemon_hmac_binds_exact_transition_proposal_and_carrier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = [root / "first.mp4", root / "second.mp4"]
            for index, path in enumerate(inputs):
                path.write_bytes(f"authority-source-{index}".encode("ascii"))
            output = root / "output"
            output.mkdir()
            sources = [{
                "source_id": f"source-{index + 1}",
                "sha256": _sha256(path),
                "duration_ms": 3_000,
            } for index, path in enumerate(inputs)]
            contracts = _contracts(sources)
            project = {
                "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
                "profile": "commercial_product",
                "delivery": {"platform": "youtube", "aspect": "16:9"},
                "target_duration": {"min_ms": 5_000, "max_ms": 5_000},
                "preferences": {
                    name: {
                        "enabled": True,
                        "preference": (
                            "motivated_only" if name == "transitions" else "auto"
                        ),
                    }
                    for name in (
                        "captions", "graphics", "music", "sfx", "transitions"
                    )
                },
            }
            capabilities = {
                "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
                "source": CAPABILITY_MANIFEST_SOURCE,
                "probe_receipt_sha256": "a" * 64,
                "available_capabilities": sorted(CAPABILITIES),
            }
            policy = resolve_project_intent_policy(project, capabilities)
            self.assertEqual(policy, contracts["edit_policy"])
            proposal = {
                "summary": "Apply the exact approved motivated transition.",
                "operations": [{"op": "set_edit_style", "style": "long"}],
                "projectIntent": project,
                "sequencePlan": contracts["sequence_plan"],
                "sequenceSourceManifest": contracts["source_manifest"],
                "transitionPlan": contracts["transition_plan"],
                "transitionSequenceManifest": contracts["transition_manifest"],
            }
            signing_key = "2" * 64
            unsigned = {
                "schema_version": daemon.PROJECT_INTENT_AUTHORITY_SCHEMA_VERSION,
                "authorization_id": "1" * 32,
                "approved_proposal_sha256": daemon._canonical_sha256(proposal),
                "project_intent": project,
                "project_intent_sha256": daemon._canonical_sha256(project),
                "edit_policy": policy,
                "edit_policy_sha256": edit_policy_sha256(policy),
                "capability_manifest": capabilities,
                "capability_manifest_sha256": daemon._canonical_sha256(
                    capabilities
                ),
            }
            authority = {
                **unsigned,
                "authorization_hmac_sha256": hmac.new(
                    bytes.fromhex(signing_key),
                    daemon._canonical_authority_json(unsigned).encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest(),
            }
            request = {
                "inputs": [str(path) for path in inputs],
                "outputDir": str(output),
                "projectType": "long",
                "script": "Approved script",
                "cachedTranscript": "",
                "creativeBrief": "",
                "creativeBriefSha256": "",
                "visionAttempt": 0,
                "proposal": proposal,
                "projectIntentAuthority": authority,
            }
            daemon._CONSUMED_PROJECT_INTENT_AUTHORIZATIONS.clear()
            with mock.patch.dict(os.environ, {
                "AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY": signing_key,
            }, clear=False):
                clean = daemon._local_render_request(request)
            self.assertEqual(
                clean["approved_transition_carrier"],
                _authority_carrier(contracts),
            )
            tampered = copy.deepcopy(request)
            tampered["proposal"]["transitionPlan"]["boundaries"][0][
                "duration_ms"
            ] = 267
            with mock.patch.dict(os.environ, {
                "AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY": signing_key,
            }, clear=False), self.assertRaisesRegex(
                ValueError, "does not bind the exact approved proposal"
            ):
                daemon._local_render_request(tampered)
            daemon._CONSUMED_PROJECT_INTENT_AUTHORIZATIONS.clear()

    def test_transition_carrier_hashes_bind_every_exact_approved_preimage(self):
        sources = [
            {"source_id": "first", "sha256": "a" * 64,
             "duration_ms": 3_000},
            {"source_id": "second", "sha256": "b" * 64,
             "duration_ms": 3_000},
        ]
        contracts = _contracts(sources)
        carrier = daemon._approved_transition_carrier(
            contracts["sequence_plan"], contracts["source_manifest"],
            contracts["transition_plan"], contracts["transition_manifest"],
        )
        self.assertEqual(set(carrier), {
            "sequence_plan_sha256", "source_manifest_sha256",
            "transition_plan_sha256",
            "transition_sequence_manifest_sha256",
        })
        mutations = (
            ("sequence_plan", lambda value: value["segments"].reverse()),
            ("source_manifest", lambda value: value["sources"][0].update(
                {"duration_ms": 3_001})),
            ("transition_plan", lambda value: value["boundaries"][0].update(
                {"kind": "hard_cut", "duration_ms": 0,
                 "audio_behavior": "hard_cut"})),
            ("transition_manifest", lambda value: value["segments"][0].update(
                {"video_trailing_handle_ms": 2_499})),
        )
        carrier_keys = (
            "sequence_plan_sha256", "source_manifest_sha256",
            "transition_plan_sha256", "transition_sequence_manifest_sha256",
        )
        for (fixture_name, mutate), carrier_key in zip(mutations, carrier_keys):
            with self.subTest(preimage=fixture_name):
                changed = copy.deepcopy(contracts)
                mutate(changed[fixture_name])
                measured = daemon._approved_transition_carrier(
                    changed["sequence_plan"], changed["source_manifest"],
                    changed["transition_plan"], changed["transition_manifest"],
                )
                self.assertNotEqual(measured[carrier_key], carrier[carrier_key])

    def test_opt_in_carrier_binds_authority_sequence_and_every_boundary(self):
        sources = [
            {"source_id": "first", "sha256": "a" * 64,
             "duration_ms": 3_000},
            {"source_id": "second", "sha256": "b" * 64,
             "duration_ms": 3_000},
        ]
        contracts = _contracts(sources)
        proposal = {
            "sequencePlan": contracts["sequence_plan"],
            "sequenceSourceManifest": contracts["source_manifest"],
            "transitionPlan": contracts["transition_plan"],
            "transitionSequenceManifest": contracts["transition_manifest"],
        }
        accepted_plan, accepted_manifest = daemon._transition_from_proposal(
            proposal, contracts["sequence_plan"], contracts["source_manifest"],
            {"edit_policy": contracts["edit_policy"]},
        )
        self.assertEqual(accepted_plan, contracts["transition_plan"])
        self.assertEqual(accepted_manifest, contracts["transition_manifest"])

        with self.assertRaisesRegex(ValueError, "trusted project intent"):
            daemon._transition_from_proposal(
                proposal, contracts["sequence_plan"],
                contracts["source_manifest"], None,
            )
        missing = copy.deepcopy(proposal)
        del missing["transitionSequenceManifest"]
        with self.assertRaisesRegex(ValueError, "requires its exact"):
            daemon._transition_from_proposal(
                missing, contracts["sequence_plan"],
                contracts["source_manifest"],
                {"edit_policy": contracts["edit_policy"]},
            )

    def test_tamper_policy_and_sequence_replay_fail_closed(self):
        sources = [
            {"source_id": "first", "sha256": "a" * 64,
             "duration_ms": 3_000},
            {"source_id": "second", "sha256": "b" * 64,
             "duration_ms": 3_000},
        ]
        contracts = _contracts(sources)
        proposal = {
            "sequencePlan": contracts["sequence_plan"],
            "sequenceSourceManifest": contracts["source_manifest"],
            "transitionPlan": contracts["transition_plan"],
            "transitionSequenceManifest": contracts["transition_manifest"],
        }
        with self.assertRaisesRegex(ValueError, "resolved edit policy"):
            daemon._transition_from_proposal(
                proposal, contracts["sequence_plan"],
                contracts["source_manifest"],
                {"edit_policy": _policy(5_000, transition_density="none")},
            )

        replayed = copy.deepcopy(contracts["sequence_plan"])
        replayed["segments"].reverse()
        with self.assertRaisesRegex(ValueError, "does not bind"):
            daemon._transition_from_proposal(
                proposal, replayed, contracts["source_manifest"],
                {"edit_policy": contracts["edit_policy"]},
            )

        tampered = copy.deepcopy(proposal)
        tampered["transitionSequenceManifest"]["segments"][0][
            "audio_trailing_handle_ms"
        ] -= 1
        with self.assertRaisesRegex(ValueError, "malformed"):
            daemon._transition_from_proposal(
                tampered, contracts["sequence_plan"],
                contracts["source_manifest"],
                {"edit_policy": contracts["edit_policy"]},
            )

    def test_absent_transition_keeps_legacy_sequence_renderer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = [root / "first.mp4", root / "second.mp4"]
            for index, path in enumerate(inputs):
                path.write_bytes(f"source-{index}".encode("ascii"))
            sources = [{
                "source_id": f"source-{index}",
                "sha256": _sha256(path),
                "duration_ms": 3_000,
            } for index, path in enumerate(inputs)]
            contracts = _contracts(sources)
            facts = {
                "duration_ms": 3_000,
                "video": {
                    "width": 320, "height": 180,
                    "fps_numerator": 30, "fps_denominator": 1,
                    "start_offset_ms": 0, "duration_ms": 3_000,
                    "end_offset_ms": 3_000, "codec_name": "h264",
                    "pix_fmt": "yuv420p", "color_range": "tv",
                    "color_space": "bt709", "color_transfer": "bt709",
                    "color_primaries": "bt709",
                },
                "audio": {
                    "present": True, "sample_rate": 48_000, "channels": 2,
                    "start_offset_ms": 0, "duration_ms": 3_000,
                    "end_offset_ms": 3_000,
                },
            }
            rendered_facts = copy.deepcopy(facts)
            rendered_facts["duration_ms"] = 5_000
            rendered_facts["video"]["duration_ms"] = 5_000
            rendered_facts["video"]["end_offset_ms"] = 5_000
            rendered_facts["audio"]["duration_ms"] = 5_000
            rendered_facts["audio"]["end_offset_ms"] = 5_000

            def execute(argv, **kwargs):
                (Path(kwargs["cwd"]) / argv[-1]).write_bytes(b"legacy-render")
                return mock.Mock(returncode=0, stderr="")

            work = root / "work"
            work.mkdir()
            with mock.patch.dict(daemon.os.environ, {
                "AUTOEDITOR_FFMPEG": "ffmpeg",
            }), mock.patch.object(
                daemon, "_probe_sequence_source",
                side_effect=[copy.deepcopy(facts), copy.deepcopy(facts),
                             rendered_facts],
            ), mock.patch.object(
                daemon, "build_transition_render"
            ) as transition_executor, mock.patch.object(
                daemon.subprocess, "run", side_effect=execute
            ):
                _, receipt = daemon._build_approved_sequence(
                    inputs, "custom", work, contracts["sequence_plan"],
                    contracts["source_manifest"],
                )
        transition_executor.assert_not_called()
        self.assertEqual(
            receipt["schema_version"],
            "autoeditor-sequence-handoff-receipt/v1",
        )
        self.assertNotIn("transition_executor_receipt", receipt)

    def test_real_ffmpeg_transition_executes_shell_free_and_closes_handoff(self):
        tools = _discover_ffmpeg_pair()
        if tools is None:
            self.skipTest("bundled/system FFmpeg and FFprobe are unavailable")
        ffmpeg, ffprobe = tools
        with tempfile.TemporaryDirectory(prefix="transition-daemon-real-") as raw:
            root = Path(raw)
            inputs = [
                root / "first & hostile.mp4",
                root / "second [hostile].mp4",
            ]
            for path, color, frequency in zip(
                    inputs, ("red", "blue"), (440, 880)):
                generated = subprocess.run([
                    ffmpeg, "-y", "-v", "error",
                    "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x180:r=30:d=2.600",
                    "-f", "lavfi", "-i",
                    f"sine=frequency={frequency}:sample_rate=48000:duration=2.600",
                    "-map", "0:v:0", "-map", "1:a:0", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", shell=False)
                self.assertEqual(generated.returncode, 0, generated.stderr)

            with mock.patch.dict(daemon.os.environ, {
                "AUTOEDITOR_FFMPEG": ffmpeg,
                "AUTOEDITOR_FFPROBE": ffprobe,
            }):
                probed = [daemon._probe_sequence_source(path) for path in inputs]
            sources = [{
                "source_id": f"source-{index + 1}",
                "sha256": _sha256(path),
                "duration_ms": facts["duration_ms"],
            } for index, (path, facts) in enumerate(zip(inputs, probed))]
            contracts = _contracts(sources)
            work = root / "private-work"
            work.mkdir()
            calls: list[tuple[list[str], dict]] = []
            real_run = subprocess.run

            def record_run(argv, **kwargs):
                calls.append((list(argv), dict(kwargs)))
                return real_run(argv, **kwargs)

            with mock.patch.dict(daemon.os.environ, {
                "AUTOEDITOR_FFMPEG": ffmpeg,
                "AUTOEDITOR_FFPROBE": ffprobe,
            }), mock.patch.object(daemon.subprocess, "run", side_effect=record_run):
                output, receipt = daemon._build_approved_sequence(
                    inputs, "custom", work,
                    contracts["sequence_plan"], contracts["source_manifest"],
                    contracts["transition_plan"],
                    contracts["transition_manifest"],
                    contracts["edit_policy"],
                )
                output_facts = daemon._probe_sequence_source(output)

            execution = [
                (argv, kwargs) for argv, kwargs in calls
                if "-filter_complex_script" in argv
            ]
            self.assertEqual(len(execution), 1)
            argv, kwargs = execution[0]
            self.assertIs(kwargs.get("shell"), False)
            self.assertNotIn("-filter_complex", argv)
            self.assertEqual(Path(kwargs["cwd"]), work)
            self.assertEqual(
                receipt["schema_version"],
                "autoeditor-sequence-handoff-receipt/v2",
            )
            self.assertEqual(receipt["source_total_duration_ms"], 5_000)
            self.assertEqual(receipt["total_duration_ms"], 4_800)
            self.assertEqual(receipt["hard_cut_boundaries_ms"], [])
            self.assertEqual(receipt["boundaries"], [{
                "boundary_index": 0,
                "kind": "cross_dissolve",
                "output_start_ms": 2_300,
                "output_end_ms": 2_500,
                "overlap_ms": 200,
            }])
            self.assertLessEqual(abs(output_facts["duration_ms"] - 4_800), 100)
            self.assertEqual(receipt["output_sha256"], _sha256(output))
            self.assertEqual(
                receipt["transition_artifact_receipt"]["output_sha256"],
                receipt["output_sha256"],
            )
            public_executor = receipt["transition_executor_receipt"]
            self.assertEqual(
                public_executor["schema_version"],
                daemon.TRANSITION_RENDER_PUBLIC_RECEIPT_SCHEMA,
            )
            self.assertEqual(public_executor["output_file"], output.name)
            self.assertNotIn("artifact_target", public_executor)
            self.assertEqual(
                set(public_executor),
                daemon._TRANSITION_RENDER_PUBLIC_RECEIPT_KEYS,
            )
            self.assertEqual(
                receipt["transition_artifact_receipt"][
                    "transition_executor_receipt_sha256"
                ],
                receipt["transition_executor_receipt_sha256"],
            )
            wire = json.dumps(
                receipt, ensure_ascii=True, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            self.assertNotIn("artifact_target", wire)
            self.assertNotIn("\\", wire)
            self.assertNotIn("first & hostile", wire)
            self.assertNotIn("second [hostile]", wire)
            self.assertNotIn(str(root), wire)
            receipt_file = work / "approved-transition-handoff.json"
            receipt_file.write_text(
                json.dumps(receipt, ensure_ascii=True, sort_keys=True,
                           separators=(",", ":"), allow_nan=False),
                encoding="utf-8",
            )
            with mock.patch.object(pipeline, "FFPROBE", ffprobe):
                validated = pipeline.validate_sequence_handoff_receipt(
                    receipt_file, output, contracts["edit_policy"],
                    _authority_carrier(contracts),
                )
            self.assertEqual(validated, receipt)

            mutations = []
            changed = copy.deepcopy(receipt)
            changed["boundaries"][0]["overlap_ms"] += 1
            mutations.append(changed)
            changed = copy.deepcopy(receipt)
            changed["transition_topology_sha256"] = "0" * 64
            mutations.append(changed)
            changed = copy.deepcopy(receipt)
            changed["transition_artifact_receipt"][
                "transition_executor_receipt_sha256"
            ] = "0" * 64
            mutations.append(changed)
            changed = copy.deepcopy(receipt)
            changed["transition_topology"][0]["video_primitive"] = (
                "xfade=transition=fade:duration=0.200:offset=0.000"
            )
            changed["transition_topology_sha256"] = daemon._canonical_sha256(
                changed["transition_topology"]
            )
            changed["transition_executor_receipt"]["topology_sha256"] = (
                changed["transition_topology_sha256"]
            )
            changed["transition_executor_receipt_sha256"] = (
                daemon._canonical_sha256(changed["transition_executor_receipt"])
            )
            changed["transition_artifact_receipt"][
                "transition_topology_sha256"
            ] = changed["transition_topology_sha256"]
            changed["transition_artifact_receipt"][
                "transition_executor_receipt_sha256"
            ] = changed["transition_executor_receipt_sha256"]
            changed["transition_artifact_receipt_sha256"] = (
                daemon._canonical_sha256(changed["transition_artifact_receipt"])
            )
            mutations.append(changed)
            changed = copy.deepcopy(receipt)
            changed["transition_topology"][0]["output_boundary_ms"] += 1
            changed["transition_topology_sha256"] = daemon._canonical_sha256(
                changed["transition_topology"]
            )
            changed["transition_executor_receipt"]["topology_sha256"] = (
                changed["transition_topology_sha256"]
            )
            changed["transition_executor_receipt_sha256"] = (
                daemon._canonical_sha256(changed["transition_executor_receipt"])
            )
            changed["transition_artifact_receipt"][
                "transition_topology_sha256"
            ] = changed["transition_topology_sha256"]
            changed["transition_artifact_receipt"][
                "transition_executor_receipt_sha256"
            ] = changed["transition_executor_receipt_sha256"]
            changed["transition_artifact_receipt_sha256"] = (
                daemon._canonical_sha256(changed["transition_artifact_receipt"])
            )
            mutations.append(changed)
            for index, candidate in enumerate(mutations):
                with self.subTest(pipeline_mutation=index):
                    receipt_file.write_text(
                        json.dumps(candidate, ensure_ascii=True,
                                   sort_keys=True, separators=(",", ":"),
                                   allow_nan=False),
                        encoding="utf-8",
                    )
                    with mock.patch.object(pipeline, "FFPROBE", ffprobe):
                        with self.assertRaisesRegex(
                                ValueError, "approved sequence receipt is invalid"):
                            pipeline.validate_sequence_handoff_receipt(
                                receipt_file, output, contracts["edit_policy"],
                                _authority_carrier(contracts),
                            )


if __name__ == "__main__":
    unittest.main()
