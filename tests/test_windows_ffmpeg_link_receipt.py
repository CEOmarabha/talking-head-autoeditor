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


def make_coff_object() -> bytes:
    return struct.pack("<H", linkage.COFF_AMD64) + b"\0" * 38


def make_short_import(dll: str) -> bytes:
    strings = b"__imp_test\0" + dll.encode("ascii") + b"\0"
    return struct.pack(
        "<HHHHIIHH", 0, 0xFFFF, 0, linkage.COFF_AMD64, 0, len(strings), 0, 0
    ) + strings


class WindowsFFmpegLinkReceiptTests(unittest.TestCase):
    def _write_capture(self, root: Path, *, program: str = "ffmpeg") -> dict[str, Path]:
        executable_name = linkage.PROGRAMS[program]
        reproduce = root / f"{program}-reproduce.tar"
        members = {
            "response.txt": (
                f"/out:{executable_name}\n"
                f"-lldmap:/artifact/{program}.lldmap\n"
                "-verbose\n"
                "-threads:1\n"
                "build/autoeditor-media/sources/FFmpeg-deadbeef/fftools/"
                f"{program}.o\n"
                "build/autoeditor-media/prefix/lib/libx264.a\n"
                "opt/llvm-mingw/x86_64-w64-mingw32/lib/libkernel32.a\n"
                "opt/llvm-mingw/x86_64-w64-mingw32/lib/libmingw32.a\n"
            ).encode(),
            f"build/autoeditor-media/sources/FFmpeg-deadbeef/fftools/{program}.o": make_coff_object(),
            "build/autoeditor-media/prefix/lib/libx264.a": make_archive(
                [("encoder.o", make_coff_object())]
            ),
            "opt/llvm-mingw/x86_64-w64-mingw32/lib/libkernel32.a": make_archive(
                [("kernel.o", make_short_import("kernel32.dll"))]
            ),
            "opt/llvm-mingw/x86_64-w64-mingw32/lib/libmingw32.a": make_archive(
                [("crtexe.o", make_coff_object())]
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
            "140001010 00000008     4         crtexe.o:(.text)\n",
            encoding="utf-8",
        )
        verbose = root / f"{program}.verbose.log"
        verbose.write_text(
            "lld: Loaded libx264.a(encoder.o) for x264_encoder_open\n"
            "lld: Reading libx264.a(encoder.o)\n"
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
                ["x264", "ffmpeg", "mingw-w64", "mingw-w64"],
            )
            self.assertEqual(
                len(receipt["verbose_log"]["selected_archive_members"]), 3
            )
            self.assertEqual(receipt["verbose_log"]["system_imports"], ["kernel32.dll"])
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
                    ("kernel.o", make_coff_object()),
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
            with capture["verbose_log"].open("a", encoding="utf-8") as handle:
                handle.write(
                    "lld: Loaded libkernel32.a(kernel.o) for __IMPORT_DESCRIPTOR_kernel32\n"
                    "lld: Reading libkernel32.a(kernel.o)\n"
                )
            receipt = linkage.create_receipt(**capture)
            group = next(
                item
                for item in receipt["verbose_log"]["selected_archive_members"]
                if item["archive"].endswith("libkernel32.a")
            )
            self.assertEqual(group["event_counts"], {"loaded": 1, "reading": 2})
            self.assertEqual(group["candidate_scope"], "exact")

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
        self.assertIn("--Map=/artifact/linkage/$program.lldmap", build)
        self.assertIn("--verbose", build)
        self.assertIn("--threads=1", build)
        self.assertIn("--reproduce=/artifact/linkage/$program-reproduce.tar", build)
        self.assertNotIn("--trace", build)
        self.assertNotIn("--cref", build)
        self.assertGreaterEqual(build.count("windows_ffmpeg_link_receipt.py verify"), 1)
        self.assertIn("tests.test_windows_ffmpeg_link_receipt", workflow)
        self.assertIn("windows-ffmpeg-two", workflow)
        self.assertIn("cmp \\", workflow)


if __name__ == "__main__":
    unittest.main()
