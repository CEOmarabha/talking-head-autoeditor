"""Measure and certify a source recording's audio/video offset.

WHY THIS EXISTS
---------------
Some phone apps record camera video and USB-microphone audio without
compensating for the microphone's latency. The result is a raw file that is
already out of sync BEFORE any editing happens, typically by 80-200ms. No
editor can detect this by inspecting its own output: every downstream check
compares the edit against the source, and both inherit the same offset. The
pipeline's sync gate will happily report 0.0ms drift on a file whose lips never
matched in the first place.

So we measure it against the one reference that cannot lie: a human ear.

HOW TO USE
----------
    make calibrate VIDEO=/path/to/a/take.mov

This writes five 25-second clips: an untouched control, plus audio shifted
earlier and later by 100ms and 200ms. Watch all five, pick the letter where the
lips look right, then run ``make certify`` with that value. Certification
writes a sidecar bound to the exact RAW file hash, so it cannot silently apply
to another recording that later reuses the filename.

Two notes from building this:
  * Automated mouth-motion cross-correlation was tried first and proved
    unreliable on bearded faces and soft consonants. The ladder below is
    slower, but it is tied to the actual recording being delivered.
  * Audio-late is far more forgiving to the ear than audio-early (~125ms vs
    ~45ms before it registers). So an overshoot in the "late" direction can
    still *feel* fine. If two options both look acceptable, pick the smaller
    correction -- that one is the true alignment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
LADDER = [("CONTROL", None), ("E200", -200), ("E100", -100),
          ("L100", 100), ("L200", 200)]


def write_certification(src: Path, offset_ms: int) -> Path:
    """Write the human decision with the exact RAW file hash."""
    h = hashlib.sha256()
    with src.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    out = Path(str(src) + ".avoffset")
    out.write_text(json.dumps({
        "offset_ms": int(offset_ms),
        "source_sha256": h.hexdigest(),
        "method": "human_calibration_ladder",
    }, indent=2) + "\n")
    return out


def build(src: Path, outdir: Path, start: float = 5.0,
          length: float = 25.0) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    for name, ms in LADDER:
        out = outdir / f"sync_{name}.mp4"
        cmd = [FFMPEG, "-y", "-v", "error", "-ss", str(start), "-t",
               str(length), "-i", str(src), "-c:v", "copy"]
        if ms is None:
            cmd += ["-c:a", "copy"]
        elif ms > 0:                       # delay audio
            cmd += ["-af", f"adelay={ms}|{ms}", "-c:a", "aac"]
        else:                              # advance audio
            cmd += ["-af", f"atrim=start={abs(ms) / 1000:.3f},"
                           "asetpts=PTS-STARTPTS", "-c:a", "aac"]
        cmd.append(str(out))
        subprocess.run(cmd, check=False)
        if out.exists():
            made.append(out)
            print(f"  wrote {out.name:18s} "
                  f"({'untouched original' if ms is None else f'audio {ms:+d}ms'})")
    return made


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build a human AV ladder or certify the chosen offset")
    ap.add_argument("video", type=Path)
    ap.add_argument("--certify", type=int, metavar="MS",
                    help="write a source-hash-bound calibration sidecar")
    args = ap.parse_args()
    src = args.video.expanduser().resolve()
    if not src.exists():
        sys.exit(f"no such file: {src}")
    if args.certify is not None:
        sidecar = write_certification(src, args.certify)
        print(f"Certified {args.certify:+d}ms for {src.name}")
        print(f"Wrote {sidecar}")
        return
    outdir = src.parent / "sync_calibration"
    print(f"Building sync ladder from {src.name}\n")
    made = build(src, outdir)
    print(f"""
Now watch these five clips and judge with your EYES, not a meter:

    {outdir}

  CONTROL  your file, untouched
  E200/E100  audio moved EARLIER by 200ms / 100ms
  L100/L200  audio moved LATER by 100ms / 200ms

Pick the one where the lips match. Then bind that decision to this exact RAW:

    make certify VIDEO="{src}" OFFSET=100

Use -100 for E100, +100 for L100, or 0 for CONTROL.

If two look right, choose the SMALLER correction. Late audio is perceptually
forgiving, so an overshoot can masquerade as correct.
""")
    if made and sys.platform == "darwin":
        subprocess.run(["open", str(outdir)], check=False)


if __name__ == "__main__":
    main()
