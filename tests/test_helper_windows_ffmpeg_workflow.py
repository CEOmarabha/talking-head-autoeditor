from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER_WORKFLOW = ROOT / ".github" / "workflows" / "helper-release.yml"


class HelperWindowsFFmpegWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = HELPER_WORKFLOW.read_text(encoding="utf-8")

    def test_helper_uses_same_run_accepted_source_build(self) -> None:
        self.assertIn(
            "windows_ffmpeg:\n    uses: ./.github/workflows/windows-ffmpeg.yml",
            self.workflow,
        )
        self.assertIn("needs: windows_ffmpeg", self.workflow)
        self.assertIn(
            "artifact-ids: ${{ needs.windows_ffmpeg.outputs.artifact_id }}",
            self.workflow,
        )
        self.assertIn(
            "WINDOWS_FFMPEG_ARTIFACT_NAME: "
            "${{ needs.windows_ffmpeg.outputs.artifact_name }}",
            self.workflow,
        )
        self.assertIn(
            "WINDOWS_FFMPEG_ARTIFACT_DIGEST: "
            "${{ needs.windows_ffmpeg.outputs.artifact_digest }}",
            self.workflow,
        )
        self.assertIn("-notmatch '^[0-9a-f]{64}$'", self.workflow)
        self.assertNotIn(
            "-notmatch '^sha256:[0-9a-f]{64}$'", self.workflow
        )
        self.assertIn(
            '$expectedName = "windows-ffmpeg-accepted-$env:GITHUB_SHA"',
            self.workflow,
        )
        self.assertNotIn("BtbN", self.workflow)
        self.assertNotIn("FFMPEG-GPL-3.0.txt", self.workflow)
        self.assertNotIn("ffmpeg.zip", self.workflow)

    def test_helper_reverifies_and_stages_exact_provenance_set(self) -> None:
        stage_at = self.workflow.index(
            "Stage accepted source-built Windows FFmpeg"
        )
        verify_at = self.workflow.index("verify-receipt", stage_at)
        promotable_at = self.workflow.index("assert-promotable", verify_at)
        copy_at = self.workflow.index("Copy-Item", promotable_at)
        self.assertLess(verify_at, promotable_at)
        self.assertLess(promotable_at, copy_at)
        self.assertIn('--linkage-dir "$source\\linkage"', self.workflow)
        for filename in (
            "ffmpeg.exe",
            "ffprobe.exe",
            "FFmpeg-COPYING.GPLv2",
            "LLVM-LICENSE.TXT",
            "LLVM-compiler-rt-LICENSE.TXT",
            "MinGW-w64-runtime-NOTICES.txt",
            "x264-COPYING",
            "zlib-LICENSE",
            "windows-ffmpeg-corresponding-source.tar",
            "windows-ffmpeg-corresponding-source.manifest.json",
            "windows-ffmpeg-build-receipt.json",
            "ffmpeg-linkage-receipt.json",
            "ffprobe-linkage-receipt.json",
            "windows-ffmpeg-sources.lock.json",
            "windows-ffmpeg-capabilities.json",
            "WINDOWS_FFMPEG_ACCEPTED_ARTIFACT.txt",
        ):
            self.assertIn(filename, self.workflow)
        self.assertNotIn(
            'Copy-Item "$source\\linkage\\*"', self.workflow
        )


if __name__ == "__main__":
    unittest.main()
