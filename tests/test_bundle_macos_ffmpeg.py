from __future__ import annotations

import importlib.util
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "bundle_macos_ffmpeg.py"
SPEC = importlib.util.spec_from_file_location("bundle_macos_ffmpeg_tested", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)


class BundleMacOSFFmpegTests(unittest.TestCase):
    def test_uses_only_exact_system_tool_paths(self) -> None:
        self.assertEqual(
            bundle.SYSTEM_TOOLS,
            (
                Path("/usr/bin/otool"),
                Path("/usr/bin/install_name_tool"),
                Path("/usr/bin/codesign"),
            ),
        )
        with mock.patch.object(bundle, "run", return_value="fixture:\n") as run:
            self.assertEqual(bundle.dependencies(Path("/tmp/fixture")), [])
        run.assert_called_once_with(
            Path("/usr/bin/otool"), "-L", Path("/tmp/fixture"), capture=True
        )

    def test_system_tool_validation_rejects_missing_or_nonregular_paths(self) -> None:
        regular = mock.Mock(st_mode=stat.S_IFREG | 0o755)
        with mock.patch.object(Path, "lstat", return_value=regular):
            bundle.validate_system_tools()

        with mock.patch.object(Path, "lstat", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "is unavailable"):
                bundle.validate_system_tools()

        symlink = mock.Mock(st_mode=stat.S_IFLNK | 0o777)
        with mock.patch.object(Path, "lstat", return_value=symlink):
            with self.assertRaisesRegex(RuntimeError, "not a regular file"):
                bundle.validate_system_tools()


if __name__ == "__main__":
    unittest.main()
