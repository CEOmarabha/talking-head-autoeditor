"""Bounded, deterministic visual evidence from trusted decoded RGB frames.

This module deliberately does not perform semantic visual evaluation.  It
measures only technical pixel and geometry conditions that are reproducible
from exact decoded ``rgb24`` frames and trusted renderer/timeline metadata:

* black and nearly uniform frames;
* exact/near-duplicate runs and isolated one-frame flashes;
* supplied renderer rectangles against the canvas and supplied safe area;
* caption/graphic raster presence, luma contrast, and state change;
* cross-dissolve or dip-to-black before/middle/after continuity.

The public request and result are closed v1 schemas.  Every decoded frame is
bound by SHA-256 before analysis, all reported metrics are integers, resource
use is bounded, and the receipt contains no filesystem paths.  Callers remain
responsible for deciding which checks are appropriate from trusted edit intent;
this analyzer makes no OCR, identity, subject, aesthetic, or narrative claims.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

import numpy as np


VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION = (
    "autoeditor-visual-quality-deterministic-request/v1"
)
VISUAL_QUALITY_DETERMINISTIC_RECEIPT_SCHEMA_VERSION = (
    "autoeditor-visual-quality-deterministic-receipt/v1"
)
VISUAL_QUALITY_DETERMINISTIC_RESULT_SCHEMA_VERSION = (
    "autoeditor-visual-quality-deterministic-result/v1"
)
VISUAL_QUALITY_DETERMINISTIC_ALGORITHM_VERSION = (
    "autoeditor-rgb24-technical-evidence/v1"
)

MAX_FRAMES = 128
MAX_CHECKS_PER_KIND = 128
MAX_WINDOW_FRAMES = 64
MAX_FRAME_DIMENSION = 4_096
MAX_FRAME_PIXELS = 3_840 * 2_160
MAX_DECODED_BYTES = 256 * 1024 * 1024
MAX_TIMESTAMP_US = 86_400 * 1_000_000
MAX_FRAME_INDEX = 20_000_000
MAX_RECT_DIMENSION = 8_192
_CHUNK_PIXELS = 1_000_000

BLACK_LUMA_MAX = 16
BLACK_PIXEL_RATIO_PPM_MIN = 990_000
BLANK_LUMA_RANGE_MAX = 4
BLANK_LUMA_MAD_MAX = 1
NEAR_DUPLICATE_MAE_PPM_MAX = 8_000
FREEZE_DURATION_US_MIN = 500_000
FLASH_LUMA_JUMP_MIN = 64
FLASH_OUTER_MAE_PPM_MAX = 47_059
OVERLAY_CHANNEL_DELTA_MIN = 8
OVERLAY_PIXEL_PRESENCE_PPM_MIN = 2_000
OVERLAY_STATE_SIGNAL_PPM_MIN = 10_000
CAPTION_CONTRAST_RATIO_PPM_MIN = 4_500_000
GRAPHIC_CONTRAST_RATIO_PPM_MIN = 3_000_000
TRANSITION_ENDPOINT_MAE_PPM_MIN = 20_000
TRANSITION_ALPHA_PPM_MIN = 50_000
TRANSITION_ALPHA_PPM_MAX = 950_000
TRANSITION_BLEND_RESIDUAL_PPM_MAX = 30_000
TRANSITION_BETWEEN_COMPONENT_RATIO_PPM_MIN = 950_000
DIP_BLACK_PIXEL_RATIO_PPM_MIN = 950_000

_THRESHOLDS = {
    "black_luma_max": BLACK_LUMA_MAX,
    "black_pixel_ratio_ppm_min": BLACK_PIXEL_RATIO_PPM_MIN,
    "blank_luma_range_max": BLANK_LUMA_RANGE_MAX,
    "blank_luma_mad_max": BLANK_LUMA_MAD_MAX,
    "near_duplicate_mae_ppm_max": NEAR_DUPLICATE_MAE_PPM_MAX,
    "freeze_duration_us_min": FREEZE_DURATION_US_MIN,
    "flash_luma_jump_min": FLASH_LUMA_JUMP_MIN,
    "flash_outer_mae_ppm_max": FLASH_OUTER_MAE_PPM_MAX,
    "overlay_channel_delta_min": OVERLAY_CHANNEL_DELTA_MIN,
    "overlay_pixel_presence_ppm_min": OVERLAY_PIXEL_PRESENCE_PPM_MIN,
    "overlay_state_signal_ppm_min": OVERLAY_STATE_SIGNAL_PPM_MIN,
    "caption_contrast_ratio_ppm_min": CAPTION_CONTRAST_RATIO_PPM_MIN,
    "graphic_contrast_ratio_ppm_min": GRAPHIC_CONTRAST_RATIO_PPM_MIN,
    "transition_endpoint_mae_ppm_min": TRANSITION_ENDPOINT_MAE_PPM_MIN,
    "transition_alpha_ppm_min": TRANSITION_ALPHA_PPM_MIN,
    "transition_alpha_ppm_max": TRANSITION_ALPHA_PPM_MAX,
    "transition_blend_residual_ppm_max": TRANSITION_BLEND_RESIDUAL_PPM_MAX,
    "transition_between_component_ratio_ppm_min": (
        TRANSITION_BETWEEN_COMPONENT_RATIO_PPM_MIN
    ),
    "dip_black_pixel_ratio_ppm_min": DIP_BLACK_PIXEL_RATIO_PPM_MIN,
}

_SCOPE = {
    "claims": [
        "decoded-rgb24-black-and-uniform-frame-measurement",
        "decoded-rgb24-near-duplicate-and-isolated-flash-measurement",
        "trusted-renderer-rectangle-and-safe-area-containment",
        "trusted-receipt-overlay-pixel-presence-contrast-and-state-change",
        "trusted-transition-before-middle-after-pixel-continuity",
    ],
    "unsupported": [
        "ocr",
        "semantic-content",
        "identity-or-target-recognition",
        "aesthetic-quality",
        "intent-inference",
        "arbitrary-transition-quality",
    ],
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$", re.ASCII)

_REQUEST_KEYS = frozenset({
    "schema_version", "artifact_sha256", "decoder_receipt_sha256",
    "timeline_receipt_sha256", "geometry", "timeline", "checks",
})
_GEOMETRY_KEYS = frozenset({"width", "height", "pixel_format"})
_TIMELINE_KEYS = frozenset({"frame_rate", "frames"})
_FRAME_RATE_KEYS = frozenset({"numerator", "denominator"})
_FRAME_KEYS = frozenset({
    "frame_id", "frame_index", "timestamp_us", "rgb24_sha256",
})
_CHECKS_KEYS = frozenset({
    "frame_state", "temporal_window", "geometry", "overlay", "transition",
})
_FRAME_STATE_KEYS = frozenset({"check_id", "frame_id", "expected_state"})
_TEMPORAL_WINDOW_KEYS = frozenset({
    "check_id", "frame_ids", "expected_state",
})
_GEOMETRY_CHECK_KEYS = frozenset({
    "check_id", "kind", "frame_id", "renderer_receipt_sha256", "rect",
    "safe_area",
})
_OVERLAY_CHECK_KEYS = frozenset({
    "check_id", "kind", "renderer_receipt_sha256",
    "inactive_before_frame_id", "active_frame_id",
    "inactive_after_frame_id", "rect",
})
_TRANSITION_CHECK_KEYS = frozenset({
    "check_id", "transition_kind", "transition_receipt_sha256",
    "before_frame_id", "middle_frame_id", "after_frame_id",
})
_RECT_KEYS = frozenset({"x", "y", "width", "height"})

_RESULT_KEYS = frozenset({"schema_version", "receipt", "receipt_sha256"})
_RECEIPT_KEYS = frozenset({
    "schema_version", "analyzer", "binding", "scope", "checks", "summary",
})
_ANALYZER_KEYS = frozenset({"algorithm_version", "thresholds"})
_BINDING_KEYS = frozenset({
    "artifact_sha256", "decoder_receipt_sha256", "timeline_receipt_sha256",
    "request_sha256", "decoded_frames_sha256", "geometry_sha256",
    "timeline_sha256", "renderer_receipt_sha256s",
})
_SUMMARY_KEYS = frozenset({
    "check_count", "passed_count", "failed_count", "all_passed",
    "failed_check_ids",
})

_FRAME_METRIC_KEYS = frozenset({
    "mean_luma", "minimum_luma", "maximum_luma", "luma_range",
    "luma_mad", "black_pixel_ratio_ppm", "quantized_luma_bin_count",
})
_TEMPORAL_METRIC_KEYS = frozenset({
    "pair_count", "exact_duplicate_pair_count", "near_duplicate_pair_count",
    "longest_exact_duplicate_run_frames",
    "longest_exact_duplicate_duration_us",
    "longest_near_duplicate_run_frames",
    "longest_near_duplicate_duration_us", "maximum_pair_mae_ppm",
    "minimum_pair_mae_ppm", "flash_count", "maximum_isolated_luma_jump",
})
_GEOMETRY_METRIC_KEYS = frozenset({
    "rect_area_pixels", "canvas_intersection_area_pixels",
    "safe_area_intersection_area_pixels", "outside_canvas_area_pixels",
    "outside_safe_area_area_pixels",
})
_OVERLAY_METRIC_KEYS = frozenset({
    "rect_area_pixels", "sampled_area_pixels", "changed_pixel_count",
    "changed_pixel_ratio_ppm", "active_before_mae_ppm",
    "active_after_mae_ppm", "inactive_return_mae_ppm",
    "state_signal_ppm", "foreground_median_luma",
    "background_median_luma", "luma_contrast_ratio_ppm",
})
_TRANSITION_METRIC_KEYS = frozenset({
    "endpoint_mae_ppm", "before_middle_mae_ppm",
    "middle_after_mae_ppm", "estimated_after_weight_ppm",
    "blend_residual_mae_ppm", "between_component_ratio_ppm",
    "middle_black_pixel_ratio_ppm",
})

_FRAME_RESULT_KEYS = frozenset({
    "check_id", "frame_id", "expected_state", "frame_sha256", "metrics",
    "observations", "passed", "defects",
})
_TEMPORAL_RESULT_KEYS = frozenset({
    "check_id", "frame_ids", "expected_state", "frame_sha256s",
    "pair_mae_ppm", "metrics", "observations", "flash_frame_ids", "passed",
    "defects",
})
_GEOMETRY_RESULT_KEYS = frozenset({
    "check_id", "kind", "frame_id", "frame_sha256",
    "renderer_receipt_sha256", "rect", "safe_area", "metrics",
    "observations", "passed", "defects",
})
_OVERLAY_RESULT_KEYS = frozenset({
    "check_id", "kind", "renderer_receipt_sha256", "frame_ids",
    "frame_sha256s", "rect", "metrics", "observations", "passed",
    "defects",
})
_TRANSITION_RESULT_KEYS = frozenset({
    "check_id", "transition_kind", "transition_receipt_sha256", "frame_ids",
    "frame_sha256s", "metrics", "observations", "passed", "defects",
})

_DEFECTS = frozenset({
    "black_frame", "blank_frame", "expected_black_missing",
    "expected_uniform_frame_missing", "freeze_run", "isolated_flash",
    "unexpected_state_change", "outside_canvas", "outside_safe_area",
    "overlay_pixels_missing", "overlay_contrast_insufficient",
    "overlay_state_change_missing", "transition_endpoints_not_distinct",
    "transition_midpoint_out_of_range", "transition_blend_discontinuity",
    "unexpected_black_midpoint", "expected_black_midpoint_missing",
    "transition_edge_content_missing",
})


class VisualQualityDeterministicError(ValueError):
    """The closed visual evidence contract could not be established."""


def _fail(message: str) -> None:
    raise VisualQualityDeterministicError(message)


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
        raise VisualQualityDeterministicError(
            "visual quality evidence is not canonical JSON"
        ) from error


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _exact_dict(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys, key=str)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unsupported " + ", ".join(map(str, extra)))
        _fail(f"{label} has invalid keys ({'; '.join(details)})")
    return value


def _integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = 9_007_199_254_740_991,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be a boolean")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(f"{label} must be a bounded path-free identifier")
    return value


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(f"{label} is unsupported")
    return value


def _bounded_list(
    value: object, label: str, *, minimum: int = 0, maximum: int,
) -> list:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _fail(f"{label} must be a list with {minimum} to {maximum} items")
    return value


def _rounded_ratio(numerator: int, denominator: int, scale: int = 1_000_000) -> int:
    if denominator <= 0:
        return 0
    return (numerator * scale + denominator // 2) // denominator


def _rect(value: object, label: str, *, safe: bool = False) -> dict[str, int]:
    raw = _exact_dict(value, _RECT_KEYS, label)
    minimum_position = 0 if safe else -MAX_RECT_DIMENSION
    x = _integer(
        raw["x"], f"{label}.x", minimum=minimum_position,
        maximum=MAX_RECT_DIMENSION,
    )
    y = _integer(
        raw["y"], f"{label}.y", minimum=minimum_position,
        maximum=MAX_RECT_DIMENSION,
    )
    width = _integer(
        raw["width"], f"{label}.width", minimum=1,
        maximum=MAX_RECT_DIMENSION,
    )
    height = _integer(
        raw["height"], f"{label}.height", minimum=1,
        maximum=MAX_RECT_DIMENSION,
    )
    return {"x": x, "y": y, "width": width, "height": height}


def _frame_rate(value: object) -> dict[str, int]:
    raw = _exact_dict(value, _FRAME_RATE_KEYS, "request.timeline.frame_rate")
    numerator = _integer(
        raw["numerator"], "request.timeline.frame_rate.numerator",
        minimum=1, maximum=240_000,
    )
    denominator = _integer(
        raw["denominator"], "request.timeline.frame_rate.denominator",
        minimum=1, maximum=10_000,
    )
    if math.gcd(numerator, denominator) != 1:
        _fail("request.timeline.frame_rate must be a reduced rational")
    if numerator < denominator or numerator > 240 * denominator:
        _fail("request.timeline.frame_rate must be from 1 to 240 fps")
    return {"numerator": numerator, "denominator": denominator}


def _frame_reference(
    value: object,
    label: str,
    frame_by_id: Mapping[str, dict[str, Any]],
) -> str:
    frame_id = _identifier(value, label)
    if frame_id not in frame_by_id:
        _fail(f"{label} does not reference a decoded frame")
    return frame_id


def _validate_request(value: object) -> dict[str, Any]:
    raw = _exact_dict(value, _REQUEST_KEYS, "request")
    if raw["schema_version"] != VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION:
        _fail("request.schema_version is unsupported")
    artifact_sha256 = _digest(raw["artifact_sha256"], "request.artifact_sha256")
    decoder_receipt_sha256 = _digest(
        raw["decoder_receipt_sha256"], "request.decoder_receipt_sha256",
    )
    timeline_receipt_sha256 = _digest(
        raw["timeline_receipt_sha256"], "request.timeline_receipt_sha256",
    )

    raw_geometry = _exact_dict(raw["geometry"], _GEOMETRY_KEYS, "request.geometry")
    width = _integer(
        raw_geometry["width"], "request.geometry.width", minimum=16,
        maximum=MAX_FRAME_DIMENSION,
    )
    height = _integer(
        raw_geometry["height"], "request.geometry.height", minimum=16,
        maximum=MAX_FRAME_DIMENSION,
    )
    if width * height > MAX_FRAME_PIXELS:
        _fail("request.geometry exceeds the bounded pixel count")
    if raw_geometry["pixel_format"] != "rgb24":
        _fail("request.geometry.pixel_format must be rgb24")
    geometry = {"width": width, "height": height, "pixel_format": "rgb24"}

    raw_timeline = _exact_dict(raw["timeline"], _TIMELINE_KEYS, "request.timeline")
    frame_rate = _frame_rate(raw_timeline["frame_rate"])
    raw_frames = _bounded_list(
        raw_timeline["frames"], "request.timeline.frames",
        minimum=1, maximum=MAX_FRAMES,
    )
    frames: list[dict[str, Any]] = []
    frame_by_id: dict[str, dict[str, Any]] = {}
    previous_index = -1
    previous_timestamp = -1
    first_index = 0
    first_timestamp = 0
    for position, value_frame in enumerate(raw_frames):
        label = f"request.timeline.frames[{position}]"
        item = _exact_dict(value_frame, _FRAME_KEYS, label)
        frame_id = _identifier(item["frame_id"], f"{label}.frame_id")
        if frame_id in frame_by_id:
            _fail(f"{label}.frame_id is duplicated")
        frame_index = _integer(
            item["frame_index"], f"{label}.frame_index",
            maximum=MAX_FRAME_INDEX,
        )
        timestamp_us = _integer(
            item["timestamp_us"], f"{label}.timestamp_us",
            maximum=MAX_TIMESTAMP_US,
        )
        if position and frame_index <= previous_index:
            _fail("request.timeline frame indices must be strictly increasing")
        if position and timestamp_us <= previous_timestamp:
            _fail("request.timeline timestamps must be strictly increasing")
        if position == 0:
            first_index = frame_index
            first_timestamp = timestamp_us
        else:
            frame_delta = frame_index - first_index
            expected_delta = _rounded_ratio(
                frame_delta * frame_rate["denominator"],
                frame_rate["numerator"],
                1_000_000,
            )
            actual_delta = timestamp_us - first_timestamp
            if abs(actual_delta - expected_delta) > 1:
                _fail("request.timeline timestamps do not match the frame clock")
        normalized_frame = {
            "frame_id": frame_id,
            "frame_index": frame_index,
            "timestamp_us": timestamp_us,
            "rgb24_sha256": _digest(
                item["rgb24_sha256"], f"{label}.rgb24_sha256",
            ),
        }
        frames.append(normalized_frame)
        frame_by_id[frame_id] = normalized_frame
        previous_index = frame_index
        previous_timestamp = timestamp_us
    timeline = {"frame_rate": frame_rate, "frames": frames}

    raw_checks = _exact_dict(raw["checks"], _CHECKS_KEYS, "request.checks")
    normalized_checks: dict[str, list[dict[str, Any]]] = {
        key: [] for key in (
            "frame_state", "temporal_window", "geometry", "overlay",
            "transition",
        )
    }
    check_ids: set[str] = set()

    def check_id(item: dict, label: str) -> str:
        result = _identifier(item["check_id"], f"{label}.check_id")
        if result in check_ids:
            _fail(f"{label}.check_id is duplicated")
        check_ids.add(result)
        return result

    raw_frame_checks = _bounded_list(
        raw_checks["frame_state"], "request.checks.frame_state",
        maximum=MAX_CHECKS_PER_KIND,
    )
    for index, value_check in enumerate(raw_frame_checks):
        label = f"request.checks.frame_state[{index}]"
        item = _exact_dict(value_check, _FRAME_STATE_KEYS, label)
        normalized_checks["frame_state"].append({
            "check_id": check_id(item, label),
            "frame_id": _frame_reference(
                item["frame_id"], f"{label}.frame_id", frame_by_id,
            ),
            "expected_state": _enum(
                item["expected_state"],
                frozenset({"non_blank_content", "black", "uniform", "observe"}),
                f"{label}.expected_state",
            ),
        })

    raw_temporal_checks = _bounded_list(
        raw_checks["temporal_window"], "request.checks.temporal_window",
        maximum=MAX_CHECKS_PER_KIND,
    )
    for index, value_check in enumerate(raw_temporal_checks):
        label = f"request.checks.temporal_window[{index}]"
        item = _exact_dict(value_check, _TEMPORAL_WINDOW_KEYS, label)
        raw_ids = _bounded_list(
            item["frame_ids"], f"{label}.frame_ids",
            minimum=3, maximum=MAX_WINDOW_FRAMES,
        )
        frame_ids = [
            _frame_reference(value_id, f"{label}.frame_ids[{position}]", frame_by_id)
            for position, value_id in enumerate(raw_ids)
        ]
        if len(set(frame_ids)) != len(frame_ids):
            _fail(f"{label}.frame_ids contains duplicates")
        indices = [frame_by_id[value_id]["frame_index"] for value_id in frame_ids]
        if any(right != left + 1 for left, right in zip(indices, indices[1:])):
            _fail(f"{label}.frame_ids must be consecutive decoded frames")
        normalized_checks["temporal_window"].append({
            "check_id": check_id(item, label),
            "frame_ids": frame_ids,
            "expected_state": _enum(
                item["expected_state"],
                frozenset({"motion_expected", "stable_expected", "observe"}),
                f"{label}.expected_state",
            ),
        })

    raw_geometry_checks = _bounded_list(
        raw_checks["geometry"], "request.checks.geometry",
        maximum=MAX_CHECKS_PER_KIND,
    )
    for index, value_check in enumerate(raw_geometry_checks):
        label = f"request.checks.geometry[{index}]"
        item = _exact_dict(value_check, _GEOMETRY_CHECK_KEYS, label)
        safe_area = _rect(item["safe_area"], f"{label}.safe_area", safe=True)
        if (
            safe_area["x"] + safe_area["width"] > width
            or safe_area["y"] + safe_area["height"] > height
        ):
            _fail(f"{label}.safe_area must be inside the decoded canvas")
        normalized_checks["geometry"].append({
            "check_id": check_id(item, label),
            "kind": _enum(
                item["kind"], frozenset({"caption", "graphic"}),
                f"{label}.kind",
            ),
            "frame_id": _frame_reference(
                item["frame_id"], f"{label}.frame_id", frame_by_id,
            ),
            "renderer_receipt_sha256": _digest(
                item["renderer_receipt_sha256"],
                f"{label}.renderer_receipt_sha256",
            ),
            "rect": _rect(item["rect"], f"{label}.rect"),
            "safe_area": safe_area,
        })

    raw_overlay_checks = _bounded_list(
        raw_checks["overlay"], "request.checks.overlay",
        maximum=MAX_CHECKS_PER_KIND,
    )
    for index, value_check in enumerate(raw_overlay_checks):
        label = f"request.checks.overlay[{index}]"
        item = _exact_dict(value_check, _OVERLAY_CHECK_KEYS, label)
        before_id = _frame_reference(
            item["inactive_before_frame_id"],
            f"{label}.inactive_before_frame_id", frame_by_id,
        )
        active_id = _frame_reference(
            item["active_frame_id"], f"{label}.active_frame_id", frame_by_id,
        )
        after_id = _frame_reference(
            item["inactive_after_frame_id"],
            f"{label}.inactive_after_frame_id", frame_by_id,
        )
        indices = [
            frame_by_id[before_id]["frame_index"],
            frame_by_id[active_id]["frame_index"],
            frame_by_id[after_id]["frame_index"],
        ]
        if not indices[0] < indices[1] < indices[2]:
            _fail(f"{label} frames must be in timeline order")
        normalized_checks["overlay"].append({
            "check_id": check_id(item, label),
            "kind": _enum(
                item["kind"], frozenset({"caption", "graphic"}),
                f"{label}.kind",
            ),
            "renderer_receipt_sha256": _digest(
                item["renderer_receipt_sha256"],
                f"{label}.renderer_receipt_sha256",
            ),
            "inactive_before_frame_id": before_id,
            "active_frame_id": active_id,
            "inactive_after_frame_id": after_id,
            "rect": _rect(item["rect"], f"{label}.rect"),
        })

    raw_transition_checks = _bounded_list(
        raw_checks["transition"], "request.checks.transition",
        maximum=MAX_CHECKS_PER_KIND,
    )
    for index, value_check in enumerate(raw_transition_checks):
        label = f"request.checks.transition[{index}]"
        item = _exact_dict(value_check, _TRANSITION_CHECK_KEYS, label)
        before_id = _frame_reference(
            item["before_frame_id"], f"{label}.before_frame_id", frame_by_id,
        )
        middle_id = _frame_reference(
            item["middle_frame_id"], f"{label}.middle_frame_id", frame_by_id,
        )
        after_id = _frame_reference(
            item["after_frame_id"], f"{label}.after_frame_id", frame_by_id,
        )
        indices = [
            frame_by_id[before_id]["frame_index"],
            frame_by_id[middle_id]["frame_index"],
            frame_by_id[after_id]["frame_index"],
        ]
        if not indices[0] < indices[1] < indices[2]:
            _fail(f"{label} frames must be in timeline order")
        normalized_checks["transition"].append({
            "check_id": check_id(item, label),
            "transition_kind": _enum(
                item["transition_kind"],
                frozenset({"cross_dissolve", "dip_to_black"}),
                f"{label}.transition_kind",
            ),
            "transition_receipt_sha256": _digest(
                item["transition_receipt_sha256"],
                f"{label}.transition_receipt_sha256",
            ),
            "before_frame_id": before_id,
            "middle_frame_id": middle_id,
            "after_frame_id": after_id,
        })

    return {
        "schema_version": VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION,
        "artifact_sha256": artifact_sha256,
        "decoder_receipt_sha256": decoder_receipt_sha256,
        "timeline_receipt_sha256": timeline_receipt_sha256,
        "geometry": geometry,
        "timeline": timeline,
        "checks": normalized_checks,
    }


def _validated_decoded_frames(
    value: object,
    request: dict[str, Any],
) -> tuple[dict[str, np.ndarray], str]:
    if type(value) is not dict:
        _fail("decoded_frames must be an exact frame_id to bytes object")
    frames = request["timeline"]["frames"]
    expected_ids = {item["frame_id"] for item in frames}
    actual_ids = set(value)
    if actual_ids != expected_ids:
        _fail("decoded frame ids do not exactly match request.timeline.frames")
    width = request["geometry"]["width"]
    height = request["geometry"]["height"]
    expected_bytes = width * height * 3
    total_bytes = expected_bytes * len(frames)
    if total_bytes > MAX_DECODED_BYTES:
        _fail("decoded frames exceed the bounded byte budget")

    arrays: dict[str, np.ndarray] = {}
    identities: list[dict[str, Any]] = []
    for item in frames:
        frame_id = item["frame_id"]
        payload = value[frame_id]
        if type(payload) is not bytes or len(payload) != expected_bytes:
            _fail(
                f"decoded frame {frame_id} must be exact bounded rgb24 bytes"
            )
        measured = hashlib.sha256(payload).hexdigest()
        if measured != item["rgb24_sha256"]:
            _fail(f"decoded frame {frame_id} hash does not match its receipt")
        array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3)
        array.setflags(write=False)
        arrays[frame_id] = array
        identities.append({
            "frame_id": frame_id,
            "rgb24_sha256": measured,
            "bytes": len(payload),
        })
    return arrays, _canonical_sha256(identities)


def _row_chunks(height: int, width: int):
    rows = max(1, _CHUNK_PIXELS // max(1, width))
    for start in range(0, height, rows):
        yield slice(start, min(height, start + rows))


def _luma(array: np.ndarray) -> np.ndarray:
    wide = array.astype(np.uint16, copy=False)
    return (
        wide[..., 0] * 54
        + wide[..., 1] * 183
        + wide[..., 2] * 19
        + 128
    ) // 256


def _frame_metrics(array: np.ndarray) -> dict[str, int]:
    histogram = np.zeros(256, dtype=np.int64)
    for rows in _row_chunks(array.shape[0], array.shape[1]):
        luminance = _luma(array[rows])
        histogram += np.bincount(luminance.reshape(-1), minlength=256)
    counts = [int(item) for item in histogram]
    pixel_count = array.shape[0] * array.shape[1]
    occupied = [index for index, count in enumerate(counts) if count]
    minimum = occupied[0]
    maximum = occupied[-1]
    weighted = sum(index * count for index, count in enumerate(counts))
    mean = (weighted + pixel_count // 2) // pixel_count
    mad_total = sum(
        abs(index - mean) * count for index, count in enumerate(counts)
    )
    mad = (mad_total + pixel_count // 2) // pixel_count
    black_count = sum(counts[:BLACK_LUMA_MAX + 1])
    quantized_bins = sum(
        1 for start in range(0, 256, 16) if sum(counts[start:start + 16])
    )
    return {
        "mean_luma": mean,
        "minimum_luma": minimum,
        "maximum_luma": maximum,
        "luma_range": maximum - minimum,
        "luma_mad": mad,
        "black_pixel_ratio_ppm": _rounded_ratio(black_count, pixel_count),
        "quantized_luma_bin_count": quantized_bins,
    }


def _is_black(metrics: Mapping[str, int]) -> bool:
    return metrics["black_pixel_ratio_ppm"] >= BLACK_PIXEL_RATIO_PPM_MIN


def _is_blank(metrics: Mapping[str, int]) -> bool:
    return (
        metrics["luma_range"] <= BLANK_LUMA_RANGE_MAX
        and metrics["luma_mad"] <= BLANK_LUMA_MAD_MAX
    )


def _pair_mae_ppm(left: np.ndarray, right: np.ndarray) -> int:
    total = 0
    for rows in _row_chunks(left.shape[0], left.shape[1]):
        difference = (
            left[rows].astype(np.int16) - right[rows].astype(np.int16)
        )
        total += int(np.abs(difference).sum(dtype=np.int64))
    denominator = left.size * 255
    return _rounded_ratio(total, denominator)


def _longest_run(
    flags: Sequence[bool],
    frame_ids: Sequence[str],
    frame_by_id: Mapping[str, dict[str, Any]],
) -> tuple[int, int]:
    best_frames = 1
    best_duration = 0
    start = 0
    for pair_index, flag in enumerate(flags):
        if not flag:
            start = pair_index + 1
            continue
        end = pair_index + 1
        count = end - start + 1
        duration = (
            frame_by_id[frame_ids[end]]["timestamp_us"]
            - frame_by_id[frame_ids[start]]["timestamp_us"]
        )
        if duration > best_duration or (
            duration == best_duration and count > best_frames
        ):
            best_frames = count
            best_duration = duration
    return best_frames, best_duration


def _intersection_area(left: Mapping[str, int], right: Mapping[str, int]) -> int:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["width"], right["x"] + right["width"])
    y2 = min(left["y"] + left["height"], right["y"] + right["height"])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _clipped_rect(
    rect: Mapping[str, int], width: int, height: int,
) -> tuple[int, int, int, int]:
    x1 = max(0, rect["x"])
    y1 = max(0, rect["y"])
    x2 = min(width, rect["x"] + rect["width"])
    y2 = min(height, rect["y"] + rect["height"])
    return x1, y1, max(x1, x2), max(y1, y2)


def _median_from_histogram(histogram: np.ndarray) -> int:
    total = int(histogram.sum(dtype=np.int64))
    if total < 1:
        return 0
    target = (total - 1) // 2
    cumulative = 0
    for index, count in enumerate(histogram):
        cumulative += int(count)
        if cumulative > target:
            return index
    return 255


def _overlay_metrics(
    before: np.ndarray,
    active: np.ndarray,
    after: np.ndarray,
    rect: Mapping[str, int],
) -> dict[str, int]:
    height, width = active.shape[:2]
    x1, y1, x2, y2 = _clipped_rect(rect, width, height)
    rect_area = rect["width"] * rect["height"]
    sampled_area = max(0, x2 - x1) * max(0, y2 - y1)
    changed = 0
    active_before_total = 0
    active_after_total = 0
    inactive_total = 0
    foreground_histogram = np.zeros(256, dtype=np.int64)
    background_histogram = np.zeros(256, dtype=np.int64)
    if sampled_area:
        crop_width = x2 - x1
        rows_per_chunk = max(1, _CHUNK_PIXELS // crop_width)
        for start in range(y1, y2, rows_per_chunk):
            stop = min(y2, start + rows_per_chunk)
            before_chunk = before[start:stop, x1:x2]
            active_chunk = active[start:stop, x1:x2]
            after_chunk = after[start:stop, x1:x2]
            before_wide = before_chunk.astype(np.int16)
            active_wide = active_chunk.astype(np.int16)
            after_wide = after_chunk.astype(np.int16)
            before_difference = np.abs(active_wide - before_wide)
            after_difference = np.abs(active_wide - after_wide)
            inactive_difference = np.abs(before_wide - after_wide)
            active_before_total += int(before_difference.sum(dtype=np.int64))
            active_after_total += int(after_difference.sum(dtype=np.int64))
            inactive_total += int(inactive_difference.sum(dtype=np.int64))
            presence = (
                np.max(before_difference, axis=2) > OVERLAY_CHANNEL_DELTA_MIN
            ) & (
                np.max(after_difference, axis=2) > OVERLAY_CHANNEL_DELTA_MIN
            )
            present_count = int(np.count_nonzero(presence))
            changed += present_count
            if present_count:
                foreground_luma = _luma(active_chunk)[presence]
                background_rgb = (
                    before_chunk.astype(np.uint16)
                    + after_chunk.astype(np.uint16)
                    + 1
                ) // 2
                background_luma = _luma(background_rgb.astype(np.uint8))[presence]
                foreground_histogram += np.bincount(
                    foreground_luma.reshape(-1), minlength=256,
                )
                background_histogram += np.bincount(
                    background_luma.reshape(-1), minlength=256,
                )
    pair_denominator = sampled_area * 3 * 255
    active_before_mae = _rounded_ratio(active_before_total, pair_denominator)
    active_after_mae = _rounded_ratio(active_after_total, pair_denominator)
    inactive_mae = _rounded_ratio(inactive_total, pair_denominator)
    state_signal = max(
        0, min(active_before_mae, active_after_mae) - inactive_mae,
    )
    foreground = _median_from_histogram(foreground_histogram)
    background = _median_from_histogram(background_histogram)
    high = max(foreground, background)
    low = min(foreground, background)
    contrast = ((high + 13) * 1_000_000) // (low + 13) if changed else 0
    return {
        "rect_area_pixels": rect_area,
        "sampled_area_pixels": sampled_area,
        "changed_pixel_count": changed,
        "changed_pixel_ratio_ppm": _rounded_ratio(changed, rect_area),
        "active_before_mae_ppm": active_before_mae,
        "active_after_mae_ppm": active_after_mae,
        "inactive_return_mae_ppm": inactive_mae,
        "state_signal_ppm": state_signal,
        "foreground_median_luma": foreground,
        "background_median_luma": background,
        "luma_contrast_ratio_ppm": contrast,
    }


def _transition_projection_metrics(
    before: np.ndarray, middle: np.ndarray, after: np.ndarray,
) -> tuple[int, int, int]:
    numerator = 0
    denominator = 0
    between_count = 0
    for rows in _row_chunks(before.shape[0], before.shape[1]):
        before_chunk = before[rows].astype(np.int32)
        middle_chunk = middle[rows].astype(np.int32)
        after_chunk = after[rows].astype(np.int32)
        difference = after_chunk - before_chunk
        offset = middle_chunk - before_chunk
        numerator += int((offset.astype(np.int64) * difference).sum(dtype=np.int64))
        denominator += int((difference.astype(np.int64) ** 2).sum(dtype=np.int64))
        lower = np.minimum(before_chunk, after_chunk) - 2
        upper = np.maximum(before_chunk, after_chunk) + 2
        between_count += int(np.count_nonzero(
            (middle_chunk >= lower) & (middle_chunk <= upper)
        ))
    if denominator:
        if numerator >= 0:
            alpha = (numerator * 1_000_000 + denominator // 2) // denominator
        else:
            alpha = -((-numerator * 1_000_000 + denominator // 2) // denominator)
        alpha = min(1_000_000, max(0, alpha))
    else:
        alpha = 0

    residual_total = 0
    for rows in _row_chunks(before.shape[0], before.shape[1]):
        before_chunk = before[rows].astype(np.int64)
        middle_chunk = middle[rows].astype(np.int64)
        after_chunk = after[rows].astype(np.int64)
        difference = after_chunk - before_chunk
        offset = middle_chunk - before_chunk
        residual_total += int(np.abs(
            offset * 1_000_000 - difference * alpha
        ).sum(dtype=np.int64))
    residual = (
        (residual_total + (before.size * 255) // 2)
        // (before.size * 255)
    )
    between_ratio = _rounded_ratio(between_count, before.size)
    return alpha, residual, between_ratio


def _frame_result(
    check: Mapping[str, Any],
    frame_by_id: Mapping[str, dict[str, Any]],
    metrics_by_id: Mapping[str, dict[str, int]],
) -> dict[str, Any]:
    frame_id = check["frame_id"]
    metrics = metrics_by_id[frame_id]
    black = _is_black(metrics)
    blank = _is_blank(metrics)
    expected = check["expected_state"]
    defects: list[str] = []
    if expected == "non_blank_content":
        if black:
            defects.append("black_frame")
        elif blank:
            defects.append("blank_frame")
    elif expected == "black" and not black:
        defects.append("expected_black_missing")
    elif expected == "uniform" and not blank:
        defects.append("expected_uniform_frame_missing")
    return {
        "check_id": check["check_id"],
        "frame_id": frame_id,
        "expected_state": expected,
        "frame_sha256": frame_by_id[frame_id]["rgb24_sha256"],
        "metrics": dict(metrics),
        "observations": {"black": black, "blank": blank},
        "passed": not defects,
        "defects": defects,
    }


def _temporal_result(
    check: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    frame_by_id: Mapping[str, dict[str, Any]],
    metrics_by_id: Mapping[str, dict[str, int]],
) -> dict[str, Any]:
    frame_ids = check["frame_ids"]
    pair_mae = [
        _pair_mae_ppm(arrays[left], arrays[right])
        for left, right in zip(frame_ids, frame_ids[1:])
    ]
    exact_flags = [
        frame_by_id[left]["rgb24_sha256"] == frame_by_id[right]["rgb24_sha256"]
        for left, right in zip(frame_ids, frame_ids[1:])
    ]
    near_flags = [value <= NEAR_DUPLICATE_MAE_PPM_MAX for value in pair_mae]
    exact_frames, exact_duration = _longest_run(
        exact_flags, frame_ids, frame_by_id,
    )
    near_frames, near_duration = _longest_run(
        near_flags, frame_ids, frame_by_id,
    )
    freeze = near_duration >= FREEZE_DURATION_US_MIN

    flash_ids: list[str] = []
    maximum_jump = 0
    for position in range(1, len(frame_ids) - 1):
        left_id = frame_ids[position - 1]
        middle_id = frame_ids[position]
        right_id = frame_ids[position + 1]
        left_mean = metrics_by_id[left_id]["mean_luma"]
        middle_mean = metrics_by_id[middle_id]["mean_luma"]
        right_mean = metrics_by_id[right_id]["mean_luma"]
        isolated_jump = min(
            abs(middle_mean - left_mean), abs(middle_mean - right_mean),
        )
        outer_mae = _pair_mae_ppm(arrays[left_id], arrays[right_id])
        if (
            isolated_jump >= FLASH_LUMA_JUMP_MIN
            and outer_mae <= FLASH_OUTER_MAE_PPM_MAX
        ):
            flash_ids.append(middle_id)
            maximum_jump = max(maximum_jump, isolated_jump)
    flash = bool(flash_ids)
    expected = check["expected_state"]
    defects: list[str] = []
    if expected == "motion_expected":
        if freeze:
            defects.append("freeze_run")
        if flash:
            defects.append("isolated_flash")
    elif expected == "stable_expected":
        if not all(near_flags):
            defects.append("unexpected_state_change")
        if flash:
            defects.append("isolated_flash")
    metrics = {
        "pair_count": len(pair_mae),
        "exact_duplicate_pair_count": sum(exact_flags),
        "near_duplicate_pair_count": sum(near_flags),
        "longest_exact_duplicate_run_frames": exact_frames,
        "longest_exact_duplicate_duration_us": exact_duration,
        "longest_near_duplicate_run_frames": near_frames,
        "longest_near_duplicate_duration_us": near_duration,
        "maximum_pair_mae_ppm": max(pair_mae),
        "minimum_pair_mae_ppm": min(pair_mae),
        "flash_count": len(flash_ids),
        "maximum_isolated_luma_jump": maximum_jump,
    }
    return {
        "check_id": check["check_id"],
        "frame_ids": list(frame_ids),
        "expected_state": expected,
        "frame_sha256s": [
            frame_by_id[frame_id]["rgb24_sha256"] for frame_id in frame_ids
        ],
        "pair_mae_ppm": pair_mae,
        "metrics": metrics,
        "observations": {
            "freeze_run": freeze,
            "isolated_flash": flash,
            "stable": all(near_flags),
        },
        "flash_frame_ids": flash_ids,
        "passed": not defects,
        "defects": defects,
    }


def _geometry_result(
    check: Mapping[str, Any],
    frame_by_id: Mapping[str, dict[str, Any]],
    width: int,
    height: int,
) -> dict[str, Any]:
    rect = check["rect"]
    safe_area = check["safe_area"]
    canvas = {"x": 0, "y": 0, "width": width, "height": height}
    area = rect["width"] * rect["height"]
    canvas_intersection = _intersection_area(rect, canvas)
    safe_intersection = _intersection_area(rect, safe_area)
    outside_canvas = area - canvas_intersection
    outside_safe = area - safe_intersection
    defects = []
    if outside_canvas:
        defects.append("outside_canvas")
    if outside_safe:
        defects.append("outside_safe_area")
    frame_id = check["frame_id"]
    return {
        "check_id": check["check_id"],
        "kind": check["kind"],
        "frame_id": frame_id,
        "frame_sha256": frame_by_id[frame_id]["rgb24_sha256"],
        "renderer_receipt_sha256": check["renderer_receipt_sha256"],
        "rect": dict(rect),
        "safe_area": dict(safe_area),
        "metrics": {
            "rect_area_pixels": area,
            "canvas_intersection_area_pixels": canvas_intersection,
            "safe_area_intersection_area_pixels": safe_intersection,
            "outside_canvas_area_pixels": outside_canvas,
            "outside_safe_area_area_pixels": outside_safe,
        },
        "observations": {
            "inside_canvas": outside_canvas == 0,
            "inside_safe_area": outside_safe == 0,
        },
        "passed": not defects,
        "defects": defects,
    }


def _overlay_result(
    check: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    frame_by_id: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    frame_ids = [
        check["inactive_before_frame_id"], check["active_frame_id"],
        check["inactive_after_frame_id"],
    ]
    metrics = _overlay_metrics(
        arrays[frame_ids[0]], arrays[frame_ids[1]], arrays[frame_ids[2]],
        check["rect"],
    )
    height, width = arrays[frame_ids[1]].shape[:2]
    rect_inside_canvas = (
        check["rect"]["x"] >= 0
        and check["rect"]["y"] >= 0
        and check["rect"]["x"] + check["rect"]["width"] <= width
        and check["rect"]["y"] + check["rect"]["height"] <= height
    )
    pixel_present = (
        metrics["changed_pixel_ratio_ppm"] >= OVERLAY_PIXEL_PRESENCE_PPM_MIN
    )
    state_changed = metrics["state_signal_ppm"] >= OVERLAY_STATE_SIGNAL_PPM_MIN
    contrast_threshold = (
        CAPTION_CONTRAST_RATIO_PPM_MIN
        if check["kind"] == "caption"
        else GRAPHIC_CONTRAST_RATIO_PPM_MIN
    )
    contrast_sufficient = (
        metrics["luma_contrast_ratio_ppm"] >= contrast_threshold
    )
    defects = []
    if not rect_inside_canvas:
        defects.append("outside_canvas")
    if not pixel_present:
        defects.append("overlay_pixels_missing")
    if not contrast_sufficient:
        defects.append("overlay_contrast_insufficient")
    if not state_changed:
        defects.append("overlay_state_change_missing")
    return {
        "check_id": check["check_id"],
        "kind": check["kind"],
        "renderer_receipt_sha256": check["renderer_receipt_sha256"],
        "frame_ids": frame_ids,
        "frame_sha256s": [
            frame_by_id[frame_id]["rgb24_sha256"] for frame_id in frame_ids
        ],
        "rect": dict(check["rect"]),
        "metrics": metrics,
        "observations": {
            "rect_inside_canvas": rect_inside_canvas,
            "pixel_present": pixel_present,
            "contrast_sufficient": contrast_sufficient,
            "state_changed": state_changed,
        },
        "passed": not defects,
        "defects": defects,
    }


def _transition_result(
    check: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    frame_by_id: Mapping[str, dict[str, Any]],
    metrics_by_id: Mapping[str, dict[str, int]],
) -> dict[str, Any]:
    frame_ids = [
        check["before_frame_id"], check["middle_frame_id"],
        check["after_frame_id"],
    ]
    before, middle, after = [arrays[frame_id] for frame_id in frame_ids]
    endpoint_mae = _pair_mae_ppm(before, after)
    before_middle_mae = _pair_mae_ppm(before, middle)
    middle_after_mae = _pair_mae_ppm(middle, after)
    alpha, residual, between_ratio = _transition_projection_metrics(
        before, middle, after,
    )
    middle_black_ratio = metrics_by_id[frame_ids[1]]["black_pixel_ratio_ppm"]
    before_black = _is_black(metrics_by_id[frame_ids[0]])
    after_black = _is_black(metrics_by_id[frame_ids[2]])
    endpoint_distinct = endpoint_mae >= TRANSITION_ENDPOINT_MAE_PPM_MIN
    midpoint_in_range = (
        TRANSITION_ALPHA_PPM_MIN <= alpha <= TRANSITION_ALPHA_PPM_MAX
        and before_middle_mae < endpoint_mae
        and middle_after_mae < endpoint_mae
    )
    unexpected_black = middle_black_ratio >= BLACK_PIXEL_RATIO_PPM_MIN
    expected_black = middle_black_ratio >= DIP_BLACK_PIXEL_RATIO_PPM_MIN
    blend_continuous = (
        endpoint_distinct
        and midpoint_in_range
        and residual <= TRANSITION_BLEND_RESIDUAL_PPM_MAX
        and between_ratio >= TRANSITION_BETWEEN_COMPONENT_RATIO_PPM_MIN
        and not unexpected_black
    )

    defects = []
    if not endpoint_distinct:
        defects.append("transition_endpoints_not_distinct")
    if before_black or after_black:
        defects.append("transition_edge_content_missing")
    if check["transition_kind"] == "cross_dissolve":
        if not midpoint_in_range:
            defects.append("transition_midpoint_out_of_range")
        if not blend_continuous:
            defects.append("transition_blend_discontinuity")
        if unexpected_black:
            defects.append("unexpected_black_midpoint")
    elif not expected_black:
        defects.append("expected_black_midpoint_missing")

    return {
        "check_id": check["check_id"],
        "transition_kind": check["transition_kind"],
        "transition_receipt_sha256": check["transition_receipt_sha256"],
        "frame_ids": frame_ids,
        "frame_sha256s": [
            frame_by_id[frame_id]["rgb24_sha256"] for frame_id in frame_ids
        ],
        "metrics": {
            "endpoint_mae_ppm": endpoint_mae,
            "before_middle_mae_ppm": before_middle_mae,
            "middle_after_mae_ppm": middle_after_mae,
            "estimated_after_weight_ppm": alpha,
            "blend_residual_mae_ppm": residual,
            "between_component_ratio_ppm": between_ratio,
            "middle_black_pixel_ratio_ppm": middle_black_ratio,
        },
        "observations": {
            "endpoint_distinct": endpoint_distinct,
            "midpoint_in_range": midpoint_in_range,
            "blend_continuous": blend_continuous,
            "unexpected_black_midpoint": unexpected_black,
            "expected_black_midpoint": expected_black,
            "edge_content_present": not before_black and not after_black,
        },
        "passed": not defects,
        "defects": defects,
    }


def analyze_visual_quality_deterministic(
    request: object,
    decoded_frames: object,
) -> dict[str, Any]:
    """Analyze exact trusted RGB frames and return a hash-bound v1 result.

    ``request`` is a JSON-safe closed schema.  ``decoded_frames`` must be an
    exact ``dict[str, bytes]`` whose keys and SHA-256 values match the timeline
    declarations.  No paths, decoders, network access, OCR, or model inference
    are accepted at this seam.
    """
    normalized = _validate_request(request)
    arrays, decoded_frames_sha256 = _validated_decoded_frames(
        decoded_frames, normalized,
    )
    frames = normalized["timeline"]["frames"]
    frame_by_id = {item["frame_id"]: item for item in frames}

    required_metric_ids = {
        check["frame_id"] for check in normalized["checks"]["frame_state"]
    }
    for check in normalized["checks"]["temporal_window"]:
        required_metric_ids.update(check["frame_ids"])
    for check in normalized["checks"]["transition"]:
        required_metric_ids.update({
            check["before_frame_id"], check["middle_frame_id"],
            check["after_frame_id"],
        })
    metrics_by_id = {
        frame_id: _frame_metrics(arrays[frame_id])
        for frame_id in sorted(required_metric_ids)
    }

    checks = {
        "frame_state": [
            _frame_result(check, frame_by_id, metrics_by_id)
            for check in normalized["checks"]["frame_state"]
        ],
        "temporal_window": [
            _temporal_result(
                check, arrays, frame_by_id, metrics_by_id,
            )
            for check in normalized["checks"]["temporal_window"]
        ],
        "geometry": [
            _geometry_result(
                check, frame_by_id, normalized["geometry"]["width"],
                normalized["geometry"]["height"],
            )
            for check in normalized["checks"]["geometry"]
        ],
        "overlay": [
            _overlay_result(check, arrays, frame_by_id)
            for check in normalized["checks"]["overlay"]
        ],
        "transition": [
            _transition_result(
                check, arrays, frame_by_id, metrics_by_id,
            )
            for check in normalized["checks"]["transition"]
        ],
    }
    ordered_results = [
        result
        for key in (
            "frame_state", "temporal_window", "geometry", "overlay",
            "transition",
        )
        for result in checks[key]
    ]
    failed_ids = [
        result["check_id"] for result in ordered_results if not result["passed"]
    ]
    renderer_receipts = sorted({
        check[key]
        for kind, key in (
            ("geometry", "renderer_receipt_sha256"),
            ("overlay", "renderer_receipt_sha256"),
            ("transition", "transition_receipt_sha256"),
        )
        for check in normalized["checks"][kind]
    })
    receipt = {
        "schema_version": VISUAL_QUALITY_DETERMINISTIC_RECEIPT_SCHEMA_VERSION,
        "analyzer": {
            "algorithm_version": VISUAL_QUALITY_DETERMINISTIC_ALGORITHM_VERSION,
            "thresholds": dict(_THRESHOLDS),
        },
        "binding": {
            "artifact_sha256": normalized["artifact_sha256"],
            "decoder_receipt_sha256": normalized["decoder_receipt_sha256"],
            "timeline_receipt_sha256": normalized["timeline_receipt_sha256"],
            "request_sha256": _canonical_sha256(normalized),
            "decoded_frames_sha256": decoded_frames_sha256,
            "geometry_sha256": _canonical_sha256(normalized["geometry"]),
            "timeline_sha256": _canonical_sha256(normalized["timeline"]),
            "renderer_receipt_sha256s": renderer_receipts,
        },
        "scope": {key: list(value) for key, value in _SCOPE.items()},
        "checks": checks,
        "summary": {
            "check_count": len(ordered_results),
            "passed_count": len(ordered_results) - len(failed_ids),
            "failed_count": len(failed_ids),
            "all_passed": not failed_ids,
            "failed_check_ids": failed_ids,
        },
    }
    result = {
        "schema_version": VISUAL_QUALITY_DETERMINISTIC_RESULT_SCHEMA_VERSION,
        "receipt": receipt,
        "receipt_sha256": _canonical_sha256(receipt),
    }
    verify_visual_quality_deterministic_result(result)
    return result


def _metrics(value: object, keys: frozenset[str], label: str) -> dict:
    raw = _exact_dict(value, keys, label)
    for key, metric in raw.items():
        _integer(metric, f"{label}.{key}")
    return raw


def _observations(value: object, keys: frozenset[str], label: str) -> dict:
    raw = _exact_dict(value, keys, label)
    for key, observation in raw.items():
        _boolean(observation, f"{label}.{key}")
    return raw


def _defects(value: object, label: str) -> list[str]:
    raw = _bounded_list(value, label, maximum=len(_DEFECTS))
    result = [
        _enum(item, _DEFECTS, f"{label}[{index}]")
        for index, item in enumerate(raw)
    ]
    if len(set(result)) != len(result):
        _fail(f"{label} contains duplicates")
    return result


def _result_identifiers(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_WINDOW_FRAMES,
) -> list[str]:
    raw = _bounded_list(value, label, minimum=minimum, maximum=maximum)
    return [
        _identifier(item, f"{label}[{index}]") for index, item in enumerate(raw)
    ]


def _result_digests(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_WINDOW_FRAMES,
) -> list[str]:
    raw = _bounded_list(value, label, minimum=minimum, maximum=maximum)
    return [_digest(item, f"{label}[{index}]") for index, item in enumerate(raw)]


def _validate_check_result(value: object, kind: str, index: int) -> dict:
    label = f"result.receipt.checks.{kind}[{index}]"
    if kind == "frame_state":
        raw = _exact_dict(value, _FRAME_RESULT_KEYS, label)
        _identifier(raw["check_id"], f"{label}.check_id")
        _identifier(raw["frame_id"], f"{label}.frame_id")
        _enum(
            raw["expected_state"],
            frozenset({"non_blank_content", "black", "uniform", "observe"}),
            f"{label}.expected_state",
        )
        _digest(raw["frame_sha256"], f"{label}.frame_sha256")
        _metrics(raw["metrics"], _FRAME_METRIC_KEYS, f"{label}.metrics")
        _observations(
            raw["observations"], frozenset({"black", "blank"}),
            f"{label}.observations",
        )
    elif kind == "temporal_window":
        raw = _exact_dict(value, _TEMPORAL_RESULT_KEYS, label)
        _identifier(raw["check_id"], f"{label}.check_id")
        ids = _result_identifiers(raw["frame_ids"], f"{label}.frame_ids", minimum=3)
        _enum(
            raw["expected_state"],
            frozenset({"motion_expected", "stable_expected", "observe"}),
            f"{label}.expected_state",
        )
        digests = _result_digests(
            raw["frame_sha256s"], f"{label}.frame_sha256s", minimum=3,
        )
        if len(ids) != len(digests):
            _fail(f"{label} frame ids and hashes differ in length")
        pair_values = _bounded_list(
            raw["pair_mae_ppm"], f"{label}.pair_mae_ppm",
            minimum=2, maximum=MAX_WINDOW_FRAMES - 1,
        )
        if len(pair_values) != len(ids) - 1:
            _fail(f"{label}.pair_mae_ppm length is invalid")
        for position, metric in enumerate(pair_values):
            _integer(metric, f"{label}.pair_mae_ppm[{position}]")
        _metrics(raw["metrics"], _TEMPORAL_METRIC_KEYS, f"{label}.metrics")
        _observations(
            raw["observations"],
            frozenset({"freeze_run", "isolated_flash", "stable"}),
            f"{label}.observations",
        )
        _result_identifiers(raw["flash_frame_ids"], f"{label}.flash_frame_ids")
    elif kind == "geometry":
        raw = _exact_dict(value, _GEOMETRY_RESULT_KEYS, label)
        _identifier(raw["check_id"], f"{label}.check_id")
        _enum(raw["kind"], frozenset({"caption", "graphic"}), f"{label}.kind")
        _identifier(raw["frame_id"], f"{label}.frame_id")
        _digest(raw["frame_sha256"], f"{label}.frame_sha256")
        _digest(
            raw["renderer_receipt_sha256"], f"{label}.renderer_receipt_sha256",
        )
        _rect(raw["rect"], f"{label}.rect")
        _rect(raw["safe_area"], f"{label}.safe_area", safe=True)
        _metrics(raw["metrics"], _GEOMETRY_METRIC_KEYS, f"{label}.metrics")
        _observations(
            raw["observations"], frozenset({"inside_canvas", "inside_safe_area"}),
            f"{label}.observations",
        )
    elif kind == "overlay":
        raw = _exact_dict(value, _OVERLAY_RESULT_KEYS, label)
        _identifier(raw["check_id"], f"{label}.check_id")
        _enum(raw["kind"], frozenset({"caption", "graphic"}), f"{label}.kind")
        _digest(
            raw["renderer_receipt_sha256"], f"{label}.renderer_receipt_sha256",
        )
        ids = _result_identifiers(raw["frame_ids"], f"{label}.frame_ids", minimum=3)
        digests = _result_digests(
            raw["frame_sha256s"], f"{label}.frame_sha256s", minimum=3,
        )
        if len(ids) != 3 or len(digests) != 3:
            _fail(f"{label} must bind exactly three frames")
        _rect(raw["rect"], f"{label}.rect")
        _metrics(raw["metrics"], _OVERLAY_METRIC_KEYS, f"{label}.metrics")
        _observations(
            raw["observations"],
            frozenset({
                "rect_inside_canvas", "pixel_present", "contrast_sufficient",
                "state_changed",
            }),
            f"{label}.observations",
        )
    else:
        raw = _exact_dict(value, _TRANSITION_RESULT_KEYS, label)
        _identifier(raw["check_id"], f"{label}.check_id")
        _enum(
            raw["transition_kind"],
            frozenset({"cross_dissolve", "dip_to_black"}),
            f"{label}.transition_kind",
        )
        _digest(
            raw["transition_receipt_sha256"],
            f"{label}.transition_receipt_sha256",
        )
        ids = _result_identifiers(raw["frame_ids"], f"{label}.frame_ids", minimum=3)
        digests = _result_digests(
            raw["frame_sha256s"], f"{label}.frame_sha256s", minimum=3,
        )
        if len(ids) != 3 or len(digests) != 3:
            _fail(f"{label} must bind exactly three frames")
        _metrics(raw["metrics"], _TRANSITION_METRIC_KEYS, f"{label}.metrics")
        _observations(
            raw["observations"],
            frozenset({
                "endpoint_distinct", "midpoint_in_range", "blend_continuous",
                "unexpected_black_midpoint", "expected_black_midpoint",
                "edge_content_present",
            }),
            f"{label}.observations",
        )
    passed = _boolean(raw["passed"], f"{label}.passed")
    defects = _defects(raw["defects"], f"{label}.defects")
    if passed != (not defects):
        _fail(f"{label}.passed does not match its defect list")
    return raw


def verify_visual_quality_deterministic_result(
    value: object,
    expected_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate a closed v1 result and return its path-free receipt."""
    raw = _exact_dict(value, _RESULT_KEYS, "result")
    if raw["schema_version"] != VISUAL_QUALITY_DETERMINISTIC_RESULT_SCHEMA_VERSION:
        _fail("result.schema_version is unsupported")
    supplied_hash = _digest(raw["receipt_sha256"], "result.receipt_sha256")
    if expected_receipt_sha256 is not None:
        expected = _digest(
            expected_receipt_sha256, "expected_receipt_sha256",
        )
        if supplied_hash != expected:
            _fail("result receipt hash does not match the expected digest")
    receipt = _exact_dict(raw["receipt"], _RECEIPT_KEYS, "result.receipt")
    measured_hash = _canonical_sha256(receipt)
    if supplied_hash != measured_hash:
        _fail("result receipt hash does not match its canonical content")
    if receipt["schema_version"] != VISUAL_QUALITY_DETERMINISTIC_RECEIPT_SCHEMA_VERSION:
        _fail("result.receipt.schema_version is unsupported")
    analyzer = _exact_dict(
        receipt["analyzer"], _ANALYZER_KEYS, "result.receipt.analyzer",
    )
    if analyzer != {
        "algorithm_version": VISUAL_QUALITY_DETERMINISTIC_ALGORITHM_VERSION,
        "thresholds": _THRESHOLDS,
    }:
        _fail("result.receipt.analyzer is not the exact v1 algorithm")
    binding = _exact_dict(
        receipt["binding"], _BINDING_KEYS, "result.receipt.binding",
    )
    for key in (
        "artifact_sha256", "decoder_receipt_sha256",
        "timeline_receipt_sha256", "request_sha256",
        "decoded_frames_sha256", "geometry_sha256", "timeline_sha256",
    ):
        _digest(binding[key], f"result.receipt.binding.{key}")
    receipt_hashes = _result_digests(
        binding["renderer_receipt_sha256s"],
        "result.receipt.binding.renderer_receipt_sha256s",
        maximum=MAX_CHECKS_PER_KIND * 3,
    )
    if receipt_hashes != sorted(set(receipt_hashes)):
        _fail("result.receipt renderer receipt hashes are not canonical")
    if receipt["scope"] != _SCOPE:
        _fail("result.receipt.scope is not the exact bounded v1 scope")
    checks = _exact_dict(
        receipt["checks"], _CHECKS_KEYS, "result.receipt.checks",
    )
    validated_results = []
    check_ids: set[str] = set()
    referenced_receipt_hashes: set[str] = set()
    for kind in (
        "frame_state", "temporal_window", "geometry", "overlay", "transition",
    ):
        items = _bounded_list(
            checks[kind], f"result.receipt.checks.{kind}",
            maximum=MAX_CHECKS_PER_KIND,
        )
        for index, item in enumerate(items):
            result = _validate_check_result(item, kind, index)
            if result["check_id"] in check_ids:
                _fail("result.receipt check ids are duplicated")
            check_ids.add(result["check_id"])
            if kind in {"geometry", "overlay"}:
                referenced_receipt_hashes.add(
                    result["renderer_receipt_sha256"]
                )
            elif kind == "transition":
                referenced_receipt_hashes.add(
                    result["transition_receipt_sha256"]
                )
            validated_results.append(result)
    if receipt_hashes != sorted(referenced_receipt_hashes):
        _fail("result.receipt binding does not match referenced receipts")
    summary = _exact_dict(
        receipt["summary"], _SUMMARY_KEYS, "result.receipt.summary",
    )
    check_count = _integer(
        summary["check_count"], "result.receipt.summary.check_count",
        maximum=MAX_CHECKS_PER_KIND * len(_CHECKS_KEYS),
    )
    passed_count = _integer(
        summary["passed_count"], "result.receipt.summary.passed_count",
        maximum=check_count,
    )
    failed_count = _integer(
        summary["failed_count"], "result.receipt.summary.failed_count",
        maximum=check_count,
    )
    all_passed = _boolean(
        summary["all_passed"], "result.receipt.summary.all_passed",
    )
    failed_ids = _result_identifiers(
        summary["failed_check_ids"],
        "result.receipt.summary.failed_check_ids",
        maximum=MAX_CHECKS_PER_KIND * len(_CHECKS_KEYS),
    )
    measured_failed = [
        result["check_id"] for result in validated_results if not result["passed"]
    ]
    if (
        check_count != len(validated_results)
        or passed_count != len(validated_results) - len(measured_failed)
        or failed_count != len(measured_failed)
        or all_passed != (not measured_failed)
        or failed_ids != measured_failed
    ):
        _fail("result.receipt.summary does not match its checks")
    return receipt


__all__ = [
    "VISUAL_QUALITY_DETERMINISTIC_ALGORITHM_VERSION",
    "VISUAL_QUALITY_DETERMINISTIC_RECEIPT_SCHEMA_VERSION",
    "VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION",
    "VISUAL_QUALITY_DETERMINISTIC_RESULT_SCHEMA_VERSION",
    "VisualQualityDeterministicError",
    "analyze_visual_quality_deterministic",
    "verify_visual_quality_deterministic_result",
]
