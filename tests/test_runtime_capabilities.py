from __future__ import annotations

import copy
import hashlib
import json
import unittest

from autoeditor.edit_policy import CAPABILITIES
from autoeditor.project_intent_policy_bridge import validate_capability_manifest
from autoeditor.runtime_capabilities import (
    CAPABILITY_CHECK_IDS,
    CAPABILITY_CHECK_MAPPING,
    CHECK_CONTRACT_SHA256,
    CHECK_FIXTURE_SHA256,
    EXPECTED_FIXTURE_SET_SHA256,
    HONEST_RUNTIME_CAPABILITIES,
    MAX_EXECUTABLES,
    RUNTIME_CAPABILITY_PROBE_PRODUCER,
    RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION,
    TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION,
    TRUSTED_CAPABILITY_MANIFEST_SOURCE,
    RuntimeCapabilityError,
    build_runtime_capability_probe_receipt,
    canonical_runtime_capability_probe_receipt_json,
    derive_trusted_capability_manifest,
    runtime_capability_probe_receipt_sha256,
    runtime_manifest_sha256,
    validate_runtime_capability_probe_receipt,
)


def result_digest(check_id: str) -> str:
    return hashlib.sha256(f"probe-result/{check_id}".encode("ascii")).hexdigest()


def executables() -> list[dict[str, str]]:
    return [
        {"name": "ffmpeg", "sha256": hashlib.sha256(b"ffmpeg").hexdigest()},
        {"name": "ffprobe", "sha256": hashlib.sha256(b"ffprobe").hexdigest()},
        {"name": "python", "sha256": hashlib.sha256(b"python").hexdigest()},
    ]


def check_results(*, failed: set[str] | None = None) -> dict[str, dict[str, str]]:
    failures = failed or set()
    return {
        check_id: {
            "result_receipt_sha256": result_digest(check_id),
            "status": "fail" if check_id in failures else "pass",
        }
        for check_id in CAPABILITY_CHECK_IDS
    }


def receipt(*, failed: set[str] | None = None) -> dict:
    return build_runtime_capability_probe_receipt(
        platform="win32",
        architecture="x64",
        executables=executables(),
        check_results=check_results(failed=failed),
    )


