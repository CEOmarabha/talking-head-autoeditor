from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "verify_windows_ffmpeg.py"
SOURCE_LOCK = ROOT / "packaging" / "windows-ffmpeg-sources.lock.json"
CAPABILITIES = ROOT / "packaging" / "windows-ffmpeg-capabilities.json"
BUILD_SCRIPT = ROOT / "packaging" / "build_windows_ffmpeg.sh"
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
        return {
            "build": {
                "capabilities_sha256": verifier.EXPECTED_CAPABILITIES_SHA256,
                "configure_args": self.capability_value["build"]["configure_args"],
                "container_image": self.capability_value["build"]["container_image"],
                "environment": self.capability_value["build"]["environment"],
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
            "outputs": {"ffmpeg": output, "ffprobe": ffprobe},
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

    def test_source_pins_match_the_audited_commits_trees_and_archives(self):
        records = {item["id"]: item for item in self.source_value["sources"]}
        expected = {
            "ffmpeg": (
                "9b6c8969e05b4f0b29f0f85cd501be6b3e582e6b",
                "d3beee09bdb9ccb2ab7f71a1e72210be2a93e5f6",
                "7e779215eae16ad7e93ddad59bd82822bd3d34e4dc61f9996f9481b2c0605bc3",
                16903934,
            ),
            "x264": (
                "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee",
                "0b8e15dd14ad8d2fb8905df7785003b475236315",
                "30c018b5aff7cd05135b40d7130a8434cfeb958115427d068333f25564dfb875",
                1022933,
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

    def test_bundle_lock_translation_is_accepted_by_source_bundle_contract(self):
        source = verifier.load_source_lock(SOURCE_LOCK)
        translated = verifier.bundle_lock_value(source)
        normalized = source_bundle.validate_lock(translated)
        self.assertEqual(normalized, translated)
        self.assertEqual(
            [item["id"] for item in translated["sources"]],
            ["ffmpeg", "llvm-mingw", "nasm", "x264", "zlib"],
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

    def test_build_script_has_offline_container_and_exact_git_archive_contract(self):
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("docker run --rm --network=none", text)
        self.assertIn("gzip -n -9", text)
        self.assertIn('origin "$object_id" </dev/null', text)
        self.assertIn('rev-parse "FETCH_HEAD^{tree}"', text)
        self.assertIn("verify-source-cache", text)
        self.assertIn("verify-configure-help", text)
        self.assertIn("verify-makefile", text)
        self.assertIn("make -j2 ffmpeg.exe ffprobe.exe", text)
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
        self.assertIn("windows-ffmpeg-accepted-${{ github.sha }}", workflow)
        self.assertIn("compare-receipts", workflow)
        self.assertLess(
            workflow.index("compare-receipts"),
            workflow.index("Upload accepted source-built runtime"),
        )


if __name__ == "__main__":
    unittest.main()
