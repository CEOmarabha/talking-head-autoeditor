"""Deterministic final-artifact acceptance for source-timeline story edits.

Planning evidence is necessary but not sufficient: this module independently
checks the delivered duration and transcript before a story edit can pass.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .story_edit import (
    SOURCE_TIMELINE,
    STORY_PLAN_SCHEMA_VERSION,
    kept_duration,
    story_plan_sha256,
)


STORY_ACCEPTANCE_SCHEMA_VERSION = "autoeditor-story-acceptance/v1"
STORY_CUT_RECEIPT_SCHEMA_VERSION = "autoeditor-story-cut-receipt/v1"
HOOK_MAX_START_SECONDS = 3.0
CLOSER_MAX_TRAILING_SECONDS = 5.0

_PLAN_KEYS = frozenset({
    "schema_version", "timeline", "target_duration", "hook_anchor_id",
    "closer_anchor_id", "keep_ranges",
})
_RANGE_KEYS = frozenset({
    "anchor_id", "anchor_text", "source_start_word", "source_end_word",
    "source_start_seconds", "source_end_seconds",
})
_RECEIPT_KEYS = frozenset({
    "schema_version", "source", "source_sha256", "story_plan_sha256",
    "transcript_sha256", "timeline", "kept_duration_seconds",
    "derived_cuts_sha256",
})
_TARGET_KEYS = frozenset({"min_seconds", "max_seconds"})
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _tokens(value: object) -> list[str]:
    return _TOKEN.findall(str(value or "").lower())


def _key_errors(value: object, expected: frozenset[str], label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors = []
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected, key=str)
    if missing:
        errors.append(f"{label} is missing keys: {', '.join(missing)}")
    if extra:
        errors.append(
            f"{label} has unsupported keys: "
            f"{', '.join(str(key) for key in extra)}"
        )
    return errors


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def check_final_duration(final_duration_seconds: object,
                         target_duration: object) -> dict[str, Any]:
    """Check the delivered duration against the plan's inclusive hard range."""
    errors = _key_errors(target_duration, _TARGET_KEYS, "target_duration")
    measured = _finite_number(final_duration_seconds)
    if measured is None or measured < 0:
        errors.append("final duration must be a finite nonnegative number")

    minimum = maximum = None
    if isinstance(target_duration, dict):
        minimum = _finite_number(target_duration.get("min_seconds"))
        maximum = _finite_number(target_duration.get("max_seconds"))
    if minimum is None or minimum < 0:
        errors.append("target minimum must be a finite nonnegative number")
    if maximum is None or maximum < 0:
        errors.append("target maximum must be a finite nonnegative number")
    if minimum is not None and maximum is not None and minimum > maximum:
        errors.append("target minimum cannot exceed target maximum")
    if (measured is not None and minimum is not None and maximum is not None
            and not minimum <= measured <= maximum):
        errors.append(
            f"final duration {measured:.3f}s is outside the required "
            f"{minimum:.3f}-{maximum:.3f}s range"
        )
    return {
        "ok": not errors,
        "measured_seconds": measured,
        "minimum_seconds": minimum,
        "maximum_seconds": maximum,
        "errors": errors,
    }


def _anchor_specs(story_plan: object, errors: list[str]) -> list[dict]:
    errors.extend(_key_errors(story_plan, _PLAN_KEYS, "story plan"))
    if not isinstance(story_plan, dict):
        return []
    if story_plan.get("schema_version") != STORY_PLAN_SCHEMA_VERSION:
        errors.append("story plan schema_version is unsupported")
    if story_plan.get("timeline") != SOURCE_TIMELINE:
        errors.append("story plan timeline must be source_seconds")

    ranges = story_plan.get("keep_ranges")
    if not isinstance(ranges, list) or len(ranges) < 2:
        errors.append("story plan requires at least a hook and closer range")
        return []

    specs = []
    seen_ids = set()
    for index, value in enumerate(ranges):
        label = f"keep_ranges[{index}]"
        errors.extend(_key_errors(value, _RANGE_KEYS, label))
        if not isinstance(value, dict):
            continue
        anchor_id = value.get("anchor_id")
        anchor_text = value.get("anchor_text")
        if not isinstance(anchor_id, str) or not anchor_id.strip():
            errors.append(f"{label}.anchor_id must be a nonempty string")
            continue
        if anchor_id in seen_ids:
            errors.append(f"{label}.anchor_id must be unique")
        seen_ids.add(anchor_id)
        tokens = _tokens(anchor_text)
        if not isinstance(anchor_text, str) or not tokens:
            errors.append(f"{label}.anchor_text must contain spoken words")
            continue
        specs.append({
            "anchor_id": anchor_id,
            "anchor_text": anchor_text,
            "tokens": tokens,
        })

    hook = story_plan.get("hook_anchor_id")
    closer = story_plan.get("closer_anchor_id")
    if not specs or hook != specs[0]["anchor_id"]:
        errors.append("hook_anchor_id must identify the first keep range")
    if not specs or closer != specs[-1]["anchor_id"]:
        errors.append("closer_anchor_id must identify the last keep range")
    if hook == closer:
        errors.append("hook and closer anchor IDs must be distinct")
    return specs


