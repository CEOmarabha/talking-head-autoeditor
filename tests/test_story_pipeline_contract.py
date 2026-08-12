import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from autoeditor import pipeline
from autoeditor.story_qa import check_final_duration


_DAEMON_PATH = Path(__file__).resolve().parents[1] / "packaging" / (
    "helper_daemon_entry.py"
)
_DAEMON_SPEC = importlib.util.spec_from_file_location(
    "autoeditor_helper_daemon_entry", _DAEMON_PATH
)
assert _DAEMON_SPEC and _DAEMON_SPEC.loader
helper_daemon_entry = importlib.util.module_from_spec(_DAEMON_SPEC)
_DAEMON_SPEC.loader.exec_module(helper_daemon_entry)


SOURCE_DURATION = 174.9


def _words():
    return [
        {
            "w": f"word{index}",
            "s": round(index * 0.4, 3),
            "e": round((index + 1) * 0.4, 3),
        }
        for index in range(417)
    ]


def _anchor(words, start, end):
    return " ".join(word["w"] for word in words[start:end + 1])


def _plan():
    words = _words()
    return {
        "schema_version": "autoeditor-story-edit/v1",
        "timeline": "source_seconds",
        "target_duration": {"min_seconds": 35.0, "max_seconds": 45.0},
        "hook_anchor_id": "hook",
        "closer_anchor_id": "closer",
        "keep_ranges": [
            {
                "anchor_id": "hook",
                "anchor_text": _anchor(words, 50, 99),
                "source_start_word": 50,
                "source_end_word": 99,
                "source_start_seconds": 20.0,
                "source_end_seconds": 40.0,
            },
            {
                "anchor_id": "closer",
                "anchor_text": _anchor(words, 300, 349),
                "source_start_word": 300,
                "source_end_word": 349,
                "source_start_seconds": 120.0,
                "source_end_seconds": 140.0,
            },
        ],
    }


def _creative_constraints():
    return {
        "schema_version": "autoeditor-creative-constraints/v1",
        "opener": {
            "exact_text": "word50 word51 word52",
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
            "text": "WORD300 VS WORD301",
            "anchor_text": "word300 word301 word302 word303 word304",
        },
        "music_allowed": False,
    }


class ApprovedStoryPipelineContractTests(unittest.TestCase):
    def test_approved_plan_binds_source_transcript_and_exact_complement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source-bytes")
            plan_path = root / "approved-story-plan.json"
            plan_path.write_text(json.dumps(_plan()), encoding="utf-8")

            plan, cuts, receipt = pipeline._approved_story_cut(
                source, SOURCE_DURATION, _words(), plan_path
            )

        self.assertEqual(plan["hook_anchor_id"], "hook")
        self.assertEqual(plan["keep_ranges"][0]["source_start_word"], 50)
        self.assertEqual(cuts, [
            {"s": 0.0, "e": 20.0},
            {"s": 40.0, "e": 120.0},
            {"s": 140.0, "e": SOURCE_DURATION},
        ])
        self.assertEqual(receipt["kept_duration_seconds"], 40.0)
        self.assertEqual(receipt["source"], "deepseek")
        self.assertEqual(len(receipt["story_plan_sha256"]), 64)

    def test_hook_text_must_be_literal_source_transcript(self):
        plan = _plan()
        plan["keep_ranges"][0]["anchor_text"] = "invented hook"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source-bytes")
            plan_path = root / "approved-story-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "source-transcript validation"):
                pipeline._approved_story_cut(
                    source, SOURCE_DURATION, _words(), plan_path
                )

    def test_158_second_output_cannot_pass_35_to_45_second_approval(self):
        result = check_final_duration(
            158.0, _plan()["target_duration"]
        )
        self.assertFalse(result["ok"])
        self.assertIn("outside the required", result["errors"][0])

    def test_daemon_rejects_duration_promise_without_story_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source")
            request = {
                "inputs": [str(source)],
                "outputDir": str(root),
                "projectType": "short",
                "script": "",
                "cachedTranscript": "",
                "creativeBrief": "",
                "creativeBriefSha256": "",
                "proposal": {
                    "summary": "Premium hook-first edit lasting 35-45 seconds",
                    "operations": [
                        {"op": "set_edit_style", "style": "short"}
                    ],
                },
            }
            with self.assertRaisesRegex(
                    ValueError, "requires a transcript-grounded story plan"):
                helper_daemon_entry._local_render_request(request)

            request["proposal"] = {
                **request["proposal"], "storyPlan": copy.deepcopy(_plan()),
                "creativeConstraints": _creative_constraints(),
            }
            normalized = helper_daemon_entry._local_render_request(request)
            self.assertEqual(
                normalized["story_plan"]["target_duration"],
                {"min_seconds": 35.0, "max_seconds": 45.0},
            )
            self.assertEqual(
                normalized["creative_constraints"]["visual_policy"][
                    "graphics_exact"
                ], 1,
            )

    def test_daemon_rejects_story_plan_without_typed_creative_constraints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mov"
            source.write_bytes(b"source")
            request = {
                "inputs": [str(source)], "outputDir": str(root),
                "projectType": "short", "script": "",
                "cachedTranscript": "", "creativeBrief": "",
                "creativeBriefSha256": "",
                "proposal": {
                    "summary": "approved edit",
                    "operations": [{"op": "set_edit_style", "style": "short"}],
                    "storyPlan": _plan(),
                },
            }
            with self.assertRaisesRegex(
                    ValueError, "requires typed creative constraints"):
                helper_daemon_entry._local_render_request(request)


if __name__ == "__main__":
    unittest.main()
