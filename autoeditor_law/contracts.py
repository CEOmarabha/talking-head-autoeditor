"""AutoEditor archive, adapter, and evidence-envelope contracts.

This module uses only the Python standard library. It deliberately does not
import Electron, FFmpeg, DeepSeek, or the AutoEditor engine. A future reader
can validate the preservation envelope without resurrecting the 2026 app.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any


CONTRACT_ID = "autoeditor-2034-contract/1"
REGISTRY_SCHEMA_ID = "urn:autoeditor:schema:registry:1"
ARCHIVE_MANIFEST_SCHEMA_ID = "urn:autoeditor:schema:archive-manifest:1"
PLANNER_PROPOSAL_SCHEMA_ID = "urn:autoeditor:schema:planner-proposal:1"
RENDER_REQUEST_SCHEMA_ID = "urn:autoeditor:schema:render-request:1"
RECEIPT_ENVELOPE_SCHEMA_ID = "urn:autoeditor:schema:receipt-envelope:1"
EDIT_INTENT_SCHEMA_ID = "urn:autoeditor:schema:edit-intent:1"

_PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_REGISTRY = _PACKAGE_ROOT / "schema_registry.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_URN = re.compile(r"^urn:autoeditor:[a-z][a-z0-9.-]*:[a-z0-9._:-]+$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_RFC3339_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

_REGISTRY_KEYS = frozenset({
    "schema_id", "contract_id", "registry_version", "schemas",
    "legacy_schema_ids", "identifier_namespaces",
    "retired_ambiguous_capabilities",
})
_SCHEMA_ENTRY_KEYS = frozenset({"id", "path", "sha256", "status", "kind"})
_MANIFEST_KEYS = frozenset({
    "schema_id", "contract_id", "archive_id", "assurance_grade",
    "created_at", "historical_policy_id", "required_schema_ids", "files",
    "attestation",
})
_FILE_KEYS = frozenset({"path", "role", "bytes", "digest"})
_DIGEST_KEYS = frozenset({"algorithm", "value"})
_ATTESTATION_KEYS = frozenset({"status", "signature_file", "anchor"})

_PLANNER_KEYS = frozenset({
    "schema_id", "proposal_id", "created_at", "planner", "inputs",
    "proposal", "qualification",
})
_PLANNER_IDENTITY_KEYS = frozenset({
    "adapter_id", "provider_id", "model_id", "model_revision",
})
_PLANNER_INPUT_KEYS = frozenset({
    "transcript_sha256", "project_intent_sha256", "profile_sha256",
})
_PLANNER_PAYLOAD_KEYS = frozenset({
    "payload_schema_id", "contract_sha256", "payload_sha256", "payload",
})
_QUALIFICATION_KEYS = frozenset({
    "suite_id", "suite_sha256", "adapter_sha256", "pass",
})

_EDIT_INTENT_KEYS = frozenset({
    "schema_id", "timeline_grid", "transcript_sha256", "events",
})
_TIMELINE_GRID_KEYS = frozenset({"unit", "ticks_per_second"})
_RATIONAL_KEYS = frozenset({"numerator", "denominator"})
_INTENT_EVENT_KEYS = frozenset({
    "event_id", "layer", "anchor_quote", "duration_ticks", "parameters",
})
_PUNCH_PARAMETERS = frozenset({"scale_milli", "reason"})
_BROLL_PARAMETERS = frozenset({"query", "family", "reason"})
_GRAPHIC_PARAMETERS = frozenset({"kind", "text", "value", "items", "reason"})
_DIAGRAM_PARAMETERS = frozenset({"template", "title", "items", "reason"})

_RENDER_KEYS = frozenset({
    "schema_id", "request_id", "created_at", "render_adapter_id",
    "archive_manifest_sha256", "planner_proposal_sha256", "edl_sha256",
    "source_map_sha256", "render_profile_sha256", "policy_id", "toolchain",
})
_TOOLCHAIN_KEYS = frozenset({
    "renderer_sha256", "ffmpeg_sha256", "ffprobe_sha256",
})

_RECEIPT_KEYS = frozenset({
    "schema_id", "receipt_id", "created_at", "subject_digest", "capability_id",
    "check_id", "algorithm_id", "payload_schema_id", "policy_id",
    "artifact_contract_id", "result", "evidence", "producer", "payload",
})
_PRODUCER_KEYS = frozenset({"name", "version", "source_sha256"})
_EVIDENCE_KEYS = frozenset({"path", "digest"})

_FILE_ROLES = frozenset({
    "master", "original_source", "canonical_source", "source_map",
    "timeline", "transcript_anchors", "approved_intent", "render_profile",
    "revision_state", "project_state", "asset", "evidence_receipt",
    "evidence_blob", "policy", "specification", "schema", "schema_lock",
    "conformance_fixture", "incident_fixture", "toolchain",
    "build_provenance", "exception", "signature_bundle", "reference_source",
})
_GRADE_REQUIREMENTS = {
    "identity": frozenset({"master"}),
    "historical_record": frozenset({
        "master", "evidence_receipt", "policy", "schema_lock",
        "specification", "build_provenance",
    }),
    "fresh_reverification": frozenset({
        "master", "original_source", "source_map", "timeline",
        "transcript_anchors", "evidence_receipt", "policy", "schema_lock",
        "specification", "conformance_fixture", "build_provenance",
    }),
    "resumption": frozenset({
        "master", "original_source", "source_map", "timeline",
        "transcript_anchors", "approved_intent", "render_profile",
        "revision_state", "project_state", "evidence_receipt", "policy",
        "schema_lock", "specification", "conformance_fixture",
        "build_provenance", "reference_source",
    }),
}


class ContractError(ValueError):
    """A closed contract is malformed or internally inconsistent."""


class UnsupportedSchemaError(ContractError):
    """A required schema has no explicitly supported local reader."""


class ArchiveContractError(ContractError):
    """An archive cannot support its declared assurance grade."""


@dataclass(frozen=True)
class ArchiveVerification:
    archive_id: str
    assurance_grade: str
    manifest_sha256: str
    file_count: int
    master_sha256: str
    required_schema_ids: tuple[str, ...]
    attestation_status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def _exact(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ContractError(f"{label} does not match its closed schema")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ContractError(f"{label} must be a lowercase SHA-256")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ContractError(f"{label} is invalid")
    return value


def _urn(value: object, label: str) -> str:
    if not isinstance(value, str) or _URN.fullmatch(value) is None:
        raise ContractError(f"{label} is invalid")
    return value


def _typed_urn(value: object, namespace: str, label: str) -> str:
    urn = _urn(value, label)
    expected = f"urn:autoeditor:{namespace}:"
    if not urn.startswith(expected):
        raise ContractError(f"{label} must use {expected}")
    return urn


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or _RFC3339_UTC.fullmatch(value) is None:
        raise ContractError(f"{label} must be second-precision UTC RFC3339")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ContractError(f"{label} is not a real UTC timestamp") from exc
    return value


def _relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ContractError(f"{label} is not a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ContractError(f"{label} is not a portable relative path")
    return value


def _read_json(path: Path, label: str, maximum_bytes: int) -> tuple[bytes, Any]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ContractError(f"{label} is unavailable") from exc
    if not path.is_file() or path.is_symlink() or stat.st_size > maximum_bytes:
        raise ContractError(f"{label} is not a bounded regular file")
    raw = path.read_bytes()
    if len(raw) != stat.st_size:
        raise ContractError(f"{label} changed while it was read")
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not valid UTF-8 JSON") from exc


def _stable_file_identity(path: Path) -> tuple[int, str]:
    try:
        with path.open("rb") as handle:
            before = path.stat()
            if not path.is_file() or path.is_symlink():
                raise ArchiveContractError(f"archive file is not regular: {path}")
            digest = hashlib.sha256()
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            after = path.stat()
    except OSError as exc:
        raise ArchiveContractError(f"archive file is unavailable: {path}") from exc
    identity_before = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    )
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise ArchiveContractError(f"archive file changed while read: {path}")
    return before.st_size, digest.hexdigest()


def load_registry(path: Path | str = _DEFAULT_REGISTRY) -> dict[str, Any]:
    registry_path = Path(path).resolve()
    _, value = _read_json(registry_path, "schema registry", 2 * 1024 * 1024)
    registry = _exact(value, _REGISTRY_KEYS, "schema registry")
    if registry["schema_id"] != REGISTRY_SCHEMA_ID:
        raise ContractError("schema registry identifier is unsupported")
    if registry["contract_id"] != CONTRACT_ID or registry["registry_version"] != 1:
        raise ContractError("schema registry contract is unsupported")

    schemas = registry["schemas"]
    if not isinstance(schemas, list) or not schemas:
        raise ContractError("schema registry has no supported schemas")
    seen: set[str] = set()
    registry_root = registry_path.parent
    for index, raw_entry in enumerate(schemas):
        entry = _exact(raw_entry, _SCHEMA_ENTRY_KEYS, f"schema entry {index}")
        schema_id = _urn(entry["id"], f"schema entry {index} id")
        if schema_id in seen:
            raise ContractError(f"schema registry repeats {schema_id}")
        seen.add(schema_id)
        if entry["status"] not in {"current", "frozen"}:
            raise ContractError(f"schema entry {schema_id} has invalid status")
        if entry["kind"] not in {
            "registry", "archive", "adapter", "evidence",
        }:
            raise ContractError(f"schema entry {schema_id} has invalid kind")
        relative = _relative_path(entry["path"], f"schema entry {schema_id} path")
        schema_path = (registry_root / relative).resolve()
        if registry_root not in schema_path.parents:
            raise ContractError(f"schema entry {schema_id} escapes the registry")
        expected = _digest(entry["sha256"], f"schema entry {schema_id} digest")
        schema_bytes, actual_value = _read_json(
            schema_path, f"schema {schema_id}", 1024 * 1024
        )
        if not isinstance(actual_value, dict) or actual_value.get("$id") != schema_id:
            raise ContractError(f"schema file identity does not match {schema_id}")
        if hashlib.sha256(schema_bytes).hexdigest() != expected:
            raise ContractError(f"schema file digest does not match {schema_id}")

    legacy = registry["legacy_schema_ids"]
    if (not isinstance(legacy, list) or legacy != sorted(set(legacy)) or
            any(not isinstance(item, str) or not item for item in legacy)):
        raise ContractError("legacy schema inventory is invalid")
    if seen.intersection(legacy):
        raise ContractError("supported and legacy schema inventories overlap")

    namespaces = registry["identifier_namespaces"]
    if not isinstance(namespaces, dict) or set(namespaces) != {
        "capability_id", "check_id", "algorithm_id", "payload_schema_id",
        "policy_id", "artifact_contract_id",
    } or any(not isinstance(value, str) or not value for value in namespaces.values()):
        raise ContractError("identifier namespace registry is invalid")

    retired = registry["retired_ambiguous_capabilities"]
    if not isinstance(retired, dict) or any(
        not isinstance(key, str) or not isinstance(values, list) or
        len(values) < 2 or any(not isinstance(value, str) for value in values)
        for key, values in retired.items()
    ):
        raise ContractError("retired capability mapping is invalid")
    return registry


def _supported_schemas(registry: dict[str, Any]) -> set[str]:
    return {entry["id"] for entry in registry["schemas"]}


def _require_supported_schema(schema_id: object, registry: dict[str, Any],
                              label: str) -> str:
    value = _urn(schema_id, label)
    if value not in _supported_schemas(registry):
        raise UnsupportedSchemaError(f"{label} is unsupported: {value}")
    return value


def _validate_digest_record(value: object, label: str) -> dict[str, Any]:
    record = _exact(value, _DIGEST_KEYS, label)
    if record["algorithm"] != "sha256":
        raise UnsupportedSchemaError(f"{label} algorithm is unsupported")
    _digest(record["value"], f"{label} value")
    return record


def validate_planner_proposal(value: object,
                              registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    raw = _exact(value, _PLANNER_KEYS, "planner proposal")
    if raw["schema_id"] != PLANNER_PROPOSAL_SCHEMA_ID:
        raise UnsupportedSchemaError("planner proposal schema is unsupported")
    _identifier(raw["proposal_id"], "planner proposal id")
    _timestamp(raw["created_at"], "planner proposal timestamp")

    planner = _exact(raw["planner"], _PLANNER_IDENTITY_KEYS, "planner identity")
    for key, item in planner.items():
        _identifier(item, f"planner {key}")
    inputs = _exact(raw["inputs"], _PLANNER_INPUT_KEYS, "planner inputs")
    for key, item in inputs.items():
        _digest(item, f"planner input {key}")
    proposal = _exact(raw["proposal"], _PLANNER_PAYLOAD_KEYS, "planner payload")
    _require_supported_schema(
        proposal["payload_schema_id"], registry, "planner payload schema"
    )
    _digest(proposal["contract_sha256"], "planner payload contract digest")
    payload_sha256 = _digest(
        proposal["payload_sha256"], "planner payload digest"
    )
    if not isinstance(proposal["payload"], dict):
        raise ContractError("planner payload must be an object")
    if canonical_sha256(proposal["payload"]) != payload_sha256:
        raise ContractError("planner payload digest does not match its bytes")
    if proposal["payload_schema_id"] != EDIT_INTENT_SCHEMA_ID:
        raise UnsupportedSchemaError(
            "planner payload must use the registered edit-intent contract"
        )
    validate_edit_intent(proposal["payload"])

    qualification = _exact(
        raw["qualification"], _QUALIFICATION_KEYS, "planner qualification"
    )
    _urn(qualification["suite_id"], "planner qualification suite")
    _digest(qualification["suite_sha256"], "planner qualification suite digest")
    _digest(qualification["adapter_sha256"], "planner adapter digest")
    if qualification["pass"] is not True:
        raise ContractError("planner adapter is not qualified")
    return json.loads(canonical_json(raw))


def validate_edit_intent(value: object) -> dict[str, Any]:
    """Validate model intent before deterministic timing is compiled.

    A planner receives a declared grid but never controls final cut boundaries.
    Every visual is anchored to spoken words. The compiler owns placement.
    """
    raw = _exact(value, _EDIT_INTENT_KEYS, "edit intent")
    if raw["schema_id"] != EDIT_INTENT_SCHEMA_ID:
        raise UnsupportedSchemaError("edit intent schema is unsupported")
    grid = _exact(raw["timeline_grid"], _TIMELINE_GRID_KEYS, "timeline grid")
    if grid["unit"] != "tick":
        raise ContractError("edit intent timeline unit is unsupported")
    rate = _exact(
        grid["ticks_per_second"], _RATIONAL_KEYS,
        "timeline ticks-per-second rational",
    )
    for key in ("numerator", "denominator"):
        if (not isinstance(rate[key], int) or isinstance(rate[key], bool) or
                rate[key] < 1):
            raise ContractError(f"timeline rational {key} is invalid")
    _digest(raw["transcript_sha256"], "edit intent transcript digest")
    events = raw["events"]
    if not isinstance(events, list):
        raise ContractError("edit intent events must be a list")
    event_ids: set[str] = set()
    for index, value in enumerate(events):
        event = _exact(value, _INTENT_EVENT_KEYS, f"edit intent event {index}")
        event_id = _identifier(event["event_id"], f"edit intent event {index} id")
        if event_id in event_ids:
            raise ContractError("edit intent repeats an event id")
        event_ids.add(event_id)
        layer = event["layer"]
        if layer not in {"punch_in", "broll", "graphic", "diagram"}:
            raise ContractError(f"edit intent event {index} layer is invalid")
        anchor = event["anchor_quote"]
        if not isinstance(anchor, str) or not 5 <= len(anchor.split()) <= 20:
            raise ContractError(
                f"edit intent event {index} needs a 5-to-20-word anchor"
            )
        duration = event["duration_ticks"]
        if (not isinstance(duration, int) or isinstance(duration, bool) or
                duration < 1):
            raise ContractError(
                f"edit intent event {index} duration must use integer ticks"
            )
        parameters = event["parameters"]
        if layer == "punch_in":
            values = _exact(parameters, _PUNCH_PARAMETERS, "punch-in parameters")
            scale = values["scale_milli"]
            if (not isinstance(scale, int) or isinstance(scale, bool) or
                    not 1000 <= scale <= 1500):
                raise ContractError("punch-in scale_milli is invalid")
        elif layer == "broll":
            values = _exact(parameters, _BROLL_PARAMETERS, "b-roll parameters")
            _identifier(values["family"], "b-roll family")
            if not isinstance(values["query"], str) or not values["query"].strip():
                raise ContractError("b-roll query is invalid")
        elif layer == "graphic":
            values = _exact(parameters, _GRAPHIC_PARAMETERS, "graphic parameters")
            if values["kind"] not in {"keyword", "stat", "callout", "bars"}:
                raise ContractError("graphic kind is invalid")
            if not isinstance(values["items"], list) or any(
                not isinstance(item, str) for item in values["items"]
            ):
                raise ContractError("graphic items are invalid")
            for key in ("text", "value"):
                if values[key] is not None and not isinstance(values[key], str):
                    raise ContractError(f"graphic {key} is invalid")
        else:
            values = _exact(parameters, _DIAGRAM_PARAMETERS, "diagram parameters")
            if values["template"] not in {"flow", "steps", "stat"}:
                raise ContractError("diagram template is invalid")
            if not isinstance(values["title"], str) or not values["title"].strip():
                raise ContractError("diagram title is invalid")
            if not isinstance(values["items"], list) or not values["items"] or any(
                not isinstance(item, str) or not item.strip()
                for item in values["items"]
            ):
                raise ContractError("diagram items are invalid")
        if not isinstance(values["reason"], str) or not values["reason"].strip():
            raise ContractError(f"edit intent event {index} reason is invalid")
    return json.loads(canonical_json(raw))


def validate_render_request(value: object) -> dict[str, Any]:
    raw = _exact(value, _RENDER_KEYS, "render request")
    if raw["schema_id"] != RENDER_REQUEST_SCHEMA_ID:
        raise UnsupportedSchemaError("render request schema is unsupported")
    _identifier(raw["request_id"], "render request id")
    _timestamp(raw["created_at"], "render request timestamp")
    _urn(raw["render_adapter_id"], "render adapter id")
    for key in (
        "archive_manifest_sha256", "planner_proposal_sha256", "edl_sha256",
        "source_map_sha256", "render_profile_sha256",
    ):
        _digest(raw[key], f"render request {key}")
    _urn(raw["policy_id"], "render policy id")
    toolchain = _exact(raw["toolchain"], _TOOLCHAIN_KEYS, "render toolchain")
    for key, item in toolchain.items():
        _digest(item, f"render toolchain {key}")
    return json.loads(canonical_json(raw))


def validate_receipt_envelope(value: object,
                              registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    raw = _exact(value, _RECEIPT_KEYS, "receipt envelope")
    if raw["schema_id"] != RECEIPT_ENVELOPE_SCHEMA_ID:
        raise UnsupportedSchemaError("receipt envelope schema is unsupported")
    _identifier(raw["receipt_id"], "receipt id")
    _timestamp(raw["created_at"], "receipt timestamp")
    _validate_digest_record(raw["subject_digest"], "receipt subject digest")
    _typed_urn(raw["capability_id"], "capability", "receipt capability id")
    _typed_urn(raw["check_id"], "check", "receipt check id")
    _typed_urn(raw["algorithm_id"], "algorithm", "receipt algorithm id")
    _require_supported_schema(
        raw["payload_schema_id"], registry, "receipt payload schema"
    )
    _typed_urn(raw["policy_id"], "policy", "receipt policy id")
    _typed_urn(
        raw["artifact_contract_id"], "artifact-contract",
        "receipt artifact contract id",
    )
    if raw["result"] not in {
        "pass", "fail", "unsupported", "accepted_with_exception",
    }:
        raise ContractError("receipt result is invalid")
    if not isinstance(raw["payload"], dict):
        raise ContractError("receipt payload must be an object")
    evidence = raw["evidence"]
    if not isinstance(evidence, list):
        raise ContractError("receipt evidence must be a list")
    for index, item in enumerate(evidence):
        entry = _exact(item, _EVIDENCE_KEYS, f"receipt evidence {index}")
        _relative_path(entry["path"], f"receipt evidence {index} path")
        _validate_digest_record(entry["digest"], f"receipt evidence {index} digest")
    producer = _exact(raw["producer"], _PRODUCER_KEYS, "receipt producer")
    _identifier(producer["name"], "receipt producer name")
    _identifier(producer["version"], "receipt producer version")
    _digest(producer["source_sha256"], "receipt producer source digest")
    return json.loads(canonical_json(raw))


def _archive_member(root: Path, relative: str) -> Path:
    member = root / PurePosixPath(relative)
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ArchiveContractError(f"archive contains a symlink: {relative}")
    try:
        resolved = member.resolve(strict=True)
    except OSError as exc:
        raise ArchiveContractError(f"archive member is unavailable: {relative}") from exc
    if root != resolved and root not in resolved.parents:
        raise ArchiveContractError(f"archive member escapes its root: {relative}")
    return resolved


def verify_archive(root: Path | str,
                   registry_path: Path | str = _DEFAULT_REGISTRY) -> ArchiveVerification:
    requested_root = Path(root).expanduser()
    if requested_root.is_symlink():
        raise ArchiveContractError("archive root cannot be a symlink")
    archive_root = requested_root.resolve()
    if not archive_root.is_dir():
        raise ArchiveContractError("archive root is not a regular directory")
    registry = load_registry(registry_path)
    manifest_path = archive_root / "manifest.json"
    manifest_bytes, value = _read_json(
        manifest_path, "archive manifest", 2 * 1024 * 1024
    )
    manifest = _exact(value, _MANIFEST_KEYS, "archive manifest")
    if manifest["schema_id"] != ARCHIVE_MANIFEST_SCHEMA_ID:
        raise UnsupportedSchemaError("archive manifest schema is unsupported")
    if manifest["contract_id"] != CONTRACT_ID:
        raise ArchiveContractError("archive contract is unsupported")
    archive_id = _identifier(manifest["archive_id"], "archive id")
    grade = manifest["assurance_grade"]
    if grade not in _GRADE_REQUIREMENTS:
        raise ArchiveContractError("archive assurance grade is invalid")
    _timestamp(manifest["created_at"], "archive creation timestamp")

    policy_id = manifest["historical_policy_id"]
    if grade == "identity":
        if policy_id is not None:
            _urn(policy_id, "historical policy id")
    else:
        _urn(policy_id, "historical policy id")

    required_schemas = manifest["required_schema_ids"]
    if (not isinstance(required_schemas, list) or
            required_schemas != sorted(set(required_schemas)) or
            ARCHIVE_MANIFEST_SCHEMA_ID not in required_schemas):
        raise ArchiveContractError("required schema inventory is invalid")
    for schema_id in required_schemas:
        _require_supported_schema(schema_id, registry, "required schema")

    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ArchiveContractError("archive has no file inventory")
    declared_paths: set[str] = set()
    roles: dict[str, list[dict[str, Any]]] = {}
    for index, value in enumerate(files):
        entry = _exact(value, _FILE_KEYS, f"archive file {index}")
        relative = _relative_path(entry["path"], f"archive file {index} path")
        if relative == "manifest.json" or relative in declared_paths:
            raise ArchiveContractError("archive file inventory repeats a path")
        declared_paths.add(relative)
        role = entry["role"]
        if role not in _FILE_ROLES:
            raise ArchiveContractError(f"archive file role is invalid: {role}")
        if not isinstance(entry["bytes"], int) or isinstance(entry["bytes"], bool) or entry["bytes"] < 1:
            raise ArchiveContractError(f"archive file byte length is invalid: {relative}")
        digest = _validate_digest_record(entry["digest"], f"archive file {relative} digest")
        member = _archive_member(archive_root, relative)
        actual_bytes, actual_sha256 = _stable_file_identity(member)
        if actual_bytes != entry["bytes"] or actual_sha256 != digest["value"]:
            raise ArchiveContractError(f"archive file identity changed: {relative}")
        roles.setdefault(role, []).append(entry)

    actual_paths: set[str] = set()
    for candidate in archive_root.rglob("*"):
        if candidate.is_symlink():
            relative = candidate.relative_to(archive_root).as_posix()
            raise ArchiveContractError(f"archive contains a symlink: {relative}")
        if candidate.is_file():
            relative = candidate.relative_to(archive_root).as_posix()
            if relative != "manifest.json":
                actual_paths.add(relative)
    if actual_paths != declared_paths:
        missing = sorted(actual_paths - declared_paths)
        absent = sorted(declared_paths - actual_paths)
        raise ArchiveContractError(
            f"archive inventory is not closed; unlisted={missing}, absent={absent}"
        )

    missing_roles = sorted(_GRADE_REQUIREMENTS[grade] - set(roles))
    if missing_roles:
        raise ArchiveContractError(
            f"archive cannot support {grade}; missing roles: {', '.join(missing_roles)}"
        )
    if len(roles.get("master", [])) != 1:
        raise ArchiveContractError("archive must bind exactly one master")

    attestation = _exact(
        manifest["attestation"], _ATTESTATION_KEYS, "archive attestation"
    )
    if attestation["status"] == "none":
        if attestation["signature_file"] is not None or attestation["anchor"] is not None:
            raise ArchiveContractError("absent attestation carries unexpected fields")
        attestation_status = "absent"
    elif attestation["status"] == "declared":
        signature_file = _relative_path(
            attestation["signature_file"], "attestation signature file"
        )
        if (not isinstance(attestation["anchor"], str) or
                not attestation["anchor"].strip()):
            raise ArchiveContractError("declared attestation has no external anchor")
        if not any(item["path"] == signature_file
                   for item in roles.get("signature_bundle", [])):
            raise ArchiveContractError("attestation signature is not bound as evidence")
        attestation_status = "declared_not_cryptographically_verified"
    else:
        raise ArchiveContractError("archive attestation status is invalid")

    master = roles["master"][0]
    return ArchiveVerification(
        archive_id=archive_id,
        assurance_grade=grade,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        file_count=len(files),
        master_sha256=master["digest"]["value"],
        required_schema_ids=tuple(required_schemas),
        attestation_status=attestation_status,
    )
