from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "packaging" / "stage_electron_chromium_provenance.py"
SPEC = importlib.util.spec_from_file_location("electron_chromium_provenance", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load Electron Chromium provenance module")
provenance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = provenance
SPEC.loader.exec_module(provenance)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ElectronChromiumProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.version = "1.2.3"
        self.chrome_version = "2.3.4"
        self.electron_license = b"Electron fixture license\n"
        self.chromium_licenses = b"Chromium fixture licenses\n"
        self.chrome_about = b"Chrome fixture about\n"
        self.chrome_license = b"Chrome fixture license\n"

        self.electron_archive = self.root / f"electron-v{self.version}.zip"
        with zipfile.ZipFile(self.electron_archive, "w") as bundle:
            bundle.writestr("LICENSE", self.electron_license)
            bundle.writestr("LICENSES.chromium.html", self.chromium_licenses)
            bundle.writestr("version", self.version.encode("ascii"))

        self.chrome_archives = {}
        chrome_targets = {
            "mac-arm64": ("chrome-headless-shell-mac-arm64", "chrome-headless-shell"),
            "mac-x64": ("chrome-headless-shell-mac-x64", "chrome-headless-shell"),
            "windows-x64": ("chrome-headless-shell-win64", "chrome-headless-shell.exe"),
        }
        for target, (archive_root, binary) in chrome_targets.items():
            archive = self.root / f"chrome-{target}.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                executable = zipfile.ZipInfo(f"{archive_root}/{binary}")
                executable.external_attr = 0o100755 << 16
                bundle.writestr(
                    executable,
                    "#!/bin/sh\nprintf '%s\\n' "
                    f"'Google Chrome for Testing {self.chrome_version}'\n",
                )
                bundle.writestr(f"{archive_root}/ABOUT", self.chrome_about)
                bundle.writestr(
                    f"{archive_root}/LICENSE.headless_shell", self.chrome_license
                )
            self.chrome_archives[target] = archive

        electron_archive_bytes = self.electron_archive.read_bytes()
        checksums = {
            f"electron-v{self.version}-darwin-arm64.zip": sha256(
                electron_archive_bytes
            ),
            f"electron-v{self.version}-darwin-x64.zip": sha256(
                electron_archive_bytes
            ),
            f"electron-v{self.version}-win32-x64.zip": sha256(
                electron_archive_bytes
            ),
        }
        self.checksums_bytes = json.dumps(
            checksums, sort_keys=True, separators=(",", ":")
        ).encode()
        package_json = json.dumps({
            "license": "MIT",
            "repository": "https://github.com/electron/electron",
            "version": self.version,
        }, sort_keys=True).encode()
        npm_members = {
            "package/LICENSE": self.electron_license,
            "package/checksums.json": self.checksums_bytes,
            "package/package.json": package_json,
        }
        self.npm_archive = self.root / f"electron-{self.version}.tgz"
        with tarfile.open(self.npm_archive, "w:gz") as bundle:
            for name, data in npm_members.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))

        self.electron_root = self.root / "node_modules" / "electron"
        self.electron_root.mkdir(parents=True)
        (self.electron_root / "package.json").write_bytes(package_json)
        (self.electron_root / "LICENSE").write_bytes(self.electron_license)
        (self.electron_root / "checksums.json").write_bytes(self.checksums_bytes)

        npm_bytes = self.npm_archive.read_bytes()
        target_names = {
            "mac-arm64": f"electron-v{self.version}-darwin-arm64.zip",
            "mac-x64": f"electron-v{self.version}-darwin-x64.zip",
            "windows-x64": f"electron-v{self.version}-win32-x64.zip",
        }
        electron_archives = {
            target: {
                "bytes": len(electron_archive_bytes),
                "filename": filename,
                "sha256": sha256(electron_archive_bytes),
                "url": f"https://example.invalid/electron/v{self.version}/{filename}",
            }
            for target, filename in target_names.items()
        }
        chrome_archive_roots = {
            "mac-arm64": (
                "chrome-headless-shell-mac-arm64",
                "chrome-headless-shell-mac",
                "chrome-headless-shell",
            ),
            "mac-x64": (
                "chrome-headless-shell-mac-x64",
                "chrome-headless-shell-mac",
                "chrome-headless-shell",
            ),
            "windows-x64": (
                "chrome-headless-shell-win64",
                "chrome-headless-shell-win64",
                "chrome-headless-shell.exe",
            ),
        }
        chrome_archives = {}
        for target, archive in self.chrome_archives.items():
            archive_root, stage_root, binary = chrome_archive_roots[target]
            archive_bytes = archive.read_bytes()
            filename = archive.name
            chrome_archives[target] = {
                "archive_root": archive_root,
                "binary": binary,
                "bytes": len(archive_bytes),
                "filename": filename,
                "sha256": sha256(archive_bytes),
                "stage_root": stage_root,
                "url": (
                    f"https://example.invalid/chrome/{self.chrome_version}/"
                    f"{filename}"
                ),
            }
        notice = lambda member, output, data: {
            "archive_member": member,
            "bytes": len(data),
            "output_filename": output,
            "sha256": sha256(data),
        }
        self.lock = {
            "chrome_headless_shell": {
                "archives": chrome_archives,
                "cft_revision": "123456",
                "notices": {
                    target_os: {
                        "about": notice(
                            "ABOUT", "Chrome-Headless-Shell-ABOUT.txt",
                            self.chrome_about,
                        ),
                        "license": notice(
                            "LICENSE.headless_shell",
                            "Chrome-Headless-Shell-LICENSE.txt",
                            self.chrome_license,
                        ),
                    }
                    for target_os in ("mac", "windows")
                },
                "source": {
                    "commit": "6" * 40,
                    "repository": (
                        "https://chromium.googlesource.com/chromium/src.git"
                    ),
                    "tag": self.chrome_version,
                },
                "version": self.chrome_version,
                "version_output": (
                    f"Google Chrome for Testing {self.chrome_version}"
                ),
            },
            "electron": {
                "archives": electron_archives,
                "chromium": {
                    "commit": "5" * 40,
                    "repository": (
                        "https://chromium.googlesource.com/chromium/src.git"
                    ),
                    "tag": "10.0.0.0",
                    "version": "10.0.0.0",
                },
                "notices": {
                    "chromium_licenses": {
                        target_os: notice(
                            "LICENSES.chromium.html",
                            "Electron-LICENSES.chromium.html",
                            self.chromium_licenses,
                        )
                        for target_os in ("mac", "windows")
                    },
                    "license": notice(
                        "LICENSE", "Electron-LICENSE.txt", self.electron_license
                    ),
                },
                "npm_package": {
                    "bytes": len(npm_bytes),
                    "filename": self.npm_archive.name,
                    "integrity": "sha512-" + base64.b64encode(
                        hashlib.sha512(npm_bytes).digest()
                    ).decode("ascii"),
                    "members": {
                        name: {"bytes": len(data), "sha256": sha256(data)}
                        for name, data in npm_members.items()
                    },
                    "resolved": (
                        f"https://registry.npmjs.org/electron/-/"
                        f"{self.npm_archive.name}"
                    ),
                    "sha256": sha256(npm_bytes),
                },
                "source": {
                    "commit": "1" * 40,
                    "deps_blob": "2" * 40,
                    "repository": "https://github.com/electron/electron.git",
                    "tag": f"v{self.version}",
                    "tag_object": "3" * 40,
                    "tree": "4" * 40,
                },
                "version": self.version,
            },
            "provenance_status": "complete",
            "schema": provenance.LOCK_SCHEMA,
        }
        self.lock_path = self.root / "provenance.lock.json"
        self._write_lock()
        npm_record = self.lock["electron"]["npm_package"]
        self.desktop_lock = self.root / "package-lock.json"
        self.desktop_lock.write_text(json.dumps({
            "packages": {
                "": {"devDependencies": {"electron": self.version}},
                "node_modules/electron": {
                    "integrity": npm_record["integrity"],
                    "resolved": npm_record["resolved"],
                    "version": self.version,
                },
            }
        }))

    def tearDown(self):
        self.temporary.cleanup()

    def _write_lock(self) -> None:
        self.lock_path.write_bytes(provenance._canonical_json(self.lock))

    def _stage(self, product="helper") -> tuple[Path, Path]:
        licenses = self.root / f"{product}-licenses"
        browser = self.root / f"{product}-browser"
        provenance.stage(
            lock_path=self.lock_path,
            desktop_package_lock=self.desktop_lock,
            electron_root=self.electron_root,
            licenses=licenses,
            product=product,
            target_os="mac",
            target_arch="arm64",
            browser_dir=browser if product == "helper" else None,
            npm_package_archive=self.npm_archive,
            electron_archive=self.electron_archive,
            chrome_archive=(
                self.chrome_archives["mac-arm64"]
                if product == "helper" else None
            ),
        )
        return licenses, browser

    def test_actual_lock_pins_current_release_identity(self):
        lock = provenance.load_lock(
            ROOT / "packaging" / "electron-chromium-provenance.lock.json"
        )
        self.assertEqual(lock["electron"]["version"], "43.3.0")
        self.assertEqual(
            lock["electron"]["source"]["commit"],
            "1aa21d231aeaf5634880a6e60187256e9f2fd4f9",
        )
        self.assertEqual(
            lock["electron"]["chromium"]["commit"],
            "69bf1c67cb894365d151bd020bb0171fd583633a",
        )
        self.assertEqual(lock["chrome_headless_shell"]["version"], "152.0.7928.2")
        self.assertEqual(
            lock["chrome_headless_shell"]["source"]["commit"],
            "8e122fd6ce1b7bb7bcef0fd0b2e96018ff110c4d",
        )
        self.assertEqual(
            set(lock["electron"]["archives"]),
            {"mac-arm64", "mac-x64", "windows-x64"},
        )
        self.assertEqual(
            set(lock["chrome_headless_shell"]["archives"]),
            {"mac-arm64", "mac-x64", "windows-x64"},
        )
        self.assertEqual(
            {
                target: record["sha256"]
                for target, record in lock["electron"]["archives"].items()
            },
            {
                "mac-arm64": (
                    "ee939d1564d83d61032b3b3cb23af4e46005a4900c91f0695f7ed793f0ce6e83"
                ),
                "mac-x64": (
                    "7347bbd5fb529eea64f9c2d148bb1c19222d98946ff234ffe27953a1bbcb9dae"
                ),
                "windows-x64": (
                    "18528bedc6a9b04bdc5efb7b803cbc3cb0e5ea6415d54046e23d464d89a00da9"
                ),
            },
        )
        self.assertEqual(
            {
                target: record["sha256"]
                for target, record in lock["chrome_headless_shell"][
                    "archives"
                ].items()
            },
            {
                "mac-arm64": (
                    "e4ca218c9cb2da2117cabd1ca4a2318a9a80efffbba242045be68d708ce3a5ed"
                ),
                "mac-x64": (
                    "3b4e27aa52345a4177f0b69211ef3e70476cfab156f75d7c3dc11342ef488ae2"
                ),
                "windows-x64": (
                    "ec7d7cfbc9d97093c9269d6a26de78a3244a49f3112ff9616e2ccb5ac3afeb24"
                ),
            },
        )
        self.assertEqual(
            lock["electron"]["npm_package"]["sha256"],
            "581b6b729df7582407aca4817e71078e815bb96de764185276a8fd15b5905399",
        )

    def test_helper_stages_exact_notices_browser_and_receipt(self):
        licenses, browser = self._stage()
        provenance.verify_staged_notices(
            licenses,
            provenance.load_lock(self.lock_path),
            product="helper",
            target_os="mac",
            target_arch="arm64",
        )
        self.assertEqual(
            set(path.name for path in licenses.iterdir()),
            set(provenance.required_notice_names("helper")),
        )
        executable = browser / "chrome-headless-shell-mac" / "chrome-headless-shell"
        self.assertTrue(executable.is_file())
        self.assertTrue(executable.stat().st_mode & 0o100)
        receipt = json.loads(
            (licenses / provenance.RECEIPT_FILENAME).read_text()
        )
        self.assertEqual(receipt["product"], "helper")
        self.assertEqual(receipt["target"], {"arch": "arm64", "os": "mac"})

    def test_pse_stages_only_electron_and_embedded_chromium_notices(self):
        licenses, browser = self._stage(product="pse")
        self.assertFalse(browser.exists())
        self.assertEqual(
            set(path.name for path in licenses.iterdir()),
            set(provenance.required_notice_names("pse")),
        )
        receipt = json.loads(
            (licenses / provenance.RECEIPT_FILENAME).read_text()
        )
        self.assertNotIn("chrome_headless_shell", receipt)

    def test_same_version_repacked_archives_fail_closed(self):
        repacked = self.root / "repacked-electron.zip"
        repacked.write_bytes(self.electron_archive.read_bytes() + b"tampered")
        with self.assertRaisesRegex(
            provenance.ProvenanceError, "size drifted|SHA-256 drifted"
        ):
            provenance.stage(
                lock_path=self.lock_path,
                desktop_package_lock=self.desktop_lock,
                electron_root=self.electron_root,
                licenses=self.root / "repacked-licenses",
                product="pse",
                target_os="mac",
                target_arch="arm64",
                browser_dir=None,
                npm_package_archive=self.npm_archive,
                electron_archive=repacked,
            )

    def test_notice_tampering_breaks_receipt_verification(self):
        licenses, _ = self._stage()
        (licenses / "Electron-LICENSE.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(provenance.ProvenanceError, "size drifted"):
            provenance.verify_staged_notices(
                licenses,
                provenance.load_lock(self.lock_path),
                product="helper",
                target_os="mac",
                target_arch="arm64",
            )

    def test_unsafe_chrome_archive_path_is_rejected(self):
        unsafe = self.root / "unsafe-chrome.zip"
        archive_root = "chrome-headless-shell-mac-arm64"
        with zipfile.ZipFile(unsafe, "w") as bundle:
            executable = zipfile.ZipInfo(f"{archive_root}/chrome-headless-shell")
            executable.external_attr = 0o100755 << 16
            bundle.writestr(
                executable,
                "#!/bin/sh\nprintf '%s\\n' "
                f"'Google Chrome for Testing {self.chrome_version}'\n",
            )
            bundle.writestr(f"{archive_root}/ABOUT", self.chrome_about)
            bundle.writestr(
                f"{archive_root}/LICENSE.headless_shell", self.chrome_license
            )
            bundle.writestr(f"{archive_root}/../escape", b"escape")
        record = self.lock["chrome_headless_shell"]["archives"]["mac-arm64"]
        record["bytes"] = unsafe.stat().st_size
        record["filename"] = unsafe.name
        record["sha256"] = sha256(unsafe.read_bytes())
        record["url"] = (
            f"https://example.invalid/chrome/{self.chrome_version}/{unsafe.name}"
        )
        self._write_lock()
        with self.assertRaisesRegex(provenance.ProvenanceError, "unsafe path"):
            provenance.stage(
                lock_path=self.lock_path,
                desktop_package_lock=self.desktop_lock,
                electron_root=self.electron_root,
                licenses=self.root / "unsafe-licenses",
                product="helper",
                target_os="mac",
                target_arch="arm64",
                browser_dir=self.root / "unsafe-browser",
                npm_package_archive=self.npm_archive,
                electron_archive=self.electron_archive,
                chrome_archive=unsafe,
            )

    def test_lock_and_desktop_dependency_drift_are_rejected(self):
        changed = copy.deepcopy(self.lock)
        changed["provenance_status"] = "pending"
        with self.assertRaisesRegex(provenance.ProvenanceError, "must be complete"):
            provenance.validate_lock(changed)

        desktop = json.loads(self.desktop_lock.read_text())
        desktop["packages"][""]["devDependencies"]["electron"] = "9.9.9"
        self.desktop_lock.write_text(json.dumps(desktop))
        with self.assertRaisesRegex(provenance.ProvenanceError, "not exact"):
            provenance.verify_desktop_package_lock(
                self.desktop_lock, provenance.load_lock(self.lock_path)
            )

    def test_existing_manifest_receipt_binds_notice_bytes(self):
        licenses, _ = self._stage()
        generator_path = ROOT / "packaging" / "generate_helper_manifest.py"
        generator_spec = importlib.util.spec_from_file_location(
            "helper_manifest_generator_for_provenance", generator_path
        )
        self.assertIsNotNone(generator_spec)
        self.assertIsNotNone(generator_spec.loader)
        generator = importlib.util.module_from_spec(generator_spec)
        generator_spec.loader.exec_module(generator)
        before = generator.directory_receipt(licenses)
        (licenses / "Electron-LICENSE.txt").write_bytes(b"changed")
        after = generator.directory_receipt(licenses)
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
