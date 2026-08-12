import hashlib
import json
import unittest

from autoeditor.story_qa import validate_story_acceptance


def _canonical_hash(value):
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _phrase(text, start, step=0.3):
    return [
        {
            "w": token,
            "s": round(start + index * step, 3),
            "e": round(start + index * step + 0.22, 3),
        }
        for index, token in enumerate(text.split())
    ]


HOOK = "is now a bad time"
MIDDLE = "the word no feels like protection and freedom"
CLOSER = "which one are you more likely to give that minute to"


def _plan():
    return {
        "schema_version": "autoeditor-story-edit/v1",
        "timeline": "source_seconds",
        "target_duration": {"min_seconds": 35.0, "max_seconds": 45.0},
        "hook_anchor_id": "opening-hook",
        "closer_anchor_id": "closing-question",
        "keep_ranges": [
            {
                "anchor_id": "opening-hook",
                "anchor_text": HOOK,
                "source_start_word": 0,
                "source_end_word": 4,
                "source_start_seconds": 10.0,
                "source_end_seconds": 17.0,
            },
            {
                "anchor_id": "reasoning",
                "anchor_text": MIDDLE,
                "source_start_word": 5,
                "source_end_word": 12,
                "source_start_seconds": 30.0,
                "source_end_seconds": 53.0,
            },
            {
                "anchor_id": "closing-question",
                "anchor_text": CLOSER,
                "source_start_word": 13,
                "source_end_word": 23,
                "source_start_seconds": 150.0,
                "source_end_seconds": 160.0,
            },
        ],
    }


def _receipt(plan):
    return {
        "schema_version": "autoeditor-story-cut-receipt/v1",
        "source": "deepseek",
        "source_sha256": "a" * 64,
        "story_plan_sha256": _canonical_hash(plan),
        "transcript_sha256": "b" * 64,
        "timeline": "source_seconds",
        "kept_duration_seconds": 40.0,
        "derived_cuts_sha256": "c" * 64,
    }


def _final_words(duration, *, hook_start=0.2, closer_start=None):
    if closer_start is None:
        closer_start = duration - 4.0
    return (
        _phrase(HOOK, hook_start)
        + _phrase(MIDDLE, duration * 0.4)
        + _phrase(CLOSER, closer_start)
    )


class StoryAcceptanceTests(unittest.TestCase):
    def _validate(self, duration, words=None, receipt=None, plan=None):
        plan = plan or _plan()
        return validate_story_acceptance(
            final_duration_seconds=duration,
            final_words=words or _final_words(duration),
            story_plan=plan,
            story_cut_receipt=receipt or _receipt(plan),
            expected_receipt_source="deepseek",
            expected_source_sha256="a" * 64,
        )

    def test_valid_story_passes_all_independent_gates(self):
        report = self._validate(40.0)

        self.assertTrue(report["pass"])
        self.assertTrue(report["checks"]["duration"]["ok"])
        self.assertTrue(report["checks"]["required_anchors"]["ok"])
        self.assertTrue(report["checks"]["story_cut_receipt"]["ok"])
        self.assertEqual(
            [item["anchor_id"] for item in
             report["checks"]["required_anchors"]["matches"]],
            ["opening-hook", "reasoning", "closing-question"],
        )

    def test_real_157_second_regression_hard_fails_35_to_45_second_target(self):
        report = self._validate(157.7)

        duration = report["checks"]["duration"]
        self.assertFalse(report["pass"])
        self.assertFalse(duration["ok"])
        self.assertEqual(duration["measured_seconds"], 157.7)
        self.assertEqual(duration["minimum_seconds"], 35.0)
        self.assertEqual(duration["maximum_seconds"], 45.0)
        self.assertTrue(report["checks"]["required_anchors"]["ok"])
        self.assertTrue(report["checks"]["story_cut_receipt"]["ok"])

    def test_hook_must_begin_in_the_first_three_seconds(self):
        report = self._validate(
            40.0, words=_final_words(40.0, hook_start=3.01)
        )

        anchors = report["checks"]["required_anchors"]
        self.assertFalse(anchors["ok"])
        self.assertTrue(any("opening 3.0 seconds" in error
                            for error in anchors["errors"]))

    def test_closer_must_finish_near_the_end(self):
        report = self._validate(
            40.0, words=_final_words(40.0, closer_start=28.0)
        )

        anchors = report["checks"]["required_anchors"]
        self.assertFalse(anchors["ok"])
        self.assertTrue(any("final 5.0 seconds" in error
                            for error in anchors["errors"]))

    def test_every_required_anchor_must_appear_in_plan_order(self):
        words = (
            _phrase(HOOK, 0.2)
            + _phrase(CLOSER, 32.2)
            + _phrase(MIDDLE, 36.0)
        )
        report = self._validate(40.0, words=words)

        anchors = report["checks"]["required_anchors"]
        self.assertFalse(anchors["ok"])
        self.assertFalse(any("final 5.0 seconds" in error
                             for error in anchors["errors"]))
        self.assertTrue(any("plan order" in error
                            for error in anchors["errors"]))

    def test_receipt_exactly_binds_source_source_hash_and_plan_hash(self):
        plan = _plan()
        mutations = {
            "wrong source": {"source": "heuristic"},
            "wrong source hash": {"source_sha256": "d" * 64},
            "wrong plan hash": {"story_plan_sha256": "e" * 64},
            "extra key": {"unexpected": True},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                receipt = {**_receipt(plan), **mutation}
                report = self._validate(40.0, receipt=receipt, plan=plan)
                self.assertFalse(report["pass"])
                self.assertFalse(
                    report["checks"]["story_cut_receipt"]["ok"]
                )


if __name__ == "__main__":
    unittest.main()
