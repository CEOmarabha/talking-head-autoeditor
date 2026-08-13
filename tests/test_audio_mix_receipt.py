from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autoeditor import pipeline


class AudioMixReceiptTests(unittest.TestCase):
    def test_receipt_binds_every_cue_music_and_mixed_master(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            master = root / "MASTER_16x9.mp4"
            cue = root / "boom.wav"
            music = root / "music.wav"
            master.write_bytes(b"mixed-master")
            cue.write_bytes(b"cue-bytes")
            music.write_bytes(b"music-bytes")
            plan = [(cue, 1.25, 0.45)]
            with mock.patch.object(pipeline, "_dur", return_value=8.0), \
                    mock.patch.object(pipeline, "_audio_stream_receipt",
                                      return_value={
                                          "codec": "aac",
                                          "sample_rate": 48000,
                                          "channels": 2,
                                      }):
                receipt = pipeline.build_audio_mix_receipt(
                    master, plan, music
                )
                check = pipeline.verify_audio_mix_receipt(
                    receipt, master, plan, music
                )
                cue.write_bytes(b"changed-cue")
                tampered = pipeline.verify_audio_mix_receipt(
                    receipt, master, plan, music
                )

        self.assertEqual(
            receipt["schema"], "autoeditor-audio-mix-receipt/v1"
        )
        self.assertTrue(receipt["mix_succeeded"])
        self.assertFalse(receipt["perceptual_quality_assessed"])
        self.assertEqual(receipt["master"]["audio"]["sample_rate"], 48000)
        self.assertEqual(len(receipt["sfx"]), 1)
        self.assertEqual(receipt["sfx"][0]["cue"], "boom")
        self.assertEqual(receipt["sfx"][0]["timestamp_seconds"], 1.25)
        self.assertIsNotNone(receipt["music"])
        self.assertTrue(check["ok"])
        self.assertEqual(check["planned_sfx"], 1)
        self.assertEqual(check["bound_sfx"], 1)
        self.assertFalse(tampered["ok"])

    def test_empty_sound_plan_is_explicitly_bound(self):
        with tempfile.TemporaryDirectory() as td:
            master = Path(td) / "MASTER_16x9.mp4"
            master.write_bytes(b"dialogue-only-master")
            with mock.patch.object(pipeline, "_dur", return_value=5.0), \
                    mock.patch.object(pipeline, "_audio_stream_receipt",
                                      return_value={
                                          "codec": "aac",
                                          "sample_rate": 48000,
                                          "channels": 2,
                                      }):
                receipt = pipeline.build_audio_mix_receipt(master, [], None)
                check = pipeline.verify_audio_mix_receipt(
                    receipt, master, [], None
                )

        self.assertEqual(receipt["sfx"], [])
        self.assertIsNone(receipt["music"])
        self.assertTrue(check["ok"])
        self.assertEqual(check["planned_sfx"], 0)

    def test_out_of_timeline_cue_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            master = root / "MASTER_16x9.mp4"
            cue = root / "boom.wav"
            master.write_bytes(b"mixed-master")
            cue.write_bytes(b"cue")
            with mock.patch.object(pipeline, "_dur", return_value=2.0), \
                    mock.patch.object(pipeline, "_audio_stream_receipt",
                                      return_value={
                                          "codec": "aac",
                                          "sample_rate": 48000,
                                          "channels": 2,
                                      }):
                with self.assertRaisesRegex(
                        RuntimeError, "bounded mix contract"):
                    pipeline.build_audio_mix_receipt(
                        master, [(cue, 2.0, 0.45)], None
                    )

    def test_pipeline_writes_temporal_receipts_for_desktop_qa(self):
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn('outdir / "AUDIO_MIX_RECEIPT.json"', source)
        self.assertIn('outdir / "EDIT_BOUNDARIES.json"', source)
        self.assertIn(
            'EDIT_BOUNDARIES_SCHEMA = "autoeditor-edit-boundaries/v1"',
            source,
        )
        self.assertIn('"removed_seconds": round(float(removed), 3)', source)
        self.assertIn("audio_mix_receipt=audio_mix_receipt", source)

    def test_caption_render_receipt_binds_exact_burned_events(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "CAPTION_RENDER_RECEIPT.json"
            receipt = pipeline.write_caption_render_receipt(
                {
                    "events": [
                        {"s": 0.0, "e": 0.9, "text": "Is now", "states": 2},
                        {"s": 0.95, "e": 1.8, "text": "a bad time?", "states": 3},
                    ]
                }, [], output, delivery_mode="burned", layout_safe=True,
                subject_clear=True, pixel_quality={"ok": True},
            )

        self.assertEqual(
            receipt["schema"], "autoeditor-caption-render-receipt/v1"
        )
        self.assertEqual(receipt["renderer"], "karaoke-band")
        self.assertEqual(receipt["events"][1]["text"], "a bad time?")
        self.assertEqual(receipt["events"][1]["state_count"], 3)

    def test_engine_artifact_contract_hash_binds_every_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = [
                "PSE_SHORT_9x16.mp4", "EDL.json", "PSE_CAPTIONS.srt",
                "CAPTION_RENDER_RECEIPT.json", "EDIT_BOUNDARIES.json",
                "AUDIO_MIX_RECEIPT.json",
            ]
            for index, name in enumerate(names):
                (root / name).write_bytes(f"artifact-{index}".encode())
            contract = pipeline.build_engine_artifact_contract(
                mode="premium-edl", delivery=root / names[0],
                final_file=root / names[0],
                edl=root / names[1], captions=root / names[2],
                caption_render=root / names[3],
                edit_boundaries=root / names[4], audio_mix=root / names[5],
            )

        self.assertEqual(
            contract["schema"],
            "autoeditor-engine-artifact-contract/v1",
        )
        self.assertEqual(contract["mode"], "premium-edl")
        self.assertEqual(contract["delivery"]["file"], names[0])
        self.assertEqual(
            contract["edl"]["sha256"],
            hashlib.sha256(b"artifact-1").hexdigest(),
        )
        self.assertEqual(
            set(contract), {
                "schema", "mode", "delivery", "edl", "captions",
                "caption_render", "edit_boundaries", "audio_mix",
            },
        )

    def test_pending_delivery_binds_the_intended_final_filename(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pending = root / "PSE_SHORT_9x16.UNVERIFIED.mp4"
            final = root / "PSE_SHORT_9x16.mp4"
            cuts = root / "cuts.json"
            mix = root / "mix.json"
            for path in (pending, cuts, mix):
                path.write_bytes(b"x")
            contract = pipeline.build_engine_artifact_contract(
                mode="generic-baseline", delivery=pending,
                final_file=final, edl=None, captions=None,
                caption_render=None, edit_boundaries=cuts, audio_mix=mix,
            )

        self.assertEqual(contract["delivery"]["file"], final.name)
        self.assertEqual(
            contract["delivery"]["sha256"], hashlib.sha256(b"x").hexdigest()
        )

    def test_baseline_contract_rejects_stale_edl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("video.mp4", "EDL.json", "cuts.json", "mix.json"):
                (root / name).write_bytes(b"x")
            with self.assertRaisesRegex(RuntimeError, "baseline"):
                pipeline.build_engine_artifact_contract(
                    mode="generic-baseline", delivery=root / "video.mp4",
                    edl=root / "EDL.json", captions=None,
                    caption_render=None, edit_boundaries=root / "cuts.json",
                    audio_mix=root / "mix.json",
                )

    def test_baseline_contract_explicitly_binds_no_edl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("video.mp4", "cuts.json", "mix.json"):
                (root / name).write_bytes(b"x")
            contract = pipeline.build_engine_artifact_contract(
                mode="generic-baseline", delivery=root / "video.mp4",
                edl=None, captions=None, caption_render=None,
                edit_boundaries=root / "cuts.json",
                audio_mix=root / "mix.json",
            )

        self.assertEqual(contract["mode"], "generic-baseline")
        self.assertIsNone(contract["edl"])
        self.assertIsNone(contract["captions"])
        self.assertIsNone(contract["caption_render"])

    def test_packaged_engine_leaves_final_naming_to_desktop_vision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pending = root / "video.UNVERIFIED.mp4"
            final = root / "video.mp4"
            pending.write_bytes(b"engine-verified")
            outputs, deferred = pipeline.release_engine_verified_outputs(
                {"9x16": pending}, {"9x16": final},
                packaged_desktop=True,
            )
            self.assertTrue(deferred)
            self.assertEqual(outputs["9x16"], pending)
            self.assertTrue(pending.exists())
            self.assertFalse(final.exists())

            outputs, deferred = pipeline.release_engine_verified_outputs(
                {"9x16": pending}, {"9x16": final},
                packaged_desktop=False,
            )
            self.assertFalse(deferred)
            self.assertEqual(outputs["9x16"], final)
            self.assertFalse(pending.exists())
            self.assertTrue(final.exists())


if __name__ == "__main__":
    unittest.main()
