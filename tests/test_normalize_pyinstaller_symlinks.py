from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "normalize_pyinstaller_symlinks.py"
SPEC = importlib.util.spec_from_file_location(
    "autoeditor_normalize_pyinstaller_symlinks", SCRIPT
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load PyInstaller normalizer: {SCRIPT}")
normalizer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = normalizer
SPEC.loader.exec_module(normalizer)


@unittest.skipUnless(sys.platform == "darwin", "Mac-only normalizer")
class NormalizePyInstallerSymlinksTests(unittest.TestCase):
    def _stage(self, root: Path) -> Path:
        stage = root / "helper-staging"
        (stage / "licenses").mkdir(parents=True)
        engine = stage / "engine"
        helper = stage / "helper"
        (engine / "_internal/nested").mkdir(parents=True)
        (helper / "_internal").mkdir(parents=True)

        engine_executable = engine / "autoeditor-engine"
        helper_executable = helper / "autoeditor-helper-daemon"
        engine_executable.write_bytes(b"engine executable")
        helper_executable.write_bytes(b"helper executable")
        engine_executable.chmod(0o755)
        helper_executable.chmod(0o755)

        engine_library = engine / "_internal/libreal.1.dylib"
        engine_library.write_bytes(b"engine dylib bytes")
        engine_library.chmod(0o644)
        (engine / "_internal/libreal.dylib").symlink_to(
            "libreal.1.dylib"
        )
        (engine / "_internal/libchain.dylib").symlink_to(
            "libreal.dylib"
        )
        (engine / "_internal/nested/libparent.dylib").symlink_to(
            "../libreal.1.dylib"
        )

        helper_library = helper / "_internal/helper-real.dylib"
        helper_library.write_bytes(b"helper dylib bytes")
        helper_library.chmod(0o644)
        (helper / "_internal/helper-link.dylib").symlink_to(
            "helper-real.dylib"
        )

        unrelated = stage / "creative-runtime.txt"
        unrelated.write_bytes(b"outside exact engine/helper scope")
        return stage

    @staticmethod
    def _receipt_path(stage: Path) -> Path:
        return (
            stage
            / normalizer.RECEIPT_DIRECTORY
            / normalizer.RECEIPT_FILENAME
        )

    @staticmethod
    def _tree_digest(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            if stat.S_ISLNK(metadata.st_mode):
                digest.update(b"link\0")
                digest.update(os.readlink(path).encode("utf-8"))
            elif stat.S_ISDIR(metadata.st_mode):
                digest.update(b"dir\0")
            elif stat.S_ISREG(metadata.st_mode):
                digest.update(b"file\0")
                digest.update(path.read_bytes())
            else:
                digest.update(b"special\0")
        return digest.hexdigest()

    def test_normalizes_only_engine_and_helper_and_verifies_canonical_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            unrelated = stage / "creative-runtime.txt"
            unrelated_identity = (
                unrelated.stat().st_dev,
                unrelated.stat().st_ino,
                unrelated.read_bytes(),
            )

            payload = normalizer.normalize_stage(stage, "arm64")
            receipt_path = self._receipt_path(stage)
            raw = receipt_path.read_bytes()
            self.assertEqual(raw, normalizer.canonical_json_bytes(payload))
            self.assertEqual(
                payload["roots"], ["engine", "helper"]
            )
            self.assertEqual(
                payload["target"], {"arch": "arm64", "os": "mac"}
            )
            self.assertEqual(normalizer.verify_stage(stage, "arm64"), payload)

            aliases = (
                stage / "engine/_internal/libreal.dylib",
                stage / "engine/_internal/libchain.dylib",
                stage / "engine/_internal/nested/libparent.dylib",
                stage / "helper/_internal/helper-link.dylib",
            )
            for alias in aliases:
                self.assertFalse(alias.is_symlink())
                self.assertTrue(alias.is_file())
                self.assertEqual(alias.stat().st_nlink, 1)
            self.assertEqual(aliases[0].read_bytes(), b"engine dylib bytes")
            self.assertEqual(aliases[1].read_bytes(), b"engine dylib bytes")
            self.assertEqual(aliases[2].read_bytes(), b"engine dylib bytes")
            self.assertEqual(aliases[3].read_bytes(), b"helper dylib bytes")
            self.assertNotEqual(
                aliases[0].stat().st_ino,
                (stage / "engine/_internal/libreal.1.dylib").stat().st_ino,
            )
            self.assertEqual(
                (
                    unrelated.stat().st_dev,
                    unrelated.stat().st_ino,
                    unrelated.read_bytes(),
                ),
                unrelated_identity,
            )
            self.assertFalse(any(
                path.name.startswith(".autoeditor-pyinstaller-normalize-")
                for path in root.iterdir()
            ))

            run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--stage-root", str(stage),
                    "--target-arch", "arm64",
                    "--verify-only",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("receipt SHA256", run.stdout)
            with self.assertRaisesRegex(
                normalizer.NormalizationError,
                "already exists; use --verify-only",
            ):
                normalizer.normalize_stage(stage, "arm64")

    def test_absolute_escape_directory_and_cycle_links_fail_without_mutation(self):
        cases = ("absolute", "escape", "directory", "cycle")
        for mutation in cases:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                stage = self._stage(root)
                engine = stage / "engine"
                alias = engine / "_internal/libreal.dylib"
                alias.unlink()
                outside = root / "outside"
                outside.write_bytes(b"outside must not change")
                before = outside.read_bytes()
                if mutation == "absolute":
                    alias.symlink_to(outside)
                    error = "nonempty relative path"
                elif mutation == "escape":
                    alias.symlink_to("../../outside")
                    error = "escapes its frozen runtime"
                elif mutation == "directory":
                    alias.symlink_to("nested", target_is_directory=True)
                    error = "not a regular file"
                else:
                    cycle = engine / "_internal/cycle.dylib"
                    alias.symlink_to("cycle.dylib")
                    cycle.symlink_to("libreal.dylib")
                    error = "symlink cycle"
                engine_before = self._tree_digest(engine)
                helper_before = self._tree_digest(stage / "helper")
                with self.assertRaisesRegex(
                    normalizer.NormalizationError, error
                ):
                    normalizer.normalize_stage(stage, "arm64")
                self.assertEqual(self._tree_digest(engine), engine_before)
                self.assertEqual(
                    self._tree_digest(stage / "helper"), helper_before
                )
                self.assertEqual(outside.read_bytes(), before)
                self.assertFalse(self._receipt_path(stage).exists())

    def test_hardlinks_and_special_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            source = stage / "engine/_internal/libreal.1.dylib"
            duplicate = stage / "engine/_internal/duplicate.dylib"
            try:
                os.link(source, duplicate)
            except OSError as exc:
                self.skipTest(f"hardlinks unavailable: {exc}")
            with self.assertRaisesRegex(
                normalizer.NormalizationError,
                "exactly one filesystem link|single-link regular file",
            ):
                normalizer.normalize_stage(stage, "arm64")
            self.assertTrue((stage / "engine/_internal/libreal.dylib").is_symlink())
            self.assertFalse(self._receipt_path(stage).exists())

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                stage = self._stage(root)
                os.mkfifo(stage / "helper/_internal/pipe")
                with self.assertRaisesRegex(
                    normalizer.NormalizationError, "special file"
                ):
                    normalizer.normalize_stage(stage, "x64")
                self.assertFalse(self._receipt_path(stage).exists())

    def test_directory_swap_to_outside_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            engine = stage / "engine"
            nested = engine / "_internal/nested"
            moved = engine / "_internal/nested-original"
            outside = root / "outside-directory"
            outside.mkdir()
            marker = outside / "marker"
            marker.write_bytes(b"outside")
            engine_identity = (engine.stat().st_dev, engine.stat().st_ino)
            real_listdir = normalizer.os.listdir
            swapped = False

            def racing_listdir(descriptor):
                nonlocal swapped
                names = real_listdir(descriptor)
                identity = (
                    os.fstat(descriptor).st_dev,
                    os.fstat(descriptor).st_ino,
                )
                if not swapped and identity == engine_identity:
                    nested.rename(moved)
                    nested.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return names

            with mock.patch.object(
                normalizer.os, "listdir", side_effect=racing_listdir
            ), self.assertRaisesRegex(
                normalizer.NormalizationError,
                "directory symlink|not a regular file|nonempty relative path",
            ):
                normalizer.normalize_stage(stage, "arm64")
            self.assertTrue(swapped)
            self.assertEqual(marker.read_bytes(), b"outside")
            self.assertFalse(self._receipt_path(stage).exists())

    def test_post_swap_receipt_failure_rolls_back_both_runtime_trees(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            engine_before = self._tree_digest(stage / "engine")
            helper_before = self._tree_digest(stage / "helper")
            with mock.patch.object(
                normalizer,
                "_write_receipt",
                side_effect=normalizer.NormalizationError(
                    "forced receipt failure"
                ),
            ), self.assertRaisesRegex(
                normalizer.NormalizationError, "forced receipt failure"
            ):
                normalizer.normalize_stage(stage, "arm64")
            self.assertEqual(self._tree_digest(stage / "engine"), engine_before)
            self.assertEqual(self._tree_digest(stage / "helper"), helper_before)
            self.assertTrue((stage / "engine/_internal/libreal.dylib").is_symlink())
            self.assertTrue(
                (stage / "helper/_internal/helper-link.dylib").is_symlink()
            )
            self.assertFalse(self._receipt_path(stage).exists())

    def test_verified_commit_survives_partial_backup_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            original_delete = normalizer._delete_entry
            deleted: list[str] = []

            def fail_after_first_backup(parent_fd, name):
                if name == "original-engine":
                    original_delete(parent_fd, name)
                    deleted.append(name)
                    return
                if name == "original-helper":
                    raise normalizer.NormalizationError(
                        "forced second backup deletion failure"
                    )
                original_delete(parent_fd, name)

            with mock.patch.object(
                normalizer,
                "_delete_entry",
                side_effect=fail_after_first_backup,
            ), self.assertRaisesRegex(
                normalizer.NormalizationError,
                "committed and verified, but backup cleanup failed",
            ):
                normalizer.normalize_stage(stage, "arm64")
            self.assertEqual(deleted, ["original-engine"])
            self.assertTrue(self._receipt_path(stage).is_file())
            self.assertFalse(
                any(
                    path.is_symlink()
                    for runtime in normalizer.RUNTIME_NAMES
                    for path in (stage / runtime).rglob("*")
                )
            )
            normalizer.verify_stage(stage, "arm64")

    def test_licenses_directory_swap_fails_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            engine_before = self._tree_digest(stage / "engine")
            helper_before = self._tree_digest(stage / "helper")
            moved_licenses = root / "moved-licenses"
            original_write = normalizer._write_receipt

            def swap_licenses_and_write(licenses_fd, payload):
                (stage / "licenses").rename(moved_licenses)
                (stage / "licenses").mkdir()
                original_write(licenses_fd, payload)

            with mock.patch.object(
                normalizer,
                "_write_receipt",
                side_effect=swap_licenses_and_write,
            ), self.assertRaisesRegex(
                normalizer.NormalizationError,
                "licenses directory changed",
            ):
                normalizer.normalize_stage(stage, "arm64")
            self.assertEqual(self._tree_digest(stage / "engine"), engine_before)
            self.assertEqual(self._tree_digest(stage / "helper"), helper_before)
            self.assertFalse(self._receipt_path(stage).exists())
            self.assertFalse(
                (moved_licenses / normalizer.RECEIPT_FILENAME).exists()
            )

    def test_verify_only_rejects_runtime_and_receipt_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            normalizer.normalize_stage(stage, "arm64")
            target = stage / "engine/_internal/libreal.dylib"
            target.write_bytes(b"drift")
            with self.assertRaisesRegex(
                normalizer.NormalizationError, "does not match receipt"
            ):
                normalizer.verify_stage(stage, "arm64")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            normalizer.normalize_stage(stage, "arm64")
            receipt_path = self._receipt_path(stage)
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            payload["runtimes"]["engine"]["source_inventory_sha256"] = "0" * 64
            receipt_path.write_bytes(normalizer.canonical_json_bytes(payload))
            with self.assertRaisesRegex(
                normalizer.NormalizationError,
                "source inventory digest does not match reconstructed engine",
            ):
                normalizer.verify_stage(stage, "arm64")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            normalizer.normalize_stage(stage, "x64")
            receipt_path = self._receipt_path(stage)
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                normalizer.NormalizationError, "not canonical"
            ):
                normalizer.verify_stage(stage, "x64")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            normalizer.normalize_stage(stage, "arm64")
            receipt_path = self._receipt_path(stage)
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            link = payload["runtimes"]["engine"]["normalized_links"][0]
            link["resolved_path"] = "autoeditor-engine"
            receipt_path.write_bytes(normalizer.canonical_json_bytes(payload))
            with self.assertRaisesRegex(
                normalizer.NormalizationError,
                "resolved target does not match copied bytes",
            ):
                normalizer.verify_stage(stage, "arm64")

    def test_stage_links_receipt_collision_and_missing_executable_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            linked = root / "linked-stage"
            linked.symlink_to(stage, target_is_directory=True)
            with self.assertRaisesRegex(
                normalizer.NormalizationError, "directory symlink"
            ):
                normalizer.normalize_stage(linked, "arm64")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            receipt = self._receipt_path(stage)
            receipt.write_bytes(b"collision")
            engine_before = self._tree_digest(stage / "engine")
            with self.assertRaisesRegex(
                normalizer.NormalizationError, "already exists"
            ):
                normalizer.normalize_stage(stage, "arm64")
            self.assertEqual(self._tree_digest(stage / "engine"), engine_before)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage = self._stage(root)
            (stage / "helper/autoeditor-helper-daemon").unlink()
            with self.assertRaisesRegex(
                normalizer.NormalizationError, "missing required executable"
            ):
                normalizer.normalize_stage(stage, "x64")
            self.assertFalse(self._receipt_path(stage).exists())

    def test_cli_exposes_no_scope_or_receipt_override(self):
        parser = normalizer.build_parser()
        options = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertEqual(
            options,
            {"-h", "--help", "--stage-root", "--target-arch", "--verify-only"},
        )
        self.assertNotIn("--runtime", options)
        self.assertNotIn("--receipt", options)
        with self.assertRaisesRegex(
            normalizer.NormalizationError, "unsupported Mac target architecture"
        ):
            normalizer.normalize_stage(Path("unused"), "universal")


if __name__ == "__main__":
    unittest.main()
