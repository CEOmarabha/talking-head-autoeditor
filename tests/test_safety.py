from __future__ import annotations

import ast
import argparse
import contextlib
import hashlib
import http.client
import inspect
import io
import json
import math
import os
import re
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest import mock

from autoeditor import (
    calibrate, config, creative_contract, pipeline, premium, profiles,
    providers,
)


class SafetyContracts(unittest.TestCase):
    def test_nsis_web_downloader_staging_is_hash_locked(self):
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(
            str(root / "packaging" / "prepare_nsis_web.py")
        )
        stage = namespace["stage"]
        plugin = b"large-file-capable-INetC"
        license_text = b"zlib license"
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr(namespace["INETC_DLL_MEMBER"], plugin)
        archive_bytes = archive_buffer.getvalue()
        stage.__globals__["INETC_ARCHIVE_SHA256"] = hashlib.sha256(
            archive_bytes
        ).hexdigest()
        stage.__globals__["INETC_DLL_SHA256"] = hashlib.sha256(
            plugin
        ).hexdigest()
        stage.__globals__["INETC_LICENSE_SHA256"] = hashlib.sha256(
            license_text
        ).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            root_dir = Path(td)
            build = root_dir / "build"
            licenses = root_dir / "licenses"
            stage(archive_bytes, license_text, build, licenses)
            self.assertEqual(
                (build / "x86-unicode" / "AutoEditorINetC.dll").read_bytes(),
                plugin,
            )
            self.assertEqual(
                (licenses / "AutoEditor-INetC-Zlib-LICENSE.md").read_bytes(),
                license_text,
            )
            self.assertIn(
                "plugin_sha256=",
                (licenses / "NSIS_WEB_DOWNLOADER.txt").read_text(
                    encoding="utf-8"
                ),
            )
            with self.assertRaisesRegex(SystemExit, "archive digest drifted"):
                stage(archive_bytes + b"tampered", license_text, build, licenses)

    def test_nsis_web_integrity_patch_writes_stable_lf_bytes(self):
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(
            str(root / "packaging" / "patch_nsis_web_integrity.py")
        )
        patch_globals = namespace["main"].__globals__
        with tempfile.TemporaryDirectory() as td:
            temporary = Path(td)
            node_modules = temporary / "node_modules"
            app_builder = node_modules / "app-builder-lib"
            include = app_builder / "templates" / "nsis" / "include"
            include.mkdir(parents=True)
            (app_builder / "package.json").write_text(
                json.dumps({"version": namespace["ELECTRON_BUILDER_VERSION"]}),
                encoding="utf-8",
            )
            source_include = (
                root / "desktop" / "node_modules" / "app-builder-lib" /
                "templates" / "nsis" / "include"
            )
            for name in ("installer.nsh", "webPackage.nsh"):
                shutil.copy2(source_include / name, include / name)
            plugin = temporary / "AutoEditorINetC.dll"
            plugin.write_bytes(b"audited-plugin")
            patch_globals["INETC_SHA256"] = hashlib.sha256(
                plugin.read_bytes()
            ).hexdigest()
            original_hashes = {
                name: hashlib.sha256((include / name).read_bytes()).hexdigest()
                for name in ("installer.nsh", "webPackage.nsh")
            }
            self.assertEqual(original_hashes, namespace["ORIGINAL_HASHES"])
            installer_text = (include / "installer.nsh").read_text(
                encoding="utf-8"
            )
            web_text = (include / "webPackage.nsh").read_text(encoding="utf-8")
            self.assertIn(
                'MessageBox MB_OK|MB_ICONSTOP "The AutoEditor runtime package '
                'failed its security check. Nothing was installed." /SD IDOK',
                namespace["INSTALLER_PATCHED"],
            )
            self.assertNotIn(
                "MessageBox MB_OK|MB_ICONSTOP /SD IDOK",
                namespace["INSTALLER_PATCHED"],
            )
            expected = {
                "installer.nsh": installer_text.replace(
                    namespace["INSTALLER_ORIGINAL"],
                    namespace["INSTALLER_PATCHED"],
                ).encode("utf-8"),
                "webPackage.nsh": web_text.replace(
                    "inetc::get", "AutoEditorINetC::get"
                ).encode("utf-8"),
            }
            patched_hashes = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in expected.items()
            }
            self.assertEqual(patched_hashes, namespace["PATCHED_HASHES"])
            with mock.patch.object(sys, "argv", [
                "patch_nsis_web_integrity.py",
                "--node-modules", str(node_modules),
                "--plugin", str(plugin),
            ]):
                namespace["main"]()
            for name, data in expected.items():
                self.assertEqual((include / name).read_bytes(), data)
                self.assertNotIn(b"\r\n", data)

    @staticmethod
    def _synthetic_pe64(payload: bytes = b"runtime-payload") -> bytearray:
        dos = bytearray(0x80)
        dos[:2] = b"MZ"
        struct.pack_into("<I", dos, 0x3C, 0x80)
        coff = struct.pack(
            "<HHIIIHH", 0x8664, 0, 0, 0, 0, 240, 0x0022
        )
        optional = bytearray(240)
        struct.pack_into("<H", optional, 0, 0x20B)
        struct.pack_into("<I", optional, 108, 16)
        return bytearray(dos + b"PE\0\0" + coff + optional + payload)

    def test_windows_manifest_receipt_ignores_only_authenticode_envelope(self):
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(
            str(root / "packaging" / "generate_helper_manifest.py")
        )
        receipt = namespace["directory_receipt"]
        error = namespace["ManifestReceiptError"]
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            executable = folder / "engine.exe"
            unsigned = self._synthetic_pe64()
            executable.write_bytes(unsigned)
            raw_unsigned = receipt(folder)
            normalized_unsigned = receipt(
                folder, normalize_windows_executables=True
            )

            signed = bytearray(unsigned)
            signed.extend(b"\0" * ((8 - len(signed) % 8) % 8))
            certificate_offset = len(signed)
            certificate = struct.pack(
                "<IHH8s", 16, 0x0200, 0x0002, b"signature"
            )
            optional_offset = 0x80 + 24
            struct.pack_into("<I", signed, optional_offset + 64, 0x12345678)
            struct.pack_into(
                "<II", signed, optional_offset + 144,
                certificate_offset, len(certificate),
            )
            executable.write_bytes(signed + certificate)
            raw_signed = receipt(folder)
            normalized_signed = receipt(
                folder, normalize_windows_executables=True
            )
            self.assertNotEqual(raw_unsigned, raw_signed)
            self.assertEqual(normalized_unsigned, normalized_signed)

            changed = bytearray(signed + certificate)
            changed[-len(certificate) - 1] ^= 0x01
            executable.write_bytes(changed)
            self.assertNotEqual(
                normalized_unsigned,
                receipt(folder, normalize_windows_executables=True),
            )

            executable.write_bytes(b"MZ-not-a-real-executable")
            with self.assertRaisesRegex(error, "PE executable|PE header offset"):
                receipt(folder, normalize_windows_executables=True)

    def test_macos_ffmpeg_formula_path_mapping(self):
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(
            str(root / "packaging" / "verify_macos_ffmpeg_formulae.py")
        )
        identify = namespace["formula_version_from_cellar"]
        self.assertEqual(
            identify(
                Path("/opt/homebrew/Cellar/x264/r3222/lib/libx264.165.dylib"),
                Path("/opt/homebrew/Cellar"),
            ),
            ("x264", "r3222"),
        )
        self.assertEqual(
            identify(
                Path("/opt/homebrew/Cellar/ffmpeg/8.1.2_1"),
                Path("/opt/homebrew/Cellar"),
            ),
            ("ffmpeg", "8.1.2_1"),
        )
        error = namespace["FormulaInventoryError"]
        with self.assertRaisesRegex(error, "outside Homebrew Cellar"):
            identify(
                Path("/usr/local/lib/libunexpected.dylib"),
                Path("/opt/homebrew/Cellar"),
            )

    def test_macos_ffmpeg_formula_inventory_comparison_fails_closed(self):
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(
            str(root / "packaging" / "verify_macos_ffmpeg_formulae.py")
        )
        compare = namespace["compare_inventories"]
        error = namespace["FormulaInventoryError"]
        record = namespace["BottleRecord"]
        expected = {
            "ffmpeg": record(
                "ffmpeg", "8.1.2_1", "arm64_sequoia", 0, "a" * 64
            ),
            "x264": record(
                "x264", "r3222", "arm64_sequoia", 0, "b" * 64
            ),
        }
        compare({"ffmpeg": "8.1.2_1", "x264": "r3222"}, expected)
        with self.assertRaisesRegex(error, "missing formulae: x264"):
            compare({"ffmpeg": "8.1.2_1"}, expected)
        with self.assertRaisesRegex(error, "unexpected formulae: libextra"):
            compare({**expected, "libextra": "1.0"}, expected)
        with self.assertRaisesRegex(
            error, "x264 expected r3222, found r9999"
        ):
            compare({"ffmpeg": "8.1.2_1", "x264": "r9999"}, expected)
        verify_archive = namespace["verify_bottle_archive"]
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / (
                "cache--ffmpeg--8.1.2_1.arm64_sequoia.bottle.tar.gz"
            )
            archive.write_bytes(b"exact bottle")
            exact = record(
                "ffmpeg", "8.1.2_1", "arm64_sequoia", 0,
                hashlib.sha256(b"exact bottle").hexdigest(),
            )
            verify_archive(archive, exact)
            with self.assertRaisesRegex(error, "bottle SHA-256 drifted"):
                verify_archive(archive, record(
                    "ffmpeg", "8.1.2_1", "arm64_sequoia", 0, "0" * 64
                ))
            with self.assertRaisesRegex(error, "unexpected bottle filename"):
                verify_archive(archive, record(
                    "ffmpeg", "8.1.2_1", "arm64_sequoia", 1,
                    exact.bottle_sha256,
                ))

    def test_helper_manifest_ignores_packaging_placeholders_and_verifies(self):
        root = Path(__file__).resolve().parent.parent
        generator = root / "packaging" / "generate_helper_manifest.py"
        verifier = root / "packaging" / "verify_helper_manifest.py"
        components = (
            "helper", "engine", "bin", "lib", "models", "profiles",
            "fonts", "certs", "node", "creative-runtime", "browser",
            "creative", "licenses",
        )
        with tempfile.TemporaryDirectory() as td:
            stage = Path(td)
            for component in components:
                folder = stage / component
                folder.mkdir()
                (folder / "payload.bin").write_bytes(component.encode())
                (folder / ".gitkeep").write_text("")
                (folder / ".DS_Store").write_bytes(b"finder")
                (folder / "._payload.bin").write_bytes(b"appledouble")
            manifest = stage / "runtime-manifest.json"
            subprocess.run([
                sys.executable, str(generator), "--stage", str(stage),
                "--output", str(manifest), "--target-os", "mac",
                "--target-arch", "arm64", "--version", "0.1.0",
            ], check=True)
            expected_manifest = stage / "expected-runtime-manifest.json"
            shutil.copy2(manifest, expected_manifest)
            payload = json.loads(manifest.read_text())
            self.assertTrue(all(
                receipt["files"] == 1
                for receipt in payload["components"].values()
            ))
            self.assertIn(
                "in_process_low_speech_cutter",
                payload["required_local_capabilities"],
            )
            self.assertIn(
                "typed_deepseek_revision_contract",
                payload["required_local_capabilities"],
            )
            self.assertIn(
                "python_utf8_mode",
                payload["required_local_capabilities"],
            )
            self.assertIn(
                "local_vision_model",
                payload["required_local_capabilities"],
            )
            self.assertEqual(
                payload["receipt_algorithm"],
                "macho-codesign-content-v1",
            )
            self.assertEqual(
                payload["account_capabilities"]["remotion"],
                "required: free-license eligibility or paid key",
            )
            subprocess.run([
                sys.executable, str(verifier), "--resources", str(stage),
                "--expected-manifest", str(expected_manifest),
                "--target-os", "mac", "--target-arch", "arm64",
                "--version", "0.1.0",
            ], check=True, capture_output=True, text=True)
            valid_manifest = manifest.read_bytes()
            missing = json.loads(valid_manifest)
            missing["required_local_capabilities"].remove(
                "in_process_low_speech_cutter"
            )
            missing_bytes = (
                json.dumps(missing, indent=2, sort_keys=True) + "\n"
            ).encode()
            manifest.write_bytes(missing_bytes)
            expected_manifest.write_bytes(missing_bytes)
            capability_failure = subprocess.run([
                sys.executable, str(verifier), "--resources", str(stage),
                "--expected-manifest", str(expected_manifest),
                "--target-os", "mac", "--target-arch", "arm64",
                "--version", "0.1.0",
            ], capture_output=True, text=True)
            self.assertNotEqual(capability_failure.returncode, 0)
            self.assertIn(
                "in_process_low_speech_cutter", capability_failure.stderr
            )
            manifest.write_bytes(valid_manifest)
            expected_manifest.write_bytes(valid_manifest)
            (stage / "engine" / "payload.bin").write_bytes(b"changed")
            failed = subprocess.run([
                sys.executable, str(verifier), "--resources", str(stage),
                "--expected-manifest", str(expected_manifest),
                "--target-os", "mac", "--target-arch", "arm64",
                "--version", "0.1.0",
            ], capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("engine", failed.stderr)

    def test_windows_manifest_allows_only_an_absent_empty_component(self):
        root = Path(__file__).resolve().parent.parent
        generator = root / "packaging" / "generate_helper_manifest.py"
        verifier = root / "packaging" / "verify_helper_manifest.py"
        components = (
            "helper", "engine", "bin", "lib", "models", "profiles",
            "fonts", "certs", "node", "creative-runtime", "browser",
            "creative", "licenses",
        )
        with tempfile.TemporaryDirectory() as td:
            temporary = Path(td)
            resources = temporary / "resources"
            resources.mkdir()
            for component in components:
                folder = resources / component
                folder.mkdir()
                if component != "lib":
                    (folder / "payload.bin").write_bytes(component.encode())
            manifest = resources / "runtime-manifest.json"
            subprocess.run([
                sys.executable, str(generator), "--stage", str(resources),
                "--output", str(manifest), "--target-os", "windows",
                "--target-arch", "x64", "--version", "0.1.0",
            ], check=True)
            expected = temporary / "expected-runtime-manifest.json"
            shutil.copy2(manifest, expected)
            (resources / "lib").rmdir()
            command = [
                sys.executable, str(verifier), "--resources", str(resources),
                "--expected-manifest", str(expected),
                "--target-os", "windows", "--target-arch", "x64",
                "--version", "0.1.0",
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            (resources / "lib").write_bytes(b"not-a-directory")
            rejected = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("component path is not a directory", rejected.stderr)

    def test_helper_release_metadata_requires_all_three_exact_candidates(self):
        root = Path(__file__).resolve().parent.parent
        script = root / "packaging" / "helper_release_metadata.py"
        targets = (
            ("windows", "x64"), ("mac", "arm64"), ("mac", "x64"),
        )
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for target_os, arch in targets:
                folder = work / f"{target_os}-{arch}"
                folder.mkdir()
                installer = folder / ("helper.exe" if target_os == "windows"
                                      else "helper.dmg")
                installer.write_bytes(f"{target_os}-{arch}".encode())
                runtime = folder / f"runtime-manifest-{target_os}-{arch}.json"
                runtime.write_text(json.dumps({
                    "target": {"os": target_os, "arch": arch},
                    "version": "1.2.3",
                }))
                receipt = folder / f"candidate-{target_os}-{arch}.json"
                candidate_command = [
                    sys.executable, str(script), "candidate",
                    "--file", str(installer),
                    "--runtime-manifest", str(runtime),
                    "--target-os", target_os, "--arch", arch,
                    "--tag", "helper-v1.2.3", "--commit", "a" * 40,
                    "--run-id", "123", "--run-attempt", "2",
                    "--signing-status", "verified",
                    "--notarization-status",
                    "not-applicable" if target_os == "windows" else "verified",
                    "--output", str(receipt),
                ]
                runtime_package = None
                if target_os == "windows":
                    runtime_package = folder / "helper-runtime.nsis.7z"
                    runtime_package.write_bytes(b"windows-runtime-package")
                    candidate_command.extend((
                        "--runtime-package", str(runtime_package),
                    ))
                subprocess.run(candidate_command, check=True)
                data = json.loads(receipt.read_text())
                head = folder / "head.json"
                head.write_text(json.dumps({
                    "ContentLength": data["bytes"],
                    "Metadata": {"sha256": data["sha256"]},
                }))
                subprocess.run([
                    sys.executable, str(script), "verify-head",
                    "--receipt", str(receipt), "--head", str(head),
                    "--tag", "helper-v1.2.3",
                ], check=True)
                if runtime_package is not None:
                    package_head = folder / "runtime-package-head.json"
                    package_head.write_text(json.dumps({
                        "ContentLength": data["runtime_package"]["bytes"],
                        "Metadata": {
                            "sha256": data["runtime_package"]["sha256"],
                        },
                    }))
                    subprocess.run([
                        sys.executable, str(script), "verify-head",
                        "--receipt", str(receipt),
                        "--head", str(package_head),
                        "--tag", "helper-v1.2.3",
                        "--object", "runtime-package",
                    ], check=True)
            output = work / "release"
            subprocess.run([
                sys.executable, str(script), "assemble",
                "--receipts", str(work), "--tag", "helper-v1.2.3",
                "--commit", "a" * 40, "--run-id", "123",
                "--run-attempt", "2",
                "--output", str(output),
            ], check=True)
            pointer = json.loads((output / "current.json").read_text())
            self.assertEqual(pointer["schema"],
                             "autoeditor-helper-release/v2")
            self.assertEqual(set(pointer["platforms"]), {
                "windows-x64", "mac-arm64", "mac-x64",
            })
            self.assertEqual(pointer["source"], {
                "commit": "a" * 40, "run_id": "123", "run_attempt": "2",
            })
            self.assertEqual(
                pointer["verification"]["windows-x64"]["notarization"],
                "not-applicable",
            )
            self.assertEqual(
                pointer["verification"]["mac-arm64"]["notarization"],
                "verified",
            )
            self.assertEqual(
                len((output / "SHA256SUMS.txt").read_text().splitlines()), 7
            )
            windows_package = pointer["platforms"]["windows-x64"][
                "runtime_package"
            ]
            self.assertEqual(
                windows_package["filename"],
                "AutoEditor-Helper-Windows.nsis.7z",
            )
            self.assertEqual(
                windows_package["content_type"],
                "application/x-7z-compressed",
            )
            self.assertNotIn(
                "runtime_package", pointer["platforms"]["mac-arm64"]
            )
            checksums = (output / "SHA256SUMS.txt").read_text()
            self.assertIn("AutoEditor-Helper-Windows.nsis.7z", checksums)
            self.assertIn("runtime-manifest-windows-x64.json", checksums)
            github_assets = json.loads(
                (output / "github-assets.json").read_text()
            )
            self.assertEqual(
                github_assets["schema"],
                "autoeditor-helper-github-assets/v1",
            )
            self.assertEqual(len(github_assets["assets"]), 6)
            emitted_assets = subprocess.run([
                sys.executable, str(script), "github-assets",
                "--plan", str(output / "github-assets.json"),
            ], check=True, capture_output=True).stdout.rstrip(b"\0").split(b"\0")
            self.assertEqual(len(emitted_assets), 6)
            for release in pointer["platforms"].values():
                self.assertIn(
                    f"dist/helper/objects/{release['sha256']}/",
                    release["key"],
                )
            windows_folder = work / "windows-x64"
            missing_package = subprocess.run([
                sys.executable, str(script), "candidate",
                "--file", str(windows_folder / "helper.exe"),
                "--runtime-manifest",
                str(windows_folder / "runtime-manifest-windows-x64.json"),
                "--target-os", "windows", "--arch", "x64",
                "--tag", "helper-v1.2.3", "--commit", "a" * 40,
                "--run-id", "123", "--run-attempt", "2",
                "--signing-status", "verified",
                "--notarization-status", "not-applicable",
                "--output", str(work / "missing-package.json"),
            ], capture_output=True, text=True)
            self.assertNotEqual(missing_package.returncode, 0)
            self.assertIn("requires one .nsis.7z", missing_package.stderr)

            empty_runtime = work / "empty.nsis.7z"
            empty_runtime.write_bytes(b"")
            empty_package = subprocess.run([
                sys.executable, str(script), "candidate",
                "--file", str(windows_folder / "helper.exe"),
                "--runtime-manifest",
                str(windows_folder / "runtime-manifest-windows-x64.json"),
                "--runtime-package", str(empty_runtime),
                "--target-os", "windows", "--arch", "x64",
                "--tag", "helper-v1.2.3", "--commit", "a" * 40,
                "--run-id", "123", "--run-attempt", "2",
                "--signing-status", "verified",
                "--notarization-status", "not-applicable",
                "--output", str(work / "empty-package.json"),
            ], capture_output=True, text=True)
            self.assertNotEqual(empty_package.returncode, 0)
            self.assertIn("missing or empty", empty_package.stderr)

            oversized_runtime = work / "oversized.nsis.7z"
            with oversized_runtime.open("wb") as handle:
                handle.truncate(4_294_967_295)
            oversized_package = subprocess.run([
                sys.executable, str(script), "candidate",
                "--file", str(windows_folder / "helper.exe"),
                "--runtime-manifest",
                str(windows_folder / "runtime-manifest-windows-x64.json"),
                "--runtime-package", str(oversized_runtime),
                "--target-os", "windows", "--arch", "x64",
                "--tag", "helper-v1.2.3", "--commit", "a" * 40,
                "--run-id", "123", "--run-attempt", "2",
                "--signing-status", "verified",
                "--notarization-status", "not-applicable",
                "--output", str(work / "oversized-package.json"),
            ], capture_output=True, text=True)
            self.assertNotEqual(oversized_package.returncode, 0)
            self.assertIn("smaller than 4294967295", oversized_package.stderr)

            mac_folder = work / "mac-arm64"
            mac_package = subprocess.run([
                sys.executable, str(script), "candidate",
                "--file", str(mac_folder / "helper.dmg"),
                "--runtime-manifest",
                str(mac_folder / "runtime-manifest-mac-arm64.json"),
                "--runtime-package",
                str(windows_folder / "helper-runtime.nsis.7z"),
                "--target-os", "mac", "--arch", "arm64",
                "--tag", "helper-v1.2.3", "--commit", "a" * 40,
                "--run-id", "123", "--run-attempt", "2",
                "--signing-status", "verified",
                "--notarization-status", "verified",
                "--output", str(work / "mac-package.json"),
            ], capture_output=True, text=True)
            self.assertNotEqual(mac_package.returncode, 0)
            self.assertIn("must not include", mac_package.stderr)
            extra_manifest = work / "extra" / "runtime-manifest-unused.json"
            extra_manifest.parent.mkdir()
            extra_manifest.write_text("{}")
            extra_manifest_failure = subprocess.run([
                sys.executable, str(script), "assemble",
                "--receipts", str(work), "--tag", "helper-v1.2.3",
                "--commit", "a" * 40, "--run-id", "123",
                "--run-attempt", "2",
                "--output", str(work / "extra-manifest-release"),
            ], capture_output=True, text=True)
            self.assertNotEqual(extra_manifest_failure.returncode, 0)
            self.assertIn(
                "unreferenced or missing runtime manifest",
                extra_manifest_failure.stderr,
            )
            extra_manifest.unlink()
            current = work / "current-newer.json"
            newer = {**pointer, "tag": "helper-v2.0.0", "version": "2.0.0"}
            current.write_text(json.dumps(newer))
            downgrade = subprocess.run([
                sys.executable, str(script), "guard",
                "--candidate", str(output / "current.json"),
                "--current", str(current),
            ], capture_output=True, text=True)
            self.assertNotEqual(downgrade.returncode, 0)
            self.assertIn("downgrade blocked", downgrade.stderr)
            mismatched_receipt = (
                work / "windows-x64" / "candidate-windows-x64.json"
            )
            mismatched = json.loads(mismatched_receipt.read_text())
            mismatched["source"]["run_attempt"] = "3"
            mismatched_receipt.write_text(json.dumps(mismatched))
            provenance_failure = subprocess.run([
                sys.executable, str(script), "assemble",
                "--receipts", str(work), "--tag", "helper-v1.2.3",
                "--commit", "a" * 40, "--run-id", "123",
                "--run-attempt", "2", "--output", str(work / "bad-release"),
            ], capture_output=True, text=True)
            self.assertNotEqual(provenance_failure.returncode, 0)
            self.assertIn("different workflow runs", provenance_failure.stderr)

    def test_release_requirements_are_exact_and_hashed(self):
        root = Path(__file__).resolve().parent.parent
        for filename in (
            "requirements-windows-x64.txt",
            "requirements-mac-arm64.txt",
            "requirements-mac-x64.txt",
        ):
            lines = (root / "packaging" / filename).read_text().splitlines()
            requirements = [line for line in lines if line and not line.startswith("#")]
            self.assertGreaterEqual(len(requirements), 40)
            self.assertTrue(all("==" in line for line in requirements))
            self.assertTrue(all(" --hash=sha256:" in line for line in requirements))
            self.assertFalse(any(">=" in line or "~=" in line for line in requirements))
            self.assertFalse(any(
                line.startswith("auto-editor==") for line in requirements
            ))

    def test_engine_self_test_executes_frozen_runtime_contracts(self):
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(str(root / "packaging" / "engine_entry.py"))
        stdout = io.StringIO()
        missing_source = (
            root / "missing-pyinstaller-source" / "creative_contract.py"
        )
        with mock.patch.object(
                creative_contract, "__file__", str(missing_source)), \
                contextlib.redirect_stdout(stdout):
            result = namespace["_self_test"]()
        receipt = json.loads(stdout.getvalue())
        self.assertEqual(result, 0, receipt)
        self.assertTrue(receipt["checks"]["utf8_mode"])
        self.assertTrue(receipt["checks"]["ffmpeg_audio_decoder"])
        self.assertTrue(receipt["checks"]["pyav_not_bundled"])
        self.assertTrue(receipt["checks"]["in_process_low_speech_cutter"])
        self.assertTrue(receipt["checks"]["creative_contract_sha256"])

    def test_helper_daemon_self_test_executes_revision_contract(self):
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(
            str(root / "packaging" / "helper_daemon_entry.py"))
        self.assertTrue(namespace["revision_contract_check"]())

    def test_under_ten_words_cuts_only_safe_source_time_silence(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "source.mp4"
            src.write_bytes(b"source-video")
            rendered = work / "rendered.mp4"
            words = [
                {"w": "one", "s": 0.5, "e": 0.8, "p": 0.9},
                {"w": "two", "s": 3.0, "e": 3.5, "p": 0.9},
                {"w": "three", "s": 8.0, "e": 8.2, "p": 0.9},
            ]
            analyzed = subprocess.CompletedProcess(
                [], 0, b"", b"silence_start: 2.0\nsilence_end: 6.0\n"
            )
            captured_cuts = []

            def fake_apply(_src, cuts, _workdir):
                captured_cuts.extend(cuts)
                rendered.write_bytes(b"rendered-video")
                return rendered

            def fake_duration(path):
                return 7.45 if Path(path) == rendered else 10.0

            with mock.patch.object(
                pipeline, "transcribe", return_value=words
            ), mock.patch.object(
                pipeline, "_dur", side_effect=fake_duration
            ), mock.patch.object(
                pipeline, "_resolve_low_speech_ffmpeg",
                return_value=Path("/bundle/bin/ffmpeg"),
            ), mock.patch.object(
                pipeline, "run", return_value=analyzed
            ) as analyzer, mock.patch.object(
                pipeline, "apply_cuts", side_effect=fake_apply
            ) as renderer:
                output, ratio, raw_words = pipeline.word_guarded_cut(src, work)

            self.assertEqual(output, rendered)
            self.assertAlmostEqual(ratio, 0.745)
            self.assertEqual(raw_words, words)
            analyzer.assert_called_once()
            renderer.assert_called_once()
            self.assertEqual(captured_cuts, [
                {"s": 2.15, "e": 2.7,
                 "why": "confirmed silence outside protected words"},
                {"s": 3.85, "e": 5.85,
                 "why": "confirmed silence outside protected words"},
            ])
            for cut in captured_cuts:
                self.assertFalse(cut["s"] < 3.85 and cut["e"] > 2.7)

    def test_under_ten_words_no_safe_cut_is_explicitly_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "source.mp4"
            src.write_bytes(b"source-video")
            analyzed = subprocess.CompletedProcess([], 0, b"", b"")
            events = []
            with mock.patch.object(
                pipeline, "transcribe", return_value=[]
            ), mock.patch.object(
                pipeline, "_dur", return_value=10.0
            ), mock.patch.object(
                pipeline, "_resolve_low_speech_ffmpeg",
                return_value=Path("/bundle/bin/ffmpeg"),
            ), mock.patch.object(
                pipeline, "run", return_value=analyzed
            ), mock.patch.object(
                pipeline, "apply_cuts"
            ) as renderer, mock.patch.object(
                pipeline, "emit", side_effect=events.append
            ):
                output, ratio, _ = pipeline.word_guarded_cut(src, work)
            self.assertEqual(output.read_bytes(), src.read_bytes())
            self.assertEqual(ratio, 1.0)
            renderer.assert_not_called()
            self.assertEqual(events[-1]["event"], "low_speech_no_safe_cut")
            self.assertIn("no confirmed", events[-1]["reason"])

    def test_low_speech_retention_guard_preserves_source(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "source.mp4"
            src.write_bytes(b"source-video")
            analyzed = subprocess.CompletedProcess(
                [], 0, b"", b"silence_start: 0\nsilence_end: 10\n"
            )
            with mock.patch.object(
                pipeline, "_dur", return_value=10.0
            ), mock.patch.object(
                pipeline, "_resolve_low_speech_ffmpeg",
                return_value=Path("/bundle/bin/ffmpeg"),
            ), mock.patch.object(
                pipeline, "run", return_value=analyzed
            ) as analyzer, mock.patch.object(
                pipeline, "apply_cuts"
            ) as renderer:
                output, ratio = pipeline.silence_cut(src, work, words=[])
            self.assertEqual(output.read_bytes(), src.read_bytes())
            self.assertEqual(ratio, 1.0)
            self.assertEqual(analyzer.call_count, 3)
            renderer.assert_not_called()

    def test_low_speech_analysis_failure_blocks_instead_of_copying(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "source.mp4"
            src.write_bytes(b"source-video")
            failed = subprocess.CompletedProcess([], 1, b"", b"decode failed")
            with mock.patch.object(
                pipeline, "_dur", return_value=10.0
            ), mock.patch.object(
                pipeline, "_resolve_low_speech_ffmpeg",
                return_value=Path("/bundle/bin/ffmpeg"),
            ), mock.patch.object(pipeline, "run", return_value=failed):
                with self.assertRaisesRegex(
                    pipeline.LowSpeechCutError, "analysis failed"
                ):
                    pipeline.silence_cut(src, work, words=[])
            self.assertFalse((work / "cut.mp4").exists())

    def test_low_speech_render_failure_blocks_instead_of_copying(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "source.mp4"
            src.write_bytes(b"source-video")
            analyzed = subprocess.CompletedProcess(
                [], 0, b"", b"silence_start: 2\nsilence_end: 5\n"
            )
            render_error = subprocess.CalledProcessError(1, ["ffmpeg"])
            with mock.patch.object(
                pipeline, "_dur", return_value=10.0
            ), mock.patch.object(
                pipeline, "_resolve_low_speech_ffmpeg",
                return_value=Path("/bundle/bin/ffmpeg"),
            ), mock.patch.object(
                pipeline, "run", return_value=analyzed
            ), mock.patch.object(
                pipeline, "apply_cuts", side_effect=render_error
            ):
                with self.assertRaisesRegex(
                    pipeline.LowSpeechCutError, "render failed"
                ):
                    pipeline.silence_cut(src, work, words=[])
            self.assertFalse((work / "cut.mp4").exists())

    def test_frozen_low_speech_requires_verified_ffmpeg_path(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {}, clear=True), \
                self.assertRaisesRegex(
                    pipeline.LowSpeechCutError, "AUTOEDITOR_FFMPEG"
                ):
            pipeline._resolve_low_speech_ffmpeg()

    def test_release_receipts_credit_builder(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn('"built_by": "Omar Marabha (@CEOmarabha)"', source)

    def test_log_is_safe_on_a_legacy_windows_console(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        with mock.patch.object(sys, "stdout", stream), mock.patch.dict(
            os.environ, {"AUTOEDITOR_PROGRESS_JSON": ""}
        ):
            pipeline.log("FAIL ✗ ❌ → café")
            stream.flush()
        stream.detach()
        output = raw.getvalue().decode("cp1252")
        self.assertIn("FAIL", output)
        self.assertIn("café", output)

    def test_remotion_render_forwards_selected_license_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "remotion"
            project.mkdir()
            fonts = root / "fonts"
            fonts.mkdir()
            (project / "package.json").write_text("{}")
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                Path(command[5]).write_bytes(b"video")

            with mock.patch.dict(os.environ, {
                "AUTOEDITOR_REQUIRE_REMOTION": "1",
                "AUTOEDITOR_NODE": "/bundle/node",
                "AUTOEDITOR_REMOTION_CLI": "/bundle/remotion-cli.js",
                "AUTOEDITOR_BROWSER": "/bundle/chrome",
                "AUTOEDITOR_BUNDLED_FONTS": str(fonts),
                "REMOTION_LICENSE_KEY": "free-license",
            }), mock.patch.object(
                premium, "REMOTION_PROJ", project
            ), mock.patch.object(
                premium, "BROLL_CACHE", root / "cache"
            ), mock.patch.object(
                premium, "_run", side_effect=fake_run
            ), mock.patch.object(
                premium, "_validated_cached", return_value=None
            ), mock.patch.object(
                premium, "_valid_video_asset", return_value=True
            ):
                output = premium._remotion_viz(
                    {"template": "flow", "title": "TEST", "items": ["ONE"]},
                    2.5, 320, 568,
                )
            self.assertTrue(output)
            self.assertIn("--license-key=free-license", calls[0])
            self.assertIn(f"--public-dir={fonts}", calls[0])
            self.assertIn("--bundle-cache=false", calls[0])

    def test_creative_renderers_use_bundled_work_sans(self):
        premium_source = Path(premium.__file__).read_text()
        remotion_root = (
            Path(__file__).resolve().parent.parent / "templates" /
            "remotion-viz" / "src" / "Root.tsx"
        ).read_text()
        self.assertIn("WorkSans-Variable.ttf", premium_source)
        self.assertIn("AUTOEDITOR_BUNDLED_FONTS", premium_source)
        self.assertIn("staticFile('WorkSans-Variable.ttf')", remotion_root)

    def test_packaged_skip_does_not_read_old_account_key_or_cached_sfx(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_key = root / "elevenlabs.key"
            old_key.write_text("old-secret")
            (root / "eleven_boom.wav").write_bytes(b"old-generated-audio")
            with mock.patch.dict(os.environ, {
                "AUTOEDITOR_PACKAGED": "1", "ELEVENLABS_API_KEY": "",
            }), mock.patch.object(
                premium, "ELEVEN_KEY_FILE", old_key
            ), mock.patch.object(premium, "SFX_DIR", root):
                self.assertEqual(
                    premium._api_key("ELEVENLABS_API_KEY", old_key), ""
                )
                resolved = premium._resolve_sfx("boom")
                self.assertEqual(resolved, root / "boom.wav")
                self.assertNotEqual(resolved.read_bytes(), b"old-generated-audio")

    def test_clean_install_builds_deterministic_48k_sfx_fallbacks(self):
        edl = {
            "punch_ins": [{"s": 0.25, "e": 1.0, "scale": 1.12}],
            "broll": [{
                "s": 2.0, "e": 5.0,
                "viz": {"template": "steps", "items": ["one", "two"]},
            }],
            "graphics": [{"s": 6.0, "e": 8.0, "kind": "stat"}],
        }
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
            os.environ, {
                "AUTOEDITOR_PACKAGED": "1", "ELEVENLABS_API_KEY": "",
            }
        ), mock.patch.object(premium, "SFX_DIR", Path(td) / "missing-sfx"):
            first = premium.build_sfx_plan(edl)
            first_bytes = {path.name: path.read_bytes() for path, _, _ in first}
            second = premium.build_sfx_plan(edl)
            second_bytes = {path.name: path.read_bytes() for path, _, _ in second}

        self.assertEqual(len(first), 6)
        self.assertEqual(
            {path.name for path, _, _ in first},
            {"boom.wav", "whoosh.wav", "pop.wav", "riser.wav", "impact.wav"},
        )
        self.assertEqual(
            [(path.name, timestamp, gain) for path, timestamp, gain in first],
            [(path.name, timestamp, gain) for path, timestamp, gain in second],
        )
        self.assertEqual(first_bytes, second_bytes)
        for data in first_bytes.values():
            with contextlib.closing(wave.open(io.BytesIO(data), "rb")) as cue:
                self.assertEqual(cue.getframerate(), 48_000)
                self.assertEqual(cue.getnchannels(), 1)
                self.assertEqual(cue.getsampwidth(), 2)
                self.assertGreater(cue.getnframes(), 0)

    def test_sfx_plan_fails_when_a_planned_cue_cannot_be_produced(self):
        edl = {"punch_ins": [{"s": 0.0, "e": 1.0, "scale": 1.12}]}
        with tempfile.TemporaryDirectory() as td:
            blocked = Path(td) / "not-a-directory"
            blocked.write_text("storage unavailable")
            with mock.patch.dict(os.environ, {
                "AUTOEDITOR_PACKAGED": "1", "ELEVENLABS_API_KEY": "",
            }), mock.patch.object(
                premium, "SFX_DIR", blocked
            ), self.assertRaisesRegex(RuntimeError, "boom"):
                premium.build_sfx_plan(edl)

    def test_premium_media_checks_use_packaged_ffmpeg_paths(self):
        probe_result = mock.Mock(
            stdout=json.dumps({
                "streams": [{"width": 1080, "height": 1920}],
                "format": {"duration": "4.0"},
            }).encode(),
            returncode=0,
        )
        with mock.patch.dict(os.environ, {
            "AUTOEDITOR_FFMPEG": r"C:\\Ryan Editor\\ffmpeg.exe",
            "AUTOEDITOR_FFPROBE": r"C:\\Ryan Editor\\ffprobe.exe",
        }), mock.patch.object(
            premium.shutil, "which", return_value=None
        ), mock.patch.object(
            premium, "_run", return_value=probe_result
        ) as runner:
            premium._video_info("clip.mp4")
            self.assertEqual(
                runner.call_args.args[0][0],
                r"C:\\Ryan Editor\\ffprobe.exe",
            )
            premium._video_decodes("clip.mp4")
            self.assertEqual(
                runner.call_args.args[0][0],
                r"C:\\Ryan Editor\\ffmpeg.exe",
            )

    def test_ryan_profiles_force_short_form_and_carry_creator_direction(self):
        landscape_long = {"width": 1920, "height": 1080, "duration": 130}
        for profile_id in ("ryan_duffy", "ryan_humes", "shared_skit"):
            with self.subTest(profile=profile_id):
                creator = config.Config.load(profile=profile_id)
                self.assertEqual(
                    pipeline._resolve_style("auto", creator, landscape_long),
                    "short",
                )
                self.assertTrue(creator.creative.get("mode"))
                self.assertTrue(creator.creative.get("opening"))
                self.assertEqual(
                    len(profiles.profile_sha256(profile_id)), 64
                )

    def test_creator_cut_settings_reach_all_profile_pacing_values(self):
        creator = config.Config.load(profile="ryan_duffy")
        settings = pipeline._cut_settings("short", creator)
        self.assertEqual(settings["min_pause"], 0.50)
        self.assertEqual(settings["head"], 0.25)
        self.assertEqual(settings["tail"], 0.30)
        self.assertEqual(settings["retake_min_words"], 3)
        self.assertEqual(settings["retake_max_gap"], 12.0)

    def test_deepseek_receipt_binds_creator_short_direction(self):
        words = [
            {"w": "funny", "s": 0.0, "e": 0.2},
            {"w": "opening", "s": 0.3, "e": 0.5},
            {"w": "premise", "s": 0.6, "e": 0.8},
            {"w": "lands", "s": 0.9, "e": 1.1},
            {"w": "here.", "s": 1.2, "e": 1.4},
        ]
        candidate = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [], "broll": [], "graphics": [],
        }
        valid = {**candidate, "contract": {"score": 100}}
        prompts = []

        def fake_llm(prompt, *args, **kwargs):
            prompts.append(prompt)
            kwargs["receipt"].update({"ok": True})
            return dict(candidate)

        with mock.patch.object(
            providers, "llm_json", side_effect=fake_llm
        ), mock.patch.object(
            creative_contract, "validate_edl",
            return_value=(valid, {"score": 100}),
        ):
            result = premium.deepseek_edl(
                words, [], 5.0, style="short",
                profile_id="ryan_duffy",
                creative={"mode": "relatable skit", "avoid": "generic stock"},
                profile_sha256_value="a" * 64,
            )
        self.assertIsNotNone(result)
        self.assertTrue(all("Creator profile: ryan_duffy" in p for p in prompts))
        self.assertTrue(all("generic stock" in p for p in prompts))
        receipt = result["production_receipt"]
        self.assertEqual(receipt["profile_id"], "ryan_duffy")
        self.assertEqual(receipt["profile_sha256"], "a" * 64)

    def test_json_extractor_requires_every_requested_key(self):
        partial = '{"punch_ins":[]}'
        self.assertIsNone(providers.extract_json(
            partial, require=("punch_ins", "broll", "graphics")
        ))
        complete = '{"punch_ins":[],"broll":[],"graphics":[]}'
        self.assertEqual(
            providers.extract_json(
                complete, require=("punch_ins", "broll", "graphics")
            ),
            {"punch_ins": [], "broll": [], "graphics": []},
        )

    def test_deepseek_v4_payload_enables_json_thinking_and_max_reasoning(self):
        captured = {}
        old_post = providers._post
        old_key = os.environ.get("DEEPSEEK_API_KEY")
        old_model = os.environ.get("DEEPSEEK_MODEL")
        old_llm_model = os.environ.get("LLM_MODEL")

        def fake_post(url, payload, headers, timeout):
            captured.update({
                "url": url, "payload": payload,
                "headers": headers, "timeout": timeout,
            })
            return {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"ok":true}'},
                }],
                "system_fingerprint": "test-fingerprint",
            }

        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        os.environ.pop("DEEPSEEK_MODEL", None)
        os.environ.pop("LLM_MODEL", None)
        providers._post = fake_post
        receipt = {}
        try:
            result = providers.llm_json(
                'Return json with an "ok" key.',
                require=("ok",), provider="deepseek", attempts=1,
                receipt=receipt,
            )
        finally:
            providers._post = old_post
            if old_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old_key
            if old_model is None:
                os.environ.pop("DEEPSEEK_MODEL", None)
            else:
                os.environ["DEEPSEEK_MODEL"] = old_model
            if old_llm_model is None:
                os.environ.pop("LLM_MODEL", None)
            else:
                os.environ["LLM_MODEL"] = old_llm_model
        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            captured["payload"]["model"], providers.DEFAULT_DEEPSEEK_MODEL
        )
        self.assertEqual(
            captured["payload"]["response_format"], {"type": "json_object"}
        )
        self.assertEqual(
            captured["payload"]["thinking"], {"type": "enabled"}
        )
        self.assertEqual(captured["payload"]["reasoning_effort"], "max")
        self.assertGreaterEqual(captured["payload"]["max_tokens"], 16000)
        self.assertTrue(receipt["ok"])

    def test_retired_deepseek_alias_is_rejected(self):
        old_key = os.environ.get("DEEPSEEK_API_KEY")
        old_model = os.environ.get("DEEPSEEK_MODEL")
        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
        try:
            with self.assertRaises(providers.ProviderConfigurationError):
                providers.llm_available("deepseek")
        finally:
            if old_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old_key
            if old_model is None:
                os.environ.pop("DEEPSEEK_MODEL", None)
            else:
                os.environ["DEEPSEEK_MODEL"] = old_model

    def test_generic_llm_model_cannot_override_deepseek_v4(self):
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "LLM_MODEL": "gpt-4o-mini",
        }, clear=True):
            self.assertEqual(
                providers._deepseek_model(),
                providers.DEFAULT_DEEPSEEK_MODEL,
            )

    def test_empty_deepseek_content_retries_before_accepting_json(self):
        replies = [
            {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": ""},
                }]
            },
            {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"ok":true}'},
                }]
            },
        ]
        receipt = {}
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_MODEL": providers.DEFAULT_DEEPSEEK_MODEL,
        }), mock.patch.object(
            providers, "_post", side_effect=replies
        ), mock.patch.object(providers.time, "sleep", return_value=None):
            result = providers.llm_json(
                "Return json.", require=("ok",), provider="deepseek",
                attempts=2, receipt=receipt,
            )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            [attempt["result"] for attempt in receipt["attempts"]],
            ["empty_content", "json_ok"],
        )

    def test_truncated_finish_reason_is_never_accepted(self):
        reply = {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": '{"ok":true}'},
            }]
        }
        receipt = {}
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_MODEL": providers.DEFAULT_DEEPSEEK_MODEL,
        }), mock.patch.object(providers, "_post", return_value=reply):
            result = providers.llm_json(
                "Return json.", require=("ok",), provider="deepseek",
                attempts=1, receipt=receipt,
            )
        self.assertIsNone(result)
        self.assertEqual(
            receipt["attempts"][0]["result"], "finish_length"
        )

    def test_incomplete_http_body_becomes_a_retryable_transport_error(self):
        with mock.patch.object(
                providers.urllib.request, "urlopen",
                side_effect=http.client.IncompleteRead(b"{", 20)):
            result = providers._post(
                "https://example.invalid", {"x": 1}, {}, 1
            )
        self.assertEqual(result, {"_transport_error": "incomplete_read"})

    def test_trickled_http_body_cannot_bypass_wall_clock_timeout(self):
        import http.server
        import threading
        import time

        body = b'{"ok":true}'

        class TrickleHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.04)
                except OSError:
                    pass

            def log_message(self, _format, *args):
                pass

        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), TrickleHandler
        )
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        thread.start()
        started = time.monotonic()
        try:
            result = providers._post(
                f"http://127.0.0.1:{server.server_port}/",
                {"x": 1}, {}, 0.12,
            )
            elapsed = time.monotonic() - started
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertEqual(result, {"_transport_error": "timeout"})
        self.assertLess(elapsed, 1.0)

    def test_permanent_http_4xx_is_not_retried(self):
        receipt = {}
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_MODEL": providers.DEFAULT_DEEPSEEK_MODEL,
        }), mock.patch.object(
            providers, "_post", return_value={"_transport_error": "http_401"}
        ) as post, mock.patch.object(
            providers.time, "sleep", return_value=None
        ) as sleep:
            result = providers.llm_json(
                "Return json.", require=("ok",), provider="deepseek",
                attempts=3, receipt=receipt,
            )
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_telegram_home_channel_is_an_explicit_chat_id_fallback(self):
        with mock.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_HOME_CHANNEL": "12345",
        }, clear=True):
            self.assertEqual(providers._tg(), ("token", "12345"))

    def test_telegram_configuration_is_explicit(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(providers.telegram_configured())
        with mock.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "12345",
        }, clear=True):
            self.assertTrue(providers.telegram_configured())

    def test_creative_contract_keeps_the_complete_transcript(self):
        words = [
            {"w": f"word{i}", "s": i * 0.2, "e": i * 0.2 + 0.1}
            for i in range(1600)
        ]
        words[-1]["w"] = "LATE_MARKER"
        payload = creative_contract.transcript_payload(words)
        self.assertIn("LATE_MARKER", payload)
        self.assertEqual(json.loads(payload)[-1]["i"], 1599)
        self.assertNotIn("[:6000]", Path(premium.__file__).read_text())

    def test_heuristic_hook_leaves_short_edit_sync_windows(self):
        duration = 11.0
        words = [
            {"w": f"word{index}", "s": index * 0.4,
             "e": index * 0.4 + 0.28}
            for index in range(27)
        ]
        edl = premium.heuristic_edl(
            words, [], duration, style="short"
        )
        self.assertEqual(len(edl["punch_ins"]), 1)
        hook = edl["punch_ins"][0]
        self.assertLessEqual(hook["e"] - hook["s"], 2.5)

        scheduled = premium._heuristic_sync_probe_schedule(
            words, edl, duration
        )
        self.assertGreaterEqual(len(scheduled), 4)

    def test_heuristic_drops_later_punch_that_starves_sync_probes(self):
        duration = 10.8
        words = []
        for index in range(26):
            token = f"word{index}"
            if index == 12:
                token += "."
            if index == 13:
                token = "50%"
            words.append({
                "w": token,
                "s": index * 0.4,
                "e": index * 0.4 + 0.28,
            })
        edl = premium.heuristic_edl(
            words, [], duration, style="short"
        )
        self.assertEqual(edl["punch_ins"], [
            {"s": 0.0, "e": 2.5, "scale": 1.1}
        ])

        scheduled = premium._heuristic_sync_probe_schedule(
            words, edl, duration
        )
        self.assertGreaterEqual(len(scheduled), 4)

    def test_heuristic_reserve_matches_gate5_group_scheduling(self):
        def make_words(duration, sentence_seconds, offset):
            words = []
            words_per_sentence = 10
            word_step = sentence_seconds / words_per_sentence
            index = 0
            while offset + index * word_step < duration - 0.3:
                token = (
                    "plain"
                    if index % words_per_sentence != words_per_sentence - 1
                    else f"{index // words_per_sentence + 1}."
                )
                start = offset + index * word_step
                words.append({
                    "w": token,
                    "s": round(start, 3),
                    "e": round(min(
                        duration - 0.02, start + word_step * 0.7
                    ), 3),
                })
                index += 1
            return words

        cases = (
            (10.8, 7.0, 0.4),
            (25.0, 4.0, 0.2),
        )
        for duration, sentence_seconds, offset in cases:
            with self.subTest(duration=duration):
                words = make_words(duration, sentence_seconds, offset)
                edl = premium.heuristic_edl(
                    words, [], duration, style="short"
                )
                word_mids = [
                    (word["s"] + word["e"]) / 2
                    for word in words
                ]
                avoid = [
                    (event["s"] - 1.0, event["e"] + 1.0)
                    for layer in ("broll", "graphics", "punch_ins")
                    for event in edl[layer]
                ]
                groups = pipeline._probe_candidate_groups(
                    word_mids,
                    avoid,
                    duration,
                    min(word_mids),
                    max(word_mids),
                )
                tried = set()
                expected = []
                for group in groups:
                    for timestamp in group:
                        key = round(timestamp, 3)
                        if key in tried:
                            continue
                        tried.add(key)
                        expected.append(timestamp)
                        break

                scheduled = premium._heuristic_sync_probe_schedule(
                    words, edl, duration
                )
                self.assertEqual(
                    [round(value, 3) for value in scheduled],
                    [round(value, 3) for value in expected],
                )
                self.assertGreaterEqual(len(scheduled), 4)

    def test_creative_contract_hash_does_not_require_module_source(self):
        source_hash = creative_contract.contract_sha256()
        self.assertEqual(
            source_hash,
            "69268bf0d64b966b2f0ef5fc5d2a0bd52de2ac246d4c02eb63f837b7a311b732",
        )
        missing_source = (
            Path("/pyinstaller") / "autoeditor" / "creative_contract.py"
        )
        with mock.patch.object(
                creative_contract, "__file__", str(missing_source)):
            frozen_hash = creative_contract.contract_sha256()
        self.assertEqual(frozen_hash, source_hash)
        self.assertEqual(len(frozen_hash), 64)
        self.assertEqual(len(bytes.fromhex(frozen_hash)), 32)

    def test_creative_contract_anchors_times_to_spoken_words(self):
        spoken = (
            "Your brain decides what matters today before any choice is made "
            "A city story now shows the concrete lesson clearly"
        ).split()
        words = [
            {"w": word, "s": index * 0.5, "e": index * 0.5 + 0.35}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.1, "e": 2.6, "scale": 1.1,
                "anchor_quote": "Your brain decides what matters today",
                "reason": "opening verdict",
            }],
            "broll": [{
                "s": 5.0, "e": 7.0,
                "query": "city skyline aerial night", "family": "",
                "anchor_quote": "A city story now shows the concrete lesson",
                "reason": "literal city story",
            }],
            "graphics": [],
        }
        edl, report = creative_contract.validate_edl(
            raw, words, [], 10.0, "long"
        )
        self.assertEqual(report["score"], 100)
        self.assertAlmostEqual(edl["punch_ins"][0]["s"], 0.0, places=3)
        city_start = next(
            word["s"] for word in words if word["w"] == "A"
        )
        self.assertAlmostEqual(
            edl["broll"][0]["s"], city_start - 0.1, places=3
        )

    def test_creative_contract_rejects_ungrounded_model_event(self):
        words = [
            {"w": word, "s": index * 0.4, "e": index * 0.4 + 0.25}
            for index, word in enumerate(
                "This opening sentence has enough real spoken words today".split()
            )
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote": "words that were never spoken here",
                "reason": "invented anchor",
            }],
            "broll": [],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "not grounded"):
            creative_contract.validate_edl(raw, words, [], 8.0, "long")

    def test_creative_contract_rejects_overlapping_model_events(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        punch = {
            "s": 0.0, "e": 2.0, "scale": 1.1,
            "anchor_quote":
                "This opening sentence contains enough real spoken words",
            "reason": "opening emphasis",
        }
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [punch, {**punch, "reason": "stacked emphasis"}],
            "broll": [{
                "s": 4.0, "e": 6.0,
                "query": "abstract light particles macro", "family": "",
                "anchor_quote": "A visual example follows with enough concrete words",
                "reason": "visual example",
            }],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "overlapping"):
            creative_contract.validate_edl(raw, words, [], 9.0, "long")

    def test_creative_contract_rejects_markup_and_unknown_commands(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote":
                    "This opening sentence contains enough real spoken words",
                "reason": "opening emphasis",
            }],
            "broll": [],
            "graphics": [{
                "s": 4.0, "e": 6.0, "kind": "callout",
                "text": "<SCRIPT>ALERT",
                "anchor_quote": "A visual example follows with enough concrete words",
                "reason": "visual example",
            }],
            "cuts": [{"s": 0.0, "e": 8.0}],
        }
        with self.assertRaises(
                creative_contract.CreativeContractError) as caught:
            creative_contract.validate_edl(raw, words, [], 9.0, "long")
        message = str(caught.exception)
        self.assertIn("unsupported top-level keys: cuts", message)
        self.assertIn("markup or control characters", message)

    def test_creative_contract_requires_exact_five_word_anchor(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote": "This opening sentence has enough words",
                "reason": "opening emphasis",
            }],
            "broll": [],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "not grounded"):
            creative_contract.validate_edl(raw, words, [], 8.0, "long")

    def test_fabricated_visual_copy_cannot_hide_behind_a_real_anchor(self):
        spoken = (
            "This city story explains architecture with a concrete lesson "
            "for everyone watching the example today"
        ).split()
        words = [
            {"w": word, "s": index * 0.4, "e": index * 0.4 + 0.25}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [],
            "broll": [{
                "s": 0.0, "e": 3.0,
                "query": "city architecture aerial", "family": "",
                "anchor_quote":
                    "This city story explains architecture with a concrete",
                "reason": "city example",
                "viz": {
                    "template": "steps",
                    "title": "THREE SIGNALS",
                    "items": ["SUPERIORITY", "AUTONOMY", "CERTAINTY"],
                },
            }],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "on-screen copy is not grounded"):
            creative_contract.validate_edl(raw, words, [], 6.0, "long")

    def test_fabricated_stat_number_cannot_reach_the_renderer(self):
        spoken = (
            "This city story explains architecture with a concrete lesson "
            "for everyone watching the example today"
        ).split()
        words = [
            {"w": word, "s": index * 0.4, "e": index * 0.4 + 0.25}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [],
            "broll": [],
            "graphics": [{
                "s": 0.0, "e": 2.0, "kind": "stat",
                "text": "REVENUE GROWTH", "value": "487%",
                "anchor_quote":
                    "This city story explains architecture with a concrete",
                "reason": "claimed result",
            }],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "on-screen copy is not grounded"):
            creative_contract.validate_edl(raw, words, [], 6.0, "long")

    def test_punch_anchor_itself_cannot_exceed_the_duration_limit(self):
        spoken = [f"word{index}" for index in range(20)]
        words = [
            {"w": word, "s": index * 0.5, "e": index * 0.5 + 0.35}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 8.0, "scale": 1.1,
                "anchor_quote": " ".join(spoken),
                "reason": "slow opening",
            }],
            "broll": [],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "spans more than 8.0 seconds"):
            creative_contract.validate_edl(raw, words, [], 11.0, "long")

    def test_legal_decimal_boundary_duration_is_not_rejected(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 1.8, "e": 2.4, "scale": 1.1,
                "anchor_quote":
                    "This opening sentence contains enough real spoken words",
                "reason": "opening emphasis",
            }],
            "broll": [{
                "s": 4.0, "e": 5.5,
                "query": "abstract visual example", "family": "",
                "anchor_quote":
                    "A visual example follows with enough concrete words",
                "reason": "opening visual",
            }],
            "graphics": [],
        }
        edl, report = creative_contract.validate_edl(
            raw, words, [], 9.0, "long"
        )
        self.assertEqual(report["score"], 100)
        self.assertGreaterEqual(
            edl["punch_ins"][0]["e"] - edl["punch_ins"][0]["s"], 0.6
        )

    def test_clustered_punch_budget_is_rejected(self):
        spoken = [f"word{index}" for index in range(100)]
        words = [
            {"w": word, "s": index * 0.3, "e": index * 0.3 + 0.2}
            for index, word in enumerate(spoken)
        ]
        punches = []
        for start_word in (0, 6, 12):
            punches.append({
                "s": start_word * 0.3,
                "e": start_word * 0.3 + 0.7,
                "scale": 1.1,
                "anchor_quote": " ".join(
                    spoken[start_word:start_word + 5]
                ),
                "reason": "clustered emphasis",
            })
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": punches,
            "broll": [{
                "s": 5.0, "e": 7.0,
                "query": "abstract opening visual", "family": "",
                "anchor_quote": " ".join(spoken[17:22]),
                "reason": "opening visual",
            }],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "pacing requires at least 10.0s"):
            creative_contract.validate_edl(raw, words, [], 30.0, "long")

    def test_stat_parser_preserves_human_numeric_display(self):
        cases = {
            "$1,200": ("$1,200", 1200.0, 0, ""),
            "1,200": ("1,200", 1200.0, 0, ""),
            "12.5%": ("12.5%", 12.5, 1, "%"),
            "10.5": ("10.5", 10.5, 1, ""),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                parts = premium._stat_parts(value)
                self.assertIsNotNone(parts)
                self.assertEqual(
                    (parts["display"], parts["number"],
                     parts["decimals"], parts["suffix"]),
                    expected,
                )
        self.assertIsNone(premium._stat_parts("HALF"))
        self.assertTrue(creative_contract._number_is_spoken(
            "12.5%", "the result was twelve point five percent"
        ))

    def test_every_graphic_kind_uses_a_caption_disjoint_lane_in_all_aspects(self):
        events = {
            "keyword": {"text": "KEY POINT"},
            "stat": {"text": "RESULT", "value": "87%"},
            "callout": {"text": "BAD TIME VS MINUTE"},
            "bars": {"text": "COMPARISON", "items": [
                {"label": "FIRST", "value": 1},
                {"label": "SECOND", "value": 2},
            ]},
        }
        for width, height in ((360, 640), (640, 360), (1080, 1920),
                              (1920, 1080)):
            lane = premium._graphic_lane_geometry(width, height)
            caption_bottom = round(
                height * premium.CAPTION_RESERVED_BOTTOM_FRAC
            )
            self.assertGreaterEqual(lane["y"], caption_bottom)
            self.assertLessEqual(lane["y"] + lane["height"], height)
            view = premium._graphic_viewport(width, height)
            self.assertGreaterEqual(
                lane["x"],
                view["x"] + math.ceil(
                    view["width"] * premium.PLATFORM_SAFE_LEFT_FRAC
                ),
            )
            self.assertLessEqual(
                lane["x"] + lane["width"],
                view["x"] + view["width"] - math.ceil(
                    view["width"] * premium.PLATFORM_SAFE_RIGHT_FRAC
                ),
            )
            self.assertLessEqual(
                lane["y"] + lane["height"],
                view["y"] + math.floor(
                    view["height"]
                    * (1.0 - premium.PLATFORM_SAFE_BOTTOM_FRAC)
                ),
            )
            for kind, event in events.items():
                with self.subTest(width=width, height=height, kind=kind):
                    check = premium._graphic_caption_geometry_check(
                        width, height, lane
                    )
                    self.assertTrue(check["ok"])
                    markup = premium._hf_kind_markup(
                        kind, event, 2.0, width, height
                    )
                    self.assertIsNotNone(markup)
                    self.assertIn(f'top:{int(lane["height"] * 0.12)}px',
                                  markup[0])

    def test_graphic_lane_is_enclosed_by_each_nine_sixteen_crop_viewport(self):
        events = {
            "keyword": {"text": "KEY POINT"},
            "stat": {"text": "RESULT", "value": "87%"},
            "callout": {"text": "BAD TIME VS MINUTE"},
            "bars": {"text": "COMPARISON", "items": [
                {"label": "FIRST", "value": 1},
                {"label": "SECOND", "value": 2},
            ]},
        }
        cases = (
            # 1920x1080 source center-cropped horizontally to 9:16.
            (1920, 1080, (656.25, 0.0, 607.5, 1080.0)),
            # A 720x1920 source center-cropped vertically to 9:16.
            (720, 1920, (0.0, 320.0, 720.0, 1280.0)),
        )
        for width, height, viewport in cases:
            view = premium._graphic_viewport(width, height, viewport)
            lane = premium._graphic_lane_geometry(width, height, viewport)
            with self.subTest(width=width, height=height):
                self.assertGreaterEqual(lane["x"], view["x"])
                self.assertGreaterEqual(lane["y"], view["y"])
                self.assertLessEqual(
                    lane["x"] + lane["width"], view["x"] + view["width"]
                )
                self.assertLessEqual(
                    lane["y"] + lane["height"], view["y"] + view["height"]
                )
            for kind, event in events.items():
                with self.subTest(width=width, height=height, kind=kind):
                    check = premium._graphic_caption_geometry_check(
                        width, height, lane, viewport=viewport
                    )
                    self.assertTrue(check["ok"])
                    self.assertTrue(check["in_viewport"])
                    markup = premium._hf_kind_markup(
                        kind, event, 2.0, width, height, viewport=viewport
                    )
                    self.assertIsNotNone(markup)
                    self.assertIn(
                        f'top:{int(lane["height"] * 0.12)}px', markup[0]
                    )
            outside = dict(lane, x=view["x"] - 1)
            failed = premium._graphic_caption_geometry_check(
                width, height, outside, viewport=viewport
            )
            self.assertFalse(failed["ok"])
            self.assertFalse(failed["in_viewport"])

    def test_graphic_geometry_gate_rejects_platform_ui_overlap(self):
        width, height = 720, 1280
        view = premium._graphic_viewport(width, height)
        lane = premium._graphic_lane_geometry(width, height)
        self.assertEqual(lane, {
            "x": 80, "y": 333, "width": 520, "height": 153,
        })
        unsafe = {
            **lane,
            "x": lane["x"] + 1,
            "width": lane["width"],
        }
        check = premium._graphic_caption_geometry_check(
            width, height, unsafe
        )
        self.assertFalse(check["ok"])
        self.assertTrue(check["in_viewport"])
        self.assertFalse(check["platform_safe"])
        bottom_unsafe = {
            **lane,
            "y": view["y"] + round(view["height"] * 0.72),
        }
        check = premium._graphic_caption_geometry_check(
            width, height, bottom_unsafe
        )
        self.assertFalse(check["ok"])
        self.assertFalse(check["platform_safe"])

    def test_invalid_graphic_viewports_fail_before_render(self):
        invalid = (
            (0, 0, 1080),
            (-1, 0, 608, 1080),
            (1500, 0, 608, 1080),
            (0, 0, float("nan"), 1080),
        )
        for viewport in invalid:
            with self.subTest(viewport=viewport), self.assertRaises(ValueError):
                premium._graphic_lane_geometry(1920, 1080, viewport)

    def test_unsafe_graphic_geometry_fails_and_remains_release_blocking(self):
        width, height = 1080, 1920
        unsafe = {
            "y": round(height * premium.CAPTION_RESERVED_TOP_FRAC),
            "height": round(height * 0.12),
        }
        check = premium._graphic_caption_geometry_check(
            width, height, unsafe
        )
        self.assertFalse(check["ok"])
        self.assertFalse(check["separate"])
        edl = {
            "graphics": [{"s": 0.0, "e": 1.0, "kind": "keyword",
                          "text": "UNSAFE"}],
            "broll": [],
            "resolution": {
                "graphics_ok": True,
                "graphics_caption_clearance_ok": False,
            },
        }
        self.assertEqual(premium.broll_layers(edl, []), [])
        self.assertFalse(edl["resolution"]["ok"])

    def test_pillow_graphics_emit_release_bound_clearance_for_every_kind(self):
        from PIL import Image

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        graphics = [
            {"s": 0.0, "e": 1.0, "kind": "keyword", "text": "KEY POINT"},
            {"s": 1.0, "e": 2.0, "kind": "stat", "text": "RESULT",
             "value": "87%"},
            {"s": 2.0, "e": 3.0, "kind": "callout",
             "text": "BAD TIME VS MINUTE"},
            {"s": 3.0, "e": 4.0, "kind": "bars", "text": "COMPARE",
             "items": [{"label": "NO", "value": 1},
                       {"label": "YES", "value": 2}]},
        ]
        for width, height in ((360, 640), (640, 360)):
            with self.subTest(width=width, height=height), \
                    tempfile.TemporaryDirectory() as td, \
                    mock.patch.object(
                        premium, "_hf_render_graphic", return_value=False
                    ):
                edl = {"graphics": [dict(event) for event in graphics]}
                layers = premium.build_graphics(
                    edl, Path(td), str(font_file), width, height
                )
                self.assertEqual([layer["kind"] for layer in layers],
                                 [event["kind"] for event in graphics])
                self.assertTrue(
                    edl["resolution"]["graphics_caption_clearance_ok"]
                )
                self.assertTrue(edl["resolution"]["ok"])
                for layer in layers:
                    self.assertTrue(layer["caption_clearance"]["ok"])
                    frame = Image.open(
                        Path(layer["seq"]) / "f_0015.png"
                    ).getchannel("A")
                    bounds = frame.getbbox()
                    self.assertIsNotNone(bounds)
                    self.assertLessEqual(bounds[3], layer["height"])
                    self.assertGreaterEqual(
                        layer["y"] + bounds[1],
                        round(height * premium.CAPTION_RESERVED_BOTTOM_FRAC),
                    )

    def test_pillow_graphics_render_inside_exact_crop_viewport_for_every_kind(self):
        from PIL import Image

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        graphics = [
            {"s": 0.0, "e": 1.0, "kind": "keyword", "text": "KEY POINT"},
            {"s": 1.0, "e": 2.0, "kind": "stat", "text": "RESULT",
             "value": "87%"},
            {"s": 2.0, "e": 3.0, "kind": "callout",
             "text": "BAD TIME VS MINUTE"},
            {"s": 3.0, "e": 4.0, "kind": "bars", "text": "COMPARE",
             "items": [{"label": "NO", "value": 1},
                       {"label": "YES", "value": 2}]},
        ]
        cases = (
            (1280, 720, (437.5, 0.0, 405.0, 720.0)),
            (360, 960, (0.0, 160.0, 360.0, 640.0)),
        )
        for width, height, viewport in cases:
            with self.subTest(width=width, height=height), \
                    tempfile.TemporaryDirectory() as td, \
                    mock.patch.object(
                        premium, "_hf_render_graphic", return_value=False
                    ):
                edl = {"graphics": [dict(event) for event in graphics]}
                layers = premium.build_graphics(
                    edl, Path(td), str(font_file), width, height,
                    viewport=viewport,
                )
                lane = premium._graphic_lane_geometry(
                    width, height, viewport
                )
                self.assertEqual(len(layers), len(graphics))
                for layer in layers:
                    self.assertEqual(
                        (layer["x"], layer["y"], layer["width"],
                         layer["height"]),
                        (lane["x"], lane["y"], lane["width"],
                         lane["height"]),
                    )
                    self.assertTrue(layer["caption_clearance"]["ok"])
                    frame = Image.open(
                        Path(layer["seq"]) / "f_0015.png"
                    ).convert("RGBA")
                    self.assertEqual(frame.size,
                                     (lane["width"], lane["height"]))
                    bounds = frame.getchannel("A").getbbox()
                    self.assertIsNotNone(bounds)
                    self.assertGreater(bounds[0], 0)
                    self.assertGreater(bounds[1], 0)
                    self.assertLess(bounds[2], frame.width)
                    self.assertLess(bounds[3], frame.height)

    def test_hyperframes_layers_keep_exact_crop_offsets_for_every_kind(self):
        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        graphics = [
            {"s": 0.0, "e": 1.0, "kind": "keyword", "text": "KEY POINT"},
            {"s": 1.0, "e": 2.0, "kind": "stat", "text": "RESULT",
             "value": "87%"},
            {"s": 2.0, "e": 3.0, "kind": "callout",
             "text": "BAD TIME VS MINUTE"},
            {"s": 3.0, "e": 4.0, "kind": "bars", "text": "COMPARE",
             "items": [{"label": "NO", "value": 1},
                       {"label": "YES", "value": 2}]},
        ]
        viewport = (437.5, 0.0, 405.0, 720.0)
        lane = premium._graphic_lane_geometry(1280, 720, viewport)
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                premium, "_hf_render_graphic", return_value=True
        ) as render:
            edl = {"graphics": graphics}
            layers = premium.build_graphics(
                edl, Path(td), str(font_file), 1280, 720,
                viewport=viewport,
            )
        self.assertEqual(render.call_count, len(graphics))
        self.assertTrue(all(
            call.kwargs["viewport"] == viewport
            for call in render.call_args_list
        ))
        self.assertEqual([layer["kind"] for layer in layers],
                         [graphic["kind"] for graphic in graphics])
        for layer in layers:
            self.assertEqual(
                (layer["x"], layer["y"], layer["width"], layer["height"]),
                (lane["x"], lane["y"], lane["width"], lane["height"]),
            )
            self.assertTrue(layer["caption_clearance"]["ok"])

    def test_vs_callout_renders_two_compact_pills_with_divider(self):
        from PIL import Image

        self.assertEqual(
            premium._comparison_parts("BAD TIME VS MINUTE"),
            ("BAD TIME", "MINUTE"),
        )
        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                premium, "_hf_render_graphic", return_value=False):
            edl = {"graphics": [{
                "s": 0.0, "e": 1.0, "kind": "callout",
                "text": "BAD TIME VS MINUTE",
            }]}
            layer = premium.build_graphics(
                edl, Path(td), str(font_file), 720, 1280
            )[0]
            image = Image.open(
                Path(layer["seq"]) / "f_0015.png"
            ).convert("RGBA")
            backing_x = set()
            for y in range(image.height):
                for x in range(image.width):
                    red, green, blue, alpha = image.getpixel((x, y))
                    if (red, green, blue, alpha) == (0, 0, 0, 218):
                        backing_x.add(x)
            runs = []
            for x in sorted(backing_x):
                if not runs or x > runs[-1][-1] + 1:
                    runs.append([x])
                else:
                    runs[-1].append(x)
        pill_runs = [
            run for run in runs
            if len(run) >= layer["width"] * 0.12
        ]
        self.assertEqual(len(pill_runs), 2)
        self.assertTrue(layer["caption_clearance"]["ok"])

    def test_approved_forty_four_character_graphic_copy_is_never_truncated(self):
        from PIL import Image

        exact = "ELEVEN CHARS TWELVE MORE THAN TWENTY CHARS!!"
        self.assertEqual(len(exact), premium.GRAPHIC_TEXT_MAX_CHARS)
        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        lane = premium._graphic_lane_geometry(720, 1280)

        for kind in ("keyword", "callout", "stat", "bars"):
            event = {"s": 0.0, "e": 1.0, "kind": kind, "text": exact}
            if kind == "stat":
                event["value"] = "87%"
            elif kind == "bars":
                event["items"] = [
                    {"label": "NO", "value": 1},
                    {"label": "YES", "value": 2},
                ]
            with self.subTest(renderer="hyperframes", kind=kind):
                markup = premium._hf_kind_markup(
                    kind, event, 1.0, 720, 1280
                )
                self.assertIsNotNone(markup)
                self.assertIn(exact, markup[0])
                self.assertNotIn(exact[:40] + "<", markup[0])
            with self.subTest(renderer="pillow", kind=kind), \
                    tempfile.TemporaryDirectory() as td, \
                    mock.patch.object(
                        premium, "_hf_render_graphic", return_value=False
                    ):
                edl = {"graphics": [event]}
                with mock.patch.object(
                        premium, "_fit_graphic_font",
                        wraps=premium._fit_graphic_font
                ) as fit:
                    layer = premium.build_graphics(
                        edl, Path(td), str(font_file), 720, 1280
                    )[0]
                fitted_texts = [call.args[1] for call in fit.call_args_list]
                self.assertIn(exact, fitted_texts)
                self.assertEqual(layer["text"], exact)
                frame = Image.open(
                    Path(layer["seq"]) / "f_0015.png"
                ).getchannel("A")
                bounds = frame.getbbox()
                self.assertIsNotNone(bounds)
                self.assertGreater(bounds[0], 0)
                self.assertLess(bounds[2], lane["width"])
                self.assertTrue(layer["caption_clearance"]["platform_safe"])

    def test_bars_preserve_all_five_validated_labels_in_both_renderers(self):
        from PIL import Image

        labels = [
            "ALPHA LABEL EXACTLY TWENTY",
            "BRAVO LABEL EXACTLY TWENTY",
            "CHARLIE LABEL IS PRESERVED",
            "DELTA LABEL IS PRESERVED",
            "ECHO LABEL IS PRESERVED",
        ]
        self.assertEqual(len(labels), 5)
        self.assertTrue(all(len(label) <= 26 for label in labels))
        items = [
            {"label": label, "value": index + 1}
            for index, label in enumerate(labels)
        ]
        event = {
            "s": 0.0, "e": 1.0, "kind": "bars",
            "text": "ALL FIVE LABELS", "items": items,
        }

        markup = premium._hf_kind_markup(
            "bars", event, 1.0, 720, 1280
        )
        self.assertIsNotNone(markup)
        for index, label in enumerate(labels):
            self.assertIn(label, markup[0])
            self.assertIn(f'id="bar{index}"', markup[0])

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                premium, "_hf_render_graphic", return_value=False):
            edl = {"graphics": [event]}
            layer = premium.build_graphics(
                edl, Path(td), str(font_file), 720, 1280
            )[0]
            frame = Image.open(
                Path(layer["seq"]) / "f_0015.png"
            ).getchannel("A")

        self.assertEqual(layer["items"], items)
        self.assertEqual(
            edl["resolution"]["graphics_copy_integrity"][0]["items"], items
        )
        self.assertTrue(edl["resolution"]["graphics_copy_integrity_ok"])
        self.assertEqual(
            edl["production_receipt"]["graphics_copy_integrity"]["events"][0]
            ["items"],
            items,
        )
        self.assertTrue(
            edl["production_receipt"]["graphics_copy_integrity"]["ok"]
        )
        bounds = frame.getbbox()
        self.assertIsNotNone(bounds)
        self.assertGreater(bounds[0], 0)
        self.assertGreater(bounds[1], 0)
        self.assertLess(bounds[2], frame.width)
        self.assertLess(bounds[3], frame.height)

    def test_graphics_copy_integrity_fails_if_renderer_alters_items(self):
        event = {
            "s": 0.0, "e": 1.0, "kind": "bars", "text": "COMPARE",
            "items": [
                {"label": "FIRST EXACT LABEL", "value": 1},
                {"label": "SECOND EXACT LABEL", "value": 2},
            ],
        }
        planned = premium._graphic_copy_binding(event)
        accepted = premium._graphic_copy_integrity([event], [planned])
        altered_layer = {**planned, "items": [
            {**planned["items"][0], "label": "ALTERED"},
            *planned["items"][1:],
        ]}
        rejected = premium._graphic_copy_integrity(
            [event], [altered_layer]
        )
        self.assertTrue(accepted["ok"])
        self.assertFalse(rejected["ok"])
        self.assertFalse(rejected["events"][0]["ok"])

    def test_bar_values_cannot_be_negative(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual comparison follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote":
                    "This opening sentence contains enough real spoken words",
                "reason": "opening emphasis",
            }],
            "broll": [],
            "graphics": [{
                "s": 4.0, "e": 6.0, "kind": "bars",
                "text": "CLEAR COMPARISON",
                "items": [
                    {"label": "FIRST", "value": -1},
                    {"label": "SECOND", "value": 2},
                ],
                "anchor_quote":
                    "A visual comparison follows with enough concrete words",
                "reason": "spoken comparison",
            }],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "nonnegative"):
            creative_contract.validate_edl(raw, words, [], 9.0, "long")

    def test_validated_plan_hash_changes_when_an_event_changes(self):
        edl = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [],
            "broll": [{
                "s": 1.0, "e": 3.0, "query": "city skyline",
                "family": "", "anchor_quote": "city skyline",
                "reason": "literal visual",
            }],
            "graphics": [],
        }
        original = creative_contract.edl_sha256(edl)
        edl["broll"][0]["query"] = "unrelated ocean"
        self.assertNotEqual(original, creative_contract.edl_sha256(edl))

    def test_requested_deepseek_mode_cannot_silently_fall_back(self):
        old_available = premium.providers.llm_available
        old_deepseek = premium.deepseek_edl
        premium.providers.llm_available = lambda provider=None: True
        premium.deepseek_edl = lambda *args, **kwargs: None
        try:
            with self.assertRaisesRegex(RuntimeError, "render is blocked"):
                premium.make_edl(
                    [{"w": "hello", "s": 0.0, "e": 0.4}],
                    [], 2.0, use_llm=True,
                )
        finally:
            premium.providers.llm_available = old_available
            premium.deepseek_edl = old_deepseek

    def test_deepseek_mode_with_empty_transcript_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "nonempty"):
            premium.make_edl([], [], 10.0, use_llm=True)

    def test_critic_repairs_again_with_fresh_validator_errors(self):
        words = [
            {"w": "opening", "s": 0.0, "e": 0.2},
            {"w": "words", "s": 0.3, "e": 0.5},
            {"w": "for", "s": 0.6, "e": 0.8},
            {"w": "a", "s": 0.9, "e": 1.1},
            {"w": "test", "s": 1.2, "e": 1.4},
        ]
        candidate = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [], "broll": [], "graphics": [],
        }
        valid_edl = {
            **candidate,
            "contract": {"score": 100},
        }
        receipts = []

        def fake_llm(*args, **kwargs):
            kwargs["receipt"].update({
                "ok": True,
                "attempts": [{"result": "json_ok"}],
                "model": providers.DEFAULT_DEEPSEEK_MODEL,
            })
            receipts.append(kwargs["purpose"])
            return dict(candidate)

        with mock.patch.object(
            providers, "llm_json", side_effect=fake_llm
        ), mock.patch.object(
            creative_contract, "validate_edl",
            side_effect=[
                creative_contract.CreativeContractError(["director bad"]),
                creative_contract.CreativeContractError(["critic still bad"]),
                (valid_edl, {"score": 100}),
            ],
        ):
            result = premium.deepseek_edl(words, [], 5.0, style="long")
        self.assertIsNotNone(result)
        production = result["production_receipt"]
        self.assertEqual(production["critic_rounds_used"], 2)
        self.assertEqual(len(production["critic_contract_error_rounds"]), 1)
        self.assertEqual(
            receipts,
            [
                "creative_edl_director",
                "creative_edl_critic_round_1",
                "creative_edl_critic_round_2",
            ],
        )

    def test_script_requirement_runs_before_media_preflight(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        requirement = source.index(
            "brand.yaml requires the script-integrity gate"
        )
        preflight = source.index("info = preflight(src)")
        self.assertLess(requirement, preflight)

    def test_supplied_control_files_cannot_silently_change_modes(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            existing = work / "script.txt"
            existing.write_text("known script")
            self.assertEqual(
                pipeline._required_input_file(existing, "--script"),
                existing.resolve(),
            )
            for option in ("--script", "--edl", "--music", "--background"):
                with self.subTest(option=option), self.assertRaisesRegex(
                        ValueError, "input path does not exist"):
                    pipeline._required_input_file(
                        work / f"missing-{option[2:]}", option
                    )

    def test_short_internal_sync_audio_is_a_failed_unusable_probe(self):
        def fake_run(command, check=False):
            if "rawvideo" in command:
                return mock.Mock(stdout=bytes(160 * 45))
            return mock.Mock(stdout=bytes(1000))

        with mock.patch.object(pipeline, "run", side_effect=fake_run):
            result = pipeline.verify_sync(
                Path("master.mp4"), Path("reference.mp4"), {}, 12.0
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["probes_used"], 0)
        self.assertTrue(result["probes"])
        self.assertTrue(all(
            probe.get("error") == "audio_probe_shorter_than_one_second"
            for probe in result["probes"]
        ))

    def test_receipt_proven_silent_video_uses_frame_timeline_verification(self):
        reference = bytes([80]) * (160 * 45)

        def fake_run(command, check=False):
            self.assertIn("rawvideo", command)
            return mock.Mock(stdout=reference)

        with mock.patch.object(pipeline, "run", side_effect=fake_run), \
                mock.patch.object(pipeline, "_dur", return_value=8.0):
            result = pipeline.verify_silent_video_timeline(
                Path("master.mp4"), Path("reference.mp4"), 8.0
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "intentional_silent_video_timeline")
        self.assertGreaterEqual(result["probes_used"], 2)

    def test_silent_video_timeline_rejects_missing_frames(self):
        with mock.patch.object(
                pipeline, "run", return_value=mock.Mock(stdout=b"")), \
                mock.patch.object(pipeline, "_dur", return_value=8.0):
            result = pipeline.verify_silent_video_timeline(
                Path("master.mp4"), Path("reference.mp4"), 8.0
            )
        self.assertFalse(result["ok"])

    def test_internal_sync_visual_threshold_allows_encode_noise_only(self):
        self.assertEqual(pipeline.SYNC_VISUAL_MAE_MAX, 13.0)
        source = inspect.getsource(pipeline.verify_sync)
        self.assertIn("mae <= SYNC_VISUAL_MAE_MAX", source)
        self.assertIn("abs(off_ms) <= 25.0", source)

    def test_live_command_imports_the_canonical_pipeline(self):
        root = Path(__file__).resolve().parent.parent
        tracked = (
            root / "integrations" / "hermes" / "hermes_pse_edit.py"
        )
        candidates = [tracked]
        live = (
            Path.home() / "cinematic-autopilot" / "tools"
            / "hermes_pse_edit.py"
        )
        if live.exists():
            candidates.append(live)
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                source = candidate.read_text()
                self.assertIn(
                    "from autoeditor.pipeline import main", source
                )
                self.assertNotIn("deepseek-v4-flash", source)
        installer = (root / "install.sh").read_text()
        self.assertIn(
            "integrations/hermes/hermes_pse_edit.py", installer
        )
        self.assertIn(".talking-head-autoeditor-root", installer)

    def test_canonical_runtime_does_not_require_an_uninstalled_legacy_venv(self):
        self.assertEqual(pipeline.VENV_PY, Path(pipeline.sys.executable))
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertNotIn("Path(sys.executable).resolve()", source)
        self.assertNotIn(
            'VENV_PY = EDIT_VENV / "bin" / "python"', source
        )

    def test_frozen_engine_uses_bundled_asr_worker_modes(self):
        commands = []

        def fake_run(command, **_kwargs):
            command = [str(value) for value in command]
            commands.append(command)
            if "--asr-words" in command:
                Path(command[-1]).write_text("[]")
            if "--asr-secondary" in command:
                Path(command[-1]).write_text('{"text":"verified words"}')
            return mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            pipeline.sys, "frozen", True, create=True
        ), mock.patch.object(pipeline, "run", side_effect=fake_run):
            work = Path(td)
            words = pipeline.transcribe(work / "input.mp4", work)
            secondary = pipeline._secondary_asr_text(
                work / "input.mp4", 1.0, 3.0, work
            )

        self.assertEqual(words, [])
        self.assertEqual(secondary, "verified words")
        self.assertTrue(any("--asr-words" in cmd for cmd in commands))
        self.assertTrue(any("--asr-secondary" in cmd for cmd in commands))

    def test_default_catalogs_exist_without_live_bridge_side_effects(self):
        self.assertTrue(premium.CLIP_CATALOGS)
        self.assertTrue(any(
            "marabha_kling_clip_library" in str(path)
            for path in premium.CLIP_CATALOGS
        ))

    def test_live_hermes_skill_requires_script_and_v4_pro(self):
        root = Path(__file__).resolve().parent.parent
        tracked = (
            root / "integrations" / "hermes"
            / "pse-talking-head-autoedit" / "SKILL.md"
        )
        candidates = [tracked]
        live = (
            Path.home() / ".hermes" / "skills" / "media"
            / "pse-talking-head-autoedit" / "SKILL.md"
        )
        if live.exists():
            candidates.append(live)
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                source = candidate.read_text()
                self.assertIn("--script", source)
                self.assertIn("DeepSeek V4 Pro", source)
                self.assertNotIn("deepseek-v4-flash", source.lower())
                self.assertIn(".UNVERIFIED", source)
        self.assertIn(
            "integrations/hermes/pse-talking-head-autoedit/SKILL.md",
            (root / "install.sh").read_text(),
        )

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg and ffprobe are required")
    def test_visual_artifact_gate_detects_present_and_missing_overlay(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            reference = work / "reference.mp4"
            present = work / "present.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(reference),
            ], check=True)
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(reference), "-vf",
                "drawbox=x=40:y=47:w=240:h=21:color=yellow:t=fill:"
                "enable='between(t,1,2)'",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(present),
            ], check=True)
            edl = {
                "broll": [],
                "graphics": [{"s": 1.0, "e": 2.0}],
            }
            found = pipeline.verify_visual_events(
                present, reference, edl
            )
            missing = pipeline.verify_visual_events(
                reference, reference, edl
            )
        self.assertTrue(found["ok"])
        self.assertFalse(missing["ok"])

    def test_visual_artifact_probe_covers_graphics_not_caption_lane(self):
        source = inspect.getsource(pipeline._visual_frame_difference)
        self.assertIn("floor(ih*0.15)", source)
        self.assertIn("floor(ih*0.25)", source)
        self.assertIn("26%-38%", source)
        self.assertNotIn("floor(ih*0.55):0:0", source)

    def test_graphics_receive_exact_delivery_viewport_before_render(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        viewport = source.index("delivery_viewport = _delivery_viewport(")
        graphics = source.index("gfx_layers = prem.build_graphics(")
        self.assertLess(viewport, graphics)
        branch = source[graphics:source.index("broll_lyrs =", graphics)]
        self.assertIn("viewport=delivery_viewport", branch)
        master = inspect.getsource(pipeline.render_master)
        self.assertIn("x={g.get('x', 0)}", master)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg and ffprobe are required")
    def test_aspect_derivatives_bind_both_geometry_paths_and_audio(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            landscape = work / "landscape.mp4"
            cropped = work / "cropped.mp4"
            portrait = work / "portrait.mp4"
            pillared = work / "pillared.mp4"
            bad_audio = work / "bad_audio.mp4"
            bad_sar = work / "bad_sar.mp4"
            black_background = work / "black_background.mp4"
            low_res_9x16 = work / "low_res_9x16.mp4"
            low_res_16x9 = work / "low_res_16x9.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-f", "lavfi", "-i",
                "sine=frequency=733:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(landscape),
            ], check=True)
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(landscape), "-vf",
                "crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9),"
                "scale=1080:1920,setsar=1",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", str(cropped),
            ], check=True)
            crop_result = pipeline.verify_aspect_derivative(
                cropped, landscape, "center_crop_9x16", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=180x320:rate=30:duration=3",
                "-f", "lavfi", "-i",
                "sine=frequency=811:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(portrait),
            ], check=True)
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(portrait), "-filter_complex",
                "[0:v]split=2[a][b];"
                "[a]scale=64:36,scale=1920:1080:flags=bicubic,"
                "crop=1920:1080,setsar=1[bg];"
                "[b]scale=608:1080,setsar=1[fg];"
                "[bg][fg]overlay=(W-w)/2:0,setsar=1",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", str(pillared),
            ], check=True)
            pillar_result = pipeline.verify_aspect_derivative(
                pillared, portrait, "portrait_pillarbox_16x9", {}, 3.0
            )
            fit_result = pipeline.verify_aspect_derivative(
                pillared, portrait, "fit_blur_16x9", {}, 3.0
            )
            wrong_geometry = pipeline.verify_aspect_derivative(
                landscape, landscape, "center_crop_9x16", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(cropped), "-vf", "setsar=2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", str(bad_sar),
            ], check=True)
            bad_sar_result = pipeline.verify_aspect_derivative(
                bad_sar, landscape, "center_crop_9x16", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(cropped), "-vf", "scale=540:960,setsar=1",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", str(low_res_9x16),
            ], check=True)
            low_res_9x16_result = pipeline.verify_aspect_derivative(
                low_res_9x16, landscape, "center_crop_9x16", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "color=black:size=1920x1080:rate=30:duration=3",
                "-i", str(portrait), "-filter_complex",
                "[0:v]setsar=1[bg];[1:v]scale=608:1080,setsar=1[fg];"
                "[bg][fg]overlay=(W-w)/2:0,setsar=1[v]",
                "-map", "[v]", "-map", "1:a", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "18", "-c:a", "copy",
                str(black_background),
            ], check=True)
            black_background_result = pipeline.verify_aspect_derivative(
                black_background, portrait, "fit_blur_16x9", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(pillared), "-vf", "scale=960:540,setsar=1",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", str(low_res_16x9),
            ], check=True)
            low_res_16x9_result = pipeline.verify_aspect_derivative(
                low_res_16x9, portrait, "fit_blur_16x9", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(cropped),
                "-f", "lavfi", "-i",
                "sine=frequency=1200:sample_rate=48000:duration=3",
                "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                "-c:a", "aac", "-shortest", str(bad_audio),
            ], check=True)
            rejected = pipeline.verify_aspect_derivative(
                bad_audio, landscape, "center_crop_9x16", {}, 3.0
            )
        self.assertTrue(crop_result["ok"])
        self.assertTrue(pillar_result["ok"])
        self.assertTrue(fit_result["ok"])
        self.assertFalse(wrong_geometry["ok"])
        self.assertIn("1080x1920", wrong_geometry["note"])
        self.assertFalse(bad_sar_result["ok"])
        self.assertIn("square pixels", bad_sar_result["note"])
        self.assertFalse(low_res_9x16_result["ok"])
        self.assertIn("1080x1920", low_res_9x16_result["note"])
        self.assertFalse(black_background_result["ok"])
        self.assertFalse(low_res_16x9_result["ok"])
        self.assertIn("1920x1080", low_res_16x9_result["note"])
        self.assertFalse(rejected["ok"])
        self.assertFalse(rejected["audio_hash_match"])

    def test_planned_diagram_cannot_degrade_into_stock_footage(self):
        edl = {
            "broll": [{
                "s": 1.0, "e": 4.0,
                "query": "generic business office",
                "family": "",
                "viz": {
                    "template": "flow",
                    "title": "THREE STEPS",
                    "items": ["ONE", "TWO", "THREE"],
                },
            }],
            "graphics": [],
        }
        with mock.patch.object(
            premium, "_remotion_viz", return_value=None
        ), mock.patch.object(
            premium, "_pexels_fetch"
        ) as stock:
            layers = premium.broll_layers(edl, [])
        self.assertEqual(layers, [])
        stock.assert_not_called()
        self.assertFalse(edl["resolution"]["ok"])
        self.assertEqual(edl["resolution"]["unresolved_broll"], [0])
        self.assertEqual(
            edl["resolution"]["broll_events"][0]["reason"],
            "planned diagram did not render",
        )

    def test_empty_family_cannot_resolve_to_arbitrary_local_footage(self):
        edl = {
            "broll": [{
                "s": 1.0, "e": 3.0,
                "query": "unavailable concrete topic", "family": "",
            }],
            "graphics": [],
        }
        clips = [{
            "family": "", "path": "/tmp/unrelated.mp4", "dur": 10.0,
        }]
        with mock.patch.object(
            premium, "_pexels_fetch", return_value=None
        ), mock.patch.object(
            premium, "_pixabay_fetch", return_value=None
        ), mock.patch.object(
            premium, "_video_duration", return_value=10.0
        ):
            layers = premium.broll_layers(edl, clips)
        self.assertEqual(layers, [])
        self.assertFalse(edl["resolution"]["ok"])

    def test_rejected_or_unclassified_catalog_rows_never_reenter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip = root / "clip.mp4"
            clip.write_bytes(b"fixture")
            rejected = root / "curated.csv"
            rejected.write_text(
                "path,rating,scene_family,duration_sec\n"
                f"{clip},REJECT,office,5\n"
            )
            unclassified = root / "manifest.csv"
            unclassified.write_text(
                "path,duration_sec\n"
                f"{clip},5\n"
            )
            with mock.patch.object(
                    premium, "CLIP_CATALOGS",
                    [unclassified, rejected]):
                clips = premium.load_kling()
        self.assertEqual(clips, [])

    def test_one_bad_catalog_duration_does_not_hide_later_clips(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "first.mp4"
            second = root / "second.mp4"
            first.write_bytes(b"fixture")
            second.write_bytes(b"fixture")
            catalog = root / "catalog.csv"
            catalog.write_text(
                "path,rating,scene_family,duration_sec\n"
                f"{first},GOOD,office,N/A\n"
                f"{second},GOOD,city,8.5\n"
            )
            with mock.patch.object(premium, "CLIP_CATALOGS", [catalog]):
                clips = premium.load_kling()
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0]["dur"], 5.0)
        self.assertEqual(clips[1]["dur"], 8.5)

    def test_short_broll_asset_cannot_freeze_through_planned_window(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "short.mp4"
            clip.write_bytes(b"short fixture")
            edl = {
                "broll": [{
                    "s": 1.0, "e": 5.0,
                    "query": "", "family": "office",
                }],
                "graphics": [],
            }
            catalog = [{
                "family": "office", "path": str(clip), "dur": 99.0,
            }]
            with mock.patch.object(
                    premium, "_video_duration", return_value=0.5):
                layers = premium.broll_layers(edl, catalog)
        self.assertEqual(layers, [])
        self.assertFalse(edl["resolution"]["ok"])
        self.assertEqual(
            edl["resolution"]["broll_events"][0]["reason"],
            "resolved asset is shorter than the planned window",
        )

    def test_invalid_cached_visual_is_removed_before_network_retry(self):
        with tempfile.TemporaryDirectory() as td:
            cached = Path(td) / "poison.mp4"
            cached.write_bytes(b"partial transfer")
            with mock.patch.object(
                    premium, "_video_info", return_value=(0.2, 1920, 1080)):
                hit = premium._validated_cached(
                    [cached], min_dur=3.0, portrait=False
                )
        self.assertIsNone(hit)
        self.assertFalse(cached.exists())

    def test_valid_metadata_cannot_hide_a_truncated_cached_visual(self):
        with tempfile.TemporaryDirectory() as td:
            cached = Path(td) / "header_only.mp4"
            cached.write_bytes(b"valid-looking partial transfer")
            with mock.patch.object(
                premium, "_video_info", return_value=(8.0, 1920, 1080)
            ), mock.patch.object(
                premium, "_video_decodes", return_value=False
            ):
                hit = premium._validated_cached(
                    [cached], min_dur=3.0, portrait=False
                )
        self.assertIsNone(hit)
        self.assertFalse(cached.exists())

    def test_calibration_is_bound_to_raw_hash(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "take.mov"
            raw.write_bytes(b"original raw bytes")
            sidecar = calibrate.write_certification(raw, -100)
            payload = json.loads(sidecar.read_text())
            self.assertEqual(payload["offset_ms"], -100)
            self.assertEqual(
                payload["source_sha256"],
                hashlib.sha256(raw.read_bytes()).hexdigest(),
            )
            self.assertEqual(pipeline.certified_av_offset(raw)[0], -100)
            raw.write_bytes(b"replacement under the same filename")
            offset, note = pipeline.certified_av_offset(raw)
            self.assertEqual(offset, 0)
            self.assertIn("does not match", note)

    def test_gate_rejects_applied_value_that_is_not_certified(self):
        with tempfile.TemporaryDirectory() as td:
            result = pipeline.verify_sync_source(
                Path(td) / "master.mp4",
                Path(td) / "raw.mov",
                {},
                applied_ms=-200,
                certified_ms=0,
                final_words=[],
                workdir=Path(td),
            )
        self.assertFalse(result["ok"])
        self.assertIn("not the certified", result["note"])

    def test_uncertified_offset_is_rejected_before_render(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "recording.mov"
            raw.write_bytes(b"original source")
            with self.assertRaisesRegex(ValueError, r"requested \+100ms"):
                pipeline.resolve_av_offset(raw, 100)
            applied, certified, note = pipeline.resolve_av_offset(raw, 0)
        self.assertEqual((applied, certified), (0, 0))
        self.assertIn("certified default is 0ms", note)

    def test_outputs_are_quarantined_until_explicit_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            final = Path(td) / "PSE_MASTER_16x9.mp4"
            final.write_bytes(b"completed but ungated")
            quarantined, final_paths = pipeline.quarantine_outputs(
                {"16x9": final}
            )
            held = quarantined["16x9"]
            self.assertFalse(final.exists())
            self.assertTrue(held.exists())
            self.assertIn(".UNVERIFIED", held.name)
            promoted = pipeline.promote_outputs(quarantined, final_paths)
            self.assertEqual(promoted["16x9"], final)
            self.assertTrue(final.exists())
            self.assertFalse(held.exists())

    def test_backward_raw_mapping_is_a_hard_failure(self):
        matches = [
            (5.0, 10.0),
            (10.0, 15.0),
            (15.0, 14.5),
            (20.0, 25.0),
        ]
        failures = pipeline._nonmonotonic_matches(matches)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["from_raw_t"], 15.0)
        self.assertEqual(failures[0]["to_raw_t"], 14.5)

    def test_duplicate_probe_is_not_a_backward_mapping(self):
        matches = [
            (199.3796, 255.31),
            (199.3800, 255.31),
        ]
        self.assertEqual(pipeline._nonmonotonic_matches(matches), [])

    def test_start_probe_searches_past_an_overlay_but_stays_bounded(self):
        words = [6.2, 6.6, 8.0, 8.4, 20.1, 20.5, 28.0, 28.4]
        groups = pipeline._probe_candidate_groups(
            words, [(-1.0, 6.0)], 30.0, 0.2, 29.0
        )
        self.assertTrue(groups[0])
        self.assertLessEqual(groups[0][0], 10.2)
        blocked = pipeline._probe_candidate_groups(
            words, [(-1.0, 12.0)], 30.0, 0.2, 29.0
        )
        self.assertEqual(blocked[0], [])

    def test_short_source_gate_still_gets_four_probe_groups(self):
        word_mids = [0.2 + index * 0.4 for index in range(36)]
        groups = pipeline._probe_candidate_groups(
            word_mids, [], 15.0, 0.2, 14.2
        )
        self.assertGreaterEqual(len(groups), 4)
        self.assertTrue(all(groups[index] for index in range(4)))
        self.assertEqual(pipeline.SOURCE_SYNC_MAX_GAP_SECONDS, 30.0)

    def test_source_audio_locator_uses_the_exact_window_energy(self):
        import numpy as np

        raw_audio = np.zeros(64, dtype=np.float64)
        raw_audio[0] = 1.0
        locator = pipeline._normalized_audio_window_locator(
            raw_audio, window_length=16, sample_rate=16
        )
        raw_time, best, second = locator(raw_audio[:16] * 2.0 + 3.0)

        self.assertEqual(raw_time, 0.0)
        self.assertGreater(best, 0.999)
        self.assertLessEqual(best, 1.0)
        self.assertEqual(second, -1.0)

    def test_source_audio_locator_rejects_zero_energy_evidence(self):
        import numpy as np

        locator = pipeline._normalized_audio_window_locator(
            np.zeros(64, dtype=np.float64),
            window_length=16,
            sample_rate=16,
        )
        self.assertEqual(locator(np.ones(16)), (0.0, -1.0, -1.0))

    def test_source_audio_locator_ignores_a_near_silent_decoy(self):
        import numpy as np

        rng = np.random.default_rng(20260807)
        target = rng.normal(size=32)
        raw_audio = np.zeros(256, dtype=np.float64)
        raw_audio[96:128] = target
        raw_audio[192:224] = target * 1e-8
        locator = pipeline._normalized_audio_window_locator(
            raw_audio, window_length=32, sample_rate=32
        )
        raw_time, best, _second = locator(target * 0.4 + 0.2)

        self.assertEqual(raw_time, 3.0)
        self.assertGreater(best, 0.999)
        self.assertLessEqual(best, 1.0)

    def test_source_audio_locator_exposes_an_ambiguous_duplicate(self):
        import numpy as np

        rng = np.random.default_rng(20260807)
        target = rng.normal(size=32)
        raw_audio = np.zeros(256, dtype=np.float64)
        raw_audio[64:96] = target
        raw_audio[160:192] = target
        locator = pipeline._normalized_audio_window_locator(
            raw_audio, window_length=32, sample_rate=32
        )
        raw_time, best, second = locator(target * 0.4 + 0.2)

        # Equal peaks may resolve to either duplicate depending on the FFT and
        # NumPy implementation. The contract is that both remain visible as
        # ambiguous, not which tied peak wins argmax.
        self.assertIn(raw_time, (2.0, 5.0))
        self.assertGreater(best, 0.999)
        self.assertGreater(second, 0.999)
        self.assertLess(best - second, 0.08)

    def test_ignored_option_combinations_fail_instead_of_changing_modes(self):
        base = {
            "no_premium": False,
            "edl": None,
            "background": None,
            "no_llm": False,
            "creative_constraints": None,
        }
        cases = [
            {**base, "no_premium": True, "edl": Path("plan.json")},
            {**base, "no_premium": True, "background": Path("bg.png")},
            {**base, "no_premium": True, "no_llm": True},
            {**base, "no_premium": True,
             "creative_constraints": Path("constraints.json")},
            {**base, "edl": Path("plan.json"), "no_llm": True},
        ]
        for values in cases:
            with self.subTest(values=values):
                self.assertTrue(
                    pipeline._option_conflicts(argparse.Namespace(**values))
                )

    def test_renderer_honors_the_contracts_full_punch_scale(self):
        source = Path(premium.__file__).read_text()
        self.assertIn("min(1.15, max(1.05", source)

    def test_caption_gate_checks_the_selected_delivery_mode(self):
        words = [{"w": "hello", "s": 0.0, "e": 0.3}]
        with tempfile.TemporaryDirectory() as td:
            sidecar = Path(td) / "captions.srt"
            sidecar.write_text("caption")
            burned = pipeline._caption_delivery_check(
                words, True, True, sidecar
            )
            missing_burn = pipeline._caption_delivery_check(
                words, True, False, sidecar
            )
            sidecar_mode = pipeline._caption_delivery_check(
                words, False, False, sidecar
            )
        self.assertTrue(burned["ok"])
        self.assertFalse(missing_burn["ok"])
        self.assertTrue(sidecar_mode["ok"])

    def test_no_speech_caption_gate_is_explicitly_not_applicable(self):
        result = pipeline._caption_delivery_check(
            [], True, False, None, no_speech=True
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "not_applicable_no_speech")
        self.assertFalse(pipeline._caption_delivery_check(
            [], True, True, None, no_speech=True
        )["ok"])

    def test_empty_silent_transcript_is_identity_not_zero_percent_loss(self):
        check = pipeline._word_integrity_check(
            [], [], intentional_silence=True
        )
        self.assertTrue(check["ok"])
        self.assertEqual(check["ratio"], 1.0)
        self.assertEqual(check["mode"], "not_applicable_no_speech")
        self.assertFalse(pipeline._word_integrity_check([], [
            {"w": "unexpected", "s": 0.0, "e": 0.3},
        ], intentional_silence=True)["ok"])

    def test_intentional_silence_requires_a_complete_audio_source_partition(self):
        receipt = {
            "ordered_segment_ids": ["seg-a", "seg-b"],
            "synthesized_silence_source_ids": ["source-a", "source-b"],
            "used_audio_source_ids": [],
        }
        self.assertTrue(pipeline.intentional_silent_sequence_mode(
            receipt, [], [], None
        ))
        receipt["used_audio_source_ids"] = ["source-b"]
        self.assertFalse(pipeline.intentional_silent_sequence_mode(
            receipt, [], [], None
        ))

    def test_caption_safe_area_blocks_unsafe_burned_layout(self):
        words = [{"w": "hello", "s": 0.0, "e": 0.3}]
        fake_ffmpeg = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"",
            stderr=b'{"input_i":"-14.0"}',
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rendered = root / "unsafe.UNVERIFIED.mp4"
            rendered.write_bytes(b"rendered")
            sidecar = root / "captions.srt"
            sidecar.write_text("caption")
            with mock.patch.object(
                    pipeline, "run", return_value=fake_ffmpeg):
                qa = pipeline.qa_and_release(
                    {"9x16": rendered}, True, words, root,
                    captions_burn_requested=True,
                    caption_inputs_rendered=True,
                    caption_layout_safe=False,
                    caption_sidecar=sidecar,
                )
        self.assertFalse(qa["checks"]["caption_safe_area"]["ok"])
        self.assertFalse(qa["pass"])

    def test_caption_band_stays_inside_portrait_and_crop_safe_areas(self):
        from PIL import Image

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        words = [
            {"w": "pauses,", "s": 0.0, "e": 0.4},
            {"w": "adds", "s": 0.4, "e": 0.8},
            {"w": "captions", "s": 0.8, "e": 1.2},
        ]
        cases = (
            (720, 1560, 720.0, 0.060),
            (1080, 1350, 1350.0 * 9.0 / 16.0, 0.060),
            (1280, 720, 720.0 * 9.0 / 16.0, 0.060),
        )
        for vid_w, vid_h, safe_width, scale in cases:
            with self.subTest(vid_w=vid_w), tempfile.TemporaryDirectory() as td:
                preferred_size = max(28, int(vid_h * scale))
                chunks = pipeline._caption_chunks(
                    words, str(font_file), preferred_size, vid_w, 3,
                    safe_width,
                )
                self.assertGreaterEqual(len(chunks), 2)
                band = pipeline.build_caption_band(
                    words, Path(td), str(font_file), vid_w, vid_h,
                    "10", 1.3, scale=scale, max_words=3,
                    safe_width=safe_width,
                )
                self.assertTrue(band["layout_safe"])
                states = sorted((Path(td) / "capband").glob("state_*.png"))
                self.assertTrue(states)
                left, right = pipeline._caption_safe_bounds(
                    vid_w, safe_width
                )
                for state in states:
                    bounds = Image.open(state).getchannel("A").getbbox()
                    if bounds:
                        self.assertGreaterEqual(bounds[0], int(left) - 1)
                        self.assertLessEqual(bounds[2], int(right) + 2)

    def test_caption_semantic_chunks_do_not_end_on_connectors(self):
        text = (
            "you feel like a lot of pressure versus the word no it feels "
            "like protection and getting the word no out of people"
        ).split()
        words = [
            {"w": word, "s": index * 0.2, "e": index * 0.2 + 0.15}
            for index, word in enumerate(text)
        ]
        chunks = pipeline._caption_semantic_chunks(words, 3)
        endings = {
            re.sub(r"[^a-z0-9']", "", chunk[-1]["w"].lower())
            for chunk in chunks[:-1]
        }
        self.assertFalse(endings & pipeline._CAPTION_NO_END)
        self.assertTrue(all(1 <= len(chunk) <= 3 for chunk in chunks))
        phrases = [" ".join(word["w"] for word in chunk) for chunk in chunks]
        self.assertNotIn("and getting the", phrases)
        self.assertNotIn("than getting the", phrases)

    def test_caption_band_pixels_include_solid_white_and_dark_backing(self):
        from PIL import Image

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        with tempfile.TemporaryDirectory() as td:
            band = pipeline.build_caption_band(
                [
                    {"w": "Clear", "s": 0.0, "e": 0.4},
                    {"w": "type", "s": 0.4, "e": 0.8},
                ],
                Path(td), str(font_file), 720, 1280, "10", 0.9,
                scale=0.062, max_words=3, safe_width=720.0,
            )
            state = sorted((Path(td) / "capband").glob("state_*.png"))[0]
            image = Image.open(state).convert("RGBA")
            pixels = list(
                image.get_flattened_data()
                if hasattr(image, "get_flattened_data") else image.getdata()
            )
        self.assertTrue(band["pixel_quality"]["ok"])
        self.assertGreaterEqual(
            band["pixel_quality"]["minimum_solid_fill_ratio"], 0.42
        )
        self.assertGreaterEqual(
            band["pixel_quality"]["minimum_contrast_ratio"], 7.0
        )
        self.assertTrue(any(r >= 245 and g >= 245 and b >= 245 and a >= 245
                            for r, g, b, a in pixels))
        self.assertTrue(any(r <= 8 and g <= 8 and b <= 8 and a >= 160
                            for r, g, b, a in pixels))

    def test_caption_layout_measures_the_same_stroke_it_renders(self):
        from PIL import Image, ImageDraw

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        canvas = Image.new("RGBA", (720, 180), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        chunk = [
            {"w": "Premium", "s": 0.0, "e": 0.3},
            {"w": "captions", "s": 0.3, "e": 0.7},
        ]
        font, stroke, _widths, x, y, safe = pipeline._caption_layout(
            draw, chunk, str(font_file), 80, 720, 180, 720.0
        )
        expected = pipeline._caption_stroke(font.size)
        self.assertEqual(stroke, expected)
        self.assertTrue(safe)
        bounds = draw.textbbox(
            (x, y), "Premium captions", font=font, stroke_width=stroke
        )
        left, right = pipeline._caption_safe_bounds(720, 720.0)
        self.assertGreaterEqual(bounds[0], left - 0.5)
        self.assertLessEqual(bounds[2], right + 0.5)

    def test_caption_pixel_gate_rejects_thin_hollow_glyphs(self):
        from PIL import Image, ImageDraw, ImageFont

        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        image = Image.new("RGBA", (720, 180), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((80, 20, 640, 160), fill=(0, 0, 0, 172))
        thin = ImageFont.truetype(str(font_file), 80)
        draw.text((100, 38), "Thin text", font=thin, fill=(255, 255, 255, 255),
                  stroke_width=9, stroke_fill=(0, 0, 0, 255))
        quality = pipeline._caption_pixel_quality(image)
        self.assertFalse(quality["ok"])
        self.assertLess(quality["solid_fill_ratio"], 0.42)

    def test_upper_caption_lane_avoids_conservative_face_mouth_zone(self):
        view_top, view_height, caption_height = 320.0, 1280.0, 210
        caption_y = pipeline._caption_lane_y(
            view_top, view_height, caption_height, "upper"
        )
        subject_top = view_top + view_height * 0.26
        self.assertGreaterEqual(caption_y, view_top)
        self.assertLessEqual(caption_y + caption_height, subject_top)

    def test_caption_band_fails_closed_on_an_unreadable_long_token(self):
        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        with tempfile.TemporaryDirectory() as td:
            band = pipeline.build_caption_band(
                [{"w": "i" * 1000, "s": 0.0, "e": 0.8}],
                Path(td), str(font_file), 720, 1560, "10", 1.0,
                scale=0.060, max_words=3, safe_width=720.0,
            )
        self.assertFalse(band["layout_safe"])

    def test_caption_band_accepts_an_empty_transcript_without_indexing(self):
        root = Path(pipeline.__file__).resolve().parent.parent
        font_file = root / "desktop/helper/renderer/WorkSans-Variable.ttf"
        with tempfile.TemporaryDirectory() as td:
            band = pipeline.build_caption_band(
                [], Path(td), str(font_file), 720, 1560, "10", 1.0
            )
        self.assertIsNone(band)

    def test_tall_portrait_caption_position_survives_the_final_crop(self):
        _left, top, width, height = pipeline._delivery_viewport(
            720, 1920, "9x16"
        )
        self.assertEqual((top, width, height), (320.0, 720.0, 1280.0))
        caption_height = 200
        caption_y = pipeline._caption_overlay_y(
            top, height, caption_height, 0.10
        )
        self.assertGreaterEqual(caption_y, top)
        self.assertLessEqual(caption_y + caption_height, top + height)

    def test_source_gate_reconstructs_spatial_normalization(self):
        module_text = Path(pipeline.__file__).read_text(encoding="utf-8")
        function = next(
            node for node in ast.parse(module_text).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "verify_sync_source"
        )
        source = ast.get_source_segment(module_text, function)
        self.assertIn("_deletterbox_spec(raw_src)", source)
        names = {
            node.id for node in ast.walk(function)
            if isinstance(node, ast.Name)
        }
        self.assertNotIn("DELETTERBOX_VF", names)

    def test_independent_asr_can_clear_a_primary_homophone(self):
        script = (
            "There are three signals your Lizard Brain broadcasts and reads "
            "in every single human interaction: Superiority, Autonomy, and "
            "Certainty."
        )
        primary = (
            "Here's three signals your lizard brain broadcasts and reads in "
            "every single human interaction. The priority, autonomy, and "
            "certainty."
        )
        secondary = (
            "There's three signals your lizard brain broadcasts and reads in "
            "every single human interaction superiority autonomy and certainty."
        )
        result = pipeline._independent_asr_recovery(
            script, primary, secondary
        )
        self.assertTrue(result["clears"])
        self.assertEqual(result["recovered_content"], ["superiority"])

    def test_independent_asr_does_not_clear_confirmed_loss(self):
        result = pipeline._independent_asr_recovery(
            "The result is five hundred million years.",
            "The result is around Philly.",
            "The result is around Philly.",
        )
        self.assertFalse(result["clears"])

    def test_independent_asr_cannot_ignore_a_missing_negation(self):
        result = pipeline._independent_asr_recovery(
            "The system is not cryptographically secure.",
            "The system is secure.",
            "The system is cryptographically secure.",
        )
        self.assertIn("not", result["missing_content"])
        self.assertFalse(result["clears"])

    def test_multi_aspect_release_is_not_supported(self):
        self.assertNotIn("all", pipeline.SUPPORTED_ASPECTS)

    def test_container_stream_start_delta_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            media = Path(td) / "offset.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=160x90:rate=30:duration=3",
                "-itsoffset", "0.125", "-f", "lavfi", "-i",
                "sine=frequency=733:sample_rate=48000:duration=2.8",
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(media),
            ], check=True)
            delta = pipeline._stream_start_delta(media)
        self.assertGreater(delta, 0.08)
        self.assertLess(delta, 0.14)

    def test_failed_qa_cannot_reach_video_send(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        qa_guard = source.index('if not qa["pass"]:')
        send = source.index("providers.send_video(")
        self.assertLess(qa_guard, send)

    def test_main_builds_final_transcript_before_artifact_gates(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        assignment = source.index("final_words = transcribe(main_out_v, work)")
        retake_gate = source.index("residue = verify_no_retakes(final_words")
        source_gate = source.index("verify_sync_source(master", assignment)
        self.assertLess(assignment, retake_gate)
        self.assertLess(assignment, source_gate)

    def test_retranscription_reapplies_script_caption_correction(self):
        raw_words = [{"w": "misheard", "s": 0.0, "e": 0.2}]
        corrected = [{"w": "scripted", "s": 0.0, "e": 0.2}]
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            pipeline, "transcribe", return_value=raw_words
        ) as transcribe_call, mock.patch.object(
            pipeline, "script_correct", return_value=corrected
        ) as correct_call:
            script = Path(td) / "script.txt"
            script.write_text("scripted")
            result = pipeline._retranscribe_post_cut(
                Path("cut.mp4"), Path(td), script
            )
        self.assertEqual(result, corrected)
        transcribe_call.assert_called_once()
        correct_call.assert_called_once_with(raw_words, script)

    def test_whole_sentence_removed_by_large_splice_cannot_be_judged_fine(self):
        script_text = (
            "Alpha opening sentence has six clear words. "
            "Critical missing sentence contains the actual promise. "
            "Omega closing sentence has six clear words."
        )
        delivered = (
            "Alpha opening sentence has six clear words "
            "Omega closing sentence has six clear words"
        ).split()
        final_words = [
            {"w": word, "s": index * 0.3, "e": index * 0.3 + 0.2, "p": 0.99}
            for index, word in enumerate(delivered)
        ]
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            script = work / "script.txt"
            script.write_text(script_text)
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = [(1.8, 2.4)]
            try:
                with mock.patch.object(
                    providers, "llm_json",
                    return_value={
                        "verdicts": [{"i": 0, "verdict": "FINE", "why": ""}]
                    },
                ):
                    result = pipeline.script_integrity(
                        final_words, script, work
                    )
            finally:
                pipeline.CUT_BOUNDARIES = old_boundaries
        self.assertFalse(result["ok"])
        self.assertTrue(result["damaged"][0]["mechanically_missing"])
        self.assertIn("whole scripted sentence", result["damaged"][0]["why"])

    def test_srt_preserves_commas_in_spoken_copy(self):
        words = [
            {"w": "Hello,", "s": 0.0, "e": 0.2},
            {"w": "world.", "s": 0.2, "e": 0.5},
        ]
        with tempfile.TemporaryDirectory() as td:
            srt = Path(td) / "captions.srt"
            pipeline.build_srt(words, srt)
            text = srt.read_text()
        self.assertIn("Hello, world.", text)
        self.assertNotIn("Hello-world", text)

    def test_script_correction_splits_a_low_confidence_collapsed_phrase(self):
        words = [
            {"w": "word", "s": 0.0, "e": 0.2, "p": 0.99},
            {"w": "no", "s": 0.2, "e": 0.4, "p": 0.99},
            {"w": "other", "s": 0.4, "e": 0.7, "p": 0.83},
            {"w": "people", "s": 0.7, "e": 1.0, "p": 0.99},
        ]
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "script.txt"
            script.write_text("word no out of people", encoding="utf-8")
            corrected = pipeline.script_correct(words, script)
        self.assertEqual(
            [word["w"] for word in corrected],
            ["word", "no", "out", "of", "people"],
        )
        self.assertEqual(corrected[2]["s"], 0.4)
        self.assertEqual(corrected[3]["e"], 0.7)

    def test_script_correction_preserves_confident_short_paraphrase(self):
        words = [
            {"w": "word", "s": 0.0, "e": 0.2, "p": 0.99},
            {"w": "another", "s": 0.2, "e": 0.5, "p": 0.99},
            {"w": "people", "s": 0.5, "e": 0.8, "p": 0.99},
        ]
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "script.txt"
            script.write_text("word out of people", encoding="utf-8")
            corrected = pipeline.script_correct(words, script)
        self.assertEqual(
            [word["w"] for word in corrected],
            ["word", "another", "people"],
        )

    def test_script_correction_restores_exact_sentence_punctuation(self):
        words = [
            {"w": "than", "s": 0.0, "e": 0.2, "p": 0.99},
            {"w": "getting", "s": 0.2, "e": 0.4, "p": 0.99},
            {"w": "the", "s": 0.4, "e": 0.5, "p": 0.99},
            {"w": "word.", "s": 0.5, "e": 0.7, "p": 0.99},
            {"w": "Yes,", "s": 0.7, "e": 0.9, "p": 0.99},
            {"w": "out", "s": 0.9, "e": 1.0, "p": 0.99},
            {"w": "of", "s": 1.0, "e": 1.1, "p": 0.99},
            {"w": "people", "s": 1.1, "e": 1.4, "p": 0.99},
        ]
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "script.txt"
            script.write_text(
                "than getting the word yes out of people.",
                encoding="utf-8",
            )
            corrected = pipeline.script_correct(words, script)
        self.assertEqual(
            [word["w"] for word in corrected],
            ["than", "getting", "the", "word", "yes", "out", "of",
             "people."],
        )

    def test_cleanup_loop_cuts_and_retranscribes_inside_each_pass(self):
        self.assertEqual(pipeline.MAX_CLEANUP_PASSES, 2)
        self.assertGreater(pipeline.MIN_CLEANUP_SECONDS, 0)
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "range(1, MAX_CLEANUP_PASSES + 1)", source
        )
        self.assertIn("cleanup_seconds < MIN_CLEANUP_SECONDS", source)
        self.assertIn("cut = apply_cuts(cut, merged, work)", source)
        self.assertIn("words = transcribe(cut, work)", source)

    def test_operator_edl_skips_autonomous_cut_before_director_timeline(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        director = source.index("elif a.edl and a.edl.exists():")
        automatic = source.index("cut, retention, raw_words = word_guarded_cut(")
        self.assertLess(director, automatic)
        branch = source[director:automatic]
        self.assertIn("cut = src", branch)
        self.assertIn("raw_words = transcribe(cut, work)", branch)
        self.assertIn("words = raw_words", branch)
        self.assertNotIn("apply_cuts", branch)

    def test_word_integrity_uses_measured_words_not_caption_spelling(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "integrity_words, words = _integrity_and_caption_words(", source
        )
        self.assertIn(
            "_word_integrity_check(\n        integrity_words, final_words,",
            source,
        )

    def test_integrity_baseline_is_isolated_from_caption_corrections(self):
        measured = [
            {"w": "other", "s": 0.0, "e": 0.4, "p": 0.2},
            {"w": "people", "s": 0.4, "e": 0.8, "p": 1.0},
        ]
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "script.txt"
            script.write_text("out of people", encoding="utf-8")
            integrity, captions = pipeline._integrity_and_caption_words(
                measured, script
            )
        self.assertEqual(
            [word["w"] for word in integrity], ["other", "people"]
        )
        self.assertEqual(
            [word["w"] for word in captions], ["out", "of", "people"]
        )
        self.assertEqual(
            [word["w"] for word in measured], ["other", "people"]
        )

    def test_later_timeline_mutations_refresh_integrity_before_display(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        anomaly = source.split(
            'log("phase 3A: re-transcribing post-anomaly timeline")', 1
        )[1].split("font_file, font_ok", 1)[0]
        director = source.split(
            'log("phase 3R: re-transcribing post-cut timeline")', 1
        )[1].split('info["duration"] = _dur(cut)', 1)[0]
        for branch in (anomaly, director):
            self.assertIn("measured_words = transcribe(cut, work)", branch)
            self.assertIn(
                "integrity_words, words = _integrity_and_caption_words(",
                branch,
            )

    def test_delivery_encode_contract_and_desktop_skip_precede_watch_copy(self):
        arguments = pipeline.DELIVERY_VIDEO_ARGS
        self.assertEqual(arguments[arguments.index("-g") + 1], "60")
        for flag in ("-color_primaries", "-color_trc", "-colorspace"):
            self.assertEqual(arguments[arguments.index(flag) + 1], "bt709")
        self.assertEqual(arguments[arguments.index("-bsf:v") + 1], (
            "h264_metadata=colour_primaries=1:transfer_characteristics=1:"
            "matrix_coefficients=1"
        ))
        self.assertEqual(arguments[arguments.index("-movflags") + 1], "+faststart")
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn('"-ar", "48000", master', source)
        self.assertIn("loudnorm=I=-14:TP=-1", source)
        self.assertLess(
            source.index('or not providers.telegram_configured()'),
            source.index('tg_file = work / "tg_copy.mp4"'),
        )

    def test_delivery_color_metadata_gate_fails_closed(self):
        good = subprocess.CompletedProcess(
            [], 0,
            stdout=json.dumps({"streams": [{
                "color_space": "bt709",
                "color_transfer": "bt709",
                "color_primaries": "bt709",
            }]}).encode("utf-8"),
            stderr=b"",
        )
        missing = subprocess.CompletedProcess(
            [], 0,
            stdout=json.dumps({"streams": [{
                "color_space": "bt709",
                "color_transfer": "unknown",
                "color_primaries": "unknown",
            }]}).encode("utf-8"),
            stderr=b"",
        )
        with mock.patch.object(pipeline, "run", return_value=good):
            accepted = pipeline.verify_delivery_color_metadata(
                Path("delivered.mp4")
            )
        with mock.patch.object(pipeline, "run", return_value=missing):
            rejected = pipeline.verify_delivery_color_metadata(
                Path("delivered.mp4")
            )
        self.assertTrue(accepted["ok"])
        self.assertEqual(accepted["color_transfer"], "bt709")
        self.assertFalse(rejected["ok"])
        self.assertIn("lacks explicit BT.709", rejected["note"])

    def test_color_normalization_is_pixel_conversion_not_metadata_only(self):
        conversion = pipeline.color_normalization_filter({
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "color_range": "pc",
            "color_space": "bt470bg",
            "color_transfer": "bt470bg",
            "color_primaries": "bt470bg",
        })
        self.assertEqual(conversion, (
            "colorspace=ispace=bt470bg:itrc=bt470bg:iprimaries=bt470bg:"
            "irange=pc:all=bt709:range=tv:format=yuv420p:fast=0:dither=fsb"
        ))
        self.assertNotIn("setparams", conversion)

        measured = {
            "duration": 10.0, "width": 1920, "height": 1080,
            "fps": "30/1", "codec_name": "h264", "pix_fmt": "yuv420p",
            "color_range": "tv", "color_space": "bt709",
            "color_transfer": "bt709", "color_primaries": "bt709",
        }
        with mock.patch.object(pipeline, "run") as execute:
            pipeline.cfr_normalize(
                Path("source.mp4"), Path("."), source_info=measured
            )
        command = execute.call_args.args[0]
        self.assertEqual(
            command[command.index("-filter_threads") + 1], "1"
        )
        self.assertLess(command.index("-filter_threads"), command.index("-i"))
        video_filter = command[command.index("-vf") + 1]
        self.assertTrue(video_filter.startswith("colorspace="))
        self.assertTrue(video_filter.endswith(",fps=30"))

    def test_color_normalization_rejects_unknown_and_hdr_sources(self):
        base = {
            "codec_name": "h264", "pix_fmt": "yuv420p", "color_range": "tv",
            "color_space": "bt709", "color_transfer": "bt709",
            "color_primaries": "bt709",
        }
        mutations = (
            ("color_space", "unknown"),
            ("color_range", "unknown"),
            ("color_transfer", "smpte2084"),
            ("color_transfer", "arib-std-b67"),
            ("color_primaries", "bt2020"),
            ("color_space", "bt2020nc"),
            ("pix_fmt", "gbrp"),
            ("pix_fmt", "yuv420p12le"),
        )
        for key, value in mutations:
            facts = dict(base, **{key: value})
            with self.subTest(key=key, value=value), self.assertRaises(
                    ValueError):
                pipeline.color_normalization_filter(facts)

    def test_color_normalization_has_one_explicit_legacy_sdr_fallback(self):
        untagged = {
            "codec_name": "h264", "pix_fmt": "yuv420p",
            "color_range": "unknown",
            "color_space": "unknown", "color_transfer": "unknown",
            "color_primaries": "unknown",
        }
        self.assertEqual(
            pipeline.color_normalization_mode(untagged),
            "inferred_legacy_untagged_sdr_bt709_tv",
        )
        self.assertEqual(
            pipeline.color_normalization_filter(untagged),
            "colorspace=ispace=bt709:itrc=bt709:iprimaries=bt709:"
            "irange=tv:all=bt709:range=tv:format=yuv420p:"
            "fast=0:dither=fsb",
        )

        rejected = (
            dict(untagged, color_space="bt709"),
            dict(untagged, color_range="pc"),
            dict(untagged, pix_fmt="yuv420p10le"),
            dict(untagged, pix_fmt="gbrp"),
        )
        for facts in rejected:
            with self.subTest(facts=facts), self.assertRaises(ValueError):
                pipeline.color_normalization_filter(facts)

    def test_color_normalization_supports_only_identified_legacy_mjpeg(self):
        camera_mjpeg = {
            "codec_name": "mjpeg", "pix_fmt": "yuvj420p",
            "color_range": "pc", "color_space": "bt470bg",
            "color_transfer": "unknown", "color_primaries": "unknown",
        }
        self.assertEqual(
            pipeline.color_normalization_mode(camera_mjpeg),
            "inferred_legacy_mjpeg_bt601_full_range",
        )
        self.assertEqual(
            pipeline.color_normalization_filter(camera_mjpeg),
            "colorspace=ispace=bt470bg:itrc=bt470bg:"
            "iprimaries=bt470bg:irange=pc:all=bt709:range=tv:"
            "format=yuv420p:fast=0:dither=fsb",
        )
        rejected = (
            dict(camera_mjpeg, codec_name="h264"),
            dict(camera_mjpeg, color_space="unknown"),
            dict(camera_mjpeg, color_range="tv"),
            dict(camera_mjpeg, pix_fmt="yuv420p"),
            dict(camera_mjpeg, color_transfer="smpte2084"),
        )
        for facts in rejected:
            with self.subTest(facts=facts), self.assertRaises(ValueError):
                pipeline.color_normalization_filter(facts)

    def test_incomplete_semantic_judgment_blocks_cut_implicated_sentence(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            script = work / "script.txt"
            tokens = "one two three four five six seven eight nine ten"
            script.write_text(tokens + ".")
            final_words = [
                {"w": word, "s": i * 0.4, "e": i * 0.4 + 0.25, "p": 0.99}
                for i, word in enumerate(tokens.split()[:8])
            ]
            old_llm_json = providers.llm_json
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = [(1.5, 0.5)]
            providers.llm_json = lambda *args, **kwargs: {"verdicts": []}
            try:
                result = pipeline.script_integrity(final_words, script, work)
            finally:
                providers.llm_json = old_llm_json
                pipeline.CUT_BOUNDARIES = old_boundaries
        self.assertFalse(result["ok"])
        self.assertEqual(result["judge"], "mechanical")
        self.assertEqual(len(result["damaged"]), 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg and ffprobe are required")
    def test_integer_cut_graph_keeps_stream_durations_aligned(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "input.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-f", "lavfi", "-i",
                "anoisesrc=color=white:sample_rate=48000:duration=3:seed=7",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", str(src),
            ], check=True)
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = []
            try:
                out = pipeline.apply_cuts(
                    src,
                    [{"s": 0.067, "e": 0.133},
                     {"s": 0.267, "e": 0.333}],
                    work,
                )
            finally:
                pipeline.CUT_BOUNDARIES = old_boundaries
            probe = subprocess.run([
                pipeline.FFPROBE, "-v", "error",
                "-show_entries", "stream=codec_type,duration",
                "-of", "json", str(out),
            ], check=True, capture_output=True, text=True)
            streams = json.loads(probe.stdout)["streams"]
            video = next(float(s["duration"]) for s in streams
                         if s["codec_type"] == "video")
            audio = next(float(s["duration"]) for s in streams
                         if s["codec_type"] == "audio")
            self.assertLessEqual(abs(video - audio), 0.002)


if __name__ == "__main__":
    unittest.main()