class RuntimeCapabilityReceiptTests(unittest.TestCase):
    def test_honest_vocabulary_and_fixed_mapping_match_edit_policy(self):
        expected = {
            "artifact_receipts",
            "audio_crossfades",
            "audio_quality_analysis",
            "caption_rendering",
            "chart_rendering",
            "color_normalization",
            "cross_dissolves",
            "dialogue_cleanup",
            "graphic_rendering",
            "hard_cuts",
            "loudness_normalization",
            "motion_quality_analysis",
            "project_generated_music",
            "project_generated_sfx",
            "scene_detection",
            "speech_transcription",
            "visual_quality_analysis",
            "word_timestamps",
        }
        self.assertEqual(HONEST_RUNTIME_CAPABILITIES, expected)
        self.assertLess(HONEST_RUNTIME_CAPABILITIES, CAPABILITIES)
        self.assertEqual(CAPABILITY_CHECK_IDS, tuple(sorted(expected)))
        self.assertEqual(dict(CAPABILITY_CHECK_MAPPING), {name: name for name in sorted(expected)})

    def test_builder_fills_only_static_mappings_and_hash_bindings(self):
        value = receipt()
        self.assertEqual(
            set(value),
            {"schema_version", "producer", "runtime", "fixture_set_sha256", "checks"},
        )
        self.assertEqual(
            value["schema_version"], RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION
        )
        self.assertEqual(value["producer"], RUNTIME_CAPABILITY_PROBE_PRODUCER)
        self.assertEqual(value["fixture_set_sha256"], EXPECTED_FIXTURE_SET_SHA256)
        self.assertEqual(
            value["runtime"]["runtime_manifest_sha256"],
            runtime_manifest_sha256("win32", "x64", executables()),
        )
        self.assertEqual([item["id"] for item in value["checks"]], list(CAPABILITY_CHECK_IDS))
        for item in value["checks"]:
            self.assertEqual(item["contract_sha256"], CHECK_CONTRACT_SHA256[item["id"]])
            self.assertEqual(item["fixture_sha256"], CHECK_FIXTURE_SHA256[item["id"]])

    def test_canonical_order_and_hash_match_independent_json_calculation(self):
        value = receipt(failed={"scene_detection"})
        expected_json = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.assertEqual(canonical_runtime_capability_probe_receipt_json(value), expected_json)
        self.assertEqual(
            runtime_capability_probe_receipt_sha256(value),
            hashlib.sha256(expected_json.encode("utf-8")).hexdigest(),
        )

    def test_validator_detaches_every_mutable_container(self):
        raw = receipt()
        clean = validate_runtime_capability_probe_receipt(raw)
        raw["runtime"]["executables"][0]["sha256"] = "0" * 64
        raw["checks"][0]["status"] = "fail"
        self.assertNotEqual(clean, raw)
        self.assertEqual(clean["checks"][0]["status"], "pass")
        self.assertNotEqual(clean["runtime"]["executables"][0]["sha256"], "0" * 64)

    def test_rejects_unsorted_or_duplicate_executables_and_checks(self):
        cases = []
        candidate = receipt()
        candidate["runtime"]["executables"].reverse()
        candidate["runtime"]["runtime_manifest_sha256"] = runtime_manifest_sha256(
            "win32",
            "x64",
            sorted(
                candidate["runtime"]["executables"], key=lambda item: item["name"]
            ),
        )
        cases.append(candidate)
        candidate = receipt()
        candidate["runtime"]["executables"][1]["name"] = (
            candidate["runtime"]["executables"][0]["name"]
        )
        cases.append(candidate)
        candidate = receipt()
        candidate["checks"].reverse()
        cases.append(candidate)
        candidate = receipt()
        candidate["checks"][1] = copy.deepcopy(candidate["checks"][0])
        cases.append(candidate)
        candidate = receipt()
        candidate["checks"].pop()
        cases.append(candidate)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(RuntimeCapabilityError):
                    validate_runtime_capability_probe_receipt(candidate)

    def test_rejects_hash_drift_at_every_static_binding(self):
        mutations = []
        candidate = receipt()
        candidate["runtime"]["runtime_manifest_sha256"] = "0" * 64
        mutations.append(candidate)
        candidate = receipt()
        candidate["fixture_set_sha256"] = "0" * 64
        mutations.append(candidate)
        candidate = receipt()
        candidate["checks"][0]["contract_sha256"] = "0" * 64
        mutations.append(candidate)
        candidate = receipt()
        candidate["checks"][0]["fixture_sha256"] = "0" * 64
        mutations.append(candidate)
        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(RuntimeCapabilityError, "does not match"):
                    validate_runtime_capability_probe_receipt(candidate)

    def test_rejects_unknown_checks_capability_claims_and_caller_mappings(self):
        mutations = []
        candidate = receipt()
        candidate["checks"][0]["id"] = "telepathy"
        mutations.append(candidate)
        candidate = receipt()
        candidate["available_capabilities"] = ["hard_cuts"]
        mutations.append(candidate)
        candidate = receipt()
        candidate["capability_mapping"] = {"hard_cuts": "telepathy"}
        mutations.append(candidate)
        candidate = receipt()
        candidate["checks"][0]["capability"] = "telepathy"
        mutations.append(candidate)
        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(RuntimeCapabilityError):
                    validate_runtime_capability_probe_receipt(candidate)

    def test_rejects_wrong_types_versions_producer_status_and_digest_case(self):
        mutations = []
        candidate = receipt()
        candidate["schema_version"] = "autoeditor-runtime-capability-probe-receipt/v2"
        mutations.append(candidate)
        candidate = receipt()
        candidate["producer"] = "model-claim"
        mutations.append(candidate)
        candidate = receipt()
        candidate["runtime"]["platform"] = "windows"
        mutations.append(candidate)
        candidate = receipt()
        candidate["runtime"]["architecture"] = "amd64"
        mutations.append(candidate)
        candidate = receipt()
        candidate["checks"][0]["status"] = True
        mutations.append(candidate)
        candidate = receipt()
        candidate["checks"][0]["status"] = "unknown"
        mutations.append(candidate)
        candidate = receipt()
        candidate["checks"][0]["result_receipt_sha256"] = "A" * 64
        mutations.append(candidate)
        candidate = receipt()
        candidate["runtime"]["executables"] = "ffmpeg"
        mutations.append(candidate)
        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(RuntimeCapabilityError):
                    validate_runtime_capability_probe_receipt(candidate)

    def test_bounded_executable_count_and_names(self):
        self.assertEqual(MAX_EXECUTABLES, 32)
        for count in (18, 19, 24, 25, 31, 32):
            accepted = [
                {
                    "name": f"tool-{index:02d}",
                    "sha256": hashlib.sha256(str(index).encode()).hexdigest(),
                }
                for index in range(count)
            ]
            with self.subTest(accepted_count=count):
                built = build_runtime_capability_probe_receipt(
                    platform="win32",
                    architecture="x64",
                    executables=accepted,
                    check_results=check_results(),
                )
                self.assertEqual(len(built["runtime"]["executables"]), count)
        with self.assertRaises(RuntimeCapabilityError):
            build_runtime_capability_probe_receipt(
                platform="win32",
                architecture="x64",
                executables=[],
                check_results=check_results(),
            )
        too_many = [
            {
                "name": f"tool-{index:02d}",
                "sha256": hashlib.sha256(str(index).encode()).hexdigest(),
            }
            for index in range(MAX_EXECUTABLES + 1)
        ]
        with self.assertRaises(RuntimeCapabilityError):
            build_runtime_capability_probe_receipt(
                platform="win32",
                architecture="x64",
                executables=too_many,
                check_results=check_results(),
            )
        invalid_name = executables()
        invalid_name[0]["name"] = "../ffmpeg.exe"
        with self.assertRaises(RuntimeCapabilityError):
            build_runtime_capability_probe_receipt(
                platform="win32",
                architecture="x64",
                executables=invalid_name,
                check_results=check_results(),
            )

    def test_builder_requires_every_result_and_never_defaults_to_pass(self):
        incomplete = check_results()
        del incomplete[CAPABILITY_CHECK_IDS[0]]
        with self.assertRaisesRegex(RuntimeCapabilityError, "missing"):
            build_runtime_capability_probe_receipt(
                platform="win32",
                architecture="x64",
                executables=executables(),
                check_results=incomplete,
            )
        forged = check_results()
        forged["telepathy"] = {
            "result_receipt_sha256": "0" * 64,
            "status": "pass",
        }
        with self.assertRaisesRegex(RuntimeCapabilityError, "unsupported"):
            build_runtime_capability_probe_receipt(
                platform="win32",
                architecture="x64",
                executables=executables(),
                check_results=forged,
            )


