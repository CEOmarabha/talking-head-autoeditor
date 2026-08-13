from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from autoeditor import pipeline


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _binding(path: Path, *, music: bool) -> dict:
    result = {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "duration_ms": 4_000,
    }
    if music:
        result.update({
            "audio_present": True,
            "sample_rate_hz": 48_000,
            "channels": 2,
        })
    return result


class MusicPipelineIntegrationTests(unittest.TestCase):
    def _fixture(self, root: Path, *, wrong_sfx_input: bool = False):
        work = root / "work"
        outdir = root / "evidence"
        music_root = work / "typed-music-production"
        sfx_root = work / "typed-sfx-production"
        for path in (work, outdir, music_root, sfx_root):
            path.mkdir(exist_ok=True)
        base = work / "base-master.mp4"
        music = music_root / "music-output.mp4"
        sfx = sfx_root / "sfx-output.mp4"
        base.write_bytes(b"base-master")
        music.write_bytes(b"base-master+verified-project-music")
        sfx.write_bytes(b"base-master+verified-project-music+verified-sfx")
        base_music_binding = _binding(base, music=True)
        music_binding = _binding(music, music=True)
        sfx_binding = _binding(sfx, music=False)
        music_receipt = {
            "program_input": base_music_binding,
            "output": music_binding,
        }
        sfx_program = (
            {key: base_music_binding[key]
             for key in ("sha256", "bytes", "duration_ms")}
            if wrong_sfx_input else
            {key: music_binding[key]
             for key in ("sha256", "bytes", "duration_ms")}
        )
        sfx_receipt = {
            "program_input": sfx_program,
            "output": sfx_binding,
        }
        music_receipt_path = outdir / pipeline.MUSIC_PRODUCTION_RECEIPT_FILE
        sfx_receipt_path = outdir / pipeline.SFX_PRODUCTION_RECEIPT_FILE
        events: list[str] = []

        def execute_music(**kwargs):
            events.append("music_execute")
            self.assertEqual(Path(kwargs["program_path"]), base.resolve())
            music_receipt_path.write_bytes(
                (_canonical(music_receipt) + "\n").encode("ascii")
            )
            return {
                "executed": True, "output_path": str(music),
                "receipt": music_receipt,
                "receipt_path": str(music_receipt_path),
                "receipt_sha256": _digest(music_receipt),
            }

        def verify_music(receipt, **kwargs):
            events.append("music_verify")
            self.assertEqual(receipt, music_receipt)
            self.assertEqual(
                Path(kwargs["program_input_path"]), base.resolve()
            )
            self.assertEqual(Path(kwargs["output_path"]), music.resolve())
            return {
                "ok": True, "mode": "rendered", "region_count": 1,
                "policy_usage": "supporting", "policy_bound": True,
                "rights_verified": True,
                "dialogue_masking_verified": True,
                "loudness_verified": True,
                "receipt_sha256": _digest(music_receipt),
                "output_sha256": music_binding["sha256"], "note": "",
            }

        def execute_sfx(**kwargs):
            events.append("sfx_execute")
            self.assertEqual(Path(kwargs["program_path"]), music.resolve())
            sfx_receipt_path.write_bytes(
                (_canonical(sfx_receipt) + "\n").encode("ascii")
            )
            return {
                "executed": True, "output_path": str(sfx),
                "receipt": sfx_receipt,
                "receipt_path": str(sfx_receipt_path),
                "receipt_sha256": _digest(sfx_receipt),
            }

        def verify_sfx(receipt, **kwargs):
            events.append("sfx_verify")
            self.assertEqual(receipt, sfx_receipt)
            self.assertEqual(Path(kwargs["output_path"]), sfx.resolve())
            return {
                "ok": True, "mode": "rendered", "cue_count": 1,
                "policy_usage": "motivated_only", "policy_bound": True,
                "receipt_sha256": _digest(sfx_receipt),
                "output_sha256": sfx_binding["sha256"], "note": "",
            }

        return {
            "work": work, "outdir": outdir, "base": base,
            "music": music, "sfx": sfx, "events": events,
            "music_receipt": music_receipt,
            "sfx_receipt": sfx_receipt,
            "execute_music": execute_music, "verify_music": verify_music,
            "execute_sfx": execute_sfx, "verify_sfx": verify_sfx,
        }

    def _execute(self, fixture: dict):
        envelope = {
            "project_intent_sha256": "1" * 64,
            "edit_policy_sha256": "2" * 64,
        }
        patches = (
            mock.patch.object(
                pipeline, "execute_project_intent_music",
                side_effect=fixture["execute_music"]),
            mock.patch.object(
                pipeline, "verify_music_production_evidence",
                side_effect=fixture["verify_music"]),
            mock.patch.object(
                pipeline, "execute_project_intent_sfx",
                side_effect=fixture["execute_sfx"]),
            mock.patch.object(
                pipeline, "verify_sfx_production_evidence",
                side_effect=fixture["verify_sfx"]),
            mock.patch.object(
                pipeline, "canonical_music_production_receipt_json",
                side_effect=_canonical),
            mock.patch.object(
                pipeline, "canonical_sfx_production_receipt_json",
                side_effect=_canonical),
            mock.patch.object(
                pipeline, "music_production_receipt_sha256",
                side_effect=_digest),
            mock.patch.object(
                pipeline, "sfx_production_receipt_sha256",
                side_effect=_digest),
            mock.patch.object(
                pipeline.os, "replace",
                side_effect=AssertionError("governed chain must not replace")),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patches[5], patches[6], patches[7], patches[8]:
            return pipeline.execute_project_intent_audio_production_chain(
                base_master=fixture["base"],
                project_intent_envelope=envelope,
                project_intent_envelope_sha256="3" * 64,
                edl={}, rendered_graphics=[], rendered_broll=[],
                edit_boundaries_receipt={}, speech_words=[],
                work=fixture["work"], outdir=fixture["outdir"],
            )

    def test_verified_music_precedes_sfx_and_final_mix_binds_only_master(self):
        with tempfile.TemporaryDirectory(prefix="music-pipeline-chain-") as raw:
            fixture = self._fixture(Path(raw))
            result = self._execute(fixture)
            self.assertEqual(fixture["events"], [
                "music_execute", "music_verify", "sfx_execute", "sfx_verify",
            ])
            self.assertEqual(result["music_output"], fixture["music"].resolve())
            self.assertEqual(result["master"], fixture["sfx"].resolve())
            self.assertEqual(fixture["base"].read_bytes(), b"base-master")
            self.assertEqual(
                fixture["music"].read_bytes(),
                b"base-master+verified-project-music",
            )
            mix_path = fixture["outdir"] / "AUDIO_MIX_RECEIPT.json"
            with mock.patch.object(
                    pipeline, "_dur", return_value=4.0), mock.patch.object(
                    pipeline, "_audio_stream_receipt", return_value={
                        "codec": "aac", "sample_rate": 48_000, "channels": 2,
                    }):
                mix = pipeline.write_audio_mix_receipt(
                    result["master"], [], None, mix_path,
                )
            self.assertEqual(
                mix["master"]["sha256"],
                hashlib.sha256(fixture["sfx"].read_bytes()).hexdigest(),
            )
            self.assertEqual(mix["sfx"], [])
            self.assertIsNone(mix["music"])

    def test_noncanonical_music_receipt_stops_before_verifier_or_sfx(self):
        with tempfile.TemporaryDirectory(prefix="music-pipeline-tamper-") as raw:
            fixture = self._fixture(Path(raw))
            original = fixture["execute_music"]

            def tampered_execute(**kwargs):
                result = original(**kwargs)
                Path(result["receipt_path"]).write_bytes(
                    (_canonical(result["receipt"]) + " \n").encode("ascii")
                )
                return result

            fixture["execute_music"] = tampered_execute
            with self.assertRaisesRegex(RuntimeError, "changed after persistence"):
                self._execute(fixture)
            self.assertEqual(fixture["events"], ["music_execute"])

    def test_music_producer_cannot_mutate_the_composited_base_master(self):
        with tempfile.TemporaryDirectory(prefix="music-pipeline-input-") as raw:
            fixture = self._fixture(Path(raw))
            original = fixture["execute_music"]

            def mutating_execute(**kwargs):
                result = original(**kwargs)
                fixture["base"].write_bytes(b"mutated-base-master")
                return result

            fixture["execute_music"] = mutating_execute
            with self.assertRaisesRegex(RuntimeError, "immutable input"):
                self._execute(fixture)
            self.assertEqual(fixture["events"], ["music_execute"])

    def test_failed_independent_music_verifier_stops_before_sfx(self):
        with tempfile.TemporaryDirectory(prefix="music-pipeline-qa-") as raw:
            fixture = self._fixture(Path(raw))
            original = fixture["verify_music"]

            def failed_verify(receipt, **kwargs):
                evidence = original(receipt, **kwargs)
                evidence.update({
                    "ok": False,
                    "rights_verified": False,
                    "note": "rights evidence missing",
                })
                return evidence

            fixture["verify_music"] = failed_verify
            with self.assertRaisesRegex(RuntimeError, "rights evidence missing"):
                self._execute(fixture)
            self.assertEqual(fixture["events"], [
                "music_execute", "music_verify",
            ])

    def test_sfx_program_input_must_equal_verified_music_output(self):
        with tempfile.TemporaryDirectory(prefix="music-pipeline-order-") as raw:
            fixture = self._fixture(Path(raw), wrong_sfx_input=True)
            with self.assertRaisesRegex(
                    RuntimeError, "program input is not the verified music"):
                self._execute(fixture)
            self.assertEqual(fixture["events"], [
                "music_execute", "music_verify", "sfx_execute",
            ])


if __name__ == "__main__":
    unittest.main()