def _flatten_final_words(final_words: object, final_duration: float | None,
                         errors: list[str]) -> list[dict]:
    if not isinstance(final_words, list) or not final_words:
        errors.append("final transcript must contain timed words")
        return []
    flattened = []
    prior_start = -1.0
    for index, word in enumerate(final_words):
        label = f"final_words[{index}]"
        if not isinstance(word, dict):
            errors.append(f"{label} must be an object")
            continue
        start = _finite_number(word.get("s"))
        end = _finite_number(word.get("e"))
        tokens = _tokens(word.get("w"))
        if start is None or end is None or start < 0 or end < start:
            errors.append(f"{label} has an invalid time range")
            continue
        if start < prior_start:
            errors.append("final transcript words must be in chronological order")
        prior_start = start
        if final_duration is not None and end > final_duration + 0.25:
            errors.append(f"{label} ends after the delivered artifact")
        if not tokens:
            errors.append(f"{label} contains no spoken token")
            continue
        for token in tokens:
            flattened.append({"token": token, "s": start, "e": end})
    return flattened


def _occurrences(wanted: list[str], transcript: list[dict]) -> list[dict]:
    found = []
    size = len(wanted)
    for start in range(len(transcript) - size + 1):
        end = start + size
        if [item["token"] for item in transcript[start:end]] != wanted:
            continue
        found.append({
            "start_token": start,
            "end_token": end,
            "start_seconds": transcript[start]["s"],
            "end_seconds": transcript[end - 1]["e"],
        })
    return found


def check_required_anchors(final_words: object, final_duration_seconds: object,
                           story_plan: object) -> dict[str, Any]:
    """Prove every required anchor appears in order in the final transcript."""
    errors: list[str] = []
    final_duration = _finite_number(final_duration_seconds)
    if final_duration is None or final_duration < 0:
        errors.append("final duration must be available for anchor acceptance")
        final_duration = None
    specs = _anchor_specs(story_plan, errors)
    transcript = _flatten_final_words(final_words, final_duration, errors)

    candidates = []
    for index, spec in enumerate(specs):
        matches = _occurrences(spec["tokens"], transcript)
        if not matches:
            errors.append(
                f"required anchor {spec['anchor_id']} is missing from the "
                "final transcript"
            )
        if index == 0:
            opening = [
                item for item in matches
                if item["start_seconds"] <= HOOK_MAX_START_SECONDS
            ]
            if matches and not opening:
                errors.append(
                    f"hook anchor must start within the opening "
                    f"{HOOK_MAX_START_SECONDS:.1f} seconds"
                )
            matches = opening
        if index == len(specs) - 1 and final_duration is not None:
            closing = [
                item for item in matches
                if -0.25 <= final_duration - item["end_seconds"]
                <= CLOSER_MAX_TRAILING_SECONDS
            ]
            if matches and not closing:
                errors.append(
                    f"closer anchor must finish within the final "
                    f"{CLOSER_MAX_TRAILING_SECONDS:.1f} seconds"
                )
            matches = closing
        candidates.append(matches)

    selected = []
    next_token = 0
    for spec, matches in zip(specs, candidates):
        match = next(
            (item for item in matches if item["start_token"] >= next_token),
            None,
        )
        if match is None:
            errors.append(
                f"required anchor {spec['anchor_id']} does not appear in "
                "plan order after the preceding anchor"
            )
            break
        selected.append({
            "anchor_id": spec["anchor_id"],
            "start_seconds": match["start_seconds"],
            "end_seconds": match["end_seconds"],
        })
        next_token = match["end_token"]

    errors = list(dict.fromkeys(errors))
    return {
        "ok": not errors and len(selected) == len(specs),
        "hook_max_start_seconds": HOOK_MAX_START_SECONDS,
        "closer_max_trailing_seconds": CLOSER_MAX_TRAILING_SECONDS,
        "matches": selected,
        "errors": errors,
    }


