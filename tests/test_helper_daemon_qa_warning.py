import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "helper_daemon_entry", ROOT / "packaging" / "helper_daemon_entry.py"
)
assert SPEC and SPEC.loader
helper_daemon_entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper_daemon_entry)


class HelperDaemonQaWarningTests(unittest.TestCase):
    def test_qa_failure_issue_names_the_rejected_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = Path(raw) / "QA_REPORT.json"
            report.write_text(json.dumps({
                "pass": False,
                "checks": {
                    "caption_safe_area": {
                        "ok": False,
                        "reason": "bottom caption crossed the safe area",
                    },
                    "decode": {"ok": True},
                },
            }), encoding="utf-8")

            issue = helper_daemon_entry._qa_failure_issue(report)

            self.assertIn("caption_safe_area", issue)
            self.assertIn("bottom caption crossed the safe area", issue)

    def test_qa_failure_issue_is_bounded_when_report_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            issue = helper_daemon_entry._qa_failure_issue(
                Path(raw) / "missing.json")
        self.assertEqual(
            issue,
            "Built-in quality assurance rejected this draft; review QA_REPORT.json.",
        )


if __name__ == "__main__":
    unittest.main()
