"""Closed, deterministic contract for multi-source sequence edits.

``autoeditor-sequence-plan/v1`` describes *what* source intervals to assemble,
in output order.  It deliberately does not contain filesystem paths or an
FFmpeg command.  Sources are addressed by a stable identifier and their full
content hash, then bound to an independently supplied source manifest before a
plan can compile.

All time values are integer milliseconds.  This is an exact 1/1000-second
rational time base: duration sums cannot drift through binary floating-point,
and compilation emits fixed-point decimal tokens that are safe to pass to
FFmpeg as individual argv elements.  Callers must never join argv tokens into
a shell command.

A speech anchor records inclusive word indices and canonical text, but this
module has no transcript input.  Its validation is therefore structural, not a
claim that the text was spoken.  Before treating an anchor as grounded, the
caller must compare it to the immutable word transcript associated with the
same ``source_sha256``.  This limitation is explicit so a planner cannot turn
unverified prose into a provenance claim.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from typing import Any


SEQUENCE_PLAN_SCHEMA_VERSION = "autoeditor-sequence-plan/v1"
SOURCE_MANIFEST_SCHEMA_VERSION = "autoeditor-source-manifest/v1"
COMPILE_RECEIPT_SCHEMA_VERSION = "autoeditor-sequence-compile-receipt/v1"

MAX_SOURCES = 20
MAX_SEGMENTS = 256
MAX_SAFE_INTEGER = 9_007_199_254_740_991
# Keep the maximum accepted contract comfortably inside every downstream
# desktop/session/IPC/receipt byte budget even with non-ASCII JSON escaping.
# Reasons are editorial metadata, while anchor text is an exact bounded quote;
# neither needs essay-sized payloads per cut.
MAX_REASON_CHARACTERS = 200
MAX_SPEECH_ANCHOR_CHARACTERS = 500
MIN_SEQUENCE_DURATION_MS = 5_000
# The execution contract currently delivers 30 fps. Anything shorter than one
# frame is not an editable interval and can disappear during CFR compilation.
MIN_SEGMENT_DURATION_MS = 34

ROLES = frozenset({
    "hook",
    "setup",
    "development",
    "evidence",
    "demonstration",
    "reaction",
    "transition",
    "payoff",
    "cta",
    "closer",
    "establishing",
    "highlight",
    "bridge",
    "other",
})

_ROOT_KEYS = frozenset({
    "schema_version", "sources", "target_duration", "segments",
})
_SOURCE_MANIFEST_KEYS = frozenset({"schema_version", "sources"})
_SOURCE_KEYS = frozenset({"source_id", "sha256", "duration_ms"})
_TARGET_KEYS = frozenset({"min_ms", "max_ms"})
_SEGMENT_KEYS = frozenset({
    "segment_id",
    "source_id",
    "source_sha256",
    "source_start_ms",
    "source_end_ms",
    "role",
    "reason",
    "speech_anchor",
    "transition",
})
_SPEECH_ANCHOR_KEYS = frozenset({"start_word", "end_word", "text"})
_TRANSITION_KEYS = frozenset({"kind"})
_RECEIPT_KEYS = frozenset({
    "schema_version",
    "sequence_plan_sha256",
    "source_manifest_sha256",
    "compiled_segments_sha256",
    "ordered_segment_ids",
    "segment_count",
    "total_duration_ms",
    "time_base",
})
_TIME_BASE_KEYS = frozenset({"numerator", "denominator"})

_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)
_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


def _source_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_SOURCE_KEYS),
        "properties": {
            "source_id": {"type": "string", "pattern": _SOURCE_ID.pattern},
            "sha256": {"type": "string", "pattern": _SHA256.pattern},
            "duration_ms": {
                "type": "integer", "minimum": 1,
                "maximum": MAX_SAFE_INTEGER,
            },
        },
    }


SEQUENCE_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_ROOT_KEYS),
    "properties": {
        "schema_version": {"const": SEQUENCE_PLAN_SCHEMA_VERSION},
        "sources": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_SOURCES,
            "items": _source_json_schema(),
        },
        "target_duration": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_TARGET_KEYS),
            "properties": {
                "min_ms": {
                    "type": "integer", "minimum": MIN_SEQUENCE_DURATION_MS,
                    "maximum": MAX_SAFE_INTEGER,
                },
                "max_ms": {
                    "type": "integer", "minimum": MIN_SEQUENCE_DURATION_MS,
                    "maximum": MAX_SAFE_INTEGER,
                },
            },
        },
        "segments": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_SEGMENTS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_SEGMENT_KEYS),
                "properties": {
                    "segment_id": {
                        "type": "string", "pattern": _SEGMENT_ID.pattern,
                    },
                    "source_id": {
                        "type": "string", "pattern": _SOURCE_ID.pattern,
                    },
                    "source_sha256": {
                        "type": "string", "pattern": _SHA256.pattern,
                    },
                    "source_start_ms": {
                        "type": "integer", "minimum": 0,
                        "maximum": MAX_SAFE_INTEGER,
                    },
                    "source_end_ms": {
                        "type": "integer", "minimum": 1,
                        "maximum": MAX_SAFE_INTEGER,
                    },
                    "role": {"type": "string", "enum": sorted(ROLES)},
                    "reason": {
                        "type": "string", "minLength": 1,
                        "maxLength": MAX_REASON_CHARACTERS,
                    },
                    "speech_anchor": {
                        "anyOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": sorted(_SPEECH_ANCHOR_KEYS),
                                "properties": {
                                    "start_word": {
                                        "type": "integer", "minimum": 0,
                                        "maximum": MAX_SAFE_INTEGER,
                                    },
                                    "end_word": {
                                        "type": "integer", "minimum": 0,
                                        "maximum": MAX_SAFE_INTEGER,
                                    },
                                    "text": {
                                        "type": "string", "minLength": 1,
                                        "maxLength": (
                                            MAX_SPEECH_ANCHOR_CHARACTERS
                                        ),
                                    },
                                },
                            },
                        ],
                    },
                    "transition": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind"],
                        "properties": {"kind": {"const": "hard_cut"}},
                    },
                },
            },
        },
    },
}


class SequencePlanError(ValueError):
    """A sequence plan or its source binding is unsafe or inconsistent."""


def _fail(message: str) -> None:
    raise SequencePlanError(message)


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
            details.append(
                "unsupported " + ", ".join(str(item) for item in extra)
            )
        _fail(f"{label} has invalid keys ({'; '.join(details)})")
    return value


def _integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_SAFE_INTEGER,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


def _identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(f"{label} has an invalid ASCII identifier")
    return value


def _sha256(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a full lowercase SHA-256 digest")
    return value


def _canonical_text(
    value: object,
    label: str,
    *,
    maximum: int,
) -> str:
    if type(value) is not str:
        _fail(f"{label} must be a string")
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    if not text or len(text) > maximum:
        _fail(f"{label} must contain 1-{maximum} canonical characters")
    if not any(character.isalnum() for character in text):
        _fail(f"{label} must contain an alphanumeric character")
    if any(unicodedata.category(character).startswith("C") for character in text):
        _fail(f"{label} must not contain control or format characters")
    return text


def _normalize_sources(value: object, label: str) -> list[dict[str, Any]]:
    if type(value) is not list or not 1 <= len(value) <= MAX_SOURCES:
        _fail(f"{label} must contain 1-{MAX_SOURCES} sources")

    normalized = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _exact_keys(raw, _SOURCE_KEYS, item_label)
        source_id = _identifier(
            item["source_id"], _SOURCE_ID, f"{item_label}.source_id"
        )
        digest = _sha256(item["sha256"], f"{item_label}.sha256")
        duration = _integer(
            item["duration_ms"], f"{item_label}.duration_ms", minimum=1
        )
        if source_id in seen_ids:
            _fail(f"{item_label}.source_id must be unique")
        if digest in seen_hashes:
            _fail(f"{item_label}.sha256 must identify one unique source")
        seen_ids.add(source_id)
        seen_hashes.add(digest)
        normalized.append({
            "source_id": source_id,
            "sha256": digest,
            "duration_ms": duration,
        })

    # Source inventory is not an edit order. Sorting makes its canonical hash
    # independent of upload enumeration while segment array order stays exact.
    return sorted(normalized, key=lambda item: item["source_id"])


def _normalize_manifest(value: object) -> dict[str, Any]:
    manifest = _exact_keys(
        value, _SOURCE_MANIFEST_KEYS, "source manifest"
    )
    if manifest["schema_version"] != SOURCE_MANIFEST_SCHEMA_VERSION:
        _fail("source manifest schema_version is unsupported")
    return {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sources": _normalize_sources(
            manifest["sources"], "source manifest sources"
        ),
    }


def _normalize_speech_anchor(value: object, label: str) -> dict | None:
    if value is None:
        return None
    anchor = _exact_keys(value, _SPEECH_ANCHOR_KEYS, label)
    start = _integer(anchor["start_word"], f"{label}.start_word")
    end = _integer(anchor["end_word"], f"{label}.end_word")
    if start > end:
        _fail(f"{label} has reversed inclusive word bounds")
    text = _canonical_text(
        anchor["text"],
        f"{label}.text",
        maximum=MAX_SPEECH_ANCHOR_CHARACTERS,
    )
    return {"start_word": start, "end_word": end, "text": text}


def _normalize_plan(value: object) -> dict[str, Any]:
    plan = _exact_keys(value, _ROOT_KEYS, "sequence plan")
    if plan["schema_version"] != SEQUENCE_PLAN_SCHEMA_VERSION:
        _fail("sequence plan schema_version is unsupported")

    sources = _normalize_sources(plan["sources"], "sequence plan sources")
    sources_by_id = {item["source_id"]: item for item in sources}

    target = _exact_keys(
        plan["target_duration"], _TARGET_KEYS, "target_duration"
    )
    minimum = _integer(
        target["min_ms"], "target_duration.min_ms",
        minimum=MIN_SEQUENCE_DURATION_MS,
    )
    maximum = _integer(
        target["max_ms"], "target_duration.max_ms",
        minimum=MIN_SEQUENCE_DURATION_MS,
    )
    if minimum > maximum:
        _fail("target_duration.min_ms cannot exceed max_ms")

    raw_segments = plan["segments"]
    if type(raw_segments) is not list or not 1 <= len(raw_segments) <= MAX_SEGMENTS:
        _fail(f"segments must contain 1-{MAX_SEGMENTS} ordered entries")

    segments = []
    seen_segment_ids: set[str] = set()
    total_duration = 0
    for index, raw in enumerate(raw_segments):
        label = f"segments[{index}]"
        item = _exact_keys(raw, _SEGMENT_KEYS, label)
        segment_id = _identifier(
            item["segment_id"], _SEGMENT_ID, f"{label}.segment_id"
        )
        if segment_id in seen_segment_ids:
            _fail(f"{label}.segment_id must be unique")
        seen_segment_ids.add(segment_id)

        source_id = _identifier(
            item["source_id"], _SOURCE_ID, f"{label}.source_id"
        )
        if source_id not in sources_by_id:
            _fail(f"{label}.source_id is absent from sequence plan sources")
        source = sources_by_id[source_id]
        digest = _sha256(
            item["source_sha256"], f"{label}.source_sha256"
        )
        if digest != source["sha256"]:
            _fail(f"{label}.source_sha256 does not bind its source_id")

        start = _integer(
            item["source_start_ms"], f"{label}.source_start_ms"
        )
        end = _integer(
            item["source_end_ms"], f"{label}.source_end_ms", minimum=1
        )
        if end - start < MIN_SEGMENT_DURATION_MS:
            _fail(
                f"{label} must be at least {MIN_SEGMENT_DURATION_MS}ms "
                "to produce a 30fps frame"
            )
        if end > source["duration_ms"]:
            _fail(f"{label} ends beyond its source duration")

        role = item["role"]
        if type(role) is not str or role not in ROLES:
            _fail(f"{label}.role is unsupported")
        reason = _canonical_text(
            item["reason"], f"{label}.reason", maximum=MAX_REASON_CHARACTERS
        )
        speech_anchor = _normalize_speech_anchor(
            item["speech_anchor"], f"{label}.speech_anchor"
        )
        transition = _exact_keys(
            item["transition"], _TRANSITION_KEYS, f"{label}.transition"
        )
        if type(transition["kind"]) is not str or transition["kind"] != "hard_cut":
            _fail(f"{label}.transition.kind must be hard_cut in v1")

        segment_duration = end - start
        total_duration += segment_duration
        if total_duration > MAX_SAFE_INTEGER:
            _fail("total segment duration exceeds the exact JSON integer range")
        segments.append({
            "segment_id": segment_id,
            "source_id": source_id,
            "source_sha256": digest,
            "source_start_ms": start,
            "source_end_ms": end,
            "role": role,
            "reason": reason,
            "speech_anchor": speech_anchor,
            "transition": {"kind": "hard_cut"},
        })

    # Source overlap is intentionally not prohibited: a sequence may repeat,
    # reorder, or partially overlap material from any bound source.
    if not minimum <= total_duration <= maximum:
        _fail(
            "sum of ordered segment durations is outside target_duration"
        )

    return {
        "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
        "sources": sources,
        "target_duration": {"min_ms": minimum, "max_ms": maximum},
        "segments": segments,
    }


def validate_sequence_plan(
    plan: object,
    source_manifest: object,
) -> dict[str, Any]:
    """Validate, normalize, and bind a plan to an external source manifest.

    The plan must declare the exact same 1-20 sources as the manifest. Manifest
    enumeration order is ignored, but every source id, full content digest, and
    millisecond duration must match. Segment order is never changed.
    """
    normalized_plan = _normalize_plan(plan)
    manifest = _normalize_manifest(source_manifest)
    if normalized_plan["sources"] != manifest["sources"]:
        _fail(
            "sequence plan sources do not exactly match the source manifest"
        )
    return copy.deepcopy(normalized_plan)


def _canonical_json_data(value: object, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise SequencePlanError(f"{label} is not canonical JSON") from error


def canonical_json(plan: object) -> str:
    """Return normalized, key-sorted, whitespace-free sequence-plan JSON."""
    return _canonical_json_data(_normalize_plan(plan), "sequence plan")


def sequence_plan_sha256(plan: object) -> str:
    """Return the SHA-256 of :func:`canonical_json`."""
    return hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()


def canonical_source_manifest_json(source_manifest: object) -> str:
    """Return canonical JSON for an order-independent source inventory."""
    return _canonical_json_data(
        _normalize_manifest(source_manifest), "source manifest"
    )


def source_manifest_sha256(source_manifest: object) -> str:
    """Hash the schema-versioned, canonical source manifest."""
    payload = canonical_source_manifest_json(source_manifest).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ffmpeg_seconds(milliseconds: int) -> str:
    """Render exact milliseconds as a non-scientific FFmpeg time token."""
    return f"{milliseconds // 1_000}.{milliseconds % 1_000:03d}"


def _normalize_receipt(value: object) -> dict[str, Any]:
    receipt = _exact_keys(value, _RECEIPT_KEYS, "compile receipt")
    if receipt["schema_version"] != COMPILE_RECEIPT_SCHEMA_VERSION:
        _fail("compile receipt schema_version is unsupported")
    plan_hash = _sha256(
        receipt["sequence_plan_sha256"],
        "compile receipt.sequence_plan_sha256",
    )
    manifest_hash = _sha256(
        receipt["source_manifest_sha256"],
        "compile receipt.source_manifest_sha256",
    )
    compiled_hash = _sha256(
        receipt["compiled_segments_sha256"],
        "compile receipt.compiled_segments_sha256",
    )
    ordered = receipt["ordered_segment_ids"]
    if type(ordered) is not list or not 1 <= len(ordered) <= MAX_SEGMENTS:
        _fail("compile receipt.ordered_segment_ids has invalid cardinality")
    normalized_ids = []
    seen_ids: set[str] = set()
    for index, value_id in enumerate(ordered):
        segment_id = _identifier(
            value_id,
            _SEGMENT_ID,
            f"compile receipt.ordered_segment_ids[{index}]",
        )
        if segment_id in seen_ids:
            _fail("compile receipt ordered segment ids must be unique")
        seen_ids.add(segment_id)
        normalized_ids.append(segment_id)
    count = _integer(
        receipt["segment_count"],
        "compile receipt.segment_count",
        minimum=1,
        maximum=MAX_SEGMENTS,
    )
    if count != len(normalized_ids):
        _fail("compile receipt.segment_count does not match ordered ids")
    total = _integer(
        receipt["total_duration_ms"],
        "compile receipt.total_duration_ms",
        minimum=1,
    )
    time_base = _exact_keys(
        receipt["time_base"], _TIME_BASE_KEYS, "compile receipt.time_base"
    )
    if (type(time_base["numerator"]) is not int
            or type(time_base["denominator"]) is not int
            or time_base["numerator"] != 1
            or time_base["denominator"] != 1_000):
        _fail("compile receipt.time_base must be the exact 1/1000 rational")
    return {
        "schema_version": COMPILE_RECEIPT_SCHEMA_VERSION,
        "sequence_plan_sha256": plan_hash,
        "source_manifest_sha256": manifest_hash,
        "compiled_segments_sha256": compiled_hash,
        "ordered_segment_ids": normalized_ids,
        "segment_count": count,
        "total_duration_ms": total,
        "time_base": {"numerator": 1, "denominator": 1_000},
    }


def compile_receipt_sha256(receipt: object) -> str:
    """Hash a closed compile receipt after validating all of its bindings."""
    canonical = _canonical_json_data(
        _normalize_receipt(receipt), "compile receipt"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compile_sequence_plan(
    plan: object,
    source_manifest: object,
) -> dict[str, Any]:
    """Compile a validated plan into inert FFmpeg trim tokens and a receipt.

    This function performs no I/O and does not invoke FFmpeg. ``source_id`` is
    intentionally retained instead of resolving a path; the execution layer
    must resolve it through its trusted manifest and pass ``ffmpeg_trim_args``
    as separate subprocess argv tokens.
    """
    validated = validate_sequence_plan(plan, source_manifest)
    compiled = []
    total_duration = 0
    for sequence_index, segment in enumerate(validated["segments"]):
        start = segment["source_start_ms"]
        duration = segment["source_end_ms"] - start
        total_duration += duration
        compiled.append({
            "sequence_index": sequence_index,
            "segment_id": segment["segment_id"],
            "source_id": segment["source_id"],
            "source_sha256": segment["source_sha256"],
            "source_start_ms": start,
            "source_end_ms": segment["source_end_ms"],
            "duration_ms": duration,
            "transition": {"kind": "hard_cut"},
            "ffmpeg_trim_args": [
                "-ss", _ffmpeg_seconds(start),
                "-t", _ffmpeg_seconds(duration),
            ],
        })

    compiled_json = _canonical_json_data(compiled, "compiled segments")
    receipt = {
        "schema_version": COMPILE_RECEIPT_SCHEMA_VERSION,
        "sequence_plan_sha256": sequence_plan_sha256(validated),
        "source_manifest_sha256": source_manifest_sha256(source_manifest),
        "compiled_segments_sha256": hashlib.sha256(
            compiled_json.encode("utf-8")
        ).hexdigest(),
        "ordered_segment_ids": [
            item["segment_id"] for item in compiled
        ],
        "segment_count": len(compiled),
        "total_duration_ms": total_duration,
        "time_base": {"numerator": 1, "denominator": 1_000},
    }
    normalized_receipt = _normalize_receipt(receipt)
    return {
        "receipt": copy.deepcopy(normalized_receipt),
        "receipt_sha256": compile_receipt_sha256(normalized_receipt),
        "ffmpeg_segments": copy.deepcopy(compiled),
    }
