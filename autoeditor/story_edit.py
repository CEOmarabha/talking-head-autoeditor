"""Strict, deterministic contract for transcript-grounded story cuts.

Story plans in this module always address the untouched source timeline.  They
cannot be validated against a transcript made after silence removal or another
edit because both the word indices and timestamps would then describe a
different artifact.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from typing import Any


STORY_PLAN_SCHEMA_VERSION = "autoeditor-story-edit/v1"
SOURCE_TIMELINE = "source_seconds"
DEFAULT_DURATION_TOLERANCE_SECONDS = 0.05
WORD_BOUNDARY_TOLERANCE_SECONDS = 0.001

_PLAN_KEYS = frozenset({
    "schema_version",
    "timeline",
    "target_duration",
    "hook_anchor_id",
    "closer_anchor_id",
    "keep_ranges",
})
_TARGET_KEYS = frozenset({"min_seconds", "max_seconds"})
_RANGE_KEYS = frozenset({
    "anchor_id",
    "anchor_text",
    "source_start_word",
    "source_end_word",
    "source_start_seconds",
    "source_end_seconds",
})
_ANCHOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


STORY_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "timeline",
        "target_duration",
        "hook_anchor_id",
        "closer_anchor_id",
        "keep_ranges",
    ],
    "properties": {
        "schema_version": {"const": STORY_PLAN_SCHEMA_VERSION},
        "timeline": {"const": SOURCE_TIMELINE},
        "target_duration": {
            "type": "object",
            "additionalProperties": False,
            "required": ["min_seconds", "max_seconds"],
            "properties": {
                "min_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                },
                "max_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                },
            },
        },
        "hook_anchor_id": {
            "type": "string",
            "pattern": _ANCHOR_ID.pattern,
        },
        "closer_anchor_id": {
            "type": "string",
            "pattern": _ANCHOR_ID.pattern,
        },
        "keep_ranges": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "anchor_id",
                    "anchor_text",
                    "source_start_word",
                    "source_end_word",
                    "source_start_seconds",
                    "source_end_seconds",
                ],
                "properties": {
                    "anchor_id": {
                        "type": "string",
                        "pattern": _ANCHOR_ID.pattern,
                    },
                    "anchor_text": {"type": "string", "minLength": 1},
                    "source_start_word": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "source_end_word": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "source_start_seconds": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "source_end_seconds": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                },
            },
        },
    },
}


class StoryEditContractError(ValueError):
    """A story plan cannot be safely grounded in its source transcript."""


def _fail(message: str) -> None:
    raise StoryEditContractError(message)


def _exact_keys(value: object, expected: frozenset[str], label: str) -> dict:
    if not isinstance(value, dict):
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


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{label} must be a finite number")
    return 0.0 if number == 0 else number


def _nonnegative_number(value: object, label: str) -> float:
    number = _finite_number(value, label)
    if number < 0:
        _fail(f"{label} must be nonnegative")
    return number


def _word_index(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{label} must be an integer")
    if value < 0:
        _fail(f"{label} must be nonnegative")
    return value


def _canonical_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        _fail(f"{label} must be a string")
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    if not text:
        _fail(f"{label} must not be empty")
    return text


def _anchor_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ANCHOR_ID.fullmatch(value):
        _fail(
            f"{label} must be a 1-64 character ASCII anchor identifier"
        )
    return value


def _normalized_structure(plan: object) -> dict[str, Any]:
    source = _exact_keys(plan, _PLAN_KEYS, "story plan")
    if source["schema_version"] != STORY_PLAN_SCHEMA_VERSION:
        _fail("story plan schema_version is unsupported")
    if source["timeline"] != SOURCE_TIMELINE:
        _fail("story plan timeline must be source_seconds")

    target = _exact_keys(
        source["target_duration"], _TARGET_KEYS, "target_duration"
    )
    minimum = _finite_number(target["min_seconds"], "target min_seconds")
    maximum = _finite_number(target["max_seconds"], "target max_seconds")
    if minimum <= 0 or maximum <= 0:
        _fail("target duration bounds must be greater than zero")
    if minimum > maximum:
        _fail("target min_seconds cannot exceed max_seconds")

    hook_id = _anchor_id(source["hook_anchor_id"], "hook_anchor_id")
    closer_id = _anchor_id(source["closer_anchor_id"], "closer_anchor_id")
    if hook_id == closer_id:
        _fail("hook_anchor_id and closer_anchor_id must be distinct")

    raw_ranges = source["keep_ranges"]
    if not isinstance(raw_ranges, list) or len(raw_ranges) < 2:
        _fail("keep_ranges must contain at least a hook and closer range")

    ranges = []
    seen_ids: set[str] = set()
    previous_end_word = -1
    previous_end_seconds = 0.0
    for index, raw in enumerate(raw_ranges):
        label = f"keep_ranges[{index}]"
        item = _exact_keys(raw, _RANGE_KEYS, label)
        anchor = _anchor_id(item["anchor_id"], f"{label}.anchor_id")
        if anchor in seen_ids:
            _fail(f"{label}.anchor_id must be unique")
        seen_ids.add(anchor)

        anchor_text = _canonical_text(
            item["anchor_text"], f"{label}.anchor_text"
        )
        if not any(character.isalnum() for character in anchor_text):
            _fail(f"{label}.anchor_text must contain a spoken word")

        start_word = _word_index(
            item["source_start_word"], f"{label}.source_start_word"
        )
        end_word = _word_index(
            item["source_end_word"], f"{label}.source_end_word"
        )
        if start_word > end_word:
            _fail(f"{label} has a reversed source word span")
        if start_word <= previous_end_word:
            _fail("keep_ranges word spans must be ordered and non-overlapping")

        start_seconds = _nonnegative_number(
            item["source_start_seconds"],
            f"{label}.source_start_seconds",
        )
        end_seconds = _nonnegative_number(
            item["source_end_seconds"], f"{label}.source_end_seconds"
        )
        if start_seconds >= end_seconds:
            _fail(f"{label} must have positive duration")
        if index and start_seconds < previous_end_seconds:
            _fail("keep_ranges times must be ordered and non-overlapping")

        ranges.append({
            "anchor_id": anchor,
            "anchor_text": anchor_text,
            "source_start_word": start_word,
            "source_end_word": end_word,
            "source_start_seconds": start_seconds,
            "source_end_seconds": end_seconds,
        })
        previous_end_word = end_word
        previous_end_seconds = end_seconds

    if hook_id != ranges[0]["anchor_id"]:
        _fail("hook_anchor_id must identify the first keep range")
    if closer_id != ranges[-1]["anchor_id"]:
        _fail("closer_anchor_id must identify the last keep range")

    return {
        "schema_version": STORY_PLAN_SCHEMA_VERSION,
        "timeline": SOURCE_TIMELINE,
        "target_duration": {
            "min_seconds": minimum,
            "max_seconds": maximum,
        },
        "hook_anchor_id": hook_id,
        "closer_anchor_id": closer_id,
        "keep_ranges": ranges,
    }


def _normalized_words(words: object, source_duration: float) -> list[dict]:
    if not isinstance(words, list) or not words:
        _fail("source transcript must contain timed words")

    normalized = []
    previous_start = -1.0
    previous_end = -1.0
    for index, raw in enumerate(words):
        label = f"words[{index}]"
        if not isinstance(raw, dict):
            _fail(f"{label} must be an object")
        missing = {"w", "s", "e"} - set(raw)
        if missing:
            _fail(f"{label} is missing required transcript fields")
        word = _canonical_text(raw["w"], f"{label}.w")
        start = _nonnegative_number(raw["s"], f"{label}.s")
        end = _nonnegative_number(raw["e"], f"{label}.e")
        if start >= end:
            _fail(f"{label} must have positive duration")
        if end > source_duration:
            _fail(f"{label} ends beyond source_duration")
        if start < previous_start or end < previous_end:
            _fail("source transcript words must be chronologically ordered")
        normalized.append({"w": word, "s": start, "e": end})
        previous_start = start
        previous_end = end
    return normalized


def kept_duration(plan: object) -> float:
    """Return the sum of the plan's kept source-time ranges.

    This performs closed-schema structural validation but cannot prove
    transcript grounding without the source words; use ``validate_story_plan``
    before applying a plan.
    """
    normalized = _normalized_structure(plan)
    return math.fsum(
        item["source_end_seconds"] - item["source_start_seconds"]
        for item in normalized["keep_ranges"]
    )


def validate_story_plan(
    plan: object,
    words: object,
    source_duration: object,
    *,
    duration_tolerance: object = DEFAULT_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Validate and normalize a source-timeline plan against every word.

    Word indices are inclusive.  Every keep range must reproduce the exact
    NFKC/whitespace-normalized transcript text for its span, and its times are
    snapped to the selected source word boundaries after a one-millisecond
    alignment check.  Any mismatch raises :class:`StoryEditContractError`.
    """
    duration = _finite_number(source_duration, "source_duration")
    if duration <= 0:
        _fail("source_duration must be greater than zero")
    tolerance = _finite_number(duration_tolerance, "duration_tolerance")
    if tolerance < 0:
        _fail("duration_tolerance must be nonnegative")

    normalized = _normalized_structure(plan)
    transcript = _normalized_words(words, duration)

    previous_end = 0.0
    for index, item in enumerate(normalized["keep_ranges"]):
        label = f"keep_ranges[{index}]"
        start_word = item["source_start_word"]
        end_word = item["source_end_word"]
        if start_word >= len(transcript) or end_word >= len(transcript):
            _fail(f"{label} source word span is outside the transcript")

        expected_text = " ".join(
            word["w"] for word in transcript[start_word:end_word + 1]
        )
        if item["anchor_text"] != expected_text:
            _fail(f"{label}.anchor_text is not fully grounded in its word span")

        expected_start = transcript[start_word]["s"]
        expected_end = transcript[end_word]["e"]
        if not math.isclose(
            item["source_start_seconds"],
            expected_start,
            rel_tol=0.0,
            abs_tol=WORD_BOUNDARY_TOLERANCE_SECONDS,
        ):
            _fail(f"{label}.source_start_seconds is not its word boundary")
        if not math.isclose(
            item["source_end_seconds"],
            expected_end,
            rel_tol=0.0,
            abs_tol=WORD_BOUNDARY_TOLERANCE_SECONDS,
        ):
            _fail(f"{label}.source_end_seconds is not its word boundary")
        if index and expected_start < previous_end:
            _fail("grounded keep_ranges overlap on the source timeline")

        item["source_start_seconds"] = expected_start
        item["source_end_seconds"] = expected_end
        previous_end = expected_end

    measured = kept_duration(normalized)
    minimum = normalized["target_duration"]["min_seconds"]
    maximum = normalized["target_duration"]["max_seconds"]
    # The final nanosecond guard keeps an inclusive decimal tolerance (for
    # example 2.90 against 2.95 +/- 0.05) inclusive after binary conversion.
    epsilon = 1e-12
    if (measured < minimum - tolerance - epsilon
            or measured > maximum + tolerance + epsilon):
        _fail(
            "grounded kept duration is outside target_duration "
            "including tolerance"
        )
    return copy.deepcopy(normalized)


def derive_complementary_cuts(
    validated_plan: object,
    source_duration: object,
) -> list[dict[str, float]]:
    """Derive the exact source-time complement of the ordered keep ranges."""
    duration = _finite_number(source_duration, "source_duration")
    if duration <= 0:
        _fail("source_duration must be greater than zero")
    normalized = _normalized_structure(validated_plan)

    cuts: list[dict[str, float]] = []
    cursor = 0.0
    for index, item in enumerate(normalized["keep_ranges"]):
        start = item["source_start_seconds"]
        end = item["source_end_seconds"]
        if end > duration:
            _fail(f"keep_ranges[{index}] ends beyond source_duration")
        if start > cursor:
            cuts.append({"s": cursor, "e": start})
        cursor = end
    if cursor < duration:
        cuts.append({"s": cursor, "e": duration})
    return cuts


def story_plan_sha256(plan: object) -> str:
    """Hash a plan using stable, whitespace-free, key-sorted JSON."""
    if not isinstance(plan, dict):
        _fail("story plan must be an object")
    try:
        payload = json.dumps(
            plan,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise StoryEditContractError(
            "story plan is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()