def check_story_cut_receipt(story_cut_receipt: object, story_plan: object, *,
                            expected_receipt_source: object,
                            expected_source_sha256: object) -> dict[str, Any]:
    """Verify that strict runtime evidence binds source bytes and story plan."""
    errors = _key_errors(
        story_cut_receipt, _RECEIPT_KEYS, "story cut receipt"
    )
    if not isinstance(story_cut_receipt, dict):
        return {"ok": False, "errors": errors}

    if (story_cut_receipt.get("schema_version")
            != STORY_CUT_RECEIPT_SCHEMA_VERSION):
        errors.append("story cut receipt schema_version is unsupported")
    if story_cut_receipt.get("timeline") != SOURCE_TIMELINE:
        errors.append("story cut receipt timeline must be source_seconds")
    if not isinstance(expected_receipt_source, str) or not expected_receipt_source:
        errors.append("expected receipt source must be a nonempty string")
    elif story_cut_receipt.get("source") != expected_receipt_source:
        errors.append("story cut receipt source does not match the trusted source")

    if not _valid_sha256(expected_source_sha256):
        errors.append("expected source SHA-256 is invalid")
    receipt_source_hash = story_cut_receipt.get("source_sha256")
    if not _valid_sha256(receipt_source_hash):
        errors.append("story cut receipt source_sha256 is invalid")
    elif (_valid_sha256(expected_source_sha256)
          and receipt_source_hash.lower() != expected_source_sha256.lower()):
        errors.append("story cut receipt is bound to different source bytes")

    try:
        expected_plan_hash = story_plan_sha256(story_plan)
    except (TypeError, ValueError, KeyError) as error:
        expected_plan_hash = None
        errors.append(f"story plan cannot be hashed: {error}")
    receipt_plan_hash = story_cut_receipt.get("story_plan_sha256")
    if not _valid_sha256(receipt_plan_hash):
        errors.append("story cut receipt story_plan_sha256 is invalid")
    elif (expected_plan_hash is not None
          and receipt_plan_hash.lower() != expected_plan_hash.lower()):
        errors.append("story cut receipt is bound to a different story plan")

    for key in ("transcript_sha256", "derived_cuts_sha256"):
        if not _valid_sha256(story_cut_receipt.get(key)):
            errors.append(f"story cut receipt {key} is invalid")

    receipt_kept = _finite_number(
        story_cut_receipt.get("kept_duration_seconds")
    )
    try:
        planned_kept = kept_duration(story_plan)
    except (TypeError, ValueError, KeyError) as error:
        planned_kept = None
        errors.append(f"story plan kept duration is invalid: {error}")
    if receipt_kept is None or receipt_kept < 0:
        errors.append("story cut receipt kept_duration_seconds is invalid")
    elif (planned_kept is not None
          and not math.isclose(receipt_kept, planned_kept, abs_tol=0.001)):
        errors.append("story cut receipt kept duration does not match the plan")

    errors = list(dict.fromkeys(errors))
    return {
        "ok": not errors,
        "source": story_cut_receipt.get("source"),
        "source_sha256": receipt_source_hash,
        "story_plan_sha256": receipt_plan_hash,
        "kept_duration_seconds": receipt_kept,
        "errors": errors,
    }


def validate_story_acceptance(*, final_duration_seconds: object,
                              final_words: object, story_plan: object,
                              story_cut_receipt: object,
                              expected_receipt_source: object,
                              expected_source_sha256: object) -> dict[str, Any]:
    """Return a fail-closed final story acceptance report."""
    target = (
        story_plan.get("target_duration")
        if isinstance(story_plan, dict) else None
    )
    checks = {
        "duration": check_final_duration(final_duration_seconds, target),
        "required_anchors": check_required_anchors(
            final_words, final_duration_seconds, story_plan
        ),
        "story_cut_receipt": check_story_cut_receipt(
            story_cut_receipt, story_plan,
            expected_receipt_source=expected_receipt_source,
            expected_source_sha256=expected_source_sha256,
        ),
    }
    return {
        "schema_version": STORY_ACCEPTANCE_SCHEMA_VERSION,
        "pass": all(check["ok"] for check in checks.values()),
        "checks": checks,
    }


__all__ = [
    "CLOSER_MAX_TRAILING_SECONDS", "HOOK_MAX_START_SECONDS",
    "STORY_ACCEPTANCE_SCHEMA_VERSION", "check_final_duration",
    "check_required_anchors", "check_story_cut_receipt",
    "validate_story_acceptance",
]
