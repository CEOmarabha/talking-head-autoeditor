from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import MappingProxyType
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "macos_remotion_receipt.py"
SPEC = importlib.util.spec_from_file_location("macos_remotion_receipt", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load macOS Remotion receipt module: {SCRIPT}")
receipt = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = receipt
SPEC.loader.exec_module(receipt)


class MacRemotionReceiptTests(unittest.TestCase):
    @staticmethod
    def _macho(arch: str, kind: str, seed: int) -> bytes:
        cpu = receipt.CPU_TYPES[arch]
        file_type = receipt.MH_EXECUTE if kind == "executable" else receipt.MH_DYLIB
        identifier = uuid.UUID(int=seed + 1).bytes
        uuid_command = struct.pack("<II16s", receipt.LC_UUID, 24, identifier)
        payload = bytes([seed % 251 + 1]) * (32 + seed)
        file_offset = 32 + 24 + 72
        page_size = 16 * 1024 if arch == "arm64" else 4 * 1024
        virtual_size = (len(payload) + page_size - 1) // page_size * page_size
        segment = struct.pack(
            "<II16sQQQQIIII",
            receipt.LC_SEGMENT_64,
            72,
            b"__LINKEDIT".ljust(16, b"\0"),
            0x100000000,
            virtual_size,
            file_offset,
            len(payload),
            1,
            1,
            0,
            0,
        )
        commands = uuid_command + segment
        header = struct.pack(
            "<IIIIIIII",
            0xFEEDFACF,
            cpu,
            0,
            file_type,
            2,
            len(commands),
            0,
            0,
        )
        return header + commands + payload

    @staticmethod
    def _signed_macho_with_alignment_padding() -> tuple[bytes, bytes, int]:
        """Return a signed image and a stripped image retaining 8 zero bytes."""
        cpu = receipt.CPU_TYPES["arm64"]
        identifier = uuid.UUID(int=1).bytes
        uuid_command = struct.pack("<II16s", receipt.LC_UUID, 24, identifier)
        payload = b"P" * 40
        file_offset = 32 + 24 + 72 + 16
        signature_offset = file_offset + len(payload) + 8
        signature = b"S" * 32
        segment = struct.pack(
            "<II16sQQQQIIII",
            receipt.LC_SEGMENT_64,
            72,
            b"__LINKEDIT".ljust(16, b"\0"),
            0x100000000,
            16 * 1024,
            file_offset,
            len(payload) + 8 + len(signature),
            1,
            1,
            0,
            0,
        )
        code_signature = struct.pack(
            "<IIII",
            receipt.LC_CODE_SIGNATURE,
            16,
            signature_offset,
            len(signature),
        )
        commands = uuid_command + segment + code_signature
        header = struct.pack(
            "<IIIIIIII",
            0xFEEDFACF,
            cpu,
            0,
            receipt.MH_EXECUTE,
            3,
            len(commands),
            0,
            0,
        )
        raw = header + commands + payload + b"\0" * 8 + signature

        stripped = bytearray(raw[:signature_offset])
        struct.pack_into("<II", stripped, 16, 2, len(commands) - 16)
        struct.pack_into(
            "<Q", stripped, 32 + 24 + 48, len(stripped) - file_offset
        )
        stripped[32 + 24 + 72:32 + len(commands)] = b"\0" * 16
        return raw, bytes(stripped), file_offset + len(payload)

    @classmethod
    def _source_files(cls, arch: str = "arm64") -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for index, name in enumerate(sorted(receipt.EXPECTED_FILES)):
            if name in receipt.NATIVE_FILES:
                kind = "executable" if name in receipt.EXECUTABLE_FILES else "dylib"
                files[name] = cls._macho(arch, kind, index)
            else:
                files[name] = f"fixture:{arch}:{name}\n".encode()
        return files

    @staticmethod
    def _tarball(path: Path, files: dict[str, bytes], *, extra: str | None = None,
                 link: str | None = None) -> None:
        with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(files):
                raw = files[name]
                member = tarfile.TarInfo(f"package/{name}")
                member.size = len(raw)
                member.mode = 0o755 if name in receipt.NATIVE_FILES else 0o644
                member.mtime = 0
                archive.addfile(member, io.BytesIO(raw))
            if extra is not None:
                raw = b"extra"
                member = tarfile.TarInfo(f"package/{extra}")
                member.size = len(raw)
                member.mode = 0o644
                member.mtime = 0
                archive.addfile(member, io.BytesIO(raw))
            if link is not None:
                member = tarfile.TarInfo("package/README.md")
                member.type = tarfile.SYMTYPE
                member.linkname = link
                member.mode = 0o644
                member.mtime = 0
                archive.addfile(member)

    @staticmethod
    def _lock_payload(contract) -> dict:
        return {
            "name": "fixture",
            "lockfileVersion": 3,
            "packages": {
                contract.lock_key: {
                    "version": receipt.VERSION,
                    "resolved": contract.resolved,
                    "integrity": contract.integrity,
                    "cpu": [contract.architecture],
                    "optional": True,
                    "os": ["darwin"],
                },
                "node_modules/@remotion/renderer": {
                    "optionalDependencies": {
                        contract.package_name: receipt.VERSION,
                    }
                },
            },
        }

    @staticmethod
    def _package_root(app: Path, contract) -> Path:
        return (
            app / "Contents" / "Resources" / "creative-runtime"
            / "node_modules" / "@remotion" / contract.package_name.split("/")[1]
        )

    @contextmanager
    def _fixture(self, arch: str = "arm64"):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = self._source_files(arch)
            tarball = root / "package.tgz"
            self._tarball(tarball, files)
            tar_raw = tarball.read_bytes()
            base = receipt.ARCH_CONTRACTS[arch]
            contract = dataclasses.replace(
                base,
                tarball_sha256=hashlib.sha256(tar_raw).hexdigest(),
                tarball_bytes=len(tar_raw),
            )
            pins = {}
            for name, raw in files.items():
                kind = (
                    "data" if name in receipt.DATA_FILES
                    else "executable" if name in receipt.EXECUTABLE_FILES
                    else "dylib"
                )
                if name in receipt.NATIVE_FILES:
                    metadata = receipt._parse_macho(raw, name)
                    pins[name] = receipt.SourceFilePin(
                        len(raw), hashlib.sha256(raw).hexdigest(), 0o755,
                        kind, len(raw), hashlib.sha256(raw).hexdigest(),
                        metadata.macho_uuid, metadata.linkedit_vm_size,
                    )
                else:
                    pins[name] = receipt.SourceFilePin(
                        len(raw), hashlib.sha256(raw).hexdigest(), 0o644, kind
                    )
            contracts = dict(receipt.ARCH_CONTRACTS)
            contracts[arch] = contract
            all_pins = dict(receipt.PINNED_SOURCE_FILES)
            all_pins[arch] = MappingProxyType(pins)
            lock = root / "package-lock.json"
            lock.write_text(
                json.dumps(self._lock_payload(contract)), encoding="utf-8"
            )
            lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
            app = root / "AutoEditor Helper.app"
            package = self._package_root(app, contract)
            package.mkdir(parents=True)
            for name, raw in files.items():
                target = package / name
                target.write_bytes(raw)
                target.chmod(0o755 if name in receipt.NATIVE_FILES else 0o644)
            with ExitStack() as patches:
                patches.enter_context(mock.patch.object(
                    receipt, "ARCH_CONTRACTS", MappingProxyType(contracts)
                ))
                patches.enter_context(mock.patch.object(
                    receipt, "PINNED_SOURCE_FILES", MappingProxyType(all_pins)
                ))
                yield {
                    "root": root,
                    "files": files,
                    "tarball": tarball,
                    "contract": contract,
                    "lock": lock,
                    "lock_sha": lock_sha,
                    "app": app,
                    "package": package,
                    "pins": pins,
                    "contracts": contracts,
                    "all_pins": all_pins,
                    "arch": arch,
                }

    @staticmethod
    def _generate(fixture):
        return receipt.generate_receipt(
            fixture["app"], fixture["lock"], fixture["lock_sha"],
            fixture["tarball"], fixture["arch"],
        )

    def test_generate_validate_verify_and_native_claims(self) -> None:
        with self._fixture() as fixture:
            payload, raw = self._generate(fixture)
            self.assertEqual(payload["schema"], receipt.SCHEMA)
            self.assertEqual(len(payload["files"]), 15)
            self.assertEqual(
                payload["package_inventory"]["native_file_count"], 10
            )
            self.assertEqual(receipt.validate_receipt(payload, raw, "arm64"), payload)
            claims = receipt.verify_app(fixture["app"], payload, raw, "arm64")
            self.assertEqual(len(claims), 10)
            self.assertEqual(set(claims), {
                receipt._final_app_path(path, "arm64")
                for path in receipt.NATIVE_FILES
            })
            self.assertTrue(all(
                claim.source_manifest_sha256 == payload["source_manifest_sha256"]
                for claim in claims.values()
            ))

    def test_exact_package_lock_entry_and_authenticated_digest(self) -> None:
        with self._fixture() as fixture:
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "raw SHA256"
            ):
                receipt.generate_receipt(
                    fixture["app"], fixture["lock"], "0" * 64,
                    fixture["tarball"], "arm64",
                )
            payload = self._lock_payload(fixture["contract"])
            payload["packages"][fixture["contract"].lock_key]["license"] = "GPL"
            fixture["lock"].write_text(json.dumps(payload), encoding="utf-8")
            fixture["lock_sha"] = hashlib.sha256(fixture["lock"].read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "keys must be exactly"
            ):
                self._generate(fixture)

    def test_lockfile_duplicate_key_rejected(self) -> None:
        with self._fixture() as fixture:
            contract = fixture["contract"]
            raw = (
                '{"packages":{"%s":{"version":"4.0.507",'
                '"version":"4.0.507","resolved":"%s","integrity":"%s",'
                '"cpu":["arm64"],"optional":true,"os":["darwin"]},'
                '"node_modules/@remotion/renderer":{"optionalDependencies":'
                '{"%s":"4.0.507"}}}}'
                % (contract.lock_key, contract.resolved, contract.integrity,
                   contract.package_name)
            ).encode()
            fixture["lock"].write_bytes(raw)
            fixture["lock_sha"] = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "duplicate JSON key"
            ):
                self._generate(fixture)

    def test_tarball_extra_member_rejected_even_with_authenticated_tar(self) -> None:
        with self._fixture() as fixture:
            altered = fixture["root"] / "extra.tgz"
            self._tarball(altered, fixture["files"], extra="surprise.bin")
            raw = altered.read_bytes()
            changed = dataclasses.replace(
                fixture["contract"],
                tarball_sha256=hashlib.sha256(raw).hexdigest(),
                tarball_bytes=len(raw),
            )
            contracts = dict(fixture["contracts"])
            contracts["arm64"] = changed
            with mock.patch.object(
                receipt, "ARCH_CONTRACTS", MappingProxyType(contracts)
            ):
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError, "tarball inventory drifted"
                ):
                    receipt.generate_receipt(
                        fixture["app"], fixture["lock"], fixture["lock_sha"],
                        altered, "arm64",
                    )

    def test_tarball_link_member_rejected(self) -> None:
        with self._fixture() as fixture:
            altered = fixture["root"] / "link.tgz"
            files = dict(fixture["files"])
            files.pop("README.md")
            self._tarball(altered, files, link="package.json")
            raw = altered.read_bytes()
            changed = dataclasses.replace(
                fixture["contract"],
                tarball_sha256=hashlib.sha256(raw).hexdigest(),
                tarball_bytes=len(raw),
            )
            contracts = dict(fixture["contracts"])
            contracts["arm64"] = changed
            with mock.patch.object(
                receipt, "ARCH_CONTRACTS", MappingProxyType(contracts)
            ):
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError, "not a regular file"
                ):
                    receipt.generate_receipt(
                        fixture["app"], fixture["lock"], fixture["lock_sha"],
                        altered, "arm64",
                    )

    def test_final_extra_missing_and_case_drift_rejected(self) -> None:
        for mutation in ("extra", "missing", "case"):
            with self.subTest(mutation=mutation), self._fixture() as fixture:
                if mutation == "extra":
                    (fixture["package"] / "extra.bin").write_bytes(b"extra")
                elif mutation == "missing":
                    (fixture["package"] / "README.md").unlink()
                else:
                    (fixture["package"] / "README.md").rename(
                        fixture["package"] / "readme.md"
                    )
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError, "package inventory drifted"
                ):
                    self._generate(fixture)

    def test_final_symlink_and_hardlink_rejected(self) -> None:
        for mutation in ("symlink", "hardlink"):
            with self.subTest(mutation=mutation), self._fixture() as fixture:
                target = fixture["package"] / "README.md"
                raw = target.read_bytes()
                target.unlink()
                outside = fixture["root"] / "outside"
                outside.write_bytes(raw)
                if mutation == "symlink":
                    target.symlink_to(outside)
                else:
                    os.link(outside, target)
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError,
                    "regular file|one link",
                ):
                    self._generate(fixture)

    def test_parent_and_package_symlinks_rejected(self) -> None:
        with self._fixture() as fixture:
            package = fixture["package"]
            real = package.with_name("real-package")
            package.rename(real)
            package.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "not a real directory"
            ):
                self._generate(fixture)

    def test_case_and_unicode_aliases_fail_before_path_selection(self) -> None:
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError, "case-colliding"
        ):
            receipt._validate_names(
                ["README.md", "readme.md"], "fixture directory"
            )
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError, "invalid path name"
        ):
            receipt._validate_names(
                ["caf\N{LATIN SMALL LETTER E WITH ACUTE}.js",
                 "cafe\N{COMBINING ACUTE ACCENT}.js"],
                "fixture directory",
            )

    def test_nonnative_byte_drift_rejected(self) -> None:
        with self._fixture() as fixture:
            (fixture["package"] / "index.js").write_bytes(b"changed")
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "data file differs"
            ):
                self._generate(fixture)

    def test_final_modes_require_source_executability_and_no_world_write(self) -> None:
        for name, mode, pattern in (
            ("ffmpeg", 0o644, "not executable"),
            ("README.md", 0o646, "world-writable"),
        ):
            with self.subTest(name=name, mode=oct(mode)), self._fixture() as fixture:
                (fixture["package"] / name).chmod(mode)
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError, pattern
                ):
                    self._generate(fixture)

    def test_receipt_binds_final_mode_to_authenticated_source_mode(self) -> None:
        with self._fixture() as fixture:
            payload, _ = self._generate(fixture)
            path = receipt._final_app_path("ffmpeg", "arm64")
            changed = json.loads(receipt.canonical_json_bytes(payload))
            changed["files"][path]["mode"] = "0644"
            changed["package_inventory"]["sha256"] = hashlib.sha256(
                receipt.canonical_json_bytes(changed["files"])
            ).hexdigest()
            raw = receipt.canonical_json_bytes(changed)
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "path metadata drifted"
            ):
                receipt.validate_receipt(changed, raw, "arm64")

    def test_native_architecture_uuid_and_normalized_drift_rejected(self) -> None:
        for mutation in ("architecture", "uuid", "bytes"):
            with self.subTest(mutation=mutation), self._fixture() as fixture:
                path = fixture["package"] / "ffmpeg"
                if mutation == "architecture":
                    path.write_bytes(self._macho("x64", "executable", 1))
                    pattern = "architecture or kind"
                elif mutation == "uuid":
                    path.write_bytes(self._macho("arm64", "executable", 99))
                    pattern = "differs beyond"
                else:
                    path.write_bytes(path.read_bytes() + b"drift")
                    pattern = "LINKEDIT bounds|differs beyond"
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError, pattern
                ):
                    self._generate(fixture)

    def test_signature_only_raw_drift_is_accepted_by_comparison(self) -> None:
        source = receipt.FileObservation(
            "ffmpeg", 10, "a" * 64, 0o755, b"source", "arm64",
            "executable", "A" * 8 + "-AAAA-AAAA-AAAA-" + "A" * 12,
            4, "c" * 64,
        )
        final = dataclasses.replace(source, byte_count=20, sha256="b" * 64, raw=b"signed")
        data_source = receipt.FileObservation(
            "README.md", 2, hashlib.sha256(b"ok").hexdigest(), 0o644, b"ok"
        )
        data_final = dataclasses.replace(data_source)
        source_files = {name: data_source for name in receipt.EXPECTED_FILES}
        final_files = {name: data_final for name in receipt.EXPECTED_FILES}
        for name in receipt.NATIVE_FILES:
            kind = "executable" if name in receipt.EXECUTABLE_FILES else "dylib"
            native_source = dataclasses.replace(source, path=name, kind=kind)
            source_files[name] = native_source
            final_files[name] = dataclasses.replace(
                final, path=name, kind=kind
            )
        receipt._assert_final_matches_source(final_files, source_files)

    def test_unsigned_vmsize_and_appended_bytes_are_never_masked(self) -> None:
        source = self._macho("arm64", "executable", 1)
        changed_vmsize = bytearray(source)
        linkedit_vmsize_offset = 32 + 24 + 32
        current = struct.unpack_from(
            "<Q", changed_vmsize, linkedit_vmsize_offset
        )[0]
        struct.pack_into(
            "<Q", changed_vmsize, linkedit_vmsize_offset,
            current + 16 * 1024,
        )
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError, "noncanonical __LINKEDIT vmsize"
        ):
            receipt._normalize_macho_bytes(
                bytes(changed_vmsize), "changed vmsize", current
            )
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError, "terminal Mach-O __LINKEDIT"
        ):
            receipt._normalize_macho_bytes(
                source + b"appended", "appended bytes", current
            )

    def test_codesign_retained_zero_padding_uses_the_pinned_unsigned_extent(self) -> None:
        raw, _, expected_bytes = self._signed_macho_with_alignment_padding()
        metadata = receipt._parse_macho(raw, "signed fixture")
        canonical = receipt._canonicalize_signed_macho(
            raw,
            metadata,
            "signed fixture",
            16 * 1024,
            expected_bytes,
        )
        self.assertEqual(len(canonical), expected_bytes)
        normalized = receipt._parse_macho(canonical, "canonical fixture")
        self.assertEqual(
            normalized.linkedit_file_size,
            expected_bytes - normalized.linkedit_file_offset,
        )

    def test_codesign_nonzero_alignment_padding_is_never_masked(self) -> None:
        raw, _, expected_bytes = self._signed_macho_with_alignment_padding()
        hostile = bytearray(raw)
        hostile[expected_bytes] = 1
        metadata = receipt._parse_macho(bytes(hostile), "hostile signed fixture")
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError,
            "non-zero code-signature alignment padding",
        ):
            receipt._canonicalize_signed_macho(
                bytes(hostile),
                metadata,
                "hostile signed fixture",
                16 * 1024,
                expected_bytes,
            )

    def test_in_memory_signature_normalization_preserves_non_signature_drift(self) -> None:
        raw, _, expected_bytes = self._signed_macho_with_alignment_padding()
        metadata = receipt._parse_macho(raw, "signed fixture")
        canonical = receipt._canonicalize_signed_macho(
            raw, metadata, "signed fixture", 16 * 1024, expected_bytes
        )
        hostile = bytearray(raw)
        hostile[metadata.linkedit_file_offset] ^= 1
        hostile_metadata = receipt._parse_macho(
            bytes(hostile), "hostile signed fixture"
        )
        hostile_canonical = receipt._canonicalize_signed_macho(
            bytes(hostile),
            hostile_metadata,
            "hostile signed fixture",
            16 * 1024,
            expected_bytes,
        )
        self.assertNotEqual(hostile_canonical, canonical)

    def test_nonterminal_code_signature_command_is_rejected_for_remotion(self) -> None:
        raw, _, _ = self._signed_macho_with_alignment_padding()
        hostile = raw[:56] + raw[128:144] + raw[56:128] + raw[144:]
        metadata = receipt._parse_macho(hostile, "nonterminal signature")
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError,
            "LC_CODE_SIGNATURE is not the terminal load command",
        ):
            receipt._canonicalize_signed_macho(
                hostile,
                metadata,
                "nonterminal signature",
                16 * 1024,
                len(hostile) - 40,
            )

    def test_generic_nonterminal_code_signature_is_removed_in_place(self) -> None:
        terminal, _, _ = self._signed_macho_with_alignment_padding()
        nonterminal = (
            terminal[:56] + terminal[128:144] + terminal[56:128] + terminal[144:]
        )
        terminal_metadata = receipt._parse_macho(terminal, "terminal signature")
        nonterminal_metadata = receipt._parse_macho(
            nonterminal, "generic nonterminal signature"
        )
        terminal_canonical = receipt._canonicalize_signed_macho(
            terminal,
            terminal_metadata,
            "terminal signature",
            general_codesign_layout=True,
        )
        nonterminal_canonical = receipt._canonicalize_signed_macho(
            nonterminal,
            nonterminal_metadata,
            "generic nonterminal signature",
            general_codesign_layout=True,
        )
        self.assertEqual(nonterminal_canonical, terminal_canonical)
        old_command_end = 32 + nonterminal_metadata.command_bytes
        self.assertEqual(
            nonterminal_canonical[old_command_end:],
            nonterminal[old_command_end:len(nonterminal_canonical)],
        )
        self.assertEqual(
            receipt._parse_macho(
                nonterminal_canonical,
                "canonical generic nonterminal signature",
                allow_exact_vmsize=True,
            ).linkedit_file_offset,
            nonterminal_metadata.linkedit_file_offset,
        )
        self.assertEqual(
            nonterminal_canonical[old_command_end - 16:old_command_end],
            b"\0" * 16,
        )

        hostile = bytearray(nonterminal)
        hostile[56 + 16 + 68] ^= 1
        hostile_metadata = receipt._parse_macho(
            bytes(hostile), "generic command drift"
        )
        hostile_canonical = receipt._canonicalize_signed_macho(
            bytes(hostile),
            hostile_metadata,
            "generic command drift",
            general_codesign_layout=True,
        )
        self.assertNotEqual(hostile_canonical, terminal_canonical)

    def test_real_generic_nonterminal_signature_is_normalized_when_available(self) -> None:
        candidates = sorted(Path("/private/tmp").glob(
            "autoeditor-normalizer-proof.*/stage/*/_internal/**/"
            "libbrotlidec.1.2.0.dylib"
        ))
        if not candidates:
            self.skipTest("audited nonterminal signed dylib is not present")
        raw = candidates[0].read_bytes()
        metadata = receipt._parse_macho(
            raw,
            "real generic nonterminal signature",
            require_uuid=False,
            allow_exact_vmsize=True,
        )
        self.assertLess(
            metadata.code_signature_command_offset + 16,
            32 + metadata.command_bytes,
        )
        normalized = receipt._normalize_macho_bytes(
            raw,
            "real generic nonterminal signature",
            max_bytes=receipt.MAX_PACKAGE_BYTES,
            require_uuid=False,
            general_codesign_layout=True,
        )
        normalized_metadata = receipt._parse_macho(
            normalized,
            "normalized real generic nonterminal signature",
            require_uuid=False,
            allow_exact_vmsize=True,
        )
        self.assertFalse(normalized_metadata.has_code_signature)
        self.assertEqual(
            normalized_metadata.command_count,
            metadata.command_count - 1,
        )
        self.assertEqual(
            normalized_metadata.command_bytes,
            metadata.command_bytes - 16,
        )
        with tempfile.TemporaryDirectory(
            prefix="autoeditor-generic-nonterminal-", dir="/private/tmp"
        ) as temporary:
            resigned_receipts = []
            for index, identifier in enumerate((
                "com.marabha.autoeditor.nonterminal.one",
                "com.marabha.autoeditor.nonterminal.two",
            )):
                resigned = Path(temporary) / f"libbrotlidec-{index}.dylib"
                shutil.copy2(candidates[0], resigned)
                completed = subprocess.run(
                    [
                        receipt.CODESIGN_PATH,
                        "--force",
                        "--sign",
                        "-",
                        "--identifier",
                        identifier,
                        "--timestamp=none",
                        str(resigned),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                resigned_receipts.append(receipt._normalize_macho_bytes(
                    resigned.read_bytes(),
                    f"resigned real generic nonterminal signature {index}",
                    max_bytes=receipt.MAX_PACKAGE_BYTES,
                    require_uuid=False,
                    general_codesign_layout=True,
                ))
            self.assertEqual(resigned_receipts, [normalized, normalized])

    def test_receipt_canonicality_manifest_binding_and_authentication(self) -> None:
        with self._fixture() as fixture:
            payload, raw = self._generate(fixture)
            path = fixture["root"] / "receipt.json"
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            loaded, loaded_raw = receipt.load_authenticated_receipt(
                path, digest, "arm64"
            )
            self.assertEqual(loaded, payload)
            self.assertEqual(loaded_raw, raw)
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "raw SHA256"
            ):
                receipt.load_authenticated_receipt(path, "0" * 64, "arm64")

            changed = json.loads(raw)
            changed["source_manifest"]["package_lock"]["sha256"] = "0" * 64
            changed_raw = receipt.canonical_json_bytes(changed)
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "source manifest digest"
            ):
                receipt.validate_receipt(changed, changed_raw, "arm64")

            noncanonical = json.dumps(payload).encode()
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "not canonical"
            ):
                receipt.validate_receipt(payload, noncanonical, "arm64")

    def test_receipt_rejects_final_claim_and_extra_key_forgery(self) -> None:
        with self._fixture() as fixture:
            payload, _ = self._generate(fixture)
            path = receipt._final_app_path("ffmpeg", "arm64")
            changed = json.loads(receipt.canonical_json_bytes(payload))
            changed["files"][path]["normalized_sha256"] = "0" * 64
            changed["package_inventory"]["sha256"] = hashlib.sha256(
                receipt.canonical_json_bytes(changed["files"])
            ).hexdigest()
            raw = receipt.canonical_json_bytes(changed)
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "normalized claim"
            ):
                receipt.validate_receipt(changed, raw, "arm64")

            changed = json.loads(receipt.canonical_json_bytes(payload))
            changed["unexpected"] = True
            raw = receipt.canonical_json_bytes(changed)
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "keys must be exactly"
            ):
                receipt.validate_receipt(changed, raw, "arm64")

    def test_verify_detects_final_raw_byte_drift(self) -> None:
        with self._fixture() as fixture:
            payload, raw = self._generate(fixture)
            path = fixture["package"] / "README.md"
            path.write_bytes(b"post-receipt drift")
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "differs from receipt"
            ):
                receipt.verify_app(fixture["app"], payload, raw, "arm64")

    def test_generation_rejects_a_tree_change_between_scans(self) -> None:
        with self._fixture() as fixture:
            observed = receipt._scan_final_package(fixture["app"], "arm64")
            changed = dict(observed)
            changed["README.md"] = dataclasses.replace(
                observed["README.md"], sha256="0" * 64
            )
            with mock.patch.object(
                receipt,
                "_scan_final_package",
                side_effect=[observed, changed],
            ):
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError,
                    "inputs changed while generating",
                ):
                    self._generate(fixture)

    def test_o_excl_receipt_write_never_overwrites(self) -> None:
        with self._fixture() as fixture:
            _, raw = self._generate(fixture)
            output = fixture["root"] / "receipt.json"
            receipt.write_new_receipt(output, raw)
            original = output.read_bytes()
            with self.assertRaisesRegex(
                receipt.MacRemotionReceiptError, "cannot create"
            ):
                receipt.write_new_receipt(output, raw)
            self.assertEqual(output.read_bytes(), original)

    def test_failed_receipt_write_leaves_exclusive_path_in_place(self) -> None:
        with self._fixture() as fixture:
            _, raw = self._generate(fixture)
            output = fixture["root"] / "failed.json"
            real_write = os.write
            calls = 0

            def fail_after_prefix(fd: int, data) -> int:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_write(fd, bytes(data[:7]))
                raise OSError("fixture failure")

            with mock.patch.object(receipt.os, "write", side_effect=fail_after_prefix):
                with self.assertRaisesRegex(
                    receipt.MacRemotionReceiptError, "cannot create"
                ):
                    receipt.write_new_receipt(output, raw)
            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes(), raw[:7])
            with self.assertRaises(receipt.MacRemotionReceiptError):
                receipt.write_new_receipt(output, raw)

    def test_real_pins_match_available_npm_tarballs(self) -> None:
        candidates = {
            "arm64": Path(
                "/private/tmp/remotion-mac-contract.p53vPf/"
                "remotion-compositor-darwin-arm64-4.0.507.tgz"
            ),
            "x64": Path(
                "/private/tmp/remotion-mac-contract.p53vPf/"
                "remotion-compositor-darwin-x64-4.0.507.tgz"
            ),
        }
        if not all(path.exists() for path in candidates.values()):
            self.skipTest("audited npm tarballs are not present")
        for arch, path in candidates.items():
            with self.subTest(arch=arch):
                observed = receipt._read_source_tarball(path, arch)
                self.assertEqual(set(observed), receipt.EXPECTED_FILES)
                self.assertEqual(
                    sum(item.path in receipt.NATIVE_FILES for item in observed.values()),
                    10,
                )

    def test_invalid_real_signature_is_rejected_before_normalization(self) -> None:
        source = Path(
            "/private/tmp/remotion-arm64-inventory.wj9nI0/package/ffmpeg"
        )
        if not source.exists():
            self.skipTest("audited signed arm64 package is not present")
        raw = bytearray(source.read_bytes())
        raw[4096] ^= 1
        pin = receipt.PINNED_SOURCE_FILES["arm64"]["ffmpeg"]
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError,
            "strict codesign verification failed",
        ):
            receipt._normalize_macho_bytes(
                bytes(raw), "invalid signed ffmpeg",
                pin.normalized_linkedit_vmsize,
            )

    def test_signed_vmsize_and_signature_suffix_must_be_exact(self) -> None:
        source = Path(
            "/private/tmp/remotion-arm64-inventory.wj9nI0/package/ffmpeg"
        )
        if not source.exists():
            self.skipTest("audited signed arm64 package is not present")
        raw = source.read_bytes()
        metadata = receipt._parse_macho(raw, "signed ffmpeg")
        changed_vmsize = bytearray(raw)
        struct.pack_into(
            "<Q",
            changed_vmsize,
            metadata.linkedit_vmsize_offset,
            metadata.linkedit_vm_size + 16 * 1024,
        )
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError,
            "exact terminal __LINKEDIT suffix",
        ):
            receipt._parse_macho(bytes(changed_vmsize), "changed vmsize")
        with self.assertRaisesRegex(
            receipt.MacRemotionReceiptError,
            "terminal Mach-O __LINKEDIT",
        ):
            receipt._parse_macho(raw + b"appended", "appended after signature")

    def test_real_resigned_packages_generate_and_verify(self) -> None:
        tarballs = {
            "arm64": Path(
                "/private/tmp/remotion-mac-contract.p53vPf/"
                "remotion-compositor-darwin-arm64-4.0.507.tgz"
            ),
            "x64": Path(
                "/private/tmp/remotion-mac-contract.p53vPf/"
                "remotion-compositor-darwin-x64-4.0.507.tgz"
            ),
        }
        sources = {
            "arm64": Path(
                "/private/tmp/remotion-arm64-inventory.wj9nI0/package"
            ),
            "x64": Path(
                "/private/tmp/remotion-x64-inventory.HS6YOu/package"
            ),
        }
        lock = ROOT / "packaging" / "helper-runtime" / "package-lock.json"
        if not (
            lock.exists()
            and all(path.exists() for path in tarballs.values())
            and all(path.exists() for path in sources.values())
        ):
            self.skipTest("audited real Remotion inputs are not present")
        lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for arch in ("arm64", "x64"):
                contract = receipt.ARCH_CONTRACTS[arch]
                app = root / arch / "AutoEditor Helper.app"
                package = self._package_root(app, contract)
                package.mkdir(parents=True)
                for source in sources[arch].iterdir():
                    shutil.copy2(source, package / source.name)
                for name in receipt.NATIVE_FILES:
                    completed = subprocess.run(
                        [
                            receipt.CODESIGN_PATH,
                            "--force",
                            "--sign",
                            "-",
                            "--timestamp=none",
                            str(package / name),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                payload, raw = receipt.generate_receipt(
                    app, lock, lock_sha, tarballs[arch], arch
                )
                claims = receipt.verify_app(app, payload, raw, arch)
                self.assertEqual(len(claims), 10)


if __name__ == "__main__":
    unittest.main()
