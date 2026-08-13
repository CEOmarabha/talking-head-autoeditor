from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "pending_delivery_daemon", ROOT / "packaging" / "helper_daemon_entry.py"
)
daemon = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daemon)


class PendingDeliveryContractTests(unittest.TestCase):
    def test_pending_artifact_and_desired_final_are_distinct_and_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pending = root / "PSE_SHORT_9x16.UNVERIFIED.mp4"
            final = root / "PSE_SHORT_9x16.mp4"
            pending.write_bytes(b"engine-verified")
            actual, desired = daemon._validated_output_targets({
                "outputs": {"9x16": str(pending)},
                "final_outputs": {"9x16": str(final)},
            }, root)

        self.assertEqual(actual["9x16"], str(pending))
        self.assertEqual(desired["9x16"], str(final))

    def test_existing_or_escaped_final_target_fails_closed(self):
        with tempfile.TemporaryDirectory() as td, \
                tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            pending = root / "pending.mp4"
            pending.write_bytes(b"engine-verified")
            existing = root / "final.mp4"
            existing.write_bytes(b"prior-good-version")
            for final in (existing, Path(outside) / "escaped.mp4", pending):
                with self.subTest(final=final), self.assertRaises(RuntimeError):
                    daemon._validated_output_targets({
                        "outputs": {"9x16": str(pending)},
                        "final_outputs": {"9x16": str(final)},
                    }, root)

    def test_missing_final_target_map_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pending = root / "pending.mp4"
            pending.write_bytes(b"engine-verified")
            with self.assertRaisesRegex(RuntimeError, "omitted"):
                daemon._validated_output_targets({
                    "outputs": {"9x16": str(pending)},
                    "final_outputs": {},
                }, root)


if __name__ == "__main__":
    unittest.main()