class TrustedManifestDerivationTests(unittest.TestCase):
    def test_manifest_is_derived_only_from_passing_fixed_checks(self):
        failed = {"chart_rendering", "scene_detection", "word_timestamps"}
        value = receipt(failed=failed)
        manifest = derive_trusted_capability_manifest(value)
        self.assertEqual(
            manifest,
            {
                "schema_version": TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION,
                "source": TRUSTED_CAPABILITY_MANIFEST_SOURCE,
                "probe_receipt_sha256": runtime_capability_probe_receipt_sha256(value),
                "available_capabilities": sorted(HONEST_RUNTIME_CAPABILITIES - failed),
            },
        )
        self.assertEqual(validate_capability_manifest(manifest), manifest)

    def test_failed_checks_keep_valid_receipts_but_unlock_nothing(self):
        value = receipt(failed=set(CAPABILITY_CHECK_IDS))
        clean = validate_runtime_capability_probe_receipt(value)
        self.assertTrue(all(item["status"] == "fail" for item in clean["checks"]))
        self.assertEqual(
            derive_trusted_capability_manifest(value)["available_capabilities"], []
        )

    def test_mutations_invalidate_bindings_or_change_manifest_receipt_hash(self):
        original = receipt()
        original_manifest = derive_trusted_capability_manifest(original)

        status_mutation = copy.deepcopy(original)
        status_mutation["checks"][0]["status"] = "fail"
        changed_manifest = derive_trusted_capability_manifest(status_mutation)
        self.assertNotEqual(
            changed_manifest["probe_receipt_sha256"],
            original_manifest["probe_receipt_sha256"],
        )
        self.assertNotIn(
            CAPABILITY_CHECK_MAPPING[CAPABILITY_CHECK_IDS[0]],
            changed_manifest["available_capabilities"],
        )

        result_mutation = copy.deepcopy(original)
        result_mutation["checks"][0]["result_receipt_sha256"] = "0" * 64
        self.assertNotEqual(
            derive_trusted_capability_manifest(result_mutation)["probe_receipt_sha256"],
            original_manifest["probe_receipt_sha256"],
        )

        executable_mutation = copy.deepcopy(original)
        executable_mutation["runtime"]["executables"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeCapabilityError, "runtime manifest"):
            derive_trusted_capability_manifest(executable_mutation)

    def test_derive_rejects_raw_available_capability_injection(self):
        candidate = receipt(failed={"hard_cuts"})
        candidate["available_capabilities"] = sorted(HONEST_RUNTIME_CAPABILITIES)
        with self.assertRaises(RuntimeCapabilityError):
            derive_trusted_capability_manifest(candidate)


if __name__ == "__main__":
    unittest.main()
