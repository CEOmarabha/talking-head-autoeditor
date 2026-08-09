from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "macos_ffmpeg_receipt.py"
SPEC = importlib.util.spec_from_file_location("macos_ffmpeg_receipt", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load Mac FFmpeg receipt module: {SCRIPT}")
receipt = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = receipt
SPEC.loader.exec_module(receipt)


class MacFFmpegReceiptTests(unittest.TestCase):
    @staticmethod
    def _macho(
        arch: str,
        kind: str,
        payload: bytes,
        *,
        uuid_seed: bytes = b"fixture",
        load_names: tuple[str, ...] = (),
        install_id: str | None = None,
        unbound_payload: bytes = b"",
        signature_payload: bytes = b"",
    ) -> bytes:
        segment_size = 72 + receipt.SECTION_64_BYTES
        uuid_size = 24
        load_commands: list[bytes] = []

        def dylib_command(command: int, name: str) -> bytes:
            encoded_name = name.encode("utf-8") + b"\0"
            load_size = (24 + len(encoded_name) + 7) // 8 * 8
            return struct.pack(
                "<6I", command, load_size, 24, 2, 0x10000, 0x10000
            ) + encoded_name.ljust(load_size - 24, b"\0")

        if kind == "executable":
            load_commands.append(
                struct.pack("<IIQQ", 0x80000028, 24, 16 * 1024, 0)
            )
        if install_id is not None:
            load_commands.append(
                dylib_command(receipt.LC_ID_DYLIB, install_id)
            )
        load_commands.extend(
            dylib_command(receipt.LC_LOAD_DYLIB, name)
            for name in load_names
        )
        load_command_bytes = b"".join(load_commands)
        signature_command_size = 16 if signature_payload else 0
        linkedit_command_size = 72 if signature_payload else 0
        command_size = (
            segment_size
            + uuid_size
            + len(load_command_bytes)
            + linkedit_command_size
            + signature_command_size
        )
        command_count = (
            2 + len(load_commands) + bool(signature_payload) * 2
        )
        file_type = (
            receipt.MH_EXECUTE if kind == "executable" else receipt.MH_DYLIB
        )
        payload_offset = 16 * 1024
        if 32 + command_size > payload_offset:
            raise AssertionError("fixture Mach-O load commands exceed header pad")
        signature_offset = payload_offset + len(payload) + len(unbound_payload)
        section_backed_size = signature_offset
        header = struct.pack(
            "<8I",
            receipt.MH_MAGIC_64,
            receipt.CPU_TYPES[arch],
            0,
            file_type,
            command_count,
            command_size,
            0,
            0,
        )
        segment = struct.pack(
            "<II16sQQQQIIII",
            receipt.LC_SEGMENT_64,
            segment_size,
            b"__TEXT".ljust(16, b"\0"),
            0,
            section_backed_size,
            0,
            section_backed_size,
            7,
            5,
            1,
            0,
        )
        section = struct.pack(
            "<16s16sQQIIIIIIII",
            b"__text".ljust(16, b"\0"),
            b"__TEXT".ljust(16, b"\0"),
            payload_offset,
            len(payload),
            payload_offset,
            0,
            0,
            0,
            0x80000400,
            0,
            0,
            0,
        )
        uuid = struct.pack(
            "<II16s",
            receipt.LC_UUID,
            uuid_size,
            hashlib.sha256(uuid_seed).digest()[:16],
        )
        linkedit = b""
        if signature_payload:
            page_bytes = 16 * 1024 if arch == "arm64" else 4 * 1024
            linkedit_vm_size = (
                (len(signature_payload) + page_bytes - 1)
                // page_bytes
                * page_bytes
            )
            linkedit = struct.pack(
                "<II16sQQQQIIII",
                receipt.LC_SEGMENT_64,
                72,
                b"__LINKEDIT".ljust(16, b"\0"),
                section_backed_size,
                linkedit_vm_size,
                signature_offset,
                len(signature_payload),
                1,
                1,
                0,
                0,
            )
        signature_command = b""
        if signature_payload:
            signature_command = struct.pack(
                "<4I", 0x1D, 16, signature_offset, len(signature_payload)
            )
        commands = (
            header
            + segment
            + section
            + uuid
            + load_command_bytes
            + linkedit
            + signature_command
        )
        return (
            commands.ljust(payload_offset, b"\0")
            + payload
            + unbound_payload
            + signature_payload
        )

    @staticmethod
    def _replace_loader_path(path: Path, old: str, new: str) -> None:
        old_raw = old.encode("utf-8")
        new_raw = new.encode("utf-8")
        if len(new_raw) > len(old_raw):
            raise AssertionError("replacement loader path exceeds fixture command")
        raw = bytearray(path.read_bytes())
        if raw.count(old_raw + b"\0") != 1:
            raise AssertionError(f"loader path is not unique in fixture: {old}")
        offset = raw.index(old_raw + b"\0")
        raw[offset:offset + len(old_raw) + 1] = (new_raw + b"\0").ljust(
            len(old_raw) + 1, b"\0"
        )
        path.write_bytes(raw)

    @staticmethod
    def _replace_dylib_timestamp(
        path: Path,
        dylib_name: str,
        timestamp: int,
    ) -> None:
        raw = bytearray(path.read_bytes())
        command_count = struct.unpack_from("<I", raw, 16)[0]
        cursor = 32
        matches = 0
        for _ in range(command_count):
            command, command_size = struct.unpack_from("<II", raw, cursor)
            if (
                command == receipt.LC_ID_DYLIB
                or command in receipt.DYNAMIC_LIBRARY_LOAD_COMMANDS
            ):
                name_offset = struct.unpack_from("<I", raw, cursor + 8)[0]
                start = cursor + name_offset
                end = raw.index(0, start, cursor + command_size)
                if raw[start:end].decode("utf-8") == dylib_name:
                    struct.pack_into("<I", raw, cursor + 12, timestamp)
                    matches += 1
            cursor += command_size
        if matches != 1:
            raise AssertionError(
                f"expected one dylib command for {dylib_name}, found {matches}"
            )
        path.write_bytes(raw)

    @staticmethod
    def _replace_signature_payload(
        path: Path,
        arch: str,
        payload: bytes,
    ) -> None:
        raw = bytearray(path.read_bytes())
        command_count = struct.unpack_from("<I", raw, 16)[0]
        cursor = 32
        signature_command = None
        linkedit_command = None
        for _ in range(command_count):
            command, command_size = struct.unpack_from("<II", raw, cursor)
            if command == receipt.LC_CODE_SIGNATURE:
                signature_command = cursor
            elif command == receipt.LC_SEGMENT_64:
                segment = raw[cursor + 8:cursor + 24].split(b"\0", 1)[0]
                if segment == b"__LINKEDIT":
                    linkedit_command = cursor
            cursor += command_size
        if signature_command is None or linkedit_command is None:
            raise AssertionError("fixture lacks its signed __LINKEDIT commands")
        signature_offset, signature_size = struct.unpack_from(
            "<II", raw, signature_command + 8
        )
        if signature_offset + signature_size != len(raw):
            raise AssertionError("fixture signature is not terminal")
        file_offset = struct.unpack_from("<Q", raw, linkedit_command + 40)[0]
        file_size = signature_offset + len(payload) - file_offset
        page_bytes = 16 * 1024 if arch == "arm64" else 4 * 1024
        vm_size = (file_size + page_bytes - 1) // page_bytes * page_bytes
        del raw[signature_offset:]
        raw.extend(payload)
        struct.pack_into("<I", raw, signature_command + 12, len(payload))
        struct.pack_into("<Q", raw, linkedit_command + 32, vm_size)
        struct.pack_into("<Q", raw, linkedit_command + 48, file_size)
        path.write_bytes(raw)

    @staticmethod
    def _add_to_linkedit_vmsize(path: Path, byte_count: int) -> None:
        raw = bytearray(path.read_bytes())
        command_count = struct.unpack_from("<I", raw, 16)[0]
        cursor = 32
        matches = 0
        for _ in range(command_count):
            command, command_size = struct.unpack_from("<II", raw, cursor)
            if command == receipt.LC_SEGMENT_64:
                segment = raw[cursor + 8:cursor + 24].split(b"\0", 1)[0]
                if segment == b"__LINKEDIT":
                    vm_size = struct.unpack_from("<Q", raw, cursor + 32)[0]
                    struct.pack_into(
                        "<Q", raw, cursor + 32, vm_size + byte_count
                    )
                    matches += 1
            cursor += command_size
        if matches != 1:
            raise AssertionError(
                f"expected one __LINKEDIT command, found {matches}"
            )
        path.write_bytes(raw)

    @staticmethod
    def _linkedit_vmsize(path: Path) -> int:
        raw = path.read_bytes()
        command_count = struct.unpack_from("<I", raw, 16)[0]
        cursor = 32
        values = []
        for _ in range(command_count):
            command, command_size = struct.unpack_from("<II", raw, cursor)
            if command == receipt.LC_SEGMENT_64:
                segment = raw[cursor + 8:cursor + 24].split(b"\0", 1)[0]
                if segment == b"__LINKEDIT":
                    values.append(struct.unpack_from("<Q", raw, cursor + 32)[0])
            cursor += command_size
        if len(values) != 1:
            raise AssertionError(
                f"expected one __LINKEDIT command, found {len(values)}"
            )
        return values[0]

    def _fixture(
        self,
        root: Path,
        arch: str = "arm64",
    ) -> dict[str, object]:
        inventory = (
            ROOT / "packaging" / f"macos-ffmpeg-formulae-{arch}.txt"
        )
        records, _ = receipt.read_formula_inventory(inventory, arch)
        versions = {record.formula: record.version for record in records}
        cellar = root / "Cellar"
        app = root / "AutoEditor Helper.app"
        embedded_inventory = (
            app
            / "Contents"
            / "Resources"
            / "licenses"
            / "FFMPEG_FORMULAE.txt"
        )
        embedded_inventory.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inventory, embedded_inventory)
        sources: dict[str, Path] = {}
        finals: dict[str, Path] = {}
        ordered_paths = sorted(receipt.EXPECTED_FINAL_PATHS.items())
        for relative, (kind, formula) in ordered_paths:
            name = Path(relative).name
            source_directory = "bin" if kind == "executable" else "lib"
            sources[relative] = (
                cellar / formula / versions[formula] / source_directory / name
            )
            finals[relative] = app / relative
        libraries = [
            sources[relative]
            for relative in sorted(sources)
            if relative.startswith("Contents/Resources/lib/")
        ]
        library_edges = {libraries[0].name: libraries[1]}
        system_load = "/usr/lib/libSystem.B.dylib"
        for index, (relative, (kind, _formula)) in enumerate(
            ordered_paths, 1
        ):
            name = Path(relative).name
            source = sources[relative]
            source.parent.mkdir(parents=True, exist_ok=True)
            section_payload = f"section-{index}-{name}".encode("utf-8")
            source.write_bytes(self._macho(
                arch,
                kind,
                section_payload,
                uuid_seed=relative.encode("utf-8"),
                load_names=(
                    tuple(str(item) for item in libraries) + (system_load,)
                    if kind == "executable"
                    else (
                        ((str(library_edges[source.name]),) + (system_load,))
                        if source.name in library_edges
                        else (system_load,)
                    )
                ),
                install_id=str(source) if kind == "dylib" else None,
                unbound_payload=(
                    b"unbound-file-bytes:" + relative.encode("utf-8")
                ),
                signature_payload=f"source-signature-{index}".encode("utf-8"),
            ))
            if kind == "executable":
                source.chmod(0o755)
            final = finals[relative]
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(self._macho(
                arch,
                kind,
                section_payload,
                uuid_seed=relative.encode("utf-8"),
                load_names=(
                    tuple(
                        "@executable_path/../lib/" + item.name
                        for item in libraries
                    ) + (system_load,)
                    if kind == "executable"
                    else (
                        (
                            "@loader_path/" + library_edges[source.name].name,
                            system_load,
                        )
                        if source.name in library_edges
                        else (system_load,)
                    )
                ),
                install_id=(
                    f"@loader_path/{name}" if kind == "dylib" else None
                ),
                unbound_payload=(
                    b"unbound-file-bytes:" + relative.encode("utf-8")
                ),
                signature_payload=f"final-signature-{index}".encode("utf-8"),
            ))
            if kind == "executable":
                final.chmod(0o755)

        def dependencies(path: Path) -> list[Path]:
            if path.name in {"ffmpeg", "ffprobe"}:
                return libraries
            if path.name in library_edges:
                return [library_edges[path.name]]
            return []

        return {
            "app": app,
            "cellar": cellar,
            "ffmpeg": sources["Contents/Resources/bin/ffmpeg"],
            "ffprobe": sources["Contents/Resources/bin/ffprobe"],
            "inventory": inventory,
            "embedded_inventory": embedded_inventory,
            "sources": sources,
            "finals": finals,
            "dependencies": dependencies,
        }

    @staticmethod
    def _source_whole_sha256(
        fixture: dict[str, object],
        source: Path,
        arch: str,
    ) -> str:
        dependencies = tuple(
            Path(item).resolve(strict=True)
            for item in fixture["dependencies"](source)
        )
        executable_directories = tuple(sorted({
            Path(fixture["ffmpeg"]).resolve(strict=True).parent,
            Path(fixture["ffprobe"]).resolve(strict=True).parent,
        }))
        return receipt._macho_whole_sha256_path(
            source,
            "fixture SVT source",
            arch,
            "dylib",
            final_path=receipt.SVT_AV1_FINAL_PATH,
            source_dependencies=dependencies,
            executable_directories=executable_directories,
        )

    @staticmethod
    def _generate(
        fixture: dict[str, object],
        arch: str = "arm64",
        fixture_member=None,
    ):
        records, _ = receipt.read_formula_inventory(
            fixture["inventory"], arch
        )
        svt_formula = next(
            record for record in records if record.formula == "svt-av1"
        )
        source = fixture["sources"][receipt.SVT_AV1_FINAL_PATH]
        source_raw = source.read_bytes()
        if fixture_member is None:
            fixture_member = receipt.BottleMemberRecord(
                bottle_sha256=svt_formula.bottle_sha256,
                member_path=(
                    "svt-av1/4.2.0/lib/libSvtAv1Enc.4.2.0.dylib"
                ),
                byte_count=len(source_raw),
                sha256=hashlib.sha256(source_raw).hexdigest(),
                macho_whole_sha256=(
                    MacFFmpegReceiptTests._source_whole_sha256(
                        fixture, source, arch
                    )
                ),
            )
        members = dict(receipt.PINNED_BOTTLE_MEMBERS)
        members[arch] = {receipt.SVT_AV1_FINAL_PATH: fixture_member}
        with mock.patch.object(receipt, "PINNED_BOTTLE_MEMBERS", members):
            return receipt.generate_receipt(
                fixture["app"],
                fixture["ffmpeg"],
                fixture["ffprobe"],
                fixture["cellar"],
                fixture["inventory"],
                arch,
                dependency_reader=fixture["dependencies"],
            )

    def test_svt_path_matches_both_authenticated_4_2_0_bottles(self):
        expected = {
            "arm64": (
                "2e6f7cbf3ff42f59ca251f3c84d4ad5a3ecfd518340237a6f70a54a428de1676",
                3_090_544,
                "72407e386bf6582771dd73ff51c6318201b7ad27a755d82efc64ea35db161d64",
                "87f9d30d9c820b29a9657631114d01064d279c16bda3556d48d7d8547895aebe",
            ),
            "x64": (
                "413ca9c3ca785dcebb9baae17b4b86a70f1c86e5881fa8af87f55ac7e5d8a5eb",
                5_450_640,
                "b10c2dfc281d442691befb528090747f92a25ac12189b6689782cc259abdd4ad",
                "ec2ff23e2b0f841949b9ddcda1935e552fa77a3ae8be76f6b40d6da182f71da5",
            ),
        }
        self.assertEqual(
            receipt.SVT_AV1_FINAL_PATH,
            "Contents/Resources/lib/libSvtAv1Enc.4.2.0.dylib",
        )
        self.assertNotIn(
            "libSvtAv1Enc.4.1.0.dylib",
            receipt.LIBRARY_SOURCE_FORMULAE,
        )
        for arch, (
            bottle_sha,
            byte_count,
            member_sha,
            whole_sha,
        ) in expected.items():
            records, _ = receipt.read_formula_inventory(
                ROOT / "packaging" / f"macos-ffmpeg-formulae-{arch}.txt",
                arch,
            )
            svt_formula = next(
                record for record in records if record.formula == "svt-av1"
            )
            member = receipt.PINNED_BOTTLE_MEMBERS[arch][
                receipt.SVT_AV1_FINAL_PATH
            ]
            self.assertEqual(svt_formula.version, "4.2.0")
            self.assertEqual(svt_formula.bottle_sha256, bottle_sha)
            self.assertEqual(member.bottle_sha256, bottle_sha)
            self.assertEqual(
                member.member_path,
                "svt-av1/4.2.0/lib/libSvtAv1Enc.4.2.0.dylib",
            )
            self.assertEqual(member.byte_count, byte_count)
            self.assertEqual(member.sha256, member_sha)
            self.assertEqual(member.macho_whole_sha256, whole_sha)

    def test_relocated_and_resigned_svt_matches_normalized_bottle_identity(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = fixture["sources"][receipt.SVT_AV1_FINAL_PATH]
            raw_member = Path(td) / "raw" / source.name
            raw_member.parent.mkdir()
            shutil.copy2(source, raw_member)
            self._replace_loader_path(
                raw_member,
                str(source),
                f"@rpath/{source.name}",
            )
            raw = raw_member.read_bytes()
            self.assertEqual(raw.count(b"source-signature-"), 1)
            raw_member.write_bytes(
                raw.replace(b"source-signature-", b"bottle-signature-", 1)
            )
            source_raw = source.read_bytes()
            member_raw = raw_member.read_bytes()
            source_whole = self._source_whole_sha256(
                fixture, source, "arm64"
            )
            member_whole = self._source_whole_sha256(
                fixture, raw_member, "arm64"
            )
            self.assertEqual(len(source_raw), len(member_raw))
            self.assertNotEqual(
                hashlib.sha256(source_raw).hexdigest(),
                hashlib.sha256(member_raw).hexdigest(),
            )
            self.assertEqual(source_whole, member_whole)

            records, _ = receipt.read_formula_inventory(
                fixture["inventory"], "arm64"
            )
            svt_formula = next(
                record for record in records if record.formula == "svt-av1"
            )
            member = receipt.BottleMemberRecord(
                bottle_sha256=svt_formula.bottle_sha256,
                member_path=(
                    "svt-av1/4.2.0/lib/libSvtAv1Enc.4.2.0.dylib"
                ),
                byte_count=len(member_raw),
                sha256=hashlib.sha256(member_raw).hexdigest(),
                macho_whole_sha256=member_whole,
            )
            self._generate(fixture, fixture_member=member)

    def test_legacy_rewrite_timestamps_do_not_weaken_system_loads(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            relative = receipt.SVT_AV1_FINAL_PATH
            source = fixture["sources"][relative]
            target = fixture["finals"][relative]
            dependency = fixture["dependencies"](source)[0]
            self._replace_dylib_timestamp(
                target,
                f"@loader_path/{target.name}",
                1_786_231_089,
            )
            self._replace_dylib_timestamp(
                target,
                f"@loader_path/{dependency.name}",
                1_786_231_090,
            )
            self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            self._replace_dylib_timestamp(
                target,
                "/usr/lib/libSystem.B.dylib",
                1_786_231_089,
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError,
                "load-command semantics",
            ):
                self._generate(fixture)

    def test_signature_growth_normalizes_only_canonical_linkedit_vmsize(self):
        for arch in ("arm64", "x64"):
            with self.subTest(arch=arch), tempfile.TemporaryDirectory() as td:
                fixture = self._fixture(Path(td), arch)
                target = fixture["finals"][receipt.SVT_AV1_FINAL_PATH]
                self._replace_signature_payload(
                    target,
                    arch,
                    b"resigned-signature" + b"x" * (20 * 1024),
                )
                self._generate(fixture, arch)

        for arch in ("arm64", "x64"):
            with self.subTest(
                hostile_arch=arch
            ), tempfile.TemporaryDirectory() as td:
                fixture = self._fixture(Path(td), arch)
                target = fixture["finals"][receipt.SVT_AV1_FINAL_PATH]
                self._replace_signature_payload(
                    target,
                    arch,
                    b"resigned-signature" + b"x" * (20 * 1024),
                )
                self._add_to_linkedit_vmsize(
                    target,
                    2 * (16 * 1024 if arch == "arm64" else 4 * 1024),
                )
                with self.assertRaisesRegex(
                    receipt.MacFFmpegReceiptError,
                    "noncanonical signed __LINKEDIT extent",
                ):
                    self._generate(fixture, arch)

    def test_authenticated_arm64_ffmpeg_linkedit_preallocation_is_exactly_bounded(self):
        relative = "Contents/Resources/lib/libavfilter.11.14.102.dylib"
        authenticated_vm_size = (
            receipt.ARM64_FFMPEG_BOTTLE_LINKEDIT_VM_BYTES[
                "libavfilter.11.14.102.dylib"
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = fixture["sources"][relative]
            self._add_to_linkedit_vmsize(
                source,
                authenticated_vm_size - self._linkedit_vmsize(source),
            )
            self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = fixture["sources"][relative]
            hostile_vm_size = authenticated_vm_size + 16 * 1024
            self._add_to_linkedit_vmsize(
                source,
                hostile_vm_size - self._linkedit_vmsize(source),
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError,
                "noncanonical signed __LINKEDIT extent",
            ):
                self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = fixture["sources"][relative]
            self._replace_signature_payload(
                source,
                "arm64",
                b"oversized-signature" + b"x" * authenticated_vm_size,
            )
            self._add_to_linkedit_vmsize(
                source,
                authenticated_vm_size - self._linkedit_vmsize(source),
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError,
                "noncanonical signed __LINKEDIT extent",
            ):
                self._generate(fixture)

    def test_authenticated_x64_ffmpeg_linkedit_preallocation_is_exactly_bounded(self):
        cases = (
            ("Contents/Resources/bin/ffprobe", 32_768),
            ("Contents/Resources/bin/ffmpeg", 81_920),
            ("Contents/Resources/bin/ffprobe", 49_152),
            (
                "Contents/Resources/lib/libavcodec.62.28.102.dylib",
                212_992,
            ),
            (
                "Contents/Resources/lib/libavdevice.62.3.102.dylib",
                49_152,
            ),
            (
                "Contents/Resources/lib/libavfilter.11.14.102.dylib",
                114_688,
            ),
            (
                "Contents/Resources/lib/libavformat.62.12.102.dylib",
                114_688,
            ),
            (
                "Contents/Resources/lib/libavutil.60.26.102.dylib",
                81_920,
            ),
            (
                "Contents/Resources/lib/libswresample.6.3.102.dylib",
                32_768,
            ),
            (
                "Contents/Resources/lib/libswscale.9.5.102.dylib",
                49_152,
            ),
        )
        for relative, authenticated_vm_size in cases:
            with (
                self.subTest(
                    relative=relative,
                    authenticated_vm_size=authenticated_vm_size,
                ),
                tempfile.TemporaryDirectory() as td,
            ):
                fixture = self._fixture(Path(td), "x64")
                source = fixture["sources"][relative]
                self._add_to_linkedit_vmsize(
                    source,
                    authenticated_vm_size - self._linkedit_vmsize(source),
                )
                self._generate(fixture, "x64")

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td), "x64")
            relative = "Contents/Resources/bin/ffmpeg"
            source = fixture["sources"][relative]
            hostile_vm_size = 81_920 + 4 * 1024
            self._add_to_linkedit_vmsize(
                source,
                hostile_vm_size - self._linkedit_vmsize(source),
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError,
                "noncanonical signed __LINKEDIT extent",
            ):
                self._generate(fixture, "x64")

    def test_authenticated_arm64_libvmaf_linkedit_preallocation_is_exactly_bounded(self):
        relative = "Contents/Resources/lib/libvmaf.3.dylib"
        authenticated_vm_size = 81_920
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = fixture["sources"][relative]
            self._add_to_linkedit_vmsize(
                source,
                authenticated_vm_size - self._linkedit_vmsize(source),
            )
            self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = fixture["sources"][relative]
            hostile_vm_size = authenticated_vm_size + 16 * 1024
            self._add_to_linkedit_vmsize(
                source,
                hostile_vm_size - self._linkedit_vmsize(source),
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError,
                "noncanonical signed __LINKEDIT extent",
            ):
                self._generate(fixture)

    def test_hostile_svt_substitution_fails_normalized_bottle_gate(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = fixture["sources"][receipt.SVT_AV1_FINAL_PATH]
            authenticated_whole = self._source_whole_sha256(
                fixture, source, "arm64"
            )
            substituted = bytearray(source.read_bytes())
            marker = b"unbound-file-bytes:" + receipt.SVT_AV1_FINAL_PATH.encode(
                "utf-8"
            )
            self.assertEqual(substituted.count(marker), 1)
            substituted[substituted.index(marker)] ^= 1
            source.write_bytes(substituted)
            substituted_whole = self._source_whole_sha256(
                fixture, source, "arm64"
            )
            self.assertNotEqual(authenticated_whole, substituted_whole)

            records, _ = receipt.read_formula_inventory(
                fixture["inventory"], "arm64"
            )
            svt_formula = next(
                record for record in records if record.formula == "svt-av1"
            )
            hostile_member = receipt.BottleMemberRecord(
                bottle_sha256=svt_formula.bottle_sha256,
                member_path=(
                    "svt-av1/4.2.0/lib/libSvtAv1Enc.4.2.0.dylib"
                ),
                byte_count=len(substituted),
                sha256=hashlib.sha256(substituted).hexdigest(),
                macho_whole_sha256=authenticated_whole,
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError,
                "authenticated bottle member",
            ):
                self._generate(
                    fixture,
                    fixture_member=hostile_member,
                )

    def test_generate_validate_claims_and_verify_exact_final_app(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            payload, raw = self._generate(fixture)

            self.assertEqual(raw, receipt.canonical_json_bytes(payload))
            self.assertEqual(payload["schema"], receipt.SCHEMA)
            self.assertEqual(payload["component"], "main-ffmpeg")
            self.assertEqual(payload["platform"], "mac-arm64")
            self.assertEqual(
                payload["formula_inventory"]["sha256"],
                receipt.PINNED_FORMULA_INVENTORY_SHA256["arm64"],
            )
            claims = receipt.claims_from_receipt(payload, raw, "arm64")
            self.assertEqual(set(claims), set(receipt.EXPECTED_FINAL_PATHS))
            self.assertEqual(len(claims), 20)
            ffmpeg = claims["Contents/Resources/bin/ffmpeg"]
            self.assertEqual(ffmpeg.kind, "executable")
            self.assertEqual(ffmpeg.source_formula, "ffmpeg")
            self.assertEqual(ffmpeg.source_formula_version, "8.1.2_1")
            self.assertEqual(
                ffmpeg.source_cellar_path,
                "ffmpeg/8.1.2_1/bin/ffmpeg",
            )
            self.assertNotEqual(ffmpeg.sha256, ffmpeg.source_sha256)
            self.assertEqual(ffmpeg.macho_uuid, ffmpeg.source_macho_uuid)
            self.assertEqual(
                ffmpeg.macho_content_sha256,
                ffmpeg.source_macho_content_sha256,
            )
            self.assertEqual(
                ffmpeg.macho_whole_sha256,
                ffmpeg.source_macho_whole_sha256,
            )
            verified = receipt.verify_app(
                fixture["app"], payload, raw, "arm64"
            )
            self.assertEqual(dict(verified), dict(claims))

    def test_x64_generation_uses_the_x64_inventory_and_macho_cpu(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td), "x64")
            payload, raw = self._generate(fixture, "x64")
            claims = receipt.claims_from_receipt(payload, raw, "x64")
            self.assertEqual(payload["platform"], "mac-x64")
            self.assertTrue(all(
                claim.architecture == "x64" for claim in claims.values()
            ))
            self.assertEqual(
                payload["formula_inventory"]["sha256"],
                receipt.PINNED_FORMULA_INVENTORY_SHA256["x64"],
            )

    def test_missing_extra_and_wrong_case_paths_fail_closed(self):
        mutations = ("missing", "extra", "case")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                fixture = self._fixture(Path(td))
                target = fixture["finals"][
                    "Contents/Resources/lib/libvpx.12.dylib"
                ]
                if mutation == "missing":
                    target.unlink()
                elif mutation == "extra":
                    extra = target.parent / "unexpected.dylib"
                    extra.write_bytes(self._macho("arm64", "dylib", b"extra"))
                else:
                    target.rename(target.with_name("LIBVPX.12.DYLIB"))
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    self._generate(fixture)

    def test_symlink_hardlink_and_nested_directory_fail_closed(self):
        mutations = ("symlink", "hardlink", "directory")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                fixture = self._fixture(root)
                target = fixture["finals"][
                    "Contents/Resources/lib/libvpx.12.dylib"
                ]
                if mutation == "symlink":
                    target.unlink()
                    target.symlink_to(
                        fixture["finals"][
                            "Contents/Resources/lib/libx264.165.dylib"
                        ]
                    )
                elif mutation == "hardlink":
                    os.link(target, root / "external-hardlink")
                else:
                    (target.parent / "nested").mkdir()
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    self._generate(fixture)

    def test_symlinked_app_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._fixture(root)
            alias = root / "Alias.app"
            alias.symlink_to(fixture["app"], target_is_directory=True)
            fixture["app"] = alias
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                self._generate(fixture)

    def test_wrong_architecture_and_wrong_file_type_fail_closed(self):
        for mutation in ("architecture", "file_type"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                fixture = self._fixture(Path(td))
                target = fixture["finals"][
                    "Contents/Resources/lib/libvpx.12.dylib"
                ]
                if mutation == "architecture":
                    target.write_bytes(self._macho("x64", "dylib", b"wrong"))
                else:
                    target.write_bytes(
                        self._macho("arm64", "executable", b"wrong")
                    )
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    self._generate(fixture)

    def test_final_macho_uuid_must_match_its_exact_cellar_source(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"][
                "Contents/Resources/lib/libvpx.12.dylib"
            ]
            relative = "Contents/Resources/lib/libvpx.12.dylib"
            raw = bytearray(target.read_bytes())
            expected_uuid = hashlib.sha256(relative.encode("utf-8")).digest()[:16]
            raw[raw.index(expected_uuid):raw.index(expected_uuid) + 16] = (
                hashlib.sha256(b"unrelated-source").digest()[:16]
            )
            target.write_bytes(raw)
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "UUID"
            ):
                self._generate(fixture)

    def test_same_uuid_with_altered_section_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            raw = bytearray(target.read_bytes())
            needle = b"section-1-ffmpeg"
            offset = raw.index(needle)
            raw[offset] ^= 0x01
            target.write_bytes(raw)
            target.chmod(0o755)
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "section content"
            ):
                self._generate(fixture)

    def test_same_sections_and_loads_with_altered_unbound_byte_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            relative = "Contents/Resources/bin/ffmpeg"
            source = fixture["sources"][relative]
            target = fixture["finals"][relative]
            source_observation = receipt._observe_macho_path(
                source, "fixture source", "arm64", "executable"
            )[2]
            raw = bytearray(target.read_bytes())
            needle = b"unbound-file-bytes:" + relative.encode("utf-8")
            offset = raw.index(needle)
            raw[offset] ^= 0x01
            target.write_bytes(raw)
            target.chmod(0o755)
            final_observation = receipt._observe_macho_path(
                target, "fixture final", "arm64", "executable"
            )[2]
            self.assertEqual(
                source_observation.content_sha256,
                final_observation.content_sha256,
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "whole Mach-O"
            ):
                self._generate(fixture)

    def test_nonzero_header_padding_outside_loader_rewrites_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            raw = bytearray(target.read_bytes())
            command_bytes = struct.unpack_from("<I", raw, 20)[0]
            padding_offset = 32 + command_bytes + 7
            self.assertEqual(raw[padding_offset], 0)
            raw[padding_offset] = 1
            target.write_bytes(raw)
            target.chmod(0o755)
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "header padding"
            ):
                self._generate(fixture)

    def test_load_command_and_signature_drift_preserves_section_identity(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            relative = "Contents/Resources/bin/ffmpeg"
            source = fixture["sources"][relative]
            final = fixture["finals"][relative]
            source_bytes, source_sha, source_macho = (
                receipt._observe_macho_path(
                    source, "fixture source", "arm64", "executable"
                )
            )
            final_bytes, final_sha, final_macho = receipt._observe_macho_path(
                final, "fixture final", "arm64", "executable"
            )
            self.assertNotEqual(source_bytes, final_bytes)
            self.assertNotEqual(source_sha, final_sha)
            self.assertEqual(source_macho.uuid, final_macho.uuid)
            self.assertEqual(
                source_macho.content_sha256,
                final_macho.content_sha256,
            )

    @unittest.skipUnless(
        all(Path(path).is_file() for path in (
            "/usr/bin/otool",
            "/usr/bin/install_name_tool",
            "/usr/bin/codesign",
            "/opt/homebrew/Cellar/ffmpeg/8.1.2_1/lib/"
            "libavutil.60.26.102.dylib",
        )),
        "requires the audited arm64 Homebrew dylib and macOS signing tools",
    )
    def test_real_install_name_tool_and_codesign_preserve_bound_semantics(self):
        source = Path(
            "/opt/homebrew/Cellar/ffmpeg/8.1.2_1/lib/"
            "libavutil.60.26.102.dylib"
        )
        with tempfile.TemporaryDirectory() as td:
            final = Path(td) / source.name
            shutil.copy2(source, final)
            source_dependencies = receipt._otool_dependencies(source)
            output = receipt._run_otool("-L", source).splitlines()
            install_id = receipt._otool_install_id(source)
            values = []
            for line in output[1:]:
                match = receipt.re.fullmatch(r"\s*(.+?)\s+\([^\n]*\)", line)
                if match:
                    values.append(match.group(1))
            if install_id is not None:
                self.assertEqual(values.pop(0), install_id)
            receipt.subprocess.run(
                [
                    "/usr/bin/install_name_tool",
                    "-id",
                    f"@loader_path/{final.name}",
                    str(final),
                ],
                check=True,
            )
            for value in values:
                dependency, is_system = receipt._canonical_absolute_otool_path(
                    value, source
                )
                if is_system:
                    continue
                resolved = dependency.resolve(strict=True)
                receipt.subprocess.run(
                    [
                        "/usr/bin/install_name_tool",
                        "-change",
                        value,
                        f"@loader_path/{resolved.name}",
                        str(final),
                    ],
                    check=True,
                )
            receipt.subprocess.run(
                ["/usr/bin/codesign", "--force", "--sign", "-", str(final)],
                check=True,
            )
            receipt.subprocess.run(
                ["/usr/bin/codesign", "--verify", "--strict", str(final)],
                check=True,
            )
            source_bytes, source_sha, source_macho = receipt._observe_macho_path(
                source, "real Homebrew source", "arm64", "dylib"
            )
            final_bytes, final_sha, final_macho = receipt._observe_macho_path(
                final, "real rewritten dylib", "arm64", "dylib"
            )
            source_profile = receipt._macho_load_command_profile(
                source_macho,
                binary=source,
                final_path=(
                    "Contents/Resources/lib/libavutil.60.26.102.dylib"
                ),
                kind="dylib",
                source_dependencies=source_dependencies,
            )
            final_profile = receipt._macho_load_command_profile(
                final_macho,
                binary=final,
                final_path=(
                    "Contents/Resources/lib/libavutil.60.26.102.dylib"
                ),
                kind="dylib",
            )
            self.assertNotEqual((source_bytes, source_sha), (final_bytes, final_sha))
            self.assertEqual(source_macho.uuid, final_macho.uuid)
            self.assertEqual(
                source_macho.content_sha256, final_macho.content_sha256
            )
            self.assertEqual(source_profile, final_profile)
            source_whole = receipt._macho_whole_sha256_path(
                source,
                "real Homebrew source",
                "arm64",
                "dylib",
                final_path=(
                    "Contents/Resources/lib/libavutil.60.26.102.dylib"
                ),
                source_dependencies=source_dependencies,
            )
            final_whole = receipt._macho_whole_sha256_path(
                final,
                "real rewritten dylib",
                "arm64",
                "dylib",
                final_path=(
                    "Contents/Resources/lib/libavutil.60.26.102.dylib"
                ),
            )
            self.assertEqual(source_whole, final_whole)

    @unittest.skipUnless(
        all(Path(path).is_file() for path in (
            "/usr/bin/otool",
            "/usr/bin/install_name_tool",
            "/usr/bin/codesign",
            "/opt/homebrew/Cellar/ffmpeg/8.1.2_1/lib/"
            "libavutil.60.26.102.dylib",
        )),
        "requires the audited arm64 Homebrew dylib and macOS signing tools",
    )
    def test_real_export_trie_mutation_survives_old_identity_but_not_whole_hash(self):
        source = Path(
            "/opt/homebrew/Cellar/ffmpeg/8.1.2_1/lib/"
            "libavutil.60.26.102.dylib"
        )
        final_path = "Contents/Resources/lib/libavutil.60.26.102.dylib"
        with tempfile.TemporaryDirectory() as td:
            final = Path(td) / source.name
            shutil.copy2(source, final)
            source_dependencies = receipt._otool_dependencies(source)
            output = receipt._run_otool("-L", source).splitlines()
            install_id = receipt._otool_install_id(source)
            values = []
            for line in output[1:]:
                match = receipt.re.fullmatch(r"\s*(.+?)\s+\([^\n]*\)", line)
                if match:
                    values.append(match.group(1))
            if install_id is not None:
                self.assertEqual(values.pop(0), install_id)
            receipt.subprocess.run(
                [
                    "/usr/bin/install_name_tool",
                    "-id",
                    f"@loader_path/{final.name}",
                    str(final),
                ],
                check=True,
            )
            for value in values:
                dependency, is_system = receipt._canonical_absolute_otool_path(
                    value, source
                )
                if is_system:
                    continue
                resolved = dependency.resolve(strict=True)
                receipt.subprocess.run(
                    [
                        "/usr/bin/install_name_tool",
                        "-change",
                        value,
                        f"@loader_path/{resolved.name}",
                        str(final),
                    ],
                    check=True,
                )
            receipt.subprocess.run(
                ["/usr/bin/codesign", "--force", "--sign", "-", str(final)],
                check=True,
            )

            source_whole = receipt._macho_whole_sha256_path(
                source,
                "real Homebrew source",
                "arm64",
                "dylib",
                final_path=final_path,
                source_dependencies=source_dependencies,
            )
            self.assertEqual(
                source_whole,
                receipt._macho_whole_sha256_path(
                    final,
                    "real rewritten dylib",
                    "arm64",
                    "dylib",
                    final_path=final_path,
                ),
            )

            raw = bytearray(final.read_bytes())
            _, _, _, _, command_count, _, _, _ = struct.unpack_from(
                "<8I", raw, 0
            )
            cursor = 32
            export_range = None
            for _ in range(command_count):
                command, command_size = struct.unpack_from("<II", raw, cursor)
                if command == 0x80000033:
                    export_range = struct.unpack_from("<II", raw, cursor + 8)
                elif command in {0x22, 0x80000022}:
                    export_range = struct.unpack_from("<II", raw, cursor + 40)
                cursor += command_size
            self.assertIsNotNone(export_range)
            export_offset, export_size = export_range
            self.assertGreater(export_size, 0)
            raw[export_offset + export_size // 2] ^= 0x01
            final.chmod(final.stat().st_mode | 0o200)
            final.write_bytes(raw)
            receipt.subprocess.run(
                ["/usr/bin/codesign", "--force", "--sign", "-", str(final)],
                check=True,
            )
            receipt.subprocess.run(
                ["/usr/bin/codesign", "--verify", "--strict", str(final)],
                check=True,
            )

            source_macho = receipt._observe_macho_path(
                source, "real Homebrew source", "arm64", "dylib"
            )[2]
            final_macho = receipt._observe_macho_path(
                final, "mutated rewritten dylib", "arm64", "dylib"
            )[2]
            self.assertEqual(source_macho.uuid, final_macho.uuid)
            self.assertEqual(
                source_macho.content_sha256, final_macho.content_sha256
            )
            self.assertEqual(
                receipt._macho_load_command_profile(
                    source_macho,
                    binary=source,
                    final_path=final_path,
                    kind="dylib",
                    source_dependencies=source_dependencies,
                ),
                receipt._macho_load_command_profile(
                    final_macho,
                    binary=final,
                    final_path=final_path,
                    kind="dylib",
                ),
            )
            self.assertNotEqual(
                source_whole,
                receipt._macho_whole_sha256_path(
                    final,
                    "mutated rewritten dylib",
                    "arm64",
                    "dylib",
                    final_path=final_path,
                ),
            )

    def test_arbitrary_final_loader_redirect_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            dependency_name = max(
                receipt.LIBRARY_SOURCE_FORMULAE, key=len
            )
            expected = "@executable_path/../lib/" + dependency_name
            self._replace_loader_path(
                target, expected, "/private/tmp/attacker-controlled.dylib"
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "absolute"
            ):
                self._generate(fixture)

    def test_final_loader_syntax_cardinality_and_install_id_fail_closed(self):
        dependency_name = max(receipt.LIBRARY_SOURCE_FORMULAE, key=len)
        expected = "@executable_path/../lib/" + dependency_name
        variants = (
            "@loader_path/" + dependency_name,
            "@rpath/" + dependency_name,
            "@executable_path/../../x.dylib",
            "@executable_path/../lib/x.dylib",
        )
        for hostile in variants:
            with self.subTest(hostile=hostile), tempfile.TemporaryDirectory() as td:
                fixture = self._fixture(Path(td))
                target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
                self._replace_loader_path(target, expected, hostile)
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            names = sorted(receipt.LIBRARY_SOURCE_FORMULAE, key=len)
            shorter = "@executable_path/../lib/" + names[0]
            longer = "@executable_path/../lib/" + names[-1]
            self._replace_loader_path(target, longer, shorter)
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "duplicate"
            ):
                self._generate(fixture)

        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                fixture = self._fixture(Path(td))
                relative = receipt.SVT_AV1_FINAL_PATH
                source = fixture["sources"][relative]
                target = fixture["finals"][relative]
                expected_dependency = fixture["dependencies"](source)[0]
                other_dependency = next(
                    path for item, path in fixture["sources"].items()
                    if item.startswith("Contents/Resources/lib/")
                    and path not in {source, expected_dependency}
                )
                load_names = [
                    "@loader_path/" + expected_dependency.name
                ]
                if mutation == "missing":
                    load_names.clear()
                else:
                    load_names.append("@loader_path/" + other_dependency.name)
                load_names.append("/usr/lib/libSystem.B.dylib")
                index = sorted(receipt.EXPECTED_FINAL_PATHS).index(relative) + 1
                target.write_bytes(self._macho(
                    "arm64",
                    "dylib",
                    f"section-{index}-{target.name}".encode("utf-8"),
                    uuid_seed=relative.encode("utf-8"),
                    load_names=tuple(load_names),
                    install_id="@loader_path/" + target.name,
                    signature_payload=f"final-signature-{index}".encode("utf-8"),
                ))
                with self.assertRaisesRegex(
                    receipt.MacFFmpegReceiptError, "dependency edges"
                ):
                    self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            source = next(
                path for relative, path in fixture["sources"].items()
                if relative.startswith("Contents/Resources/lib/")
                and fixture["dependencies"](path)
            )
            dependency = fixture["dependencies"](source)[0]
            relative = "Contents/Resources/lib/" + source.name
            target = fixture["finals"][relative]
            self._replace_loader_path(
                target,
                "@loader_path/" + dependency.name,
                "@rpath/" + dependency.name,
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "alternate"
            ):
                self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            relative = max(
                (
                    item for item in receipt.EXPECTED_FINAL_PATHS
                    if item.startswith("Contents/Resources/lib/")
                ),
                key=len,
            )
            target = fixture["finals"][relative]
            name = Path(relative).name
            self._replace_loader_path(
                target,
                "@loader_path/" + name,
                "@rpath/" + name,
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "install ID"
            ):
                self._generate(fixture)

    def test_system_load_and_entry_point_semantics_are_bound(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            self._replace_loader_path(
                target,
                "/usr/lib/libSystem.B.dylib",
                "/usr/lib/libc++.1.dylib",
            )
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "system loads"
            ):
                self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            raw = bytearray(target.read_bytes())
            command = struct.pack("<IIQQ", 0x80000028, 24, 16 * 1024, 0)
            offset = raw.index(command)
            struct.pack_into("<Q", raw, offset + 8, 16 * 1024 + 4)
            target.write_bytes(raw)
            target.chmod(0o755)
            with self.assertRaisesRegex(
                receipt.MacFFmpegReceiptError, "load-command semantics"
            ):
                self._generate(fixture)

    def test_source_formula_and_complete_source_graph_are_enforced(self):
        for mutation in ("wrong_formula", "missing_library"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                fixture = self._fixture(root)
                original = list(
                    fixture["dependencies"](fixture["ffmpeg"])
                )
                if mutation == "wrong_formula":
                    expected = fixture["sources"][
                        "Contents/Resources/lib/libvpx.12.dylib"
                    ]
                    wrong = (
                        fixture["cellar"]
                        / "x264"
                        / "r3222"
                        / "lib"
                        / expected.name
                    )
                    wrong.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(expected, wrong)
                    dependencies = [
                        wrong if item.name == expected.name else item
                        for item in original
                    ]
                else:
                    dependencies = [
                        item for item in original
                        if item.name != "libvpx.12.dylib"
                    ]

                def reader(path: Path) -> list[Path]:
                    if path.name in {"ffmpeg", "ffprobe"}:
                        return dependencies
                    return []

                fixture["dependencies"] = reader
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    self._generate(fixture)

    def test_formula_inventory_is_arch_pinned_and_canonical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._fixture(root)
            drifted = root / "formulae.txt"
            drifted.write_bytes(
                Path(fixture["inventory"]).read_bytes() + b"\n"
            )
            fixture["inventory"] = drifted
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                self._generate(fixture)

    def test_embedded_formula_inventory_is_required_and_exact(self):
        for mutation in ("missing", "drift", "symlink", "hardlink"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                fixture = self._fixture(root)
                embedded = fixture["embedded_inventory"]
                if mutation == "missing":
                    embedded.unlink()
                elif mutation == "drift":
                    embedded.write_bytes(embedded.read_bytes() + b"\n")
                elif mutation == "symlink":
                    embedded.unlink()
                    embedded.symlink_to(fixture["inventory"])
                else:
                    os.link(embedded, root / "inventory-hardlink")
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    self._generate(fixture)

        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            fixture["inventory"] = (
                ROOT / "packaging" / "macos-ffmpeg-formulae-x64.txt"
            )
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                self._generate(fixture)

    def test_receipt_rejects_duplicate_keys_and_noncanonical_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            payload, raw = self._generate(fixture)
            duplicate = (
                b'{\n  "schema": "autoeditor-macos-ffmpeg-bundle/v1",\n'
                + raw[2:]
            )
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                receipt.validate_receipt(payload, duplicate, "arm64")
            noncanonical = json.dumps(payload, sort_keys=True).encode("utf-8")
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                receipt.validate_receipt(payload, noncanonical, "arm64")

    def test_receipt_rejects_path_lineage_and_inventory_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            payload, _ = self._generate(fixture)
            mutations = []
            bad_path = copy.deepcopy(payload)
            bad_path["files"]["Contents/Resources/bin/ffmpeg"]["source"][
                "cellar_path"
            ] = "ffmpeg/8.1.2_1/bin/../ffmpeg"
            mutations.append(bad_path)
            bad_formula = copy.deepcopy(payload)
            bad_formula["files"]["Contents/Resources/lib/libvpx.12.dylib"][
                "source"
            ]["formula"] = "x264"
            mutations.append(bad_formula)
            bad_inventory = copy.deepcopy(payload)
            bad_inventory["formula_inventory"]["records"][0]["version"] = "0"
            mutations.append(bad_inventory)
            extra_key = copy.deepcopy(payload)
            extra_key["unexpected"] = True
            mutations.append(extra_key)
            bad_content = copy.deepcopy(payload)
            bad_content["files"]["Contents/Resources/bin/ffmpeg"][
                "macho_content_sha256"
            ] = "0" * 64
            mutations.append(bad_content)
            bad_whole = copy.deepcopy(payload)
            bad_whole["files"]["Contents/Resources/bin/ffmpeg"][
                "macho_whole_sha256"
            ] = "0" * 64
            mutations.append(bad_whole)
            bad_uuid = copy.deepcopy(payload)
            bad_uuid["files"]["Contents/Resources/bin/ffmpeg"][
                "source"
            ]["macho_uuid"] = "0" * 32
            mutations.append(bad_uuid)
            for mutation in mutations:
                raw = receipt.canonical_json_bytes(mutation)
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    receipt.validate_receipt(mutation, raw, "arm64")

    def test_verify_detects_final_byte_drift(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self._fixture(Path(td))
            payload, raw = self._generate(fixture)
            target = fixture["finals"]["Contents/Resources/bin/ffmpeg"]
            target.write_bytes(target.read_bytes() + b"changed")
            target.chmod(0o755)
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                receipt.verify_app(fixture["app"], payload, raw, "arm64")

    def test_authenticated_load_rejects_wrong_raw_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._fixture(root)
            payload, raw = self._generate(fixture)
            path = root / "receipt.json"
            path.write_bytes(raw)
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                receipt.load_authenticated_receipt(path, "0" * 64, "arm64")
            loaded, loaded_raw = receipt.load_authenticated_receipt(
                path, hashlib.sha256(raw).hexdigest(), "arm64"
            )
            self.assertEqual(loaded, payload)
            self.assertEqual(loaded_raw, raw)

    def test_otool_skips_install_id_but_resolves_loader_path_load(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binary = root / "libexample.dylib"
            dependency = root / "libdependency.dylib"
            binary.write_bytes(b"binary")
            dependency.write_bytes(b"dependency")
            outputs = {
                "-D": f"{binary}:\n@rpath/libexample.dylib\n",
                "-L": (
                    f"{binary}:\n"
                    "\t@rpath/libexample.dylib "
                    "(compatibility version 1.0.0, current version 1.0.0)\n"
                    "\t@loader_path/libdependency.dylib "
                    "(compatibility version 1.0.0, current version 1.0.0)\n"
                ),
            }

            def run(command, **_kwargs):
                self.assertEqual(command[0], "/usr/bin/otool")
                return receipt.subprocess.CompletedProcess(
                    command, 0, stdout=outputs[command[1]], stderr=""
                )

            with mock.patch.object(receipt.subprocess, "run", side_effect=run):
                observed = receipt._otool_dependencies(binary)
            self.assertEqual(observed, [dependency.resolve(strict=True)])

    def test_non_system_dynamic_loader_paths_resolve_or_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable_directory = root / "bin"
            executable_directory.mkdir()
            binary = executable_directory / "ffmpeg"
            dependency = executable_directory / "libdependency.dylib"
            binary.write_bytes(b"binary")
            dependency.write_bytes(b"dependency")

            def inspect(value: str, executable_directories=()):
                outputs = {
                    "-D": f"{binary}:\n",
                    "-L": (
                        f"{binary}:\n\t{value} "
                        "(compatibility version 1.0.0, current version 1.0.0)\n"
                    ),
                }

                def run(command, **_kwargs):
                    self.assertEqual(command[0], "/usr/bin/otool")
                    return receipt.subprocess.CompletedProcess(
                        command, 0, stdout=outputs[command[1]], stderr=""
                    )

                with mock.patch.object(
                    receipt.subprocess, "run", side_effect=run
                ):
                    return receipt._otool_dependencies(
                        binary,
                        executable_directories=executable_directories,
                    )

            self.assertEqual(
                inspect(
                    "@executable_path/libdependency.dylib",
                    (executable_directory,),
                ),
                [dependency.resolve(strict=True)],
            )
            for hostile in (
                "@rpath/libdependency.dylib",
                "@executable_path/libdependency.dylib",
                "@loader_path//libdependency.dylib",
                "@unknown/libdependency.dylib",
            ):
                with self.subTest(hostile=hostile), self.assertRaises(
                    receipt.MacFFmpegReceiptError
                ):
                    inspect(hostile)

    def test_install_id_must_be_the_first_otool_entry(self):
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "libexample.dylib"
            binary.write_bytes(b"binary")
            outputs = {
                "-D": f"{binary}:\n@rpath/libexample.dylib\n",
                "-L": (
                    f"{binary}:\n"
                    "\t/usr/lib/libSystem.B.dylib "
                    "(compatibility version 1.0.0, current version 1.0.0)\n"
                    "\t@rpath/libexample.dylib "
                    "(compatibility version 1.0.0, current version 1.0.0)\n"
                ),
            }

            def run(command, **_kwargs):
                self.assertEqual(command[0], "/usr/bin/otool")
                return receipt.subprocess.CompletedProcess(
                    command, 0, stdout=outputs[command[1]], stderr=""
                )

            with mock.patch.object(receipt.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(
                    receipt.MacFFmpegReceiptError, "install ID"
                ):
                    receipt._otool_dependencies(binary)

    def test_absolute_otool_paths_are_validated_before_system_exemption(self):
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "ffmpeg"
            binary.write_bytes(b"binary")

            def inspect(value: str):
                outputs = {
                    "-D": f"{binary}:\n",
                    "-L": (
                        f"{binary}:\n\t{value} "
                        "(compatibility version 1.0.0, current version 1.0.0)\n"
                    ),
                }

                def run(command, **_kwargs):
                    self.assertEqual(command[0], "/usr/bin/otool")
                    return receipt.subprocess.CompletedProcess(
                        command, 0, stdout=outputs[command[1]], stderr=""
                    )

                with mock.patch.object(
                    receipt.subprocess, "run", side_effect=run
                ):
                    return receipt._otool_dependencies(binary)

            for hostile in (
                "/usr/lib/../../tmp/escape.dylib",
                "/System/../tmp/escape.dylib",
                "/usr//lib/libSystem.B.dylib",
                "/usr/lib/./libSystem.B.dylib",
                "/usr/lib/libSystem.B.dylib/",
                "/usr/lib/control\x01name.dylib",
                "/usr/lib/format\u202ename.dylib",
                "/usr/lib/decomposed-e\u0301.dylib",
            ):
                with self.subTest(hostile=hostile), self.assertRaises(
                    receipt.MacFFmpegReceiptError
                ):
                    inspect(hostile)

            self.assertEqual(inspect("/usr/lib/libSystem.B.dylib"), [])
            self.assertEqual(
                inspect(
                    "/System/Library/Frameworks/Foundation.framework/"
                    "Versions/C/Foundation"
                ),
                [],
            )
            _, exact_system = receipt._canonical_absolute_otool_path(
                "/System/Library/example.dylib", binary
            )
            _, prefix_collision = receipt._canonical_absolute_otool_path(
                "/Systematic/example.dylib", binary
            )
            self.assertTrue(exact_system)
            self.assertFalse(prefix_collision)

    @unittest.skipUnless(
        Path("/usr/bin/otool").is_file() and Path("/usr/bin/true").is_file(),
        "requires the macOS system otool and true binary",
    )
    def test_real_otool_system_dependency_is_canonical_and_exempt(self):
        self.assertEqual(
            receipt._otool_dependencies(Path("/usr/bin/true")),
            [],
        )

    def test_write_is_create_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._fixture(root)
            _, raw = self._generate(fixture)
            output = root / "out" / "receipt.json"
            receipt.write_new_receipt(output, raw)
            self.assertEqual(output.read_bytes(), raw)
            with self.assertRaises(receipt.MacFFmpegReceiptError):
                receipt.write_new_receipt(output, raw)

    def test_failed_write_never_unlinks_a_replacement_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self._fixture(root)
            _, raw = self._generate(fixture)
            output = root / "out" / "receipt.json"
            moved = root / "out" / "opened-receipt.json"
            replacement = b"replacement-must-survive"

            def replace_then_fail(_descriptor, _view):
                output.rename(moved)
                output.write_bytes(replacement)
                raise OSError("injected write failure after replacement")

            with mock.patch.object(
                receipt.os, "write", side_effect=replace_then_fail
            ):
                with self.assertRaises(receipt.MacFFmpegReceiptError):
                    receipt.write_new_receipt(output, raw)

            self.assertEqual(output.read_bytes(), replacement)
            self.assertTrue(moved.exists())


if __name__ == "__main__":
    unittest.main()
