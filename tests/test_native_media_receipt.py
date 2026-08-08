from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "native_media_receipt.py"
SPEC = importlib.util.spec_from_file_location("native_media_receipt", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load native media receipt module: {SCRIPT}")
receipt = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = receipt
SPEC.loader.exec_module(receipt)


class NativeMediaReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.production_remotion_inventory_after = (
            receipt.REMOTION_INVENTORY_SHA256_AFTER
        )
        self.production_onnx_inventory = dict(
            receipt.ONNX_NATIVE_INVENTORY
        )

    def tearDown(self) -> None:
        receipt.REMOTION_INVENTORY_SHA256_AFTER = (
            self.production_remotion_inventory_after
        )
        receipt.ONNX_NATIVE_INVENTORY = dict(
            self.production_onnx_inventory
        )

    @staticmethod
    def _pe64(
        payload: bytes = b"native-media", *, dll: bool = False
    ) -> bytes:
        """Build a bounded one-section PE32+ fixture, not a magic-only stub."""
        data = bytearray(0x400)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into(
            "<HHIIIHH",
            data,
            0x84,
            receipt.PE_MACHINE_AMD64,
            1,
            0,
            0,
            0,
            0xF0,
            0x2022 if dll else 0x0022,
        )
        optional = 0x98
        struct.pack_into("<H", data, optional, 0x20B)
        struct.pack_into("<I", data, optional + 16, 0x1000)
        struct.pack_into("<I", data, optional + 32, 0x1000)
        struct.pack_into("<I", data, optional + 36, 0x200)
        struct.pack_into("<I", data, optional + 56, 0x2000)
        struct.pack_into("<I", data, optional + 60, 0x200)
        struct.pack_into("<I", data, optional + 108, 16)
        section = optional + 0xF0
        data[section:section + 8] = b".text\0\0\0"
        struct.pack_into("<I", data, section + 8, 0x200)
        struct.pack_into("<I", data, section + 12, 0x1000)
        struct.pack_into("<I", data, section + 16, 0x200)
        struct.pack_into("<I", data, section + 20, 0x200)
        struct.pack_into("<I", data, section + 36, 0x60000020)
        data[0x200:0x200 + min(len(payload), 0x200)] = payload[:0x200]
        return bytes(data)

    @staticmethod
    def _macho64(
        cpu_type: int,
        payload: bytes = b"native-media",
        *,
        file_type: int = receipt.MH_EXECUTE,
    ) -> bytes:
        """Build a bounded 64-bit Mach-O fixture with one load command."""
        command_size = 152
        header = struct.pack(
            "<IIIIIIII",
            0xFEEDFACF,
            cpu_type,
            0,
            file_type,
            1,
            command_size,
            0,
            0,
        )
        total_size = len(header) + command_size + len(payload)
        segment = struct.pack(
            "<II16sQQQQIIII",
            0x19,
            command_size,
            b"__TEXT".ljust(16, b"\0"),
            0,
            total_size,
            0,
            total_size,
            7,
            5,
            1,
            0,
        )
        section = struct.pack(
            "<16s16sQQIIIIIIII",
            b"__text".ljust(16, b"\0"),
            b"__TEXT".ljust(16, b"\0"),
            len(header) + command_size,
            len(payload),
            len(header) + command_size,
            0,
            0,
            0,
            0x80000400,
            0,
            0,
            0,
        )
        return header + segment + section + payload

    @staticmethod
    def _entry(
        component: str,
        lineage: str,
        manifest: str = "a" * 64,
    ) -> dict[str, str]:
        return {
            "component": component,
            "lineage_id": lineage,
            "source_manifest_sha256": manifest,
        }

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _load(
        self,
        path: Path,
        platform: str,
        expected_digest: str | None = None,
    ):
        digest = expected_digest if expected_digest is not None else self._digest(path)
        return receipt.load_allowlist(path, platform, digest)

    @staticmethod
    def _scan(app_root: Path, platform: str, allowlist):
        return receipt.scan_app(
            app_root, platform, allowlist, allowlist.sha256
        )

    @staticmethod
    def _verify(app_root: Path, platform: str, allowlist, receipt_path: Path):
        return receipt.verify_app(
            app_root,
            platform,
            allowlist,
            receipt_path,
            allowlist.sha256,
        )

    def _write_allowlist(
        self,
        root: Path,
        platform: str,
        scan_roots: list[str],
        files: dict[str, dict[str, str]],
        *,
        raw: str | None = None,
        name: str = "allowlist.json",
    ) -> Path:
        path = root / name
        if raw is None:
            raw = json.dumps({
                "schema": receipt.ALLOWLIST_SCHEMA,
                "platform": platform,
                "scan_roots": scan_roots,
                "files": files,
            })
        path.write_text(raw, encoding="utf-8")
        return path

    def _entry_for_path(
        self, platform: str, relative: str, index: int
    ) -> dict[str, str]:
        component = receipt._component_for_path(relative, platform)
        contract = receipt.PLATFORM_COMPONENT_RULES[platform].get(component, {})
        lineage = contract.get("lineage_id", f"fixture:{component}:{platform}")
        manifest = f"{index % 16:x}" * 64
        return self._entry(component, lineage, manifest)

    def _required_paths(self, platform: str) -> set[str]:
        paths: set[str] = set()
        for contract in receipt.PLATFORM_COMPONENT_RULES[platform].values():
            paths.update(contract.get("required_all", ()))
            for alternatives in contract.get("required_any", ()):
                paths.add(alternatives[-1])
        return paths

    def _write_native_files(
        self,
        app_root: Path,
        platform: str,
        files: dict[str, dict[str, str]],
    ) -> None:
        cpu_type = (
            receipt.PE_MACHINE_AMD64
            if platform == "windows-x64"
            else receipt.PLATFORM_RULES[platform]["machine"]
        )
        for index, relative in enumerate(files):
            path = app_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            roles = receipt._expected_binary_roles(relative, platform)
            if platform == "windows-x64":
                data = self._pe64(
                    bytes([index % 256]), dll=roles == {"library"}
                )
            else:
                file_type = (
                    receipt.MH_EXECUTE
                    if roles == {"executable"}
                    else receipt.MH_BUNDLE
                    if "bundle" in roles
                    else receipt.MH_DYLIB
                )
                data = self._macho64(
                    cpu_type,
                    bytes([index % 256]),
                    file_type=file_type,
                )
            path.write_bytes(data)

    @staticmethod
    def _write_remotion_prune_receipt(app_root: Path) -> str:
        path = app_root / receipt.REMOTION_PRUNE_RECEIPT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            json.dumps(
                receipt._expected_remotion_prune_receipt(),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _write_onnx_prune_receipt(app_root: Path, platform: str) -> str:
        path = app_root / receipt._onnx_prune_receipt_path(platform)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            json.dumps(
                receipt._expected_onnx_prune_receipt(platform),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def _prepare_onnx_fixture(
        self,
        app_root: Path,
        platform: str,
        files: dict[str, dict[str, str]],
    ) -> None:
        receipt.ONNX_NATIVE_INVENTORY = dict(
            self.production_onnx_inventory
        )
        package_root = receipt._onnx_package_root(platform)
        native_prefix = f"{package_root}/bin/napi-v3/"
        for relative, metadata in files.items():
            if metadata["component"] != "onnxruntime-node":
                continue
            inventory_path = relative[len(native_prefix):]
            receipt.ONNX_NATIVE_INVENTORY[inventory_path] = self._digest(
                app_root / relative
            )
        prune_receipt_sha = self._write_onnx_prune_receipt(
            app_root, platform
        )
        for metadata in files.values():
            if metadata["component"] == "onnxruntime-node":
                metadata["source_manifest_sha256"] = prune_receipt_sha

    @staticmethod
    def _package_inventory_digest(package_root: Path) -> str:
        inventory = {
            path.relative_to(package_root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in package_root.rglob("*")
            if path.is_file()
        }
        digest = hashlib.sha256()
        for relative, file_sha256 in sorted(inventory.items()):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(file_sha256))
        return digest.hexdigest()

    def _windows_app(
        self, root: Path
    ) -> tuple[Path, list[str], dict[str, dict[str, str]]]:
        platform = "windows-x64"
        app_root = root / "AutoEditor Helper"
        paths = self._required_paths(platform)
        paths.update({
            "resources/lib/avcodec-62.dll",
            (
                "resources/browser/chrome-headless-shell-win64/"
                "libEGL.dll"
            ),
            "AutoEditor Helper.exe",
        })
        files = {
            relative: self._entry_for_path(platform, relative, index)
            for index, relative in enumerate(sorted(paths), 1)
        }
        self._write_native_files(app_root, platform, files)
        self._prepare_onnx_fixture(app_root, platform, files)
        remotion_root = app_root / receipt.PLATFORM_COMPONENT_RULES[
            platform
        ]["remotion"]["roots"][0]
        for name in (
            "README.md",
            "index.d.ts",
            "index.js",
            "index.mjs",
            "package.json",
        ):
            (remotion_root / name).write_text(
                f"fixture:{name}\n", encoding="utf-8"
            )
        receipt.REMOTION_INVENTORY_SHA256_AFTER = (
            self._package_inventory_digest(remotion_root)
        )
        prune_receipt_sha = self._write_remotion_prune_receipt(app_root)
        for metadata in files.values():
            if metadata["component"] == "remotion":
                metadata["source_manifest_sha256"] = prune_receipt_sha
        (app_root / "resources/engine").mkdir(parents=True, exist_ok=True)
        (app_root / "resources/helper").mkdir(parents=True, exist_ok=True)
        return app_root, ["."], files

    def _mac_app(
        self,
        root: Path,
        platform: str = "mac-arm64",
    ) -> tuple[Path, list[str], dict[str, dict[str, str]]]:
        app_root = root / "AutoEditor Helper.app"
        rules = receipt.PLATFORM_COMPONENT_RULES[platform]
        paths = self._required_paths(platform)
        paths.add(
            "Contents/Resources/browser/chrome-headless-shell-mac/"
            "libEGL.dylib"
        )
        files = {
            relative: self._entry_for_path(platform, relative, index)
            for index, relative in enumerate(sorted(paths), 1)
        }
        self._write_native_files(app_root, platform, files)
        self._prepare_onnx_fixture(app_root, platform, files)
        remotion_root = rules["remotion"]["roots"][0]
        notes = app_root / remotion_root / "README.md"
        notes.write_text("not a native binary", encoding="utf-8")
        (app_root / "Contents/Resources/engine").mkdir(
            parents=True, exist_ok=True
        )
        (app_root / "Contents/Resources/helper").mkdir(
            parents=True, exist_ok=True
        )
        scan_roots = sorted({
            "Contents/Resources/bin",
            "Contents/Resources/engine",
            "Contents/Resources/helper",
            "Contents/Resources/lib",
            *rules["remotion"]["roots"],
            *rules["onnxruntime-node"]["roots"],
            *rules["browser"]["roots"],
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/A/"
                "Libraries"
            ),
        })
        return app_root, scan_roots, files

    def test_scan_cli_writes_canonical_digest_bound_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            platform = "mac-arm64"
            app_root, scan_roots, files = self._mac_app(root, platform)
            allowlist_path = self._write_allowlist(
                root,
                platform,
                scan_roots,
                dict(reversed(tuple(files.items()))),
            )
            allowlist_sha = self._digest(allowlist_path)
            output = root / "receipt.json"

            argv = [
                str(SCRIPT),
                "scan",
                "--app-root", str(app_root),
                "--platform", platform,
                "--allowlist", str(allowlist_path),
                "--expected-allowlist-sha256", allowlist_sha,
                "--output", str(output),
            ]
            with mock.patch.object(sys, "argv", argv):
                receipt.main()
            raw = output.read_bytes()
            payload = json.loads(raw)
            self.assertEqual(raw, receipt.canonical_json_bytes(payload))
            self.assertEqual(payload["schema"], receipt.RECEIPT_SCHEMA)
            self.assertEqual(payload["platform"], platform)
            self.assertEqual(payload["allowlist_sha256"], allowlist_sha)
            self.assertEqual(payload["scan_roots"], scan_roots)
            self.assertEqual(
                [item["path"] for item in payload["files"]], sorted(files)
            )
            for item in payload["files"]:
                path = app_root / item["path"]
                self.assertEqual(item["bytes"], path.stat().st_size)
                self.assertEqual(
                    item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
                )
                self.assertEqual(
                    item["lineage_id"], files[item["path"]]["lineage_id"]
                )
                self.assertEqual(
                    item["component"], files[item["path"]]["component"]
                )

            loaded = self._load(allowlist_path, platform)
            second = self._scan(app_root, platform, loaded)
            self.assertEqual(raw, receipt.canonical_json_bytes(second))

    def test_cli_requires_digest_and_documents_external_attestation_gate(self):
        help_run = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        self.assertIn("signed attestation", help_run.stdout)

        scan_help = subprocess.run(
            [sys.executable, str(SCRIPT), "scan", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(scan_help.returncode, 0, scan_help.stderr)
        self.assertIn("--expected-allowlist-sha256", scan_help.stdout)

    def test_discovers_all_required_components_and_nested_browser_siblings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            scanned = self._scan(
                app_root, "windows-x64", self._load(path, "windows-x64")
            )
            by_component = {
                item["component"] for item in scanned["files"]
            }
            self.assertTrue(receipt.REQUIRED_COMPONENTS <= by_component)
            self.assertIn(
                "resources/browser/chrome-headless-shell-win64/libEGL.dll",
                {item["path"] for item in scanned["files"]},
            )

        for platform in ("mac-arm64", "mac-x64"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app_root, scan_roots, files = self._mac_app(root, platform)
                path = self._write_allowlist(
                    root, platform, scan_roots, files
                )
                scanned = self._scan(
                    app_root, platform, self._load(path, platform)
                )
                self.assertTrue(
                    receipt.REQUIRED_COMPONENTS
                    <= {item["component"] for item in scanned["files"]}
                )
                self.assertIn(
                    "Contents/Resources/browser/chrome-headless-shell-mac/"
                    "libEGL.dylib",
                    {item["path"] for item in scanned["files"]},
                )

    def test_verify_accepts_exact_app_and_rejects_hash_or_size_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")
            expected = self._scan(app_root, "windows-x64", allowlist)
            receipt_path = root / "receipt.json"
            receipt_path.write_bytes(receipt.canonical_json_bytes(expected))
            self.assertEqual(
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                ),
                expected,
            )

            changed = app_root / "resources/bin/ffmpeg.exe"
            changed.write_bytes(self._pe64(b"changed-and-longer"))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "hash/size drift"
            ):
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                )

    def test_missing_extra_and_unexpected_nested_native_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")

            ffprobe = app_root / "resources/bin/ffprobe.exe"
            ffprobe.unlink()
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                r"missing native media paths: resources/bin/ffprobe\.exe",
            ):
                self._scan(app_root, "windows-x64", allowlist)

            ffprobe.write_bytes(self._pe64())
            nonnative = app_root / "resources/engine/_internal/ignored.node"
            nonnative.parent.mkdir(parents=True, exist_ok=True)
            nonnative.write_text("plain text", encoding="utf-8")
            self._scan(app_root, "windows-x64", allowlist)

            unexpected = app_root / (
                "resources/browser/chrome-headless-shell-win64/unexpected.data"
            )
            unexpected.write_bytes(self._pe64(dll=True))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                r"extra native media paths: .*unexpected\.data",
            ):
                self._scan(app_root, "windows-x64", allowlist)

    def test_symlink_special_entry_and_bad_scan_root_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")
            target = root / "outside.txt"
            target.write_text("outside", encoding="utf-8")
            link = app_root / "resources/engine/linked.txt"
            link.symlink_to(target)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "symlink"
            ):
                self._scan(app_root, "windows-x64", allowlist)

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app_root, scan_roots, files = self._windows_app(root)
                path = self._write_allowlist(
                    root, "windows-x64", scan_roots, files
                )
                special = app_root / "resources/engine/pipe"
                os.mkfifo(special)
                with self.assertRaisesRegex(
                    receipt.NativeMediaReceiptError, "non-file"
                ):
                    self._scan(
                        app_root, "windows-x64", self._load(path, "windows-x64")
                    )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._mac_app(root)
            scan_root_file = app_root / "Contents/not-a-directory"
            scan_root_file.write_text("file", encoding="utf-8")
            bad = self._write_allowlist(
                root,
                "mac-arm64",
                [*scan_roots, "Contents/not-a-directory"],
                files,
            )
            allowlist = self._load(bad, "mac-arm64")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "scan root is not a directory",
            ):
                self._scan(app_root, "mac-arm64", allowlist)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, _, files = self._windows_app(root)
            linked_root = root / "linked-app"
            linked_root.symlink_to(app_root, target_is_directory=True)
            full = self._write_allowlist(
                root, "windows-x64", ["."], files, name="full.json"
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "final app root must not be a symlink",
            ):
                self._scan(
                    linked_root,
                    "windows-x64",
                    self._load(full, "windows-x64"),
                )

    @unittest.skipIf(os.name == "nt", "POSIX openat race regression")
    def test_directory_swap_to_symlink_during_walk_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")
            engine = app_root / "resources/engine"
            raced = engine / "raced-directory"
            raced.mkdir()
            (raced / "plain.txt").write_text("inside", encoding="utf-8")
            outside = root / "outside"
            outside.mkdir()
            (outside / "plain.txt").write_text("outside", encoding="utf-8")
            original = engine / "raced-directory-original"
            engine_identity = (engine.stat().st_dev, engine.stat().st_ino)
            real_listdir = receipt.os.listdir
            swapped = False

            def racing_listdir(path):
                nonlocal swapped
                names = real_listdir(path)
                if (
                    not swapped
                    and isinstance(path, int)
                    and (
                        os.fstat(path).st_dev,
                        os.fstat(path).st_ino,
                    ) == engine_identity
                ):
                    raced.rename(original)
                    raced.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return names

            with mock.patch.object(
                receipt.os, "listdir", side_effect=racing_listdir
            ), self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "symlink in native media scan root",
            ):
                self._scan(app_root, "windows-x64", allowlist)
            self.assertTrue(swapped)

    def test_scan_roots_are_explicit_safe_nonempty_and_nonoverlapping(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, files = self._windows_app(root)
            cases = (
                ([], "nonempty"),
                (["../resources"], "unsafe scan root"),
                (["/resources"], "unsafe scan root"),
                (["resources\\bin"], "unsafe scan root"),
                (["resources", "resources/bin"], "overlapping scan roots"),
                ([".", "resources"], "overlapping scan roots"),
                (["resources", "Resources"], "casefold collision"),
            )
            for index, (scan_roots, error) in enumerate(cases):
                with self.subTest(scan_roots=scan_roots):
                    path = self._write_allowlist(
                        root,
                        "windows-x64",
                        scan_roots,
                        files,
                        name=f"allowlist-{index}.json",
                    )
                    with self.assertRaisesRegex(
                        receipt.NativeMediaReceiptError, error
                    ):
                        self._load(path, "windows-x64")

            uncovered = self._write_allowlist(
                root,
                "windows-x64",
                ["resources/bin"],
                files,
                name="allowlist-uncovered.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "do not cover mandatory component subtrees",
            ):
                self._load(uncovered, "windows-x64")

    def test_core_only_and_browser_omission_bypasses_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, files = self._windows_app(root)
            core_paths = set(receipt.PLATFORM_RULES["windows-x64"]["core"])
            core_only = {
                relative: metadata
                for relative, metadata in files.items()
                if relative in core_paths
            }
            core_allowlist = self._write_allowlist(
                root,
                "windows-x64",
                ["."],
                core_only,
                name="core-only.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "missing required native media components: "
                "browser, electron, frozen-engine, frozen-helper, "
                "onnxruntime-node, remotion",
            ):
                self._load(core_allowlist, "windows-x64")

            without_browser = {
                relative: metadata
                for relative, metadata in files.items()
                if metadata["component"] != "browser"
            }
            path = self._write_allowlist(
                root, "windows-x64", ["."], without_browser,
                name="no-browser.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "missing required native media components: browser",
            ):
                self._load(path, "windows-x64")

    def test_windows_remotion_requires_pruned_inventory_and_bound_receipt(self):
        self.assertEqual(
            self.production_remotion_inventory_after,
            "77976da929c0744b4503720c070f441702522f30a9ba3c6dacf6abcf70d123f1",
        )
        stale_names = set(receipt.WINDOWS_REMOTION_STALE_NATIVE_SHA256)
        self.assertEqual(
            set(receipt.WINDOWS_REMOTION_NATIVE_NAMES),
            {
                "avcodec-61.dll",
                "avdevice-61.dll",
                "avfilter-10.dll",
                "avformat-61.dll",
                "avutil-59.dll",
                "ffmpeg.exe",
                "ffprobe.exe",
                "libgcc_s_seh-1.dll",
                "libssp-0.dll",
                "libstdc++-6.dll",
                "libvpx-1.dll",
                "libwinpthread-1.dll",
                "msvcr100.dll",
                "remotion.exe",
                "swresample-5.dll",
                "swscale-8.dll",
                "zlib1.dll",
            },
        )
        self.assertEqual(
            stale_names,
            {
                "avcodec-60.dll",
                "avdevice-60.dll",
                "avfilter-9.dll",
                "avformat-60.dll",
                "avutil-58.dll",
                "swresample-4.dll",
                "swscale-7.dll",
            },
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")
            remotion_root = receipt.PLATFORM_COMPONENT_RULES[
                "windows-x64"
            ]["remotion"]["roots"][0]
            for stale_name in stale_names:
                stale = app_root / remotion_root / stale_name
                stale.write_bytes(self._pe64(dll=True))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "final inventory does not match the canonical",
            ):
                self._scan(app_root, "windows-x64", allowlist)

            for stale_name in stale_names:
                (app_root / remotion_root / stale_name).unlink()
            unexpected_text = app_root / remotion_root / "unexpected.txt"
            unexpected_text.write_text("not a PE file", encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "final inventory does not match the canonical",
            ):
                self._scan(app_root, "windows-x64", allowlist)
            unexpected_text.unlink()

            remotion_metadata = next(
                metadata for metadata in files.values()
                if metadata["component"] == "remotion"
            )
            forged = {path: dict(metadata) for path, metadata in files.items()}
            for stale_name in stale_names:
                forged[f"{remotion_root}/{stale_name}"] = dict(
                    remotion_metadata
                )
            forged_path = self._write_allowlist(
                root,
                "windows-x64",
                scan_roots,
                forged,
                name="pre-prune-allowlist.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "disallowed pinned remotion paths",
            ):
                self._load(forged_path, "windows-x64")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")
            prune_receipt = app_root / receipt.REMOTION_PRUNE_RECEIPT_PATH
            prune_receipt.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "pruning receipt SHA256 does not match",
            ):
                self._scan(app_root, "windows-x64", allowlist)

            forged_receipt = receipt._expected_remotion_prune_receipt()
            forged_receipt["package"]["inventorySha256After"] = "0" * 64
            forged_raw = (
                json.dumps(forged_receipt, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "does not match the canonical 4.0.507 post-prune contract",
            ):
                receipt._validate_remotion_prune_receipt(
                    forged_raw, hashlib.sha256(forged_raw).hexdigest()
                )

            self._write_remotion_prune_receipt(app_root)
            changed = {path: dict(metadata) for path, metadata in files.items()}
            target = next(
                path for path, metadata in changed.items()
                if metadata["component"] == "remotion"
            )
            changed[target]["source_manifest_sha256"] = "f" * 64
            changed_path = self._write_allowlist(
                root,
                "windows-x64",
                scan_roots,
                changed,
                name="split-prune-receipt.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "one canonical pruning receipt",
            ):
                self._load(changed_path, "windows-x64")

    def test_onnx_component_is_exact_and_binds_the_v2_prune_receipt(self):
        self.assertEqual(
            receipt.ONNX_CONTRACT_SOURCE_COMMIT,
            "68719fe31df8454a9fecaaa967c8687f2e5df200",
        )
        self.assertEqual(len(self.production_onnx_inventory), 17)
        self.assertEqual(
            {
                platform: len(receipt._expected_onnx_target_inventory(platform))
                for platform in receipt.PLATFORM_RULES
            },
            {"windows-x64": 3, "mac-arm64": 2, "mac-x64": 2},
        )
        producer_path = ROOT / "packaging" / "prune_onnxruntime_node.py"
        if producer_path.exists():
            producer_spec = importlib.util.spec_from_file_location(
                "native_receipt_onnx_contract_producer", producer_path
            )
            self.assertIsNotNone(producer_spec)
            self.assertIsNotNone(producer_spec.loader)
            producer = importlib.util.module_from_spec(producer_spec)
            sys.modules[producer_spec.name] = producer
            producer_spec.loader.exec_module(producer)
            self.assertEqual(
                receipt.ONNX_NATIVE_INVENTORY,
                producer.EXPECTED_NATIVE_INVENTORY,
            )
            self.assertEqual(
                receipt.ONNX_PACKAGE_INTEGRITY,
                producer.EXPECTED_LOCK_ENTRY["integrity"],
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")
            self._scan(app_root, "windows-x64", allowlist)

            onnx_path = next(
                relative for relative, metadata in files.items()
                if metadata["component"] == "onnxruntime-node"
            )
            native = app_root / onnx_path
            original = native.read_bytes()
            native.write_bytes(
                self._pe64(
                    b"drifted-onnx",
                    dll=receipt._expected_binary_roles(
                        onnx_path, "windows-x64"
                    ) == {"library"},
                )
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "native bytes do not match the authenticated",
            ):
                self._scan(app_root, "windows-x64", allowlist)
            native.write_bytes(original)

            unexpected = (
                app_root
                / receipt._onnx_package_root("windows-x64")
                / "bin/napi-v3/win32/x64/unexpected.dll"
            )
            unexpected.write_bytes(self._pe64(dll=True))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "extra native media paths: .*unexpected.dll",
            ):
                self._scan(app_root, "windows-x64", allowlist)
            unexpected.unlink()

            split_files = {
                relative: dict(metadata)
                for relative, metadata in files.items()
            }
            split_target = next(
                relative for relative, metadata in split_files.items()
                if metadata["component"] == "onnxruntime-node"
            )
            split_files[split_target]["source_manifest_sha256"] = "f" * 64
            split_allowlist = self._write_allowlist(
                root,
                "windows-x64",
                scan_roots,
                split_files,
                name="split-onnx-receipt.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "one canonical target-pruning receipt",
            ):
                self._load(split_allowlist, "windows-x64")

            prune_path = app_root / receipt._onnx_prune_receipt_path(
                "windows-x64"
            )
            prune_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "pruning receipt SHA256 does not match",
            ):
                self._scan(app_root, "windows-x64", allowlist)

            forged = json.loads(json.dumps(
                receipt._expected_onnx_prune_receipt("windows-x64")
            ))
            forged["package"]["version"] = "9.9.9"
            forged_raw = (
                json.dumps(forged, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            prune_path.write_bytes(forged_raw)
            forged_sha = hashlib.sha256(forged_raw).hexdigest()
            forged_files = {
                relative: dict(metadata)
                for relative, metadata in files.items()
            }
            for metadata in forged_files.values():
                if metadata["component"] == "onnxruntime-node":
                    metadata["source_manifest_sha256"] = forged_sha
            forged_allowlist = self._write_allowlist(
                root,
                "windows-x64",
                scan_roots,
                forged_files,
                name="forged-onnx-receipt.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "does not match the canonical 1.21.1",
            ):
                self._scan(
                    app_root,
                    "windows-x64",
                    self._load(forged_allowlist, "windows-x64"),
                )

    def test_onnx_whole_package_root_must_be_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._mac_app(root)
            package_root = receipt._onnx_package_root("mac-arm64")
            target_root = (
                f"{package_root}/bin/napi-v3/"
                f"{receipt.ONNX_TARGET_DIRECTORIES['mac-arm64']}"
            )
            narrowed = [
                target_root if scan_root == package_root else scan_root
                for scan_root in scan_roots
            ]
            path = self._write_allowlist(
                root, "mac-arm64", sorted(narrowed), files
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "do not cover mandatory component subtrees",
            ):
                self._load(path, "mac-arm64")

    def test_frozen_runtime_directories_and_executables_are_mandatory(self):
        for component, relative in receipt.FROZEN_RUNTIME_PATHS[
            "windows-x64"
        ].items():
            with self.subTest(component=component), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app_root, scan_roots, files = self._windows_app(root)
                allowlist_path = self._write_allowlist(
                    root, "windows-x64", scan_roots, files
                )
                allowlist = self._load(allowlist_path, "windows-x64")
                shutil.rmtree((app_root / relative).parent)
                with self.assertRaisesRegex(
                    receipt.NativeMediaReceiptError,
                    "cannot inspect scan root",
                ):
                    self._scan(app_root, "windows-x64", allowlist)

            with self.subTest(component=component + "-executable"), \
                    tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app_root, scan_roots, files = self._windows_app(root)
                allowlist_path = self._write_allowlist(
                    root, "windows-x64", scan_roots, files
                )
                allowlist = self._load(allowlist_path, "windows-x64")
                (app_root / relative).unlink()
                with self.assertRaisesRegex(
                    receipt.NativeMediaReceiptError,
                    "missing native media paths: .*autoeditor",
                ):
                    self._scan(app_root, "windows-x64", allowlist)

    def test_frozen_components_own_every_native_in_engine_and_helper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            additions = (
                "resources/engine/_internal/private-extension.node",
                "resources/helper/_internal/private-runtime.dll",
            )
            for index, relative in enumerate(additions, 301):
                metadata = self._entry_for_path(
                    "windows-x64", relative, index
                )
                expected = (
                    "frozen-engine" if "/engine/" in relative
                    else "frozen-helper"
                )
                self.assertEqual(metadata["component"], expected)
                files[relative] = metadata
            self._write_native_files(
                app_root,
                "windows-x64",
                {relative: files[relative] for relative in additions},
            )
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            self._scan(
                app_root, "windows-x64", self._load(path, "windows-x64")
            )

            forged = {
                relative: dict(metadata)
                for relative, metadata in files.items()
            }
            forged[additions[0]] = self._entry(
                "supporting-native", "fixture:supporting-native", "e" * 64
            )
            forged_path = self._write_allowlist(
                root,
                "windows-x64",
                scan_roots,
                forged,
                name="forged-engine-ownership.json",
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "expected frozen-engine",
            ):
                self._load(forged_path, "windows-x64")

    def test_windows_electron_requires_only_root_ffmpeg_dll(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            extra = "libffmpeg.dll"
            (app_root / extra).write_bytes(self._pe64(dll=True))
            files[extra] = self._entry_for_path(
                "windows-x64", extra, 401
            )
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "disallowed pinned electron paths: libffmpeg.dll",
            ):
                self._load(path, "windows-x64")

    def test_allowlist_constructor_is_private_and_loader_validated(self):
        self.assertFalse(hasattr(receipt, "_new_validated_allowlist"))
        with self.assertRaisesRegex(TypeError, "must come from load_allowlist"):
            receipt._ValidatedAllowlist(
                "windows-x64", tuple(["."]), {}, "0" * 64
            )

        class Lookalike:
            platform = "windows-x64"
            scan_roots = (".",)
            files = {}
            sha256 = "0" * 64

        with self.assertRaisesRegex(
            receipt.NativeMediaReceiptError, "object was not validated"
        ):
            receipt.scan_app(
                Path("unused"), "windows-x64", Lookalike(), "0" * 64
            )

    def test_fabricated_component_roots_and_core_substitutes_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, files = self._windows_app(root)
            forged = (
                (
                    "resources/creative-runtime/node_modules/@remotion/"
                    "compositor-win32-x64-gnu/remotion.exe",
                    "remotion",
                ),
                (
                    "resources/browser/chrome-headless-shell-win64-copy/"
                    "chrome-headless-shell.exe",
                    "browser",
                ),
                ("resources/libffmpeg.dll", "electron"),
            )
            for index, (relative, component) in enumerate(forged):
                with self.subTest(relative=relative):
                    changed = {
                        path: dict(metadata) for path, metadata in files.items()
                    }
                    contract = receipt.PLATFORM_COMPONENT_RULES[
                        "windows-x64"
                    ].get(component, {})
                    lineage = contract.get("lineage_id", "forged:path")
                    changed[relative] = self._entry(
                        component, lineage, "e" * 64
                    )
                    path = self._write_allowlist(
                        root,
                        "windows-x64",
                        ["."],
                        changed,
                        name=f"forged-root-{index}.json",
                    )
                    with self.assertRaisesRegex(
                        receipt.NativeMediaReceiptError,
                        "allowlist component .* is invalid",
                    ):
                        self._load(path, "windows-x64")

            replacements = (
                (
                    "resources/creative-runtime/node_modules/@remotion/"
                    "compositor-win32-x64-msvc/remotion.exe",
                    "resources/creative-runtime/node_modules/@remotion/"
                    "compositor-win32-x64-msvc/not-remotion.exe",
                    "remotion",
                ),
                (
                    "resources/browser/chrome-headless-shell-win64/"
                    "chrome-headless-shell.exe",
                    "resources/browser/chrome-headless-shell-win64/"
                    "not-chrome.exe",
                    "browser",
                ),
            )
            for index, (real_core, fake_core, component) in enumerate(replacements):
                with self.subTest(component=component):
                    changed = {
                        path: dict(metadata) for path, metadata in files.items()
                    }
                    changed.pop(real_core)
                    changed[fake_core] = self._entry(
                        component,
                        receipt.PLATFORM_COMPONENT_RULES["windows-x64"]
                        [component]["lineage_id"],
                        "d" * 64,
                    )
                    path = self._write_allowlist(
                        root,
                        "windows-x64",
                        ["."],
                        changed,
                        name=f"fake-core-{index}.json",
                    )
                    with self.assertRaisesRegex(
                        receipt.NativeMediaReceiptError,
                        f"missing required {component} paths",
                    ):
                        self._load(path, "windows-x64")

    def test_all_distributed_component_lineages_are_exact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, files = self._windows_app(root)
            for component in sorted(receipt.REQUIRED_COMPONENTS):
                with self.subTest(component=component):
                    changed = {
                        path: dict(metadata) for path, metadata in files.items()
                    }
                    target = next(
                        path for path, metadata in changed.items()
                        if metadata["component"] == component
                    )
                    changed[target]["lineage_id"] = "forged:version"
                    path = self._write_allowlist(
                        root,
                        "windows-x64",
                        ["."],
                        changed,
                        name=f"wrong-lineage-{component}.json",
                    )
                    with self.assertRaisesRegex(
                        receipt.NativeMediaReceiptError,
                        f"wrong pinned {component} lineage",
                    ):
                        self._load(path, "windows-x64")

    def test_validated_allowlist_is_deeply_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            target = "resources/bin/ffmpeg.exe"
            with self.assertRaises(TypeError):
                allowlist.files[target]["lineage_id"] = "forged:lineage"
            with self.assertRaises(TypeError):
                allowlist.files[target] = self._entry(
                    "main-ffmpeg", "forged:lineage"
                )

    def test_pyav_payloads_are_forbidden_in_engine_and_helper_trees(self):
        cases = (
            "resources/engine/_internal/av/README.txt",
            "resources/engine/_internal/av.libs/avcodec-62.dll",
            "resources/engine/_internal/av-18.0.0.dist-info/METADATA",
            "resources/helper/_internal/libavfilter.10.dylib",
            "resources/helper/_internal/postproc-58.dll",
        )
        for relative in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app_root, scan_roots, files = self._windows_app(root)
                path = self._write_allowlist(
                    root, "windows-x64", scan_roots, files
                )
                payload = app_root / relative
                payload.parent.mkdir(parents=True, exist_ok=True)
                payload.write_text("forbidden", encoding="utf-8")
                with self.assertRaisesRegex(
                    receipt.NativeMediaReceiptError,
                    "PyAV payload in frozen runtime",
                ):
                    self._scan(
                        app_root,
                        "windows-x64",
                        self._load(path, "windows-x64"),
                    )

    def test_truncated_pe_and_macho_headers_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            core = app_root / "resources/bin/ffmpeg.exe"
            core.write_bytes(b"MZ\0\0\0\0\0\0")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "truncated PE"
            ):
                self._scan(app_root, "windows-x64", allowlist)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._mac_app(root)
            path = self._write_allowlist(
                root, "mac-arm64", scan_roots, files
            )
            allowlist = self._load(path, "mac-arm64")
            core = app_root / "Contents/Resources/bin/ffmpeg"
            core.write_bytes(b"\xcf\xfa\xed\xfe\0\0\0\0")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "truncated Mach-O header"
            ):
                self._scan(app_root, "mac-arm64", allowlist)

    def test_invalid_pe_section_and_macho_load_command_bounds_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            malformed = bytearray(self._pe64())
            struct.pack_into("<I", malformed, 0x188 + 20, 0x1000)
            (app_root / "resources/bin/ffmpeg.exe").write_bytes(malformed)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "invalid PE section bounds"
            ):
                self._scan(app_root, "windows-x64", allowlist)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._mac_app(root)
            path = self._write_allowlist(
                root, "mac-arm64", scan_roots, files
            )
            allowlist = self._load(path, "mac-arm64")
            malformed = bytearray(self._macho64(receipt.CPU_TYPE_ARM64))
            struct.pack_into("<I", malformed, 32 + 4, 0xFFFF)
            (app_root / "Contents/Resources/bin/ffmpeg").write_bytes(malformed)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "invalid Mach-O load command"
            ):
                self._scan(app_root, "mac-arm64", allowlist)

    def test_header_only_and_width_forged_native_stubs_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            header_only = bytearray(0x200)
            header_only[:2] = b"MZ"
            struct.pack_into("<I", header_only, 0x3C, 0x80)
            header_only[0x80:0x84] = b"PE\0\0"
            struct.pack_into(
                "<HHIIIHH",
                header_only,
                0x84,
                receipt.PE_MACHINE_AMD64,
                1,
                0,
                0,
                0,
                0xF0,
                0x0022,
            )
            optional = 0x98
            struct.pack_into("<H", header_only, optional, 0x20B)
            struct.pack_into("<I", header_only, optional + 16, 0x1000)
            struct.pack_into("<I", header_only, optional + 32, 0x1000)
            struct.pack_into("<I", header_only, optional + 36, 0x200)
            struct.pack_into("<I", header_only, optional + 56, 0x2000)
            struct.pack_into("<I", header_only, optional + 60, 0x200)
            section = optional + 0xF0
            header_only[section:section + 8] = b".text\0\0\0"
            struct.pack_into("<I", header_only, section + 8, 0x200)
            struct.pack_into("<I", header_only, section + 12, 0x1000)
            struct.pack_into("<I", header_only, section + 36, 0x60000020)
            (app_root / "resources/bin/ffmpeg.exe").write_bytes(header_only)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "no executable section data",
            ):
                self._scan(app_root, "windows-x64", allowlist)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._mac_app(root)
            path = self._write_allowlist(
                root, "mac-arm64", scan_roots, files
            )
            allowlist = self._load(path, "mac-arm64")
            invalid_segment = struct.pack(
                "<IIIIIIIIII",
                0xFEEDFACF,
                receipt.CPU_TYPE_ARM64,
                0,
                receipt.MH_EXECUTE,
                1,
                8,
                0,
                0,
                receipt.LC_SEGMENT_64,
                8,
            )
            core = app_root / "Contents/Resources/bin/ffmpeg"
            core.write_bytes(invalid_segment)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "truncated Mach-O segment command",
            ):
                self._scan(app_root, "mac-arm64", allowlist)

            header_32 = struct.pack(
                "<IIIIIII",
                0xFEEDFACE,
                receipt.CPU_TYPE_ARM64,
                0,
                receipt.MH_EXECUTE,
                1,
                56,
                0,
            )
            segment_32 = struct.pack(
                "<II16sIIIIIIII",
                receipt.LC_SEGMENT,
                56,
                b"__TEXT".ljust(16, b"\0"),
                0,
                84,
                0,
                84,
                7,
                5,
                0,
                0,
            )
            core.write_bytes(header_32 + segment_32)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "header width does not match CPU type",
            ):
                self._scan(app_root, "mac-arm64", allowlist)

    def test_every_native_hardlink_is_rejected_even_across_components(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            source = app_root / (
                "resources/browser/chrome-headless-shell-win64/libEGL.dll"
            )
            electron = app_root / "ffmpeg.dll"
            electron.unlink()
            os.link(source, electron)
            if source.stat().st_ino == 0:
                self.skipTest("filesystem does not expose stable inode IDs")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "exactly one filesystem link",
            ):
                self._scan(app_root, "windows-x64", allowlist)

    def test_duplicate_native_identity_is_rejected_even_with_unit_link_counts(self):
        collector = receipt._NativeCollector("windows-x64")
        first = receipt._NativeObservation(10, "a" * 64, (1, 99), 1)
        second = receipt._NativeObservation(20, "b" * 64, (1, 99), 1)
        collector.record_native("support-one.dll", first)
        with self.assertRaisesRegex(
            receipt.NativeMediaReceiptError,
            "duplicate native or supporting file identity",
        ):
            collector.record_native(
                "resources/browser/chrome-headless-shell-win64/libEGL.dll",
                second,
            )

    def test_supporting_inventory_and_component_receipts_reject_hardlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            remotion_root = app_root / receipt.PLATFORM_COMPONENT_RULES[
                "windows-x64"
            ]["remotion"]["roots"][0]
            os.link(remotion_root / "README.md", root / "readme-hardlink")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "native or supporting file must have exactly one",
            ):
                self._scan(app_root, "windows-x64", allowlist)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            onnx_receipt = app_root / receipt._onnx_prune_receipt_path(
                "windows-x64"
            )
            os.link(onnx_receipt, root / "onnx-receipt-hardlink")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "native media receipt must have exactly one",
            ):
                self._scan(app_root, "windows-x64", allowlist)

    def test_wrong_allowlist_digest_and_receipt_digest_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "allowlist SHA256 does not match"
            ):
                self._load(path, "windows-x64", "0" * 64)

            allowlist = self._load(path, "windows-x64")
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "validated allowlist SHA256 does not match",
            ):
                receipt.scan_app(
                    app_root, "windows-x64", allowlist, "0" * 64
                )

            payload = self._scan(app_root, "windows-x64", allowlist)
            payload["allowlist_sha256"] = "0" * 64
            receipt_path = root / "receipt.json"
            receipt_path.write_bytes(receipt.canonical_json_bytes(payload))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "receipt allowlist SHA256 does not match",
            ):
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                )

    def test_duplicate_casefold_unsafe_and_wrong_platform_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            duplicate = (
                '{"schema":"' + receipt.ALLOWLIST_SCHEMA + '",'
                '"platform":"windows-x64","scan_roots":["."],"files":{'
                '"resources/bin/ffmpeg.exe":{},'
                '"resources/bin/ffmpeg.exe":{}}}'
            )
            path = self._write_allowlist(
                root, "windows-x64", ["."], {}, raw=duplicate
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "duplicate JSON key"
            ):
                self._load(path, "windows-x64")

            _, _, files = self._windows_app(root)
            files["nested/codec.node"] = self._entry(
                "supporting-native", "case-one", "e" * 64
            )
            files["nested/CODEC.NODE"] = self._entry(
                "supporting-native", "case-two", "f" * 64
            )
            path = self._write_allowlist(root, "windows-x64", ["."], files)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "casefold collision"
            ):
                self._load(path, "windows-x64")

            files.pop("nested/codec.node")
            files.pop("nested/CODEC.NODE")
            files["../escape.pyd"] = self._entry(
                "supporting-native", "escape", "f" * 64
            )
            path = self._write_allowlist(root, "windows-x64", ["."], files)
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "unsafe path"
            ):
                self._load(path, "windows-x64")

            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "wrong platform"
            ):
                self._load(path, "mac-arm64")

    def test_binary_platform_is_checked_for_windows_and_macos(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(path, "windows-x64")
            (app_root / "resources/bin/ffmpeg.exe").write_bytes(
                self._macho64(receipt.CPU_TYPE_X86_64)
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "wrong platform"
            ):
                self._scan(app_root, "windows-x64", allowlist)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._mac_app(root, "mac-x64")
            path = self._write_allowlist(
                root, "mac-x64", scan_roots, files
            )
            allowlist = self._load(path, "mac-x64")
            (app_root / "Contents/Resources/bin/ffmpeg").write_bytes(
                self._macho64(receipt.CPU_TYPE_ARM64)
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "wrong platform"
            ):
                self._scan(app_root, "mac-x64", allowlist)

    def test_executable_and_library_roles_are_checked(self):
        windows_cases = (
            ("resources/bin/ffmpeg.exe", True),
            ("ffmpeg.dll", False),
        )
        for relative, dll in windows_cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app_root, scan_roots, files = self._windows_app(root)
                path = self._write_allowlist(
                    root, "windows-x64", scan_roots, files
                )
                (app_root / relative).write_bytes(self._pe64(dll=dll))
                with self.assertRaisesRegex(
                    receipt.NativeMediaReceiptError, "wrong binary role"
                ):
                    self._scan(
                        app_root,
                        "windows-x64",
                        self._load(path, "windows-x64"),
                    )

        mac_cases = (
            (
                "Contents/Resources/bin/ffmpeg",
                receipt.MH_DYLIB,
            ),
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/"
                "A/Libraries/libffmpeg.dylib",
                receipt.MH_EXECUTE,
            ),
        )
        for relative, file_type in mac_cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app_root, scan_roots, files = self._mac_app(root)
                path = self._write_allowlist(
                    root, "mac-arm64", scan_roots, files
                )
                (app_root / relative).write_bytes(
                    self._macho64(
                        receipt.CPU_TYPE_ARM64,
                        file_type=file_type,
                    )
                )
                with self.assertRaisesRegex(
                    receipt.NativeMediaReceiptError, "wrong binary role"
                ):
                    self._scan(
                        app_root,
                        "mac-arm64",
                        self._load(path, "mac-arm64"),
                    )

    def test_receipt_schema_roots_lineage_and_canonical_bytes_are_strict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_root, scan_roots, files = self._windows_app(root)
            allowlist_path = self._write_allowlist(
                root, "windows-x64", scan_roots, files
            )
            allowlist = self._load(allowlist_path, "windows-x64")
            payload = self._scan(app_root, "windows-x64", allowlist)
            receipt_path = root / "receipt.json"
            receipt_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "not canonical"
            ):
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                )

            payload["scan_roots"] = ["resources/bin"]
            receipt_path.write_bytes(receipt.canonical_json_bytes(payload))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "scan_roots do not match"
            ):
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                )

            payload = self._scan(app_root, "windows-x64", allowlist)
            main_entry = next(
                item for item in payload["files"]
                if item["component"] == "main-ffmpeg"
            )
            remotion_entry = next(
                item for item in payload["files"]
                if item["component"] == "remotion"
            )
            main_entry["component"], remotion_entry["component"] = (
                remotion_entry["component"], main_entry["component"]
            )
            receipt_path.write_bytes(receipt.canonical_json_bytes(payload))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError,
                "wrong pinned .* lineage|receipt component drift",
            ):
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                )

            payload = self._scan(app_root, "windows-x64", allowlist)
            payload["files"][0]["lineage_id"] = "drifted:lineage"
            receipt_path.write_bytes(receipt.canonical_json_bytes(payload))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "lineage metadata drift"
            ):
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                )

            payload = self._scan(app_root, "windows-x64", allowlist)
            payload["files"].append(dict(payload["files"][0]))
            receipt_path.write_bytes(receipt.canonical_json_bytes(payload))
            with self.assertRaisesRegex(
                receipt.NativeMediaReceiptError, "duplicate receipt path"
            ):
                self._verify(
                    app_root, "windows-x64", allowlist, receipt_path
                )


if __name__ == "__main__":
    unittest.main()
