from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "helper-release.yml"


class HelperMacNativeWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_unsigned_jobs_build_source_and_verify_loose_and_mounted_apps(self):
        self.assertIn("verify_macos_ffmpeg_source.py fetch-cache", self.workflow)
        self.assertIn("packaging/source_bundle.py build", self.workflow)
        self.assertIn(
            'NPM_TARBALL="compositor-darwin-${{ matrix.arch }}-'
            '$REMOTION_VERSION.tgz"',
            self.workflow,
        )
        self.assertIn(
            '/-/$NPM_TARBALL"',
            self.workflow,
        )
        self.assertNotIn('/-/$TARBALL"', self.workflow)
        self.assertEqual(
            self.workflow.count("verify_macos_ffmpeg_source.py verify-bundle"), 2
        )
        self.assertEqual(self.workflow.count("macos_ffmpeg_receipt.py generate"), 2)
        self.assertEqual(self.workflow.count("macos_ffmpeg_receipt.py verify"), 4)
        self.assertEqual(self.workflow.count("macos_remotion_receipt.py generate"), 2)
        self.assertEqual(self.workflow.count("macos_remotion_receipt.py verify"), 4)
        packed = self.workflow.index(
            "Create and verify exact packed Mac FFmpeg and Remotion receipts"
        )
        released = self.workflow.index(
            "Release duplicate staging bytes before artifact acceptance", packed
        )
        mounted = self.workflow.index(
            '--app-root "$MOUNTED_APP" --receipt "$FFMPEG_RECEIPT"', released
        )
        self.assertLess(packed, released)
        self.assertGreater(mounted, released)

    def test_signed_jobs_consume_accepted_inputs_and_emit_final_receipts(self):
        self.assertIn("name: accepted-mac-native-${{ matrix.arch }}", self.workflow)
        self.assertIn("Verify accepted Mac source and receipt input set", self.workflow)
        self.assertIn(
            "Create and verify exact signed Mac FFmpeg and Remotion receipts",
            self.workflow,
        )
        self.assertIn("macos-ffmpeg-signed-${{ matrix.arch }}.json", self.workflow)
        self.assertIn("macos-remotion-signed-${{ matrix.arch }}.json", self.workflow)
        self.assertIn("$RECEIPT_DIR/accepted-native", self.workflow)

    def test_incomplete_allowlist_is_not_invoked(self):
        self.assertNotIn("generate_native_media_allowlist.py", self.workflow)
        for required in (
            "macos-ffmpeg-sources.lock.json",
            "macos-ffmpeg-corresponding-source-${{ matrix.arch }}.tar",
            "macos-ffmpeg-${{ matrix.arch }}.json",
            "macos-remotion-${{ matrix.arch }}.json",
        ):
            self.assertIn(required, self.workflow)


if __name__ == "__main__":
    unittest.main()
