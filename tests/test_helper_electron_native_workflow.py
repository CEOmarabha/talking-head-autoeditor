from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER_WORKFLOW = ROOT / ".github" / "workflows" / "helper-release.yml"


class HelperElectronNativeWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = HELPER_WORKFLOW.read_text(encoding="utf-8")

    def test_all_helper_builds_create_exact_packed_receipts(self) -> None:
        self.assertEqual(
            self.workflow.count("electron_native_receipt.py create"), 3
        )
        self.assertIn("electron-v43.3.0-win32-x64.zip", self.workflow)
        self.assertIn(
            "electron-v43.3.0-darwin-${{ matrix.arch }}.zip",
            self.workflow,
        )
        for required_input in (
            "--source-lock packaging/electron-chromium-provenance.lock.json",
            "--builder-config desktop/electron-builder.helper.yml",
            "--package-json desktop/package.json",
            "--icon desktop/build/icon.ico",
        ):
            self.assertEqual(self.workflow.count(required_input), 7)

        unsigned_create = self.workflow.index(
            "Create exact packed Electron native producer receipt"
        )
        unsigned_release = self.workflow.index(
            "Release duplicate staging bytes before artifact acceptance",
            unsigned_create,
        )
        windows_create = self.workflow.index(
            "Create exact signed packed Electron native producer receipt"
        )
        windows_release = self.workflow.index(
            "Release duplicate signed staging bytes before acceptance",
            windows_create,
        )
        mac_job = self.workflow.index("sign-macos:")
        mac_create = self.workflow.index(
            "Create exact signed packed Electron native producer receipt",
            mac_job,
        )
        mac_release = self.workflow.index(
            "Release duplicate signed staging bytes before acceptance",
            mac_create,
        )
        self.assertLess(unsigned_create, unsigned_release)
        self.assertLess(windows_create, windows_release)
        self.assertLess(mac_create, mac_release)

    def test_installed_and_mounted_bytes_are_reverified(self) -> None:
        self.assertEqual(
            self.workflow.count("electron_native_receipt.py verify"), 4
        )
        self.assertEqual(
            self.workflow.count("--expected-receipt-sha256"), 4
        )
        self.assertIn(
            "Installed Helper Electron native receipt verification failed",
            self.workflow,
        )
        self.assertIn(
            "Signed installed Helper Electron native receipt verification failed",
            self.workflow,
        )

        unsigned_mac = self.workflow.index(
            "Smoke-test macOS app, DMG, signing and notarization"
        )
        unsigned_strict = self.workflow.index(
            'codesign --verify --deep --strict --verbose=2 "$MOUNTED_APP"',
            unsigned_mac,
        )
        unsigned_verify = self.workflow.index(
            "electron_native_receipt.py verify", unsigned_strict
        )
        signed_mac = self.workflow.index("Verify the final mounted Mac artifact")
        signed_strict = self.workflow.index(
            'codesign --verify --deep --strict --verbose=4 "$APP"',
            signed_mac,
        )
        signed_verify = self.workflow.index(
            "electron_native_receipt.py verify", signed_strict
        )
        self.assertLess(unsigned_strict, unsigned_verify)
        self.assertLess(signed_strict, signed_verify)

    def test_receipts_follow_unsigned_and_signed_artifacts(self) -> None:
        self.assertIn(
            "${{ runner.temp }}/electron-native-${{ matrix.target_os }}-"
            "${{ matrix.arch }}.json",
            self.workflow,
        )
        for receipt_name in (
            "electron-native-windows-x64.json",
            "electron-native-mac-${{ matrix.arch }}.json",
        ):
            self.assertGreaterEqual(self.workflow.count(receipt_name), 3)
        self.assertIn("release-receipt/helper-windows-x64", self.workflow)
        self.assertIn(
            "release-receipt/helper-mac-${{ matrix.arch }}", self.workflow
        )


if __name__ == "__main__":
    unittest.main()
