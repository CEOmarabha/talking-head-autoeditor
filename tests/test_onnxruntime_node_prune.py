import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "packaging"
    / "prune_onnxruntime_node.py"
)
SPEC = importlib.util.spec_from_file_location(
    "autoeditor_onnxruntime_node_pruner",
    SCRIPT_PATH,
)
PRUNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PRUNER
SPEC.loader.exec_module(PRUNER)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, base):
        self.stage = Path(base) / "stage"
        self.package = (
            self.stage
            / "creative-runtime"
            / "node_modules"
            / "onnxruntime-node"
        )
        self.native = self.package / "bin" / "napi-v3"
        self.licenses = self.stage / "licenses"
        self.licenses.mkdir(parents=True)
        self.native.mkdir(parents=True)
        self.transactions = Path(base) / "transactions"
        self.transactions.mkdir()
        self.lock = Path(base) / "package-lock.json"
        self.package_fields = {
            "name": "onnxruntime-node-fixture",
            "version": "1.0.0",
            "license": "MIT",
            "os": ["win32", "darwin"],
        }
        (self.package / "package.json").write_text(
            json.dumps(self.package_fields),
            encoding="utf-8",
        )
        (self.package / "README.md").write_bytes(b"fixture readme")
        self.targets = {
            ("mac", "arm64"): "darwin/arm64",
            ("mac", "x64"): "darwin/x64",
            ("windows", "x64"): "win32/x64",
        }
        self.inventory = {}
        for target in self.targets.values():
            directory = self.native / target
            directory.mkdir(parents=True)
            for name in ("runtime.bin", "binding.node"):
                path = directory / name
                path.write_bytes(f"{target}:{name}".encode("ascii"))
                self.inventory[path.relative_to(self.native).as_posix()] = digest(path)
        self.lock_entry = {
            "integrity": "sha512-fixture",
            "version": "1.0.0",
        }
        self.write_lock(self.lock_entry)
        package_inventory = {
            "README.md": digest(self.package / "README.md"),
            "package.json": digest(self.package / "package.json"),
        }
        package_inventory.update(
            {
                "bin/napi-v3/" + relative: value
                for relative, value in self.inventory.items()
            }
        )
        self.policy = PRUNER.Policy(
            package_name="onnxruntime-node-fixture",
            package_version="1.0.0",
            package_relative_root=Path(
                "creative-runtime/node_modules/onnxruntime-node"
            ),
            native_relative_root=Path("bin/napi-v3"),
            lock_package_key="node_modules/onnxruntime-node",
            lock_entry=self.lock_entry,
            package_fields=self.package_fields,
            inventory=self.inventory,
            package_inventory=package_inventory,
            targets=self.targets,
        )
        self.receipt = self.package / PRUNER.RECEIPT_RELATIVE_PATH

    def write_lock(self, entry):
        self.lock.write_text(
            json.dumps(
                {"packages": {"node_modules/onnxruntime-node": entry}}
            ),
            encoding="utf-8",
        )

    def run(self, target=("windows", "x64"), policy=None):
        return PRUNER.run_gate(
            self.stage,
            self.lock,
            self.transactions,
            target[0],
            target[1],
            policy or self.policy,
        )


