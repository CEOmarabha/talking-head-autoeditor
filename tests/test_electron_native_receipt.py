from __future__ import annotations

import copy
import hashlib
import io
import importlib.util
import json
import os
import stat
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "electron_native_receipt.py"
SPEC = importlib.util.spec_from_file_location("electron_native_receipt", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load Electron native receipt module: {SCRIPT}")
receipt = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = receipt
SPEC.loader.exec_module(receipt)


class ElectronNativeReceiptTests(unittest.TestCase):
    @staticmethod
    def _windows_archive(marker: bytes) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as bundle:
            for name in receipt.WINDOWS_ARCHIVE_NAMES:
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o644 << 16
                bundle.writestr(info, marker + b":" + name.encode("ascii"))
        return output.getvalue()

    @staticmethod
    def _pe(*, certificate: bytes = b"", bad_certificate_offset: bool = False) -> bytes:
        data = bytearray(0x400)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 1, 7, 0, 0, 0xF0, 0x22)
        optional = 0x98
        struct.pack_into("<H", data, optional, 0x20B)
        struct.pack_into("<I", data, optional + 32, 0x1000)
        struct.pack_into("<I", data, optional + 36, 0x200)
        struct.pack_into("<I", data, optional + 56, 0x2000)
        struct.pack_into("<I", data, optional + 60, 0x200)
        struct.pack_into("<I", data, optional + 64, 0x12345678 if certificate else 0)
        struct.pack_into("<I", data, optional + 108, 16)
        section = optional + 0xF0
        data[section : section + 8] = b".text\0\0\0"
        struct.pack_into("<IIIIIIHHI", data, section + 8, 0x200, 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0x60000020)
        data[0x200:0x208] = b"CODEDATA"
        if certificate:
            offset = 0x3F8 if bad_certificate_offset else 0x400
            struct.pack_into("<II", data, optional + 112 + 4 * 8, offset, len(certificate))
            data.extend(certificate)
        return bytes(data)

    @staticmethod
    def _resource_pe(payload: bytes, *, hostile_gap: bool = False) -> bytes:
        resource_size = 0x80 + len(payload)
        data = bytearray(0x400)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 1, 0, 0, 0, 0xF0, 0x22)
        optional = 0x98
        struct.pack_into("<H", data, optional, 0x20B)
        struct.pack_into("<I", data, optional + 32, 0x1000)
        struct.pack_into("<I", data, optional + 36, 0x200)
        struct.pack_into("<I", data, optional + 56, 0x2000)
        struct.pack_into("<I", data, optional + 60, 0x200)
        struct.pack_into("<I", data, optional + 108, 16)
        struct.pack_into("<II", data, optional + 112 + 2 * 8, 0x1000, resource_size)
        section = optional + 0xF0
        data[section : section + 8] = b".rsrc\0\0\0"
        struct.pack_into("<IIIIIIHHI", data, section + 8, resource_size, 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0x40000040)
        base = 0x200
        struct.pack_into("<IIHHHH", data, base, 0, 0, 0, 0, 0, 1)
        struct.pack_into("<II", data, base + 16, 24, 0x80000020)
        struct.pack_into("<IIHHHH", data, base + 0x20, 0, 0, 0, 0, 0, 1)
        struct.pack_into("<II", data, base + 0x30, 1, 0x80000040)
        struct.pack_into("<IIHHHH", data, base + 0x40, 0, 0, 0, 0, 0, 1)
        struct.pack_into("<II", data, base + 0x50, 1033, 0x60)
        struct.pack_into("<IIII", data, base + 0x60, 0x1080, len(payload), 0, 0)
        if hostile_gap:
            data[base + 0x70] = 0x41
        data[base + 0x80 : base + 0x80 + len(payload)] = payload
        return bytes(data)

    @staticmethod
    def _resedit_layout_pe(
        *,
        rsrc_virtual_size: int,
        rsrc_raw_size: int,
        reloc_virtual_address: int,
        reloc_raw_pointer: int,
    ) -> bytes:
        data = bytearray(reloc_raw_pointer + 0x200)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 2, 7, 0, 0, 0xF0, 0x22)
        optional = 0x98
        struct.pack_into("<H", data, optional, 0x20B)
        struct.pack_into("<I", data, optional + 32, 0x1000)
        struct.pack_into("<I", data, optional + 36, 0x200)
        struct.pack_into(
            "<I",
            data,
            optional + 56,
            receipt._align(reloc_virtual_address + 0x100, 0x1000),
        )
        struct.pack_into("<I", data, optional + 60, 0x200)
        struct.pack_into("<I", data, optional + 108, 16)
        struct.pack_into(
            "<II", data, optional + 112 + 2 * 8, 0x1000, rsrc_virtual_size
        )
        struct.pack_into(
            "<II", data, optional + 112 + 5 * 8, reloc_virtual_address, 0x100
        )
        rsrc = optional + 0xF0
        data[rsrc : rsrc + 8] = b".rsrc\0\0\0"
        struct.pack_into(
            "<IIIIIIHHI",
            data,
            rsrc + 8,
            rsrc_virtual_size,
            0x1000,
            rsrc_raw_size,
            0x200,
            0,
            0,
            0,
            0,
            0x40000040,
        )
        reloc = rsrc + 40
        data[reloc : reloc + 8] = b".reloc\0\0"
        struct.pack_into(
            "<IIIIIIHHI",
            data,
            reloc + 8,
            0x100,
            reloc_virtual_address,
            0x200,
            reloc_raw_pointer,
            0,
            0,
            0,
            0,
            0x42000040,
        )
        data[0x200 : 0x200 + rsrc_raw_size] = b"R" * rsrc_raw_size
        data[reloc_raw_pointer : reloc_raw_pointer + 0x200] = b"L" * 0x200
        return bytes(data)

    @staticmethod
    def _macho(*, signature_bytes: int, linkedit_vmsize: int, code_byte: int = 0x41) -> bytes:
        text = struct.pack(
            "<II16sQQQQIIII",
            0x19,
            72,
            b"__TEXT".ljust(16, b"\0"),
            0x100000000,
            0x1000,
            0,
            0x1000,
            7,
            5,
            0,
            0,
        )
        linkedit = struct.pack(
            "<II16sQQQQIIII",
            0x19,
            72,
            b"__LINKEDIT".ljust(16, b"\0"),
            0x100001000,
            linkedit_vmsize,
            0x1000,
            0x40 + signature_bytes,
            1,
            1,
            0,
            0,
        )
        signature = struct.pack("<IIII", 0x1D, 16, 0x1040, signature_bytes)
        header = struct.pack("<IIIIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 3, len(text + linkedit + signature), 0, 0)
        raw = bytearray(header + text + linkedit + signature)
        raw.extend(b"\0" * (0x1000 - len(raw)))
        raw.extend(bytes([code_byte]) * 0x40)
        raw.extend(b"S" * signature_bytes)
        return bytes(raw)

    @staticmethod
    def _receipt_payload(target: str = "windows-x64") -> dict:
        files = {}
        for source, final in receipt._mappings(target):
            files[final] = {
                "canonical_bytes": 1,
                "canonical_sha256": "c" * 64,
                "component": receipt._component(final, target),
                "final": {"bytes": 1, "mode": 0o644, "sha256": "f" * 64},
                "mapping": {"archive_path": source, "final_path": final},
                "normalization": {"kind": "fixture"},
                "source": {"bytes": 1, "mode": 0o644, "sha256": "e" * 64},
            }
        return {
            "archive": copy.deepcopy(receipt.ARCHIVE_RECORDS[target]),
            "configuration": {
                "builder_config_sha256": "b" * 64,
                "copyright": receipt.COPYRIGHT,
                "electron_builder": "26.15.3",
                "icon_bytes": 1,
                "icon_sha256": receipt.ICON_SHA256,
                "package_manifest_sha256": "d" * 64,
                "product_name": receipt.PRODUCT_NAME,
                "version": "0.1.0",
                "version_quad": [0, 1, 0, 0],
            },
            "electron_version": receipt.ELECTRON_VERSION,
            "files": files,
            "schema": receipt.SCHEMA,
            "source_lock_sha256": receipt.SOURCE_LOCK_SHA256,
            "target": target,
        }

    def test_authenticode_normalization_is_terminal_and_exact(self):
        unsigned_raw = self._pe()
        certificate = b"C" * 32
        signed_raw = self._pe(certificate=certificate)
        unsigned = receipt._parse_pe(unsigned_raw, "unsigned")
        signed = receipt._parse_pe(signed_raw, "signed")
        normalized, details = receipt._normalized_pe(signed)
        self.assertEqual(normalized, unsigned_raw)
        self.assertEqual(details["authenticode"], "present")
        self.assertEqual(details["certificate_sha256"], hashlib.sha256(certificate).hexdigest())
        with self.assertRaisesRegex(receipt.ElectronNativeReceiptError, "non-terminal Authenticode"):
            receipt._parse_pe(self._pe(certificate=certificate, bad_certificate_offset=True), "hostile")
        with self.assertRaisesRegex(
            receipt.ElectronNativeReceiptError,
            "archive electron.exe unexpectedly has Authenticode",
        ):
            receipt._windows_root_transformation(
                signed_raw,
                unsigned_raw,
                b"fixture-icon",
                {},
                Path("."),
            )

    def test_archive_members_use_authenticated_buffer_after_atomic_path_swap(self):
        trusted = self._windows_archive(b"trusted")
        hostile = self._windows_archive(b"hostile")
        filename = receipt.ARCHIVE_RECORDS["windows-x64"]["filename"]
        record = {
            "bytes": len(trusted),
            "filename": filename,
            "sha256": hashlib.sha256(trusted).hexdigest(),
        }
        real_read = receipt._read_regular
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / filename
            hostile_path = Path(td) / "hostile.zip"
            archive_path.write_bytes(trusted)
            hostile_path.write_bytes(hostile)

            def authenticate_then_swap(path, label, maximum):
                authenticated = real_read(path, label, maximum)
                os.replace(hostile_path, archive_path)
                return authenticated

            with mock.patch.dict(
                receipt.ARCHIVE_RECORDS,
                {"windows-x64": record},
            ), mock.patch.object(
                receipt,
                "_read_regular",
                side_effect=authenticate_then_swap,
            ):
                members, authenticated = receipt._archive_members(
                    archive_path,
                    "windows-x64",
                )

        self.assertEqual(authenticated.raw, trusted)
        self.assertEqual(set(members), set(receipt.WINDOWS_ARCHIVE_NAMES))
        for member in members.values():
            self.assertTrue(member.raw.startswith(b"trusted:"))

    def test_resource_parser_rejects_unowned_rsrc_bytes(self):
        image = receipt._parse_pe(self._resource_pe(b"manifest"), "resource")
        leaves = receipt._resource_leaves(image)
        self.assertEqual(leaves[(24, 1, 1033)].data, b"manifest")
        hostile = receipt._parse_pe(self._resource_pe(b"manifest", hostile_gap=True), "hostile")
        with self.assertRaisesRegex(receipt.ElectronNativeReceiptError, "unowned nonzero"):
            receipt._resource_leaves(hostile)

    def test_windows_version_info_matches_real_builder_26_dictionary(self):
        actual_strings = {
            "CompanyName": "GitHub, Inc.",
            "FileDescription": "AutoEditor Helper",
            "FileVersion": "0.1.0",
            "InternalName": "AutoEditor Helper",
            "LegalCopyright": "Copyright © 2026 Omar Marabha (@CEOmarabha)",
            "OriginalFilename": "",
            "ProductName": "AutoEditor Helper",
            "ProductVersion": "0.1.0.0",
            "SquirrelAwareVersion": "1",
        }
        integrity_sha = "a" * 64
        final_leaves = {
            (3, 1, 1033): receipt._ResourceLeaf((3, 1, 1033), 0, b"icon"),
            (14, 1, 1033): receipt._ResourceLeaf((14, 1, 1033), 0, b"group"),
            (16, 1, 1033): receipt._ResourceLeaf((16, 1, 1033), 1200, b"version"),
            ("INTEGRITY", "ELECTRONASAR", 1033): receipt._ResourceLeaf(
                ("INTEGRITY", "ELECTRONASAR", 1033),
                1200,
                receipt.canonical_json_bytes(
                    [
                        {
                            "alg": "SHA256",
                            "file": "resources\\app.asar",
                            "value": integrity_sha,
                        }
                    ]
                ),
            ),
        }
        configuration = {"version": "0.1.0", "version_quad": [0, 1, 0, 0]}
        asar = receipt._FileData(b"asar", 0o644, hashlib.sha256(b"asar").hexdigest())

        def validate(strings: dict[str, str]) -> dict:
            with mock.patch.object(
                receipt,
                "_icon_payloads",
                return_value=([b"icon"], b"group"),
            ), mock.patch.object(
                receipt,
                "_decode_version",
                return_value=((0, 1, 0, 0), strings),
            ), mock.patch.object(
                receipt,
                "_read_regular",
                return_value=asar,
            ), mock.patch.object(
                receipt,
                "_asar_header_sha256",
                return_value=integrity_sha,
            ), mock.patch.object(
                receipt,
                "_packed_asar_paths",
                return_value=("resources/app.asar",),
            ):
                return receipt._validate_windows_resources(
                    None,
                    None,
                    b"fixture-icon",
                    configuration,
                    Path("."),
                    source_leaves={},
                    final_leaves=final_leaves,
                )

        self.assertEqual(validate(actual_strings)["version_strings"], actual_strings)
        drifted = dict(actual_strings, CompanyName="Omar Marabha")
        with self.assertRaisesRegex(
            receipt.ElectronNativeReceiptError,
            "VERSIONINFO field drifted: CompanyName",
        ):
            validate(drifted)

    def test_windows_asar_integrity_binds_every_packed_asar(self):
        header_one = b'{"files":{"one":{}}}'
        header_two = b'{"files":{"two":{}}}'

        def asar(header: bytes) -> bytes:
            return (
                struct.pack("<IIII", 4, len(header) + 8, len(header) + 4, len(header))
                + header
                + b"payload"
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "resources" / "app.asar"
            second = root / "resources" / "creative-runtime" / "vendor.asar"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(asar(header_one))
            second.write_bytes(asar(header_two))
            integrity = [
                {
                    "alg": "SHA256",
                    "file": "resources\\app.asar",
                    "value": hashlib.sha256(header_one).hexdigest(),
                },
                {
                    "alg": "SHA256",
                    "file": "resources\\creative-runtime\\vendor.asar",
                    "value": hashlib.sha256(header_two).hexdigest(),
                },
            ]
            profiles = receipt._validate_asar_integrity(integrity, root)
            self.assertEqual(
                [profile["path"] for profile in profiles],
                ["resources/app.asar", "resources/creative-runtime/vendor.asar"],
            )
            integrity.pop()
            with self.assertRaisesRegex(
                receipt.ElectronNativeReceiptError,
                "inventory does not match",
            ):
                receipt._validate_asar_integrity(integrity, root)

    def test_resedit_growth_shifts_only_the_terminal_relocation_section(self):
        source_leaves = {
            (24, 1, 1033): receipt._ResourceLeaf((24, 1, 1033), 0, b"manifest")
        }
        final_leaves = {
            **source_leaves,
            ("INTEGRITY", "ELECTRONASAR", 1033): receipt._ResourceLeaf(
                ("INTEGRITY", "ELECTRONASAR", 1033),
                1200,
                b"integrity",
            ),
        }
        source = self._resedit_layout_pe(
            rsrc_virtual_size=0x180,
            rsrc_raw_size=0x200,
            reloc_virtual_address=0x2000,
            reloc_raw_pointer=0x400,
        )
        final = self._resedit_layout_pe(
            rsrc_virtual_size=0x280,
            rsrc_raw_size=0x400,
            reloc_virtual_address=0x2000,
            reloc_raw_pointer=0x600,
        )
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            receipt,
            "_validate_windows_resources",
            return_value={"fixture": "validated"},
        ), mock.patch.object(
            receipt,
            "_resource_leaves",
            side_effect=[source_leaves, final_leaves],
        ):
            canonical, details = receipt._windows_root_transformation(
                source,
                final,
                b"fixture-icon",
                {},
                Path(td),
            )
        self.assertEqual(canonical, final)
        self.assertEqual(details["resource_edit"], {"fixture": "validated"})

        hostile_suffix = bytearray(final)
        hostile_suffix[0x600] ^= 0x01
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            receipt,
            "_validate_windows_resources",
            return_value={"fixture": "validated"},
        ), mock.patch.object(
            receipt,
            "_resource_leaves",
            side_effect=[source_leaves, final_leaves],
        ), self.assertRaisesRegex(
            receipt.ElectronNativeReceiptError,
            "outside the exact resource rewrite",
        ):
            receipt._windows_root_transformation(
                source,
                bytes(hostile_suffix),
                b"fixture-icon",
                {},
                Path(td),
            )

        hostile_gap = self._resedit_layout_pe(
            rsrc_virtual_size=0x280,
            rsrc_raw_size=0x400,
            reloc_virtual_address=0x2000,
            reloc_raw_pointer=0x800,
        )
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            receipt,
            "_validate_windows_resources",
            return_value={"fixture": "validated"},
        ), mock.patch.object(
            receipt,
            "_resource_leaves",
            side_effect=[source_leaves, final_leaves],
        ), self.assertRaisesRegex(
            receipt.ElectronNativeReceiptError,
            r"exact \.rsrc raw growth",
        ):
            receipt._windows_root_transformation(
                source,
                hostile_gap,
                b"fixture-icon",
                {},
                Path(td),
            )

    def test_resedit_virtual_page_shrink_moves_only_relocation_rva(self):
        source_leaves = {
            (24, 1, 1033): receipt._ResourceLeaf((24, 1, 1033), 0, b"manifest")
        }
        final_leaves = {
            **source_leaves,
            ("INTEGRITY", "ELECTRONASAR", 1033): receipt._ResourceLeaf(
                ("INTEGRITY", "ELECTRONASAR", 1033),
                1200,
                b"integrity",
            ),
        }
        source = self._resedit_layout_pe(
            rsrc_virtual_size=0x1180,
            rsrc_raw_size=0x1200,
            reloc_virtual_address=0x3000,
            reloc_raw_pointer=0x1400,
        )
        final = self._resedit_layout_pe(
            rsrc_virtual_size=0xF80,
            rsrc_raw_size=0x1200,
            reloc_virtual_address=0x2000,
            reloc_raw_pointer=0x1400,
        )
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            receipt,
            "_validate_windows_resources",
            return_value={"fixture": "validated"},
        ), mock.patch.object(
            receipt,
            "_resource_leaves",
            side_effect=[source_leaves, final_leaves],
        ):
            canonical, _ = receipt._windows_root_transformation(
                source,
                final,
                b"fixture-icon",
                {},
                Path(td),
            )
        self.assertEqual(canonical, final)

    def test_resedit_raw_allocation_retains_larger_asar_integrity_pass(self):
        source_leaves = {
            (24, 1, 1033): receipt._ResourceLeaf((24, 1, 1033), 0, b"m")
        }
        final_leaves = {
            ("INTEGRITY", "ELECTRONASAR", 1033): receipt._ResourceLeaf(
                ("INTEGRITY", "ELECTRONASAR", 1033),
                1200,
                b"I" * 1200,
            )
        }
        self.assertEqual(
            receipt._expected_resedit_rsrc_raw_size(
                source_raw_size=0x200,
                final_virtual_size=0x280,
                file_alignment=0x200,
                source_leaves=source_leaves,
                final_leaves=final_leaves,
            ),
            0x600,
        )

    def test_macho_normalizes_only_signature_allocation_and_linkedit_rounding(self):
        source = self._macho(signature_bytes=0x40, linkedit_vmsize=0x4000)
        final = self._macho(signature_bytes=0x80, linkedit_vmsize=0x8000)
        source_canonical, _ = receipt._macho_canonical(source, "mac-arm64", "source")
        final_canonical, _ = receipt._macho_canonical(final, "mac-arm64", "final")
        self.assertEqual(source_canonical, final_canonical)
        hostile = self._macho(signature_bytes=0x80, linkedit_vmsize=0x8000, code_byte=0x42)
        hostile_canonical, _ = receipt._macho_canonical(hostile, "mac-arm64", "hostile")
        self.assertNotEqual(source_canonical, hostile_canonical)

    def test_authenticated_unsigned_x64_archive_matches_only_its_signed_form(self):
        final = bytearray(
            self._macho(signature_bytes=0x80, linkedit_vmsize=0x8000)
        )
        struct.pack_into("<I", final, 4, 0x01000007)
        signature_command = 32 + 72 + 72
        signature_offset, _ = struct.unpack_from(
            "<II", final, signature_command + 8
        )
        source = bytearray(final[:signature_offset])
        struct.pack_into("<II", source, 16, 2, 72 + 72)
        source[signature_command : signature_command + 16] = b"\0" * 16
        linkedit_command = 32 + 72
        struct.pack_into("<Q", source, linkedit_command + 32, 0x1000)
        struct.pack_into("<Q", source, linkedit_command + 48, 0x40)

        canonical, details = receipt._mac_transformation(
            bytes(source),
            bytes(final),
            "mac-x64",
            "Electron.app/Contents/MacOS/Electron",
            "Contents/MacOS/AutoEditor",
        )
        self.assertEqual(len(canonical), signature_offset)
        self.assertEqual(
            details["source_macho"]["archive_signature"],
            "absent-authenticated-by-archive-sha256",
        )

        hostile = bytearray(final)
        hostile[0x1000] ^= 1
        with self.assertRaisesRegex(
            receipt.ElectronNativeReceiptError,
            "outside signature allocation",
        ):
            receipt._mac_transformation(
                bytes(source),
                bytes(hostile),
                "mac-x64",
                "Electron.app/Contents/MacOS/Electron",
                "Contents/MacOS/AutoEditor",
            )

        hostile_source = bytearray(source)
        hostile_source[signature_command] = 1
        with self.assertRaisesRegex(
            receipt.ElectronNativeReceiptError,
            "zero command slot",
        ):
            receipt._mac_transformation(
                bytes(hostile_source),
                bytes(final),
                "mac-x64",
                "Electron.app/Contents/MacOS/Electron",
                "Contents/MacOS/AutoEditor",
            )

    def test_authenticated_receipt_rejects_mapping_and_digest_drift(self):
        payload = self._receipt_payload()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "receipt.json"
            raw = receipt.canonical_json_bytes(payload)
            path.write_bytes(raw)
            loaded, digest = receipt.load_authenticated_receipt(
                path, hashlib.sha256(raw).hexdigest(), "windows-x64"
            )
            self.assertEqual(len(receipt.claims_from_receipt(loaded, "windows-x64")), 9)
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(receipt.ElectronNativeReceiptError, "SHA256 mismatch"):
                receipt.load_authenticated_receipt(path, "0" * 64, "windows-x64")
            forged = copy.deepcopy(payload)
            forged["files"]["ffmpeg.dll"]["mapping"]["archive_path"] = "other.dll"
            forged_raw = receipt.canonical_json_bytes(forged)
            path.write_bytes(forged_raw)
            with self.assertRaisesRegex(receipt.ElectronNativeReceiptError, "mapping drifted"):
                receipt.load_authenticated_receipt(
                    path, hashlib.sha256(forged_raw).hexdigest(), "windows-x64"
                )

    def test_claim_modes_are_bound_to_final_files(self):
        payload = self._receipt_payload()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for path in payload["files"]:
                final = root / path
                final.parent.mkdir(parents=True, exist_ok=True)
                final.write_bytes(b"x")
                final.chmod(0o644)
            receipt.validate_claim_modes(root, payload, "windows-x64")
            changed = root / "ffmpeg.dll"
            changed.chmod(0o600)
            with self.assertRaisesRegex(receipt.ElectronNativeReceiptError, "metadata drifted"):
                receipt.validate_claim_modes(root, payload, "windows-x64")

    def test_configured_icon_chunks_are_exact(self):
        raw = (ROOT / "desktop" / "build" / "icon.ico").read_bytes()
        payloads, group = receipt._icon_payloads(raw)
        self.assertEqual(len(payloads), 7)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt.ICON_SHA256)
        self.assertEqual(struct.unpack_from("<H", group, 4)[0], 7)

    def test_asar_integrity_hashes_only_the_exact_header_string(self):
        header = b'{"files":{}}'
        raw = struct.pack("<IIII", 4, len(header) + 8, len(header) + 4, len(header)) + header + b"payload"
        self.assertEqual(receipt._asar_header_sha256(raw), hashlib.sha256(header).hexdigest())
        hostile = bytearray(raw)
        struct.pack_into("<I", hostile, 12, len(header) + 1)
        with self.assertRaisesRegex(receipt.ElectronNativeReceiptError, "header pickle"):
            receipt._asar_header_sha256(bytes(hostile))


if __name__ == "__main__":
    unittest.main()
