from __future__ import annotations

import unittest

from autoeditor import creative_contract


def _words(text: str) -> list[dict]:
    result = []
    for index, token in enumerate(text.split()):
        result.append({
            "w": token,
            "s": round(index * 0.3, 3),
            "e": round(index * 0.3 + 0.22, 3),
        })
    return result


def _normalize_graphic(text: str, anchor: str, transcript: str,
                       *, kind: str = "callout") -> tuple[dict | None, list[str]]:
    words = _words(transcript)
    errors: list[str] = []
    event = {
        "s": 0.0,
        "e": 1.5,
        "kind": kind,
        "text": text,
        "anchor_quote": anchor,
        "reason": "faithful on-screen summary",
    }
    normalized = creative_contract._normalize_event(
        "graphics", event, 0, words, set(),
        float(words[-1]["e"]), errors,
    )
    return normalized, errors


class CreativePolarityContractTests(unittest.TestCase):
    def test_negative_question_cannot_become_negative_assertion(self):
        transcript = (
            "Is now a bad time? This exact opening asks a safe question today"
        )
        normalized, errors = _normalize_graphic(
            "NOT A BAD TIME",
            "Is now a bad time? This exact opening",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertFalse(normalized["display_copy_grounded"])
        self.assertTrue(any("interrogative polarity" in error
                            for error in errors), errors)

    def test_affirmative_question_cannot_gain_negation(self):
        transcript = (
            "Is this a bad time? This exact opening asks a safe question today"
        )
        normalized, errors = _normalize_graphic(
            "NOT A BAD TIME",
            "Is this a bad time? This exact opening",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertFalse(normalized["display_copy_grounded"])
        self.assertTrue(any("negation polarity" in error
                            for error in errors), errors)

    def test_negative_assertion_cannot_drop_negation(self):
        transcript = (
            "This is not a bad time because the schedule remains open today"
        )
        normalized, errors = _normalize_graphic(
            "THIS IS A BAD TIME",
            "This is not a bad time because the schedule",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertFalse(normalized["display_copy_grounded"])
        self.assertTrue(any("negation polarity" in error
                            for error in errors), errors)

    def test_assertion_cannot_be_reframed_as_question(self):
        transcript = (
            "This is a bad time because the schedule is completely full today"
        )
        normalized, errors = _normalize_graphic(
            "IS THIS A BAD TIME?",
            "This is a bad time because the schedule",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertFalse(normalized["display_copy_grounded"])
        self.assertTrue(any("interrogative polarity" in error
                            for error in errors), errors)

    def test_question_label_that_preserves_mood_and_polarity_is_allowed(self):
        transcript = (
            "Is now a bad time? This exact opening asks a safe question today"
        )
        normalized, errors = _normalize_graphic(
            "IS NOW A BAD TIME?",
            "Is now a bad time? This exact opening",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertTrue(normalized["display_copy_grounded"], errors)
        self.assertFalse(any("polarity" in error for error in errors), errors)

    def test_quoted_word_no_is_not_mistaken_for_logical_negation(self):
        transcript = (
            "The word no feels like protection and safety for everyone today"
        )
        normalized, errors = _normalize_graphic(
            "THE WORD NO",
            "The word no feels like protection and safety",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertTrue(normalized["display_copy_grounded"], errors)
        self.assertFalse(any("polarity" in error for error in errors), errors)

    def test_comparison_label_no_versus_yes_remains_neutral(self):
        transcript = (
            "Getting the word no is easier than getting the word yes today"
        )
        normalized, errors = _normalize_graphic(
            "NO VERSUS YES",
            "Getting the word no is easier than getting",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertTrue(normalized["display_copy_grounded"], errors)
        self.assertFalse(any("polarity" in error for error in errors), errors)

    def test_contrast_clause_does_not_leak_unrelated_negation(self):
        transcript = (
            "Do not pressure them, but the safe option feels like freedom today"
        )
        normalized, errors = _normalize_graphic(
            "SAFE OPTION",
            "Do not pressure them but the safe option",
            transcript,
        )

        self.assertIsNotNone(normalized)
        self.assertTrue(normalized["display_copy_grounded"], errors)
        self.assertFalse(any("polarity" in error for error in errors), errors)

    def test_protocol_identity_changes_with_semantic_guard(self):
        self.assertEqual(
            creative_contract.PROTOCOL_VERSION,
            "pse-creative-edl/2026-08-12.1",
        )
        self.assertEqual(len(creative_contract.contract_sha256()), 64)


if __name__ == "__main__":
    unittest.main()
