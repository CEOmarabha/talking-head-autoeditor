"""Closed receipt contract for trusted local runtime capability probes.

This module is deliberately a receipt *contract*, not a capability detector.
It does not run probes and it never accepts a caller-provided capability list
or check-to-capability mapping.  A trusted local producer must run every fixed
check, retain each detailed result receipt, and pass only its digest and status
to :func:`build_runtime_capability_probe_receipt`.

Validation proves schema, canonical ordering, static contract/fixture binding,
and runtime-manifest binding.  It cannot authenticate an arbitrary dictionary
as having come from the trusted process; callers must load the receipt from the
local probe boundary rather than from user, model, or remote API input.
"""
from __future__ import annotations

import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from .edit_policy import CAPABILITIES


RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-runtime-capability-probe-receipt/v1"
)
RUNTIME_CAPABILITY_PROBE_PRODUCER = "autoeditor-local-runtime-probe/v1"
TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION = (
    "autoeditor-trusted-capability-manifest/v1"
)
TRUSTED_CAPABILITY_MANIFEST_SOURCE = RUNTIME_CAPABILITY_PROBE_PRODUCER

RUNTIME_PLATFORMS = frozenset({"darwin", "linux", "win32"})
RUNTIME_ARCHITECTURES = frozenset({"arm64", "x64"})
CHECK_STATUSES = frozenset({"fail", "pass"})
MAX_EXECUTABLES = 32

# Check identifiers and capability identifiers intentionally share names in
# v1.  The mapping remains explicit so no serialized field can choose which
# capability a passing check unlocks, and a future version can split checks
# without changing the trust rule.
_CHECK_TO_CAPABILITY = {
    "artifact_receipts": "artifact_receipts",
    "audio_crossfades": "audio_crossfades",
    "audio_quality_analysis": "audio_quality_analysis",
    "caption_rendering": "caption_rendering",
    "chart_rendering": "chart_rendering",
    "color_normalization": "color_normalization",
    "cross_dissolves": "cross_dissolves",
    "dialogue_cleanup": "dialogue_cleanup",
    "graphic_rendering": "graphic_rendering",
    "hard_cuts": "hard_cuts",
    "loudness_normalization": "loudness_normalization",
    "motion_quality_analysis": "motion_quality_analysis",
    "project_generated_music": "project_generated_music",
    "project_generated_sfx": "project_generated_sfx",
    "scene_detection": "scene_detection",
    "speech_transcription": "speech_transcription",
    "visual_quality_analysis": "visual_quality_analysis",
    "word_timestamps": "word_timestamps",
}
CAPABILITY_CHECK_MAPPING: Mapping[str, str] = MappingProxyType(
    dict(sorted(_CHECK_TO_CAPABILITY.items()))
)
CAPABILITY_CHECK_IDS = tuple(CAPABILITY_CHECK_MAPPING)
HONEST_RUNTIME_CAPABILITIES = frozenset(CAPABILITY_CHECK_MAPPING.values())

if not HONEST_RUNTIME_CAPABILITIES < CAPABILITIES:
    raise RuntimeError("runtime capability probe surface drifted from edit-policy/v1")
if len(HONEST_RUNTIME_CAPABILITIES) != len(CAPABILITY_CHECK_MAPPING):
    raise RuntimeError("runtime capability probe checks must map one-to-one in v1")

