from __future__ import annotations

import importlib.util
import io
import json
import os
import struct
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
SCRIPT = ROOT / "packaging" / "windows_ffmpeg_link_receipt.py"
BUILD_SCRIPT = ROOT / "packaging" / "build_windows_ffmpeg.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-ffmpeg.yml"
SPEC = importlib.util.spec_from_file_location("windows_ffmpeg_link_receipt", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load linkage verifier")
linkage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = linkage
SPEC.loader.exec_module(linkage)


def make_pe(import_name: str = "kernel32.dll") -> bytes:
    pe_offset = 0x80
    optional_size = 240
    section_table = pe_offset + 24 + optional_size
    raw_offset = 0x200
    raw_size = 0x400
    data = bytearray(raw_offset + raw_size)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b"PE\0\0"
    coff = pe_offset + 4
    struct.pack_into(
        "<HHIIIHH", data, coff, 0x8664, 1, 0, 0, 0, optional_size, 0x0022
    )
    optional = pe_offset + 24
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<H", data, optional + 68, 3)
    struct.pack_into("<H", data, optional + 70, 0x0160)
    struct.pack_into("<I", data, optional + 108, 16)
    struct.pack_into("<II", data, optional + 112 + 8, 0x1000, 40)
    section = section_table
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x300, 0x1000, raw_size, raw_offset)
    struct.pack_into("<I", data, section + 36, 0x40000040)
    struct.pack_into("<IIIII", data, raw_offset, 0, 0, 0, 0x1050, 0)
    encoded = import_name.encode("ascii") + b"\0"
    data[raw_offset + 0x50:raw_offset + 0x50 + len(encoded)] = encoded
    return bytes(data)


def make_archive(members: list[tuple[str, bytes]]) -> bytes:
    raw = bytearray(linkage.ARCHIVE_MAGIC)
    for name, payload in members:
        encoded_name = (name + "/").encode("utf-8")
        if len(encoded_name) > 16:
            raise ValueError("test archive member name is too long")
        header = (
            encoded_name.ljust(16, b" ")
            + b"0".ljust(12, b" ")
            + b"0".ljust(6, b" ")
            + b"0".ljust(6, b" ")
            + b"100644".ljust(8, b" ")
            + str(len(payload)).encode("ascii").ljust(10, b" ")
            + b"`\n"
        )
        if len(header) != 60:
            raise AssertionError("invalid test archive header")
        raw.extend(header)
        raw.extend(payload)
        if len(payload) & 1:
            raw.extend(b"\n")
    return bytes(raw)


def make_coff_object(symbol: str = "test_symbol") -> bytes:
    encoded = symbol.encode("utf-8")
    section_offset = 20
    raw_offset = section_offset + 40
    symbol_offset = raw_offset + 1
    string_table = struct.pack("<I", 5 + len(encoded)) + encoded + b"\0"
    raw = bytearray(symbol_offset + linkage.COFF_SYMBOL_BYTES + len(string_table))
    struct.pack_into(
        "<HHIIIHH",
        raw,
        0,
        linkage.COFF_AMD64,
        1,
        0,
        symbol_offset,
        1,
        0,
        0,
    )
    raw[section_offset:section_offset + 8] = b".text\0\0\0"
    struct.pack_into("<I", raw, section_offset + 16, 1)
    struct.pack_into("<I", raw, section_offset + 20, raw_offset)
    struct.pack_into("<I", raw, section_offset + 36, 0x60000020)
    raw[raw_offset] = 0xC3
    struct.pack_into("<II", raw, symbol_offset, 0, 4)
    struct.pack_into("<IhHBB", raw, symbol_offset + 8, 0, 1, 0, 2, 0)
    raw[symbol_offset + linkage.COFF_SYMBOL_BYTES:] = string_table
    return bytes(raw)


def make_short_import(dll: str) -> bytes:
    strings = b"__imp_test\0" + dll.encode("ascii") + b"\0"
    return struct.pack(
        "<HHHHIIHH", 0, 0xFFFF, 0, linkage.COFF_AMD64, 0, len(strings), 0, 0
    ) + strings


