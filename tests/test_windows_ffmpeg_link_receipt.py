from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "windows_ffmpeg_link_receipt.py"
SPEC = importlib.util.spec_from_file_location("windows_ffmpeg_link_receipt", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load linkage verifier")
linkage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = linkage
SPEC.loader.exec_module(linkage)


class WindowsFFmpegLinkReceiptTests(unittest.TestCase):
    def _write_capture(self, root: Path, *, program: str = "ffmpeg") -> dict[str, Path]:
        executable_name = linkage.PROGRAMS[program]
        reproduce = root / f"{program}-reproduce.tar"
        members = {
            "response.txt": (
                f"/out:{executable_name}\n"
                f"-lldmap:/artifact/{program}.lldmap\n"
                "-verbose\n"
                "build/autoeditor-media/sources/FFmpeg-deadbeef/fftools/"
                f"{program}.o\n"
                "build/autoeditor-media/prefix/lib/libx264.a\n"
                "opt/llvm-mingw/x86_64-w64-mingw32/lib/libmingw32.a\n"
            ).encode(),
            f"build/autoeditor-media/sources/FFmpeg-deadbeef/fftools/{program}.o": b"object",
            "build/autoeditor-media/prefix/lib/libx264.a": b"!<arch>\n",
            "opt/llvm-mingw/x86_64-w64-mingw32/lib/libmingw32.a": b"!<arch>\n",
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
            "140001008 00000008     4         encoder.o:(.text)\n",
            encoding="utf-8",
        )
        verbose = root / f"{program}.verbose.log"
        verbose.write_text(
            "lld: Loaded libx264.a(encoder.o) for x264_encoder_open\n"
            "lld: Reading libmingw32.a(crtexe.o)\n",
            encoding="utf-8",
        )
        executable = root / executable_name
        executable.write_bytes(b"MZ" + b"\0" * 64)
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
                ["x264", "ffmpeg", "mingw-w64"],
            )
            self.assertEqual(
                len(receipt["verbose_log"]["selected_archive_members"]), 2
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
                raw = b"!<arch>\n"
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
            capture["unstripped_executable"].write_bytes(b"MZchanged")
            recomputed = linkage.create_receipt(**capture)
            self.assertNotEqual(
                recomputed["unstripped_executable"]["sha256"],
                receipt["unstripped_executable"]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
