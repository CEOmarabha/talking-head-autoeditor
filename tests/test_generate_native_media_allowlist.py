from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "generate_native_media_allowlist.py"
SPEC = importlib.util.spec_from_file_location(
    "generate_native_media_allowlist", SCRIPT
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load native allowlist generator: {SCRIPT}")
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


class NativeMediaAllowlistGeneratorTests(unittest.TestCase):
    @staticmethod
    def _pe64(payload: bytes = b"native-media") -> bytes:
        data = bytearray(0x400)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into(
            "<HHIIIHH",
            data,
            0x84,
            generator.native.PE_MACHINE_AMD64,
            1,
            0,
            0,
            0,
            0xF0,
            0x0022,
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
        payload: bytes = b"native-media",
        *,
        file_type: int = generator.native.MH_EXECUTE,
    ) -> bytes:
        command_size = 152
        header = struct.pack(
            "<IIIIIIII",
            0xFEEDFACF,
            generator.native.CPU_TYPE_ARM64,
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
    def _write(path: Path, payload: object, *, compact: bool = False) -> str:
        if compact:
            raw = generator.canonical_json_bytes(payload)
        else:
            raw = (
                json.dumps(payload, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _authenticated(
        payload: dict, *, compact: bool = False, name: str = "receipt.json"
    ) -> generator.AuthenticatedJson:
        raw = (
            generator.canonical_json_bytes(payload)
            if compact
            else (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )
        return generator.AuthenticatedJson(
            Path(name), payload, raw, hashlib.sha256(raw).hexdigest()
        )

    @staticmethod
    def _creative_lock(platform: str) -> dict:
        remotion_key, remotion_integrity = generator.REMOTION_INTEGRITIES[
            platform
        ]
        return {
            "name": "autoeditor-creative-runtime",
            "version": "0.1.0",
            "lockfileVersion": 3,
            "requires": True,
            "packages": {
                "": {
                    "dependencies": {
                        "@remotion/cli": "4.0.507",
                        "gsap": "3.15.0",
                        "hyperframes": "0.7.99",
                        "react": "19.0.0",
                        "react-dom": "19.0.0",
                        "remotion": "4.0.507",
                    }
                },
                "node_modules/hyperframes": {
                    "version": "0.7.99",
                    "resolved": (
                        "https://registry.npmjs.org/hyperframes/-/"
                        "hyperframes-0.7.99.tgz"
                    ),
                    "integrity": generator.HYPERFRAMES_INTEGRITY,
                },
                remotion_key: {
                    "version": "4.0.507",
                    "integrity": remotion_integrity,
                },
                "node_modules/onnxruntime-node": {
                    "version": "1.21.1",
                    "integrity": generator.native.ONNX_PACKAGE_INTEGRITY,
                },
            },
        }

    @staticmethod
    def _runtime_manifest(app_root: Path, platform: str) -> dict:
        resources = generator._resources_root(app_root, platform)
        components = {}
        for name in generator.RUNTIME_COMPONENTS:
            component = resources / name
            component.mkdir(parents=True, exist_ok=True)
            components[name] = generator.helper_manifest.directory_receipt(
                component,
                normalize_windows_executables=platform == "windows-x64",
            )
        return {
            "account_capabilities": {},
            "builder": {"python": "test", "system": "test"},
            "components": components,
            "receipt_algorithm": (
                "pe-authenticode-content-v1"
                if platform == "windows-x64"
                else "raw-sha256-v1"
            ),
            "required_local_capabilities": [],
            "schema": generator.RUNTIME_BUILD_SCHEMA,
            "target": generator._platform_target(platform),
            "version": "0.0.0-test",
        }

    @staticmethod
    def _normalization_payload(platform: str) -> dict:
        arch = generator._platform_target(platform)["arch"]
        runtimes = {}
        for runtime, executable in generator.normalizer.REQUIRED_EXECUTABLES.items():
            content = runtime.encode("utf-8")
            entry = {
                "bytes": len(content),
                "mode": 0o755,
                "path": executable,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            source_entry = {**entry, "kind": "file"}
            runtimes[runtime] = {
                "directories": [],
                "files": [entry],
                "normalized_links": [],
                "root_mode": 0o755,
                "source_inventory_sha256": (
                    generator.normalizer._source_inventory_sha256_from_entries(
                        0o755, [source_entry]
                    )
                ),
            }
        return {
            "roots": ["engine", "helper"],
            "runtimes": runtimes,
            "schema": generator.normalizer.SCHEMA,
            "target": {"arch": arch, "os": "mac"},
        }

    @staticmethod
    def _required_observations(platform: str) -> dict[str, SimpleNamespace]:
        paths = set()
        for contract in generator.native.PLATFORM_COMPONENT_RULES[
            platform
        ].values():
            paths.update(contract.get("required_all", ()))
            for alternatives in contract.get("required_any", ()):
                paths.add(alternatives[0])
        return {
            path: SimpleNamespace(
                byte_count=index + 100,
                sha256=hashlib.sha256(path.encode("utf-8")).hexdigest(),
            )
            for index, path in enumerate(sorted(paths))
        }

    @staticmethod
    def _owners(platform: str, digest: str = "a" * 64):
        contracts = generator.native.PLATFORM_COMPONENT_RULES[platform]
        result = {}
        for component in generator.native.REQUIRED_COMPONENTS:
            result[component] = generator.ProducerOwner(
                component,
                contracts[component]["lineage_id"],
                digest,
                f"fixture {component}",
            )
        return result

    @staticmethod
    def _claims(observations, owners):
        claims = {}
        for relative, observed in observations.items():
            component = generator.native._component_for_path(
                relative, "windows-x64"
            )
            claims[relative] = generator.ProducerClaim(
                owners[component], observed.sha256, observed.byte_count
            )
        return claims

    @staticmethod
    def _ffmpeg_link_evidence(status: str = "verified") -> dict:
        programs = {}
        for program, names in generator.WINDOWS_FFMPEG_LINK_FILENAMES.items():
            root = f"{program}-reproduce"
            programs[program] = {
                "lld_map": {
                    "bytes": 10,
                    "filename": names["lld_map"],
                    "sha256": "1" * 64,
                },
                "reproducer": {
                    "bytes": 30,
                    "filename": names["reproducer"],
                    "members": [
                        {
                            "bytes": 10,
                            "path": f"{root}/input.a",
                            "sha256": "2" * 64,
                        },
                        {
                            "bytes": 10,
                            "path": f"{root}/input.o",
                            "sha256": "3" * 64,
                        },
                        {
                            "bytes": 10,
                            "path": f"{root}/response.txt",
                            "sha256": "4" * 64,
                        },
                    ],
                    "sha256": "5" * 64,
                },
                "verbose": {
                    "bytes": 10,
                    "filename": names["verbose"],
                    "sha256": "6" * 64,
                },
            }
        return {"closure_status": status, "programs": programs}

    @classmethod
    def _ffmpeg_build_receipt(cls, source_sha: str) -> dict:
        output = lambda name: {
            "authenticode_content_bytes": 100,
            "authenticode_content_sha256": "7" * 64,
            "buildconf_sha256": "8" * 64,
            "bytes": 100,
            "filename": f"{name}.exe",
            "pe": {
                "certificate_bytes": 0,
                "characteristics": 34,
                "coff_timestamp": 0,
                "dll_characteristics": 352,
                "imports": ["kernel32.dll"],
                "machine": "AMD64",
            },
            "sha256": "9" * 64,
            "version": f"{name} AutoEditor",
            "version_sha256": "a" * 64,
        }
        return {
            "build": {
                "link_evidence": {
                    "closure_status": "verified",
                    "formats": ["lld-map", "lld-reproducer", "lld-verbose"],
                    "programs": ["ffmpeg", "ffprobe"],
                }
            },
            "inventory": {},
            "license_expression": "GPL-2.0-or-later",
            "link_evidence": cls._ffmpeg_link_evidence(),
            "outputs": {
                "ffmpeg": output("ffmpeg"),
                "ffprobe": output("ffprobe"),
            },
            "runtime_notices": [],
            "runtime_smoke": {
                "checks": [
                    "f32le-audio",
                    "ffprobe-mp4",
                    "lavfi-input",
                    "libx264-aac-mp4",
                    "wrapped-avframe-null-video",
                ],
                "status": "passed",
            },
            "schema": generator.WINDOWS_FFMPEG_BUILD_SCHEMA,
            "source": {
                "bundle_bytes": 1,
                "bundle_lock_sha256": "b" * 64,
                "bundle_manifest_bytes": 1,
                "bundle_manifest_sha256": source_sha,
                "bundle_sha256": "c" * 64,
                "primary_lock_sha256": "d" * 64,
                "repository_commit": "e" * 40,
                "repository_tree": "f" * 40,
            },
            "target": {
                "arch": "x64",
                "machine": "AMD64",
                "os": "windows",
                "triple": "x86_64-w64-mingw32",
            },
        }

    def test_authentication_rejects_digest_mismatch_duplicate_key_and_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "receipt.json"
            path.write_text('{"schema":"x"}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError, "raw SHA256 mismatch"
            ):
                generator._read_authenticated_json(
                    path, "0" * 64, "fixture receipt"
                )

            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema":"x","schema":"y"}\n')
            digest = hashlib.sha256(duplicate.read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError, "duplicate JSON key"
            ):
                generator._read_authenticated_json(
                    duplicate, digest, "fixture receipt"
                )

            link = root / "linked.json"
            link.symlink_to(path.name)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError, "not a symlink"
            ):
                generator._read_authenticated_json(
                    link, digest, "fixture receipt"
                )

    def test_exact_electron_chrome_receipt_accepts_production_contract_and_rejects_drift(self):
        for platform in ("windows-x64", "mac-arm64", "mac-x64"):
            with self.subTest(platform=platform):
                payload = generator._expected_electron_chromium(platform)
                authenticated = self._authenticated(payload)
                generator._validate_electron_chromium(
                    authenticated, platform
                )

                forged = copy.deepcopy(payload)
                forged["chrome_headless_shell"]["archive"]["sha256"] = "0" * 64
                with self.assertRaisesRegex(
                    generator.AllowlistGenerationError, "provenance receipt drifted"
                ):
                    generator._validate_electron_chromium(
                        self._authenticated(forged), platform
                    )

    def test_mac_arm64_scan_roots_cover_current_product_framework_shape(self):
        platform = "mac-arm64"
        expected_native_paths = {
            "Contents/MacOS/AutoEditor",
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/A/"
                "Electron Framework"
            ),
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/A/"
                "Helpers/chrome_crashpad_handler"
            ),
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/A/"
                "Libraries/libEGL.dylib"
            ),
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/A/"
                "Libraries/libGLESv2.dylib"
            ),
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/A/"
                "Libraries/libffmpeg.dylib"
            ),
            (
                "Contents/Frameworks/Electron Framework.framework/Versions/A/"
                "Libraries/libvk_swiftshader.dylib"
            ),
            "Contents/Frameworks/Mantle.framework/Versions/A/Mantle",
            (
                "Contents/Frameworks/ReactiveObjC.framework/Versions/A/"
                "ReactiveObjC"
            ),
            "Contents/Frameworks/Squirrel.framework/Versions/A/Squirrel",
            (
                "Contents/Frameworks/Squirrel.framework/Versions/A/"
                "Resources/ShipIt"
            ),
            (
                "Contents/Frameworks/AutoEditor Helper Helper.app/"
                "Contents/MacOS/AutoEditor Helper Helper"
            ),
            (
                "Contents/Frameworks/AutoEditor Helper Helper (GPU).app/"
                "Contents/MacOS/AutoEditor Helper Helper (GPU)"
            ),
            (
                "Contents/Frameworks/AutoEditor Helper Helper (Plugin).app/"
                "Contents/MacOS/AutoEditor Helper Helper (Plugin)"
            ),
            (
                "Contents/Frameworks/AutoEditor Helper Helper (Renderer).app/"
                "Contents/MacOS/AutoEditor Helper Helper (Renderer)"
            ),
        }
        self.assertEqual(len(expected_native_paths), 15)
        self.assertEqual(
            set(generator.MAC_ELECTRON_NATIVE_PATHS), expected_native_paths
        )
        self.assertIn(
            "Contents/MacOS/AutoEditor",
            generator.MAC_ELECTRON_NATIVE_PATHS,
        )
        self.assertNotIn(
            "Contents/MacOS/AutoEditor Helper",
            generator.MAC_ELECTRON_NATIVE_PATHS,
        )
        roots = generator._scan_roots(platform)
        generator._validate_generator_scan_coverage(roots, platform)
        renderer_root = (
            "Contents/Frameworks/AutoEditor Helper Helper (Renderer).app/"
            "Contents/MacOS"
        )
        with self.assertRaisesRegex(
            generator.AllowlistGenerationError,
            r"scan roots do not cover.*Helper \(Renderer\)",
        ):
            generator._validate_generator_scan_coverage(
                tuple(root for root in roots if root != renderer_root),
                platform,
            )

        with tempfile.TemporaryDirectory() as td:
            app_root = Path(td).resolve() / "AutoEditor Helper.app"
            for mandatory in generator.native.MANDATORY_SCAN_PATHS[platform]:
                (app_root / mandatory).mkdir(parents=True, exist_ok=True)
            for root in generator.MAC_ELECTRON_SCAN_ROOTS:
                (app_root / root).mkdir(parents=True, exist_ok=True)
            for index, relative in enumerate(sorted(expected_native_paths)):
                path = app_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    self._macho64(
                        f"accepted-arm64-{index}".encode("ascii"),
                        file_type=(
                            generator.native.MH_DYLIB
                            if (
                                relative.endswith(".dylib")
                                or relative
                                in generator.MAC_FRAMEWORK_LIBRARY_PATHS
                            )
                            else generator.native.MH_EXECUTE
                        ),
                    )
                )
            observed = generator._inventory_native_tree(
                app_root,
                tuple(sorted(generator.MAC_ELECTRON_SCAN_ROOTS)),
                platform,
            )
            self.assertEqual(set(observed), expected_native_paths)
            correct_root = app_root / "Contents/MacOS/AutoEditor"
            incorrect_root = app_root / "Contents/MacOS/AutoEditor Helper"
            correct_root.rename(incorrect_root)
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError,
                "Mac Electron native path set.*missing "
                "Contents/MacOS/AutoEditor; unexpected "
                "Contents/MacOS/AutoEditor Helper",
            ):
                generator._inventory_native_tree(
                    app_root,
                    tuple(sorted(generator.MAC_ELECTRON_SCAN_ROOTS)),
                    platform,
                )

    def test_native_claim_outside_mac_scan_roots_is_rejected(self):
        owner = generator.ProducerOwner(
            "supporting-native",
            "fixture:electron-builder",
            "a" * 64,
            "fixture final Electron app manifest",
        )
        claims = {
            "Contents/Frameworks/Unexpected.framework/Versions/A/Unexpected": (
                generator.ProducerClaim(owner, "b" * 64, 100)
            )
        }
        with self.assertRaisesRegex(
            generator.AllowlistGenerationError,
            "claims are outside the configured final scan roots.*Unexpected",
        ):
            generator._applicable_claims(claims, "mac-arm64")

    def test_creative_lock_requires_exact_hyperframes_remotion_and_onnx_pins(self):
        platform = "windows-x64"
        lock = self._creative_lock(platform)
        generator._validate_creative_runtime_lock(
            self._authenticated(lock), platform
        )
        cases = (
            ("node_modules/hyperframes", "version", "0.8.0", "HyperFrames"),
            (
                generator.REMOTION_INTEGRITIES[platform][0],
                "version",
                "4.0.508",
                "Remotion",
            ),
            (
                "node_modules/onnxruntime-node",
                "integrity",
                "sha512-forged",
                "ONNX Runtime",
            ),
        )
        for package, field, value, message in cases:
            with self.subTest(package=package):
                forged = copy.deepcopy(lock)
                forged["packages"][package][field] = value
                with self.assertRaisesRegex(
                    generator.AllowlistGenerationError, message
                ):
                    generator._validate_creative_runtime_lock(
                        self._authenticated(forged), platform
                    )

    def test_runtime_build_manifest_recomputes_final_component_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            app_root = Path(td) / "AutoEditor Helper"
            payload = self._runtime_manifest(app_root, "windows-x64")
            authenticated = self._authenticated(payload)
            generator._validate_runtime_build_manifest(
                authenticated, app_root, "windows-x64"
            )
            changed = app_root / "resources" / "engine" / "late.dll"
            changed.write_bytes(b"late native bytes")
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError,
                "engine differs from its build manifest",
            ):
                generator._validate_runtime_build_manifest(
                    authenticated, app_root, "windows-x64"
                )

            changed.unlink()
            changed_browser = (
                app_root
                / "resources/browser/chrome-headless-shell-win64/"
                "chrome-headless-shell.exe"
            )
            changed_browser.parent.mkdir(parents=True)
            changed_browser.write_bytes(
                self._pe64(b"replacement browser bytes")
            )
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError,
                "browser differs from its build manifest",
            ):
                generator._validate_runtime_build_manifest(
                    authenticated, app_root, "windows-x64"
                )

    def test_windows_ffmpeg_requires_exact_shared_v4_artifact_verifier(self):
        self.assertEqual(
            generator.WINDOWS_FFMPEG_BUILD_SCHEMA,
            generator.windows_ffmpeg_verifier.RECEIPT_SCHEMA,
        )
        source = self._authenticated({"source": True}, compact=True)
        payload = self._ffmpeg_build_receipt(source.sha256)
        authenticated = self._authenticated(payload)
        source_lock = self._authenticated(
            {"source_lock": True}, name="source-lock.json"
        )
        capabilities = self._authenticated(
            {"capabilities": True}, name="capabilities.json"
        )
        source_archive = generator.AuthenticatedFile(
            Path("source.tar"), "c" * 64, 100
        )
        pinned_source = SimpleNamespace(sha256=source_lock.sha256)
        pinned_capabilities = SimpleNamespace(sha256=capabilities.sha256)

        class FakeVerifierError(ValueError):
            pass

        def loaded_receipt(value):
            raw = (
                json.dumps(value, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            return SimpleNamespace(
                canonical=raw,
                sha256=hashlib.sha256(raw).hexdigest(),
                parsed=lambda: copy.deepcopy(value),
            )

        fake = SimpleNamespace(
            RECEIPT_SCHEMA=generator.WINDOWS_FFMPEG_BUILD_SCHEMA,
            WindowsFFmpegError=FakeVerifierError,
            canonical_json=lambda value: (
                json.dumps(value, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8"),
            create_receipt=mock.Mock(return_value=copy.deepcopy(payload)),
            load_contracts=mock.Mock(
                return_value=(pinned_source, pinned_capabilities)
            ),
            load_receipt=mock.Mock(return_value=loaded_receipt(payload)),
            validate_receipt_against_contracts=mock.Mock(),
        )
        arguments = {
            "app_root": Path("final-app"),
            "license_dir": Path("licenses"),
            "link_evidence_dir": Path("link-evidence"),
            "linkage_dir": Path("linkage"),
            "repository_commit": "e" * 40,
        }
        with mock.patch.object(
            generator, "windows_ffmpeg_verifier", fake
        ):
            self.assertEqual(
                generator._validate_windows_ffmpeg_build(
                    authenticated,
                    source,
                    source_lock,
                    capabilities,
                    source_archive,
                    **arguments,
                ),
                payload,
            )
        self.assertEqual(
            fake.create_receipt.call_args.kwargs,
            {
                "source_lock_path": source_lock.path,
                "capabilities_path": capabilities.path,
                "ffmpeg": Path("final-app/resources/bin/ffmpeg.exe"),
                "ffprobe": Path("final-app/resources/bin/ffprobe.exe"),
                "license_dir": Path("licenses"),
                "link_evidence_dir": Path("link-evidence"),
                "linkage_dir": Path("linkage"),
                "source_bundle": source_archive.path,
                "source_manifest": source.path,
                "repository_commit": "e" * 40,
                "repo_root": ROOT,
            },
        )
        fake.validate_receipt_against_contracts.assert_called_once()

        forged = copy.deepcopy(payload)
        forged["outputs"]["ffmpeg"]["sha256"] = "0" * 64
        forged_authenticated = self._authenticated(forged)
        fake.load_receipt.return_value = loaded_receipt(forged)
        fake.create_receipt.return_value = copy.deepcopy(payload)
        with self.assertRaisesRegex(
            generator.AllowlistGenerationError,
            "differs from the exact shared artifact verifier",
        ):
            with mock.patch.object(
                generator, "windows_ffmpeg_verifier", fake
            ):
                generator._validate_windows_ffmpeg_build(
                    forged_authenticated,
                    source,
                    source_lock,
                    capabilities,
                    source_archive,
                    **arguments,
                )

        unverified = copy.deepcopy(payload)
        unverified["link_evidence"]["closure_status"] = (
            "input-classification-unverified"
        )
        fake.load_receipt.return_value = loaded_receipt(unverified)
        fake.create_receipt.return_value = copy.deepcopy(unverified)
        with self.assertRaisesRegex(
            generator.AllowlistGenerationError,
            "link input closure is not verified",
        ):
            with mock.patch.object(
                generator, "windows_ffmpeg_verifier", fake
            ):
                generator._validate_windows_ffmpeg_build(
                    self._authenticated(unverified),
                    source,
                    source_lock,
                    capabilities,
                    source_archive,
                    **arguments,
                )

        with self.assertRaisesRegex(
            generator.MissingProducerContractError,
            "exact shared verify_windows_ffmpeg.py v4 verifier is unavailable",
        ):
            with mock.patch.object(
                generator, "windows_ffmpeg_verifier", None
            ), mock.patch.object(
                generator, "windows_ffmpeg_verifier_error", None
            ):
                generator._validate_windows_ffmpeg_build(
                    authenticated,
                    source,
                    source_lock,
                    capabilities,
                    source_archive,
                    **arguments,
                )

    def test_windows_ffmpeg_rejects_raw_path_ambiguity_and_logical_duplicates(self):
        payload = {
            "link_evidence": self._ffmpeg_link_evidence()["programs"]
        }
        payload = {"link_evidence": {"programs": payload["link_evidence"]}}
        generator._prevalidate_link_member_paths(payload)
        root = "ffmpeg-reproduce"
        hostile = (
            f"{root}//input.o",
            f"{root}/./input.o",
            f"{root}/../outside.o",
            f"{root}\\input.o",
            f"{root}/control\x1f.o",
            f"{root}/e\u0301.o",
            f"{root}/Ａ.o",
            f"{root}/",
            "/ffmpeg-reproduce/input.o",
            "other-root/input.o",
        )
        for path in hostile:
            with self.subTest(path=repr(path)):
                changed = copy.deepcopy(payload)
                changed["link_evidence"]["programs"]["ffmpeg"][
                    "reproducer"
                ]["members"][1]["path"] = path
                with self.assertRaisesRegex(
                    generator.AllowlistGenerationError, "path is invalid"
                ):
                    generator._prevalidate_link_member_paths(changed)

        duplicate = copy.deepcopy(payload)
        members = duplicate["link_evidence"]["programs"]["ffmpeg"][
            "reproducer"
        ]["members"]
        members[0]["path"] = f"{root}/INPUT.O"
        members[1]["path"] = f"{root}/input.o"
        with self.assertRaisesRegex(
            generator.AllowlistGenerationError, "logical duplicate"
        ):
            generator._prevalidate_link_member_paths(duplicate)

    def test_normalization_receipt_reconstructs_source_inventory_and_matches_embedded(self):
        with tempfile.TemporaryDirectory() as td:
            app_root = Path(td).resolve() / "AutoEditor Helper.app"
            payload = self._normalization_payload("mac-arm64")
            raw = generator.canonical_json_bytes(payload)
            embedded = (
                app_root
                / "Contents/Resources/licenses"
                / generator.normalizer.RECEIPT_FILENAME
            )
            embedded.parent.mkdir(parents=True)
            embedded.write_bytes(raw)
            resources = app_root / "Contents/Resources"
            for runtime, executable in (
                generator.normalizer.REQUIRED_EXECUTABLES.items()
            ):
                runtime_root = resources / runtime
                runtime_root.mkdir(mode=0o755)
                runtime_root.chmod(0o755)
                binary = runtime_root / executable
                binary.write_bytes(runtime.encode("utf-8"))
                binary.chmod(0o755)
            authenticated = generator.AuthenticatedJson(
                embedded,
                payload,
                raw,
                hashlib.sha256(raw).hexdigest(),
            )
            # The normalization implementation intentionally refuses to run
            # off macOS.  This contract test exercises the generator's
            # authenticated-receipt seam on every CI host, while the
            # normalizer's own suite covers the physical stage verification.
            with mock.patch.object(
                generator.normalizer, "verify_stage", return_value=payload
            ):
                self.assertEqual(
                    generator._validate_normalization(
                        authenticated, app_root, "mac-arm64"
                    ),
                    payload,
                )

                forged = copy.deepcopy(payload)
                forged["runtimes"]["engine"]["source_inventory_sha256"] = (
                    "0" * 64
                )
                forged_raw = generator.canonical_json_bytes(forged)
                embedded.write_bytes(forged_raw)
                with self.assertRaisesRegex(
                    generator.AllowlistGenerationError,
                    "source inventory digest does not match",
                ):
                    generator._validate_normalization(
                        generator.AuthenticatedJson(
                            embedded,
                            forged,
                            forged_raw,
                            hashlib.sha256(forged_raw).hexdigest(),
                        ),
                        app_root,
                        "mac-arm64",
                    )

    def test_macos_fails_with_precise_missing_contracts_after_usable_inputs(self):
        fixture = self._authenticated({"fixture": True})
        inputs = generator.GeneratorInputs(
            onnx_receipt=Path("onnx"),
            onnx_receipt_sha256="a" * 64,
            electron_chromium_receipt=Path("electron"),
            electron_chromium_receipt_sha256="b" * 64,
            creative_runtime_lock=Path("lock"),
            creative_runtime_lock_sha256="c" * 64,
            runtime_build_manifest=Path("runtime"),
            runtime_build_manifest_sha256="d" * 64,
            mac_normalization_receipt=Path("normalization"),
            mac_normalization_receipt_sha256="e" * 64,
        )
        with mock.patch.object(
            generator, "_read_authenticated_json", return_value=fixture
        ), mock.patch.object(
            generator.native, "_validate_onnx_prune_receipt"
        ), mock.patch.object(
            generator, "_embedded_receipt_matches"
        ), mock.patch.object(
            generator, "_validate_electron_chromium"
        ), mock.patch.object(
            generator, "_validate_creative_runtime_lock"
        ), mock.patch.object(
            generator, "_validate_runtime_build_manifest"
        ), mock.patch.object(
            generator, "_validate_normalization"
        ):
            with self.assertRaisesRegex(
                generator.MissingProducerContractError,
                "Mac FFmpeg bundle receipt.*Mac Remotion.*final Electron app",
            ):
                generator._load_producers(
                    Path("unused"), "mac-arm64", inputs
                )

    def test_unique_owner_rejects_unclaimed_and_multiply_claimed_paths(self):
        relative = "AutoEditor Helper.exe"
        with self.assertRaisesRegex(
            generator.MissingProducerContractError,
            "final Electron app build manifest",
        ):
            generator._unique_owner(relative, [])
        owner = generator.ProducerOwner(
            "supporting-native", "fixture:a", "a" * 64, "producer a"
        )
        other = generator.ProducerOwner(
            "supporting-native", "fixture:b", "b" * 64, "producer b"
        )
        with self.assertRaisesRegex(
            generator.AllowlistGenerationError,
            "multiple authenticated producers.*producer a, producer b",
        ):
                generator._unique_owner(relative, [owner, other])

    def test_production_owners_leave_final_electron_paths_unclaimed(self):
        platform = "windows-x64"
        contracts = generator.native.PLATFORM_COMPONENT_RULES[platform]
        onnx = self._authenticated({"onnx": True}, name="onnx.json")
        electron = self._authenticated(
            {"electron": True}, name="electron.json"
        )
        runtime = self._authenticated({"runtime": True}, name="runtime.json")
        remotion = self._authenticated(
            {"remotion": True}, name="remotion.json"
        )
        source = self._authenticated({"source": True}, name="source.json")
        owners = generator._component_owners(
            platform,
            onnx=onnx,
            electron=electron,
            runtime=runtime,
            remotion=remotion,
            ffmpeg_source=source,
            normalization=None,
        )
        self.assertNotIn("electron", owners)
        self.assertEqual(
            owners["browser"],
            generator.ProducerOwner(
                "browser",
                contracts["browser"]["lineage_id"],
                runtime.sha256,
                (
                    "Helper runtime build manifest bound to the pinned "
                    "Chrome/HyperFrames provenance receipt"
                ),
            ),
        )

        observations = self._required_observations(platform)
        ffmpeg_build = {
            "outputs": {
                name: {
                    "bytes": observations[
                        f"resources/bin/{name}.exe"
                    ].byte_count,
                    "sha256": observations[
                        f"resources/bin/{name}.exe"
                    ].sha256,
                }
                for name in ("ffmpeg", "ffprobe")
            }
        }
        with mock.patch.object(
            generator.native, "_validate_onnx_observed"
        ):
            with self.assertRaisesRegex(
                generator.MissingProducerContractError,
                "ffmpeg.dll.*final Electron app build manifest",
            ):
                generator._validate_observations(
                    observations, platform, owners, {}, ffmpeg_build
                )

    def test_windows_generation_emits_canonical_loadable_allowlist_and_raw_sha(self):
        platform = "windows-x64"
        observations = self._required_observations(platform)
        owners = self._owners(platform)
        claims = self._claims(observations, owners)
        ffmpeg_build = {
            "outputs": {
                "ffmpeg": {
                    "bytes": observations[
                        "resources/bin/ffmpeg.exe"
                    ].byte_count,
                    "sha256": observations[
                        "resources/bin/ffmpeg.exe"
                    ].sha256,
                },
                "ffprobe": {
                    "bytes": observations[
                        "resources/bin/ffprobe.exe"
                    ].byte_count,
                    "sha256": observations[
                        "resources/bin/ffprobe.exe"
                    ].sha256,
                },
            }
        }
        inputs = mock.sentinel.inputs
        with mock.patch.object(
            generator,
            "_load_producers",
            return_value=(owners, ffmpeg_build, claims),
        ) as load_producers, mock.patch.object(
            generator.native,
            "_inventory_native_tree",
            side_effect=(observations, dict(observations)),
        ) as inventory, mock.patch.object(
            generator.native, "_validate_onnx_observed"
        ):
            payload, digest = generator.generate_allowlist(
                Path("final-app"), platform, inputs
            )
        self.assertEqual(load_producers.call_count, 2)
        self.assertEqual(inventory.call_count, 2)
        raw = generator.canonical_json_bytes(payload)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
        self.assertEqual(payload["schema"], generator.native.ALLOWLIST_SCHEMA)
        self.assertEqual(payload["scan_roots"], ["."])
        self.assertEqual(set(payload["files"]), set(observations))

        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "allowlist.json"
            generator.write_allowlist(output, payload, digest)
            self.assertEqual(output.read_bytes(), raw)
            loaded = generator.native.load_allowlist(
                output, platform, digest
            )
            self.assertEqual(set(loaded.files), set(observations))
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError, "cannot write"
            ):
                generator.write_allowlist(output, payload, digest)

    def test_stable_b_omission_rejects_27_claims_and_26_observations(self):
        platform = "windows-x64"
        observations = self._required_observations(platform)
        self.assertEqual(len(observations), 26)
        owners = self._owners(platform)
        claims = self._claims(observations, owners)
        omitted = "resources/engine/omitted-native.dll"
        claims[omitted] = generator.ProducerClaim(
            owners["frozen-engine"], "f" * 64, 500
        )
        self.assertEqual(len(claims), 27)
        ffmpeg_build = {
            "outputs": {
                name: {
                    "bytes": observations[
                        f"resources/bin/{name}.exe"
                    ].byte_count,
                    "sha256": observations[
                        f"resources/bin/{name}.exe"
                    ].sha256,
                }
                for name in ("ffmpeg", "ffprobe")
            }
        }
        with mock.patch.object(
            generator,
            "_load_producers",
            return_value=(owners, ffmpeg_build, claims),
        ), mock.patch.object(
            generator.native,
            "_inventory_native_tree",
            side_effect=(observations, dict(observations)),
        ), mock.patch.object(
            generator.native, "_validate_onnx_observed"
        ):
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError,
                "claim paths are missing from the final native scan.*"
                "omitted-native.dll",
            ):
                generator.generate_allowlist(
                    Path("final-app"), platform, mock.sentinel.inputs
                )

    def test_generation_rejects_unclaimed_supporting_native_and_tree_race(self):
        platform = "windows-x64"
        observations = self._required_observations(platform)
        owners = self._owners(platform)
        claims = self._claims(observations, owners)
        ffmpeg_build = {
            "outputs": {
                name: {
                    "bytes": observations[f"resources/bin/{name}.exe"].byte_count,
                    "sha256": observations[f"resources/bin/{name}.exe"].sha256,
                }
                for name in ("ffmpeg", "ffprobe")
            }
        }
        inputs = mock.sentinel.inputs

        with_supporting = dict(observations)
        with_supporting["AutoEditor Helper.exe"] = SimpleNamespace(
            byte_count=500, sha256="f" * 64
        )
        with mock.patch.object(
            generator,
            "_load_producers",
            return_value=(owners, ffmpeg_build, claims),
        ), mock.patch.object(
            generator.native,
            "_inventory_native_tree",
            side_effect=(with_supporting, dict(with_supporting)),
        ), mock.patch.object(
            generator.native, "_validate_onnx_observed"
        ):
            with self.assertRaisesRegex(
                generator.MissingProducerContractError,
                "AutoEditor Helper.exe.*final Electron app build manifest",
            ):
                generator.generate_allowlist(
                    Path("final-app"), platform, inputs
                )

        changed_owners = dict(owners)
        changed_owners["browser"] = generator.ProducerOwner(
            "browser",
            changed_owners["browser"].lineage_id,
            "b" * 64,
            "changed browser producer",
        )
        with mock.patch.object(
            generator,
            "_load_producers",
            side_effect=(
                (owners, ffmpeg_build, claims),
                (changed_owners, ffmpeg_build, claims),
            ),
        ), mock.patch.object(
            generator.native,
            "_inventory_native_tree",
            side_effect=(observations, dict(observations)),
        ):
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError,
                "producer bindings changed while generating",
            ):
                generator.generate_allowlist(
                    Path("final-app"), platform, inputs
                )

        drifted = dict(observations)
        drifted[next(iter(drifted))] = SimpleNamespace(
            byte_count=999, sha256="e" * 64
        )
        with mock.patch.object(
            generator,
            "_load_producers",
            return_value=(owners, ffmpeg_build, claims),
        ), mock.patch.object(
            generator.native,
            "_inventory_native_tree",
            side_effect=(observations, drifted),
        ):
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError, "changed while generating"
            ):
                generator.generate_allowlist(
                    Path("final-app"), platform, inputs
                )

        swapped = dict(observations)
        swapped_path = "resources/browser/chrome-headless-shell-win64/" \
            "chrome-headless-shell.exe"
        swapped[swapped_path] = SimpleNamespace(
            byte_count=observations[swapped_path].byte_count,
            sha256="0" * 64,
        )
        with mock.patch.object(
            generator,
            "_load_producers",
            return_value=(owners, ffmpeg_build, claims),
        ), mock.patch.object(
            generator.native,
            "_inventory_native_tree",
            side_effect=(swapped, dict(swapped)),
        ), mock.patch.object(
            generator.native, "_validate_onnx_observed"
        ):
            with self.assertRaisesRegex(
                generator.AllowlistGenerationError,
                "authenticated per-path producer inventory.*chrome-headless-shell",
            ):
                generator.generate_allowlist(
                    Path("final-app"), platform, inputs
                )

    def test_cli_help_exposes_only_specific_receipts_and_raw_digests(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        help_text = result.stdout
        self.assertIn("--onnx-receipt-sha256", help_text)
        self.assertIn("--electron-chromium-receipt-sha256", help_text)
        self.assertIn("--windows-ffmpeg-source-manifest-sha256", help_text)
        self.assertIn("--windows-ffmpeg-source-lock-sha256", help_text)
        self.assertIn("--windows-ffmpeg-capabilities-sha256", help_text)
        self.assertIn("--windows-ffmpeg-source-bundle-sha256", help_text)
        self.assertIn("--windows-ffmpeg-linkage-dir", help_text)
        self.assertIn("--windows-ffmpeg-repository-commit", help_text)
        self.assertNotIn("--producer", help_text)


if __name__ == "__main__":
    unittest.main()