class WindowsFFmpegLinkReceiptTests(unittest.TestCase):
    def _write_capture(self, root: Path, *, program: str = "ffmpeg") -> dict[str, Path]:
        executable_name = linkage.PROGRAMS[program]
        ffmpeg_root = linkage.FFMPEG_SOURCE_ROOT
        reproduce = root / f"{program}-reproduce.tar"
        members = {
            "response.txt": (
                f"/out:{executable_name}\n"
                f"-lldmap:/artifact/{program}.lldmap\n"
                "-verbose\n"
                "-threads:1\n"
                f"{ffmpeg_root}fftools/{program}.o\n"
                "build/autoeditor-media/prefix/lib/libx264.a\n"
                "build/autoeditor-media/prefix/lib/libz.a\n"
                "opt/llvm-mingw/lib/clang/22/lib/windows/"
                "libclang_rt.builtins-x86_64.a\n"
                "opt/llvm-mingw/x86_64-w64-mingw32/lib/libkernel32.a\n"
                "opt/llvm-mingw/x86_64-w64-mingw32/lib/libmingw32.a\n"
            ).encode(),
            f"{ffmpeg_root}fftools/{program}.o": make_coff_object(program),
            "build/autoeditor-media/prefix/lib/libx264.a": make_archive(
                [("encoder.o", make_coff_object("x264_encoder_open"))]
            ),
            "build/autoeditor-media/prefix/lib/libz.a": make_archive(
                [("adler32.o", make_coff_object("zlib_adler32"))]
            ),
            "opt/llvm-mingw/lib/clang/22/lib/windows/libclang_rt.builtins-x86_64.a": make_archive(
                [("chkstk.o", make_coff_object("___chkstk_ms"))]
            ),
            "opt/llvm-mingw/x86_64-w64-mingw32/lib/libkernel32.a": make_archive(
                [("kernel.o", make_short_import("kernel32.dll"))]
            ),
            "opt/llvm-mingw/x86_64-w64-mingw32/lib/libmingw32.a": make_archive(
                [("crtexe.o", make_coff_object("main"))]
            ),
        }
        with tarfile.open(reproduce, "w") as archive:
            for name, raw in members.items():
                info = tarfile.TarInfo(f"{program}-reproduce/{name}")
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
        lld_map = root / f"{program}.lldmap"
        lld_map.write_text(
            "Address  Size     Align Out     In      Symbol\n"
            "140001000 00000010    16 .text\n"
            f"140001000 00000008     4         fftools/{program}.o:(.text)\n"
            "140001008 00000008     4         encoder.o:(.text)\n"
            "140001010 00000008     4         adler32.o:(.text)\n"
            "140001018 00000008     4         chkstk.o:(.text)\n"
            "140001020 00000008     4         crtexe.o:(.text)\n",
            encoding="utf-8",
        )
        verbose = root / f"{program}.verbose.log"
        verbose.write_text(
            f"lld: Reading fftools/{program}.o\n"
            "lld: Reading /build/autoeditor-media/prefix/lib/libx264.a\n"
            "lld: Reading /build/autoeditor-media/prefix/lib/libz.a\n"
            "lld: Reading /opt/llvm-mingw/lib/clang/22/lib/windows/"
            "libclang_rt.builtins-x86_64.a\n"
            "lld: Reading /opt/llvm-mingw/x86_64-w64-mingw32/lib/libkernel32.a\n"
            "lld: Reading /opt/llvm-mingw/x86_64-w64-mingw32/lib/libmingw32.a\n"
            "lld: Loaded libx264.a(encoder.o) for x264_encoder_open\n"
            "lld: Reading libx264.a(encoder.o)\n"
            "lld: Reading libz.a(adler32.o)\n"
            "lld: Loaded libz.a(adler32.o) for zlib_adler32\n"
            "lld: Reading libclang_rt.builtins-x86_64.a(chkstk.o)\n"
            "lld: Loaded libclang_rt.builtins-x86_64.a(chkstk.o) for ___chkstk_ms\n"
            "lld: Reading libkernel32.a(kernel.o)\n"
            "lld: Loaded libmingw32.a(crtexe.o) for main\n"
            "lld: Reading libmingw32.a(crtexe.o)\n",
            encoding="utf-8",
        )
        executable = root / executable_name
        executable.write_bytes(make_pe())
        return {
            "program": program,
            "reproduce": reproduce,
            "lld_map": lld_map,
            "verbose_log": verbose,
            "unstripped_executable": executable,
        }

    def test_create_and_verify_exact_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            receipt = linkage.create_receipt(**capture)
            self.assertEqual(receipt["schema"], linkage.SCHEMA)
            self.assertEqual(
                [item["origin"] for item in receipt["reproducer"]["inputs"]],
                [
                    "x264",
                    "zlib",
                    "ffmpeg",
                    "llvm-project",
                    "mingw-w64",
                    "mingw-w64",
                ],
            )
            self.assertEqual(
                len(receipt["verbose_log"]["selected_archive_members"]), 5
            )
            self.assertEqual(receipt["verbose_log"]["system_imports"], ["kernel32.dll"])
            self.assertEqual(
                [item["path"] for item in receipt["verbose_log"]["read_inputs"]],
                [item["path"] for item in receipt["reproducer"]["inputs"]],
            )
            self.assertEqual(
                receipt["closure"],
                {
                    "build_only_source_ids": ["llvm-mingw", "nasm"],
                    "code_source_ids": [
                        "ffmpeg",
                        "llvm-project",
                        "mingw-w64",
                        "x264",
                        "zlib",
                    ],
                    "import_source_ids": ["mingw-w64"],
                    "mapping": "exact-reproducer-input-and-archive-member-sha256",
                    "reproducer_input_count": 6,
                    "reproducer_source_ids": [
                        "ffmpeg",
                        "llvm-project",
                        "mingw-w64",
                        "x264",
                        "zlib",
                    ],
                    "selected_code_member_count": 4,
                    "selected_directive_member_count": 0,
                    "selected_import_member_count": 1,
                    "status": "verified",
                },
            )
            receipt_path = root / "receipt.json"
            receipt_path.write_bytes(linkage.canonical_json(receipt))
            self.assertEqual(linkage.load_receipt(receipt_path), receipt)

    def test_unknown_input_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            with tarfile.open(capture["reproduce"], "a") as archive:
                raw = b"evil"
                info = tarfile.TarInfo("ffmpeg-reproduce/tmp/evil.o")
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            with self.assertRaisesRegex(linkage.LinkageError, "outside every allowed"):
                linkage.create_receipt(**capture)

    def test_symlink_reproducer_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            with tarfile.open(capture["reproduce"], "a") as archive:
                info = tarfile.TarInfo("ffmpeg-reproduce/build/link.o")
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp/evil"
                archive.addfile(info)
            with self.assertRaisesRegex(linkage.LinkageError, "must be regular"):
                linkage.create_receipt(**capture)

    def test_duplicate_archive_basename_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            with tarfile.open(capture["reproduce"], "a") as archive:
                raw = make_archive([("duplicate.o", make_coff_object())])
                info = tarfile.TarInfo(
                    "ffmpeg-reproduce/opt/llvm-mingw/x86_64-w64-mingw32/lib/alt/libx264.a"
                )
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            with self.assertRaisesRegex(linkage.LinkageError, "basenames are ambiguous"):
                linkage.create_receipt(**capture)

    def test_selected_archive_absent_from_reproducer_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            capture["verbose_log"].write_text(
                "lld: Loaded libevil.a(evil.o) for evil\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(linkage.LinkageError, "absent from reproducer"):
                linkage.create_receipt(**capture)

    def test_verbose_must_read_every_reproducer_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            text = capture["verbose_log"].read_text(encoding="utf-8")
            capture["verbose_log"].write_text(
                text.replace("lld: Reading fftools/ffmpeg.o\n", ""),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(linkage.LinkageError, "does not read every"):
                linkage.create_receipt(**capture)

    def test_unparsed_loaded_event_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            text = capture["verbose_log"].read_text(encoding="utf-8")
            capture["verbose_log"].write_text(
                text.replace(
                    "Loaded libx264.a(encoder.o) for x264_encoder_open",
                    "Loaded libx264.a[encoder.o] for x264_encoder_open",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(linkage.LinkageError, "unparsed verbose Loaded"):
                linkage.create_receipt(**capture)

    def test_map_archive_member_absent_from_verbose_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            text = capture["lld_map"].read_text(encoding="utf-8")
            capture["lld_map"].write_text(
                text.replace("encoder.o:(.text)", "ghost.o:(.text)"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(linkage.LinkageError, "absent from reproducer/verbose"):
                linkage.create_receipt(**capture)

    def test_short_import_must_equal_an_actual_pe_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            capture["unstripped_executable"].write_bytes(make_pe("user32.dll"))
            with self.assertRaisesRegex(linkage.LinkageError, "differs from PE imports"):
                linkage.create_receipt(**capture)

    def test_code_bearing_member_requires_reading_and_loaded_events(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            text = capture["verbose_log"].read_text(encoding="utf-8")
            capture["verbose_log"].write_text(
                text.replace(
                    "lld: Loaded libx264.a(encoder.o) for x264_encoder_open\n", ""
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(linkage.LinkageError, "event count exceeds candidates"):
                linkage.create_receipt(**capture)

    def test_duplicate_same_name_import_members_are_counted_not_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            archive_path = "opt/llvm-mingw/x86_64-w64-mingw32/lib/libkernel32.a"
            with tarfile.open(capture["reproduce"], "r") as archive:
                captured = {
                    member.name: archive.extractfile(member).read()
                    for member in archive.getmembers()
                    if member.isfile()
                }
            root_name = "ffmpeg-reproduce"
            captured[f"{root_name}/{archive_path}"] = make_archive(
                [
                    ("kernel.o", make_short_import("kernel32.dll")),
                    ("kernel.o", make_short_import("kernel32.dll")),
                ]
            )
            rewritten = root / "rewritten.tar"
            with tarfile.open(rewritten, "w") as archive:
                for name, raw in captured.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            capture["reproduce"] = rewritten
            receipt = linkage.create_receipt(**capture)
            group = next(
                item
                for item in receipt["verbose_log"]["selected_archive_members"]
                if item["archive"].endswith("libkernel32.a")
            )
            self.assertEqual(group["event_counts"], {"loaded": 0, "reading": 1})
            self.assertEqual(
                group["import_candidate_scope"],
                "actual-pe-import-conservative",
            )
            self.assertEqual(group["selected_code_members"], [])
            self.assertEqual(group["selected_import_member_count"], 1)

    def test_symbol_normalization_changes_exactly_one_leading_underscore(self):
        self.assertEqual(linkage._reason_match_rank({"test"}, "test"), 0)
        self.assertEqual(linkage._reason_match_rank({"_test"}, "test"), 1)
        self.assertEqual(linkage._reason_match_rank({"test"}, "_test"), 1)
        self.assertIsNone(linkage._reason_match_rank({"__test"}, "test"))
        self.assertIsNone(linkage._reason_match_rank({"test"}, "__test"))
        self.assertEqual(
            linkage._reason_match_rank(
                {"__imp_test"}, "__declspec(dllimport) test"
            ),
            0,
        )

    def test_equal_rank_code_candidate_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            archive_path = "build/autoeditor-media/prefix/lib/libx264.a"
            with tarfile.open(capture["reproduce"], "r") as archive:
                captured = {
                    member.name: archive.extractfile(member).read()
                    for member in archive.getmembers()
                    if member.isfile()
                }
            captured[f"ffmpeg-reproduce/{archive_path}"] = make_archive(
                [
                    ("encoder.o", make_coff_object("x264_encoder_open")),
                    ("encoder.o", make_coff_object("x264_encoder_open")),
                ]
            )
            rewritten = root / "ambiguous.tar"
            with tarfile.open(rewritten, "w") as archive:
                for name, raw in captured.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            capture["reproduce"] = rewritten
            with self.assertRaisesRegex(linkage.LinkageError, "resolves ambiguously"):
                linkage.create_receipt(**capture)

    def test_receipt_rejects_source_or_member_identity_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt = linkage.create_receipt(**self._write_capture(root))
            changed = json.loads(json.dumps(receipt))
            changed["reproducer"]["inputs"][0]["source_archive_sha256"] = "f" * 64
            with self.assertRaisesRegex(linkage.LinkageError, "source archive mapping"):
                linkage.validate_receipt(changed)

            changed = json.loads(json.dumps(receipt))
            group = next(
                item
                for item in changed["verbose_log"]["selected_archive_members"]
                if item["archive"].endswith("libx264.a")
            )
            group["candidates"][0]["sha256"] = "f" * 64
            with self.assertRaisesRegex(linkage.LinkageError, "exact candidate"):
                linkage.validate_receipt(changed)

            changed = json.loads(json.dumps(receipt))
            changed["verbose_log"]["read_inputs"][0]["display_name"] = "evil.o"
            with self.assertRaisesRegex(linkage.LinkageError, "display mapping"):
                linkage.validate_receipt(changed)

    def test_verbose_member_must_exist_inside_captured_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            text = capture["verbose_log"].read_text(encoding="utf-8")
            capture["verbose_log"].write_text(
                text.replace("encoder.o", "absent.o"), encoding="utf-8"
            )
            with self.assertRaisesRegex(linkage.LinkageError, "absent from archive"):
                linkage.create_receipt(**capture)

    def test_empty_lld_map_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            capture["lld_map"].write_text(
                "Address  Size     Align Out     In      Symbol\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(linkage.LinkageError, "no live input"):
                linkage.create_receipt(**capture)

    def test_noncanonical_or_tampered_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture = self._write_capture(root)
            receipt = linkage.create_receipt(**capture)
            path = root / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(linkage.LinkageError, "canonical"):
                linkage.load_receipt(path)
            receipt["unstripped_executable"]["sha256"] = "f" * 64
            path.write_bytes(linkage.canonical_json(receipt))
            os.chmod(path, 0o600)
            self.assertEqual(linkage.load_receipt(path), receipt)
            changed = bytearray(capture["unstripped_executable"].read_bytes())
            changed[-1] ^= 1
            capture["unstripped_executable"].write_bytes(changed)
            recomputed = linkage.create_receipt(**capture)
            self.assertNotEqual(
                recomputed["unstripped_executable"]["sha256"],
                receipt["unstripped_executable"]["sha256"],
            )

    def test_receipt_creation_refuses_existing_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.json"
            target.write_bytes(b"preserve")
            receipt = root / "receipt.json"
            receipt.symlink_to(target)
            with self.assertRaisesRegex(linkage.LinkageError, "refusing to replace"):
                linkage._write_new_receipt(receipt, b"changed")
            self.assertEqual(target.read_bytes(), b"preserve")

    def test_build_and_workflow_bind_sequential_reproducible_link_capture(self):
        build = BUILD_SCRIPT.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("make -j2 ffmpeg.exe ffprobe.exe", build)
        self.assertIn('make -j1 "$program.exe" "LDFLAGS-$program=$link_flags"', build)
        self.assertIn(
            "--Map=/artifact/link-evidence/${program}-lld.map", build
        )
        self.assertIn("--verbose", build)
        self.assertIn("--threads=1", build)
        self.assertIn(
            "--reproduce=/artifact/link-evidence/${program}-reproduce.tar", build
        )
        self.assertNotIn("--trace", build)
        self.assertNotIn("--cref", build)
        self.assertGreaterEqual(build.count("windows_ffmpeg_link_receipt.py verify"), 1)
        self.assertIn("tests.test_windows_ffmpeg_link_receipt", workflow)
        self.assertIn("windows-ffmpeg-two", workflow)
        self.assertIn("cmp \\", workflow)


if __name__ == "__main__":
    unittest.main()
