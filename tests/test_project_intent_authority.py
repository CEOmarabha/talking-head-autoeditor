from __future__ import annotations

import copy
import hashlib
import hmac
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autoeditor.edit_policy import CAPABILITIES, edit_policy_sha256
from autoeditor.project_intent_policy_bridge import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    CAPABILITY_MANIFEST_SOURCE,
    PROJECT_INTENT_SCHEMA_VERSION,
    resolve_project_intent_policy,
    validate_capability_manifest,
    validate_project_intent,
)

_ROOT = Path(__file__).resolve().parents[1]
_DAEMON_SPEC = importlib.util.spec_from_file_location(
    "project_intent_authority_daemon",
    _ROOT / "packaging" / "helper_daemon_entry.py",
)
assert _DAEMON_SPEC is not None and _DAEMON_SPEC.loader is not None
daemon = importlib.util.module_from_spec(_DAEMON_SPEC)
_DAEMON_SPEC.loader.exec_module(daemon)


def project_intent() -> dict:
    return {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": "dialogue_talking_head",
        "delivery": {"platform": "youtube", "aspect": "16:9"},
        "target_duration": {"min_ms": 30_000, "max_ms": 45_000},
        "preferences": {
            "captions": {"enabled": True, "preference": "auto"},
            "graphics": {"enabled": True, "preference": "auto"},
            "music": {"enabled": True, "preference": "auto"},
            "sfx": {"enabled": True, "preference": "auto"},
            "transitions": {"enabled": True, "preference": "auto"},
        },
    }


