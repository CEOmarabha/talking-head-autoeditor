from __future__ import annotations

import hashlib
import json
import unittest

from autoeditor.story_edit import (
    STORY_PLAN_JSON_SCHEMA,
    StoryEditContractError,
    derive_complementary_cuts,
    kept_duration,
    story_plan_sha256,
    validate_story_plan,
)


def _words():
    return [
        {"w": "Hook", "s": 0.0, "e": 0.4, "p": 0.99},
        {"w": "promise.", "s": 0.45, "e": 0.9, "p": 0.98},
        {"w": "Filler", "s": 1.5, "e": 1.9, "p": 0.90},
        {"w": "detail", "s": 1.95, "e": 2.4, "p": 0.91},
        {"w": "Core", "s": 3.0, "e": 3.4, "p": 0.97},
        {"w": "proof", "s": 3.45, "e": 4.0, "p": 0.96},
        {"w": "Strong", "s": 5.0, "e": 5.4, "p": 0.99},
        {"w": "finish.", "s": 5.45, "e": 6.0, "p": 0.99},
    ]


def _plan():
    return {
        "schema_version": "autoeditor-story-edit/v1",
        "timeline": "source_seconds",
        "target_duration": {"min_seconds": 2.85, "max_seconds": 3.0},
        "hook_anchor_id": "hook",
        "closer_anchor_id": "closer",
        "keep_ranges": [
            {
                "anchor_id": "hook",
                "anchor_text": "Hook promise.",
                "source_start_word": 0,
                "source_end_word": 1,
                "source_start_seconds": 0.0,
                "source_end_seconds": 0.9,
            },
            {
                "anchor_id": "body",
                "anchor_text": "Core proof",
                "source_start_word": 4,
                "source_end_word": 5,
                "source_start_seconds": 3.0,
                "source_end_seconds": 4.0,
            },
            {
                "anchor_id": "closer",
                "anchor_text": "Strong finish.",
                "source_start_word": 6,
                "source_end_word": 7,
                "source_start_seconds": 5.0,
                "source_end_seconds": 6.0,
            },
        ],
    }


