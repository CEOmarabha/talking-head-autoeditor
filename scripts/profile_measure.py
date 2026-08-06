#!/usr/bin/env python3
"""Measure a creator's editing style from finished reels.

Feed it a folder of a creator's finished exports; it measures the things a
profile can encode and writes a profile draft plus a human-readable report:

  cut rhythm        ffmpeg scene detection -> shot lengths (hook vs body)
  pacing            silences kept in the final edit (silencedetect)
  loudness          integrated LUFS + loudness range (ebur128)
  format            aspect, fps, duration distribution

Usage:
  python scripts/profile_measure.py REELS_DIR --name ryan_duffy \
      [--out profiles/ryan_duffy] [--scene 0.30]

The draft goes to <out>/profile_draft.yaml (never overwrites profile.yaml)
with a report at <out>/MEASUREMENT_REPORT.md. Review, merge, ship.

Method note: this generalizes the fern reference analysis (cut-rate windows,
loudness arcs, surge placement) from the AI Video Editing Framework project.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics as st
import subprocess
import sys
from pathlib import Path

FFMPEG = os.environ.get("AUTOEDITOR_FFMPEG") or shutil.which("ffmpeg") \
    or "/opt/homebrew/bin/ffmpeg"
FFPROBE = os.environ.get("AUTOEDITOR_FFPROBE") or shutil.which("ffprobe") \
    or "/opt/homebrew/bin/ffprobe"

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


def probe(path: Path) -> dict:
    p = subprocess.run([FFPROBE, "-v", "quiet", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, check=True)
    info = json.loads(p.stdout)
    vs = next(s for s in info["streams"] if s["codec_type"] == "video")
    num, den = (vs.get("r_frame_rate") or "30/1").split("/")
    return {
        "duration": float(info["format"]["duration"]),
        "w": int(vs["width"]), "h": int(vs["height"]),
        "fps": round(float(num) / float(den or 1), 2),
    }


def scene_cuts(path: Path, thresh: float) -> list[float]:
    p = subprocess.run(
        [FFMPEG, "-i", str(path), "-vf",
         f"select='gt(scene,{thresh})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True)
    return [float(m) for m in
            re.findall(r"pts_time:([0-9.]+)", p.stderr)]


def loudness(path: Path) -> dict:
    p = subprocess.run(
        [FFMPEG, "-i", str(path), "-af", "ebur128=framelog=verbose",
         "-f", "null", "-"], capture_output=True, text=True)
    i = re.findall(r"I:\s+(-?[0-9.]+) LUFS", p.stderr)
    lra = re.findall(r"LRA:\s+([0-9.]+) LU", p.stderr)
    return {"lufs": float(i[-1]) if i else None,
            "lra": float(lra[-1]) if lra else None}


def silences(path: Path, floor_db: int = -35,
             min_d: float = 0.30) -> list[float]:
    p = subprocess.run(
        [FFMPEG, "-i", str(path), "-af",
         f"silencedetect=noise={floor_db}dB:d={min_d}", "-f", "null", "-"],
        capture_output=True, text=True)
    return [float(d) for d in
            re.findall(r"silence_duration:\s*([0-9.]+)", p.stderr)]


def analyze(path: Path, scene_thresh: float) -> dict:
    meta = probe(path)
    cuts = scene_cuts(path, scene_thresh)
    dur = meta["duration"]
    bounds = [0.0] + cuts + [dur]
    shots = [b - a for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]
    hook_cuts = [c for c in cuts if c <= 3.0]
    sil = silences(path)
    return {
        "file": path.name, **meta,
        "n_cuts": len(cuts),
        "cuts_per_min": round(len(cuts) / (dur / 60), 1) if dur else 0,
        "avg_shot": round(st.mean(shots), 2) if shots else dur,
        "median_shot": round(st.median(shots), 2) if shots else dur,
        "hook_cuts_first3s": len(hook_cuts),
        "silences_kept": len(sil),
        "max_silence_kept": round(max(sil), 2) if sil else 0.0,
        **loudness(path),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reels_dir", type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--scene", type=float, default=0.30,
                    help="scene-change threshold (0.2 loose - 0.5 strict)")
    a = ap.parse_args()
    files = sorted(p for p in a.reels_dir.iterdir()
                   if p.suffix.lower() in VIDEO_EXT)
    if not files:
        sys.exit(f"no video files in {a.reels_dir}")
    out = a.out or Path("profiles") / a.name
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for f in files:
        print(f"measuring {f.name} ...", flush=True)
        try:
            rows.append(analyze(f, a.scene))
        except Exception as e:  # a single bad export must not kill the run
            print(f"  SKIP {f.name}: {e}", file=sys.stderr)

    agg = {
        "reels": len(rows),
        "portrait_share": round(sum(r["h"] > r["w"] for r in rows)
                                / len(rows), 2),
        "median_duration": round(st.median(r["duration"] for r in rows), 1),
        "median_cuts_per_min": round(
            st.median(r["cuts_per_min"] for r in rows), 1),
        "median_shot": round(st.median(r["median_shot"] for r in rows), 2),
        "median_hook_cuts_first3s": int(st.median(
            r["hook_cuts_first3s"] for r in rows)),
        "median_max_silence_kept": round(st.median(
            r["max_silence_kept"] for r in rows), 2),
        "median_lufs": round(st.median(
            r["lufs"] for r in rows if r["lufs"] is not None), 1),
    }
    # translate measurements into engine parameters
    pause_short = max(0.35, min(0.7, agg["median_max_silence_kept"] + 0.05))
    draft = f"""# DRAFT measured from {agg['reels']} finished reels on\
 {a.reels_dir}
# Review, then merge into profile.yaml. Generated by profile_measure.py.

meta:
  display_name: "{a.name}"
  status: "measured-draft"
  description: "auto-measured from {agg['reels']} reels"

rules:
  min_pause_short: {pause_short:.2f}   # longest silence kept ~\
{agg['median_max_silence_kept']}s
  target_lufs: {agg['median_lufs']}

style:
  default_style: "{'short' if agg['portrait_share'] >= 0.5 else 'auto'}"

# measured reference (not read by the engine, kept for humans):
#   median duration        {agg['median_duration']}s
#   cuts per minute        {agg['median_cuts_per_min']}
#   median shot length     {agg['median_shot']}s
#   hook cuts in first 3s  {agg['median_hook_cuts_first3s']}
"""
    (out / "profile_draft.yaml").write_text(draft)
    lines = ["# Measurement report: " + a.name, "",
             "| file | dur | wxh | cuts/min | med shot | hook3s | LUFS |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['file']} | {r['duration']:.0f}s "
                     f"| {r['w']}x{r['h']} | {r['cuts_per_min']} "
                     f"| {r['median_shot']}s | {r['hook_cuts_first3s']} "
                     f"| {r['lufs']} |")
    lines += ["", "## Aggregate", "```json",
              json.dumps(agg, indent=2), "```"]
    (out / "MEASUREMENT_REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(agg, indent=2))
    print(f"\nwrote {out/'profile_draft.yaml'}\n"
          f"      {out/'MEASUREMENT_REPORT.md'}")


if __name__ == "__main__":
    main()