def capability_manifest() -> dict:
    return {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": "a" * 64,
        "available_capabilities": sorted(CAPABILITIES),
    }


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def authority(identifier: str, key: str, proposal: dict) -> dict:
    project = validate_project_intent(project_intent())
    manifest = validate_capability_manifest(capability_manifest())
    policy = resolve_project_intent_policy(project, manifest)
    unsigned = {
        "schema_version": daemon.PROJECT_INTENT_AUTHORITY_SCHEMA_VERSION,
        "authorization_id": identifier,
        "approved_proposal_sha256": digest(proposal),
        "project_intent": project,
        "project_intent_sha256": digest(project),
        "edit_policy": policy,
        "edit_policy_sha256": edit_policy_sha256(policy),
        "capability_manifest": manifest,
        "capability_manifest_sha256": digest(manifest),
    }
    return {
        **unsigned,
        "authorization_hmac_sha256": hmac.new(
            bytes.fromhex(key), canonical(unsigned).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
    }


class ProjectIntentAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(
            prefix="project-intent-authority-"
        )
        root = Path(self.directory.name)
        self.video = root / "input.mp4"
        self.video.write_bytes(b"video")
        self.output = root / "output"
        self.output.mkdir()
        self.key = "2" * 64
        daemon._CONSUMED_PROJECT_INTENT_AUTHORIZATIONS.clear()

    def tearDown(self) -> None:
        daemon._CONSUMED_PROJECT_INTENT_AUTHORIZATIONS.clear()
        self.directory.cleanup()

    def request(self, *, identifier: str = "1" * 32,
                include_intent: bool = True,
                include_authority: bool = True) -> dict:
        proposal: dict = {
            "summary": "Use the approved expert policy.",
            "operations": [{"op": "set_edit_style", "style": "long"}],
        }
        if include_intent:
            proposal["projectIntent"] = project_intent()
        value = {
            "inputs": [str(self.video)],
            "outputDir": str(self.output),
            "projectType": "long",
            "script": "Approved script",
            "cachedTranscript": "",
            "creativeBrief": "",
            "creativeBriefSha256": "",
            "visionAttempt": 0,
            "proposal": proposal,
        }
        if include_authority:
            value["projectIntentAuthority"] = authority(
                identifier, self.key, proposal
            )
        return value

    def validate(self, value: dict) -> dict:
        with mock.patch.dict(os.environ, {
            "AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY": self.key,
        }, clear=False):
            return daemon._local_render_request(value)

    def test_absent_intent_preserves_the_legacy_request(self) -> None:
        value = self.request(include_intent=False, include_authority=False)
        clean = daemon._local_render_request(value)
        self.assertIsNone(clean["project_intent_authority"])
        self.assertEqual(clean["proposal"], value["proposal"])

    def test_rejects_omission_and_unapproved_injection(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing its trusted authority"):
            daemon._local_render_request(
                self.request(include_authority=False)
            )
        with self.assertRaisesRegex(ValueError, "without an approved"):
            self.validate(self.request(include_intent=False))

    def test_validates_exact_hashes_policy_manifest_signature_and_replay(self) -> None:
        raw = self.request()
        self.assertEqual({
            "proposal": raw["projectIntentAuthority"][
                "approved_proposal_sha256"
            ],
            "project": raw["projectIntentAuthority"]["project_intent_sha256"],
            "manifest": raw["projectIntentAuthority"][
                "capability_manifest_sha256"
            ],
            "policy": raw["projectIntentAuthority"]["edit_policy_sha256"],
            "hmac": raw["projectIntentAuthority"][
                "authorization_hmac_sha256"
            ],
        }, {
            "proposal": (
                "e3b80212df90462086de382506bc8bf5ca644a2418fe41e5a52b260ed20eccdd"
            ),
            "project": "99c128648be416902001bebfd42c04510176bed773f168f4a49d062bb6377878",
            "manifest": (
                "5611d54d339631516875844a7fad0233593d6badd87a2d4818eb060f9955a62c"
            ),
            "policy": (
                "1e97411c7109bbf98cdd4a15d133a9569321a846958f537a705bd39a7a769ff8"
            ),
            "hmac": (
                "ba74e907635c3cca57c45576a8a2afe43b087b2433ca8b45bd32e233d1482a48"
            ),
        })
        clean = self.validate(raw)
        self.assertEqual(
            clean["project_intent_authority"]["project_intent"],
            project_intent(),
        )
        with self.assertRaisesRegex(ValueError, "already consumed"):
            self.validate(self.request())

        daemon._CONSUMED_PROJECT_INTENT_AUTHORIZATIONS.clear()
        tamper = self.request(identifier="3" * 32)
        tamper["projectIntentAuthority"]["edit_policy_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "policy digest does not match"):
            self.validate(tamper)

        tamper = self.request(identifier="4" * 32)
        tamper["projectIntentAuthority"]["authorization_hmac_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "signature does not match"):
            self.validate(tamper)

        tamper = self.request(identifier="5" * 32)
        tamper["proposal"]["projectIntent"]["delivery"]["aspect"] = "9:16"
        with self.assertRaisesRegex(ValueError, "does not match the approved|does not bind"):
            self.validate(tamper)

        tamper = self.request(identifier="8" * 32)
        tamper["proposal"]["summary"] = "Swapped after authorization."
        with self.assertRaisesRegex(ValueError, "does not bind the exact approved"):
            self.validate(tamper)

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "key is unavailable"):
                daemon._local_render_request(
                    self.request(identifier="6" * 32)
                )

    def test_private_engine_envelope_is_exact_tamper_evident_and_cleared(self) -> None:
        clean = self.validate(self.request(identifier="7" * 32))
        work = Path(self.directory.name) / "private-work"
        work.mkdir()
        binding = daemon._open_project_intent_engine_envelope(
            work, clean["project_intent_authority"],
            clean["approved_transition_carrier"],
        )
        self.assertIsNotNone(binding)
        path = binding["path"]
        try:
            payload = path.read_bytes()
            self.assertFalse(payload.endswith(b"\n"))
            self.assertNotIn(b"authorization_hmac_sha256", payload)
            envelope = json.loads(payload)
            self.assertEqual(
                envelope["approved_proposal_sha256"],
                clean["project_intent_authority"][
                    "approved_proposal_sha256"
                ],
            )
            self.assertEqual(
                envelope["approved_transition_carrier"],
                clean["approved_transition_carrier"],
            )
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(), binding["sha256"]
            )
            daemon._verify_project_intent_engine_envelope(binding)
            os.lseek(binding["descriptor"], 0, os.SEEK_SET)
            os.write(binding["descriptor"], b"!")
            os.fsync(binding["descriptor"])
            with self.assertRaisesRegex(RuntimeError, "changed during rendering"):
                daemon._verify_project_intent_engine_envelope(binding)
        finally:
            daemon._clear_project_intent_engine_envelope(binding)
        self.assertFalse(path.exists())

    def test_every_engine_child_omits_the_daemon_authority_key(self) -> None:
        engine = Path(self.directory.name) / "autoeditor-engine.exe"
        engine.write_bytes(b"engine")
        captured_environments: list[dict[str, str]] = []

        class Process:
            stdout: list[str] = []

            @staticmethod
            def wait() -> int:
                return 0

        def popen(*_args, **kwargs):
            captured_environments.append(dict(kwargs["env"]))
            return Process()

        environment = {
            "AUTOEDITOR_ENGINE": str(engine),
            "AUTOEDITOR_INSTALL_ROOT": self.directory.name,
            "AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY": self.key,
        }
        with mock.patch.dict(os.environ, environment, clear=False), \
                mock.patch.object(daemon.subprocess, "Popen", side_effect=popen):
            # The daemon must still retain the key long enough to authenticate
            # the exact approved request before spawning either child.
            clean = daemon._local_render_request(
                self.request(identifier="9" * 32)
            )
            self.assertIsNotNone(clean["project_intent_authority"])
            self.assertEqual(
                os.environ["AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY"], self.key
            )
            self.assertEqual(
                daemon._run_local_engine([
                    str(self.video), "--transcribe-only", "--out",
                    str(self.output),
                ])[0],
                0,
            )
            self.assertEqual(
                daemon._run_local_engine([
                    str(self.video), "--out", str(self.output),
                    "--project-intent-authority", "private-envelope.json",
                    "--project-intent-authority-sha256", "a" * 64,
                ])[0],
                0,
            )
            self.assertEqual(
                os.environ["AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY"], self.key
            )
        self.assertEqual(len(captured_environments), 2)
        for child_environment in captured_environments:
            self.assertNotIn(
                "AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY", child_environment
            )

    def test_authorized_request_reaches_only_final_engine_with_private_envelope(self) -> None:
        value = self.request(identifier="7" * 32)
        value["script"] = ""
        pending = self.output / "pending-output.mp4"
        final = self.output / "finished-output.mp4"
        captured: list[list[str]] = []

        def run_engine(args: list[str]) -> tuple[int, dict]:
            captured.append(list(args))
            if "--transcribe-only" in args:
                self.assertNotIn("--project-intent-authority", args)
                transcript_dir = Path(args[args.index("--out") + 1])
                transcript_dir.mkdir()
                (transcript_dir / "TRANSCRIPT.txt").write_text(
                    "Measured transcript", encoding="utf-8"
                )
                return 0, None
            authority_index = args.index("--project-intent-authority")
            authority_path = Path(args[authority_index + 1])
            digest_index = args.index("--project-intent-authority-sha256")
            self.assertTrue(authority_path.is_absolute())
            self.assertTrue(authority_path.is_file())
            payload = authority_path.read_bytes()
            self.assertFalse(payload.endswith(b"\n"))
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(), args[digest_index + 1]
            )
            self.assertNotIn(b"authorization_hmac_sha256", payload)
            envelope = json.loads(payload)
            self.assertEqual(
                envelope["approved_proposal_sha256"],
                value["projectIntentAuthority"][
                    "approved_proposal_sha256"
                ],
            )
            self.assertIsNone(envelope["approved_transition_carrier"])
            pending.write_bytes(b"finished-video")
            return 0, {
                "outputs": {"horizontal": str(pending)},
                "final_outputs": {"horizontal": str(final)},
                "qa_report": "",
                "qa_pass": True,
            }

        with mock.patch.dict(os.environ, {
            "AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY": self.key,
            "DEEPSEEK_API_KEY": "saved-key",
        }, clear=False), mock.patch.object(
            daemon, "_read_local_request", return_value=copy.deepcopy(value)
        ), mock.patch.object(daemon, "_run_local_engine") as engine_mock:
            engine_mock.side_effect = run_engine
            self.assertEqual(daemon.local_render(), 0)
        self.assertEqual(len(captured), 2)
        self.assertIn("--transcribe-only", captured[0])
        self.assertNotIn("--project-intent-authority", captured[0])
        self.assertNotIn("--transcribe-only", captured[1])
        authority_path = Path(captured[1][
            captured[1].index("--project-intent-authority") + 1
        ])
        self.assertFalse(authority_path.exists())


if __name__ == "__main__":
    unittest.main()