class OnnxRuntimeNodePruneTests(unittest.TestCase):
    def test_each_supported_target_keeps_only_its_exact_native_files(self):
        for target in PRUNER.TARGET_DIRECTORIES:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(temp)
                receipt = fixture.run(target)
                kept_prefix = fixture.targets[target] + "/"
                expected = {
                    name: value
                    for name, value in fixture.inventory.items()
                    if name.startswith(kept_prefix)
                }
                observed, directories = PRUNER._inventory(fixture.native)
                self.assertEqual(observed, expected)
                self.assertEqual(
                    directories,
                    PRUNER._expected_directories(expected),
                )
                self.assertEqual(
                    {entry["path"] for entry in receipt["kept"]},
                    set(expected),
                )
                self.assertEqual(
                    json.loads(fixture.receipt.read_text(encoding="utf-8")),
                    receipt,
                )

    def test_extra_missing_or_changed_native_file_fails_before_deletion(self):
        for mutation in ("extra", "missing", "changed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(temp)
                path = fixture.native / "darwin" / "arm64" / "runtime.bin"
                if mutation == "extra":
                    (fixture.native / "surprise.dll").write_bytes(b"extra")
                elif mutation == "missing":
                    path.unlink()
                else:
                    path.write_bytes(b"changed")
                before, before_directories = PRUNER._inventory(fixture.native)

                with self.assertRaisesRegex(PRUNER.GateError, "inventory drift"):
                    fixture.run()

                after, after_directories = PRUNER._inventory(fixture.native)
                self.assertEqual(after, before)
                self.assertEqual(after_directories, before_directories)

    def test_lock_or_package_metadata_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            bad_lock = copy.deepcopy(fixture.lock_entry)
            bad_lock["integrity"] = "sha512-wrong"
            fixture.write_lock(bad_lock)
            with self.assertRaisesRegex(PRUNER.GateError, "lock entry drift"):
                fixture.run()

        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            metadata = dict(fixture.package_fields)
            metadata["version"] = "2.0.0"
            (fixture.package / "package.json").write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PRUNER.GateError, "metadata drift"):
                fixture.run()

    def test_linked_or_hardlinked_native_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            path = fixture.native / "darwin" / "arm64" / "runtime.bin"
            outside = Path(temp) / "outside"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            try:
                os.link(outside, path)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")
            with self.assertRaisesRegex(PRUNER.GateError, "linked file"):
                fixture.run()

    def test_receipt_collision_fails_before_any_native_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            fixture.receipt.write_bytes(b"collision")
            non_target = fixture.native / "darwin" / "arm64" / "runtime.bin"
            before = digest(non_target)
            with self.assertRaisesRegex(PRUNER.GateError, "inventory drift"):
                fixture.run()
            self.assertEqual(digest(non_target), before)

    def test_receipt_failure_leaves_published_package_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            before, before_directories = PRUNER._inventory(fixture.package)
            with mock.patch.object(
                PRUNER._DirectoryRenamer,
                "write_receipt",
                side_effect=PRUNER.GateError("forced receipt failure"),
            ):
                with self.assertRaisesRegex(PRUNER.GateError, "receipt failure"):
                    fixture.run()
            after, after_directories = PRUNER._inventory(fixture.package)
            self.assertEqual(after, before)
            self.assertEqual(after_directories, before_directories)

    def test_receipt_parent_swap_never_writes_outside_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            outside = Path(temp) / "outside-receipt-target"
            outside.mkdir()
            original = PRUNER._DirectoryRenamer.write_receipt

            def swap_then_write(renamer, directory_name, filename, payload):
                candidate = renamer.transaction / directory_name
                moved = renamer.transaction / "moved-target-package"
                candidate.rename(moved)
                candidate.symlink_to(outside, target_is_directory=True)
                return original(renamer, directory_name, filename, payload)

            with mock.patch.object(
                PRUNER._DirectoryRenamer,
                "write_receipt",
                autospec=True,
                side_effect=swap_then_write,
            ):
                with self.assertRaises((PRUNER.GateError, OSError)):
                    fixture.run()
            self.assertFalse(
                (outside / PRUNER.RECEIPT_RELATIVE_PATH.name).exists()
            )

    def test_verify_only_rejects_payload_or_receipt_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            expected = fixture.run()
            self.assertEqual(
                PRUNER.verify_gate(
                    fixture.stage,
                    fixture.lock,
                    "windows",
                    "x64",
                    fixture.policy,
                ),
                expected,
            )
            binding = fixture.native / "win32" / "x64" / "binding.node"
            binding.write_bytes(b"drift after prune")
            with self.assertRaisesRegex(PRUNER.GateError, "inventory drift"):
                PRUNER.verify_gate(
                    fixture.stage,
                    fixture.lock,
                    "windows",
                    "x64",
                    fixture.policy,
                )

        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            fixture.run()
            fixture.receipt.write_bytes(b"{}\n")
            with self.assertRaisesRegex(PRUNER.GateError, "receipt"):
                PRUNER.verify_gate(
                    fixture.stage,
                    fixture.lock,
                    "windows",
                    "x64",
                    fixture.policy,
                )

    def test_no_unsafe_path_rename_fallback_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            package_parent = Path(temp) / "package-parent"
            transaction = Path(temp) / "transaction"
            package_parent.mkdir()
            transaction.mkdir()
            with mock.patch.object(PRUNER.os, "supports_dir_fd", set()), \
                    mock.patch.object(PRUNER.os, "name", "posix"):
                with self.assertRaisesRegex(PRUNER.GateError, "unavailable"):
                    PRUNER._DirectoryRenamer(package_parent, transaction)

    def test_late_replacement_drift_leaves_published_package_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            before, before_directories = PRUNER._inventory(fixture.package)
            original_copy = PRUNER._copy_target_package

            def corrupt_after_copy(source, destination, native_root, keep):
                original_copy(source, destination, native_root, keep)
                target = destination / native_root / keep / "binding.node"
                target.write_bytes(b"late drift")

            with mock.patch.object(
                PRUNER,
                "_copy_target_package",
                side_effect=corrupt_after_copy,
            ):
                with self.assertRaisesRegex(PRUNER.GateError, "inventory drift"):
                    fixture.run()
            after, after_directories = PRUNER._inventory(fixture.package)
            self.assertEqual(after, before)
            self.assertEqual(after_directories, before_directories)

    def test_post_swap_failure_restores_the_exact_published_package(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            before, before_directories = PRUNER._inventory(fixture.package)
            original = PRUNER._verify_package_metadata

            def fail_committed(root, policy):
                original(root, policy)
                if (root / fixture.receipt.name).exists():
                    raise PRUNER.GateError("forced committed-package failure")

            with mock.patch.object(
                PRUNER,
                "_verify_package_metadata",
                side_effect=fail_committed,
            ):
                with self.assertRaisesRegex(PRUNER.GateError, "committed-package"):
                    fixture.run()
            after, after_directories = PRUNER._inventory(fixture.package)
            self.assertEqual(after, before)
            self.assertEqual(after_directories, before_directories)
            self.assertFalse(fixture.receipt.exists())

    def test_parent_swap_never_deletes_or_changes_outside_files(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            original_copy = PRUNER._copy_target_package
            moved = Path(temp) / "moved-arm64"
            outside_hashes = {}

            def swap_after_copy(*args, **kwargs):
                original_copy(*args, **kwargs)
                source = fixture.native / "darwin" / "arm64"
                source.rename(moved)
                outside_hashes.update(
                    {path.name: digest(path) for path in moved.iterdir()}
                )
                try:
                    source.symlink_to(moved, target_is_directory=True)
                except OSError as exc:
                    moved.rename(source)
                    self.skipTest(f"directory symlinks unavailable: {exc}")

            with mock.patch.object(
                PRUNER,
                "_copy_target_package",
                side_effect=swap_after_copy,
            ):
                receipt = fixture.run()
            self.assertEqual(
                {path.name: digest(path) for path in moved.iterdir()},
                outside_hashes,
            )
            self.assertEqual(
                receipt["target"],
                {"os": "windows", "arch": "x64"},
            )

    def test_unsupported_target_and_policy_overrides_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(temp)
            with self.assertRaisesRegex(PRUNER.GateError, "unsupported"):
                fixture.run(("windows", "arm64"))
        options = {
            option
            for action in PRUNER.build_parser()._actions
            for option in action.option_strings
        }
        self.assertNotIn("--policy", options)
        self.assertNotIn("--receipt", options)
        self.assertNotIn("--expected-digest", options)
        self.assertIn("--transaction-parent", options)
        self.assertIn("--verify-only", options)

    def test_production_policy_and_repository_lock_are_exact(self):
        root = Path(__file__).resolve().parents[1]
        PRUNER._verify_lock(
            root / "packaging" / "helper-runtime" / "package-lock.json",
            PRUNER.PRODUCTION_POLICY,
        )
        self.assertEqual(len(PRUNER.EXPECTED_NATIVE_INVENTORY), 17)
        self.assertEqual(len(PRUNER.EXPECTED_PACKAGE_INVENTORY), 40)
        expected_counts = {
            target: sum(
                name.startswith(directory + "/")
                for name in PRUNER.EXPECTED_NATIVE_INVENTORY
            )
            for target, directory in PRUNER.TARGET_DIRECTORIES.items()
        }
        self.assertEqual(
            expected_counts,
            {("mac", "arm64"): 2, ("mac", "x64"): 2, ("windows", "x64"): 3},
        )


if __name__ == "__main__":
    unittest.main()
