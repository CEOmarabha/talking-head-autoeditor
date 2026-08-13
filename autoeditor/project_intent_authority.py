"""Engine-side ProjectIntent authority and render-receipt contracts.

The desktop authenticates an approved intent to the helper daemon with a
one-use HMAC.  The HMAC key is deliberately never handed to the editing
engine.  After authenticating that message, the daemon uses this module to
build a smaller canonical envelope and passes both its private path and exact
SHA-256 to the engine.  The engine independently validates every normalized
object, recomputes the policy from the intent and capability manifest, and
binds the result to the rendered artifact's QA receipt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from .edit_policy import edit_policy_sha256, validate_edit_policy
from .project_intent_policy_bridge import (
    resolve_project_intent_policy,
    validate_capability_manifest,
    validate_project_intent,
)


PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA = (
    "autoeditor-project-intent-engine-envelope/v2"
)
PROJECT_INTENT_RENDER_RECEIPT_SCHEMA = (
    "autoeditor-project-intent-render-receipt/v2"
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_AUTHORIZATION_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_AUTHORITY_INPUT_KEYS = frozenset({
    "schema_version", "authorization_id", "approved_proposal_sha256",
    "project_intent",
    "project_intent_sha256", "edit_policy", "edit_policy_sha256",
    "capability_manifest", "capability_manifest_sha256",
    "authorization_hmac_sha256",
})
_ENGINE_ENVELOPE_KEYS = frozenset({
    "schema_version", "authorization_id", "approved_proposal_sha256",
    "approved_transition_carrier", "project_intent",
    "project_intent_sha256", "edit_policy", "edit_policy_sha256",
    "capability_manifest", "capability_manifest_sha256",
    "capability_probe_receipt_sha256",
})
_APPROVED_TRANSITION_CARRIER_KEYS = frozenset({
    "sequence_plan_sha256", "source_manifest_sha256",
    "transition_plan_sha256", "transition_sequence_manifest_sha256",
})
_ACTUAL_RENDER_KEYS = frozenset({
    "duration_ms", "delivery", "preferences",
})
_ACTUAL_DELIVERY_KEYS = frozenset({
    "platform", "configured_aspect", "artifact_aspect", "width", "height",
})
_ACTUAL_PREFERENCE_KEYS = frozenset({
    "captions", "graphics", "music", "sfx", "transitions",
})
_CAPTION_FACT_KEYS = frozenset({"delivery", "event_count"})
_GRAPHICS_FACT_KEYS = frozenset({"event_count"})
_MUSIC_FACT_KEYS = frozenset({"added_music_present", "source_music_preserved"})
_SFX_FACT_KEYS = frozenset({"cue_count", "policy_usage", "policy_bound"})
_TRANSITION_FACT_KEYS = frozenset({
    "event_count", "non_hard_event_count", "policy_usage", "policy_bound",
})
_RENDER_RECEIPT_KEYS = frozenset({
    "schema_version", "authorization_id", "approved_proposal_sha256",
    "approved_transition_carrier", "engine_envelope_sha256",
    "project_intent", "project_intent_sha256", "edit_policy",
    "edit_policy_sha256", "capability_manifest",
    "capability_manifest_sha256", "capability_probe_receipt_sha256",
    "actual_render", "checks", "pass",
})
_CHECK_NAMES = (
    "canonical_authority", "target_duration", "delivery", "captions",
    "graphics", "music", "sfx", "transitions",
)
_ASPECT_RATIOS = {
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "1:1": 1.0,
    "4:5": 4 / 5,
    "21:9": 21 / 9,
}


class ProjectIntentAuthorityError(ValueError):
    """An engine authority envelope or render receipt failed closed."""


def _fail(message: str) -> None:
    raise ProjectIntentAuthorityError(message)


def _exact_object(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} does not match its closed contract")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ProjectIntentAuthorityError(
            "project intent authority is not canonical JSON"
        ) from error


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _lower_sha256(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be lowercase SHA-256")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{label} must be a nonnegative integer")
    return value


def _normalize_approved_transition_carrier(value: object) -> dict | None:
    if value is None:
        return None
    raw = _exact_object(
        value, _APPROVED_TRANSITION_CARRIER_KEYS,
        "approved transition carrier",
    )
    return {
        name: _lower_sha256(raw.get(name), f"transition carrier {name}")
        for name in sorted(_APPROVED_TRANSITION_CARRIER_KEYS)
    }


def build_project_intent_engine_envelope(
        authority: object,
        approved_transition_carrier: object = None) -> dict[str, Any]:
    """Strip daemon-only HMAC material from an authenticated authority.

    This function does not authenticate the input HMAC; callers must invoke it
    only after the daemon's one-use HMAC validator succeeds.  It does perform
    every object, digest, and policy-derivation check again so the engine
    receives one stable and narrowly scoped wire contract.
    """

    raw = _exact_object(authority, _AUTHORITY_INPUT_KEYS, "daemon authority")
    if raw.get("schema_version") != "autoeditor-project-intent-authority/v2":
        _fail("daemon authority schema is unsupported")
    authorization_id = raw.get("authorization_id")
    if (type(authorization_id) is not str
            or _AUTHORIZATION_ID_RE.fullmatch(authorization_id) is None):
        _fail("daemon authority authorization_id is invalid")

    project = validate_project_intent(raw["project_intent"])
    manifest = validate_capability_manifest(raw["capability_manifest"])
    policy = validate_edit_policy(raw["edit_policy"])
    resolved = resolve_project_intent_policy(project, manifest)
    if _canonical_json(policy) != _canonical_json(resolved):
        _fail("daemon authority policy was not derived from its exact intent")
    project_hash = _canonical_sha256(project)
    manifest_hash = _canonical_sha256(manifest)
    policy_hash = edit_policy_sha256(policy)
    if raw.get("project_intent_sha256") != project_hash:
        _fail("daemon authority project intent digest does not match")
    if raw.get("capability_manifest_sha256") != manifest_hash:
        _fail("daemon authority capability manifest digest does not match")
    if raw.get("edit_policy_sha256") != policy_hash:
        _fail("daemon authority edit policy digest does not match")
    _lower_sha256(
        raw.get("authorization_hmac_sha256"),
        "daemon authority authorization_hmac_sha256",
    )
    approved_proposal_hash = _lower_sha256(
        raw.get("approved_proposal_sha256"),
        "daemon authority approved_proposal_sha256",
    )
    transition_carrier = _normalize_approved_transition_carrier(
        approved_transition_carrier
    )
    probe_hash = _lower_sha256(
        manifest["probe_receipt_sha256"],
        "capability manifest probe_receipt_sha256",
    )
    return {
        "schema_version": PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA,
        "authorization_id": authorization_id,
        "approved_proposal_sha256": approved_proposal_hash,
        "approved_transition_carrier": transition_carrier,
        "project_intent": copy.deepcopy(project),
        "project_intent_sha256": project_hash,
        "edit_policy": copy.deepcopy(policy),
        "edit_policy_sha256": policy_hash,
        "capability_manifest": copy.deepcopy(manifest),
        "capability_manifest_sha256": manifest_hash,
        # This digest is the canonical aggregate of the complete probe
        # receipt, which itself binds every per-check result receipt and the
        # measured runtime-manifest digest.  The envelope does not claim that
        # the runtime-manifest preimage is separately available to the engine.
        "capability_probe_receipt_sha256": probe_hash,
    }


def validate_project_intent_engine_envelope(value: object) -> dict[str, Any]:
    raw = _exact_object(value, _ENGINE_ENVELOPE_KEYS, "engine authority envelope")
    if raw.get("schema_version") != PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA:
        _fail("engine authority envelope schema is unsupported")
    authorization_id = raw.get("authorization_id")
    if (type(authorization_id) is not str
            or _AUTHORIZATION_ID_RE.fullmatch(authorization_id) is None):
        _fail("engine authority envelope authorization_id is invalid")
    approved_proposal_hash = _lower_sha256(
        raw.get("approved_proposal_sha256"),
        "engine authority envelope approved_proposal_sha256",
    )
    transition_carrier = _normalize_approved_transition_carrier(
        raw.get("approved_transition_carrier")
    )
    project = validate_project_intent(raw["project_intent"])
    manifest = validate_capability_manifest(raw["capability_manifest"])
    policy = validate_edit_policy(raw["edit_policy"])
    resolved = resolve_project_intent_policy(project, manifest)
    if _canonical_json(policy) != _canonical_json(resolved):
        _fail("engine authority policy was not derived from its exact intent")
    project_hash = _canonical_sha256(project)
    manifest_hash = _canonical_sha256(manifest)
    policy_hash = edit_policy_sha256(policy)
    probe_hash = manifest["probe_receipt_sha256"]
    expected = {
        "project_intent_sha256": project_hash,
        "edit_policy_sha256": policy_hash,
        "capability_manifest_sha256": manifest_hash,
        "capability_probe_receipt_sha256": probe_hash,
    }
    for name, digest in expected.items():
        if _lower_sha256(raw.get(name), name) != digest:
            _fail(f"engine authority envelope {name} does not match")
    return {
        "schema_version": PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA,
        "authorization_id": authorization_id,
        "approved_proposal_sha256": approved_proposal_hash,
        "approved_transition_carrier": transition_carrier,
        "project_intent": copy.deepcopy(project),
        "project_intent_sha256": project_hash,
        "edit_policy": copy.deepcopy(policy),
        "edit_policy_sha256": policy_hash,
        "capability_manifest": copy.deepcopy(manifest),
        "capability_manifest_sha256": manifest_hash,
        "capability_probe_receipt_sha256": probe_hash,
    }


def canonical_project_intent_engine_envelope_bytes(value: object) -> bytes:
    normalized = validate_project_intent_engine_envelope(value)
    return _canonical_json(normalized).encode("utf-8")


def project_intent_engine_envelope_sha256(value: object) -> str:
    return hashlib.sha256(
        canonical_project_intent_engine_envelope_bytes(value)
    ).hexdigest()


def _normalize_actual_render(value: object) -> dict[str, Any]:
    raw = _exact_object(value, _ACTUAL_RENDER_KEYS, "actual render facts")
    duration_ms = _nonnegative_integer(raw["duration_ms"], "duration_ms")
    delivery = _exact_object(
        raw["delivery"], _ACTUAL_DELIVERY_KEYS, "actual render delivery"
    )
    platform = delivery.get("platform")
    configured_aspect = delivery.get("configured_aspect")
    artifact_aspect = delivery.get("artifact_aspect")
    if any(type(item) is not str or not item for item in (
            platform, configured_aspect, artifact_aspect)):
        _fail("actual render delivery strings are invalid")
    width = _nonnegative_integer(delivery.get("width"), "delivery.width")
    height = _nonnegative_integer(delivery.get("height"), "delivery.height")
    if width < 1 or height < 1:
        _fail("actual render delivery dimensions are invalid")

    preferences = _exact_object(
        raw["preferences"], _ACTUAL_PREFERENCE_KEYS,
        "actual render preferences",
    )
    captions = _exact_object(
        preferences["captions"], _CAPTION_FACT_KEYS, "caption render facts"
    )
    if captions.get("delivery") not in {"none", "sidecar", "burned"}:
        _fail("caption render delivery is unsupported")
    caption_count = _nonnegative_integer(
        captions.get("event_count"), "captions.event_count"
    )
    graphics = _exact_object(
        preferences["graphics"], _GRAPHICS_FACT_KEYS, "graphics render facts"
    )
    graphic_count = _nonnegative_integer(
        graphics.get("event_count"), "graphics.event_count"
    )
    music = _exact_object(
        preferences["music"], _MUSIC_FACT_KEYS, "music render facts"
    )
    if type(music.get("added_music_present")) is not bool \
            or type(music.get("source_music_preserved")) is not bool:
        _fail("music render facts must be boolean")
    sfx = _exact_object(
        preferences["sfx"], _SFX_FACT_KEYS, "SFX render facts"
    )
    cue_count = _nonnegative_integer(sfx.get("cue_count"), "sfx.cue_count")
    if type(sfx.get("policy_usage")) is not str \
            or type(sfx.get("policy_bound")) is not bool:
        _fail("SFX policy facts are invalid")
    transitions = _exact_object(
        preferences["transitions"], _TRANSITION_FACT_KEYS,
        "transition render facts",
    )
    event_count = _nonnegative_integer(
        transitions.get("event_count"), "transitions.event_count"
    )
    non_hard_count = _nonnegative_integer(
        transitions.get("non_hard_event_count"),
        "transitions.non_hard_event_count",
    )
    if non_hard_count > event_count:
        _fail("transition non-hard count exceeds total events")
    if type(transitions.get("policy_usage")) is not str \
            or type(transitions.get("policy_bound")) is not bool:
        _fail("transition policy facts are invalid")
    return {
        "duration_ms": duration_ms,
        "delivery": {
            "platform": platform,
            "configured_aspect": configured_aspect,
            "artifact_aspect": artifact_aspect,
            "width": width,
            "height": height,
        },
        "preferences": {
            "captions": {
                "delivery": captions["delivery"],
                "event_count": caption_count,
            },
            "graphics": {"event_count": graphic_count},
            "music": {
                "added_music_present": music["added_music_present"],
                "source_music_preserved": music["source_music_preserved"],
            },
            "sfx": {
                "cue_count": cue_count,
                "policy_usage": sfx["policy_usage"],
                "policy_bound": sfx["policy_bound"],
            },
            "transitions": {
                "event_count": event_count,
                "non_hard_event_count": non_hard_count,
                "policy_usage": transitions["policy_usage"],
                "policy_bound": transitions["policy_bound"],
            },
        },
    }


def _preference_checks(project: dict, policy: dict,
                       actual: dict) -> dict[str, bool]:
    requested = project["preferences"]
    facts = actual["preferences"]

    caption_preference = requested["captions"]["preference"]
    caption_delivery = facts["captions"]["delivery"]
    caption_count = facts["captions"]["event_count"]
    caption_intent_ok = (
        (caption_preference == "none" and caption_delivery == "none"
         and caption_count == 0)
        or (caption_preference == "verbatim"
            and caption_delivery in {"sidecar", "burned"}
            and caption_count > 0)
        or caption_preference == "auto"
    )
    caption_rule = policy["rules"]["captions"]["usage"]
    caption_policy_ok = (
        caption_rule == "optional"
        or (caption_rule == "forbidden" and caption_delivery == "none"
            and caption_count == 0)
        or (caption_rule in {"required", "verbatim_required"}
            and caption_delivery in {"sidecar", "burned"}
            and caption_count > 0)
    )
    captions_ok = caption_intent_ok and caption_policy_ok

    graphic_preference = requested["graphics"]["preference"]
    graphic_count = facts["graphics"]["event_count"]
    graphic_intent_ok = (
        graphic_preference == "auto"
        or (graphic_preference == "none"
            and graphic_count == 0)
    )
    visualization_rule = policy["rules"]["visualizations"]["usage"]
    graphic_policy_ok = (
        visualization_rule in {"allowed", "recommended"}
        or (visualization_rule == "forbidden" and graphic_count == 0)
        or (visualization_rule == "required" and graphic_count > 0)
    )
    graphics_ok = graphic_intent_ok and graphic_policy_ok

    music_preference = requested["music"]["preference"]
    added_music = facts["music"]["added_music_present"]
    source_music = facts["music"]["source_music_preserved"]
    music_intent_ok = {
        "auto": True,
        "none": not added_music,
        "primary": added_music,
        "supporting": added_music,
        "source_primary": source_music and not added_music,
    }[music_preference]
    music_rule = policy["rules"]["music"]["usage"]
    music_policy_ok = {
        "optional": True,
        "forbidden": not added_music,
        "primary": added_music,
        "supporting": added_music,
        "source_primary": source_music and not added_music,
    }[music_rule]
    music_ok = music_intent_ok and music_policy_ok

    sfx_preference = requested["sfx"]["preference"]
    sfx_count = facts["sfx"]["cue_count"]
    sfx_usage = facts["sfx"]["policy_usage"]
    sfx_bound = facts["sfx"]["policy_bound"]
    sfx_intent_ok = (
        sfx_preference == "auto"
        or (sfx_preference == "none" and sfx_count == 0)
        or (sfx_preference not in {"auto", "none"}
            and sfx_count > 0 and sfx_bound
            and sfx_usage == sfx_preference)
    )
    sfx_rule = policy["rules"]["sfx"]
    sfx_policy_ok = (
        (sfx_rule["density"] == "none" and sfx_count == 0)
        or (sfx_rule["density"] != "none" and (
            sfx_count == 0
            or (sfx_bound and sfx_usage == sfx_rule["usage"])
        ))
    )
    sfx_ok = sfx_intent_ok and sfx_policy_ok

    transition_preference = requested["transitions"]["preference"]
    transition_count = facts["transitions"]["event_count"]
    non_hard_count = facts["transitions"]["non_hard_event_count"]
    transition_usage = facts["transitions"]["policy_usage"]
    transition_bound = facts["transitions"]["policy_bound"]
    transition_intent_ok = (
        transition_preference == "auto"
        or (transition_preference in {"none", "hard_cut_only"}
            and non_hard_count == 0)
        or (transition_preference not in {"auto", "none", "hard_cut_only"}
            and transition_count > 0 and non_hard_count > 0
            and transition_bound and transition_usage == transition_preference)
    )
    transition_rule = policy["rules"]["transitions"]
    transition_policy_ok = (
        (transition_rule["density"] == "none" and non_hard_count == 0)
        or (transition_rule["density"] != "none" and (
            non_hard_count == 0
            or (transition_bound
                and transition_usage == transition_rule["usage"])
        ))
    )
    transitions_ok = transition_intent_ok and transition_policy_ok
    return {
        "captions": captions_ok,
        "graphics": graphics_ok,
        "music": music_ok,
        "sfx": sfx_ok,
        "transitions": transitions_ok,
    }


def _artifact_aspect_matches(aspect: str, width: int, height: int) -> bool:
    ratio = _ASPECT_RATIOS.get(aspect)
    if ratio is None:
        return False
    return abs(width / height - ratio) <= 0.01


def build_project_intent_render_receipt(
        envelope: object, envelope_sha256: object,
        actual_render: object) -> dict[str, Any]:
    """Build the release-blocking receipt for actual rendered settings."""

    authority = validate_project_intent_engine_envelope(envelope)
    expected_envelope_hash = project_intent_engine_envelope_sha256(authority)
    supplied_envelope_hash = _lower_sha256(
        envelope_sha256, "engine envelope SHA-256"
    )
    actual = _normalize_actual_render(actual_render)
    project = authority["project_intent"]
    policy = authority["edit_policy"]

    minimum = project["target_duration"]["min_ms"]
    maximum = project["target_duration"]["max_ms"]
    duration_ok = minimum <= actual["duration_ms"] <= maximum
    delivery = actual["delivery"]
    delivery_ok = (
        delivery["platform"] == project["delivery"]["platform"]
        == policy["delivery"]["platform"]
        and delivery["configured_aspect"] == project["delivery"]["aspect"]
        == policy["delivery"]["aspect"]
        and delivery["artifact_aspect"] == project["delivery"]["aspect"]
        and _artifact_aspect_matches(
            project["delivery"]["aspect"],
            delivery["width"], delivery["height"],
        )
    )
    preference_checks = _preference_checks(project, policy, actual)
    check_values = {
        "canonical_authority": supplied_envelope_hash == expected_envelope_hash,
        "target_duration": duration_ok,
        "delivery": delivery_ok,
        **preference_checks,
    }
    checks = {
        name: {"ok": bool(check_values[name])}
        for name in _CHECK_NAMES
    }
    return {
        "schema_version": PROJECT_INTENT_RENDER_RECEIPT_SCHEMA,
        "authorization_id": authority["authorization_id"],
        "approved_proposal_sha256": authority["approved_proposal_sha256"],
        "approved_transition_carrier": copy.deepcopy(
            authority["approved_transition_carrier"]
        ),
        "engine_envelope_sha256": supplied_envelope_hash,
        "project_intent": copy.deepcopy(project),
        "project_intent_sha256": authority["project_intent_sha256"],
        "edit_policy": copy.deepcopy(policy),
        "edit_policy_sha256": authority["edit_policy_sha256"],
        "capability_manifest": copy.deepcopy(authority["capability_manifest"]),
        "capability_manifest_sha256": authority[
            "capability_manifest_sha256"
        ],
        "capability_probe_receipt_sha256": authority[
            "capability_probe_receipt_sha256"
        ],
        "actual_render": actual,
        "checks": checks,
        "pass": all(check["ok"] for check in checks.values()),
    }


def validate_project_intent_render_receipt(value: object) -> dict[str, Any]:
    raw = _exact_object(value, _RENDER_RECEIPT_KEYS, "intent render receipt")
    if raw.get("schema_version") != PROJECT_INTENT_RENDER_RECEIPT_SCHEMA:
        _fail("intent render receipt schema is unsupported")
    envelope = {
        name: raw[name]
        for name in _ENGINE_ENVELOPE_KEYS
        if name != "schema_version"
    }
    envelope["schema_version"] = PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA
    normalized_envelope = validate_project_intent_engine_envelope(envelope)
    normalized = build_project_intent_render_receipt(
        normalized_envelope, raw.get("engine_envelope_sha256"),
        raw.get("actual_render"),
    )
    if _canonical_json(raw) != _canonical_json(normalized):
        _fail("intent render receipt does not match derived release checks")
    return copy.deepcopy(normalized)


def canonical_project_intent_render_receipt_json(value: object) -> str:
    return _canonical_json(validate_project_intent_render_receipt(value))


def project_intent_render_receipt_sha256(value: object) -> str:
    return hashlib.sha256(
        canonical_project_intent_render_receipt_json(value).encode("utf-8")
    ).hexdigest()


__all__ = (
    "PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA",
    "PROJECT_INTENT_RENDER_RECEIPT_SCHEMA",
    "ProjectIntentAuthorityError",
    "build_project_intent_engine_envelope",
    "validate_project_intent_engine_envelope",
    "canonical_project_intent_engine_envelope_bytes",
    "project_intent_engine_envelope_sha256",
    "build_project_intent_render_receipt",
    "validate_project_intent_render_receipt",
    "canonical_project_intent_render_receipt_json",
    "project_intent_render_receipt_sha256",
)
