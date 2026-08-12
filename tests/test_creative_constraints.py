from __future__ import annotations

import unittest

from autoeditor.creative_constraints import (
    CreativeConstraintsError,
    constraints_sha256,
    validate_creative_constraints,
)
from autoeditor import creative_contract
from autoeditor import pipeline


def valid_constraints() -> dict:
    return {
        "schema_version": "autoeditor-creative-constraints/v1",
        "opener": {
            "exact_text": "Is now a bad time?",
            "max_start_seconds": 3.0,
        },
        "visual_policy": {
            "graphics_exact": 1,
            "broll_exact": 0,
            "opening_punch_required": True,
            "opening_visual_required": False,
            "max_visual_gap_seconds": None,
        },
        "required_graphic": {
            "kind": "callout",
            "text": "BAD TIME VS MINUTE",
            "anchor_text": "is now a bad time versus do you have a minute",
        },
        "music_allowed": False,
    }


class CreativeConstraintsTests(unittest.TestCase):
    def test_normalizes_closed_constraint_and_hashes_canonically(self):
        raw = valid_constraints()
        raw["opener"]["exact_text"] = "  Is now a bad time?  "
        clean = validate_creative_constraints(raw)
        self.assertEqual(clean["opener"]["exact_text"], "Is now a bad time?")
        self.assertRegex(constraints_sha256(raw), r"^[0-9a-f]{64}$")
        self.assertEqual(constraints_sha256(raw), constraints_sha256(clean))

    def test_rejects_extra_key(self):
        raw = valid_constraints()
        raw["visual_policy"]["random_transition_pack"] = True
        with self.assertRaises(CreativeConstraintsError):
            validate_creative_constraints(raw)

    def test_exact_one_requires_exact_graphic(self):
        raw = valid_constraints()
        raw["required_graphic"] = None
        with self.assertRaises(CreativeConstraintsError):
            validate_creative_constraints(raw)

    def test_required_graphic_for_multiple_graphics_is_rejected(self):
        raw = valid_constraints()
        raw["visual_policy"]["graphics_exact"] = 2
        with self.assertRaises(CreativeConstraintsError):
            validate_creative_constraints(raw)

    def test_rejects_nonuppercase_or_long_graphic_copy(self):
        for text in ("Bad Time", "ONE TWO THREE FOUR FIVE"):
            raw = valid_constraints()
            raw["required_graphic"]["text"] = text
            with self.subTest(text=text), self.assertRaises(
                    CreativeConstraintsError):
                validate_creative_constraints(raw)

    def test_rejects_music_string_and_nonfinite_gap(self):
        raw = valid_constraints()
        raw["music_allowed"] = "false"
        with self.assertRaises(CreativeConstraintsError):
            validate_creative_constraints(raw)

    def test_explicit_sparse_policy_replaces_generic_density_only(self):
        spoken = (
            "Is now a bad time "
            + " ".join(f"context{i}" for i in range(58))
            + " is now a bad time versus do you have a minute "
            + " closing thought lands clearly today"
        ).split()
        words = [
            {"w": word, "s": index * 0.4, "e": index * 0.4 + 0.3}
            for index, word in enumerate(spoken)
        ]
        anchor_start = next(
            index for index in range(5, len(spoken))
            if spoken[index:index + 5] == ["is", "now", "a", "bad", "time"]
        )
        anchor = " ".join(spoken[anchor_start:anchor_start + 10])
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote": "Is now a bad time",
                "reason": "approved opening emphasis",
            }],
            "broll": [],
            "graphics": [{
                "s": words[anchor_start]["s"],
                "e": words[anchor_start]["s"] + 3.0,
                "kind": "callout", "text": "BAD TIME VS MINUTE",
                "anchor_quote": anchor,
                "reason": "approved comparison",
            }],
        }
        constraints = valid_constraints()
        constraints["required_graphic"]["anchor_text"] = anchor
        edl, report = creative_contract.validate_edl(
            raw, words, [], 40.0, "short", constraints=constraints
        )
        self.assertEqual(len(edl["graphics"]), 1)
        self.assertTrue(report["approved_constraints_applied"])
        self.assertTrue(report["coverage_ok"])
        with self.assertRaises(creative_contract.CreativeContractError):
            creative_contract.validate_edl(raw, words, [], 40.0, "short")

        missing = {**raw, "graphics": []}
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "approved exact count"):
            creative_contract.validate_edl(
                missing, words, [], 40.0, "short", constraints=constraints
            )

    def test_exact_opener_is_a_hard_gate(self):
        constraints = valid_constraints()
        spoken = "It's not a bad time and this opening continues clearly today".split()
        words = [
            {"w": word, "s": index * 0.3, "e": index * 0.3 + 0.2}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 1.5, "scale": 1.1,
                "anchor_quote": "It's not a bad time and",
                "reason": "opening",
            }],
            "broll": [], "graphics": [],
        }
        constraints["visual_policy"]["graphics_exact"] = 0
        constraints["required_graphic"] = None
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "exact approved opener"):
            creative_contract.validate_edl(
                raw, words, [], 4.0, "short", constraints=constraints
            )

    def test_low_confidence_now_not_homophone_uses_approved_opener_text(self):
        constraints = valid_constraints()
        words = [
            {"w": "It's", "s": 0.0, "e": 0.5, "p": 0.45},
            {"w": "not", "s": 0.5, "e": 0.8, "p": 0.47},
            {"w": "a", "s": 0.8, "e": 0.9, "p": 0.99},
            {"w": "bad", "s": 0.9, "e": 1.0, "p": 0.99},
            {"w": "time.", "s": 1.0, "e": 1.3, "p": 0.99},
        ]
        corrected = pipeline.apply_approved_opener(words, constraints)
        self.assertEqual(
            [word["w"] for word in corrected],
            ["Is", "now", "a", "bad", "time?"],
        )
        check = pipeline._approved_opener_check(corrected, constraints)
        self.assertTrue(check["ok"])
        self.assertEqual(check["matched_start_seconds"], 0.0)

    def test_high_confidence_different_opener_is_not_silently_rewritten(self):
        constraints = valid_constraints()
        words = [
            {"w": token, "s": index * 0.2, "e": index * 0.2 + 0.15,
             "p": 0.99}
            for index, token in enumerate(
                ["This", "is", "a", "bad", "time."]
            )
        ]
        unchanged = pipeline.apply_approved_opener(words, constraints)
        self.assertEqual(unchanged[0]["w"], "This")
        self.assertFalse(
            pipeline._approved_opener_check(unchanged, constraints)["ok"]
        )
        raw = valid_constraints()
        raw["visual_policy"]["max_visual_gap_seconds"] = float("nan")
        with self.assertRaises(CreativeConstraintsError):
            validate_creative_constraints(raw)


if __name__ == "__main__":
    unittest.main()
