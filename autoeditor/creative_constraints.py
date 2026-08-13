"""Closed, user-approved creative constraints for a premium edit.

The prose brief remains useful director context, but it is not executable.
This module is the small deterministic contract that makes visual promises
machine-checkable before planning and again before release.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata


SCHEMA_VERSION = "autoeditor-creative-constraints/v1"
GRAPHIC_KINDS = frozenset({"keyword", "stat", "callout", "bars"})
_ROOT_KEYS = frozenset({
    "schema_version", "opener", "visual_policy", "required_graphic",
    "music_allowed",
})
_OPENER_KEYS = frozenset({"exact_text", "max_start_seconds"})
_VISUAL_KEYS = frozenset({
    "graphics_exact", "broll_exact", "opening_punch_required",
    "opening_visual_required", "max_visual_gap_seconds",
})
_GRAPHIC_KEYS = frozenset({"kind", "text", "anchor_text"})
_APOSTROPHE_TRANSLATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u02bc": "'", "\uff07": "'",
})


class CreativeConstraintsError(ValueError):
    """The approved creative policy is malformed or internally inconsistent."""


def canonical_text(value: object) -> str:
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))
    ).strip()


def word_tokens(value: object) -> list[str]:
    """Use one token boundary contract for constraints and creative QA."""
    text = canonical_text(value).translate(_APOSTROPHE_TRANSLATION).lower()
    return re.findall(r"[a-z0-9']+", text)


def _plain_dict(value: object, keys: frozenset[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise CreativeConstraintsError(
            f"{label} must contain exactly: {', '.join(sorted(keys))}"
        )
    return value


def _bounded_number(value: object, label: str, low: float,
                    high: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not low <= float(value) <= high):
        raise CreativeConstraintsError(
            f"{label} must be a finite number from {low:g} to {high:g}"
        )
    return float(value)


def _exact_count(value: object, label: str) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not 0 <= value <= 16):
        raise CreativeConstraintsError(f"{label} must be an integer from 0 to 16")
    return value


def validate_creative_constraints(raw: object) -> dict:
    root = _plain_dict(raw, _ROOT_KEYS, "creative constraints")
    if root["schema_version"] != SCHEMA_VERSION:
        raise CreativeConstraintsError("creative constraints schema is unsupported")

    opener = _plain_dict(root["opener"], _OPENER_KEYS, "opener")
    opener_text = canonical_text(opener["exact_text"])
    if not opener_text or len(opener_text) > 160:
        raise CreativeConstraintsError("opener.exact_text must contain 1-160 characters")
    opener_start = _bounded_number(
        opener["max_start_seconds"], "opener.max_start_seconds", 0, 10
    )

    policy = _plain_dict(
        root["visual_policy"], _VISUAL_KEYS, "visual_policy"
    )
    graphics_exact = _exact_count(
        policy["graphics_exact"], "visual_policy.graphics_exact"
    )
    broll_exact = _exact_count(
        policy["broll_exact"], "visual_policy.broll_exact"
    )
    for key in ("opening_punch_required", "opening_visual_required"):
        if not isinstance(policy[key], bool):
            raise CreativeConstraintsError(f"visual_policy.{key} must be boolean")
    raw_gap = policy["max_visual_gap_seconds"]
    max_gap = None if raw_gap is None else _bounded_number(
        raw_gap, "visual_policy.max_visual_gap_seconds", 1, 300
    )

    required = root["required_graphic"]
    clean_graphic = None
    if required is not None:
        graphic = _plain_dict(required, _GRAPHIC_KEYS, "required_graphic")
        if graphics_exact != 1:
            raise CreativeConstraintsError(
                "required_graphic requires visual_policy.graphics_exact=1"
            )
        kind = canonical_text(graphic["kind"]).lower()
        text = canonical_text(graphic["text"])
        anchor = canonical_text(graphic["anchor_text"])
        if kind not in GRAPHIC_KINDS:
            raise CreativeConstraintsError("required_graphic.kind is unsupported")
        if (not text or len(text) > 44 or text != text.upper()
                or len(re.findall(r"[A-Za-z0-9']+", text)) > 4):
            raise CreativeConstraintsError(
                "required_graphic.text must be uppercase, at most 44 characters "
                "and four words"
            )
        if (not anchor or len(anchor) > 200
                or not 5 <= len(word_tokens(anchor)) <= 20):
            raise CreativeConstraintsError(
                "required_graphic.anchor_text must contain 5-20 exact words "
                "and at most 200 characters"
            )
        clean_graphic = {"kind": kind, "text": text, "anchor_text": anchor}
    elif graphics_exact == 1:
        raise CreativeConstraintsError(
            "one exact graphic requires a required_graphic specification"
        )

    if not isinstance(root["music_allowed"], bool):
        raise CreativeConstraintsError("music_allowed must be boolean")

    return {
        "schema_version": SCHEMA_VERSION,
        "opener": {
            "exact_text": opener_text,
            "max_start_seconds": opener_start,
        },
        "visual_policy": {
            "graphics_exact": graphics_exact,
            "broll_exact": broll_exact,
            "opening_punch_required": policy["opening_punch_required"],
            "opening_visual_required": policy["opening_visual_required"],
            "max_visual_gap_seconds": max_gap,
        },
        "required_graphic": clean_graphic,
        "music_allowed": root["music_allowed"],
    }


def canonical_json(value: object) -> str:
    return json.dumps(
        validate_creative_constraints(value), ensure_ascii=True,
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    )


def constraints_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
