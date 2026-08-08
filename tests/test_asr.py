from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest import mock

import numpy as np

from autoeditor import asr


class AsrContracts(unittest.TestCase):
    def setUp(self):
        self._faster_whisper_modules = {
            name: module
            for name, module in tuple(sys.modules.items())
            if name == "faster_whisper" or name.startswith("faster_whisper.")
        }
        for name in self._faster_whisper_modules:
            sys.modules.pop(name, None)

    def tearDown(self):
        for name in tuple(sys.modules):
            if name == "faster_whisper" or name.startswith("faster_whisper."):
                sys.modules.pop(name, None)
        sys.modules.update(self._faster_whisper_modules)

    def test_decoder_uses_manifest_bound_ffmpeg_and_float32(self):
        pcm = np.array([-8192, 0, 16384], dtype="<i2")
        expected = np.array([-0.25, 0.0, 0.5], dtype=np.float32)
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=pcm.tobytes(), stderr=b""
        )
        with tempfile.TemporaryDirectory() as temporary:
            ffmpeg = Path(temporary) / "ffmpeg"
            ffmpeg.write_bytes(b"binary")
            with mock.patch.dict(
                os.environ, {"AUTOEDITOR_FFMPEG": str(ffmpeg)}
            ), mock.patch.object(
                asr.subprocess, "run", return_value=completed
            ) as invoked:
                actual = asr.decode_audio(Path(temporary) / "input.mp4")
        np.testing.assert_array_equal(actual, expected)
        command = invoked.call_args.args[0]
        self.assertEqual(command[0], str(ffmpeg))
        self.assertIn("0:a:0", command)
        self.assertIn("s16le", command)
        self.assertNotIn("shell", invoked.call_args.kwargs)

    def test_decoder_fails_closed_on_ffmpeg_error_or_invalid_pcm(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffmpeg = Path(temporary) / "ffmpeg"
            ffmpeg.write_bytes(b"binary")
            environment = {"AUTOEDITOR_FFMPEG": str(ffmpeg)}
            failed = subprocess.CompletedProcess(
                args=[], returncode=1, stdout=b"", stderr=b"bad input"
            )
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                asr.subprocess, "run", return_value=failed
            ):
                with self.assertRaisesRegex(RuntimeError, "audio decode failed"):
                    asr.decode_audio("input.mp4")
            malformed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"abc", stderr=b""
            )
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                asr.subprocess, "run", return_value=malformed
            ):
                with self.assertRaisesRegex(RuntimeError, "invalid or empty"):
                    asr.decode_audio("input.mp4")

    def test_faster_whisper_audio_is_replaced_before_import(self):
        asr.prepare_faster_whisper()
        shim = sys.modules["faster_whisper.audio"]
        self.assertTrue(shim._autoeditor_ffmpeg_decoder)
        self.assertIs(shim.decode_audio, asr.decode_audio)
        self.assertTrue(asr.decoder_contract_check())
        import faster_whisper

        transcribe_module = importlib.import_module("faster_whisper.transcribe")
        self.assertIs(faster_whisper.decode_audio, asr.decode_audio)
        self.assertIs(transcribe_module.decode_audio, asr.decode_audio)
        self.assertIs(transcribe_module.pad_or_trim, asr._pad_or_trim)

    def test_pyav_payload_scan_rejects_packages_and_native_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(asr.pyav_payload_paths(root), ())
            package = root / "av" / "_core.pyd"
            package.parent.mkdir()
            package.write_bytes(b"native")
            self.assertEqual(
                asr.pyav_payload_paths(root), ("av", "av/_core.pyd")
            )
            package.unlink()
            package.parent.rmdir()
            library = root / "nested" / "libavcodec.61.dylib"
            library.parent.mkdir()
            library.write_bytes(b"native")
            self.assertEqual(
                asr.pyav_payload_paths(root),
                ("nested/libavcodec.61.dylib",),
            )

    def test_pyav_payload_scan_rejects_complete_native_family_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = (
                "libavdevice.61.dylib",
                "libavfilter.10.dylib",
                "libpostproc.58.dylib",
                "avdevice-61.dll",
                "avfilter-10.dll",
                "postproc-58.dll",
            )
            for name in names:
                path = root / "native" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"native")
            metadata = root / "av-14.2.0.dist-info" / "METADATA"
            metadata.parent.mkdir()
            metadata.write_text("Name: av\n", encoding="utf-8")
            self.assertEqual(
                asr.pyav_payload_paths(root),
                tuple(sorted(
                    [f"native/{name}" for name in names]
                    + [
                        "av-14.2.0.dist-info",
                        "av-14.2.0.dist-info/METADATA",
                    ]
                )),
            )

    def test_frozen_spec_excludes_pyav(self):
        root = Path(__file__).resolve().parent.parent
        spec = (root / "packaging" / "engine.spec").read_text(
            encoding="utf-8"
        )
        entry = (root / "packaging" / "engine_entry.py").read_text(
            encoding="utf-8"
        )
        notices = (root / "packaging" / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )
        helper_spec = (root / "packaging" / "helper_daemon.spec").read_text(
            encoding="utf-8"
        )
        helper_entry = (
            root / "packaging" / "helper_daemon_entry.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"onnxruntime", "av"', spec)
        self.assertIn('"auto_editor", "av"', spec)
        self.assertIn('"pytest", "av"', helper_spec)
        self.assertIn("asr.pyav_payload_absent()", helper_entry)
        self.assertIn("excluded from the frozen engine", notices)
        self.assertIn("no PyAV FFmpeg libraries are distributed", notices)
        self.assertIn("multiprocessing.freeze_support()", entry)
        self.assertLess(
            entry.index("multiprocessing.freeze_support()"),
            entry.rindex("main()"),
        )

    def test_engine_audio_decoder_self_test_uses_real_ffmpeg(self):
        if not asr.shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is unavailable")
        root = Path(__file__).resolve().parent.parent
        namespace = runpy.run_path(str(root / "packaging" / "engine_entry.py"))
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=False), \
                contextlib.redirect_stdout(stdout):
            os.environ.pop("AUTOEDITOR_FFMPEG", None)
            self.assertEqual(namespace["_audio_decoder_self_test"](), 0)
        self.assertTrue(
            json.loads(stdout.getvalue())["checks"]["ffmpeg_waveform_decode"]
        )

    @unittest.skipIf(os.name == "nt", "symlinked venv regression is POSIX-only")
    def test_source_worker_preserves_symlinked_virtual_environment(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            environment = Path(temporary) / "venv"
            venv.EnvBuilder(
                with_pip=False,
                system_site_packages=True,
                symlinks=True,
            ).create(environment)
            python = environment / "bin" / "python"
            site_packages = subprocess.run(
                [
                    str(python),
                    "-c",
                    "import sysconfig; print(sysconfig.get_paths()['purelib'])",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            Path(site_packages, "autoeditor_venv_marker.py").write_text(
                "MARKER = 'venv-site-packages'\n", encoding="utf-8"
            )
            code = (
                "import subprocess; from autoeditor import pipeline; "
                "r=subprocess.run([str(pipeline.VENV_PY),'-c',"
                "'import autoeditor_venv_marker as m; print(m.MARKER)'],"
                "check=True,capture_output=True,text=True); "
                "print(r.stdout.strip())"
            )
            process = subprocess.run(
                [str(python), "-c", code],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(root)},
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.strip(), "venv-site-packages")


if __name__ == "__main__":
    unittest.main()
