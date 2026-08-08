from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "verify_windows_ffmpeg.py"
SOURCE_LOCK = ROOT / "packaging" / "windows-ffmpeg-sources.lock.json"
CAPABILITIES = ROOT / "packaging" / "windows-ffmpeg-capabilities.json"
BUILD_SCRIPT = ROOT / "packaging" / "build_windows_ffmpeg.sh"
GIT_ATTRIBUTES = ROOT / ".gitattributes"
SPEC = importlib.util.spec_from_file_location("verify_windows_ffmpeg", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)

SOURCE_BUNDLE_SPEC = importlib.util.spec_from_file_location(
    "source_bundle_for_windows_test", ROOT / "packaging" / "source_bundle.py"
)
if SOURCE_BUNDLE_SPEC is None or SOURCE_BUNDLE_SPEC.loader is None:
    raise RuntimeError("cannot load source_bundle.py")
source_bundle = importlib.util.module_from_spec(SOURCE_BUNDLE_SPEC)
sys.modules[SOURCE_BUNDLE_SPEC.name] = source_bundle
SOURCE_BUNDLE_SPEC.loader.exec_module(source_bundle)


def canonical(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def make_pe(import_name="kernel32.dll", *, timestamp=0, dll_characteristics=0x0160):
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
        "<HHIIIHH",
        data,
        coff,
        0x8664,
        1,
        timestamp,
        0,
        0,
        optional_size,
        0x0022,
    )
    optional = pe_offset + 24
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<H", data, optional + 68, 3)
    struct.pack_into("<H", data, optional + 70, dll_characteristics)
    struct.pack_into("<I", data, optional + 108, 16)
    if import_name:
        struct.pack_into("<II", data, optional + 112 + 8, 0x1000, 40)
    section = section_table
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x300, 0x1000, raw_size, raw_offset)
    struct.pack_into("<I", data, section + 36, 0x40000040)
    if import_name:
        struct.pack_into("<IIIII", data, raw_offset, 0, 0, 0, 0x1050, 0)
        encoded = import_name.encode("ascii") + b"\0"
        data[raw_offset + 0x50:raw_offset + 0x50 + len(encoded)] = encoded
    return bytes(data)


