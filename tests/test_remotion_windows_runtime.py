import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "packaging"
    / "prune_remotion_windows_runtime.py"
)
SPEC = importlib.util.spec_from_file_location(
    "autoeditor_remotion_windows_runtime_pruner", SCRIPT_PATH
)
PRUNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PRUNER
SPEC.loader.exec_module(PRUNER)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def minimal_pe(imports, delay_imports=()):
    """Build a compact independent PE32+ import-table fixture."""
    section_rva = 0x1000
    section_raw = 0x200
    section = bytearray()
    directories = {}

    def add_descriptors(names, descriptor_size, delay):
        if not names:
            return (0, 0)
        table_at = len(section)
        section.extend(b"\0" * ((len(names) + 1) * descriptor_size))
        for index, name in enumerate(names):
            name_at = len(section)
            section.extend(name.encode("ascii") + b"\0")
            name_rva = section_rva + name_at
            descriptor_at = table_at + index * descriptor_size
            if delay:
                struct.pack_into(
                    "<IIIIIIII",
                    section,
                    descriptor_at,
                    1,
                    name_rva,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                )
            else:
                struct.pack_into(
                    "<IIIII", section, descriptor_at, 0, 0, 0, name_rva, 0
                )
        return (section_rva + table_at, (len(names) + 1) * descriptor_size)

    directories[1] = add_descriptors(tuple(imports), 20, False)
    directories[13] = add_descriptors(tuple(delay_imports), 32, True)
    raw_size = (len(section) + 0x1FF) & ~0x1FF
    section.extend(b"\0" * (raw_size - len(section)))

    dos = bytearray(0x80)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20B)
    struct.pack_into("<Q", optional, 24, 0x140000000)
    struct.pack_into("<I", optional, 32, 0x1000)
    struct.pack_into("<I", optional, 36, 0x200)
    struct.pack_into("<I", optional, 56, 0x2000)
    struct.pack_into("<I", optional, 60, 0x200)
    struct.pack_into("<I", optional, 108, 16)
    for index, (rva, size) in directories.items():
        struct.pack_into("<II", optional, 112 + index * 8, rva, size)
    section_header = bytearray(40)
    section_header[:8] = b".rdata\0\0"
    struct.pack_into(
        "<IIIIIIHHI",
        section_header,
        8,
        len(section),
        section_rva,
        raw_size,
        section_raw,
        0,
        0,
        0,
        0,
        0x40000040,
    )
    headers = dos + b"PE\0\0" + coff + optional + section_header
    headers += b"\0" * (section_raw - len(headers))
    return bytes(headers + section)


class Fixture:
    def __init__(self, base):
        self.stage = Path(base) / "stage"
        self.root = self.stage / PRUNER.PACKAGE_RELATIVE_ROOT
        self.licenses = self.stage / "licenses"
        self.root.mkdir(parents=True)
        self.licenses.mkdir()
        self.lock = Path(base) / "package-lock.json"
        self.receipt = self.licenses / "REMOTION_WINDOWS_RUNTIME_PRUNE.json"

        self.imports = {
            "remotion.exe": frozenset({"kernel32.dll", "avcodec-61.dll"}),
            "ffmpeg.exe": frozenset({"kernel32.dll", "avformat-61.dll"}),
            "ffprobe.exe": frozenset({"kernel32.dll", "swscale-8.dll"}),
        }
        package_json = copy.deepcopy(PRUNER.EXPECTED_PACKAGE_JSON)
        (self.root / "package.json").write_text(
            json.dumps(package_json), encoding="utf-8"
        )
        (self.root / "README.md").write_bytes(b"fixture readme\n")
        for executable, imports in self.imports.items():
            (self.root / executable).write_bytes(minimal_pe(sorted(imports)))
        for name in (
            "avcodec-61.dll",
            "avdevice-61.dll",
            "avfilter-10.dll",
            "avformat-61.dll",
            "avutil-59.dll",
            "swresample-5.dll",
            "swscale-8.dll",
        ):
            (self.root / name).write_bytes(("active:" + name).encode("ascii"))
        for name in PRUNER.STALE_FILES:
            (self.root / name).write_bytes(("stale:" + name).encode("ascii"))

        inventory = {
            path.relative_to(self.root).as_posix(): sha256(path)
            for path in self.root.iterdir()
        }
        stale = {name: inventory[name] for name in PRUNER.STALE_FILES}
        self.policy = PRUNER.Policy(
            package_name=PRUNER.PACKAGE_NAME,
            package_version=PRUNER.PACKAGE_VERSION,
            package_relative_root=PRUNER.PACKAGE_RELATIVE_ROOT,
            lock_package_key=PRUNER.LOCK_PACKAGE_KEY,
            resolved=PRUNER.PACKAGE_RESOLVED,
            integrity=PRUNER.PACKAGE_INTEGRITY,
            tarball_sha256=PRUNER.PACKAGE_TARBALL_SHA256,
            lock_entry=copy.deepcopy(PRUNER.EXPECTED_LOCK_ENTRY),
            package_json=package_json,
            inventory=inventory,
            stale_files=stale,
            expected_imports=self.imports,
        )
        self.write_lock(copy.deepcopy(PRUNER.EXPECTED_LOCK_ENTRY))

    def write_lock(self, entry):
        self.lock.write_text(
            json.dumps({"packages": {PRUNER.LOCK_PACKAGE_KEY: entry}}),
            encoding="utf-8",
        )

    def run(self, policy=None, require=True):
        return PRUNER.run_gate(
            self.stage,
            self.lock,
            self.receipt,
            require,
            policy or self.policy,
        )

    def stale_paths(self):
        return [self.root / name for name in self.policy.stale_files]