_ROOT_KEYS = frozenset({
    "schema_version", "producer", "runtime", "fixture_set_sha256", "checks",
})
_RUNTIME_KEYS = frozenset({
    "platform", "architecture", "runtime_manifest_sha256", "executables",
})
_EXECUTABLE_KEYS = frozenset({"name", "sha256"})
_CHECK_KEYS = frozenset({
    "id",
    "contract_sha256",
    "fixture_sha256",
    "result_receipt_sha256",
    "status",
})
_CHECK_RESULT_KEYS = frozenset({"result_receipt_sha256", "status"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_EXECUTABLE_NAME_RE = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")


class RuntimeCapabilityError(ValueError):
    """A capability probe receipt failed its closed contract."""


def _fail(message: str) -> None:
    raise RuntimeCapabilityError(message)


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected, key=str)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unsupported " + ", ".join(str(item) for item in extra))
        _fail(f"{label} has invalid keys ({'; '.join(details)})")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise RuntimeCapabilityError("value is not canonical JSON") from error


def _digest_canonical(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _fixed_contract_digest(check_id: str) -> str:
    payload = f"autoeditor-runtime-capability-check-contract/{check_id}/v1"
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _fixed_fixture_digest(check_id: str) -> str:
    payload = f"autoeditor-runtime-capability-check-fixture/{check_id}/v1"
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


CHECK_CONTRACT_SHA256: Mapping[str, str] = MappingProxyType({
    check_id: _fixed_contract_digest(check_id) for check_id in CAPABILITY_CHECK_IDS
})
CHECK_FIXTURE_SHA256: Mapping[str, str] = MappingProxyType({
    check_id: _fixed_fixture_digest(check_id) for check_id in CAPABILITY_CHECK_IDS
})


def _fixture_set_payload() -> list[dict[str, str]]:
    return [
        {"id": check_id, "fixture_sha256": CHECK_FIXTURE_SHA256[check_id]}
        for check_id in CAPABILITY_CHECK_IDS
    ]


EXPECTED_FIXTURE_SET_SHA256 = _digest_canonical(_fixture_set_payload())


def _lower_sha256(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256")
    return value


def _member(value: object, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(f"{label} is unsupported")
    return value


def _normalize_executables(value: object) -> list[dict[str, str]]:
    if type(value) is not list:
        _fail("runtime.executables must be a sorted list")
    if not 1 <= len(value) <= MAX_EXECUTABLES:
        _fail(f"runtime.executables must contain 1 to {MAX_EXECUTABLES} entries")

    executables = []
    for index, item in enumerate(value):
        raw = _exact_keys(item, _EXECUTABLE_KEYS, f"runtime.executables[{index}]")
        name = raw["name"]
        if type(name) is not str or _EXECUTABLE_NAME_RE.fullmatch(name) is None:
            _fail(
                f"runtime.executables[{index}].name must be a lowercase identifier"
            )
        executables.append({
            "name": name,
            "sha256": _lower_sha256(
                raw["sha256"], f"runtime.executables[{index}].sha256"
            ),
        })

    names = [item["name"] for item in executables]
    if names != sorted(set(names)):
        _fail("runtime.executables must be sorted by unique name")
    return executables


def _runtime_manifest_payload(
    platform: str, architecture: str, executables: list[dict[str, str]]
) -> dict[str, object]:
    return {
        "platform": platform,
        "architecture": architecture,
        "executables": [dict(item) for item in executables],
    }


def runtime_manifest_sha256(
    platform: object, architecture: object, executables: object
) -> str:
    """Hash normalized runtime identity data without the self-referential hash."""

    normalized_platform = _member(platform, RUNTIME_PLATFORMS, "runtime.platform")
    normalized_architecture = _member(
        architecture, RUNTIME_ARCHITECTURES, "runtime.architecture"
    )
    normalized_executables = _normalize_executables(executables)
    return _digest_canonical(
        _runtime_manifest_payload(
            normalized_platform, normalized_architecture, normalized_executables
        )
    )


def validate_runtime_capability_probe_receipt(value: object) -> dict[str, Any]:
    """Validate and detach a complete local probe receipt.

    All v1 checks are mandatory.  A failed check is represented by ``fail``;
    omitting it is not an accepted substitute and cannot create ambiguity
    between "failed", "not run", and "unknown to this producer".
    """

    raw = _exact_keys(value, _ROOT_KEYS, "runtime capability probe receipt")
    if raw["schema_version"] != RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION:
        _fail("runtime capability probe receipt schema_version is unsupported")
    if raw["producer"] != RUNTIME_CAPABILITY_PROBE_PRODUCER:
        _fail("runtime capability probe receipt producer is untrusted")

    raw_runtime = _exact_keys(raw["runtime"], _RUNTIME_KEYS, "runtime")
    platform = _member(raw_runtime["platform"], RUNTIME_PLATFORMS, "runtime.platform")
    architecture = _member(
        raw_runtime["architecture"], RUNTIME_ARCHITECTURES, "runtime.architecture"
    )
    executables = _normalize_executables(raw_runtime["executables"])
    manifest_digest = _lower_sha256(
        raw_runtime["runtime_manifest_sha256"], "runtime.runtime_manifest_sha256"
    )
    expected_manifest_digest = _digest_canonical(
        _runtime_manifest_payload(platform, architecture, executables)
    )
    if manifest_digest != expected_manifest_digest:
        _fail("runtime.runtime_manifest_sha256 does not match the runtime manifest")

    fixture_set_digest = _lower_sha256(
        raw["fixture_set_sha256"], "fixture_set_sha256"
    )
    if fixture_set_digest != EXPECTED_FIXTURE_SET_SHA256:
        _fail("fixture_set_sha256 does not match the fixed v1 fixture set")

    raw_checks = raw["checks"]
    if type(raw_checks) is not list:
        _fail("checks must be a sorted list")
    if len(raw_checks) != len(CAPABILITY_CHECK_IDS):
        _fail(f"checks must contain all {len(CAPABILITY_CHECK_IDS)} v1 checks")

    checks = []
    for index, item in enumerate(raw_checks):
        check = _exact_keys(item, _CHECK_KEYS, f"checks[{index}]")
        check_id = check["id"]
        if type(check_id) is not str or check_id not in CAPABILITY_CHECK_MAPPING:
            _fail(f"checks[{index}].id is unsupported")
        contract_digest = _lower_sha256(
            check["contract_sha256"], f"checks[{index}].contract_sha256"
        )
        if contract_digest != CHECK_CONTRACT_SHA256[check_id]:
            _fail(f"checks[{index}].contract_sha256 does not match {check_id}")
        fixture_digest = _lower_sha256(
            check["fixture_sha256"], f"checks[{index}].fixture_sha256"
        )
        if fixture_digest != CHECK_FIXTURE_SHA256[check_id]:
            _fail(f"checks[{index}].fixture_sha256 does not match {check_id}")
        result_digest = _lower_sha256(
            check["result_receipt_sha256"],
            f"checks[{index}].result_receipt_sha256",
        )
        status = _member(check["status"], CHECK_STATUSES, f"checks[{index}].status")
        checks.append({
            "id": check_id,
            "contract_sha256": contract_digest,
            "fixture_sha256": fixture_digest,
            "result_receipt_sha256": result_digest,
            "status": status,
        })

    check_ids = [check["id"] for check in checks]
    if tuple(check_ids) != CAPABILITY_CHECK_IDS:
        _fail("checks must contain every v1 check once in sorted id order")

    return {
        "schema_version": RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION,
        "producer": RUNTIME_CAPABILITY_PROBE_PRODUCER,
        "runtime": {
            "platform": platform,
            "architecture": architecture,
            "runtime_manifest_sha256": manifest_digest,
            "executables": executables,
        },
        "fixture_set_sha256": fixture_set_digest,
        "checks": checks,
    }


def build_runtime_capability_probe_receipt(
    *,
    platform: object,
    architecture: object,
    executables: object,
    check_results: object,
) -> dict[str, Any]:
    """Build a receipt from already-run trusted probe result records.

    ``check_results`` must contain every fixed check and only the detailed
    result-receipt digest plus ``pass``/``fail`` status.  There is deliberately
    no default success and no caller-controlled capability mapping.
    """

    normalized_platform = _member(platform, RUNTIME_PLATFORMS, "runtime.platform")
    normalized_architecture = _member(
        architecture, RUNTIME_ARCHITECTURES, "runtime.architecture"
    )
    normalized_executables = _normalize_executables(executables)
    if type(check_results) is not dict:
        _fail("check_results must be an object keyed by every v1 check id")
    actual_check_ids = set(check_results)
    expected_check_ids = set(CAPABILITY_CHECK_IDS)
    if actual_check_ids != expected_check_ids:
        missing = sorted(expected_check_ids - actual_check_ids)
        extra = sorted(actual_check_ids - expected_check_ids, key=str)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unsupported " + ", ".join(str(item) for item in extra))
        _fail(f"check_results has invalid check ids ({'; '.join(details)})")

    checks = []
    for check_id in CAPABILITY_CHECK_IDS:
        raw_result = _exact_keys(
            check_results[check_id], _CHECK_RESULT_KEYS, f"check_results.{check_id}"
        )
        checks.append({
            "id": check_id,
            "contract_sha256": CHECK_CONTRACT_SHA256[check_id],
            "fixture_sha256": CHECK_FIXTURE_SHA256[check_id],
            "result_receipt_sha256": _lower_sha256(
                raw_result["result_receipt_sha256"],
                f"check_results.{check_id}.result_receipt_sha256",
            ),
            "status": _member(
                raw_result["status"], CHECK_STATUSES, f"check_results.{check_id}.status"
            ),
        })

    runtime_payload = _runtime_manifest_payload(
        normalized_platform, normalized_architecture, normalized_executables
    )
    return validate_runtime_capability_probe_receipt({
        "schema_version": RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION,
        "producer": RUNTIME_CAPABILITY_PROBE_PRODUCER,
        "runtime": {
            **runtime_payload,
            "runtime_manifest_sha256": _digest_canonical(runtime_payload),
        },
        "fixture_set_sha256": EXPECTED_FIXTURE_SET_SHA256,
        "checks": checks,
    })


def canonical_runtime_capability_probe_receipt_json(value: object) -> str:
    """Return validated key-sorted, whitespace-free ASCII JSON."""

    return _canonical_json(validate_runtime_capability_probe_receipt(value))


def runtime_capability_probe_receipt_sha256(value: object) -> str:
    """Return the SHA-256 digest of the complete validated probe receipt."""

    return hashlib.sha256(
        canonical_runtime_capability_probe_receipt_json(value).encode("utf-8")
    ).hexdigest()


def derive_trusted_capability_manifest(value: object) -> dict[str, Any]:
    """Derive the bridge manifest from fixed mappings and passing checks only."""

    receipt = validate_runtime_capability_probe_receipt(value)
    passed_checks = {
        check["id"] for check in receipt["checks"] if check["status"] == "pass"
    }
    available = sorted(
        CAPABILITY_CHECK_MAPPING[check_id] for check_id in passed_checks
    )
    return {
        "schema_version": TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": TRUSTED_CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": runtime_capability_probe_receipt_sha256(receipt),
        "available_capabilities": available,
    }


__all__ = (
    "RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION",
    "RUNTIME_CAPABILITY_PROBE_PRODUCER",
    "TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION",
    "TRUSTED_CAPABILITY_MANIFEST_SOURCE",
    "RUNTIME_PLATFORMS",
    "RUNTIME_ARCHITECTURES",
    "CHECK_STATUSES",
    "MAX_EXECUTABLES",
    "CAPABILITY_CHECK_MAPPING",
    "CAPABILITY_CHECK_IDS",
    "HONEST_RUNTIME_CAPABILITIES",
    "CHECK_CONTRACT_SHA256",
    "CHECK_FIXTURE_SHA256",
    "EXPECTED_FIXTURE_SET_SHA256",
    "RuntimeCapabilityError",
    "runtime_manifest_sha256",
    "validate_runtime_capability_probe_receipt",
    "build_runtime_capability_probe_receipt",
    "canonical_runtime_capability_probe_receipt_json",
    "runtime_capability_probe_receipt_sha256",
    "derive_trusted_capability_manifest",
)
