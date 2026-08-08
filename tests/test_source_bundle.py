from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "autoeditor_source_bundle",
    ROOT / "packaging" / "source_bundle.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load source_bundle.py")
source_bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source_bundle
SPEC.loader.exec_module(source_bundle)


class SourceBundleContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cache = self.root / "source-cache"
        self.cache.mkdir()
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        (self.repository / "LICENSE.txt").write_text("fixture license\n", encoding="utf-8")
        (self.repository / "src").mkdir()
        (self.repository / "src.file").write_text(
            "git tree directory ordering fixture\n", encoding="utf-8"
        )
        executable = self.repository / "src" / "build.sh"
        executable.write_text("#!/bin/sh\nprintf 'fixture\\n'\n", encoding="utf-8")
        executable.chmod(0o755)
        os.symlink("../LICENSE.txt", self.repository / "src" / "license-link")
        self._git("add", "--all")
        self._git(
            "-c", "user.name=Source Fixture",
            "-c", "user.email=source-fixture@example.invalid",
            "commit", "--quiet", "-m", "fixture",
            env={
                "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
            },
        )
        self.commit = self._git("rev-parse", "HEAD").stdout.strip()
        self.archive_name = "codec-1.2.3.tar.xz"
        self.archive_bytes = b"exact upstream source archive\n"
        (self.cache / self.archive_name).write_bytes(self.archive_bytes)
        self.lock = {
            "schema": source_bundle.LOCK_SCHEMA,
            "provenance_status": "complete",
            "sources": [{
                "id": "fixture-codec",
                "version": "1.2.3",
                "archive": self.archive_name,
                "source_url": "https://sources.example.invalid/codec-1.2.3.tar.xz",
                "sha256": hashlib.sha256(self.archive_bytes).hexdigest(),
                "license": ["SPDX:MIT", "LICENSE"],
                "build": ["BUILDING.md#release"],
                "patches": ["none"],
            }],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _git(self, *arguments, env=None):
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            env=command_env,
        )

    def _write_lock(self, value=None, *, name="sources.lock.json"):
        path = self.root / name
        path.write_text(
            json.dumps(self.lock if value is None else value, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _build(self, suffix="one", lock_path=None):
        output_tar = self.root / f"bundle-{suffix}.tar"
        output_manifest = self.root / f"bundle-{suffix}.manifest.json"
        source_bundle.build_bundle(
            lock_path=lock_path or self._write_lock(name=f"sources-{suffix}.lock.json"),
            source_cache=self.cache,
            repository=self.repository,
            repository_commit=self.commit,
            output_tar=output_tar,
            output_manifest=output_manifest,
        )
        return output_tar, output_manifest

    def _rewrite_bundle(self, output_tar, output_manifest, manifest, replacements):
        manifest_bytes = source_bundle._canonical_json(manifest)
        entries = []
        with tarfile.open(output_tar, "r:") as archive:
            for member in archive.getmembers():
                if member.name == source_bundle.MANIFEST_MEMBER:
                    continue
                if member.issym():
                    target = member.linkname
                    target_bytes = target.encode("utf-8")
                    entries.append(source_bundle.BundleEntry(
                        path=member.name,
                        entry_type="symlink",
                        mode=member.mode,
                        size=len(target_bytes),
                        sha256=hashlib.sha256(target_bytes).hexdigest(),
                        link_target=target,
                    ))
                    continue
                handle = archive.extractfile(member)
                self.assertIsNotNone(handle)
                data = replacements.get(member.name, handle.read())
                entries.append(source_bundle._bytes_entry(
                    member.name, data, member.mode
                ))
        entries.append(source_bundle._bytes_entry(
            source_bundle.MANIFEST_MEMBER, manifest_bytes
        ))
        rewritten = output_tar.with_name(output_tar.name + ".rewritten")
        source_bundle._write_tar(rewritten, entries)
        os.replace(rewritten, output_tar)
        output_manifest.write_bytes(manifest_bytes)

    def test_build_is_deterministic_offline_and_contains_exact_sources(self):
        first_tar, first_manifest = self._build("first")
        second_tar, second_manifest = self._build("second")

        self.assertEqual(first_tar.read_bytes(), second_tar.read_bytes())
        self.assertEqual(first_manifest.read_bytes(), second_manifest.read_bytes())
        verified = source_bundle.verify_bundle(first_tar, first_manifest)
        self.assertEqual(verified["repository"]["commit"], self.commit)
        self.assertEqual(verified["sources"][0]["sha256"], self.lock["sources"][0]["sha256"])

        with tarfile.open(first_tar, "r:") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            self.assertEqual(names, sorted(names, key=lambda item: item.encode("utf-8")))
            self.assertTrue(all(member.uid == member.gid == member.mtime == 0 for member in members))
            self.assertTrue(all(member.uname == member.gname == "" for member in members))
            self.assertTrue(all(not member.pax_headers for member in members))
            upstream = archive.extractfile(
                f"{source_bundle.UPSTREAM_PREFIX}/{self.archive_name}"
            )
            self.assertIsNotNone(upstream)
            self.assertEqual(upstream.read(), self.archive_bytes)
            executable = archive.getmember(
                f"{source_bundle.REPOSITORY_PREFIX}/src/build.sh"
            )
            self.assertEqual(executable.mode, 0o755)
            symlink = archive.getmember(
                f"{source_bundle.REPOSITORY_PREFIX}/src/license-link"
            )
            self.assertTrue(symlink.issym())
            self.assertEqual(symlink.linkname, "../LICENSE.txt")
            embedded_manifest = archive.extractfile(source_bundle.MANIFEST_MEMBER)
            self.assertIsNotNone(embedded_manifest)
            self.assertEqual(embedded_manifest.read(), first_manifest.read_bytes())
        self.assertEqual(first_tar.stat().st_size % tarfile.RECORDSIZE, 0)

    def test_cli_build_and_verify_round_trip(self):
        lock_path = self._write_lock(name="cli.lock.json")
        output_tar = self.root / "cli.tar"
        output_manifest = self.root / "cli.manifest.json"
        built = subprocess.run(
            [
                sys.executable,
                str(ROOT / "packaging" / "source_bundle.py"),
                "build",
                "--lock", str(lock_path),
                "--source-cache", str(self.cache),
                "--repository", str(self.repository),
                "--repository-commit", self.commit,
                "--output-tar", str(output_tar),
                "--output-manifest", str(output_manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("source bundle built", built.stdout)
        verified = subprocess.run(
            [
                sys.executable,
                str(ROOT / "packaging" / "source_bundle.py"),
                "verify",
                "--archive", str(output_tar),
                "--manifest", str(output_manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("source bundle verified", verified.stdout)

    def test_lock_validation_rejects_untrusted_or_incomplete_provenance(self):
        cases = {}

        value = copy.deepcopy(self.lock)
        value["unknown"] = True
        cases["unknown top-level field"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["unknown"] = True
        cases["unknown source field"] = value

        value = copy.deepcopy(self.lock)
        value["provenance_status"] = "pending"
        cases["incomplete provenance"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["version"] = "latest"
        cases["moving version"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["version"] = "release/1.2"
        cases["branch-shaped version"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["archive"] = "codec-latest.tar.xz"
        cases["moving archive"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["archive"] = "codec-1.2.3\n.tar.xz"
        cases["control character in archive"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["source_url"] = (
            "https://github.com/example/codec/archive/refs/heads/main.tar.gz"
        )
        cases["branch URL"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["source_url"] = (
            "https://github.com/example/codec/archive/refs%2Fheads%2Fmain.tar.gz"
        )
        cases["encoded branch URL"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["source_url"] = "http://example.invalid/codec.tar.xz"
        cases["non-HTTPS URL"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["sha256"] = "abc123"
        cases["short SHA"] = value

        for field in ("license", "build", "patches"):
            value = copy.deepcopy(self.lock)
            value["sources"][0].pop(field)
            cases[f"missing {field}"] = value
            value = copy.deepcopy(self.lock)
            value["sources"][0][field] = []
            cases[f"empty {field}"] = value

        value = copy.deepcopy(self.lock)
        value["sources"][0]["license"] = ["LICENSE", "LICENSE"]
        cases["duplicate metadata entry"] = value

        duplicate = copy.deepcopy(self.lock["sources"][0])
        duplicate["version"] = "1.2.4"
        value = copy.deepcopy(self.lock)
        value["sources"].append(duplicate)
        cases["duplicate source"] = value

        for label, invalid in cases.items():
            with self.subTest(label=label), self.assertRaises(source_bundle.SourceBundleError):
                source_bundle.validate_lock(invalid)

    def test_lock_validation_rejects_duplicate_json_keys(self):
        path = self.root / "duplicate.lock.json"
        path.write_text(
            '{"schema":"autoeditor-native-media-sources/v1",'
            '"schema":"autoeditor-native-media-sources/v1",'
            '"provenance_status":"complete","sources":[]}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(source_bundle.SourceBundleError, "duplicate JSON key"):
            source_bundle.load_lock(path)

    def test_windows_drive_prefixed_symlink_targets_are_rejected(self):
        for target in (b"C:/Windows/System32", b"C:../../outside"):
            with self.subTest(target=target), self.assertRaisesRegex(
                source_bundle.SourceBundleError, "symlink target is unsafe"
            ):
                source_bundle._safe_symlink_target("src/link", target)

    def test_build_requires_exact_local_archive_hash_and_explicit_commit(self):
        lock_path = self._write_lock()
        output_tar = self.root / "rejected.tar"
        output_manifest = self.root / "rejected.json"

        (self.cache / self.archive_name).write_bytes(b"tampered")
        with self.assertRaisesRegex(source_bundle.SourceBundleError, "hash mismatch"):
            source_bundle.build_bundle(
                lock_path=lock_path,
                source_cache=self.cache,
                repository=self.repository,
                repository_commit=self.commit,
                output_tar=output_tar,
                output_manifest=output_manifest,
            )
        self.assertFalse(output_tar.exists())
        self.assertFalse(output_manifest.exists())

        (self.cache / self.archive_name).unlink()
        with self.assertRaisesRegex(source_bundle.SourceBundleError, "missing from cache"):
            source_bundle.build_bundle(
                lock_path=lock_path,
                source_cache=self.cache,
                repository=self.repository,
                repository_commit=self.commit,
                output_tar=output_tar,
                output_manifest=output_manifest,
            )

        (self.cache / self.archive_name).write_bytes(self.archive_bytes)
        with self.assertRaisesRegex(source_bundle.SourceBundleError, "explicit full"):
            source_bundle.build_bundle(
                lock_path=lock_path,
                source_cache=self.cache,
                repository=self.repository,
                repository_commit="HEAD",
                output_tar=output_tar,
                output_manifest=output_manifest,
            )

    def test_build_rejects_git_object_bytes_that_do_not_match_their_oid(self):
        blob_oid = self._git("rev-parse", "HEAD:LICENSE.txt").stdout.strip()
        corrupt = b"different bytes hidden under the original Git object ID\n"
        loose_object = self.repository / ".git" / "objects" / blob_oid[:2] / blob_oid[2:]
        loose_object.chmod(0o600)
        loose_object.write_bytes(
            zlib.compress(b"blob " + str(len(corrupt)).encode("ascii") + b"\0" + corrupt)
        )
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError,
            "blob content does not match its object ID",
        ):
            self._build("corrupt-git-object")

    def test_verify_rehashes_archive_entries_and_embedded_manifest(self):
        output_tar, output_manifest = self._build("verify")
        with tarfile.open(output_tar, "r:") as archive:
            upstream = archive.getmember(
                f"{source_bundle.UPSTREAM_PREFIX}/{self.archive_name}"
            )
            data_offset = upstream.offset_data
        with output_tar.open("r+b") as handle:
            handle.seek(data_offset)
            original = handle.read(1)
            handle.seek(data_offset)
            handle.write(bytes([original[0] ^ 0x01]))
        with self.assertRaisesRegex(source_bundle.SourceBundleError, "hash mismatch"):
            source_bundle.verify_bundle(output_tar, output_manifest)

        output_tar, output_manifest = self._build("manifest")
        manifest = json.loads(output_manifest.read_text(encoding="utf-8"))
        manifest["sources"][0]["source_url"] = (
            "https://sources.example.invalid/codec-1.2.3-repacked.tar.xz"
        )
        output_manifest.write_bytes(source_bundle._canonical_json(manifest))
        with self.assertRaisesRegex(source_bundle.SourceBundleError, "embedded manifest hash mismatch"):
            source_bundle.verify_bundle(output_tar, output_manifest)

    def test_manifest_binds_each_locked_source_hash_to_its_archive_entry(self):
        _, output_manifest = self._build("source-binding")
        manifest = json.loads(output_manifest.read_text(encoding="utf-8"))
        manifest["sources"][0]["sha256"] = "0" * 64
        manifest_bytes = source_bundle._canonical_json(manifest)
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError,
            "upstream source hash differs from its lock",
        ):
            source_bundle._validate_manifest(manifest, manifest_bytes)

    def test_verify_reconstructs_the_claimed_git_commit_tree(self):
        output_tar, output_manifest = self._build("git-tree")
        manifest = json.loads(output_manifest.read_text(encoding="utf-8"))
        target = f"{source_bundle.REPOSITORY_PREFIX}/LICENSE.txt"
        changed = b"coherently changed source bytes\n"
        entry = next(item for item in manifest["entries"] if item["path"] == target)
        entry["size"] = len(changed)
        entry["sha256"] = hashlib.sha256(changed).hexdigest()
        self._rewrite_bundle(
            output_tar,
            output_manifest,
            manifest,
            {target: changed},
        )
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError,
            "do not reconstruct the claimed Git tree",
        ):
            source_bundle.verify_bundle(output_tar, output_manifest)


if __name__ == "__main__":
    unittest.main()
