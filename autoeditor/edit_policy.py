"""Closed expert policy resolver for deterministic, auditable video edits.

``autoeditor-edit-policy/v1`` is deliberately a policy contract, not an edit
decision list.  It resolves an approved project intent into bounded rules that
downstream planners and QA gates can enforce.  The resolver has one explicit
precedence order (highest first): hard invariants, explicit intent, delivery
platform, edit profile, duration band, then consented preferences.  A baseline
only fills fields on which every higher layer abstains.

The contract fails closed.  Unknown keys, profiles, enum members,
capabilities, incompatible aspects, unconsented preferences, and unsatisfied
capability gates are errors.  All serialized numbers are integer
milliseconds; canonical JSON therefore cannot contain NaN or floating-point
spelling differences.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import copy
import hashlib
import json
from typing import Any, Iterable


EDIT_POLICY_REQUEST_SCHEMA_VERSION = "autoeditor-edit-policy-request/v1"
EDIT_POLICY_SCHEMA_VERSION = "autoeditor-edit-policy/v1"
MAX_DURATION_MS = 86_400_000

CUT_DENSITIES = frozenset({"very_low", "low", "medium", "high", "very_high"})
EFFECT_DENSITIES = frozenset({"none", "sparse", "medium", "dense"})
DIALOGUE_RULES = frozenset({"none", "supporting", "primary", "verbatim"})
MUSIC_RULES = frozenset({
    "forbidden", "optional", "supporting", "primary", "source_primary",
})
CAPTION_RULES = frozenset({
    "forbidden", "optional", "required", "verbatim_required",
})
VISUALIZATION_RULES = frozenset({
    "forbidden", "allowed", "recommended", "required",
})

CUT_MOTIVATIONS = frozenset({
    "speech_motivated",
    "speaker_motivated",
    "instruction_step_motivated",
    "conversion_motivated",
    "story_motivated",
    "gameplay_event_motivated",
    "event_motivated",
    "sports_event_motivated",
    "beat_motivated",
    "space_continuity_motivated",
    "factual_narrative_motivated",
    "retention_motivated",
    "source_faithful",
})
JL_CUT_RULES = frozenset({
    "forbidden", "allowed_when_continuity_benefits", "preferred_for_dialogue",
})
SFX_USAGE_RULES = frozenset({
    "forbidden",
    "motivated_only",
    "interface_feedback_only",
    "event_accent_only",
    "source_only",
})
TRANSITION_USAGE_RULES = frozenset({
    "hard_cut_only",
    "motivated_only",
    "beat_or_phrase_motivated",
    "continuity_motivated",
    "location_motivated",
})

PLATFORMS = frozenset({
    "youtube",
    "youtube_shorts",
    "tiktok",
    "instagram_reels",
    "instagram_feed",
    "facebook",
    "x",
    "linkedin",
    "web",
    "broadcast",
    "archive",
})
ASPECTS = frozenset({"9:16", "16:9", "1:1", "4:5", "21:9", "source"})

CAPABILITIES = frozenset({
    "artifact_receipts",
    "audio_crossfades",
    "audio_quality_analysis",
    "beat_detection",
    "caption_rendering",
    "chart_rendering",
    "color_normalization",
    "cross_dissolves",
    "dialogue_cleanup",
    "graphic_rendering",
    "hard_cuts",
    "licensed_broll",
    "licensed_music",
    "licensed_sfx",
    "loudness_normalization",
    "motion_quality_analysis",
    "motion_tracking",
    "multicam_sync",
    "ocr",
    "project_generated_music",
    "project_generated_sfx",
    "replay",
    "scene_detection",
    "screen_content_detection",
    "slow_motion",
    "source_music_preservation",
    "speaker_diarization",
    "speech_transcription",
    "stabilization",
    "visual_quality_analysis",
    "word_timestamps",
})

RESOLUTION_SOURCES = frozenset({
    "hard_invariant",
    "explicit_intent",
    "platform",
    "profile",
    "duration",
    "consented_preferences",
    "baseline",
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
_REQUEST_KEYS = frozenset({
    "schema_version",
    "profile",
    "duration_ms",
    "delivery",
    "explicit_intent",
    "consented_preferences",
    "available_capabilities",
})
_DELIVERY_KEYS = frozenset({"platform", "aspect"})
_PREFERENCES_KEYS = frozenset({"consented", "values"})
_POLICY_KEYS = frozenset({
    "schema_version",
    "profile",
    "duration",
    "delivery",
    "rules",
    "resolution_sources",
    "required_capabilities",
    "forbidden_actions",
    "qa_checks",
})
_DURATION_KEYS = frozenset({"duration_ms", "band"})
_RULE_KEYS = frozenset({
    "cuts", "sfx", "transitions", "dialogue", "music", "captions",
    "visualizations",
})
_CUT_KEYS = frozenset({"density", "motivation", "j_l_cuts"})
_SFX_KEYS = frozenset({"density", "usage"})
_TRANSITION_KEYS = frozenset({"density", "usage"})
_DIALOGUE_KEYS = frozenset({"priority", "preserve_meaning"})
_MUSIC_KEYS = frozenset({"usage", "duck_under_dialogue"})
_CAPTION_KEYS = frozenset({"usage", "safe_area_required", "max_lines"})
_VISUALIZATION_KEYS = frozenset({"usage", "evidence_required"})


class EditPolicyError(ValueError):
    """The requested or resolved edit policy is unsafe or malformed."""


@dataclass(frozen=True)
class PolicyValues:
    """The seven soft policy values that participate in precedence."""

    cut_density: str | None = None
    sfx_density: str | None = None
    transition_density: str | None = None
    dialogue_rule: str | None = None
    music_rule: str | None = None
    caption_rule: str | None = None
    visualization_rule: str | None = None


@dataclass(frozen=True)
class ProfileSpec:
    values: PolicyValues
    cut_motivation: str
    j_l_cuts: str
    sfx_usage: str
    transition_usage: str
    required_capabilities: frozenset[str]
    forbidden_actions: frozenset[str]
    qa_checks: frozenset[str]


@dataclass(frozen=True)
class PlatformSpec:
    default_aspect: str
    allowed_aspects: frozenset[str]
    overrides: PolicyValues


@dataclass(frozen=True)
class DurationSpec:
    maximum_ms: int
    name: str
    overrides: PolicyValues


_BASELINE = PolicyValues(
    cut_density="medium",
    sfx_density="none",
    transition_density="sparse",
    dialogue_rule="supporting",
    music_rule="optional",
    caption_rule="optional",
    visualization_rule="allowed",
)

_DURATION_SPECS = (
    DurationSpec(15_000, "micro", PolicyValues(cut_density="high")),
    DurationSpec(60_000, "short", PolicyValues(cut_density="high")),
    DurationSpec(300_000, "medium", PolicyValues(cut_density="medium")),
    DurationSpec(1_800_000, "long", PolicyValues(cut_density="low")),
    DurationSpec(MAX_DURATION_MS, "extended", PolicyValues(cut_density="very_low")),
)
DURATION_BANDS = tuple(spec.name for spec in _DURATION_SPECS)


def _pv(
    cut: str | None,
    sfx: str | None,
    transition: str | None,
    dialogue: str | None,
    music: str | None,
    captions: str | None,
    visualizations: str | None,
) -> PolicyValues:
    return PolicyValues(
        cut, sfx, transition, dialogue, music, captions, visualizations
    )


_PROFILE_SPECS: dict[str, ProfileSpec] = {
    "dialogue_talking_head": ProfileSpec(
        _pv("high", "sparse", "sparse", "primary", "supporting", "required", "allowed"),
        "speech_motivated", "preferred_for_dialogue", "motivated_only", "motivated_only",
        frozenset({"scene_detection", "color_normalization"}),
        frozenset({"cover_speaking_face", "random_broll_without_anchor"}),
        frozenset({"face_framing_and_eyeline_verified", "jump_cut_cadence_reviewed"}),
    ),
    "podcast_interview": ProfileSpec(
        _pv(None, "none", "sparse", "primary", "supporting", "required", "allowed"),
        "speaker_motivated", "preferred_for_dialogue", "forbidden", "continuity_motivated",
        frozenset({"speaker_diarization", "multicam_sync", "scene_detection"}),
        frozenset({"speaker_misattribution", "reaction_retiming_misrepresentation"}),
        frozenset({"active_speaker_cut_verified", "speaker_label_accuracy_verified"}),
    ),
    "course_tutorial_screencast": ProfileSpec(
        _pv("medium", "sparse", "sparse", "primary", "optional", "required", "required"),
        "instruction_step_motivated", "allowed_when_continuity_benefits",
        "interface_feedback_only", "motivated_only",
        frozenset({
            "screen_content_detection", "ocr", "motion_tracking", "chart_rendering",
            "graphic_rendering",
        }),
        frozenset({"cover_critical_ui", "invent_instruction_step"}),
        frozenset({"critical_ui_visibility_verified", "instruction_order_verified"}),
    ),
    "commercial_product": ProfileSpec(
        _pv("high", "medium", "medium", "supporting", "supporting", "required", "recommended"),
        "conversion_motivated", "allowed_when_continuity_benefits", "motivated_only", "motivated_only",
        frozenset({"scene_detection", "graphic_rendering", "chart_rendering", "color_normalization"}),
        frozenset({"unsubstantiated_claim", "unauthorized_brand_asset"}),
        frozenset({"claim_evidence_verified", "brand_and_legal_approval_verified"}),
    ),
    "vlog_travel": ProfileSpec(
        _pv("high", "medium", None, "supporting", "supporting", "required", "allowed"),
        "story_motivated", "allowed_when_continuity_benefits", "motivated_only", "location_motivated",
        frozenset({"scene_detection", "stabilization", "color_normalization"}),
        frozenset({"misrepresent_location_as_fact", "unanchored_stock_replacement"}),
        frozenset({"location_continuity_reviewed", "unstable_shot_reviewed"}),
    ),
    "gaming": ProfileSpec(
        _pv("very_high", "medium", "sparse", "supporting", "optional", "required", "allowed"),
        "gameplay_event_motivated", "allowed_when_continuity_benefits",
        "event_accent_only", "motivated_only",
        frozenset({"scene_detection", "screen_content_detection", "ocr", "motion_tracking"}),
        frozenset({"cover_hud_or_objective", "fabricate_gameplay_outcome"}),
        frozenset({"hud_visibility_verified", "gameplay_event_order_verified"}),
    ),
    "wedding_event": ProfileSpec(
        _pv("medium", "sparse", "medium", "supporting", "supporting", None, "forbidden"),
        "event_motivated", "preferred_for_dialogue", "motivated_only", "continuity_motivated",
        frozenset({"scene_detection", "multicam_sync", "stabilization", "color_normalization"}),
        frozenset({"reorder_vows_to_change_meaning", "omit_named_must_keep_event"}),
        frozenset({"identity_continuity_verified", "ceremony_and_vows_integrity_verified"}),
    ),
    "sports_highlights": ProfileSpec(
        _pv("very_high", "dense", "medium", "supporting", "supporting", "optional", "recommended"),
        "sports_event_motivated", "allowed_when_continuity_benefits",
        "event_accent_only", "motivated_only",
        frozenset({
            "scene_detection", "motion_tracking", "slow_motion", "replay", "chart_rendering",
        }),
        frozenset({"fabricate_score_or_event_order", "present_replay_as_live"}),
        frozenset({"score_and_event_order_verified", "replay_labeling_verified"}),
    ),
    "music_performance": ProfileSpec(
        _pv("high", "sparse", "medium", "none", "source_primary", None, "forbidden"),
        "beat_motivated", "allowed_when_continuity_benefits", "source_only", "beat_or_phrase_motivated",
        frozenset({"beat_detection", "multicam_sync", "color_normalization"}),
        frozenset({"desynchronize_performance", "replace_source_performance_without_consent"}),
        frozenset({"performance_sync_verified", "musical_phrase_integrity_verified"}),
    ),
    "real_estate": ProfileSpec(
        _pv("medium", "sparse", "medium", "supporting", "supporting", None, "recommended"),
        "space_continuity_motivated", "allowed_when_continuity_benefits",
        "motivated_only", "continuity_motivated",
        frozenset({"scene_detection", "stabilization", "color_normalization", "graphic_rendering"}),
        frozenset({"alter_room_geometry", "hide_material_property_defect"}),
        frozenset({"room_identity_and_geometry_verified", "property_label_accuracy_verified"}),
    ),
    "documentary_narrative": ProfileSpec(
        _pv("low", "none", "sparse", "primary", "supporting", "required", "recommended"),
        "factual_narrative_motivated", "preferred_for_dialogue", "forbidden", "motivated_only",
        frozenset({
            "speaker_diarization", "scene_detection", "licensed_broll", "graphic_rendering",
            "chart_rendering",
        }),
        frozenset({"decontextualize_quote", "fabricate_archive_source"}),
        frozenset({"quote_context_verified", "archive_provenance_verified"}),
    ),
    "montage_meme": ProfileSpec(
        _pv("very_high", "dense", "medium", "supporting", "primary", "required", "allowed"),
        "retention_motivated", "allowed_when_continuity_benefits", "event_accent_only", "beat_or_phrase_motivated",
        frozenset({"scene_detection", "beat_detection", "graphic_rendering"}),
        frozenset({"unlicensed_meme_asset", "fabricate_subject_context"}),
        frozenset({"rights_and_sensitive_content_reviewed", "setup_payoff_comprehension_verified"}),
    ),
    "utility_faithful": ProfileSpec(
        _pv(None, "none", "none", "verbatim", "forbidden", None, "forbidden"),
        "source_faithful", "forbidden", "forbidden", "hard_cut_only",
        frozenset({"color_normalization"}),
        frozenset({"semantic_reordering", "decorative_overlay", "content_aware_reframe"}),
        frozenset({"source_content_fidelity_verified", "frame_and_audio_continuity_verified"}),
    ),
}
PROFILE_NAMES = frozenset(_PROFILE_SPECS)


_PLATFORM_SPECS: dict[str, PlatformSpec] = {
    "youtube": PlatformSpec("16:9", frozenset({"16:9", "9:16", "1:1", "4:5"}), PolicyValues()),
    "youtube_shorts": PlatformSpec("9:16", frozenset({"9:16"}), PolicyValues(cut_density="high", caption_rule="required")),
    "tiktok": PlatformSpec("9:16", frozenset({"9:16"}), PolicyValues(cut_density="high", caption_rule="required")),
    "instagram_reels": PlatformSpec("9:16", frozenset({"9:16"}), PolicyValues(cut_density="high", caption_rule="required")),
    "instagram_feed": PlatformSpec("4:5", frozenset({"4:5", "1:1"}), PolicyValues(caption_rule="required")),
    "facebook": PlatformSpec("16:9", frozenset({"16:9", "9:16", "4:5", "1:1"}), PolicyValues()),
    "x": PlatformSpec("16:9", frozenset({"16:9", "9:16", "1:1"}), PolicyValues(caption_rule="required")),
    "linkedin": PlatformSpec("16:9", frozenset({"16:9", "9:16", "4:5", "1:1"}), PolicyValues(caption_rule="required")),
    "web": PlatformSpec("source", ASPECTS, PolicyValues()),
    "broadcast": PlatformSpec("16:9", frozenset({"16:9"}), PolicyValues()),
    "archive": PlatformSpec("source", frozenset({"source", "16:9", "9:16", "4:5", "1:1"}), PolicyValues()),
}

_GLOBAL_REQUIRED_CAPABILITIES = frozenset({
    "artifact_receipts",
    "audio_quality_analysis",
    "hard_cuts",
    "loudness_normalization",
    "visual_quality_analysis",
})
_GLOBAL_FORBIDDEN_ACTIONS = frozenset({
    "fabricate_speech_or_event",
    "ship_failed_or_unverified_qa",
    "use_unlicensed_asset",
    "use_untraceable_source",
})
_GLOBAL_QA_CHECKS = frozenset({
    "artifact_hash_and_source_manifest_bound",
    "audio_decode_and_peak_ceiling_verified",
    "color_range_and_video_decode_verified",
    "loudness_delivery_target_verified",
    "manual_review_required_when_automated_qa_is_uncertain",
    "timeline_bounds_verified",
})

_HARD_EXACT: dict[str, dict[str, str]] = {
    "course_tutorial_screencast": {"visualization_rule": "required"},
    "music_performance": {"music_rule": "source_primary"},
    "utility_faithful": {
        "sfx_density": "none",
        "transition_density": "none",
        "dialogue_rule": "verbatim",
        "music_rule": "forbidden",
        "visualization_rule": "forbidden",
    },
}


def _fail(message: str) -> None:
    raise EditPolicyError(message)


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


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(f"{label} is unsupported")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be boolean")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _sorted_known_list(
    value: object,
    allowed: frozenset[str],
    label: str,
    *,
    allow_empty: bool = True,
) -> list[str]:
    if type(value) is not list or (not allow_empty and not value):
        _fail(f"{label} must be a{' non-empty' if not allow_empty else ''} list")
    clean = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        member = _enum(item, allowed, f"{label}[{index}]")
        if member in seen:
            _fail(f"{label} must not contain duplicates")
        seen.add(member)
        clean.append(member)
    return sorted(clean)


def _policy_enum(field: str) -> frozenset[str]:
    return {
        "cut_density": CUT_DENSITIES,
        "sfx_density": EFFECT_DENSITIES,
        "transition_density": EFFECT_DENSITIES,
        "dialogue_rule": DIALOGUE_RULES,
        "music_rule": MUSIC_RULES,
        "caption_rule": CAPTION_RULES,
        "visualization_rule": VISUALIZATION_RULES,
    }[field]


def _parse_policy_values(value: object, label: str) -> PolicyValues:
    raw = _exact_keys(value, frozenset(_POLICY_FIELDS), label)
    parsed: dict[str, str | None] = {}
    for field in _POLICY_FIELDS:
        member = raw[field]
        if member == "auto":
            parsed[field] = None
        else:
            parsed[field] = _enum(member, _policy_enum(field), f"{label}.{field}")
    return PolicyValues(**parsed)


def _values_dict(values: PolicyValues) -> dict[str, str | None]:
    return {field.name: getattr(values, field.name) for field in fields(PolicyValues)}


def duration_band(duration_ms: object) -> str:
    duration = _integer(duration_ms, "duration_ms", 1, MAX_DURATION_MS)
    for spec in _DURATION_SPECS:
        if duration <= spec.maximum_ms:
            return spec.name
    raise AssertionError("duration band table does not cover MAX_DURATION_MS")


def _duration_spec(duration_ms: int) -> DurationSpec:
    band = duration_band(duration_ms)
    return next(spec for spec in _DURATION_SPECS if spec.name == band)


def _overlay(
    resolved: dict[str, str],
    sources: dict[str, str],
    values: PolicyValues,
    source: str,
) -> None:
    for field, member in _values_dict(values).items():
        if member is not None:
            resolved[field] = member
            sources[field] = source


def _apply_hard_invariants(
    profile: str,
    resolved: dict[str, str],
    sources: dict[str, str],
) -> None:
    for field, required in _HARD_EXACT.get(profile, {}).items():
        if resolved[field] != required and sources[field] == "explicit_intent":
            _fail(
                f"explicit_intent.{field} conflicts with the {profile} hard invariant"
            )
        resolved[field] = required
        sources[field] = "hard_invariant"
    if profile == "wedding_event" and resolved["sfx_density"] not in {"none", "sparse"}:
        _fail("wedding_event hard invariant permits only none or sparse SFX")
    if profile == "documentary_narrative" and resolved["dialogue_rule"] not in {"primary", "verbatim"}:
        _fail("documentary_narrative hard invariant requires grounded primary dialogue")
    spec = _PROFILE_SPECS[profile]
    if spec.sfx_usage == "forbidden" and resolved["sfx_density"] != "none":
        _fail(f"{profile} forbids added SFX, so sfx_density must be none")
    if (
        spec.transition_usage == "hard_cut_only"
        and resolved["transition_density"] != "none"
    ):
        _fail(f"{profile} permits hard cuts only, so transition_density must be none")


def _required_capabilities(profile: str, resolved: dict[str, str]) -> list[str]:
    spec = _PROFILE_SPECS[profile]
    required = set(_GLOBAL_REQUIRED_CAPABILITIES | spec.required_capabilities)
    dialogue = resolved["dialogue_rule"]
    if dialogue in {"primary", "verbatim"}:
        required.update({"speech_transcription", "word_timestamps", "dialogue_cleanup"})
    elif dialogue == "supporting":
        required.add("dialogue_cleanup")
    if resolved["caption_rule"] != "forbidden":
        required.add("caption_rendering")
    if resolved["caption_rule"] == "verbatim_required":
        required.update({"speech_transcription", "word_timestamps"})
    if resolved["music_rule"] == "supporting":
        # Governed supporting music is synthesized locally from a closed PCM
        # generator and carries project-owned byte evidence.  It must never be
        # represented as a catalog/external `licensed_music` capability.
        required.add("project_generated_music")
    elif resolved["music_rule"] == "primary":
        # Primary/external music remains unavailable until a separately
        # authenticated license-selection path exists.
        required.add("licensed_music")
    elif resolved["music_rule"] == "source_primary":
        required.add("source_music_preservation")
    if resolved["sfx_density"] != "none" and spec.sfx_usage != "source_only":
        # The v1 production planner creates deterministic project-owned cue
        # bytes and persists their generator/rights preimage. It never selects
        # an external catalog, so `licensed_sfx` would be a false capability
        # claim. A future source-selection rule may require that separately.
        required.add("project_generated_sfx")
    if resolved["transition_density"] != "none":
        required.update({"audio_crossfades", "cross_dissolves", "motion_quality_analysis"})
    if resolved["visualization_rule"] in {"recommended", "required"}:
        required.add("graphic_rendering")
    return sorted(required)


def _forbidden_actions(profile: str) -> list[str]:
    return sorted(_GLOBAL_FORBIDDEN_ACTIONS | _PROFILE_SPECS[profile].forbidden_actions)


def _qa_checks(profile: str, resolved: dict[str, str]) -> list[str]:
    spec = _PROFILE_SPECS[profile]
    checks = set(_GLOBAL_QA_CHECKS | spec.qa_checks)
    if resolved["dialogue_rule"] != "none":
        checks.update({"dialogue_intelligibility_verified", "dialogue_sync_verified"})
    if resolved["caption_rule"] != "forbidden":
        checks.update({
            "caption_safe_area_and_contrast_verified",
            "caption_text_and_timing_verified",
        })
    if resolved["music_rule"] == "supporting":
        checks.update({
            "dialogue_music_masking_verified",
            "project_generated_music_rights_verified",
        })
    elif resolved["music_rule"] == "primary":
        checks.update({"dialogue_ducking_verified", "music_license_receipt_verified"})
    elif resolved["music_rule"] == "source_primary":
        checks.add("source_music_integrity_verified")
    if resolved["sfx_density"] != "none" and spec.sfx_usage != "source_only":
        checks.update({
            "sfx_generation_and_rights_receipt_verified",
            "sfx_motivation_and_masking_verified",
        })
    if resolved["transition_density"] != "none":
        checks.update({"transition_audio_continuity_verified", "transition_motivation_verified"})
    if resolved["visualization_rule"] != "forbidden":
        checks.update({"visualization_data_provenance_verified", "visualization_legibility_verified"})
    return sorted(checks)


def _make_rules(profile: str, resolved: dict[str, str]) -> dict[str, Any]:
    spec = _PROFILE_SPECS[profile]
    music_usage = resolved["music_rule"]
    dialogue_priority = resolved["dialogue_rule"]
    return {
        "cuts": {
            "density": resolved["cut_density"],
            "motivation": spec.cut_motivation,
            "j_l_cuts": spec.j_l_cuts,
        },
        "sfx": {"density": resolved["sfx_density"], "usage": spec.sfx_usage},
        "transitions": {
            "density": resolved["transition_density"],
            "usage": spec.transition_usage,
        },
        "dialogue": {"priority": dialogue_priority, "preserve_meaning": True},
        "music": {
            "usage": music_usage,
            "duck_under_dialogue": (
                music_usage in {"supporting", "primary"}
                and dialogue_priority != "none"
            ),
        },
        "captions": {
            "usage": resolved["caption_rule"],
            "safe_area_required": True,
            "max_lines": 2,
        },
        "visualizations": {
            "usage": resolved["visualization_rule"],
            "evidence_required": True,
        },
    }


def resolve_edit_policy(request: object) -> dict[str, Any]:
    """Resolve and capability-gate an ``autoeditor-edit-policy-request/v1``.

    The returned mapping is detached from the request and safe to hash with
    :func:`edit_policy_sha256`.  Extra available capabilities do not affect the
    resolved policy or its hash.
    """
    raw = _exact_keys(request, _REQUEST_KEYS, "edit policy request")
    if raw["schema_version"] != EDIT_POLICY_REQUEST_SCHEMA_VERSION:
        _fail("edit policy request schema_version is unsupported")
    profile = _enum(raw["profile"], PROFILE_NAMES, "profile")
    duration_ms = _integer(raw["duration_ms"], "duration_ms", 1, MAX_DURATION_MS)

    delivery = _exact_keys(raw["delivery"], _DELIVERY_KEYS, "delivery")
    platform = _enum(delivery["platform"], PLATFORMS, "delivery.platform")
    requested_aspect = delivery["aspect"]
    if requested_aspect != "auto":
        requested_aspect = _enum(requested_aspect, ASPECTS, "delivery.aspect")
    platform_spec = _PLATFORM_SPECS[platform]
    aspect = platform_spec.default_aspect if requested_aspect == "auto" else requested_aspect
    if aspect not in platform_spec.allowed_aspects:
        _fail(f"delivery.aspect {aspect} is incompatible with {platform}")

    explicit = _parse_policy_values(raw["explicit_intent"], "explicit_intent")
    preferences = _exact_keys(
        raw["consented_preferences"], _PREFERENCES_KEYS, "consented_preferences"
    )
    consented = _boolean(preferences["consented"], "consented_preferences.consented")
    preference_values = _parse_policy_values(
        preferences["values"], "consented_preferences.values"
    )
    if not consented and any(
        value is not None for value in _values_dict(preference_values).values()
    ):
        _fail("unconsented preference values must all be auto")

    available = _sorted_known_list(
        raw["available_capabilities"], CAPABILITIES, "available_capabilities"
    )

    resolved: dict[str, str] = {}
    sources: dict[str, str] = {}
    _overlay(resolved, sources, _BASELINE, "baseline")
    if consented:
        _overlay(resolved, sources, preference_values, "consented_preferences")
    duration_spec = _duration_spec(duration_ms)
    _overlay(resolved, sources, duration_spec.overrides, "duration")
    _overlay(resolved, sources, _PROFILE_SPECS[profile].values, "profile")
    _overlay(resolved, sources, platform_spec.overrides, "platform")
    _overlay(resolved, sources, explicit, "explicit_intent")
    _apply_hard_invariants(profile, resolved, sources)

    required = _required_capabilities(profile, resolved)
    missing = sorted(set(required) - set(available))
    if missing:
        _fail("capability gate failed; missing: " + ", ".join(missing))

    sources["aspect"] = (
        "platform" if requested_aspect == "auto" else "explicit_intent"
    )
    policy = {
        "schema_version": EDIT_POLICY_SCHEMA_VERSION,
        "profile": profile,
        "duration": {"duration_ms": duration_ms, "band": duration_spec.name},
        "delivery": {"platform": platform, "aspect": aspect},
        "rules": _make_rules(profile, resolved),
        "resolution_sources": sources,
        "required_capabilities": required,
        "forbidden_actions": _forbidden_actions(profile),
        "qa_checks": _qa_checks(profile, resolved),
    }
    return validate_edit_policy(policy)


def _validate_sorted_exact_list(
    value: object,
    expected: Iterable[str],
    label: str,
) -> list[str]:
    expected_list = sorted(expected)
    if type(value) is not list or value != expected_list:
        _fail(f"{label} must exactly equal its sorted derived contract")
    if any(type(item) is not str for item in value):
        _fail(f"{label} must contain strings")
    return list(value)


def validate_edit_policy(policy: object) -> dict[str, Any]:
    """Validate and detach a resolved ``autoeditor-edit-policy/v1`` mapping."""
    raw = _exact_keys(policy, _POLICY_KEYS, "edit policy")
    if raw["schema_version"] != EDIT_POLICY_SCHEMA_VERSION:
        _fail("edit policy schema_version is unsupported")
    profile = _enum(raw["profile"], PROFILE_NAMES, "profile")
    spec = _PROFILE_SPECS[profile]

    duration = _exact_keys(raw["duration"], _DURATION_KEYS, "duration")
    duration_ms = _integer(duration["duration_ms"], "duration.duration_ms", 1, MAX_DURATION_MS)
    band = _enum(duration["band"], frozenset(DURATION_BANDS), "duration.band")
    if band != duration_band(duration_ms):
        _fail("duration.band does not match duration.duration_ms")

    delivery = _exact_keys(raw["delivery"], _DELIVERY_KEYS, "delivery")
    platform = _enum(delivery["platform"], PLATFORMS, "delivery.platform")
    aspect = _enum(delivery["aspect"], ASPECTS, "delivery.aspect")
    if aspect not in _PLATFORM_SPECS[platform].allowed_aspects:
        _fail("delivery aspect is incompatible with its platform")

    rules = _exact_keys(raw["rules"], _RULE_KEYS, "rules")
    cuts = _exact_keys(rules["cuts"], _CUT_KEYS, "rules.cuts")
    cut_density = _enum(cuts["density"], CUT_DENSITIES, "rules.cuts.density")
    if _enum(cuts["motivation"], CUT_MOTIVATIONS, "rules.cuts.motivation") != spec.cut_motivation:
        _fail("rules.cuts.motivation does not match profile")
    if _enum(cuts["j_l_cuts"], JL_CUT_RULES, "rules.cuts.j_l_cuts") != spec.j_l_cuts:
        _fail("rules.cuts.j_l_cuts does not match profile")

    sfx = _exact_keys(rules["sfx"], _SFX_KEYS, "rules.sfx")
    sfx_density = _enum(sfx["density"], EFFECT_DENSITIES, "rules.sfx.density")
    if _enum(sfx["usage"], SFX_USAGE_RULES, "rules.sfx.usage") != spec.sfx_usage:
        _fail("rules.sfx.usage does not match profile")

    transitions = _exact_keys(
        rules["transitions"], _TRANSITION_KEYS, "rules.transitions"
    )
    transition_density = _enum(
        transitions["density"], EFFECT_DENSITIES, "rules.transitions.density"
    )
    if _enum(
        transitions["usage"], TRANSITION_USAGE_RULES, "rules.transitions.usage"
    ) != spec.transition_usage:
        _fail("rules.transitions.usage does not match profile")

    dialogue = _exact_keys(rules["dialogue"], _DIALOGUE_KEYS, "rules.dialogue")
    dialogue_rule = _enum(dialogue["priority"], DIALOGUE_RULES, "rules.dialogue.priority")
    if _boolean(dialogue["preserve_meaning"], "rules.dialogue.preserve_meaning") is not True:
        _fail("rules.dialogue.preserve_meaning is a hard invariant")

    music = _exact_keys(rules["music"], _MUSIC_KEYS, "rules.music")
    music_rule = _enum(music["usage"], MUSIC_RULES, "rules.music.usage")
    expected_duck = music_rule in {"supporting", "primary"} and dialogue_rule != "none"
    if _boolean(music["duck_under_dialogue"], "rules.music.duck_under_dialogue") != expected_duck:
        _fail("rules.music.duck_under_dialogue is inconsistent")

    captions = _exact_keys(rules["captions"], _CAPTION_KEYS, "rules.captions")
    caption_rule = _enum(captions["usage"], CAPTION_RULES, "rules.captions.usage")
    if _boolean(captions["safe_area_required"], "rules.captions.safe_area_required") is not True:
        _fail("rules.captions.safe_area_required is a hard invariant")
    if _integer(captions["max_lines"], "rules.captions.max_lines", 1, 2) != 2:
        _fail("rules.captions.max_lines must be 2 in v1")

    visualizations = _exact_keys(
        rules["visualizations"], _VISUALIZATION_KEYS, "rules.visualizations"
    )
    visualization_rule = _enum(
        visualizations["usage"], VISUALIZATION_RULES, "rules.visualizations.usage"
    )
    if _boolean(
        visualizations["evidence_required"], "rules.visualizations.evidence_required"
    ) is not True:
        _fail("rules.visualizations.evidence_required is a hard invariant")

    resolved = {
        "cut_density": cut_density,
        "sfx_density": sfx_density,
        "transition_density": transition_density,
        "dialogue_rule": dialogue_rule,
        "music_rule": music_rule,
        "caption_rule": caption_rule,
        "visualization_rule": visualization_rule,
    }
    invariant_probe = dict(resolved)
    invariant_sources = {field: "profile" for field in _POLICY_FIELDS}
    _apply_hard_invariants(profile, invariant_probe, invariant_sources)
    if invariant_probe != resolved:
        _fail("resolved rules violate a profile hard invariant")

    resolution_sources = _exact_keys(
        raw["resolution_sources"], frozenset((*_POLICY_FIELDS, "aspect")),
        "resolution_sources",
    )
    normalized_sources = {
        key: _enum(value, RESOLUTION_SOURCES, f"resolution_sources.{key}")
        for key, value in resolution_sources.items()
    }
    for field in _HARD_EXACT.get(profile, {}):
        if normalized_sources[field] != "hard_invariant":
            _fail(f"resolution_sources.{field} must record its hard invariant")

    required = _required_capabilities(profile, resolved)
    _validate_sorted_exact_list(
        raw["required_capabilities"], required, "required_capabilities"
    )
    forbidden = _forbidden_actions(profile)
    _validate_sorted_exact_list(raw["forbidden_actions"], forbidden, "forbidden_actions")
    checks = _qa_checks(profile, resolved)
    _validate_sorted_exact_list(raw["qa_checks"], checks, "qa_checks")

    normalized = {
        "schema_version": EDIT_POLICY_SCHEMA_VERSION,
        "profile": profile,
        "duration": {"duration_ms": duration_ms, "band": band},
        "delivery": {"platform": platform, "aspect": aspect},
        "rules": {
            "cuts": {
                "density": cut_density,
                "motivation": spec.cut_motivation,
                "j_l_cuts": spec.j_l_cuts,
            },
            "sfx": {"density": sfx_density, "usage": spec.sfx_usage},
            "transitions": {
                "density": transition_density,
                "usage": spec.transition_usage,
            },
            "dialogue": {"priority": dialogue_rule, "preserve_meaning": True},
            "music": {"usage": music_rule, "duck_under_dialogue": expected_duck},
            "captions": {
                "usage": caption_rule,
                "safe_area_required": True,
                "max_lines": 2,
            },
            "visualizations": {
                "usage": visualization_rule,
                "evidence_required": True,
            },
        },
        "resolution_sources": normalized_sources,
        "required_capabilities": required,
        "forbidden_actions": forbidden,
        "qa_checks": checks,
    }
    return copy.deepcopy(normalized)


def canonical_edit_policy_json(policy: object) -> str:
    """Return normalized, key-sorted, whitespace-free ASCII JSON."""
    try:
        return json.dumps(
            validate_edit_policy(policy),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, EditPolicyError):
            raise
        raise EditPolicyError("edit policy is not canonical JSON") from error


def edit_policy_sha256(policy: object) -> str:
    """Return the SHA-256 digest of :func:`canonical_edit_policy_json`."""
    payload = canonical_edit_policy_json(policy).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
