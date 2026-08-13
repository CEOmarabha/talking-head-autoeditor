"""PyInstaller entry point for the frozen AutoEditor engine.

The desktop app spawns this binary with the same CLI as
`python -m autoeditor`. Keeping the entry file separate from the package
lets PyInstaller resolve imports cleanly.
"""
from __future__ import annotations

import array
import hashlib
import importlib
import json
import math
import multiprocessing
import os
import sys
import tempfile
import wave
from pathlib import Path


def _model(name: str) -> str:
    """Use installer-bundled ASR weights when present, never redownload."""
    return os.environ.get(f"AUTOEDITOR_WHISPER_{name.upper()}", name)


def _asr_words(media: str, output: str) -> None:
    from autoeditor.asr import create_model, transcribe

    model = create_model(_model("small"), device="cpu", compute_type="int8")
    segments, _ = transcribe(model, media, word_timestamps=True)
    words = [
        {
            "w": word.word.strip(),
            "s": round(word.start, 3),
            "e": round(word.end, 3),
            "p": round(word.probability, 2),
        }
        for segment in segments
        for word in (segment.words or [])
    ]
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(words, handle)


def _asr_secondary(media: str, output: str) -> None:
    from autoeditor.asr import create_model, transcribe

    model = create_model(_model("medium"), device="cpu", compute_type="int8")
    segments, _ = transcribe(
        model, media,
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    text = " ".join(segment.text.strip() for segment in segments)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump({"text": text}, handle)


def _self_test() -> int:
    """Prove required native backends survived the PyInstaller freeze."""
    required = (
        "ctranslate2", "faster_whisper", "huggingface_hub",
        "numpy", "onnxruntime", "PIL", "tokenizers", "tqdm",
    )
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    checks["utf8_mode"] = (
        not getattr(sys, "frozen", False) or sys.flags.utf8_mode == 1
    )
    if not checks["utf8_mode"]:
        errors["utf8_mode"] = "frozen Python did not start with -X utf8"
    try:
        from autoeditor import asr

        checks["ffmpeg_audio_decoder"] = asr.decoder_contract_check()
        checks["pyav_not_bundled"] = asr.pyav_payload_absent()
        if not checks["ffmpeg_audio_decoder"]:
            errors["ffmpeg_audio_decoder"] = "decoder shim contract failed"
        if not checks["pyav_not_bundled"]:
            errors["pyav_not_bundled"] = (
                "PyAV package or native libraries were found in frozen engine"
            )
    except Exception as exc:
        checks["ffmpeg_audio_decoder"] = False
        checks["pyav_not_bundled"] = False
        errors["ffmpeg_audio_decoder"] = type(exc).__name__
        errors["pyav_not_bundled"] = type(exc).__name__
    for name in required:
        try:
            importlib.import_module(name)
            checks[name] = True
        except Exception as exc:  # pragma: no cover - exercised frozen in CI
            checks[name] = False
            errors[name] = type(exc).__name__
    try:
        from autoeditor.pipeline import low_speech_cutter_self_test

        checks["in_process_low_speech_cutter"] = bool(
            low_speech_cutter_self_test()
        )
        if not checks["in_process_low_speech_cutter"]:
            errors["in_process_low_speech_cutter"] = "contract returned false"
    except Exception as exc:  # pragma: no cover - exercised frozen in CI
        checks["in_process_low_speech_cutter"] = False
        errors["in_process_low_speech_cutter"] = type(exc).__name__
    try:
        from autoeditor import creative_contract

        contract_hash = creative_contract.contract_sha256()
        checks["creative_contract_sha256"] = (
            isinstance(contract_hash, str)
            and len(contract_hash) == 64
            and all(
                character in "0123456789abcdef"
                for character in contract_hash
            )
        )
        if not checks["creative_contract_sha256"]:
            errors["creative_contract_sha256"] = (
                "contract returned invalid hash"
            )
    except Exception as exc:  # pragma: no cover - exercised frozen in CI
        checks["creative_contract_sha256"] = False
        errors["creative_contract_sha256"] = type(exc).__name__
    print(json.dumps({"event": "autoeditor-engine-self-test",
                      "checks": checks, "errors": errors}, sort_keys=True))
    return 0 if all(checks.values()) else 1


def _audio_decoder_self_test() -> int:
    """Exercise the frozen FFmpeg waveform decoder against real PCM input."""
    from autoeditor.asr import decode_audio

    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    try:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "tone.wav"
            samples = array.array(
                "h",
                (
                    round(12_000 * math.sin(2 * math.pi * 440 * i / 16_000))
                    for i in range(16_000)
                ),
            )
            with wave.open(str(source), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(samples.tobytes())
            decoded = decode_audio(source)
            checks["ffmpeg_waveform_decode"] = (
                decoded.dtype.name == "float32"
                and 15_900 <= decoded.size <= 16_100
                and bool((abs(decoded) > 0.1).any())
            )
            if not checks["ffmpeg_waveform_decode"]:
                errors["ffmpeg_waveform_decode"] = "unexpected PCM output"
    except Exception as exc:
        checks["ffmpeg_waveform_decode"] = False
        errors["ffmpeg_waveform_decode"] = type(exc).__name__
    print(json.dumps({"event": "autoeditor-engine-media-self-test",
                      "checks": checks, "errors": errors}, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def _artifact_receipt_self_test(
        delivery: str, final_file: str, output_dir: str) -> int:
    """Exercise production engine receipt builders without ASR or vision."""
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    try:
        from autoeditor.pipeline import write_artifact_receipt_probe

        result = write_artifact_receipt_probe(
            Path(delivery), Path(final_file), Path(output_dir)
        )
        checks["production_artifact_receipts"] = all(
            Path(result[key]).is_file()
            for key in ("qa_report", "edit_boundaries", "audio_mix")
        )
        checks["artifact_identity"] = (
            isinstance(result.get("artifact_sha256"), str)
            and len(result["artifact_sha256"]) == 64
            and isinstance(result.get("artifact_bytes"), int)
            and result["artifact_bytes"] > 0
        )
    except Exception as exc:
        checks["production_artifact_receipts"] = False
        checks["artifact_identity"] = False
        errors["artifact_receipts"] = type(exc).__name__
    print(json.dumps({
        "event": "autoeditor-engine-artifact-receipt-self-test",
        "checks": checks,
        "errors": errors,
    }, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def _caption_render_self_test(
        source: str, output: str, output_dir: str) -> int:
    """Burn a fixed-word production caption fixture without ASR or vision."""
    check_names = (
        "bundled_worksans",
        "production_caption_band",
        "production_caption_receipt",
        "burned_timed_pixel_evidence",
    )
    checks = {name: False for name in check_names}
    errors: dict[str, str] = {}
    result_receipt = None
    try:
        from autoeditor.pipeline import write_caption_render_probe

        font_root = os.environ.get("AUTOEDITOR_BUNDLED_FONTS", "")
        if not font_root or not Path(font_root).is_absolute():
            raise RuntimeError("bundled caption font root is unavailable")
        font_file = Path(font_root) / "WorkSans-Variable.ttf"
        checks["bundled_worksans"] = (
            font_file.is_file()
            and font_file.stat().st_size >= 100_000
        )
        if not checks["bundled_worksans"]:
            raise RuntimeError("bundled WorkSans caption font is unavailable")
        result = write_caption_render_probe(
            Path(source), Path(output), Path(output_dir), font_file
        )
        checks["production_caption_band"] = (
            result.get("duration_ms") == 2000
            and result.get("width") == 180
            and result.get("height") == 320
            and result.get("fps_milli") == 30000
        )
        checks["production_caption_receipt"] = (
            Path(result["caption_receipt"]).is_file()
            and result.get("caption_receipt_bytes", 0) > 0
            and len(str(result.get("caption_receipt_sha256", ""))) == 64
        )
        pixel_evidence = result.get("pixel_evidence") or {}
        checks["burned_timed_pixel_evidence"] = (
            set(pixel_evidence.get("frame_sha256") or {})
            == {"blank_before", "word_cut", "word_it", "word_now",
                "blank_after"}
            and len(set(pixel_evidence["frame_sha256"].values())) >= 4
        )
        result_receipt = {
            "artifact": {
                "file": Path(result["output"]).name,
                "sha256": result["output_sha256"],
                "bytes": result["output_bytes"],
                "duration_ms": result["duration_ms"],
                "width": result["width"],
                "height": result["height"],
                "fps_milli": result["fps_milli"],
            },
            "caption_receipt": {
                "file": Path(result["caption_receipt"]).name,
                "sha256": result["caption_receipt_sha256"],
                "bytes": result["caption_receipt_bytes"],
            },
            "font": {
                "file": font_file.name,
                "sha256": result["font_sha256"],
                "bytes": result["font_bytes"],
            },
            "overlay": {
                "caption_y": result["caption_y"],
                "band_height": result["band_height"],
                "pixel_evidence": pixel_evidence,
            },
        }
    except Exception as exc:
        errors["caption_render"] = type(exc).__name__
    print(json.dumps({
        "event": "autoeditor-engine-caption-render-self-test",
        "schema_version": "autoeditor-engine-caption-render-self-test/v1",
        "checks": checks,
        "errors": errors,
        "result": result_receipt,
    }, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def _sfx_production_self_test(
        source: str, output: str, work_dir: str) -> int:
    """Execute the fixed production SFX path and its independent verifier."""
    check_names = (
        "decoded_cue_placement", "independent_evidence_verifier",
        "production_sfx_planner", "production_sfx_renderer",
        "project_generated_rights", "tamper_rejected",
    )
    checks = {name: False for name in check_names}
    errors: dict[str, str] = {}
    result_receipt = None
    schema_version = "autoeditor-sfx-production-self-test/v1"
    try:
        from autoeditor.sfx_production import write_sfx_production_probe

        ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "")
        ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "")
        if (not ffmpeg or not ffprobe
                or not Path(ffmpeg).is_absolute()
                or not Path(ffprobe).is_absolute()):
            raise RuntimeError("bundled SFX media tools are unavailable")
        result = write_sfx_production_probe(
            source, output, work_dir, ffmpeg, ffprobe
        )
        if result.get("schema_version") != schema_version:
            raise RuntimeError("SFX production probe schema drifted")
        measured_checks = result.get("checks")
        if (not isinstance(measured_checks, dict)
                or set(measured_checks) != set(check_names)
                or any(value is not True
                       for value in measured_checks.values())):
            raise RuntimeError("SFX production probe checks did not pass")
        checks = dict(measured_checks)
        result_receipt = {
            "artifact": result["artifact"],
            "production_receipt": result["production_receipt"],
            "decoded_placement": result["decoded_placement"],
            "evidence": result["evidence"],
        }
    except Exception as exc:
        errors["sfx_production"] = type(exc).__name__
    print(json.dumps({
        "event": "autoeditor-engine-sfx-production-self-test",
        "schema_version": schema_version,
        "checks": checks,
        "errors": errors,
        "result": result_receipt,
    }, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def _music_production_self_test(
        source: str, output: str, work_dir: str) -> int:
    """Execute the fixed project-owned music path and independent verifier."""
    check_names = (
        "decoded_music_placement", "dialogue_masking",
        "independent_evidence_verifier", "measured_loudness",
        "omission_rejected", "production_music_planner",
        "production_music_renderer", "project_generated_rights",
        "tamper_rejected",
    )
    checks = {name: False for name in check_names}
    errors: dict[str, str] = {}
    result_receipt = None
    schema_version = "autoeditor-music-production-self-test/v1"
    try:
        from autoeditor.music_production import write_music_production_probe

        ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "")
        ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "")
        if (not ffmpeg or not ffprobe
                or not Path(ffmpeg).is_absolute()
                or not Path(ffprobe).is_absolute()):
            raise RuntimeError("bundled music media tools are unavailable")
        result = write_music_production_probe(
            source, output, work_dir, ffmpeg, ffprobe
        )
        expected_result_keys = {
            "schema_version", "checks", "artifact", "production_receipt",
            "decoded_placement", "measured_audio", "evidence",
        }
        if (not isinstance(result, dict)
                or set(result) != expected_result_keys
                or result.get("schema_version") != schema_version):
            raise RuntimeError("music production probe schema drifted")
        measured_checks = result.get("checks")
        if (not isinstance(measured_checks, dict)
                or set(measured_checks) != set(check_names)
                or any(value is not True
                       for value in measured_checks.values())):
            raise RuntimeError("music production probe checks did not pass")
        checks = dict(measured_checks)
        result_receipt = {
            "artifact": result["artifact"],
            "production_receipt": result["production_receipt"],
            "decoded_placement": result["decoded_placement"],
            "measured_audio": result["measured_audio"],
            "evidence": result["evidence"],
        }
    except Exception as exc:
        errors["music_production"] = type(exc).__name__
    print(json.dumps({
        "event": "autoeditor-engine-music-production-self-test",
        "schema_version": schema_version,
        "checks": checks,
        "errors": errors,
        "result": result_receipt,
    }, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def _asr_capability_self_test(output: str, work_dir: str) -> int:
    """Exercise bundled offline ASR and persist its canonical probe receipt."""
    check_names = (
        "expected_transcript", "fixture_identity", "model_identity",
        "offline_small_model", "ordered_word_timestamps", "production_asr",
    )
    checks = {name: False for name in check_names}
    errors: dict[str, str] = {}
    result_receipt = None
    schema_version = "autoeditor-asr-runtime-probe/v1"
    try:
        ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "")
        if not ffmpeg or not Path(ffmpeg).is_absolute():
            raise RuntimeError("bundled ASR FFmpeg is unavailable")
        from autoeditor.asr_runtime_probe import (
            ASR_RUNTIME_PROBE_EXPECTED_TERMS,
            ASR_RUNTIME_PROBE_FIXTURE_BYTES,
            ASR_RUNTIME_PROBE_FIXTURE_NAME,
            ASR_RUNTIME_PROBE_FIXTURE_SHA256,
            ASR_RUNTIME_PROBE_RECEIPT_FILE,
            ASR_RUNTIME_PROBE_SOURCE_REVISION,
            run_asr_runtime_probe,
        )

        result = run_asr_runtime_probe(
            output_path=output,
            work_dir=work_dir,
            model_path=_model("small"),
            ffmpeg_path=ffmpeg,
        )
        if (not isinstance(result, dict)
                or set(result) != {
                    "schema_version", "checks", "fixture", "model",
                    "transcript", "words", "receipt",
                }
                or result.get("schema_version") != schema_version):
            raise RuntimeError("ASR runtime probe schema drifted")
        measured_checks = result.get("checks")
        if (not isinstance(measured_checks, dict)
                or set(measured_checks) != set(check_names)
                or any(value is not True
                       for value in measured_checks.values())):
            raise RuntimeError("ASR runtime probe checks did not pass")
        fixture = result["fixture"]
        if (not isinstance(fixture, dict)
                or set(fixture) != {
                    "name", "sha256", "bytes", "source_revision",
                }
                or fixture != {
                    "name": ASR_RUNTIME_PROBE_FIXTURE_NAME,
                    "sha256": ASR_RUNTIME_PROBE_FIXTURE_SHA256,
                    "bytes": ASR_RUNTIME_PROBE_FIXTURE_BYTES,
                    "source_revision": ASR_RUNTIME_PROBE_SOURCE_REVISION,
                }):
            raise RuntimeError("ASR runtime probe fixture identity drifted")
        model = result["model"]
        if (not isinstance(model, dict)
                or set(model) != {"name", "tree_sha256", "bytes", "files"}
                or model.get("name") != "faster-whisper-small"
                or not isinstance(model.get("tree_sha256"), str)
                or len(model["tree_sha256"]) != 64
                or any(character not in "0123456789abcdef"
                       for character in model["tree_sha256"])
                or type(model.get("bytes")) is not int or model["bytes"] < 1
                or type(model.get("files")) is not int
                or not 1 <= model["files"] <= 64):
            raise RuntimeError("ASR runtime probe model identity drifted")
        transcript = result["transcript"]
        if (not isinstance(transcript, dict)
                or set(transcript) != {"language", "text", "normalized_text"}
                or transcript.get("language") != "en"
                or not isinstance(transcript.get("text"), str)
                or not transcript["text"].strip()
                or not isinstance(transcript.get("normalized_text"), str)
                or not transcript["normalized_text"].strip()):
            raise RuntimeError("ASR runtime probe transcript drifted")
        words = result["words"]
        if not isinstance(words, list) or not words or len(words) > 128:
            raise RuntimeError("ASR runtime probe words drifted")
        normalized_words = []
        prior_end = 0
        for word in words:
            if (not isinstance(word, dict)
                    or set(word) != {
                        "text", "start_ms", "end_ms",
                        "probability_millionths",
                    }
                    or not isinstance(word.get("text"), str)
                    or not word["text"].strip()
                    or type(word.get("start_ms")) is not int
                    or type(word.get("end_ms")) is not int
                    or word["start_ms"] < prior_end
                    or not word["start_ms"] < word["end_ms"] <= 10_000
                    or type(word.get("probability_millionths")) is not int
                    or not 0 <= word["probability_millionths"] <= 1_000_000):
                raise RuntimeError("ASR runtime probe word timestamp drifted")
            normalized_words.append("".join(
                character for character in word["text"].strip().casefold()
                if character.isascii() and (
                    character.isalnum() or character == "'"
                )
            ))
            prior_end = word["end_ms"]
        cursor = 0
        for term in ASR_RUNTIME_PROBE_EXPECTED_TERMS:
            try:
                cursor = normalized_words.index(term, cursor) + 1
            except ValueError as error:
                raise RuntimeError(
                    "ASR runtime probe expected transcript drifted"
                ) from error
        receipt = result["receipt"]
        output_file = Path(output).resolve()
        if (not isinstance(receipt, dict)
                or set(receipt) != {"file", "sha256", "bytes"}
                or receipt.get("file") != ASR_RUNTIME_PROBE_RECEIPT_FILE
                or output_file.name != receipt["file"]
                or not output_file.is_file()
                or type(receipt.get("bytes")) is not int
                or receipt["bytes"] != output_file.stat().st_size
                or not isinstance(receipt.get("sha256"), str)
                or hashlib.sha256(output_file.read_bytes()).hexdigest()
                    != receipt["sha256"]):
            raise RuntimeError("ASR runtime probe receipt binding drifted")
        receipt_contract = {
            "schema_version": schema_version,
            "checks": measured_checks,
            "fixture": fixture,
            "model": model,
            "transcript": transcript,
            "words": words,
        }
        expected_receipt_bytes = (
            json.dumps(
                receipt_contract, ensure_ascii=True, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ) + "\n"
        ).encode("ascii")
        if output_file.read_bytes() != expected_receipt_bytes:
            raise RuntimeError("ASR runtime probe receipt was not canonical")
        checks = {name: measured_checks[name] for name in check_names}
        result_receipt = {
            "fixture": fixture,
            "model": model,
            "transcript": transcript,
            "words": words,
            "receipt": receipt,
        }
    except Exception as exc:
        errors["asr_runtime_probe"] = type(exc).__name__
    print(json.dumps({
        "event": "autoeditor-engine-asr-capability-self-test",
        "schema_version": schema_version,
        "checks": checks,
        "errors": errors,
        "result": result_receipt,
    }, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def _render_capability_self_test(output: str, work_dir: str) -> int:
    """Exercise fixed production color, video, audio, and motion evidence."""
    check_names = (
        "audio_crossfades",
        "color_normalization",
        "cross_dissolves",
        "motion_quality_analysis",
    )
    checks = {name: False for name in check_names}
    errors: dict[str, str] = {}
    result_receipt = None
    schema_version = "autoeditor-render-capability-runtime-probe/v1"
    try:
        ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "")
        ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "")
        if (not ffmpeg or not Path(ffmpeg).is_absolute()
                or not ffprobe or not Path(ffprobe).is_absolute()):
            raise RuntimeError(
                "bundled render-capability media tool identities are unavailable"
            )
        from autoeditor.render_capability_runtime_probe import (
            RENDER_CAPABILITY_RUNTIME_PROBE_EVENT,
            RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE,
            RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION,
            run_render_capability_runtime_probe,
            verify_render_capability_runtime_probe_receipt,
        )

        if (RENDER_CAPABILITY_RUNTIME_PROBE_EVENT
                != "autoeditor-engine-render-capability-self-test"
                or RENDER_CAPABILITY_RUNTIME_PROBE_SCHEMA_VERSION
                != schema_version):
            raise RuntimeError("render capability event contract drifted")
        result = run_render_capability_runtime_probe(
            output_path=output,
            work_dir=work_dir,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
        )
        result_keys = {
            "schema_version", "checks", "scope", "fixture", "runtime",
            "production", "artifact", "evidence", "receipt",
        }
        if (not isinstance(result, dict)
                or set(result) != result_keys
                or result.get("schema_version") != schema_version):
            raise RuntimeError("render capability runtime probe schema drifted")
        measured_checks = result.get("checks")
        if (not isinstance(measured_checks, dict)
                or set(measured_checks) != set(check_names)
                or any(value is not True
                       for value in measured_checks.values())):
            raise RuntimeError(
                "render capability runtime probe checks did not pass"
            )

        receipt = result.get("receipt")
        output_file = Path(output).resolve()
        if (not isinstance(receipt, dict)
                or set(receipt) != {"file", "sha256", "bytes"}
                or receipt.get("file")
                    != RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT_FILE
                or output_file.name != receipt["file"]
                or not output_file.is_file()
                or type(receipt.get("bytes")) is not int
                or receipt["bytes"] != output_file.stat().st_size
                or not isinstance(receipt.get("sha256"), str)
                or len(receipt["sha256"]) != 64
                or any(character not in "0123456789abcdef"
                       for character in receipt["sha256"])
                or hashlib.sha256(output_file.read_bytes()).hexdigest()
                    != receipt["sha256"]):
            raise RuntimeError(
                "render capability runtime probe receipt binding drifted"
            )
        verified = verify_render_capability_runtime_probe_receipt(
            output_file.read_bytes(), receipt["sha256"]
        )
        receipt_contract = {
            key: result[key]
            for key in (
                "schema_version", "checks", "scope", "fixture", "runtime",
                "production", "artifact", "evidence",
            )
        }
        if verified != receipt_contract:
            raise RuntimeError(
                "render capability runtime probe receipt content drifted"
            )
        checks = {name: measured_checks[name] for name in check_names}
        result_receipt = {
            key: result[key]
            for key in (
                "scope", "fixture", "runtime", "production", "artifact",
                "evidence", "receipt",
            )
        }
    except Exception as exc:
        errors["render_capability_runtime_probe"] = type(exc).__name__
    print(json.dumps({
        "event": "autoeditor-engine-render-capability-self-test",
        "schema_version": schema_version,
        "checks": checks,
        "errors": errors,
        "result": result_receipt,
    }, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def _dialogue_cleanup_capability_self_test(output: str, work_dir: str) -> int:
    """Exercise the fixed offline retake cleanup and its delivery QA gate."""
    check_names = (
        "artifact_identity",
        "expected_single_take_after",
        "false_start_detector",
        "fixture_identity",
        "frame_sample_accurate_av_cut",
        "model_identity",
        "no_retake_residue",
        "normalized_av_before_after",
        "offline_small_model",
        "production_asr_before_after",
        "production_dialogue_pipeline",
        "repeated_take_detected",
        "tool_identity",
        "word_safe_kept_take_boundary",
    )
    checks = {name: False for name in check_names}
    errors: dict[str, str] = {}
    result_receipt = None
    schema_version = "autoeditor-dialogue-cleanup-runtime-probe/v1"
    try:
        ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "")
        ffprobe = os.environ.get("AUTOEDITOR_FFPROBE", "")
        model_path = _model("small")
        if (not ffmpeg or not Path(ffmpeg).is_absolute()
                or not ffprobe or not Path(ffprobe).is_absolute()
                or not model_path or not Path(model_path).is_absolute()):
            raise RuntimeError(
                "bundled dialogue-cleanup runtime identities are unavailable"
            )
        from autoeditor.asr_runtime_probe import (
            ASR_RUNTIME_PROBE_FIXTURE_BYTES,
            ASR_RUNTIME_PROBE_FIXTURE_NAME,
            ASR_RUNTIME_PROBE_FIXTURE_SHA256,
            ASR_RUNTIME_PROBE_SOURCE_REVISION,
        )
        from autoeditor.dialogue_cleanup_runtime_probe import (
            DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE,
            DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE,
            run_dialogue_cleanup_runtime_probe,
        )

        result = run_dialogue_cleanup_runtime_probe(
            output_path=output,
            work_dir=work_dir,
            model_path=model_path,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
        )
        result_keys = {
            "schema_version", "checks", "scope", "fixture", "runtime",
            "production_functions", "detectors", "transcripts", "edit",
            "media", "receipt",
        }
        if (not isinstance(result, dict)
                or set(result) != result_keys
                or result.get("schema_version") != schema_version):
            raise RuntimeError("dialogue-cleanup runtime probe schema drifted")
        measured_checks = result.get("checks")
        if (not isinstance(measured_checks, dict)
                or set(measured_checks) != set(check_names)
                or any(value is not True
                       for value in measured_checks.values())):
            raise RuntimeError(
                "dialogue-cleanup runtime probe checks did not pass"
            )

        scope = result.get("scope")
        expected_scope = {
            "certified": [
                "repeated_take_detection",
                "false_start_detection",
                "frame_sample_accurate_av_cut",
                "post_render_retake_residue_gate",
            ],
            "not_certified": [
                "cough_classification",
                "dead_air_policy_quality",
                "garbled_speech_semantics",
                "general_asr_accuracy",
            ],
        }
        if scope != expected_scope:
            raise RuntimeError("dialogue-cleanup capability scope drifted")

        def valid_sha256(value: object) -> bool:
            return (
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
            )

        def valid_identity(value: object) -> bool:
            return (
                isinstance(value, dict)
                and set(value) == {"sha256", "bytes"}
                and valid_sha256(value.get("sha256"))
                and type(value.get("bytes")) is int
                and value["bytes"] > 0
            )

        fixture = result.get("fixture")
        if (not isinstance(fixture, dict)
                or set(fixture) != {
                    "name", "sha256", "bytes", "source_revision",
                    "take_count", "pause_ms", "filter_graph_sha256",
                    "false_start_timeline_sha256",
                }
                or fixture.get("name") != ASR_RUNTIME_PROBE_FIXTURE_NAME
                or fixture.get("sha256") != ASR_RUNTIME_PROBE_FIXTURE_SHA256
                or fixture.get("bytes") != ASR_RUNTIME_PROBE_FIXTURE_BYTES
                or fixture.get("source_revision")
                    != ASR_RUNTIME_PROBE_SOURCE_REVISION
                or fixture.get("take_count") != 2
                or fixture.get("pause_ms") != 500
                or not valid_sha256(fixture.get("filter_graph_sha256"))
                or not valid_sha256(
                    fixture.get("false_start_timeline_sha256"))):
            raise RuntimeError(
                "dialogue-cleanup runtime probe fixture identity drifted"
            )

        runtime = result.get("runtime")
        if not isinstance(runtime, dict) or set(runtime) != {"model", "tools"}:
            raise RuntimeError("dialogue-cleanup runtime identity drifted")
        model = runtime.get("model")
        if (not isinstance(model, dict)
                or set(model) != {"name", "tree_sha256", "bytes", "files"}
                or model.get("name") != "faster-whisper-small"
                or not valid_sha256(model.get("tree_sha256"))
                or type(model.get("bytes")) is not int
                or model["bytes"] < 1
                or type(model.get("files")) is not int
                or not 1 <= model["files"] <= 64):
            raise RuntimeError("dialogue-cleanup model identity drifted")
        tools = runtime.get("tools")
        if (not isinstance(tools, dict)
                or set(tools) != {"ffmpeg", "ffprobe"}
                or not all(valid_identity(tools.get(name))
                           for name in ("ffmpeg", "ffprobe"))):
            raise RuntimeError("dialogue-cleanup tool identity drifted")

        expected_functions = [
            "autoeditor.asr.create_model",
            "autoeditor.asr.transcribe",
            "autoeditor.pipeline.detect_retakes",
            "autoeditor.pipeline.detect_false_starts",
            "autoeditor.pipeline.apply_cuts",
            "autoeditor.pipeline.verify_no_retakes",
        ]
        if result.get("production_functions") != expected_functions:
            raise RuntimeError(
                "dialogue-cleanup production function binding drifted"
            )

        detectors = result.get("detectors")
        if (not isinstance(detectors, dict)
                or set(detectors) != {"retake", "false_start"}):
            raise RuntimeError("dialogue-cleanup detector result drifted")

        def one_cut(value: object, prefix: str) -> dict:
            if (not isinstance(value, dict) or set(value) != {"cuts"}
                    or not isinstance(value.get("cuts"), list)
                    or len(value["cuts"]) != 1):
                raise RuntimeError("dialogue-cleanup detector cut drifted")
            cut = value["cuts"][0]
            if (not isinstance(cut, dict)
                    or set(cut) != {"start_ms", "end_ms", "why"}
                    or type(cut.get("start_ms")) is not int
                    or type(cut.get("end_ms")) is not int
                    or not 0 <= cut["start_ms"] < cut["end_ms"] <= 5_500
                    or not isinstance(cut.get("why"), str)
                    or not cut["why"].startswith(prefix)):
                raise RuntimeError("dialogue-cleanup detector cut drifted")
            return cut

        retake_cut = one_cut(detectors["retake"], "retake (")
        one_cut(detectors["false_start"], "false start (")

        expected_take = " ".join(DIALOGUE_CLEANUP_RUNTIME_PROBE_EXPECTED_TAKE)
        transcripts = result.get("transcripts")
        if (not isinstance(transcripts, dict)
                or set(transcripts) != {"before", "after"}):
            raise RuntimeError("dialogue-cleanup transcript result drifted")

        def valid_transcript(
                value: object, text: str, takes: int, words: int) -> bool:
            return (
                isinstance(value, dict)
                and set(value) == {
                    "normalized_text", "take_count", "word_count",
                    "word_timing_sha256",
                }
                and value.get("normalized_text") == text
                and value.get("take_count") == takes
                and value.get("word_count") == words
                and valid_sha256(value.get("word_timing_sha256"))
            )

        if (not valid_transcript(
                    transcripts["before"],
                    f"{expected_take} {expected_take}", 2, 10)
                or not valid_transcript(
                    transcripts["after"], expected_take, 1, 5)):
            raise RuntimeError("dialogue-cleanup transcript result drifted")

        edit = result.get("edit")
        if (not isinstance(edit, dict)
                or set(edit) != {
                    "start_frame", "end_frame", "removed_frames",
                    "removed_ms", "kept_take_start_ms", "cut_end_ms",
                    "gap_before_kept_take_ms",
                }
                or any(type(edit.get(name)) is not int for name in edit)
                or not 0 <= edit["start_frame"] < edit["end_frame"] <= 165
                or edit["removed_frames"]
                    != edit["end_frame"] - edit["start_frame"]
                or edit["removed_frames"] < 60
                or edit["removed_ms"]
                    != round(edit["removed_frames"] * 1000 / 30)
                or edit["cut_end_ms"] != retake_cut["end_ms"]
                or edit["gap_before_kept_take_ms"]
                    != edit["kept_take_start_ms"] - edit["cut_end_ms"]
                or not 30 <= edit["gap_before_kept_take_ms"] <= 250):
            raise RuntimeError("dialogue-cleanup edit result drifted")

        media = result.get("media")
        if (not isinstance(media, dict) or set(media) != {"source", "edited"}):
            raise RuntimeError("dialogue-cleanup media result drifted")

        def valid_media(value: object) -> bool:
            if (not isinstance(value, dict)
                    or set(value) != {
                        "sha256", "bytes", "video", "audio",
                        "av_duration_drift_ms",
                    }
                    or not valid_sha256(value.get("sha256"))
                    or type(value.get("bytes")) is not int
                    or value["bytes"] < 1
                    or type(value.get("av_duration_drift_ms")) is not int
                    or not 0 <= value["av_duration_drift_ms"] <= 34):
                return False
            video = value.get("video")
            audio = value.get("audio")
            return (
                isinstance(video, dict)
                and set(video) == {
                    "codec", "width", "height", "pixel_format", "fps",
                    "frames", "duration_ms",
                }
                and video.get("codec") == "h264"
                and video.get("width") == 320
                and video.get("height") == 180
                and video.get("pixel_format") == "yuv420p"
                and video.get("fps") == 30
                and type(video.get("frames")) is int
                and video["frames"] > 0
                and type(video.get("duration_ms")) is int
                and video["duration_ms"] > 0
                and isinstance(audio, dict)
                and set(audio) == {
                    "codec", "sample_rate", "channels", "duration_ms",
                }
                and audio.get("codec") == "aac"
                and audio.get("sample_rate") == 48_000
                and audio.get("channels") == 2
                and type(audio.get("duration_ms")) is int
                and audio["duration_ms"] > 0
                and abs(video["duration_ms"] - audio["duration_ms"])
                    == value["av_duration_drift_ms"]
            )

        source_media = media["source"]
        edited_media = media["edited"]
        if (not valid_media(source_media) or not valid_media(edited_media)
                or source_media["video"]["frames"] != 165
                or source_media["video"]["duration_ms"] != 5_500
                or edited_media["video"]["frames"]
                    != 165 - edit["removed_frames"]
                or abs(
                    (5_500 - edited_media["video"]["duration_ms"])
                    - edit["removed_ms"]
                ) > 34):
            raise RuntimeError("dialogue-cleanup media result drifted")

        receipt = result.get("receipt")
        output_file = Path(output).resolve()
        if (not isinstance(receipt, dict)
                or set(receipt) != {"file", "sha256", "bytes"}
                or receipt.get("file")
                    != DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT_FILE
                or output_file.name != receipt["file"]
                or not output_file.is_file()
                or type(receipt.get("bytes")) is not int
                or receipt["bytes"] != output_file.stat().st_size
                or not valid_sha256(receipt.get("sha256"))
                or hashlib.sha256(output_file.read_bytes()).hexdigest()
                    != receipt["sha256"]):
            raise RuntimeError(
                "dialogue-cleanup runtime probe receipt binding drifted"
            )
        receipt_contract = {
            key: result[key]
            for key in (
                "schema_version", "checks", "scope", "fixture", "runtime",
                "production_functions", "detectors", "transcripts", "edit",
                "media",
            )
        }
        expected_receipt_bytes = (
            json.dumps(
                receipt_contract, ensure_ascii=True, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ) + "\n"
        ).encode("ascii")
        if output_file.read_bytes() != expected_receipt_bytes:
            raise RuntimeError(
                "dialogue-cleanup runtime probe receipt was not canonical"
            )
        checks = {name: measured_checks[name] for name in check_names}
        result_receipt = {
            key: result[key]
            for key in (
                "scope", "fixture", "runtime", "production_functions",
                "detectors", "transcripts", "edit", "media", "receipt",
            )
        }
    except Exception as exc:
        errors["dialogue_cleanup_runtime_probe"] = type(exc).__name__
    print(json.dumps({
        "event": "autoeditor-engine-dialogue-cleanup-capability-self-test",
        "schema_version": schema_version,
        "checks": checks,
        "errors": errors,
        "result": result_receipt,
    }, sort_keys=True))
    return 0 if checks and all(checks.values()) else 1


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(_self_test())
    if len(sys.argv) == 2 and sys.argv[1] == "--audio-decoder-self-test":
        raise SystemExit(_audio_decoder_self_test())
    if len(sys.argv) == 5 and sys.argv[1] == "--artifact-receipt-self-test":
        raise SystemExit(_artifact_receipt_self_test(
            sys.argv[2], sys.argv[3], sys.argv[4]))
    if len(sys.argv) == 5 and sys.argv[1] == "--caption-render-self-test":
        raise SystemExit(_caption_render_self_test(
            sys.argv[2], sys.argv[3], sys.argv[4]))
    if len(sys.argv) == 5 and sys.argv[1] == "--sfx-production-self-test":
        raise SystemExit(_sfx_production_self_test(
            sys.argv[2], sys.argv[3], sys.argv[4]))
    if len(sys.argv) == 5 and sys.argv[1] == "--music-production-self-test":
        raise SystemExit(_music_production_self_test(
            sys.argv[2], sys.argv[3], sys.argv[4]))
    if len(sys.argv) == 4 and sys.argv[1] == "--asr-capability-self-test":
        raise SystemExit(_asr_capability_self_test(sys.argv[2], sys.argv[3]))
    if len(sys.argv) == 4 and sys.argv[1] == "--render-capability-self-test":
        raise SystemExit(_render_capability_self_test(
            sys.argv[2], sys.argv[3]))
    if (len(sys.argv) == 4
            and sys.argv[1] == "--dialogue-cleanup-capability-self-test"):
        raise SystemExit(_dialogue_cleanup_capability_self_test(
            sys.argv[2], sys.argv[3]))
    if len(sys.argv) == 4 and sys.argv[1] == "--asr-words":
        _asr_words(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--asr-secondary":
        _asr_secondary(sys.argv[2], sys.argv[3])
        return

    from autoeditor.pipeline import main as pipeline_main

    pipeline_main()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
