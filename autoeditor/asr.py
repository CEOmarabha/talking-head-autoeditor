"""Offline speech recognition over AutoEditor's bundled FFmpeg.

faster-whisper accepts a mono float32 waveform directly.  Decode media with
the exact FFmpeg executable already bound into the release manifest instead
of shipping PyAV's second, separately built FFmpeg runtime.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np


SAMPLE_RATE = 16_000
PYAV_PATH_PARTS = frozenset({"av", "av.libs"})
PYAV_NATIVE_NAME = re.compile(
    r"^(?:lib)?(?:avcodec|avdevice|avfilter|avformat|avutil|postproc|"
    r"swresample|swscale)(?:[.\-]|$)",
    re.IGNORECASE,
)
PYAV_DIST_INFO = re.compile(r"^av-[^/]+\.dist-info$", re.IGNORECASE)


def _ffmpeg() -> str:
    configured = os.environ.get("AUTOEDITOR_FFMPEG")
    if configured:
        candidate = Path(configured)
        if not candidate.is_file():
            raise RuntimeError("AUTOEDITOR_FFMPEG is not a file")
        return str(candidate)
    if getattr(sys, "frozen", False):
        raise RuntimeError("frozen ASR requires bundled AUTOEDITOR_FFMPEG")
    discovered = shutil.which("ffmpeg")
    if not discovered:
        raise RuntimeError("ffmpeg is required for speech recognition")
    return discovered


def decode_audio(
    media: str | os.PathLike[str],
    sampling_rate: int = SAMPLE_RATE,
    split_stereo: bool = False,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Decode the first audio stream to finite float32 PCM through FFmpeg."""
    if not isinstance(sampling_rate, int) or sampling_rate <= 0:
        raise ValueError("sampling_rate must be a positive integer")
    channels = 2 if split_stereo else 1
    command = [
        _ffmpeg(), "-nostdin", "-v", "error", "-i", str(media),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", str(channels),
        "-ar", str(sampling_rate), "-f", "s16le", "-c:a", "pcm_s16le",
        "pipe:1",
    ]
    kwargs: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": False,
        "timeout": 1800,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    completed = subprocess.run(command, **kwargs)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg audio decode failed: {detail[-800:]}")
    if not completed.stdout or len(completed.stdout) % (2 * channels):
        raise RuntimeError("FFmpeg returned invalid or empty PCM audio")
    audio = np.frombuffer(completed.stdout, dtype="<i2").astype(np.float32)
    audio /= 32768.0
    if not np.isfinite(audio).all():
        raise RuntimeError("FFmpeg returned non-finite audio samples")
    if split_stereo:
        stereo = audio.reshape(-1, 2)
        return stereo[:, 0].copy(), stereo[:, 1].copy()
    return audio


def _pad_or_trim(array: np.ndarray, length: int = 3000, *, axis: int = -1):
    """Match faster-whisper's small array helper without importing PyAV."""
    if array.shape[axis] > length:
        array = array.take(indices=range(length), axis=axis)
    if array.shape[axis] < length:
        pad_widths = [(0, 0)] * array.ndim
        pad_widths[axis] = (0, length - array.shape[axis])
        array = np.pad(array, pad_widths)
    return array


def prepare_faster_whisper() -> None:
    """Install the audio module before faster-whisper can import PyAV."""
    loaded = sys.modules.get("faster_whisper.audio")
    if loaded is not None:
        if not getattr(loaded, "_autoeditor_ffmpeg_decoder", False):
            raise RuntimeError("faster-whisper audio loaded before AutoEditor decoder")
        return
    if "faster_whisper" in sys.modules:
        raise RuntimeError("faster-whisper loaded before AutoEditor decoder")
    shim = types.ModuleType("faster_whisper.audio")
    shim.__package__ = "faster_whisper"
    shim.decode_audio = decode_audio
    shim.pad_or_trim = _pad_or_trim
    shim._autoeditor_ffmpeg_decoder = True
    sys.modules["faster_whisper.audio"] = shim


def create_model(model_path: str, **kwargs):
    prepare_faster_whisper()
    from faster_whisper import WhisperModel

    return WhisperModel(model_path, **kwargs)


def transcribe(model, media: str | os.PathLike[str], **kwargs):
    audio = decode_audio(media, SAMPLE_RATE)
    return model.transcribe(audio, **kwargs)


def pyav_payload_paths(root: str | os.PathLike[str]) -> tuple[str, ...]:
    """Return PyAV package or native-library paths under a frozen bundle."""
    bundle = Path(root)
    if not bundle.is_dir():
        return ("<missing-bundle-root>",)
    matches: set[str] = set()
    for path in bundle.rglob("*"):
        try:
            relative = path.relative_to(bundle)
        except ValueError:
            matches.add(str(path))
            continue
        folded_parts = {part.casefold() for part in relative.parts}
        if (
            folded_parts & PYAV_PATH_PARTS
            or any(PYAV_DIST_INFO.match(part) for part in relative.parts)
            or PYAV_NATIVE_NAME.match(path.name)
        ):
            matches.add(relative.as_posix())
    return tuple(sorted(matches))


def pyav_payload_absent() -> bool:
    """Fail closed if a frozen executable still carries any PyAV payload."""
    if not getattr(sys, "frozen", False):
        return True
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    try:
        import importlib.util

        module_present = importlib.util.find_spec("av") is not None
    except (ImportError, AttributeError, ValueError):
        module_present = True
    return not module_present and not pyav_payload_paths(root)


def decoder_contract_check() -> bool:
    prepare_faster_whisper()
    shim = sys.modules.get("faster_whisper.audio")
    return bool(
        shim
        and getattr(shim, "_autoeditor_ffmpeg_decoder", False)
        and shim.decode_audio is decode_audio
        and shim.pad_or_trim is _pad_or_trim
    )
