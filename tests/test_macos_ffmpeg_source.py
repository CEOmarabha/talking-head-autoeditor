import copy
import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "packaging" / "macos-ffmpeg-sources.lock.json"
SCRIPT = ROOT / "packaging" / "verify_macos_ffmpeg_source.py"
SPEC = importlib.util.spec_from_file_location("macos_ffmpeg_source_tested", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
source = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = source
SPEC.loader.exec_module(source)


def canonical(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


class MacOSFFmpegSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = source.load_lock(LOCK)
        cls.formulae = {item["name"]: item for item in cls.lock["formulae"]}

    def test_lock_is_canonical_and_digest_pinned(self):
        raw = LOCK.read_bytes()
        self.assertEqual(raw, canonical(self.lock))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), source.EXPECTED_LOCK_SHA256)

    def test_contracts_cross_bind_both_audited_inventories(self):
        value = source.verify_contracts(LOCK, ROOT)
        self.assertEqual(tuple(item["name"] for item in value["formulae"]), source.EXPECTED_FORMULAE)

    def test_historical_source_and_bottle_commits_are_exact(self):
        expected = {
            "dav1d": ("632a0b93c14d30a94ff823c88540e49a907528c3", "e82156599049e9669d722858ee759f0c3b73ebaf"),
            "ffmpeg": ("c8d371d10663c637fe24eafcdf6bcd5cd0bec4ea", "c7348004c5876a7cddfa236babd4bf3489f21d87"),
            "libvpx": ("bda13e1bfa1c0085b3a22f2d77f3201a4b760353", "30e8b07eb9becf25653cf858b95b81a8fa1820fc"),
            "mpg123": ("63a0c10d3a5f115bc28bb858cce57ef4b1eebf20", "b854b7b20bd2a4fced247b67cf803be58aacf71c"),
            "openssl@3": ("84e4e32eecfd4abb49960ea23ddf90a64d94bc62", "afd93f1b5d40319fef3976408e83f0b232de81ac"),
            "x264": ("458c54b935eb507cc582a3b7c0c766df349e1d6e", "9ecddc07a2c404f80ded336430c69b3679136505"),
        }
        for name, (source_commit, bottle_commit) in expected.items():
            self.assertEqual(self.formulae[name]["source_version_commit"], source_commit)
            self.assertEqual(self.formulae[name]["formula"]["bottle_commit"], bottle_commit)

    def test_mpg123_is_1336_not_current_1337(self):
        record = self.formulae["mpg123"]
        self.assertEqual(record["package_version"], "1.33.6")
        self.assertEqual(record["source"]["bytes"], 1123797)
        self.assertEqual(
            record["source"]["sha256"],
            "929a7c18ba662b8927aed4de229ad9ae8ab2b4806dd0f30b90113eb1b4e2195a",
        )
        self.assertNotIn("1.33.7", record["source"]["source_url"])

    def test_x264_source_names_exact_r3222_commit(self):
        record = self.formulae["x264"]
        commit = "b35605ace3ddf7c1a5d67a2eb553f034aef41d55"
        self.assertIn(commit, record["source"]["archive"])
        self.assertIn(commit, record["source"]["source_url"])
        self.assertEqual(record["source"]["bytes"], 848719)
        self.assertEqual(record["source"]["sha256"], "6eeb82934e69fd51e043bd8c5b0d152839638d1ce7aa4eea65a3fedcf83ff224")

    def test_openssl_formula_binds_all_exact_backport_patches(self):
        record = self.formulae["openssl@3"]
        self.assertEqual(tuple(item["commit"] for item in record["patches"]), source.EXPECTED_OPENSSL_PATCHES)
        self.assertEqual(sum(item["bytes"] for item in record["patches"]), 15014)

    def test_bundle_locks_are_generic_source_bundle_compatible(self):
        module = source._load_source_bundle_module(ROOT)
        for arch in ("arm64", "x64"):
            derived = source.bundle_lock_value(self.lock, arch)
            self.assertEqual(module.validate_lock(derived), derived)
            self.assertEqual(len(derived["sources"]), 26)

    def test_arch_bundle_locks_differ_only_in_build_inventory_binding(self):
        arm = source.bundle_lock_value(self.lock, "arm64")
        x64 = source.bundle_lock_value(self.lock, "x64")
        self.assertNotEqual(canonical(arm), canonical(x64))
        self.assertEqual(len(arm["sources"]), len(x64["sources"]))
        for arm_item, x64_item in zip(arm["sources"], x64["sources"]):
            self.assertEqual(arm_item["id"], x64_item["id"])
            left = {key: value for key, value in arm_item.items() if key != "build"}
            right = {key: value for key, value in x64_item.items() if key != "build"}
            self.assertEqual(left, right)
            self.assertEqual(arm_item["build"][0], "packaging/macos-ffmpeg-formulae-arm64.txt")
            self.assertEqual(x64_item["build"][0], "packaging/macos-ffmpeg-formulae-x64.txt")

    def test_all_cache_urls_are_https_and_revision_pinned(self):
        for item in source.cache_items(self.lock):
            self.assertTrue(item.source_url.startswith("https://"))
            self.assertNotRegex(item.source_url.lower(), r"(?:^|[/._-])(latest|nightly|master|main)(?:$|[/._-])")
        self.assertEqual(len({item.archive for item in source.cache_items(self.lock)}), 26)

    def _minimal_formula(self, name="mpg123"):
        record = copy.deepcopy(self.formulae[name])
        arm = record["bottles"]["arm64"]
        x64 = record["bottles"]["x64"]
        lines = [
            "class Fixture < Formula\n",
            f'  url "{record["source"]["source_url"]}"\n',
            f'  sha256 "{record["source"]["sha256"]}"\n',
            f'  license "{record["license"]}"\n',
        ]
        if record["package_version"] != record["source"]["version"]:
            lines.append(f'  version "{record["package_version"]}"\n')
        lines.extend([
            "\n",
            "  bottle do\n",
        ])
        if arm["bottle_rebuild"]:
            lines.append(f'    rebuild {arm["bottle_rebuild"]}\n')
        lines.extend([
            f'    sha256 {arm["bottle_tag"]}: "{arm["bottle_sha256"]}"\n',
            f'    sha256 {x64["bottle_tag"]}: "{x64["bottle_sha256"]}"\n',
            "  end\n",
            "\n",
        ])
        for patch in record["patches"]:
            lines.extend([
                "  patch do\n",
                f'    url "{patch["source_url"]}"\n',
                f'    sha256 "{patch["sha256"]}"\n',
                "  end\n",
            ])
        lines.append("end\n")
        return record, "".join(lines).encode()

    def test_formula_parser_accepts_exact_source_bottles_and_license(self):
        record, raw = self._minimal_formula()
        stripped, stable = source._parse_formula_bytes(raw, record)
        self.assertEqual(stable, "1.33.6")
        self.assertNotIn(b"bottle do", stripped)

    def test_formula_parser_rejects_a_changed_source_hash(self):
        record, raw = self._minimal_formula()
        raw = raw.replace(record["source"]["sha256"].encode(), b"0" * 64, 1)
        with self.assertRaisesRegex(source.MacSourceError, "upstream SHA-256"):
            source._parse_formula_bytes(raw, record)

    def test_formula_parser_rejects_a_changed_bottle_hash(self):
        record, raw = self._minimal_formula()
        digest = record["bottles"]["arm64"]["bottle_sha256"].encode()
        raw = raw.replace(digest, b"0" * 64, 1)
        with self.assertRaisesRegex(source.MacSourceError, "bottle hash"):
            source._parse_formula_bytes(raw, record)

    def test_formula_parser_rejects_duplicate_or_noncanonical_bottle_blocks(self):
        record, raw = self._minimal_formula()
        duplicate = raw + b"  bottle do\n  end\n"
        with self.assertRaisesRegex(source.MacSourceError, "exactly one"):
            source._parse_formula_bytes(duplicate, record)
        with self.assertRaisesRegex(source.MacSourceError, "exactly one"):
            source._parse_formula_bytes(raw.replace(b"\n", b"\r\n"), record)

    def test_validator_rejects_mpg123_1337_even_with_well_formed_fields(self):
        changed = copy.deepcopy(self.lock)
        record = changed["formulae"][5]
        record["package_version"] = "1.33.7"
        record["source"]["version"] = "1.33.7"
        record["source"]["source_url"] = "https://www.mpg123.de/download/mpg123-1.33.7.tar.bz2"
        with self.assertRaisesRegex(source.MacSourceError, "mpg123 must remain"):
            source._validate_lock_value(changed)

    def test_validator_rejects_later_libvpx_formula_that_retains_bottle_hashes(self):
        changed = copy.deepcopy(self.lock)
        record = changed["formulae"][4]
        later = "cc4849f3c6a6253c855ffdaf082e7cb0b0771550"
        record["formula"]["bottle_commit"] = later
        record["formula"]["source_url"] = f"https://raw.githubusercontent.com/Homebrew/homebrew-core/{later}/Formula/lib/libvpx.rb"
        with self.assertRaisesRegex(source.MacSourceError, "Yasm bottle-producing"):
            source._validate_lock_value(changed)

    def test_inventory_drift_is_rejected_even_if_the_line_is_well_formed(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            (repo / "packaging").mkdir()
            for arch in ("arm64", "x64"):
                original = ROOT / self.lock["inventories"][arch]["path"]
                target = repo / self.lock["inventories"][arch]["path"]
                target.write_bytes(original.read_bytes())
            target = repo / self.lock["inventories"]["arm64"]["path"]
            target.write_text(target.read_text().replace("mpg123 1.33.6", "mpg123 1.33.7"))
            with self.assertRaisesRegex(source.MacSourceError, "digest or size drifted"):
                source.verify_inventories(self.lock, repo)

    def test_regular_file_reader_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            real = root / "real"
            real.write_bytes(b"data")
            linked = root / "linked"
            linked.symlink_to(real)
            with self.assertRaisesRegex(source.MacSourceError, "not a symlink"):
                source._read_regular(linked, "fixture")

    def test_embedded_formula_requires_one_exact_member(self):
        record, raw = self._minimal_formula("mpg123")
        stripped, _ = source._parse_formula_bytes(raw, record)
        member = f"{record['name']}/{record['package_version']}/.brew/{record['name']}.rb"
        with tempfile.TemporaryDirectory() as root:
            bottle = Path(root) / "fixture.tar.gz"
            with tarfile.open(bottle, "w:gz") as archive:
                info = tarfile.TarInfo(member)
                info.size = len(stripped)
                archive.addfile(info, io.BytesIO(stripped))
            self.assertEqual(source._embedded_formula(bottle, record), stripped)
            with tarfile.open(bottle, "w:gz") as archive:
                for _ in range(2):
                    info = tarfile.TarInfo(member)
                    info.size = len(stripped)
                    archive.addfile(info, io.BytesIO(stripped))
            with self.assertRaisesRegex(source.MacSourceError, "lacks one exact"):
                source._embedded_formula(bottle, record)

    def _valid_receipt(self, stable_version="r3222"):
        return {
            "arch": "arm64",
            "built_as_bottle": True,
            "built_on": {
                "clt": "26.0",
                "cpu_family": "dunno",
                "os": "Macintosh",
                "os_version": "macOS 15",
                "preferred_perl": "5.34",
                "xcode": "26.0",
            },
            "compiler": "clang",
            "poured_from_bottle": True,
            "runtime_dependencies": [],
            "source": {
                "spec": "stable",
                "tap": "homebrew/core",
                "versions": {"stable": stable_version},
            },
            "unused_options": [],
            "used_options": [],
        }

    def test_install_receipt_rejects_unclassified_runtime_dependency(self):
        record = self.formulae["x264"]
        receipt = self._valid_receipt()
        receipt["runtime_dependencies"] = [{
            "bottle_rebuild": 0,
            "declared_directly": True,
            "full_name": "attacker-codec",
            "pkg_version": "1.0",
            "revision": 0,
            "version": "1.0",
        }]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "INSTALL_RECEIPT.json"
            path.write_bytes(canonical(receipt))
            with self.assertRaisesRegex(source.MacSourceError, "unclassified runtime dependency"):
                source._verify_install_receipt(path, record, "arm64", self.lock, "r3222")

    def test_install_receipt_accepts_strict_build_metadata(self):
        record = self.formulae["x264"]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "INSTALL_RECEIPT.json"
            path.write_bytes(canonical(self._valid_receipt()))
            value, raw = source._verify_install_receipt(path, record, "arm64", self.lock, "r3222")
            self.assertEqual(value["built_on"]["os"], "Macintosh")
            self.assertEqual(raw, path.read_bytes())

    def test_write_new_refuses_to_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "receipt.json"
            source._write_new(path, b"first", "fixture")
            with self.assertRaisesRegex(source.MacSourceError, "refusing to overwrite"):
                source._write_new(path, b"second", "fixture")
            self.assertEqual(path.read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
