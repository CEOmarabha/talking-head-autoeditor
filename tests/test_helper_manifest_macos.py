from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "packaging" / "generate_helper_manifest.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "helper_manifest_macos_test_generator", SOURCE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MacHelperManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = _load_generator()

    def test_macho_magic_routes_through_codesign_normalizer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "native.node"
            native.write_bytes(b"\xcf\xfa\xed\xfe" + b"not-a-real-macho")
            expected = {"bytes": 17, "sha256": "a" * 64}
            with mock.patch.object(
                self.generator,
                "macho_codesign_content_receipt",
                return_value=expected,
            ) as normalizer:
                receipt = self.generator.directory_receipt(
                    root, normalize_macos_machos=True
                )
            normalizer.assert_called_once_with(native)
            self.assertEqual(receipt["files"], 1)
            self.assertEqual(receipt["bytes"], expected["bytes"])

    def test_normalization_targets_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                self.generator.ManifestReceiptError, "ambiguous"
            ):
                self.generator.directory_receipt(
                    Path(temporary),
                    normalize_windows_executables=True,
                    normalize_macos_machos=True,
                )

    @unittest.skipUnless(
        sys.platform == "darwin"
        and Path("/usr/bin/clang").is_file()
        and Path("/usr/bin/codesign").is_file(),
        "requires the exact macOS compiler and codesign tools",
    )
    def test_real_signature_replacement_preserves_only_macho_content(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            source = root / "main.c"
            binary = root / "runtime"
            marker = b"AUTOEDITOR_MANIFEST_MARKER"
            source.write_text(
                "__attribute__((used)) static const char marker[] = "
                '"AUTOEDITOR_MANIFEST_MARKER";\n'
                "int main(void) { return marker[0] == 'A' ? 0 : 1; }\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["/usr/bin/clang", str(source), "-o", str(binary)],
                check=True,
                capture_output=True,
                text=True,
            )

            def sign(identifier: str) -> None:
                subprocess.run(
                    [
                        "/usr/bin/codesign", "--force", "--sign", "-",
                        "--identifier", identifier, str(binary),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

            sign("com.marabha.autoeditor.manifest.one")
            first = self.generator.macho_codesign_content_receipt(binary)
            sign("com.marabha.autoeditor.manifest.two")
            second = self.generator.macho_codesign_content_receipt(binary)
            self.assertEqual(first, second)

            raw = binary.read_bytes()
            offset = raw.find(marker)
            self.assertGreaterEqual(offset, 0)
            changed = bytearray(raw)
            changed[offset + len(marker) - 1] ^= 0x01
            binary.write_bytes(changed)
            sign("com.marabha.autoeditor.manifest.three")
            third = self.generator.macho_codesign_content_receipt(binary)
            self.assertNotEqual(first, third)

    @unittest.skipUnless(
        sys.platform == "darwin"
        and Path("/usr/bin/clang").is_file()
        and Path("/usr/bin/codesign").is_file(),
        "requires the exact macOS compiler and codesign tools",
    )
    def test_real_macho_bundle_is_supported(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            source = root / "bundle.c"
            bundle = root / "native.node"
            source.write_text("int autoeditor_bundle(void) { return 7; }\n")
            subprocess.run(
                ["/usr/bin/clang", "-bundle", str(source), "-o", str(bundle)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)],
                check=True,
                capture_output=True,
                text=True,
            )
            receipt = self.generator.macho_codesign_content_receipt(bundle)
            self.assertGreater(receipt["bytes"], 0)
            self.assertRegex(receipt["sha256"], r"\A[0-9a-f]{64}\Z")


if __name__ == "__main__":
    unittest.main()