class RemotionWindowsRuntimeGateTests(unittest.TestCase):
    def test_exact_payload_prunes_only_seven_stale_dlls(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            retained = {
                name: sha256(fixture.root / name)
                for name in (
                    "avcodec-61.dll",
                    "avdevice-61.dll",
                    "avfilter-10.dll",
                    "avformat-61.dll",
                    "avutil-59.dll",
                    "swresample-5.dll",
                    "swscale-8.dll",
                    "remotion.exe",
                    "ffmpeg.exe",
                    "ffprobe.exe",
                )
            }

            receipt = fixture.run()

            self.assertEqual(receipt["status"], "pruned")
            self.assertEqual(len(receipt["removed"]), 7)
            self.assertTrue(all(not path.exists() for path in fixture.stale_paths()))
            self.assertEqual(
                retained,
                {name: sha256(fixture.root / name) for name in retained},
            )
            self.assertEqual(json.loads(fixture.receipt.read_text()), receipt)

    def test_stale_hash_drift_fails_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            (fixture.root / "avcodec-60.dll").write_bytes(b"tampered")

            with self.assertRaisesRegex(PRUNER.GateError, "inventory drift"):
                fixture.run()

            self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_active_hash_drift_fails_and_keeps_all_stale_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            (fixture.root / "avcodec-61.dll").write_bytes(b"tampered active")

            with self.assertRaisesRegex(PRUNER.GateError, "inventory drift"):
                fixture.run()

            self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_extra_or_missing_package_member_fails_closed(self):
        for mutation in ("extra", "missing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(temporary)
                if mutation == "extra":
                    (fixture.root / "surprise.dll").write_bytes(b"unexpected")
                else:
                    (fixture.root / "README.md").unlink()

                with self.assertRaisesRegex(PRUNER.GateError, "inventory drift"):
                    fixture.run()

                self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_wrong_lock_integrity_fails_before_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            entry = copy.deepcopy(PRUNER.EXPECTED_LOCK_ENTRY)
            entry["integrity"] = "sha512-attacker-selected"
            fixture.write_lock(entry)

            with self.assertRaisesRegex(PRUNER.GateError, "npm lock entry drift"):
                fixture.run()

            self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_wrong_package_version_fails_even_with_matching_fixture_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            metadata = copy.deepcopy(PRUNER.EXPECTED_PACKAGE_JSON)
            metadata["version"] = "4.0.508"
            (fixture.root / "package.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            inventory = dict(fixture.policy.inventory)
            inventory["package.json"] = sha256(fixture.root / "package.json")
            policy = replace(fixture.policy, inventory=inventory)

            with self.assertRaisesRegex(PRUNER.GateError, "package metadata drift"):
                fixture.run(policy)

            self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_truncated_pe_cannot_pass_on_a_matching_fixture_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            executable = fixture.root / "remotion.exe"
            executable.write_bytes(b"MZ\0\0\0\0\0\0")
            inventory = dict(fixture.policy.inventory)
            inventory["remotion.exe"] = sha256(executable)
            policy = replace(fixture.policy, inventory=inventory)

            with self.assertRaisesRegex(PRUNER.GateError, "not a complete DOS/PE"):
                fixture.run(policy)

            self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_delay_import_of_stale_dll_blocks_all_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            executable = fixture.root / "remotion.exe"
            normal = {"kernel32.dll", "avcodec-61.dll"}
            stale = "avcodec-60.dll"
            executable.write_bytes(minimal_pe(sorted(normal), (stale,)))
            inventory = dict(fixture.policy.inventory)
            inventory["remotion.exe"] = sha256(executable)
            imports = dict(fixture.policy.expected_imports)
            imports["remotion.exe"] = frozenset(normal | {stale})
            policy = replace(
                fixture.policy, inventory=inventory, expected_imports=imports
            )

            with self.assertRaisesRegex(PRUNER.GateError, "imports stale FFmpeg"):
                fixture.run(policy)

            self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_hardlinked_package_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            outside = Path(temporary) / "outside-readme"
            outside.write_bytes((fixture.root / "README.md").read_bytes())
            (fixture.root / "README.md").unlink()
            try:
                os.link(outside, fixture.root / "README.md")
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")

            with self.assertRaisesRegex(PRUNER.GateError, "hard links"):
                fixture.run()

            self.assertTrue(all(path.exists() for path in fixture.stale_paths()))

    def test_symlinked_package_ancestor_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(temporary)
            creative = fixture.stage / "creative-runtime"
            real_creative = fixture.stage / "real-creative-runtime"
            creative.rename(real_creative)
            try:
                creative.symlink_to(real_creative, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            with self.assertRaisesRegex(PRUNER.GateError, "contains a link"):
                fixture.run()

            real_root = (
                real_creative
                / "node_modules"
                / "@remotion"
                / "compositor-win32-x64-msvc"
            )
            self.assertTrue(
                all((real_root / name).exists() for name in fixture.policy.stale_files)
            )

    def test_absent_package_is_recorded_but_stray_stale_name_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary) / "stage"
            licenses = stage / "licenses"
            licenses.mkdir(parents=True)
            receipt = licenses / "receipt.json"
            payload = PRUNER.run_gate(
                stage,
                Path(temporary) / "unused-lock.json",
                receipt,
                False,
            )
            self.assertEqual(payload["status"], "package-not-present")

            stray = stage / "other" / "avcodec-60.dll"
            stray.parent.mkdir()
            stray.write_bytes(b"stale")
            with self.assertRaisesRegex(PRUNER.GateError, "outside the canonical"):
                PRUNER.run_gate(
                    stage,
                    Path(temporary) / "unused-lock.json",
                    receipt,
                    False,
                )

    def test_required_package_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary) / "stage"
            licenses = stage / "licenses"
            licenses.mkdir(parents=True)
            with self.assertRaisesRegex(PRUNER.GateError, "is missing"):
                PRUNER.run_gate(
                    stage,
                    Path(temporary) / "unused-lock.json",
                    licenses / "receipt.json",
                    True,
                )

    def test_cli_has_no_caller_selected_digest_or_policy_override(self):
        parser = PRUNER.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--stage-root",
                    "stage",
                    "--package-lock",
                    "package-lock.json",
                    "--receipt",
                    "receipt.json",
                    "--expected-digest",
                    "0" * 64,
                ]
            )
        option_strings = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertNotIn("--policy", option_strings)
        self.assertNotIn("--expected-digest", option_strings)

    def test_embedded_production_policy_matches_repository_lock(self):
        lock_path = (
            Path(__file__).resolve().parents[1]
            / "packaging"
            / "helper-runtime"
            / "package-lock.json"
        )
        PRUNER._verify_lock(lock_path, PRUNER.PRODUCTION_POLICY)
        self.assertEqual(len(PRUNER.EXPECTED_INVENTORY), 29)
        self.assertEqual(len(PRUNER.STALE_FILES), 7)
        self.assertEqual(
            PRUNER.PACKAGE_TARBALL_SHA256,
            "f0e006a1b84d7ac3caf6970ea6cfa4c0419371db230a2bd593996e86db197749",
        )


if __name__ == "__main__":
    unittest.main()
