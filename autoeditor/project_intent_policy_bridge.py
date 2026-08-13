"""Strict bridge from project intent to the expert edit-policy contract.

The bridge is intentionally narrower than either source contract.  It maps only
preferences whose meaning can be represented exactly by
``autoeditor-edit-policy-request/v1``.  A selective-caption request or a typed
graphics style therefore fails instead of being silently weakened to a generic
caption or visualization rule.

Capability availability is a trust boundary.  This module accepts only an
exact, versioned manifest attributed to the local runtime probe and bound to a
SHA-256 probe receipt.  It validates that every claimed capability belongs to
the closed edit-policy vocabulary, but it cannot prove that the referenced
receipt was produced locally.  The desktop/helper integration must verify the
receipt and must never construct this manifest from user, model, or remote API
claims.  The manifest receipt must be retained beside the resolved policy
because edit-policy/v1 intentionally records required, not available,
capabilities.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .edit_policy import (
    ASPECTS,
    CAPABILITIES,
    EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    MAX_DURATION_MS,
    PLATFORMS,
    PROFILE_NAMES,
    EditPolicyError,
    duration_band,
    resolve_edit_policy,
)


PROJECT_INTENT_SCHEMA_VERSION = "autoeditor-project-intent/v1"
CAPABILITY_MANIFEST_SCHEMA_VERSION = "autoeditor-trusted-capability-manifest/v1"
CAPABILITY_MANIFEST_SOURCE = "autoeditor-local-runtime-probe/v1"

# These identifiers have concrete local implementation/probe seams in the
# current runtime.  They are not unconditional availability claims: the local
# preflight must include a name only after that capability succeeds for the
# current job.  Capabilities outside this set remain valid in a trusted
# manifest so a future verified runtime can satisfy the stable policy contract.
CURRENT_RUNTIME_CAPABILITIES = frozenset({
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
})
if not CURRENT_RUNTIME_CAPABILITIES < CAPABILITIES:
    raise RuntimeError("current runtime capability surface drifted from edit-policy/v1")


FEATURE_NAMES = ("captions", "graphics", "music", "sfx", "transitions")
FEATURE_PREFERENCES = {
    "captions": frozenset({"auto", "none", "selective", "verbatim"}),
    "music": frozenset({"auto", "none", "primary", "source_primary", "supporting"}),
    "sfx": frozenset({
        "auto", "event_accent_only", "interface_feedback_only", "motivated_only", "none",
    }),
    "graphics": frozenset({
        "auto", "brand_led", "data_driven", "informational", "minimal", "none",
    }),
    "transitions": frozenset({
        "auto",
        "beat_or_phrase_motivated",
        "continuity_motivated",
        "hard_cut_only",
        "location_motivated",
        "motivated_only",
        "none",
    }),
}

_PLATFORM_ASPECTS = {
    "youtube": frozenset({"16:9", "9:16", "1:1", "4:5"}),
    "youtube_shorts": frozenset({"9:16"}),
    "tiktok": frozenset({"9:16"}),
    "instagram_reels": frozenset({"9:16"}),
    "instagram_feed": frozenset({"4:5", "1:1"}),
    "facebook": frozenset({"16:9", "9:16", "4:5", "1:1"}),
    "x": frozenset({"16:9", "9:16", "1:1"}),
    "linkedin": frozenset({"16:9", "9:16", "4:5", "1:1"}),
    "web": ASPECTS,
    "broadcast": frozenset({"16:9"}),
    "archive": frozenset({"source", "16:9", "9:16", "4:5", "1:1"}),
}
if frozenset(_PLATFORM_ASPECTS) != PLATFORMS:
    raise RuntimeError("project-intent platform surface drifted from edit-policy/v1")

_ROOT_KEYS = frozenset({
    "schema_version", "profile", "delivery", "target_duration", "preferences",
})
_DELIVERY_KEYS = frozenset({"platform", "aspect"})
_TARGET_DURATION_KEYS = frozenset({"min_ms", "max_ms"})
_PREFERENCE_KEYS = frozenset({"enabled", "preference"})
_MANIFEST_KEYS = frozenset({
    "schema_version", "source", "probe_receipt_sha256", "available_capabilities",
})
_POLICY_FIELDS = (
    "cut_density",
    "sfx_density",
    "transition_density",
    "dialogue_rule",
    "music_rule",
    "caption_rule",
    "visualization_rule",
)
_ADDED_SFX_USAGES = frozenset({
    "event_accent_only", "interface_feedback_only", "motivated_only",
})
_TYPED_TRANSITION_USAGES = frozenset({
    "beat_or_phrase_motivated",
    "continuity_motivated",
    "location_motivated",
    "motivated_only",
})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ProjectIntentPolicyBridgeError(ValueError):
    """Project intent could not be represented or capability-gated safely."""


def _fail(message: str) -> None:
    raise ProjectIntentPolicyBridgeError(message)


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected, key=str)
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if extra:
            parts.append("unsupported " + ", ".join(str(item) for item in extra))
        _fail(f"{label} has invalid keys ({'; '.join(parts)})")
    return value


def _member(value: object, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(f"{label} is unsupported")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_DURATION_MS:
        _fail(f"{label} must be an integer from 1 to {MAX_DURATION_MS}")
    return value


def _normalize_preference(value: object, name: str) -> dict[str, object]:
    raw = _exact_keys(value, _PREFERENCE_KEYS, f"preferences.{name}")
    enabled = raw["enabled"]
    if type(enabled) is not bool:
        _fail(f"preferences.{name}.enabled must be boolean")
    preference = _member(
        raw["preference"], FEATURE_PREFERENCES[name], f"preferences.{name}.preference"
    )
    if not enabled and preference != "none":
        _fail(f"preferences.{name}.preference must be none when disabled")
    if enabled and preference == "none":
        _fail(f"preferences.{name}.preference cannot be none when enabled")
    return {"enabled": enabled, "preference": preference}


def validate_project_intent(value: object) -> dict[str, Any]:
    """Validate and detach the JavaScript ``autoeditor-project-intent/v1`` shape."""

    raw = _exact_keys(value, _ROOT_KEYS, "project intent")
    if raw["schema_version"] != PROJECT_INTENT_SCHEMA_VERSION:
        _fail("project intent schema_version is unsupported")
    profile = _member(raw["profile"], PROFILE_NAMES, "profile")

    raw_delivery = _exact_keys(raw["delivery"], _DELIVERY_KEYS, "delivery")
    platform = _member(raw_delivery["platform"], PLATFORMS, "delivery.platform")
    aspect = _member(raw_delivery["aspect"], ASPECTS, "delivery.aspect")
    if aspect not in _PLATFORM_ASPECTS[platform]:
        _fail(f"delivery.aspect {aspect} is incompatible with {platform}")

    raw_target = _exact_keys(
        raw["target_duration"], _TARGET_DURATION_KEYS, "target_duration"
    )
    minimum = _integer(raw_target["min_ms"], "target_duration.min_ms")
    maximum = _integer(raw_target["max_ms"], "target_duration.max_ms")
    if minimum > maximum:
        _fail("target_duration.min_ms cannot exceed target_duration.max_ms")

    raw_preferences = _exact_keys(
        raw["preferences"], frozenset(FEATURE_NAMES), "preferences"
    )
    normalized_preferences = {
        name: _normalize_preference(raw_preferences[name], name)
        for name in FEATURE_NAMES
    }
    return {
        "schema_version": PROJECT_INTENT_SCHEMA_VERSION,
        "profile": profile,
        "delivery": {"platform": platform, "aspect": aspect},
        "target_duration": {"min_ms": minimum, "max_ms": maximum},
        "preferences": normalized_preferences,
    }


def validate_capability_manifest(value: object) -> dict[str, Any]:
    """Validate and detach a locally verified capability receipt reference.

    Validation establishes contract shape, vocabulary, ordering, and receipt
    syntax.  Authenticating the referenced receipt remains the caller's trust
    boundary and must happen before this function is called.
    """

    raw = _exact_keys(value, _MANIFEST_KEYS, "capability manifest")
    if raw["schema_version"] != CAPABILITY_MANIFEST_SCHEMA_VERSION:
        _fail("capability manifest schema_version is unsupported")
    if raw["source"] != CAPABILITY_MANIFEST_SOURCE:
        _fail("capability manifest source is untrusted")
    receipt = raw["probe_receipt_sha256"]
    if type(receipt) is not str or _SHA256_RE.fullmatch(receipt) is None:
        _fail("capability manifest probe_receipt_sha256 must be lowercase SHA-256")

    available = raw["available_capabilities"]
    if type(available) is not list:
        _fail("capability manifest available_capabilities must be a sorted list")
    if any(type(item) is not str for item in available):
        _fail("capability manifest available_capabilities must contain strings")
    unknown = sorted(set(available) - CAPABILITIES)
    if unknown:
        _fail(
            "capability manifest available_capabilities has unsupported values: "
            + ", ".join(unknown)
        )
    if available != sorted(set(available)):
        _fail(
            "capability manifest available_capabilities must be sorted and unique"
        )
    return {
        "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "source": CAPABILITY_MANIFEST_SOURCE,
        "probe_receipt_sha256": receipt,
        "available_capabilities": list(available),
    }


def _auto_policy_values() -> dict[str, str]:
    return {field: "auto" for field in _POLICY_FIELDS}


def _map_preferences(project: dict[str, Any]) -> dict[str, str]:
    preferences = project["preferences"]
    captions = preferences["captions"]["preference"]
    graphics = preferences["graphics"]["preference"]
    music = preferences["music"]["preference"]
    sfx = preferences["sfx"]["preference"]
    transitions = preferences["transitions"]["preference"]

    if captions == "selective":
        _fail(
            "edit-policy/v1 cannot represent selective captions without weakening intent"
        )
    if graphics not in {"auto", "none"}:
        _fail(
            f"edit-policy/v1 cannot represent graphics preference {graphics} "
            "without losing its typed mode"
        )

    values = _auto_policy_values()
    values["caption_rule"] = {
        "auto": "auto",
        "none": "forbidden",
        "verbatim": "verbatim_required",
    }[captions]
    values["visualization_rule"] = {
        "auto": "auto",
        "none": "forbidden",
    }[graphics]
    values["music_rule"] = {
        "auto": "auto",
        "none": "forbidden",
        "primary": "primary",
        "source_primary": "source_primary",
        "supporting": "supporting",
    }[music]
    values["sfx_density"] = "none" if sfx == "none" else "auto"
    values["transition_density"] = (
        "none" if transitions in {"none", "hard_cut_only"} else "auto"
    )
    return values


def _build_request(
    project: dict[str, Any], capability_manifest: dict[str, Any]
) -> dict[str, Any]:
    minimum = project["target_duration"]["min_ms"]
    maximum = project["target_duration"]["max_ms"]
    try:
        minimum_band = duration_band(minimum)
        maximum_band = duration_band(maximum)
    except EditPolicyError as error:
        _fail(str(error))
    if minimum_band != maximum_band:
        _fail(
            "target_duration crosses edit-policy duration bands; "
            "split the range or choose bounds within one band"
        )

    return {
        "schema_version": EDIT_POLICY_REQUEST_SCHEMA_VERSION,
        "profile": project["profile"],
        # The upper bound is conservative for resource/cadence planning, and a
        # same-band check above guarantees it cannot change duration policy.
        "duration_ms": maximum,
        "delivery": copy.deepcopy(project["delivery"]),
        "explicit_intent": _map_preferences(project),
        "consented_preferences": {
            "consented": False,
            "values": _auto_policy_values(),
        },
        "available_capabilities": list(
            capability_manifest["available_capabilities"]
        ),
    }


def build_edit_policy_request(
    project_intent: object, capability_manifest: object
) -> dict[str, Any]:
    """Build a detached edit-policy request from two strict input contracts."""

    project = validate_project_intent(project_intent)
    manifest = validate_capability_manifest(capability_manifest)
    return _build_request(project, manifest)


def _verify_resolved_intent(project: dict[str, Any], policy: dict[str, Any]) -> None:
    preferences = project["preferences"]
    rules = policy["rules"]

    captions = preferences["captions"]["preference"]
    expected_caption = {
        "none": "forbidden",
        "verbatim": "verbatim_required",
    }.get(captions)
    if expected_caption is not None and rules["captions"]["usage"] != expected_caption:
        _fail("resolved edit policy did not preserve the caption preference")

    graphics = preferences["graphics"]["preference"]
    if graphics == "none" and rules["visualizations"]["usage"] != "forbidden":
        _fail("resolved edit policy did not preserve the graphics preference")

    music = preferences["music"]["preference"]
    expected_music = {
        "none": "forbidden",
        "primary": "primary",
        "source_primary": "source_primary",
        "supporting": "supporting",
    }.get(music)
    if expected_music is not None and rules["music"]["usage"] != expected_music:
        _fail("resolved edit policy did not preserve the music preference")

    sfx = preferences["sfx"]["preference"]
    if sfx == "none" and rules["sfx"]["density"] != "none":
        _fail("resolved edit policy did not preserve the disabled SFX preference")
    if sfx in _ADDED_SFX_USAGES:
        if rules["sfx"]["usage"] != sfx:
            _fail(
                f"edit policy profile {project['profile']} does not support requested "
                f"SFX usage {sfx}"
            )
        if rules["sfx"]["density"] == "none":
            _fail("resolved edit policy cannot enable the requested SFX usage")

    transitions = preferences["transitions"]["preference"]
    if transitions in {"none", "hard_cut_only"}:
        if rules["transitions"]["density"] != "none":
            _fail("resolved edit policy did not preserve the hard-cut preference")
    elif transitions in _TYPED_TRANSITION_USAGES:
        if rules["transitions"]["usage"] != transitions:
            _fail(
                f"edit policy profile {project['profile']} does not support requested "
                f"transition usage {transitions}"
            )
        if rules["transitions"]["density"] == "none":
            _fail("resolved edit policy cannot enable the requested transition usage")


def resolve_project_intent_policy(
    project_intent: object, capability_manifest: object
) -> dict[str, Any]:
    """Resolve project intent through edit-policy/v1 and all capability gates."""

    project = validate_project_intent(project_intent)
    manifest = validate_capability_manifest(capability_manifest)
    request = _build_request(project, manifest)
    try:
        policy = resolve_edit_policy(request)
    except EditPolicyError as error:
        raise ProjectIntentPolicyBridgeError(str(error)) from error
    _verify_resolved_intent(project, policy)
    return policy


__all__ = (
    "PROJECT_INTENT_SCHEMA_VERSION",
    "CAPABILITY_MANIFEST_SCHEMA_VERSION",
    "CAPABILITY_MANIFEST_SOURCE",
    "CURRENT_RUNTIME_CAPABILITIES",
    "FEATURE_NAMES",
    "FEATURE_PREFERENCES",
    "ProjectIntentPolicyBridgeError",
    "validate_project_intent",
    "validate_capability_manifest",
    "build_edit_policy_request",
    "resolve_project_intent_policy",
)
