"""Versioned contract between a creative model and the video renderer.

The model proposes intent. This module owns types, transcript grounding,
timing, density, collisions, and the quality score used by the release gate.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Iterable

PROTOCOL_VERSION = "pse-creative-edl/2026-07-28.1"
TIMELINE_SPACE = "post_cut_seconds"
REQUIRED_TOP_LEVEL = (
    "protocol_version", "timeline_space",
    "punch_ins", "broll", "graphics",
)
VIZ_TEMPLATES = frozenset({"flow", "steps", "stat"})
GRAPHIC_KINDS = frozenset({"keyword", "stat", "callout", "bars"})

_EVENT_KEYS = {
    "punch_ins": frozenset({
        "s", "e", "scale", "anchor_quote", "reason",
    }),
    "broll": frozenset({
        "s", "e", "query", "family", "viz", "anchor_quote", "reason",
    }),
    "graphics": frozenset({
        "s", "e", "kind", "text", "value", "items",
        "anchor_quote", "reason",
    }),
}
_SPACING = {
    "long": {"punch_ins": 10.0, "broll": 14.0, "graphics": 20.0},
    "short": {"punch_ins": 5.0, "broll": 7.0, "graphics": 8.0},
}
_SPAN_LIMITS = {
    "punch_ins": (0.6, 8.0),
    "broll": (1.5, 6.5),
    "graphics": (1.2, 5.0),
}
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for",
    "from", "how", "i", "if", "in", "is", "it", "of", "on", "or",
    "that", "the", "their", "then", "there", "these", "they", "this",
    "to", "was", "we", "what", "when", "where", "which", "who", "why",
    "with", "you", "your",
})
_NUMERIC_DISPLAY_RE = re.compile(
    r"^\$?\d[\d,]*(?:\.\d+)?\s*(?:%|x|k|m|b)?$", re.I
)
_SMALL_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_SCALES = {
    "thousand": 1_000.0,
    "million": 1_000_000.0,
    "billion": 1_000_000_000.0,
}

# Receipts need the same contract identity in source checkouts and PyInstaller
# builds, where this module's .py file does not exist. Keep this payload limited
# to explicit protocol/schema constants, and bump PROTOCOL_VERSION whenever the
# validator's externally visible semantics change.
_CONTRACT_PAYLOAD = json.dumps(
    {
        "protocol_version": PROTOCOL_VERSION,
        "timeline_space": TIMELINE_SPACE,
        "required_top_level": REQUIRED_TOP_LEVEL,
        "event_keys": {
            layer: sorted(keys) for layer, keys in _EVENT_KEYS.items()
        },
        "spacing": _SPACING,
        "span_limits": _SPAN_LIMITS,
        "viz_templates": sorted(VIZ_TEMPLATES),
        "graphic_kinds": sorted(GRAPHIC_KINDS),
    },
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
_CONTRACT_SHA256 = hashlib.sha256(_CONTRACT_PAYLOAD).hexdigest()


class CreativeContractError(ValueError):
    """The model output cannot safely or faithfully drive the renderer."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(str(e) for e in errors)
        super().__init__("; ".join(self.errors))


def _tokens(text: object) -> list[str]:
    return re.findall(r"[a-z0-9']+", str(text or "").lower())


def _content_tokens(text: object) -> set[str]:
    return {
        token for token in _tokens(text)
        if len(token) > 2 and token not in _STOPWORDS
    }


def transcript_payload(words: list[dict]) -> str:
    """Serialize every spoken word and timecode without silent truncation."""
    rows = []
    for index, word in enumerate(words):
        rows.append({
            "i": index,
            "s": round(float(word["s"]), 3),
            "e": round(float(word["e"]), 3),
            "w": str(word["w"]),
        })
    return json.dumps(rows, ensure_ascii=True, separators=(",", ":"))


def transcript_sha256(words: list[dict]) -> str:
    return hashlib.sha256(transcript_payload(words).encode()).hexdigest()


def contract_sha256() -> str:
    """Return the deterministic protocol fingerprint used in receipts."""
    return _CONTRACT_SHA256