def write_link_evidence(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for program, names in verifier.LINK_EVIDENCE_FILES.items():
        (root / names["lld_map"]).write_text(
            "Address  Size     Align Out     In      Symbol\n"
            "00001000 00000010  4096 .text\n",
            encoding="utf-8",
        )
        (root / names["verbose"]).write_text(
            f"{program}_g.exe --Map={program}-lld.map --verbose "
            f"--reproduce={program}-reproduce.tar\n",
            encoding="utf-8",
        )
        reproducer_root = Path(names["reproducer"]).stem
        members = {
            f"{reproducer_root}/input.a": b"archive input\n",
            f"{reproducer_root}/input.o": b"object input\n",
            f"{reproducer_root}/response.txt": (
                f"-lldmap:{program}-lld.map\n-verbose\n/out:{program}_g.exe\n"
            ).encode("utf-8"),
        }
        with tarfile.open(root / names["reproducer"], mode="w") as archive:
            for name, raw in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
    return root


class WindowsFFmpegContractTests(unittest.TestCase):
    def setUp(self):
        self.source_value = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
        self.capability_value = json.loads(CAPABILITIES.read_text(encoding="utf-8"))

    def _write(self, root, name, value):
        path = Path(root) / name
        path.write_bytes(canonical(value))
        return path

    def _receipt(self):
        digest = "1" * 64
        loaded_source = verifier.load_source_lock(SOURCE_LOCK)
        bundle_lock_sha256 = hashlib.sha256(
            canonical(verifier.bundle_lock_value(loaded_source))
        ).hexdigest()
        required = self.capability_value["required"]
        output = {
            "authenticode_content_bytes": 1536,
            "authenticode_content_sha256": digest,
            "buildconf_sha256": digest,
            "bytes": 1536,
            "filename": "ffmpeg.exe",
            "pe": {
                "certificate_bytes": 0,
                "characteristics": 0x0022,
                "coff_timestamp": 0,
                "dll_characteristics": 0x0160,
                "imports": ["kernel32.dll"],
                "machine": "AMD64",
            },
            "sha256": digest,
            "version": "ffmpeg version autoeditor.n8.1.2-34-g9b6c8969e0",
            "version_sha256": digest,
        }
        ffprobe = copy.deepcopy(output)
        ffprobe["filename"] = "ffprobe.exe"
        link_programs = {}
        for program, names in verifier.LINK_EVIDENCE_FILES.items():
            reproducer_root = Path(names["reproducer"]).stem
            link_programs[program] = {
                "lld_map": {
                    "bytes": 1,
                    "filename": names["lld_map"],
                    "sha256": digest,
                },
                "reproducer": {
                    "bytes": 1,
                    "filename": names["reproducer"],
                    "members": [
                        {"bytes": 1, "path": f"{reproducer_root}/input.a", "sha256": digest},
                        {"bytes": 1, "path": f"{reproducer_root}/input.o", "sha256": digest},
                        {"bytes": 1, "path": f"{reproducer_root}/response.txt", "sha256": digest},
                    ],
                    "sha256": digest,
                },
                "verbose": {
                    "bytes": 1,
                    "filename": names["verbose"],
                    "sha256": digest,
                },
            }
        return {
            "build": {
                "capabilities_sha256": verifier.EXPECTED_CAPABILITIES_SHA256,
                "configure_args": self.capability_value["build"]["configure_args"],
                "container_image": self.capability_value["build"]["container_image"],
                "environment": self.capability_value["build"]["environment"],
                "link_evidence": self.capability_value["build"]["link_evidence"],
                "make": self.capability_value["build"]["make"],
                "source_date_epoch": 1785458830,
                "strip": self.capability_value["build"]["strip"],
            },
            "inventory": {
                "codecs": ["h264"],
                "command_output_sha256": {
                    name: digest for name in sorted(verifier.COMMAND_HASH_FIELDS)
                },
                "decoders": sorted(required["decoders"]),
                "demuxers": sorted(required["demuxers"]),
                "encoders": sorted(required["encoders"]),
                "filters": sorted(required["filters"]),
                "input_devices": sorted(required["input_devices"]),
                "muxers": sorted(required["muxers"]),
                "output_devices": sorted(required["output_devices"]),
                "protocols": required["protocols"],
            },
            "license_expression": "GPL-2.0-or-later",
            "link_evidence": {
                "closure_status": "input-classification-unverified",
                "programs": link_programs,
            },
            "outputs": {"ffmpeg": output, "ffprobe": ffprobe},
            "runtime_notices": [
                {**notice, "bytes": 1, "sha256": digest}
                for notice in self.capability_value["runtime_notices"]
            ],
            "runtime_smoke": {
                "checks": list(verifier.RUNTIME_SMOKE_CHECKS),
                "status": "passed",
            },
            "schema": verifier.RECEIPT_SCHEMA,
            "source": {
                "bundle_bytes": 1,
                "bundle_lock_sha256": bundle_lock_sha256,
                "bundle_manifest_bytes": 1,
                "bundle_manifest_sha256": digest,
                "bundle_sha256": digest,
                "primary_lock_sha256": verifier.EXPECTED_SOURCE_LOCK_SHA256,
                "repository_commit": "2" * 40,
                "repository_tree": "3" * 40,
            },
            "target": self.capability_value["target"],
        }

    def test_tracked_contracts_are_canonical_and_digest_pinned(self):
        source, capabilities = verifier.load_contracts(SOURCE_LOCK, CAPABILITIES)
        self.assertEqual(source.sha256, verifier.EXPECTED_SOURCE_LOCK_SHA256)
        self.assertEqual(capabilities.sha256, verifier.EXPECTED_CAPABILITIES_SHA256)
        self.assertEqual(SOURCE_LOCK.read_bytes(), canonical(self.source_value))
        self.assertEqual(CAPABILITIES.read_bytes(), canonical(self.capability_value))
        self.assertEqual(
            self.capability_value["runtime_notices"],
            verifier.EXPECTED_RUNTIME_NOTICES,
        )

    def test_windows_checkout_preserves_canonical_contract_line_endings(self):
        attributes = GIT_ATTRIBUTES.read_text(encoding="utf-8").splitlines()
        self.assertIn(
            "/packaging/windows-ffmpeg-capabilities.json text eol=lf",
            attributes,
        )
        self.assertIn(
            "/packaging/windows-ffmpeg-sources.lock.json text eol=lf",
            attributes,
        )

    def test_source_pins_match_the_audited_commits_trees_and_archives(self):
        records = {item["id"]: item for item in self.source_value["sources"]}
        expected = {
            "ffmpeg": (
                "9b6c8969e05b4f0b29f0f85cd501be6b3e582e6b",
                "d3beee09bdb9ccb2ab7f71a1e72210be2a93e5f6",
                "7e779215eae16ad7e93ddad59bd82822bd3d34e4dc61f9996f9481b2c0605bc3",
                16903934,
            ),
            "llvm-project": (
                "ca7933e47d3a3451d81e72ac174dcb5aa28b59d1",
                "1e4fdb95266974a0cbca9ec4c6f740488322f238",
                "9dd0aba32a0c2b9e8e808e9b67502cc977f22220f67268bbfd937fa07e5ee6ce",
                258325313,
            ),
            "llvm-mingw": (
                "170b7e1ec4ad1d9264e6ba320cd4d02f96299c60",
                "bc5f7040c389e8862daaee41c2fb837b2f1cad5a",
                "be6c80d7a8ac205b2b7da676030a4fd4e0a7f40e95cd3fdba772f325639c6117",
                70880,
            ),
            "mingw-w64": (
                "c28e9555bb8800c53449f42a465ad9a5676fce88",
                "16044fc7a8a2b36978b82ce8572f7280ba581268",
                "f07cfc452676fe1061c4b6c062335903dbe0d5d18cda6ab8ee6d94637d32a87a",
                15766022,
            ),
            "nasm": (
                "e9fac2faa62647bb50f1a61c26212c63c87090ae",
                "f780f92b74638c0d3daf5ffffdb3c36c2ad8cc25",
                "b7324cbe86e767b65f26f467ed8b12ad80e124e3ccb89076855c98e43a9eddd4",
                1499136,
            ),
            "x264": (
                "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee",
                "0b8e15dd14ad8d2fb8905df7785003b475236315",
                "d0967a1348c85dfde363bb52610403be898171493100561efa0dd05d5fd1ae50",
                1040667,
            ),
            "zlib": (
                "e3dc0a85b7032e98380dec011bc8f2c2ee0d8fca",
                "28feaf0a47eef3165c49b4ddbb1563aabb01ac68",
                "33356dac6140d584347fe46bcf7083bd949dec49ac4b52417ae334ec70e3dbc3",
                1571579,
            ),
        }
        for source_id, values in expected.items():
            commit, tree, digest, size = values
            self.assertEqual(records[source_id]["git_ref"]["commit"], commit)
            self.assertEqual(records[source_id]["git_ref"]["tree"], tree)
            self.assertEqual(records[source_id]["archive_sha256"], digest)
            self.assertEqual(records[source_id]["archive_bytes"], size)
        self.assertEqual(records["nasm"]["git_ref"]["object"], "19fd1bb434f2fed19b0eb82b1b42c5608b601134")
        self.assertEqual(records["nasm"]["git_ref"]["commit"], "e9fac2faa62647bb50f1a61c26212c63c87090ae")
        self.assertEqual(
            records["llvm-project"]["git_ref"]["object"],
            "e013073558445169e8732e25fa86e9913bfdd24e",
        )
        self.assertEqual(
            self.source_value["link_closure"],
            {
                "evidence": ["lld-map", "lld-reproducer", "lld-verbose"],
                "status": "input-classification-unverified",
            },
        )

    def test_bundle_lock_translation_is_accepted_by_source_bundle_contract(self):
        source = verifier.load_source_lock(SOURCE_LOCK)
        translated = verifier.bundle_lock_value(source)
        normalized = source_bundle.validate_lock(translated)
        self.assertEqual(normalized, translated)
        self.assertEqual(
            [item["id"] for item in translated["sources"]],
            [
                "ffmpeg", "llvm-mingw", "llvm-project", "mingw-w64",
                "nasm", "x264", "zlib",
            ],
        )

    def test_real_source_bundle_round_trip_links_prefixed_manifest_archive(self):
        content = b"immutable source archive\n"
        source_value = {
            "sources": [{
                "archive": "codec-1.0.tar.gz",
                "archive_sha256": hashlib.sha256(content).hexdigest(),
                "build": ["packaging/build_windows_ffmpeg.sh"],
                "fetch": {
                    "url": "https://sources.example.invalid/codec-1.0.tar.gz",
                },
                "id": "codec",
                "license": ["SPDX:MIT"],
                "patches": ["none"],
                "version": "1.0",
            }],
        }
        source_bytes = canonical(source_value)
        loaded = verifier.LoadedContract(
            Path("fixture"), source_bytes, hashlib.sha256(source_bytes).hexdigest()
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Contract Test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repository), "add", "tracked.txt"], check=True
            )
            commit_environment = {
                **os.environ,
                "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
            }
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-q", "-m", "fixture"],
                check=True,
                env=commit_environment,
            )
            commit = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            cache = root / "cache"
            cache.mkdir()
            (cache / "codec-1.0.tar.gz").write_bytes(content)
            lock_path = root / "bundle-lock.json"
            lock_path.write_bytes(canonical(verifier.bundle_lock_value(loaded)))
            bundle = root / "source.tar"
            manifest_path = root / "source.manifest.json"
            source_bundle.build_bundle(
                lock_path=lock_path,
                source_cache=cache,
                repository=repository,
                repository_commit=commit,
                output_tar=bundle,
                output_manifest=manifest_path,
            )
            manifest, receipt = verifier.verify_bundle_linkage(
                loaded, bundle, manifest_path, commit, ROOT
            )
            self.assertEqual(
                manifest["sources"][0]["archive"],
                f"{source_bundle.UPSTREAM_PREFIX}/codec-1.0.tar.gz",
            )
            self.assertEqual(
                receipt["bundle_lock_sha256"],
                hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                verifier.bundle_lock_value(loaded)["sources"][0]["archive"],
                "codec-1.0.tar.gz",
            )

    def test_loaded_contract_returns_fresh_untrusted_copies(self):
        loaded = verifier.load_source_lock(SOURCE_LOCK)
        first = loaded.parsed()
        first["sources"][0]["git_ref"]["tree"] = "f" * 40
        self.assertNotEqual(
            first["sources"][0]["git_ref"]["tree"],
            loaded.parsed()["sources"][0]["git_ref"]["tree"],
        )

    def test_source_lock_rejects_unknown_nested_field(self):
        with tempfile.TemporaryDirectory() as td:
            changed = copy.deepcopy(self.source_value)
            changed["sources"][0]["git_ref"]["branch"] = "main"
            path = self._write(td, "lock.json", changed)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "unknown branch"):
                verifier.load_source_lock(path)

    def test_source_lock_rejects_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as td:
            raw = SOURCE_LOCK.read_text(encoding="utf-8")
            raw = raw.replace(
                '  "license_expression": "GPL-2.0-or-later",',
                '  "license_expression": "GPL-2.0-or-later",\n'
                '  "license_expression": "GPL-2.0-or-later",',
                1,
            )
            path = Path(td) / "lock.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "duplicate JSON key"):
                verifier.load_source_lock(path)

    def test_source_lock_rejects_crlf_and_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            crlf = Path(td) / "crlf.json"
            crlf.write_bytes(SOURCE_LOCK.read_bytes().replace(b"\n", b"\r\n"))
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "LF line endings"):
                verifier.load_source_lock(crlf)
            link = Path(td) / "link.json"
            os.symlink(SOURCE_LOCK, link)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "not a symlink"):
                verifier.load_source_lock(link)

    def test_coherent_source_pin_mutation_still_fails_embedded_digest(self):
        with tempfile.TemporaryDirectory() as td:
            changed = copy.deepcopy(self.source_value)
            changed["sources"][0]["archive_sha256"] = "f" * 64
            path = self._write(td, "lock.json", changed)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "digest drifted"):
                verifier.load_source_lock(path)

    def test_moving_source_url_is_rejected_before_digest_check(self):
        with tempfile.TemporaryDirectory() as td:
            changed = copy.deepcopy(self.source_value)
            changed["sources"][0]["fetch"]["url"] = (
                "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/heads/main"
            )
            path = self._write(td, "lock.json", changed)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "moving reference"):
                verifier.load_source_lock(path)

    def test_source_lock_cannot_claim_verified_link_closure_without_classification(self):
        with tempfile.TemporaryDirectory() as td:
            changed = copy.deepcopy(self.source_value)
            changed["link_closure"]["status"] = "verified"
            path = self._write(td, "verified.json", changed)
            with self.assertRaisesRegex(
                verifier.WindowsFFmpegError,
                "must remain unverified",
            ):
                verifier.load_source_lock(path)

    def test_capability_contract_rejects_unknown_field_and_mutable_image(self):
        with tempfile.TemporaryDirectory() as td:
            changed = copy.deepcopy(self.capability_value)
            changed["build"]["make"]["fallback"] = "latest"
            path = self._write(td, "capabilities.json", changed)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "unknown fallback"):
                verifier.load_capabilities(path)

            changed = copy.deepcopy(self.capability_value)
            changed["build"]["container_image"] = "docker.io/mstorsjo/llvm-mingw:latest"
            path = self._write(td, "mutable.json", changed)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "not digest-pinned"):
                verifier.load_capabilities(path)

    def test_source_cache_rejects_missing_extra_and_changed_files(self):
        content = b"pinned source\n"
        lock_value = {
            "sources": [{
                "archive": "source.tar.gz",
                "archive_bytes": len(content),
                "archive_sha256": hashlib.sha256(content).hexdigest(),
                "id": "source",
            }],
        }
        loaded = verifier.LoadedContract(
            Path("fixture"), canonical(lock_value), hashlib.sha256(canonical(lock_value)).hexdigest()
        )
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "missing or not regular"):
                verifier.verify_source_cache(loaded, cache)
            (cache / "source.tar.gz").write_bytes(content)
            verifier.verify_source_cache(loaded, cache)
            (cache / "extra.tar.gz").write_bytes(b"extra")
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "member set drifted"):
                verifier.verify_source_cache(loaded, cache)
            (cache / "extra.tar.gz").unlink()
            (cache / "source.tar.gz").write_bytes(b"changed")
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "archive drifted"):
                verifier.verify_source_cache(loaded, cache)

    def test_llvm_mingw_wrapper_binds_underlying_toolchain_sources(self):
        wrapper_archive_name = "llvm-mingw-deadbeef.tar.gz"
        source_value = {
            "sources": [
                {
                    "archive": wrapper_archive_name,
                    "id": "llvm-mingw",
                },
                {
                    "id": "llvm-project",
                    "version": "llvmorg-22.1.8",
                },
                {
                    "git_ref": {
                        "commit": "c28e9555bb8800c53449f42a465ad9a5676fce88",
                    },
                    "id": "mingw-w64",
                },
            ],
        }
        loaded = verifier.LoadedContract(
            Path("fixture"),
            canonical(source_value),
            hashlib.sha256(canonical(source_value)).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td)
            scripts = {
                "llvm-mingw-deadbeef/build-llvm.sh": (
                    b": ${LLVM_VERSION:=llvmorg-22.1.8}\n"
                ),
                "llvm-mingw-deadbeef/build-mingw-w64.sh": (
                    b": ${MINGW_W64_VERSION:=c28e9555bb8800c53449f42a465ad9a5676fce88}\n"
                ),
            }
            with tarfile.open(cache / wrapper_archive_name, mode="w:gz") as archive:
                for name, raw in scripts.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            verifier._verify_toolchain_source_pins(loaded, cache)

            scripts["llvm-mingw-deadbeef/build-llvm.sh"] = (
                b": ${LLVM_VERSION:=llvmorg-22.1.7}\n"
            )
            with tarfile.open(cache / wrapper_archive_name, mode="w:gz") as archive:
                for name, raw in scripts.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            with self.assertRaisesRegex(
                verifier.WindowsFFmpegError,
                "does not bind LLVM_VERSION",
            ):
                verifier._verify_toolchain_source_pins(loaded, cache)

    def test_link_evidence_records_every_reproducer_member_and_stays_unverified(self):
        capabilities = verifier.load_capabilities(CAPABILITIES)
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = write_link_evidence(Path(td) / "link-evidence")
            receipt = verifier.link_evidence_receipt(evidence_dir, capabilities)
            self.assertEqual(
                receipt["closure_status"],
                "input-classification-unverified",
            )
            for program in ("ffmpeg", "ffprobe"):
                members = receipt["programs"][program]["reproducer"]["members"]
                self.assertEqual(len(members), 3)
                self.assertEqual(
                    [member["path"] for member in members],
                    sorted(member["path"] for member in members),
                )

    def test_link_evidence_rejects_extra_files_and_recursive_reproducer(self):
        capabilities = verifier.load_capabilities(CAPABILITIES)
        with tempfile.TemporaryDirectory() as td:
            evidence_dir = write_link_evidence(Path(td) / "link-evidence")
            (evidence_dir / "unexpected.txt").write_text("extra\n", encoding="utf-8")
            with self.assertRaisesRegex(
                verifier.WindowsFFmpegError,
                "evidence set drifted",
            ):
                verifier.link_evidence_receipt(evidence_dir, capabilities)
            (evidence_dir / "unexpected.txt").unlink()

            program = "ffmpeg"
            name = verifier.LINK_EVIDENCE_FILES[program]["reproducer"]
            reproducer_root = Path(name).stem
            response = (
                f"-lldmap:{program}-lld.map\n-verbose\n"
                f"-reproduce:{name}\n/out:{program}_g.exe\n"
            ).encode("utf-8")
            with tarfile.open(evidence_dir / name, mode="w") as archive:
                for member_name, raw in {
                    f"{reproducer_root}/input.a": b"archive\n",
                    f"{reproducer_root}/input.o": b"object\n",
                    f"{reproducer_root}/response.txt": response,
                }.items():
                    info = tarfile.TarInfo(member_name)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            with self.assertRaisesRegex(
                verifier.WindowsFFmpegError,
                "recursively records reproduce",
            ):
                verifier.link_evidence_receipt(evidence_dir, capabilities)

    def test_runtime_notice_is_byte_identical_to_nested_source_archive(self):
        notice_raw = b"pinned upstream license text\n"
        archive_member = "codec-deadbeef/COPYING"
        inner_buffer = io.BytesIO()
        with tarfile.open(fileobj=inner_buffer, mode="w:gz") as inner:
            info = tarfile.TarInfo(archive_member)
            info.size = len(notice_raw)
            inner.addfile(info, io.BytesIO(notice_raw))
        archive_raw = inner_buffer.getvalue()
        notice_contract = {
            "archive_member": archive_member,
            "filename": "codec-COPYING",
            "license_expression": "GPL-2.0-or-later",
            "source_id": "codec",
        }
        source_value = {
            "sources": [{
                "archive": "codec-deadbeef.tar.gz",
                "archive_sha256": hashlib.sha256(archive_raw).hexdigest(),
                "id": "codec",
            }],
        }
        capability_value = {"runtime_notices": [notice_contract]}
        source = verifier.LoadedContract(
            Path("source.json"),
            canonical(source_value),
            hashlib.sha256(canonical(source_value)).hexdigest(),
        )
        capabilities = verifier.LoadedContract(
            Path("capabilities.json"),
            canonical(capability_value),
            hashlib.sha256(canonical(capability_value)).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "source.tar"
            with tarfile.open(bundle, mode="w") as outer:
                info = tarfile.TarInfo(
                    "autoeditor-corresponding-source/upstream/codec-deadbeef.tar.gz"
                )
                info.size = len(archive_raw)
                outer.addfile(info, io.BytesIO(archive_raw))
            license_dir = root / "licenses"
            license_dir.mkdir()
            (license_dir / "codec-COPYING").write_bytes(notice_raw)
            self.assertEqual(
                verifier.runtime_notice_receipts(
                    license_dir, bundle, source, capabilities
                ),
                [{
                    **notice_contract,
                    "bytes": len(notice_raw),
                    "sha256": hashlib.sha256(notice_raw).hexdigest(),
                }],
            )
            (license_dir / "codec-COPYING").write_bytes(b"changed\n")
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "differs"):
                verifier.runtime_notice_receipts(
                    license_dir, bundle, source, capabilities
                )

    def test_required_inventory_accepts_exact_minimum_and_rejects_missing_filter(self):
        capabilities = verifier.load_capabilities(CAPABILITIES)
        required = self.capability_value["required"]
        inventory = {
            "decoders": required["decoders"],
            "demuxers": required["demuxers"],
            "encoders": required["encoders"],
            "filters": required["filters"],
            "input_devices": required["input_devices"],
            "muxers": required["muxers"],
            "output_devices": required["output_devices"],
            "protocols": required["protocols"],
        }
        verifier.verify_inventory(
            inventory, self.capability_value["build"]["configure_args"], capabilities
        )
        changed = copy.deepcopy(inventory)
        changed["filters"].remove("zoompan")
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "zoompan"):
            verifier.verify_inventory(
                changed, self.capability_value["build"]["configure_args"], capabilities
            )

    def test_ffmpeg_8_filter_inventory_uses_two_capability_columns(self):
        output = """Filters:
  T.. = Timeline support
  .S. = Slice threading
  A = Audio input/output
  V = Video input/output
  N = Dynamic number and/or type of input/output
  | = Source or sink filter
  ------
 TS aap               AA->A      Apply Affine Projection algorithm.
 .. abench            A->A       Benchmark part of a filtergraph.
"""
        self.assertEqual(
            verifier._named_inventory(output, 2, "filter"),
            ["aap", "abench"],
        )
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "inventory is empty"):
            verifier._named_inventory(output, 3, "filter")

    def test_inventory_rejects_any_protocol_beyond_file_and_pipe(self):
        capabilities = verifier.load_capabilities(CAPABILITIES)
        required = self.capability_value["required"]
        inventory = {
            "decoders": required["decoders"],
            "demuxers": required["demuxers"],
            "encoders": required["encoders"],
            "filters": required["filters"],
            "input_devices": required["input_devices"],
            "muxers": required["muxers"],
            "output_devices": required["output_devices"],
            "protocols": {"input": ["file", "http", "pipe"], "output": ["file", "pipe"]},
        }
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "exactly file and pipe"):
            verifier.verify_inventory(
                inventory, self.capability_value["build"]["configure_args"], capabilities
            )

    def test_inventory_rejects_buildconf_drift(self):
        capabilities = verifier.load_capabilities(CAPABILITIES)
        required = self.capability_value["required"]
        inventory = {
            "decoders": required["decoders"],
            "demuxers": required["demuxers"],
            "encoders": required["encoders"],
            "filters": required["filters"],
            "input_devices": required["input_devices"],
            "muxers": required["muxers"],
            "output_devices": required["output_devices"],
            "protocols": required["protocols"],
        }
        args = list(self.capability_value["build"]["configure_args"])
        args.remove("--disable-network")
        args.append("--enable-network")
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "buildconf differs"):
            verifier.verify_inventory(inventory, args, capabilities)

    def test_buildconf_ignores_ffmpeg_exit_diagnostic_after_arguments(self):
        output = """
configuration:
  --disable-autodetect
  --enable-gpl --enable-libx264

Exiting with exit code 0
"""
        self.assertEqual(
            verifier._buildconf(output),
            ["--disable-autodetect", "--enable-gpl", "--enable-libx264"],
        )
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "invalid arguments"):
            verifier._buildconf("configuration:\nnot-an-argument\n")
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "invalid arguments"):
            verifier._buildconf(
                "configuration:\n--disable-network\nunexpected-tail\n"
            )
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "invalid arguments"):
            verifier._buildconf(
                "configuration:\n--disable-network\n"
                "Exiting with exit code 0\n--enable-network\n"
            )

    def test_pe_inspection_accepts_hardened_static_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ffmpeg.exe"
            path.write_bytes(make_pe())
            result = verifier.inspect_pe(
                path, self.capability_value["forbidden"]["pe_import_patterns"]
            )
            self.assertEqual(result["machine"], "AMD64")
            self.assertEqual(result["imports"], ["kernel32.dll"])
            self.assertEqual(result["coff_timestamp"], 0)
            self.assertEqual(result["certificate_bytes"], 0)
            self.assertRegex(result["authenticode_content_sha256"], r"^[0-9a-f]{64}$")

    def test_pe_inspection_rejects_forbidden_static_dependency_dlls(self):
        patterns = self.capability_value["forbidden"]["pe_import_patterns"]
        for imported in (
            "libx264-165.dll", "zlib1.dll", "libz.dll", "libwinpthread-1.dll",
            "libgcc_s_seh-1.dll", "libstdc++-6.dll", "libc++.dll",
            "clang_rt.dll", "libclang_rt.asan_dynamic-x86_64.dll", "libunwind.dll",
        ):
            with self.subTest(imported=imported), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "ffmpeg.exe"
                path.write_bytes(make_pe(imported))
                with self.assertRaisesRegex(verifier.WindowsFFmpegError, "forbidden runtime DLL"):
                    verifier.inspect_pe(path, patterns)

    def test_pe_inspection_rejects_timestamp_and_missing_hardening(self):
        patterns = self.capability_value["forbidden"]["pe_import_patterns"]
        with tempfile.TemporaryDirectory() as td:
            timestamped = Path(td) / "timestamped.exe"
            timestamped.write_bytes(make_pe(timestamp=1))
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "nonzero COFF timestamp"):
                verifier.inspect_pe(timestamped, patterns)
            weak = Path(td) / "weak.exe"
            weak.write_bytes(make_pe(dll_characteristics=0x0100))
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "lacks high-entropy"):
                verifier.inspect_pe(weak, patterns)

    def test_receipt_shape_rejects_unknown_fields_and_noncanonical_json(self):
        receipt = self._receipt()
        verifier.validate_receipt_shape(receipt)
        changed = copy.deepcopy(receipt)
        changed["outputs"]["ffmpeg"]["pe"]["trusted"] = True
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "unknown trusted"):
            verifier.validate_receipt_shape(changed)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "canonical sorted JSON"):
                verifier.load_receipt(path)

    def test_receipt_and_promotion_gate_fail_closed_on_unverified_link_inputs(self):
        receipt = self._receipt()
        verifier.validate_receipt_shape(receipt)
        changed = copy.deepcopy(receipt)
        changed["link_evidence"]["closure_status"] = "verified"
        with self.assertRaisesRegex(
            verifier.WindowsFFmpegError,
            "may not claim verified closure",
        ):
            verifier.validate_receipt_shape(changed)
        with tempfile.TemporaryDirectory() as td:
            path = self._write(td, "receipt.json", receipt)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "assert-promotable",
                    "--receipt",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("actual LLD link inputs remain unclassified", result.stderr)

    def test_dual_build_comparison_requires_byte_identical_canonical_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            first = self._write(td, "first.json", self._receipt())
            second = self._write(td, "second.json", self._receipt())
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "compare-receipts", "--first", str(first), "--second", str(second)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            changed = self._receipt()
            changed["outputs"]["ffmpeg"]["sha256"] = "f" * 64
            second.write_bytes(canonical(changed))
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "compare-receipts", "--first", str(first), "--second", str(second)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not reproducible", result.stderr)

    def test_cli_contracts_and_configure_argument_stream(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "contracts"],
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        emitted = subprocess.run(
            [sys.executable, str(SCRIPT), "emit-configure-args", "--nul"],
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(
            emitted.split(b"\0")[:-1],
            [item.encode("utf-8") for item in self.capability_value["build"]["configure_args"]],
        )

    def test_configure_help_binding_accepts_documented_inverse_and_rejects_unknown(self):
        capabilities = verifier.load_capabilities(CAPABILITIES)
        options = []
        for argument in self.capability_value["build"]["configure_args"]:
            option = argument.split("=", 1)[0]
            if option == "--enable-static":
                option = "--disable-static"
            options.append(f"  {option}=VALUE  fixture")
        options.append("  --help  fixture")
        bindings = verifier.verify_configure_help("\n".join(options), capabilities)
        self.assertEqual(bindings["--enable-static"], "--disable-static")
        changed = "\n".join(
            line for line in options if "--disable-network" not in line
        )
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "--disable-network"):
            verifier.verify_configure_help(changed, capabilities)

    def test_makefile_binding_requires_windows_executable_targets(self):
        capabilities = verifier.load_capabilities(CAPABILITIES)
        makefile = (
            "$(PROGS): %$(PROGSSUF)$(EXESUF): "
            "%$(PROGSSUF)_g$(EXESUF)\n"
        )
        tools_makefile = "\n".join((
            "AVPROGS-$(CONFIG_FFMPEG)   += ffmpeg",
            "AVPROGS-$(CONFIG_FFPROBE)  += ffprobe",
            "AVPROGS     := $(AVPROGS-yes:%=%$(PROGSSUF)$(EXESUF))",
        ))
        config_mak = "\n".join((
            "CONFIG_FFMPEG=yes",
            "CONFIG_FFPROBE=yes",
            "EXESUF=.exe",
            "PROGSSUF=",
        ))
        verifier.verify_makefile_contract(
            makefile, tools_makefile, config_mak, capabilities
        )
        with self.assertRaisesRegex(verifier.WindowsFFmpegError, "ffmpeg.exe"):
            verifier.verify_makefile_contract(
                makefile,
                tools_makefile,
                config_mak.replace("EXESUF=.exe", "EXESUF="),
                capabilities,
            )

    def test_runtime_smoke_executes_all_required_paths(self):
        ffmpeg_script = """#!/usr/bin/env python3
import pathlib
import sys

arguments = sys.argv[1:]
if "pcm_f32le" in arguments:
    pathlib.Path(arguments[-1]).write_bytes(b"\\0" * 8000)
elif "libx264" in arguments:
    pathlib.Path(arguments[-1]).write_bytes(b"fixture mp4")
sys.exit(0)
"""
        ffprobe_script = """#!/usr/bin/env python3
import json

print(json.dumps({"streams": [
    {"codec_name": "h264", "codec_type": "video"},
    {"codec_name": "aac", "codec_type": "audio"},
]}))
"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ffmpeg = root / "ffmpeg.exe"
            ffprobe = root / "ffprobe.exe"
            ffmpeg.write_text(ffmpeg_script, encoding="utf-8")
            ffprobe.write_text(ffprobe_script, encoding="utf-8")
            ffmpeg.chmod(0o755)
            ffprobe.chmod(0o755)
            self.assertEqual(
                verifier.run_runtime_smoke(ffmpeg, ffprobe),
                {"checks": verifier.RUNTIME_SMOKE_CHECKS, "status": "passed"},
            )
            ffprobe.write_text("#!/usr/bin/env python3\nprint('{\"streams\": []}')\n", encoding="utf-8")
            ffprobe.chmod(0o755)
            with self.assertRaisesRegex(verifier.WindowsFFmpegError, "lacks H.264"):
                verifier.run_runtime_smoke(ffmpeg, ffprobe)

    def test_build_script_has_offline_container_and_immutable_source_contract(self):
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("docker run --rm --network=none", text)
        self.assertNotIn("git-archive", text)
        self.assertNotIn("code.videolan.org", text)
        self.assertIn("verify-source-cache", text)
        self.assertIn("verify-configure-help", text)
        self.assertIn("verify-makefile", text)
        self.assertIn("verify-link-evidence", text)
        self.assertIn("export NASMENV=--reproducible", text)
        self.assertEqual(
            self.capability_value["build"]["environment"]["NASMENV"],
            "--reproducible",
        )
        self.assertIn("make -j2 ffmpeg.exe ffprobe.exe", text)
        self.assertIn("--Map=/artifact/link-evidence/", text)
        self.assertIn("--verbose", text)
        self.assertIn("--reproduce=/artifact/link-evidence/", text)
        self.assertIn("--threads=1", text)
        for archive in (
            "llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1.tar.gz",
            "mingw-w64-c28e9555bb8800c53449f42a465ad9a5676fce88.tar.gz",
        ):
            self.assertIn(archive, text)
        for filename in (
            "FFmpeg-COPYING.GPLv2",
            "LLVM-LICENSE.TXT",
            "LLVM-compiler-rt-LICENSE.TXT",
            "MinGW-w64-runtime-NOTICES.txt",
            "x264-COPYING",
            "zlib-LICENSE",
        ):
            self.assertIn(f"/artifact/licenses/{filename}", text)
        self.assertIn('--user "$(id -u):$(id -g)"', text)
        self.assertIn('--volume "$nasm_prefix:/opt/nasm-3.01"', text)
        self.assertNotIn("HOST_UID", text)
        self.assertNotIn("HOST_GID", text)
        self.assertNotIn("chown ", text)
        self.assertIn("source_bundle.py\" build", text)
        self.assertNotIn("make -j2 ffmpeg ffprobe", text)
        self.assertNotIn("llvm-mingw:latest", text)
        self.assertNotIn("BtbN", text)

        workflow = (
            ROOT / ".github" / "workflows" / "windows-ffmpeg.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("windows-ffmpeg-evidence-${{ github.sha }}", workflow)
        self.assertNotIn("windows-ffmpeg-accepted-", workflow)
        self.assertIn("compare-receipts", workflow)
        self.assertEqual(workflow.count("--license-dir"), 2)
        self.assertEqual(workflow.count("--link-evidence-dir"), 2)
        self.assertEqual(workflow.count("overwrite: true"), 3)
        self.assertIn("workflow_call:", workflow)
        self.assertNotIn("push:\n    branches:", workflow)
        self.assertIn("artifact_id: ${{ steps.evidence.outputs.artifact-id }}", workflow)
        self.assertIn(
            "artifact_digest: ${{ steps.evidence.outputs.artifact-digest }}",
            workflow,
        )
        self.assertIn("id: evidence", workflow)
        self.assertLess(
            workflow.index("compare-receipts"),
            workflow.index("Upload reproducible unverified evidence candidate"),
        )


if __name__ == "__main__":
    unittest.main()
