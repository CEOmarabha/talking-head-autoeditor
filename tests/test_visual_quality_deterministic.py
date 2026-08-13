from __future__ import annotations

import copy
import hashlib
import json
import unittest

from autoeditor.visual_quality_deterministic import (
    VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION,
    VISUAL_QUALITY_DETERMINISTIC_RESULT_SCHEMA_VERSION,
    VisualQualityDeterministicError,
    analyze_visual_quality_deterministic,
    verify_visual_quality_deterministic_result,
)


WIDTH = 32
HEIGHT = 24


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _solid(red: int, green: int, blue: int) -> bytes:
    return bytes((red, green, blue)) * (WIDTH * HEIGHT)


def _pattern(seed: int = 0) -> bytes:
    value = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            value.extend((
                (x * 9 + seed * 17) % 256,
                (y * 13 + seed * 29) % 256,
                ((x + y) * 7 + seed * 11) % 256,
            ))
    return bytes(value)


def _average(left: bytes, right: bytes) -> bytes:
    return bytes((a + b + 1) // 2 for a, b in zip(left, right))


def _paint(source: bytes, rect: dict[str, int], rgb: tuple[int, int, int]) -> bytes:
    value = bytearray(source)
    for y in range(rect["y"], rect["y"] + rect["height"]):
        for x in range(rect["x"], rect["x"] + rect["width"]):
            offset = (y * WIDTH + x) * 3
            value[offset:offset + 3] = bytes(rgb)
    return bytes(value)


def _request(
    payloads: list[bytes],
    checks: dict[str, list[dict]],
) -> tuple[dict, dict[str, bytes]]:
    frames = []
    decoded = {}
    for index, payload in enumerate(payloads):
        frame_id = f"frame-{index}"
        frames.append({
            "frame_id": frame_id,
            "frame_index": index,
            "timestamp_us": index * 100_000,
            "rgb24_sha256": _sha256(payload),
        })
        decoded[frame_id] = payload
    return {
        "schema_version": VISUAL_QUALITY_DETERMINISTIC_REQUEST_SCHEMA_VERSION,
        "artifact_sha256": "a" * 64,
        "decoder_receipt_sha256": "8" * 64,
        "timeline_receipt_sha256": "9" * 64,
        "geometry": {
            "width": WIDTH,
            "height": HEIGHT,
            "pixel_format": "rgb24",
        },
        "timeline": {
            "frame_rate": {"numerator": 10, "denominator": 1},
            "frames": frames,
        },
        "checks": checks,
    }, decoded


def _empty_checks() -> dict[str, list[dict]]:
    return {
        "frame_state": [],
        "temporal_window": [],
        "geometry": [],
        "overlay": [],
        "transition": [],
    }


class VisualQualityDeterministicTests(unittest.TestCase):
    def test_clean_mechanical_evidence_passes_and_is_hash_bound(self):
        pattern = _pattern()
        black = _solid(0, 0, 0)
        motion = [_solid(20, 30, 40), _solid(70, 80, 90),
                  _solid(130, 140, 150)]
        overlay_rect = {"x": 8, "y": 8, "width": 16, "height": 8}
        inactive = _solid(20, 20, 20)
        active = _paint(inactive, overlay_rect, (255, 255, 255))
        transition_before = _pattern(1)
        transition_after = _pattern(7)
        transition_middle = _average(transition_before, transition_after)
        payloads = [
            pattern, black, *motion, inactive, active, inactive,
            transition_before, transition_middle, transition_after,
        ]
        checks = _empty_checks()
        checks["frame_state"] = [
            {
                "check_id": "content-frame",
                "frame_id": "frame-0",
                "expected_state": "non_blank_content",
            },
            {
                "check_id": "intentional-black",
                "frame_id": "frame-1",
                "expected_state": "black",
            },
        ]
        checks["temporal_window"] = [{
            "check_id": "motion-window",
            "frame_ids": ["frame-2", "frame-3", "frame-4"],
            "expected_state": "motion_expected",
        }]
        checks["geometry"] = [{
            "check_id": "caption-safe-area",
            "kind": "caption",
            "frame_id": "frame-6",
            "renderer_receipt_sha256": "b" * 64,
            "rect": overlay_rect,
            "safe_area": {"x": 2, "y": 2, "width": 28, "height": 20},
        }]
        checks["overlay"] = [{
            "check_id": "caption-raster-state",
            "kind": "caption",
            "renderer_receipt_sha256": "b" * 64,
            "inactive_before_frame_id": "frame-5",
            "active_frame_id": "frame-6",
            "inactive_after_frame_id": "frame-7",
            "rect": overlay_rect,
        }]
        checks["transition"] = [{
            "check_id": "cross-dissolve-continuity",
            "transition_kind": "cross_dissolve",
            "transition_receipt_sha256": "c" * 64,
            "before_frame_id": "frame-8",
            "middle_frame_id": "frame-9",
            "after_frame_id": "frame-10",
        }]
        request, decoded = _request(payloads, checks)

        result = analyze_visual_quality_deterministic(request, decoded)

        self.assertEqual(
            result["schema_version"],
            VISUAL_QUALITY_DETERMINISTIC_RESULT_SCHEMA_VERSION,
        )
        self.assertTrue(result["receipt"]["summary"]["all_passed"])
        self.assertEqual(result["receipt"]["summary"], {
            "check_count": 6,
            "passed_count": 6,
            "failed_count": 0,
            "all_passed": True,
            "failed_check_ids": [],
        })
        frames = result["receipt"]["checks"]["frame_state"]
        self.assertFalse(frames[0]["observations"]["black"])
        self.assertFalse(frames[0]["observations"]["blank"])
        self.assertTrue(frames[1]["observations"]["black"])
        overlay = result["receipt"]["checks"]["overlay"][0]
        self.assertTrue(overlay["observations"]["pixel_present"])
        self.assertTrue(overlay["observations"]["contrast_sufficient"])
        self.assertTrue(overlay["observations"]["state_changed"])
        transition = result["receipt"]["checks"]["transition"][0]
        self.assertGreater(
            transition["metrics"]["estimated_after_weight_ppm"], 450_000,
        )
        self.assertLess(
            transition["metrics"]["estimated_after_weight_ppm"], 550_000,
        )
        self.assertLess(
            transition["metrics"]["blend_residual_mae_ppm"], 5_000,
        )

        canonical_request = json.dumps(
            request, ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("ascii")
        self.assertEqual(
            result["receipt"]["binding"]["request_sha256"],
            hashlib.sha256(canonical_request).hexdigest(),
        )
        self.assertEqual(
            result["receipt"]["binding"]["decoder_receipt_sha256"],
            "8" * 64,
        )
        self.assertEqual(
            result["receipt"]["binding"]["timeline_receipt_sha256"],
            "9" * 64,
        )
        self.assertEqual(
            verify_visual_quality_deterministic_result(result),
            result["receipt"],
        )

    def test_black_blank_freeze_and_flash_are_distinct_integer_observations(self):
        black = _solid(0, 0, 0)
        uniform = _solid(90, 90, 90)
        frozen = _pattern(3)
        payloads = [black, uniform] + [frozen] * 6 + [
            _solid(100, 100, 100),
            _solid(255, 255, 255),
            _solid(100, 100, 100),
        ]
        checks = _empty_checks()
        checks["frame_state"] = [
            {
                "check_id": "black-content-defect",
                "frame_id": "frame-0",
                "expected_state": "non_blank_content",
            },
            {
                "check_id": "uniform-content-defect",
                "frame_id": "frame-1",
                "expected_state": "non_blank_content",
            },
        ]
        checks["temporal_window"] = [
            {
                "check_id": "freeze-defect",
                "frame_ids": [f"frame-{index}" for index in range(2, 8)],
                "expected_state": "motion_expected",
            },
            {
                "check_id": "flash-defect",
                "frame_ids": ["frame-8", "frame-9", "frame-10"],
                "expected_state": "motion_expected",
            },
        ]
        request, decoded = _request(payloads, checks)

        result = analyze_visual_quality_deterministic(request, decoded)
        receipt = result["receipt"]

        self.assertFalse(receipt["summary"]["all_passed"])
        frame_results = receipt["checks"]["frame_state"]
        self.assertEqual(frame_results[0]["defects"], ["black_frame"])
        self.assertEqual(frame_results[1]["defects"], ["blank_frame"])
        temporal = receipt["checks"]["temporal_window"]
        self.assertTrue(temporal[0]["observations"]["freeze_run"])
        self.assertEqual(
            temporal[0]["metrics"]["longest_near_duplicate_duration_us"],
            500_000,
        )
        self.assertIn("freeze_run", temporal[0]["defects"])
        self.assertTrue(temporal[1]["observations"]["isolated_flash"])
        self.assertEqual(temporal[1]["metrics"]["flash_count"], 1)
        self.assertEqual(temporal[1]["flash_frame_ids"], ["frame-9"])
        self.assertIn("isolated_flash", temporal[1]["defects"])

        def assert_no_float(value):
            if isinstance(value, dict):
                for item in value.values():
                    assert_no_float(item)
            elif isinstance(value, list):
                for item in value:
                    assert_no_float(item)
            else:
                self.assertNotIsInstance(value, float)

        assert_no_float(receipt)

    def test_geometry_overlay_and_cross_dissolve_fail_closed_on_bad_pixels(self):
        baseline = _solid(20, 20, 20)
        low_contrast = _paint(
            baseline, {"x": 8, "y": 8, "width": 16, "height": 8},
            (25, 25, 25),
        )
        before = _pattern(1)
        after = _pattern(8)
        bad_middle = _solid(0, 0, 0)
        payloads = [baseline, low_contrast, baseline, before, bad_middle, after]
        checks = _empty_checks()
        checks["geometry"] = [{
            "check_id": "clipped-caption",
            "kind": "caption",
            "frame_id": "frame-1",
            "renderer_receipt_sha256": "b" * 64,
            "rect": {"x": 25, "y": 18, "width": 16, "height": 8},
            "safe_area": {"x": 2, "y": 2, "width": 28, "height": 20},
        }]
        checks["overlay"] = [{
            "check_id": "invisible-caption",
            "kind": "caption",
            "renderer_receipt_sha256": "b" * 64,
            "inactive_before_frame_id": "frame-0",
            "active_frame_id": "frame-1",
            "inactive_after_frame_id": "frame-2",
            "rect": {"x": 8, "y": 8, "width": 16, "height": 8},
        }]
        checks["transition"] = [{
            "check_id": "black-flash-transition",
            "transition_kind": "cross_dissolve",
            "transition_receipt_sha256": "c" * 64,
            "before_frame_id": "frame-3",
            "middle_frame_id": "frame-4",
            "after_frame_id": "frame-5",
        }]
        request, decoded = _request(payloads, checks)

        receipt = analyze_visual_quality_deterministic(request, decoded)["receipt"]

        geometry = receipt["checks"]["geometry"][0]
        self.assertFalse(geometry["passed"])
        self.assertGreater(
            geometry["metrics"]["outside_canvas_area_pixels"], 0,
        )
        self.assertIn("outside_canvas", geometry["defects"])
        self.assertIn("outside_safe_area", geometry["defects"])
        overlay = receipt["checks"]["overlay"][0]
        self.assertFalse(overlay["passed"])
        self.assertFalse(overlay["observations"]["pixel_present"])
        self.assertFalse(overlay["observations"]["contrast_sufficient"])
        transition = receipt["checks"]["transition"][0]
        self.assertFalse(transition["passed"])
        self.assertIn("unexpected_black_midpoint", transition["defects"])
        self.assertIn("transition_blend_discontinuity", transition["defects"])

    def test_dip_to_black_and_stable_window_are_supported_without_semantics(self):
        stable = _pattern(4)
        before = _pattern(2)
        middle = _solid(0, 0, 0)
        after = _pattern(9)
        payloads = [stable, stable, stable, before, middle, after]
        checks = _empty_checks()
        checks["temporal_window"] = [{
            "check_id": "intentional-still",
            "frame_ids": ["frame-0", "frame-1", "frame-2"],
            "expected_state": "stable_expected",
        }]
        checks["transition"] = [{
            "check_id": "intentional-dip",
            "transition_kind": "dip_to_black",
            "transition_receipt_sha256": "d" * 64,
            "before_frame_id": "frame-3",
            "middle_frame_id": "frame-4",
            "after_frame_id": "frame-5",
        }]
        request, decoded = _request(payloads, checks)

        receipt = analyze_visual_quality_deterministic(request, decoded)["receipt"]

        self.assertTrue(receipt["summary"]["all_passed"])
        self.assertTrue(
            receipt["checks"]["temporal_window"][0]["observations"][
                "freeze_run"
            ] is False
        )
        self.assertTrue(
            receipt["checks"]["transition"][0]["observations"][
                "expected_black_midpoint"
            ]
        )

    def test_request_schema_payload_and_hashes_fail_closed(self):
        request, decoded = _request([_pattern()], _empty_checks())

        invalid = copy.deepcopy(request)
        invalid["unexpected"] = True
        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "invalid keys",
        ):
            analyze_visual_quality_deterministic(invalid, decoded)

        invalid = copy.deepcopy(request)
        invalid["timeline"]["frames"][0]["rgb24_sha256"] = "f" * 64
        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "hash does not match",
        ):
            analyze_visual_quality_deterministic(invalid, decoded)

        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "decoded frame ids",
        ):
            analyze_visual_quality_deterministic(request, {
                **decoded, "frame-extra": _pattern(2),
            })

        invalid = copy.deepcopy(request)
        invalid["timeline"]["frames"][0]["frame_index"] = True
        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "must be an integer",
        ):
            analyze_visual_quality_deterministic(invalid, decoded)

        invalid = copy.deepcopy(request)
        invalid["checks"]["frame_state"] = [{
            "check_id": "../path",
            "frame_id": "frame-0",
            "expected_state": "non_blank_content",
        }]
        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "identifier",
        ):
            analyze_visual_quality_deterministic(invalid, decoded)

    def test_temporal_and_transition_checks_require_exact_timeline_order(self):
        payloads = [_pattern(1), _pattern(2), _pattern(3), _pattern(4)]
        checks = _empty_checks()
        checks["temporal_window"] = [{
            "check_id": "skipped-frame",
            "frame_ids": ["frame-0", "frame-2", "frame-3"],
            "expected_state": "motion_expected",
        }]
        request, decoded = _request(payloads, checks)
        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "consecutive decoded frames",
        ):
            analyze_visual_quality_deterministic(request, decoded)

        checks = _empty_checks()
        checks["transition"] = [{
            "check_id": "reversed-transition",
            "transition_kind": "cross_dissolve",
            "transition_receipt_sha256": "c" * 64,
            "before_frame_id": "frame-3",
            "middle_frame_id": "frame-2",
            "after_frame_id": "frame-1",
        }]
        request, decoded = _request(payloads, checks)
        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "timeline order",
        ):
            analyze_visual_quality_deterministic(request, decoded)

    def test_result_receipt_detects_tampering_and_contains_no_paths(self):
        checks = _empty_checks()
        checks["frame_state"] = [{
            "check_id": "content",
            "frame_id": "frame-0",
            "expected_state": "non_blank_content",
        }]
        request, decoded = _request([_pattern()], checks)
        result = analyze_visual_quality_deterministic(request, decoded)

        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("path", serialized.lower())
        self.assertNotIn("file", serialized.lower())

        tampered = copy.deepcopy(result)
        tampered["receipt"]["summary"]["all_passed"] = False
        with self.assertRaisesRegex(
            VisualQualityDeterministicError, "receipt hash does not match",
        ):
            verify_visual_quality_deterministic_result(tampered)

        inconsistent = copy.deepcopy(result)
        inconsistent["receipt"]["binding"][
            "renderer_receipt_sha256s"
        ] = ["e" * 64]
        inconsistent["receipt_sha256"] = hashlib.sha256(json.dumps(
            inconsistent["receipt"], ensure_ascii=True, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("ascii")).hexdigest()
        with self.assertRaisesRegex(
            VisualQualityDeterministicError,
            "binding does not match referenced receipts",
        ):
            verify_visual_quality_deterministic_result(inconsistent)

    def test_bounded_schema_supports_more_than_sixty_four_check_receipts(self):
        checks = _empty_checks()
        checks["frame_state"] = [
            {
                "check_id": f"content-{index}",
                "frame_id": "frame-0",
                "expected_state": "non_blank_content",
            }
            for index in range(70)
        ]
        request, decoded = _request([_pattern()], checks)

        result = analyze_visual_quality_deterministic(request, decoded)

        self.assertEqual(result["receipt"]["summary"]["check_count"], 70)
        self.assertEqual(result["receipt"]["summary"]["passed_count"], 70)
        self.assertEqual(
            verify_visual_quality_deterministic_result(result),
            result["receipt"],
        )


if __name__ == "__main__":
    unittest.main()