def edl_sha256(edl: dict) -> str:
    """Bind a receipt to the exact validated plan that reaches the renderer."""
    payload = json.dumps(
        public_edl(edl), ensure_ascii=True, sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _finite_number(value: object, label: str, errors: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{label} must be a JSON number")
        return None
    number = float(value)
    if not math.isfinite(number):
        errors.append(f"{label} must be finite")
        return None
    return number


def _string(value: object, label: str, errors: list[str],
            *, minimum: int = 1, maximum: int = 240) -> str:
    if not isinstance(value, str):
        errors.append(f"{label} must be a string")
        return ""
    text = value.strip()
    if not minimum <= len(text) <= maximum:
        errors.append(
            f"{label} must contain {minimum}-{maximum} characters"
        )
    if "\u2014" in text:
        errors.append(f"{label} contains a banned em dash")
    return text


def _display_string(value: object, label: str, errors: list[str],
                    *, minimum: int = 1, maximum: int = 44) -> str:
    """Accept plain display copy, never markup or control characters."""
    text = _string(
        value, label, errors, minimum=minimum, maximum=maximum
    )
    if any(char in text for char in "<>&\r\n\t"):
        errors.append(f"{label} contains markup or control characters")
    return text


def _numeric_display(value: object, label: str,
                     errors: list[str]) -> str:
    text = _display_string(value, label, errors, maximum=16)
    if text and not _NUMERIC_DISPLAY_RE.fullmatch(text):
        errors.append(
            f"{label} must be a number with optional $, commas, decimal, "
            "%, x, k, m, or b suffix"
        )
    return text


def _display_number(text: str) -> float | None:
    match = _NUMERIC_DISPLAY_RE.fullmatch(text.strip())
    if not match:
        return None
    cleaned = text.strip().lower().replace("$", "").replace(",", "")
    suffix = cleaned[-1] if cleaned[-1:] in "%xkmb" else ""
    if suffix:
        cleaned = cleaned[:-1].strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number * {"k": 1e3, "m": 1e6, "b": 1e9}.get(suffix, 1.0)


def _spoken_number_candidates(text: str) -> set[float]:
    """Return numeric meanings found in nearby spoken transcript text."""
    candidates: set[float] = set()
    for match in re.finditer(
            r"\$?(\d[\d,]*(?:\.\d+)?)\s*"
            r"(thousand|million|billion|%|x|k|m|b)?",
            text.lower()):
        number = float(match.group(1).replace(",", ""))
        suffix = match.group(2) or ""
        multiplier = {
            "thousand": 1e3, "k": 1e3,
            "million": 1e6, "m": 1e6,
            "billion": 1e9, "b": 1e9,
        }.get(suffix, 1.0)
        candidates.add(number * multiplier)

    tokens = _tokens(text)
    digit_words = {
        **{word: value for word, value in _SMALL_NUMBERS.items()
           if value < 10},
        "oh": 0,
    }
    for point_index, token in enumerate(tokens):
        if token != "point" or point_index == 0:
            continue
        left = tokens[point_index - 1]
        integer = _SMALL_NUMBERS.get(left, _TENS.get(left))
        if integer is None:
            continue
        decimals = []
        for decimal_token in tokens[point_index + 1:]:
            if decimal_token not in digit_words:
                break
            decimals.append(str(digit_words[decimal_token]))
        if decimals:
            candidates.add(float(f"{integer}.{''.join(decimals)}"))
    for start in range(len(tokens)):
        current = 0.0
        total = 0.0
        found = False
        for index in range(start, len(tokens)):
            token = tokens[index]
            if token in _SMALL_NUMBERS:
                current += _SMALL_NUMBERS[token]
                found = True
            elif token in _TENS:
                current += _TENS[token]
                found = True
            elif token == "half":
                current += 0.5
                found = True
            elif token == "a" and index + 1 < len(tokens) and (
                    tokens[index + 1] in _NUMBER_SCALES):
                if not found:
                    current = 1.0
                    found = True
            elif token == "hundred" and found:
                current = max(1.0, current) * 100.0
            elif token in _NUMBER_SCALES and found:
                total += max(1.0, current) * _NUMBER_SCALES[token]
                current = 0.0
            elif token == "and" and found:
                continue
            else:
                break
            candidates.add(total + current)
    return candidates


def _number_is_spoken(value: str, nearby_text: str) -> bool:
    wanted = _display_number(value)
    if wanted is None:
        return False
    return any(
        math.isclose(wanted, candidate, rel_tol=1e-6, abs_tol=1e-6)
        for candidate in _spoken_number_candidates(nearby_text)
    )


def _anchor_span(anchor: str, words: list[dict],
                 proposed_s: float) -> tuple[float, float, float] | None:
    wanted = _tokens(anchor)
    wanted_content = _content_tokens(anchor)
    if not 5 <= len(wanted) <= 20 or not wanted_content:
        return None
    normalized = []
    token_words = []
    for word_index, word in enumerate(words):
        for token in _tokens(word.get("w", "")):
            normalized.append(token)
            token_words.append(word_index)
    best = None
    size = len(wanted)
    for start in range(len(normalized) - size + 1):
        end = start + size
        if normalized[start:end] != wanted:
            continue
        start_word = token_words[start]
        end_word = token_words[end - 1] + 1
        distance = abs(float(words[start_word]["s"]) - proposed_s)
        candidate = (-distance, start_word, end_word)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    _, start, end = best
    return (
        float(words[start]["s"]),
        float(words[end - 1]["e"]),
        1.0,
    )


def _validate_text_items(items: object, label: str, errors: list[str],
                         *, object_items: bool) -> list:
    if not isinstance(items, list):
        errors.append(f"{label} must be a list")
        return []
    if not 2 <= len(items) <= 5:
        errors.append(f"{label} must contain 2-5 items")
    out = []
    for index, item in enumerate(items[:5]):
        if object_items:
            if not isinstance(item, dict) or set(item) != {"label", "value"}:
                errors.append(
                    f"{label}[{index}] must contain only label and value"
                )
                continue
            item_label = _display_string(
                item.get("label"), f"{label}[{index}].label", errors,
                maximum=26,
            )
            item_value = _finite_number(
                item.get("value"), f"{label}[{index}].value", errors
            )
            if item_value is not None and item_value < 0:
                errors.append(f"{label}[{index}].value must be nonnegative")
            out.append({"label": item_label, "value": item_value or 0.0})
        else:
            out.append(_display_string(
                item, f"{label}[{index}]", errors, maximum=26
            ))
    return out


def _normalize_event(layer: str, event: object, index: int,
                     words: list[dict], families: set[str], duration: float,
                     errors: list[str]) -> dict | None:
    label = f"{layer}[{index}]"
    if not isinstance(event, dict):
        errors.append(f"{label} must be an object")
        return None
    unknown = sorted(set(event) - _EVENT_KEYS[layer])
    if unknown:
        errors.append(f"{label} has unsupported keys: {', '.join(unknown)}")
    proposed_s = _finite_number(event.get("s"), f"{label}.s", errors)
    proposed_e = _finite_number(event.get("e"), f"{label}.e", errors)
    anchor = _string(
        event.get("anchor_quote"), f"{label}.anchor_quote", errors,
        minimum=4, maximum=200,
    )
    if not 5 <= len(_tokens(anchor)) <= 20:
        errors.append(f"{label}.anchor_quote must contain 5-20 exact words")
    reason = _string(
        event.get("reason"), f"{label}.reason", errors,
        minimum=4, maximum=240,
    )
    if proposed_s is None or proposed_e is None:
        return None
    if not 0 <= proposed_s < proposed_e <= duration + 0.001:
        errors.append(f"{label} time range is outside the post-cut timeline")
        return None
    anchor_match = _anchor_span(anchor, words, proposed_s)
    if anchor_match is None:
        errors.append(f"{label}.anchor_quote is not grounded in the transcript")
        return None
    anchor_s, anchor_e, anchor_score = anchor_match
    if abs(proposed_s - anchor_s) > 3.0:
        errors.append(
            f"{label}.s is more than 3 seconds from its spoken anchor"
        )
    minimum, maximum = _SPAN_LIMITS[layer]
    if layer == "punch_ins" and anchor_e - anchor_s > maximum:
        errors.append(
            f"{label}.anchor_quote spans more than {maximum:.1f} seconds"
        )
        return None
    span = proposed_e - proposed_s
    if not (minimum - 1e-6) <= span <= (maximum + 1e-6):
        errors.append(
            f"{label} duration must be {minimum:.1f}-{maximum:.1f} seconds"
        )
    span = min(maximum, max(minimum, span))
    start = max(0.0, anchor_s - (0.1 if layer != "punch_ins" else 0.0))
    if layer == "punch_ins":
        end = max(anchor_e, start + span)
    else:
        end = start + span
    end = min(duration, end)
    if end - start < minimum:
        start = max(0.0, end - minimum)

    normalized = {
        "s": round(start, 3),
        "e": round(end, 3),
        "anchor_quote": anchor,
        "reason": reason,
        "anchor_score": round(anchor_score, 3),
        "display_copy_grounded": True,
    }
    nearby_words = [
        str(word.get("w", ""))
        for word in words
        if float(word.get("e", 0.0)) >= anchor_s - 6.0
        and float(word.get("s", 0.0)) <= anchor_e + 6.0
    ]
    nearby_text = " ".join(nearby_words)
    nearby_tokens = _content_tokens(nearby_text)
    if layer == "punch_ins":
        scale = _finite_number(event.get("scale"), f"{label}.scale", errors)
        if scale is None:
            return None
        if not 1.05 <= scale <= 1.15:
            errors.append(f"{label}.scale must be 1.05-1.15")
        normalized["scale"] = round(min(1.15, max(1.05, scale)), 3)
    elif layer == "broll":
        query = _string(
            event.get("query"), f"{label}.query", errors,
            minimum=3, maximum=80,
        )
        if not 2 <= len(_tokens(query)) <= 8:
            errors.append(f"{label}.query must contain 2-8 search words")
        family = event.get("family", "")
        if not isinstance(family, str):
            errors.append(f"{label}.family must be a string")
            family = ""
        family = family.strip()
        if family and family not in families:
            errors.append(f"{label}.family is not in the supplied clip catalog")
        normalized.update({"query": query, "family": family})
        viz = event.get("viz")
        if viz is not None:
            if not isinstance(viz, dict):
                errors.append(f"{label}.viz must be an object")
            else:
                allowed = {"template", "title", "items", "value"}
                extra = sorted(set(viz) - allowed)
                if extra:
                    errors.append(
                        f"{label}.viz has unsupported keys: {', '.join(extra)}"
                    )
                template = str(viz.get("template", "")).lower()
                if template not in VIZ_TEMPLATES:
                    errors.append(f"{label}.viz.template is unsupported")
                title = _display_string(
                    viz.get("title"), f"{label}.viz.title", errors,
                    maximum=36,
                )
                clean_viz = {"template": template, "title": title}
                if template in {"flow", "steps"}:
                    clean_viz["items"] = _validate_text_items(
                        viz.get("items"), f"{label}.viz.items", errors,
                        object_items=False,
                    )
                elif template == "stat":
                    clean_viz["value"] = _numeric_display(
                        viz.get("value"), f"{label}.viz.value", errors,
                    )
                normalized["viz"] = clean_viz
                copy_parts = [title]
                copy_parts.extend(clean_viz.get("items", []))
                copy_tokens = _content_tokens(" ".join(copy_parts))
                required = min(
                    len(copy_tokens),
                    2 if template in {"flow", "steps"} else 1,
                )
                copy_ok = (
                    required == 0
                    or len(copy_tokens & nearby_tokens) >= required
                )
                number_ok = (
                    template != "stat"
                    or _number_is_spoken(
                        clean_viz.get("value", ""), nearby_text
                    )
                )
                if not copy_ok or not number_ok:
                    normalized["display_copy_grounded"] = False
                    errors.append(
                        f"{label}.viz on-screen copy is not grounded in "
                        "the transcript near its anchor"
                    )
    else:
        kind = str(event.get("kind", "")).lower()
        if kind not in GRAPHIC_KINDS:
            errors.append(f"{label}.kind is unsupported")
        text = _display_string(
            event.get("text"), f"{label}.text", errors, maximum=44
        )
        if len(_tokens(text)) > 4:
            errors.append(f"{label}.text must contain at most 4 words")
        if text != text.upper():
            errors.append(f"{label}.text must be uppercase")
        normalized.update({"kind": kind, "text": text})
        if kind == "stat":
            normalized["value"] = _numeric_display(
                event.get("value"), f"{label}.value", errors
            )
        elif kind == "bars":
            normalized["items"] = _validate_text_items(
                event.get("items"), f"{label}.items", errors,
                object_items=True,
            )
        copy_parts = [text]
        copy_parts.extend(
            str(item.get("label", ""))
            for item in normalized.get("items", [])
            if isinstance(item, dict)
        )
        copy_tokens = _content_tokens(" ".join(copy_parts))
        number_ok = True
        if kind == "stat":
            number_ok = _number_is_spoken(
                normalized.get("value", ""), nearby_text
            )
        elif kind == "bars":
            number_ok = all(
                any(
                    math.isclose(
                        float(item["value"]), candidate,
                        rel_tol=1e-6, abs_tol=1e-6,
                    )
                    for candidate in _spoken_number_candidates(nearby_text)
                )
                for item in normalized.get("items", [])
            )
        copy_ok = bool(copy_tokens & nearby_tokens)
        if not copy_ok or not number_ok:
            normalized["display_copy_grounded"] = False
            errors.append(
                f"{label} on-screen copy is not grounded in the transcript "
                "near its anchor"
            )
    return normalized


def _has_framework_language(words: list[dict]) -> bool:
    text = " ".join(str(word.get("w", "")) for word in words).lower()
    patterns = (
        r"\b(?:three|four|five|six|seven|\d+)\s+"
        r"(?:steps|signals|parts|pillars|stages|rules|principles|ways)\b",
        r"\b(?:first|step one)\b.{0,180}\b(?:second|step two)\b",
    )
    return any(re.search(pattern, text, re.S) for pattern in patterns)


def _max_visual_gap(edl: dict, duration: float) -> float:
    windows = sorted(
        (
            (float(event["s"]), float(event["e"]))
            for layer in ("broll", "graphics")
            for event in edl[layer]
        ),
        key=lambda pair: pair[0],
    )
    if not windows:
        return duration
    points = [(0.0, windows[0][0])]
    points.extend(
        (left[1], right[0]) for left, right in zip(windows, windows[1:])
    )
    points.append((windows[-1][1], duration))
    return max(max(0.0, end - start) for start, end in points)


def validate_edl(raw: dict, words: list[dict], clips: list[dict],
                 duration: float, style: str = "long") -> tuple[dict, dict]:
    """Validate, transcript-anchor, score, and canonicalize a model EDL."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise CreativeContractError(["EDL root must be an object"])
    missing = [key for key in REQUIRED_TOP_LEVEL if key not in raw]
    if missing:
        errors.append("missing top-level keys: " + ", ".join(missing))
    unknown_top = sorted(set(raw) - set(REQUIRED_TOP_LEVEL))
    if unknown_top:
        errors.append(
            "unsupported top-level keys: " + ", ".join(unknown_top)
        )
    if raw.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("protocol_version does not match the renderer")
    if raw.get("timeline_space") != TIMELINE_SPACE:
        errors.append("timeline_space must be post_cut_seconds")
    families = {
        str(clip.get("family", "")).strip()
        for clip in clips if str(clip.get("family", "")).strip()
    }
    edl = {
        "protocol_version": PROTOCOL_VERSION,
        "timeline_space": TIMELINE_SPACE,
        "punch_ins": [],
        "broll": [],
        "graphics": [],
    }
    for layer in ("punch_ins", "broll", "graphics"):
        events = raw.get(layer)
        if not isinstance(events, list):
            errors.append(f"{layer} must be a list")
            continue
        limit = max(2, math.ceil(duration / _SPACING[style][layer]) + 2)
        if len(events) > limit:
            errors.append(f"{layer} exceeds the density cap of {limit}")
        for index, event in enumerate(events):
            normalized = _normalize_event(
                layer, event, index, words, families, duration, errors
            )
            if normalized is not None:
                edl[layer].append(normalized)
        edl[layer].sort(key=lambda event: float(event["s"]))

    for layer in ("punch_ins", "broll", "graphics"):
        for prior, current in zip(edl[layer], edl[layer][1:]):
            if float(current["s"]) < float(prior["e"]) + 0.25:
                errors.append(f"{layer} contains overlapping or stacked events")
            start_gap = float(current["s"]) - float(prior["s"])
            required_gap = _SPACING[style][layer]
            if start_gap < required_gap - 1e-6:
                errors.append(
                    f"{layer} events start {start_gap:.1f}s apart; "
                    f"{style} pacing requires at least {required_gap:.1f}s"
                )
    for broll in edl["broll"]:
        for graphic in edl["graphics"]:
            if (float(graphic["s"]) < float(broll["e"]) + 0.25
                    and float(graphic["e"]) > float(broll["s"]) - 0.25):
                errors.append("broll and graphics collide on screen")
                break

    first_speech = float(words[0]["s"]) if words else 0.0
    hook_limit = first_speech + (2.5 if style == "short" else 2.0)
    hook_ok = any(
        float(event["s"]) <= hook_limit for event in edl["punch_ins"]
    )
    visual_limit = first_speech + (3.0 if style == "short" else 8.0)
    opening_visual_ok = any(
        float(event["s"]) <= visual_limit
        for layer in ("broll", "graphics") for event in edl[layer]
    ) if duration >= 8.0 else True
    max_gap = _max_visual_gap(edl, duration)
    gap_limit = 12.0 if style == "short" else 75.0
    coverage_ok = max_gap <= gap_limit
    framework = _has_framework_language(words)
    diagram_ok = (
        not framework
        or any(event.get("viz") for event in edl["broll"])
    )
    score = (
        (25 if hook_ok else 0)
        + (20 if opening_visual_ok else 0)
        + (25 if coverage_ok else 0)
        + (20 if diagram_ok else 0)
        + 10
    )
    if not hook_ok:
        errors.append("no punch-in is anchored to the opening hook")
    if not opening_visual_ok:
        errors.append("no b-roll or graphic is anchored in the opening window")
    if not coverage_ok:
        errors.append(
            f"maximum visual gap {max_gap:.1f}s exceeds {gap_limit:.1f}s"
        )
    if not diagram_ok:
        errors.append("framework language is present but no diagram was planned")
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "score": score,
        "minimum_score": 100,
        "hook_ok": hook_ok,
        "opening_visual_ok": opening_visual_ok,
        "coverage_ok": coverage_ok,
        "max_visual_gap_seconds": round(max_gap, 3),
        "diagram_required": framework,
        "diagram_ok": diagram_ok,
        "all_events_transcript_grounded": all(
            float(event.get("anchor_score", 0)) >= 0.78
            and event.get("display_copy_grounded") is True
            for layer in ("punch_ins", "broll", "graphics")
            for event in edl[layer]
        ),
        "errors": list(dict.fromkeys(errors)),
    }
    if errors:
        raise CreativeContractError(report["errors"])
    edl["contract"] = report
    return edl, report


def public_edl(edl: dict) -> dict:
    """Strip validator-only fields before a plan reaches a renderer."""
    result = {
        key: value for key, value in edl.items()
        if key not in {"contract", "production_receipt", "resolution"}
    }
    for layer in ("punch_ins", "broll", "graphics"):
        result[layer] = [
            {
                key: value for key, value in event.items()
                if key not in {"anchor_score", "display_copy_grounded"}
            }
            for event in edl.get(layer, [])
        ]
    return result