class StoryEditContractTests(unittest.TestCase):
    def assert_rejected(self, plan, *, words=None, source_duration=7.0):
        with self.assertRaises(StoryEditContractError):
            validate_story_plan(
                plan,
                _words() if words is None else words,
                source_duration,
            )

    def test_valid_plan_is_deep_copied_and_derives_exact_complement(self):
        plan = _plan()
        validated = validate_story_plan(plan, _words(), 7.0)

        self.assertEqual(validated, plan)
        self.assertIsNot(validated, plan)
        self.assertIsNot(validated["keep_ranges"], plan["keep_ranges"])
        self.assertAlmostEqual(kept_duration(validated), 2.9)
        self.assertEqual(
            derive_complementary_cuts(validated, 7.0),
            [
                {"s": 0.9, "e": 3.0},
                {"s": 4.0, "e": 5.0},
                {"s": 6.0, "e": 7.0},
            ],
        )

    def test_plan_and_nested_objects_require_exact_keys(self):
        plan = _plan()
        plan["comment"] = "not part of the contract"
        self.assert_rejected(plan)

        plan = _plan()
        del plan["target_duration"]["max_seconds"]
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][0]["confidence"] = 1.0
        self.assert_rejected(plan)

    def test_wrong_version_or_timeline_fails_closed(self):
        plan = _plan()
        plan["schema_version"] = "autoeditor-story-edit/v2"
        self.assert_rejected(plan)

        plan = _plan()
        plan["timeline"] = "edited_seconds"
        self.assert_rejected(plan)

    def test_hallucinated_or_partially_grounded_anchor_text_is_rejected(self):
        plan = _plan()
        plan["keep_ranges"][1]["anchor_text"] = "Core amazing proof"
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][1]["anchor_text"] = "Core"
        self.assert_rejected(plan)

    def test_anchor_matching_normalizes_unicode_and_whitespace_only(self):
        words = _words()
        words[0]["w"] = "Cafe\u0301"
        words[1]["w"] = "  promise.  "
        plan = _plan()
        plan["keep_ranges"][0]["anchor_text"] = "Caf\u00e9 promise."
        validated = validate_story_plan(plan, words, 7.0)
        self.assertEqual(validated["keep_ranges"][0]["anchor_text"], "Caf\u00e9 promise.")

        plan["keep_ranges"][0]["anchor_text"] = "caf\u00e9 promise."
        self.assert_rejected(plan, words=words)

    def test_word_indices_are_inclusive_in_bounds_and_not_booleans(self):
        plan = _plan()
        plan["keep_ranges"][0]["source_start_word"] = True
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][2]["source_end_word"] = len(_words())
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][1]["source_start_word"] = 5
        plan["keep_ranges"][1]["source_end_word"] = 4
        self.assert_rejected(plan)

    def test_range_times_must_match_transcript_boundaries_within_one_ms(self):
        plan = _plan()
        plan["keep_ranges"][1]["source_start_seconds"] = 3.001
        validate_story_plan(plan, _words(), 7.0)

        plan["keep_ranges"][1]["source_start_seconds"] = 3.0011
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][1]["source_end_seconds"] = 4.01
        self.assert_rejected(plan)

    def test_ranges_must_be_ordered_unique_and_non_overlapping(self):
        plan = _plan()
        plan["keep_ranges"][1]["source_start_word"] = 1
        plan["keep_ranges"][1]["anchor_text"] = "promise. Filler detail Core proof"
        plan["keep_ranges"][1]["source_start_seconds"] = 0.45
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][1], plan["keep_ranges"][2] = (
            plan["keep_ranges"][2],
            plan["keep_ranges"][1],
        )
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][1]["anchor_id"] = "hook"
        self.assert_rejected(plan)

    def test_hook_and_closer_must_identify_first_and_last_ranges(self):
        plan = _plan()
        plan["hook_anchor_id"] = "body"
        self.assert_rejected(plan)

        plan = _plan()
        plan["closer_anchor_id"] = "body"
        self.assert_rejected(plan)

    def test_kept_duration_must_be_inside_target_with_tolerance(self):
        plan = _plan()
        plan["target_duration"] = {"min_seconds": 2.95, "max_seconds": 3.0}
        validate_story_plan(plan, _words(), 7.0, duration_tolerance=0.05)

        with self.assertRaises(StoryEditContractError):
            validate_story_plan(
                plan, _words(), 7.0, duration_tolerance=0.049
            )

        plan = _plan()
        plan["target_duration"] = {"min_seconds": 2.0, "max_seconds": 2.8}
        self.assert_rejected(plan)

    def test_empty_or_invalid_transcript_cannot_ground_a_plan(self):
        self.assert_rejected(_plan(), words=[])

        words = _words()
        words[2]["s"] = float("nan")
        self.assert_rejected(_plan(), words=words)

        words = _words()
        words[7]["e"] = 7.1
        self.assert_rejected(_plan(), words=words)

    def test_non_finite_or_boolean_numeric_values_are_rejected(self):
        plan = _plan()
        plan["target_duration"]["min_seconds"] = True
        self.assert_rejected(plan)

        plan = _plan()
        plan["keep_ranges"][0]["source_start_seconds"] = float("nan")
        self.assert_rejected(plan)

        with self.assertRaises(StoryEditContractError):
            validate_story_plan(_plan(), _words(), True)
        with self.assertRaises(StoryEditContractError):
            validate_story_plan(
                _plan(), _words(), 7.0, duration_tolerance=-0.1
            )

    def test_plan_requires_distinct_hook_and_closer_ranges(self):
        plan = _plan()
        plan["keep_ranges"] = [plan["keep_ranges"][1]]
        plan["hook_anchor_id"] = "body"
        plan["closer_anchor_id"] = "body"
        plan["target_duration"] = {"min_seconds": 1.0, "max_seconds": 1.0}
        self.assert_rejected(plan)

    def test_hash_is_canonical_order_independent_and_rejects_nan(self):
        plan = _plan()
        reversed_plan = dict(reversed(list(plan.items())))
        expected = hashlib.sha256(
            json.dumps(
                plan,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(story_plan_sha256(plan), expected)
        self.assertEqual(story_plan_sha256(reversed_plan), expected)

        plan["target_duration"]["min_seconds"] = float("nan")
        with self.assertRaises(StoryEditContractError):
            story_plan_sha256(plan)

    def test_json_schema_exposes_the_same_closed_contract(self):
        self.assertEqual(
            STORY_PLAN_JSON_SCHEMA["properties"]["schema_version"]["const"],
            "autoeditor-story-edit/v1",
        )
        self.assertEqual(
            STORY_PLAN_JSON_SCHEMA["properties"]["timeline"]["const"],
            "source_seconds",
        )
        self.assertFalse(STORY_PLAN_JSON_SCHEMA["additionalProperties"])
        self.assertFalse(
            STORY_PLAN_JSON_SCHEMA["properties"]["target_duration"][
                "additionalProperties"
            ]
        )
        self.assertFalse(
            STORY_PLAN_JSON_SCHEMA["properties"]["keep_ranges"]["items"][
                "additionalProperties"
            ]
        )


if __name__ == "__main__":
    unittest.main()
