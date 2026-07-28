"""Verified talking-head auto-editor.

Raw camera file in, upload-ready cut out, with no human in the loop -- and
three mechanical gates that BLOCK delivery if the edit damaged your words or
your lip sync. See README.md for the architecture and docs/VERIFICATION.md for
why the gates exist.
"""
from __future__ import annotations
import argparse, json, hashlib, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

from . import providers
from .config import Config, font_file as _font_file

CFG = Config.load()
providers.load_dotenv()

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
EDIT_VENV = Path.home() / "cinematic-autopilot" / "venv"
AUTO_EDITOR = EDIT_VENV / "bin" / "auto-editor"
VENV_PY = EDIT_VENV / "bin" / "python"

GOLD = "&H00A7C7E8"   # ASS BGR for brand gold (#E8C7A7-ish warm gold)
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"

def run(cmd, **kw):
    kw.setdefault("check", True)
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    return subprocess.run([str(c) for c in cmd], **kw)

def log(msg):
    print(f"[pse-edit {time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ---------------------------------------------------------------- phase 1
def preflight(src: Path) -> dict:
    p = run([FFPROBE, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", src])
    info = json.loads(p.stdout)
    vs = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    au = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not vs:
        sys.exit("FATAL preflight: no video stream")
    if not au:
        sys.exit("FATAL preflight: no audio stream (talking head needs speech)")
    dur = float(info["format"].get("duration", 0))
    if dur < 3:
        sys.exit(f"FATAL preflight: clip too short ({dur:.1f}s)")
    return {"duration": dur, "width": int(vs["width"]), "height": int(vs["height"]),
            "fps": vs.get("r_frame_rate", "30/1")}

def deletterbox(src: Path, workdir: Path) -> Path:
    """Phase 1.5: strip baked-in letterbox/pillarbox bars.

    2026-07-23 incident: an iPhone share/export wrapped you LANDSCAPE
    recording inside a portrait canvas with black bars, so the pipeline
    edited it as a vertical video. Detect the true content band with
    cropdetect; if the bars eat >12% of the frame, crop them off and
    upscale to the standard canvas for the TRUE orientation."""
    p = run([FFMPEG, "-ss", "30", "-t", "20", "-i", src, "-vf",
             "cropdetect=limit=24:round=2", "-f", "null", "-"], check=False)
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)",
                       p.stderr.decode(errors="replace"))
    if not crops:
        return src
    cw, chh, cx, cy = map(int, max(set(crops), key=crops.count))
    probe = run([FFPROBE, "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0",
                 src], check=False)
    try:
        fw, fh = map(int, probe.stdout.decode().strip().split(","))
    except ValueError:
        return src
    if cw * chh >= fw * fh * 0.88 or cw < 320 or chh < 320:
        return src   # no meaningful bars
    target = "1920:1080" if cw > chh else "1080:1920"
    out = workdir / "deletterboxed.mp4"
    log(f"phase 1.5: letterbox detected, true content {cw}x{chh} at "
        f"({cx},{cy}); cropping bars, canvas -> {target.replace(':','x')}")
    global DELETTERBOX_VF
    DELETTERBOX_VF = f"crop={cw}:{chh}:{cx}:{cy},scale={target}"
    run([FFMPEG, "-y", "-i", src, "-vf",
         f"crop={cw}:{chh}:{cx}:{cy},scale={target}",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", out])
    return out


CUT_BOUNDARIES: list = []   # (position_s, removed_s) splices in the output timeline
DELETTERBOX_VF = ""          # spatial chain deletterbox applied; gate 5 replays it on RAW frames
AV_OFFSET_MS = CFG.rules.av_offset_ms
# Many phone apps record USB-microphone audio out of sync with the camera --
# typically 80-200ms -- and the file is already wrong before any editing.
# Measure yours once with `make calibrate`, then set rules.av_offset_ms.
# Positive delays the audio (use when audio LEADS the video).


def measure_av_offset(src: Path, start: float = 15.0,
                      window: float = 60.0) -> dict:
    """Measure the AV offset baked into the SOURCE, before any editing.

    This closes the one hole verify_sync structurally cannot see. That gate
    compares the master against the cut, and both inherit the source's own
    offset, so it reports 0.0ms drift on footage whose lips never matched.
    Nine renders shipped that way because a constant measured on a DIFFERENT
    recording was reused here without re-measuring.

    Mouth-region motion is cross-correlated against the audio envelope. The
    result is only trusted when three disjoint slices of the window agree,
    which is what separates a real peak from noise on a bearded face.
    Returns {"ms", "corr", "reliable"}; ms is positive when audio LAGS video.
    """
    import numpy as np
    FPS = 30
    # candidate mouth boxes as fractions of frame (speakers frame themselves
    # differently, so try a few and keep whichever correlates best)
    boxes = [(0.42, 0.45, 0.18, 0.20), (0.35, 0.50, 0.30, 0.25),
             (0.30, 0.30, 0.40, 0.35)]

    def series(box):
        x, y, w, h = box
        crop = f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"
        p1 = run([FFMPEG, "-v", "quiet", "-ss", str(start), "-t", str(window),
                  "-i", src, "-vf", f"{crop},fps={FPS},scale=48:32,format=gray",
                  "-f", "rawvideo", "-"], check=False)
        r = np.frombuffer(p1.stdout, dtype=np.uint8)
        n = len(r) // (48 * 32)
        if n < 60:
            return None, None
        f = r[:n * 48 * 32].reshape(n, 32, 48).astype(np.float32)
        mo = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
        p2 = run([FFMPEG, "-v", "quiet", "-ss", str(start), "-t", str(window),
                  "-i", src, "-vn", "-ac", "1", "-ar", "48000",
                  "-f", "f32le", "-"], check=False)
        a = np.abs(np.frombuffer(p2.stdout, dtype=np.float32))
        hop = 48000 // FPS  # 1600 exactly; 8000//30=266 skewed the audio timebase to 30.075Hz, a fake +150ms/min drift
        au = a[:len(a) // hop * hop].reshape(-1, hop).mean(1)
        return mo, au

    def onset(x):
        d = np.diff(x); d[d < 0] = 0
        sd = d.std()
        return (d - d.mean()) / sd if sd > 0 else d

    def lag(m, a):
        n = min(len(m), len(a))
        m, a = m[:n], a[:n]
        best, bl = -9.0, 0
        for L in range(-12, 13):
            c = (np.corrcoef(m[:n - L], a[L:])[0, 1] if L >= 0
                 else np.corrcoef(m[-L:], a[:n + L])[0, 1])
            if np.isfinite(c) and c > best:
                best, bl = float(c), L
        return bl * 1000.0 / FPS, best

    results = []
    for box in boxes:
        mo, au = series(box)
        if mo is None:
            continue
        m, a = onset(mo), onset(au)
        whole, corr = lag(m, a)
        third = min(len(m), len(a)) // 3
        if third < 30:
            continue
        parts = [lag(m[i * third:(i + 1) * third],
                     a[i * third:(i + 1) * third])[0] for i in range(3)]
        spread = max(parts) - min(parts)
        results.append({"ms": whole, "corr": corr, "spread": spread,
                        "parts": parts})
    if not results:
        log("av-offset: could not measure (no usable video window)")
        return {"ms": 0.0, "corr": 0.0, "reliable": False}
    best = max(results, key=lambda r: (r["spread"] <= 100, r["corr"]))
    reliable = best["spread"] <= 100
    log(f"av-offset measured: {best['ms']:+.0f}ms "
        f"(corr {best['corr']:.3f}, slices {[round(x) for x in best['parts']]}, "
        f"{'reliable' if reliable else 'UNRELIABLE, spread too wide'})")
    return {"ms": round(best["ms"]), "corr": round(best["corr"], 3),
            "reliable": reliable}


def cfr_normalize(src: Path, workdir: Path, fps: str = "30", av_offset_ms: int = AV_OFFSET_MS) -> Path:
    """Phase 1.6 -- a root cause of lip-sync drift: phone recordings
    drop frames (VFR jitter), and every frame-grid tool downstream
    (auto-editor especially) assumes constant fps, cuts land offset from
    the audio and lips drift. Rebuild the source on a strict CFR grid FIRST
    so the entire pipeline operates on exact frame math. Always on."""
    out = workdir / "cfr.mp4"
    af = ["-ar", "48000"]
    if av_offset_ms > 0:
        # source audio leads video: delay audio by the offset
        log(f"phase 1.6: CFR normalize -> {fps}fps strict grid + AV offset (audio +{av_offset_ms}ms delay)")
        af = ["-af", f"adelay={av_offset_ms}|{av_offset_ms}", "-ar", "48000"]
    elif av_offset_ms < 0:
        # source audio lags video: trim audio head to advance it
        s = abs(av_offset_ms) / 1000.0
        log(f"phase 1.6: CFR normalize -> {fps}fps strict grid + AV offset (audio {av_offset_ms}ms advance)")
        af = ["-af", f"atrim=start={s},asetpts=PTS-STARTPTS", "-ar", "48000"]
    else:
        log(f"phase 1.6: CFR normalize -> {fps}fps strict grid (VFR-drop repair)")
    run([FFMPEG, "-y", "-i", src, "-vf", f"fps={fps}",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", *af, out], timeout=3600)
    return out


def verify_sync_source(master: Path, raw_src: Path, edl: dict,
                       applied_ms: int, certified_ms: int,
                       final_words: list, workdir: Path) -> dict:
    """HARD GATE 5: the finished master must be in sync with the RAW RECORDING.

    Review-hardened (2026-07-28). The first version had two holes named by an
    external review: it compared the measurement against the value the
    pipeline itself applied (so a wrong --av-offset validated itself), and it
    matched frames against the CFR intermediate, which inherits the same
    defects as the master. Now:
      * the oracle is CERTIFIED truth: the offset a human ladder stored in a
        sidecar next to the source (default 0). applied != certified fails.
      * frames are matched against the RAW file itself, replaying only the
        spatial deletterbox chain, selected by original presentation time.
      * per-probe tolerance (a median hides staircases), forced probes near
        both ends, a max gap between usable probes, audio-match uniqueness
        margin, 3-frame temporal video matching with a runner-up margin, a
        speech requirement from the transcript instead of waveform variance,
        and monotonic master->raw time mapping (cuts only remove, so raw
        positions must strictly increase)."""
    import numpy as np
    SR, FPS = 16000, 30.0
    out = {"ok": False, "probes": [], "median_ms": None, "spread_ms": None,
           "applied_ms": applied_ms, "certified_ms": certified_ms, "note": ""}
    if applied_ms != certified_ms:
        out["note"] = (f"applied offset {applied_ms:+d}ms is not the certified "
                       f"source offset {certified_ms:+d}ms - refuse to certify")
        log(f"sync-to-source: {out['note']} - BLOCKED")
        return out

    def pcm(path):
        pr = run([FFMPEG, "-v", "quiet", "-i", path, "-vn", "-ac", "1",
                  "-ar", str(SR), "-f", "f32le", "-"], check=False)
        return np.frombuffer(pr.stdout, dtype=np.float32).astype(np.float64)

    raw_a, mas_a = pcm(raw_src), pcm(master)
    if len(raw_a) < SR * 5 or len(mas_a) < SR * 5:
        out["note"] = "audio too short to verify"
        log("sync-to-source: cannot verify (audio too short) - BLOCKED")
        return out

    n = int(1.2 * SR)
    N = len(raw_a)
    size = 1 << int(np.ceil(np.log2(N + n)))
    R = np.fft.rfft(raw_a, size)
    csum = np.cumsum(raw_a ** 2)
    win_e = csum[n:] - csum[:-n]

    def locate(needle):
        q = np.fft.rfft(needle[::-1], size)
        c = np.fft.irfft(R * q, size)[n - 1:N]
        denom = np.sqrt(win_e * (needle ** 2).sum()) + 1e-9
        m = min(len(c), len(denom))
        sc = c[:m] / denom[:m]
        i1 = int(np.argmax(sc))
        best = float(sc[i1])
        lo, hi = max(0, i1 - SR // 2), min(m, i1 + SR // 2)
        sc2 = sc.copy(); sc2[lo:hi] = -1
        second = float(sc2.max()) if m else -1.0
        return i1 / SR, best, second

    spatial = (DELETTERBOX_VF + ",") if DELETTERBOX_VF else ""

    def band(path, t, raw):
        vf = ((spatial if raw else "")
              + "crop=iw:ih*0.45:0:ih*0.20,scale=160:44,format=gray")
        pr = run([FFMPEG, "-v", "quiet", "-ss", f"{max(0.0, t):.4f}",
                  "-i", path, "-frames:v", "1", "-vf", vf,
                  "-f", "rawvideo", "-"], check=False)
        a = np.frombuffer(pr.stdout, dtype=np.uint8)
        return a[:160 * 44].reshape(44, 160).astype(np.float32) \
            if len(a) >= 160 * 44 else None

    def band3(path, t, raw):
        fs = [band(path, t + d, raw) for d in (-1 / 15, 0.0, 1 / 15)]
        return None if any(f is None for f in fs) else np.stack(fs)

    word_mids = [(w["s"] + w["e"]) / 2 for w in (final_words or [])]

    avoid = [(float(e["s"]) - 1.0, float(e["e"]) + 1.0)
             for k in ("broll", "graphics", "punch_ins")
             for e in (edl or {}).get(k, [])]
    dur = len(mas_a) / SR
    cands = sorted(set(
        [5.0, max(5.0, dur - 6.0)]
        + list(np.arange(6.0, dur - 4, max(8.0, (dur - 12) / 14)))))
    cands = [t for t in cands
             if all(not (a0 <= t <= b0) for a0, b0 in avoid)]

    results = []
    for Tm in cands:
        i0 = int(Tm * SR)
        needle = mas_a[i0:i0 + n]
        if len(needle) < n:
            continue
        # speech requirement: at least 2 transcript words inside the needle
        if sum(1 for m0 in word_mids if Tm <= m0 <= Tm + 1.2) < 2:
            continue
        Tr, sc, sc2 = locate(needle - needle.mean())
        if sc < 0.6 or (sc - sc2) < 0.08:      # weak or not unique
            continue
        fm = band3(master, Tm, raw=False)
        if fm is None:
            continue
        maes = {}
        for k in range(-9, 10):
            fr = band3(raw_src, Tr + k / FPS, raw=True)
            if fr is not None:
                maes[k] = float(np.abs(fr - fm).mean())
        if not maes:
            continue
        bk = min(maes, key=maes.get)
        rest = [v for k2, v in maes.items() if abs(k2 - bk) > 1]
        if maes[bk] > 30 or (rest and min(rest) - maes[bk] < 1.0):
            continue                            # ambiguous frame match
        results.append((float(Tm), Tr, sc, bk * 1000.0 / FPS, maes[bk]))

    # monotonicity: cuts only remove material, so Tr must increase with Tm
    results.sort()
    mono, last_tr = [], -1e9
    for r in results:
        if r[1] > last_tr - 0.2:
            mono.append(r); last_tr = r[1]
    results = mono

    for Tm, Tr, sc, ms, mae in results:
        out["probes"].append({"t": round(Tm, 1), "raw_t": round(Tr, 2),
                              "corr": round(sc, 3), "desync_ms": round(ms),
                              "mae": round(mae, 1)})
    offs = [ms for _, _, _, ms, _ in results]
    if len(offs) < 4:
        out["note"] = f"only {len(offs)} usable probe(s), cannot verify"
        log(f"sync-to-source: {out['note']} - BLOCKED")
        return out
    gaps = [b[0] - a[0] for a, b in zip(results, results[1:])]
    med = float(np.median(offs))
    spread = float(max(offs) - min(offs))
    worst = max(abs(o - certified_ms) for o in offs)
    out["median_ms"] = round(med)
    out["spread_ms"] = round(spread)
    out["worst_ms"] = round(worst)
    out["max_gap_s"] = round(max(gaps), 1) if gaps else 0.0
    out["ok"] = (abs(med - certified_ms) <= 60 and worst <= 67
                 and spread <= 100 and (not gaps or max(gaps) <= 75))
    log(f"sync-to-source: {len(offs)} probes vs RAW, median {med:+.0f}ms "
        f"worst {worst:.0f}ms spread {spread:.0f}ms max-gap "
        f"{out['max_gap_s']}s (certified {certified_ms:+d}ms) - "
        f"{'PASS' if out['ok'] else 'FAIL - DELIVERY BLOCKED'}")
    (workdir / "sync_to_source.json").write_text(json.dumps(out, indent=2))
    return out


def verify_no_retakes(final_words: list, script_path: Path | None = None,
                      workdir: Path | None = None) -> dict:
    """HARD GATE 4: prove no flubbed take survived into the delivered file.

    Every other guarantee here checks the artifact rather than the plan, and
    retake removal was the one job still being trusted to run correctly. It
    did not: a self-correction and its bad take were removed while the aborted
    fragment in front of them stayed in the video, and nothing noticed because
    no check was looking at the finished master for repeats.

    So: re-transcribe the master and run the same repeat detection over it. A
    duplicate found HERE means a flub shipped. Repeats that also appear twice
    in the script are deliberate writing and are ignored, same shield the
    cutter uses."""
    survivors = (detect_retakes(final_words, script_path=script_path)
                 + detect_false_starts(final_words, script_path))
    out = {"survivors": [], "ok": True}
    for c in survivors:
        said = " ".join(w["w"] for w in final_words
                        if c["s"] <= w["s"] < c["e"])[:120]
        out["survivors"].append({"s": c["s"], "e": c["e"],
                                 "why": c.get("why", ""), "text": said})
    out["ok"] = not out["survivors"]
    if out["ok"]:
        log("retake residue: none, no flubbed take survived")
    else:
        log(f"retake residue: {len(out['survivors'])} flubbed take(s) SURVIVED "
            "- DELIVERY BLOCKED")
        for x in out["survivors"]:
            log(f"  x [{x['s']:.1f}-{x['e']:.1f}] {x['text'][:80]!r}")
    if workdir:
        (workdir / "retake_residue.json").write_text(json.dumps(out, indent=2))
    return out


def verify_sync(master: Path, ref_cut: Path, edl: dict, duration: float) -> dict:
    """Mechanical lip-sync verifier . At probe points chosen OUTSIDE every overlay/punch
    window, the final master must match the pre-overlay cut in BOTH streams:
    video frames aligned (top-band image match, below caption, no overlays)
    and audio aligned (normalized cross-correlation peak within ±25ms).
    Drift is monotonic, so alignment at spread points proves the timeline."""
    import numpy as np
    windows = []
    for k in ("punch_ins", "broll", "graphics"):
        for ev in edl.get(k, []):
            windows.append((float(ev["s"]) - 0.7, float(ev["e"]) + 0.7))

    def clear(t):
        return all(not (a <= t <= b) for a, b in windows)

    points = []
    for f in (0.12, 0.35, 0.55, 0.78, 0.92):
        t = duration * f
        for _ in range(20):
            if clear(t) and clear(t + 1.5) and 2 < t < duration - 3:
                points.append(round(t, 2)); break
            t += 1.0
    results, ok = [], True
    for t in points:
        try:
            fr = {}
            for tag, vid in (("m", master), ("r", ref_cut)):
                p = run([FFMPEG, "-y", "-ss", f"{t:.2f}", "-i", vid,
                         "-frames:v", "1", "-vf",
                         "crop=iw:ih*0.5:0:0,scale=160:45,format=gray",
                         "-f", "rawvideo", "-"], check=False)
                fr[tag] = np.frombuffer(p.stdout, dtype=np.uint8)[:160*45]
            mae = float(np.abs(fr["m"].astype(int) - fr["r"].astype(int)).mean()) \
                if len(fr["m"]) == len(fr["r"]) == 160*45 else 99.0
            au = {}
            for tag, vid in (("m", master), ("r", ref_cut)):
                p = run([FFMPEG, "-y", "-ss", f"{t:.2f}", "-t", "2", "-i", vid,
                         "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                        check=False)
                a = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float64)
                au[tag] = (a - a.mean()) / (a.std() + 1e-9)
            n = min(len(au["m"]), len(au["r"]))
            if n < 8000:
                results.append({"t": t, "mae": mae, "offset_ms": None}); continue
            a, b = au["m"][:n], au["r"][:n]
            lags = range(-200, 201)  # ±25ms at 8kHz
            best = max(lags, key=lambda L: float(
                np.dot(a[max(0, L):n+min(0, L)], b[max(0, -L):n-max(0, L)])))
            off_ms = best / 8.0
            good = mae < 12.0 and abs(off_ms) <= 25.0
            ok = ok and good
            results.append({"t": t, "mae": round(mae, 1),
                            "offset_ms": round(off_ms, 1), "ok": good})
        except Exception as e:
            ok = False
            results.append({"t": t, "error": type(e).__name__})
    for r in results:
        log(f"sync probe @{r['t']}s: mae={r.get('mae')} "
            f"offset={r.get('offset_ms')}ms "
            f"{'OK' if r.get('ok') else 'FAIL'}")
    # Short clips with dense overlays can leave fewer than 3 windows where the
    # face is on screen. Requiring 3 there fails good videos, so the floor
    # scales with how much clear footage actually exists. Zero clear probes is
    # still a failure: unverified is not the same as verified.
    need = 3 if duration >= 60 else (2 if duration >= 25 else 1)
    enough = len(results) >= need
    if results and not enough:
        log(f"sync: only {len(results)} clear probe(s) available, need {need}")
    return {"ok": ok and enough, "probes": results,
            "probes_used": len(results), "probes_required": need}


# ---------------------------------------------------------------- phase 2
def _dur(path: Path) -> float:
    p = run([FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], check=False)
    try:
        return float(p.stdout.decode().strip())
    except ValueError:
        return 0.0


def silence_cut(src: Path, workdir: Path, margin: str = "0.15s",
                min_keep: float = 0.55) -> tuple[Path, float]:
    """Silence/stumble cut with a RETENTION GUARDRAIL.

    Quiet recordings (e.g. phone across the room, mean volume ~-40dB) fall
    below auto-editor's default 4% loudness threshold, which then deletes
    SPEECH as 'silence', the 2026-07-23 incident turned a 6:14 lesson into
    46s. So: try progressively gentler thresholds, and if the cut still
    keeps less than ``min_keep`` of the source, ship the SOURCE UNCUT, a
    long video beats a butchered one. Returns (path, retention_ratio).
    """
    src_dur = _dur(src) or 1.0
    attempts = [None, "audio:threshold=1%", "audio:threshold=0.4%"]
    best, best_ratio = None, -1.0
    for i, edit in enumerate(attempts):
        out = workdir / f"cut_try{i}.mp4"
        cmd = [AUTO_EDITOR, src, "--margin", margin, "--no-open",
               "--output", out]
        if edit:
            cmd += ["--edit", edit]
        if not AUTO_EDITOR.exists():
            break
        run(cmd, check=False)
        if not out.exists() or out.stat().st_size == 0:
            continue
        ratio = _dur(out) / src_dur
        log(f"phase 2: cut attempt {i+1} "
            f"({edit or 'default threshold'}) kept {ratio:.0%}")
        if ratio > best_ratio:
            best, best_ratio = out, ratio
        if ratio >= min_keep:
            return out, ratio
    if best is not None and best_ratio >= min_keep:
        return best, best_ratio
    log(f"phase 2 GUARDRAIL: best cut kept only {max(best_ratio,0):.0%} "
        f"(< {min_keep:.0%}), quiet recording; using SOURCE UNCUT so no "
        "speech is lost")
    out = workdir / "cut.mp4"
    shutil.copy(src, out)
    return out, 1.0


def word_guarded_cut(src: Path, workdir: Path,
                     min_pause: float = 0.9, head: float = 0.30,
                     tail: float = 0.35) -> tuple[Path, float, list]:
    """Phase 2 REWRITE (2026-07-24 word-integrity incident): auto-editor cuts
    by LOUDNESS, and you soft word-endings fall below any threshold, the
    retake lost 152/623 words MID-SENTENCE while 'kept 55%' looked legal.
    New law: the transcript is the single source of truth for what is speech.
    Transcribe the SOURCE first; silence may only be removed BETWEEN padded
    word spans (tail after a word, head before the next), never inside one.
    Word loss is now architecturally impossible. Returns
    (cut_video, retention, raw_words). Falls back to the loudness cutter
    only if whisper finds almost nothing (not a talking-head video)."""
    raw_words = transcribe(src, workdir)
    dur = _dur(src) or 1.0
    if len(raw_words) < 10:
        log("phase 2: <10 words transcribed, falling back to loudness cut")
        out, ratio = silence_cut(src, workdir)
        return out, ratio, raw_words
    cuts = detect_dead_air(raw_words, dur, min_pause, head, tail)
    if not cuts:
        out = workdir / "cut.mp4"
        shutil.copy(src, out)
        log("phase 2: word-guarded cut, no removable pauses; source kept whole")
        return out, 1.0, raw_words
    out = apply_cuts(src, cuts, workdir)
    ratio = _dur(out) / dur
    log(f"phase 2: word-guarded cut removed {len(cuts)} pause(s) "
        f"(≥{min_pause}s, pad {head}/{tail}s), kept {ratio:.0%}, "
        f"all {len(raw_words)} words preserved")
    return out, ratio, raw_words

RESTART_MARKERS = (
    "let me say that again", "let's make that clear", "lets make that clear",
    "let me redo", "let me try that again", "one more time", "take two",
    "start over", "scratch that", "let me start again", "say that again",
    "let me rephrase", "hold on", "wait no", "my bad", "excuse me")


def _absorb_restart(words: list, norm: list, i: int,
                    look_back: float = 8.0, script_norm: str = "") -> int:
    """Return the index the retake cut should START from — walking back over a
    spoken self-correction ('alright, let's make that clear') and any short
    aborted fragment right before it. Those belong to the bad take."""
    t0 = words[i]["s"]
    lo = i
    while lo > 0 and t0 - words[lo - 1]["s"] <= look_back:
        lo -= 1
    if lo >= i:
        return i
    joined = " ".join(n.replace("'", "") for n in norm[lo:i])
    hit = None
    for mk in RESTART_MARKERS:
        pos = joined.find(mk.replace("'", ""))
        if pos >= 0:
            hit = lo + len(joined[:pos].split())
            break
    if hit is None:
        return i
    # Swallow every SHORT aborted sentence stacked before the aside, not just
    # one. A fragment like "A man with in... or woman." ends in a period, so a
    # single hop back to the previous sentence boundary lands on its own edge
    # and leaves the fragment in the video. Keep stepping back while the
    # sentences stay short and close together.
    start = hit
    ends = lambda i: words[i]["w"].strip().endswith((".", "!", "?"))
    while start - 1 > lo:
        # the sentence immediately preceding `start` ENDS at start-1; find
        # where it begins by looking for the punctuation before that.
        end_idx = start - 1
        prev_end = None
        for x in range(end_idx - 1, lo - 1, -1):
            if ends(x):
                prev_end = x
                break
        frag_start = (prev_end + 1) if prev_end is not None else lo
        if frag_start >= start:
            break
        if (start - frag_start) > 9:          # a real sentence, not a fragment
            break
        if (words[start]["s"] - words[start - 1]["e"]) > 2.5:
            break                              # too far away to belong to it
        if script_norm:
            phrase = " " + " ".join(norm[frag_start:start]).strip() + " "
            if len(phrase) > 12 and phrase in script_norm:
                break        # this is a line he actually wrote, not a flub
        start = frag_start
    return start


def _cut_edge(words: list, i: int) -> float:
    """A cut boundary that can never land inside a word.

    detect_retakes wrote `words[i].s - 0.10` directly, and when the preceding
    word ended less than 100ms earlier that boundary sliced through it. In one
    render it clipped "having" down to "hav", which the speech model then read
    as "head", and the script gate correctly flagged the sentence as damaged.
    The pause cutter always had this guard. The retake cutters did not."""
    prev_end = words[i - 1]["e"] if i > 0 else 0.0
    return round(max(prev_end + 0.03, words[i]["s"] - 0.10), 3)


def detect_retakes(words: list, max_gap: float = 14.0,
                   min_n: int = 3, script_path: Path | None = None) -> list:
    """Retake removal (2026-07-25, Omar: 'how did you not notice I messed up
    the first time and didn't cut to where I repeat it correctly').

    When Omar flubs a line he simply says it again. The transcript then
    contains the SAME word sequence twice, back to back. Keep the LAST take
    (the clean one) and cut everything from the start of the first attempt to
    the start of the final attempt. Longest repeat wins, so partial restarts
    ('a stranger cuts in front of you / a stranger cuts in front of you and
    nobody...') collapse correctly."""
    norm = [re.sub(r"[^a-z0-9']", "", w["w"].lower()) for w in words]
    # SCRIPT SHIELD: some phrases repeat because the SCRIPT repeats them
    # ("it sounds like having all the answers, and nobody has all the
    # answers"). Deleting the second one is not retake removal, it is
    # deleting the line. If the script says it twice, the speaker meant it.
    script_norm = ""
    if script_path and script_path.exists():
        script_norm = " " + " ".join(
            re.sub(r"[^a-z0-9']", "", t.lower())
            for t in re.findall(r"[A-Za-z0-9']+", script_path.read_text())) + " "
    cuts, n, skip_to = [], len(words), 0
    for i in range(n):
        if i < skip_to:
            continue
        best = None
        for j in range(i + min_n, min(n, i + 90)):
            if words[j]["s"] - words[i]["s"] > max_gap:
                break
            k = 0
            while (i + k < j and j + k < n
                   and norm[i + k] and norm[i + k] == norm[j + k]):
                k += 1
            if k >= min_n and (best is None or k > best[1]):
                best = (j, k)
        if best:
            j, k = best
            if script_norm:
                phrase = " " + " ".join(norm[i:i + k]) + " "
                spoken_all = " " + " ".join(norm) + " "
                # deliberate only if the script repeats it AT LEAST as often
                # as it was delivered; a third delivered occurrence of a
                # twice-scripted phrase is still a flub
                if 2 <= script_norm.count(phrase) and \
                        spoken_all.count(phrase) <= script_norm.count(phrase):
                    log(f"retake SKIPPED [{words[i]['s']:.1f}]: "
                        f"'{' '.join(w['w'] for w in words[i:i + k])[:45]}' "
                        "repeats in the script too, so it is deliberate")
                    skip_to = j
                    continue
            start_i, why = i, f"retake ({k}-word repeat)"
            # absorb the wind-up: a self-correction aside Omar says out loud
            # ("alright, let's make that clear") and any short aborted
            # fragment right before it belong to the bad take, not the good one.
            back = _absorb_restart(words, norm, i,
                                   script_norm=script_norm)
            if back < i:
                start_i, why = back, why + " + self-correction aside"
            cuts.append({"s": _cut_edge(words, start_i),
                         "e": _cut_edge(words, j), "why": why})
            skip_to = j
    for c in cuts:
        log(f"retake cut: [{c['s']:.1f}-{c['e']:.1f}] {c['why']} — "
            "keeping the later take")
    return cuts


def detect_false_starts(words: list, script_path: Path | None = None,
                        max_words: int = 7, max_gap: float = 3.5) -> list:
    """False-start removal (2026-07-25, Omar @3:42: 'You never hesitate.' ->
    'You never compromise.').

    A retake that changes the ending shares only a short prefix, so the
    n-gram matcher in detect_retakes can't see it. Pattern: two ADJACENT
    sentences opening with the same >=2 words, the first one SHORT and
    abandoned, the second the real line. Cut the first.

    Guards against Omar's deliberate parallel structure ('What is my
    Superiority signal... What is my Autonomy signal...'): only short
    sentences qualify, and a first sentence that appears verbatim in the
    script is intentional and never cut."""
    script_prose = ""
    if script_path and script_path.exists():
        script_prose = re.sub(r"[^a-z0-9' ]", " ",
                              script_path.read_text().lower())
        script_prose = re.sub(r"\s+", " ", script_prose)
    norm = lambda t: re.sub(r"[^a-z0-9']", "", t.lower())
    sents, cur = [], []
    for w in words:
        cur.append(w)
        if w["w"].strip().endswith((".", "!", "?")):
            sents.append(cur); cur = []
    if cur:
        sents.append(cur)
    cuts = []
    for a, b in zip(sents, sents[1:]):
        if len(a) > max_words or not a or not b:
            continue
        if b[0]["s"] - a[-1]["e"] > max_gap:
            continue
        pre = 0
        while (pre < len(a) - 1 and pre < len(b)
               and norm(a[pre]["w"]) and norm(a[pre]["w"]) == norm(b[pre]["w"])):
            pre += 1
        if pre < 2:
            continue
        phrase = " ".join(norm(x["w"]) for x in a).strip()
        if script_prose and phrase and phrase in script_prose:
            continue        # Omar wrote it that way — intentional
        cuts.append({"s": _cut_edge(words, words.index(a[0])),
                     "e": _cut_edge(words, words.index(b[0])),
                     "why": f"false start ({pre}-word prefix repeat)"})
    for c in cuts:
        log(f"false-start cut: [{c['s']:.1f}-{c['e']:.1f}] {c['why']}")
    return cuts


def detect_head_noise_audio(src: Path, max_burst: float = 0.7,
                            min_gap: float = 0.14, window: float = 5.0) -> list:
    """Opening cough/throat-clear, detected from the AUDIO (2026-07-25).

    The word-level version of this check (`detect_lead_noise`) misses the
    common case: whisper labels the cough with the first real word and gives
    that 'word' a long duration spanning the silence after it, so there is no
    measurable gap to find. The waveform has no such ambiguity -- a cough is a
    short burst, then silence, then speech starts."""
    import numpy as np
    p = run([FFMPEG, "-v", "quiet", "-t", str(window), "-i", src,
             "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            check=False)
    a = np.frombuffer(p.stdout, dtype=np.float32)
    hop = 400                                     # 25ms bins
    if len(a) < hop * 8:
        return []
    env = np.abs(a[:len(a) // hop * hop].reshape(-1, hop)).mean(1)
    thr = max(float(env.max()) * 0.12, 0.012)
    loud = env > thr
    spans, i = [], 0
    while i < len(loud):
        if loud[i]:
            j = i
            while j < len(loud) and loud[j]:
                j += 1
            spans.append((i * 0.025, j * 0.025))
            i = j
        else:
            i += 1
    if len(spans) < 2:
        return []
    (s0, e0), (s1, _) = spans[0], spans[1]
    if s0 <= 0.60 and (e0 - s0) <= max_burst and (s1 - e0) >= min_gap:
        cut = {"s": 0.0, "e": max(0.0, s1 - 0.08),
               "why": f"opening cough/throat clear ({e0 - s0:.2f}s burst, "
                      f"{s1 - e0:.2f}s of silence after it)"}
        log(f"head-noise cut: [{cut['s']:.2f}-{cut['e']:.2f}] {cut['why']}")
        return [cut]
    return []


def detect_lead_noise(words: list, max_p: float = 0.70,
                      min_gap: float = 0.25) -> list:
    """Throat-clear / cough on the opening frame (2026-07-25, Omar: 'how about
    cutting out the cough at the very beginning').

    The cough detector only fires on loud spans containing NO words — but
    whisper transcribes a cough as a low-confidence word ('Your', p=0.54),
    so it slipped through and became the first frame of the video. Signature:
    the FIRST word is low-confidence AND separated from the next word by a
    real gap (a genuine opening word runs straight into its phrase)."""
    cuts, i = [], 0
    while i < len(words) - 1:
        w, nxt = words[i], words[i + 1]
        if w.get("p", 1.0) < max_p and (nxt["s"] - w["e"]) >= min_gap:
            cuts.append({"s": max(0.0, w["s"] - 0.12),
                         "e": w["e"] + min(0.15, (nxt["s"] - w["e"]) / 2),
                         "why": f"lead-in noise (cough/throat clear, "
                                f"p={w.get('p')})"})
            i += 1
            continue
        break
    for c in cuts:
        log(f"lead-noise cut: [{c['s']:.2f}-{c['e']:.2f}] {c['why']}")
    return cuts


def detect_dead_air(words: list, duration: float, min_pause: float = 0.9,
                    head: float = 0.30, tail: float = 0.35) -> list:
    """Pause removal on an EXISTING transcript. Used both by the phase-2
    word-guarded cut and as a second sweep afterwards: the raw-source pass
    misses gaps where whisper first heard phantom words (2026-07-25. 4.5s of
    dead air survived mid-sentence in the delivered chunk 1)."""
    cuts = []
    if not words:
        return cuts
    if words[0]["s"] - head > 1.0:
        cuts.append({"s": 0.0, "e": words[0]["s"] - head})
    for w1, w2 in zip(words, words[1:]):
        if w2["s"] - w1["e"] >= min_pause:
            cuts.append({"s": w1["e"] + tail, "e": w2["s"] - head})
    if duration - words[-1]["e"] > 1.0:
        cuts.append({"s": words[-1]["e"] + tail, "e": duration})
    return [c for c in cuts if c["e"] - c["s"] > 0.15]


def detect_anomaly_cuts(src: Path, words: list,
                        script_path: Path | None = None) -> list:
    """Auto-detect coughs (loud sound containing zero words, 0.3-3s) and
    garbled speech (>=2 consecutive words below 0.40 Whisper confidence).
    Born from the 2026-07-24 director notes: a cough and a mangled sentence
    survived to the final render. Conservative by design.

    SCRIPT SHIELD (2026-07-24, incident #3): low whisper confidence is NOT
    proof of a flub, it cut 'Superiority, Autonomy,' out of the SAC reveal
    because whisper was unsure of the words you said perfectly. When the
    teleprompter script is known, a garble span whose words appear in the
    script is REAL CONTENT and is never cut."""
    cuts = []
    script_toks = set()
    if script_path and script_path.exists():
        script_toks = {re.sub(r"[^a-z0-9']", "", t.lower())
                       for t in re.findall(r"[A-Za-z0-9']+",
                                           script_path.read_text())}

    def on_script(span_words) -> bool:
        """True if this 'garble' actually carries scripted content."""
        if not script_toks:
            return False
        toks = [re.sub(r"[^a-z0-9']", "", w["w"].lower()) for w in span_words]
        toks = [t for t in toks if len(t) > 2]
        return bool(toks) and sum(t in script_toks for t in toks) / len(toks) >= 0.5
    # garble clusters
    run_w = []
    for w in words:
        if w.get("p", 1.0) < 0.40:
            run_w.append(w)
        else:
            if len(run_w) >= 2 and run_w[-1]["e"] - run_w[0]["s"] <= 4.0:
                if on_script(run_w):
                    log(f"anomaly SKIPPED [{run_w[0]['s']:.1f}-"
                        f"{run_w[-1]['e']:.1f}]: low confidence but the words "
                        "are in the script, real content, not a flub")
                else:
                    cuts.append({"s": max(0, run_w[0]["s"] - 0.1),
                                 "e": run_w[-1]["e"] + 0.1, "why": "garbled"})
            run_w = []
    if len(run_w) >= 2 and run_w[-1]["e"] - run_w[0]["s"] <= 4.0 and not on_script(run_w):
        cuts.append({"s": max(0, run_w[0]["s"] - 0.1),
                     "e": run_w[-1]["e"] + 0.1, "why": "garbled"})
    # coughs: sound spans with no words
    p = run([FFMPEG, "-i", src, "-af", "silencedetect=noise=-32dB:d=0.25",
             "-f", "null", "-"], check=False)
    txt = p.stderr.decode(errors="replace")
    starts = [float(m.group(1)) for m in
              re.finditer(r"silence_start: ([\d.]+)", txt)]
    ends = [float(m.group(1)) for m in
            re.finditer(r"silence_end: ([\d.]+)", txt)]
    total = _dur(src)
    events = sorted([(t, "s") for t in starts] + [(t, "e") for t in ends])
    spans, cur, sounding = [], 0.0, True
    for t, kind in events:
        if kind == "s" and sounding:
            spans.append((cur, t)); sounding = False
        elif kind == "e" and not sounding:
            cur = t; sounding = True
    if sounding:
        spans.append((cur, total))
    for a, b in spans:
        # A cough is short. Allowing up to 3s let this remove real speech that
        # the transcript happened to miss ("gets left on read" -> "gets led").
        # Wider word margin for the same reason: near-misses are not noise.
        if 0.3 <= b - a <= 1.2 and not any(
                w["s"] < b + 0.35 and w["e"] > a - 0.35 for w in words):
            cuts.append({"s": round(a, 2), "e": round(b, 2), "why": "cough/noise"})
    for c in cuts:
        log(f"anomaly cut: [{c['s']:.1f}-{c['e']:.1f}] {c['why']}")
    return [{"s": c["s"], "e": c["e"]} for c in cuts]


def apply_cuts(src: Path, cuts: list, workdir: Path) -> Path:
    """Director-mode retake removal: delete [s,e) ranges (flubbed takes,
    trailing 'um's) with frame-accurate AV re-encode + concat. Caller must
    re-transcribe afterwards — all downstream times are post-cut."""
    if not cuts:
        return src
    total = _dur(src)
    # INTEGER TRIMS (2026-07-28, review finding): snapping to the grid and
    # then serializing with :.3f re-broke the boundaries. 0.0666666 becomes
    # 0.067, trim's end is exclusive, and a rounded value flips whether the
    # boundary frame is admitted while atrim cuts at the printed decimal. A
    # three-range repro measured 65ms of A/V mismatch. Frames and samples are
    # integers, so the graph is now built from integers only: video by
    # start_frame/end_frame, audio by start_sample/end_sample at exactly
    # 1600 samples per frame (48000Hz / 30fps, both enforced by cfr_normalize).
    G, SPF = 30.0, 1600
    pr = run([FFPROBE, "-v", "quiet", "-select_streams", "v:0",
              "-show_entries", "stream=nb_frames", "-of", "csv=p=0", src],
             check=False)
    try:
        total_f = int(pr.stdout.decode().strip())
    except ValueError:
        total_f = int(round(total * G))
    dropf = sorted((max(0, int(round(float(c["s"]) * G))),
                    min(total_f, int(round(float(c["e"]) * G))))
                   for c in cuts)
    dropf = [(a0, b0) for a0, b0 in dropf if b0 > a0]
    keepf, tf = [], 0
    for sf, ef in dropf:
        if sf > tf:
            keepf.append((tf, sf))
        tf = max(tf, ef)
    if tf < total_f:
        keepf.append((tf, total_f))
    drops = [(sf / G, ef / G) for sf, ef in dropf]      # seconds, for logs/ledger
    keeps = [(sf / G, ef / G) for sf, ef in keepf]

    # BOUNDARY LEDGER: remember where every splice lands in the OUTPUT
    # timeline and how much it removed. The script gate uses this to tell
    # real edit damage from a speech-model mishearing.
    global CUT_BOUNDARIES
    kept = []
    for b, r in CUT_BOUNDARIES:                     # remap old boundaries
        if any(s0 <= b <= e0 for s0, e0 in drops):
            continue                                # this splice was cut away
        kept.append((b - sum(min(e0, b) - s0 for s0, e0 in drops if s0 < b), r))
    accf = 0
    for i, (sf, ef) in enumerate(keepf[:-1]):
        accf += ef - sf
        removed = (keepf[i + 1][0] - ef) / G
        kept.append((round(accf / G, 3), round(removed, 3)))
    CUT_BOUNDARIES = sorted(kept)

    vparts, aparts, vl, al = [], [], [], []
    for i, (sf, ef) in enumerate(keepf):
        vparts.append(f"[0:v]trim=start_frame={sf}:end_frame={ef},"
                      f"setpts=PTS-STARTPTS[kv{i}]")
        aparts.append(f"[0:a]atrim=start_sample={sf * SPF}:end_sample={ef * SPF},"
                      f"asetpts=PTS-STARTPTS[ka{i}]")
        vl.append(f"[kv{i}]"); al.append(f"[ka{i}]")
    graph = (";".join(vparts + aparts) + ";"
             + "".join(vl) + f"concat=n={len(keeps)}:v=1:a=0[vout];"
             + "".join(al) + f"concat=n={len(keeps)}:v=0:a=1[aout]")
    # unique per call: apply_cuts now runs twice (word-guarded pause cut, then
    # anomaly cut) and reusing one name made input==output (ffmpeg exit 234).
    n = len(list(workdir.glob("retakes_cut*.mp4")))
    out = workdir / f"retakes_cut{n}.mp4"
    run([FFMPEG, "-y", "-i", src, "-filter_complex", graph,
         "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", out], timeout=3600)
    removed = sum(e - s for s, e in drops)
    pr2 = run([FFPROBE, "-v", "quiet", "-show_entries",
               "stream=codec_type,duration", "-of", "json", out], check=False)
    try:
        streams = json.loads(pr2.stdout.decode())["streams"]
        vd = next(float(x["duration"]) for x in streams
                  if x["codec_type"] == "video")
        ad = next(float(x["duration"]) for x in streams
                  if x["codec_type"] == "audio")
        if abs(vd - ad) > 0.034:
            log(f"apply_cuts WARNING: A/V stream durations differ by "
                f"{(vd - ad) * 1000:+.0f}ms after cutting - investigate")
    except (StopIteration, KeyError, ValueError):
        pass
    log(f"director cuts: removed {len(drops)} range(s), {removed:.1f}s "
        f"(flubs/retakes/coughs) -> {_dur(out):.1f}s")
    return out


# ---------------------------------------------------------------- phase 3
def transcribe(video: Path, workdir: Path) -> list[dict]:
    log("phase 3: faster-whisper word-level transcript")
    script = workdir / "_whisper.py"
    script.write_text(
        "import json,sys\n"
        "from faster_whisper import WhisperModel\n"
        "m=WhisperModel('small',device='cpu',compute_type='int8')\n"
        "segs,_=m.transcribe(sys.argv[1],word_timestamps=True)\n"
        "words=[{'w':w.word.strip(),'s':round(w.start,3),'e':round(w.end,3),"
        "'p':round(w.probability,2)}\n"
        "       for s in segs for w in (s.words or [])]\n"
        "json.dump(words,open(sys.argv[2],'w'))\n")
    wj = workdir / "words.json"
    run([VENV_PY, script, video, wj], timeout=1800)
    return json.loads(wj.read_text())

def script_correct(words: list[dict], script_path: Path) -> list[dict]:
    """2026-07-24: you reads from a teleprompter script, that script is
    ground truth for caption TEXT (whisper stays ground truth for TIMING).
    Sequence-align whisper words to the script's words and replace misheard
    cores with the scripted spelling; whisper's punctuation/casing shell is
    kept so caption chunking (sentence-end flush) still works."""
    import difflib
    prose = "\n".join(l for l in script_path.read_text().splitlines()
                      if l.strip() and not l.startswith(("#", "---")))
    stoks = re.findall(r"[A-Za-z0-9']+", prose)

    def norm(t):
        return re.sub(r"[^a-z0-9']", "", t.lower())

    sm = difflib.SequenceMatcher(a=[norm(t) for t in stoks],
                                 b=[norm(w["w"]) for w in words],
                                 autojunk=False)
    fixed = skipped = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                orig = words[j1 + k]["w"]
                stok = stoks[i1 + k]
                # PARAPHRASE LAW : only correct actual
                # MISHEARINGS, whisper unsure of the word, or the heard
                # word is phonetically close to the scripted one. A word
                # whisper heard confidently that differs from the script is
                # you paraphrasing on purpose: the spoken word wins.
                sim = difflib.SequenceMatcher(
                    a=norm(orig), b=norm(stok)).ratio()
                if words[j1 + k].get("p", 1.0) >= 0.70 and sim < 0.60:
                    skipped += 1
                    continue
                m = re.match(r"^(\W*)(.*?)(\W*)$", orig)
                words[j1 + k]["w"] = (m.group(1) + stok + m.group(3)
                                      if m else stok)
                fixed += 1
    matched = sum(i2 - i1 for op, i1, i2, _, _ in sm.get_opcodes()
                  if op == "equal")
    log(f"captions: script alignment, {matched} exact, "
        f"{fixed} misheard word(s) corrected from script, "
        f"{skipped} paraphrase(s) kept as spoken")
    return words


def _gap_has_big_cut(sents, si, sent_of, span, final_words) -> bool:
    """A script sentence with almost no delivered words is an intentional skip
    ONLY if no large cut sits in the gap where it should have been. A cut of
    2s or more there means the edit may have deleted the whole sentence."""
    prev_t = 0.0
    for sj in range(si - 1, -1, -1):
        if sj in span:
            prev_t = final_words[min(len(final_words) - 1, span[sj][1])]["e"]
            break
    next_t = final_words[-1]["e"] if final_words else 0.0
    for sj in range(si + 1, len(sents)):
        if sj in span:
            next_t = final_words[max(0, span[sj][0])]["s"]
            break
    return any(prev_t - 0.3 <= b <= next_t + 0.3 and r >= 2.0
               for b, r in CUT_BOUNDARIES)


def script_integrity(final_words: list[dict], script_path: Path,
                     workdir: Path) -> dict:
    """HARD GATE 3 (Omar 2026-07-24): compare the DELIVERED speech to the
    teleprompter script SEMANTICALLY.

    Omar's law: "I paraphrase, I add elaboration, I skip sentences — that is
    NOT a loss of integrity. The idea was still said, in my own wording."
    So only real DAMAGE fails: a sentence the edit chopped mid-thought
    (the 2026-07-24 incident: 'assigning status for around five hundred
    million years' delivered as 'signing status for around Philly').

    Mechanically: word-align script->spoken, score each script sentence,
    and hand every ambiguous sentence to DeepSeek to classify as
    DELIVERED / PARAPHRASED / SKIPPED (all fine) or DAMAGED (blocks).
    """
    import difflib
    prose = " ".join(l for l in script_path.read_text().splitlines()
                     if l.strip() and not l.startswith(("#", "---")))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose) if s.strip()]
    norm = lambda t: re.sub(r"[^a-z0-9']", "", t.lower())
    stoks, sent_of = [], []
    for si, s in enumerate(sents):
        for t in re.findall(r"[A-Za-z0-9']+", s):
            stoks.append(norm(t)); sent_of.append(si)
    spoken = [norm(w["w"]) for w in final_words]
    sm = difflib.SequenceMatcher(a=stoks, b=spoken, autojunk=False)
    hit = [False] * len(stoks)
    span = {}          # script sentence -> [min,max] spoken index touched
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            hit[i + k] = True
            si = sent_of[i + k]
            lo, hi = span.get(si, (j + k, j + k))
            span[si] = (min(lo, j + k), max(hi, j + k))

    suspects, delivered, skipped = [], 0, 0
    for si, s in enumerate(sents):
        idx = [i for i, x in enumerate(sent_of) if x == si]
        if not idx:
            continue
        frac = sum(hit[i] for i in idx) / len(idx)
        big_cut_near = False
        lo_, hi_ = span.get(si, (None, None))
        if lo_ is not None:
            t0_ = final_words[max(0, lo_)]["s"]
            t1_ = final_words[min(len(final_words) - 1, hi_)]["e"]
            big_cut_near = any(t0_ - 0.6 <= b <= t1_ + 0.6 and r >= 2.0
                               for b, r in CUT_BOUNDARIES)
        if frac >= 0.93 or (frac >= 0.80 and not big_cut_near):
            delivered += 1
        elif frac < 0.15 and not _gap_has_big_cut(sents, si, sent_of, span,
                                                  final_words):
            skipped += 1          # skipped by choice, no large cut nearby
        else:
            lo, hi = span.get(si, (0, -1))
            heard = " ".join(w["w"] for w in final_words[max(0, lo - 2):hi + 3])
            t0 = final_words[max(0, lo)]["s"] if lo <= hi else 0.0
            t1 = final_words[min(len(final_words) - 1, hi)]["e"] if lo <= hi else 0.0
            suspects.append({"script": s, "heard": heard,
                             "matched": round(frac, 2),
                             "t0": round(t0, 2), "t1": round(t1, 2)})

    result = {"script_sentences": len(sents), "delivered": delivered,
              "skipped_by_omar": skipped, "suspects": len(suspects),
              "damaged": [], "ok": True}
    if not suspects:
        log(f"script integrity: {delivered} delivered, {skipped} skipped "
            f"by choice, 0 suspect — PASS")
        return result

    # --- DeepSeek judges: paraphrase/skip = fine, mid-sentence damage = fail
    payload = json.dumps([{"i": i, "script": s["script"], "heard": s["heard"]}
                          for i, s in enumerate(suspects)], indent=0)
    prompt = (
        "You are QA for a video editor. Omar reads a teleprompter script but "
        "PARAPHRASES freely, ADDS his own elaboration, and sometimes SKIPS "
        "sentences on purpose. All of that is perfectly fine.\n"
        "The ONLY failure is DAMAGE: the editor's cut destroyed his speech, so "
        "the delivered line is garbled, truncated mid-thought, or lost a "
        "concrete fact (numbers, names, key terms) leaving nonsense.\n"
        'Example DAMAGE: script "assigning status for around five hundred '
        'million years" / heard "signing status for around Philly".\n'
        'Example FINE (paraphrase): script "Superiority is not a comparison '
        'you win. It is a fact you carry." / heard "superiority isn\'t '
        'something you win against people, you just carry it".\n'
        "For each item reply with its verdict. Output ONLY JSON:\n"
        '{"verdicts":[{"i":0,"verdict":"DAMAGED","why":"lost the 500 million '
        'year figure, sentence ends in nonsense"}]}\n'
        'verdict is one of: FINE, DAMAGED.\n\nITEMS:\n' + payload)
    try:
        hermes = str(Path.home() / ".hermes/hermes-agent/venv/bin/hermes")
        p = run([hermes, "chat", "-q", prompt, "-Q", "--provider", "deepseek",
                 "-m", "deepseek-v4-flash", "--max-turns", "1"],
                timeout=min(600, 180 + len(payload) // 15), check=False)
        raw = p.stdout.decode(errors="replace")
        sid = re.search(r"session_id:\s*(\S+)",
                        raw + p.stderr.decode(errors="replace"))
        if sid:
            run([hermes, "sessions", "delete", sid.group(1), "--yes"],
                timeout=30, check=False)
        m = re.search(r"\{.*\}", raw, re.S)
        verdicts = json.loads(m.group(0))["verdicts"] if m else []
        answered = {int(v.get("i", -1)) for v in verdicts
                    if str(v.get("verdict", "")).strip()}
        missing_idx = set(range(len(suspects))) - answered
        if missing_idx:
            log(f"script integrity: judge left {len(missing_idx)} suspect(s) "
                "unanswered - judging them mechanically (fail-closed)")
            for mi in sorted(missing_idx):
                sus = suspects[mi]
                spliced = any(sus["t0"] - 0.35 <= b <= sus["t1"] + 0.35
                              for b, _r in CUT_BOUNDARIES) \
                    if "t0" in sus else True
                if spliced and sus.get("matched", 1.0) < 0.8:
                    result["damaged"].append(
                        {**sus, "why": "unanswered by judge; a splice lands "
                                       "in this sentence"})
        for v in verdicts:
            if not str(v.get("verdict", "")).upper().startswith("DAM"):
                continue
            sus = suspects[int(v["i"])]
            spliced = any(sus["t0"] - 0.35 <= b <= sus["t1"] + 0.35
                          for b, _r in CUT_BOUNDARIES)
            if not spliced:
                # No cut landed here, so the edit did not damage this line.
                # The speech model simply misheard it (low-confidence words
                # like 'having' -> 'head is'). Report, never block.
                result.setdefault("misheard", []).append(
                    {**sus, "why": v.get("why", "")})
                log(f"  ~ transcription artifact (no splice in "
                    f"{sus['t0']:.1f}-{sus['t1']:.1f}s): "
                    f"{sus['script'][:60]!r}")
                continue
            result["damaged"].append({**sus, "why": v.get("why", "")})
        result["judge"] = "deepseek"
    except Exception as e:
        # judge unavailable: mechanical fallback — damage = an interior run of
        # >=3 script words missing while BOTH flanks of the sentence matched
        log(f"script integrity: judge unavailable ({type(e).__name__}) — "
            "mechanical fallback")
        result["judge"] = "mechanical"
        for si, s in enumerate(sents):
            idx = [i for i, x in enumerate(sent_of) if x == si]
            if not idx or not (0.15 <= sum(hit[i] for i in idx) / len(idx) < 0.80):
                continue
            runs, cur = [], 0
            for i in idx:
                cur = cur + 1 if not hit[i] else 0
                runs.append(cur)
            if hit[idx[0]] and hit[idx[-1]] and max(runs) >= 3:
                result["damaged"].append(
                    {"script": s, "heard": "", "matched": 0.0,
                     "why": f"{max(runs)} consecutive words missing inside "
                            "an otherwise-matching sentence"})
    result["ok"] = not result["damaged"]
    (workdir / "script_integrity.json").write_text(json.dumps(result, indent=2))
    mis = len(result.get("misheard", []))
    log(f"script integrity: {delivered} delivered, {skipped} skipped by "
        f"choice, {len(suspects)} reviewed -> {len(result['damaged'])} DAMAGED"
        + (f", {mis} transcription artifact(s)" if mis else "")
        + f" — {'PASS' if result['ok'] else 'FAIL - DELIVERY BLOCKED'}")
    for d in result["damaged"]:
        log(f"  ✗ script: {d['script'][:80]!r}")
        log(f"    heard : {d['heard'][:80]!r}  ({d.get('why','')[:60]})")
    return result


# ---------------------------------------------------------------- phase 4
def brand_font() -> tuple[str, bool]:
    """Return (font FILE path, is_worksans). PNG captions need a real file."""
    for d in (Path.home() / "Library/Fonts", Path("/Library/Fonts")):
        hits = sorted(d.glob("WorkSans*Black*")) or sorted(d.glob("WorkSans*"))
        if hits:
            return str(hits[0]), True
    for fb in ("/System/Library/Fonts/Supplemental/Arial Black.ttf",
               "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
               "/System/Library/Fonts/Helvetica.ttc"):
        if Path(fb).exists():
            return fb, False   # flagged in QA
    return "", False


def build_caption_pngs(words: list[dict], workdir: Path, font_file: str,
                       vid_w: int, vid_h: int,
                       scale: float = 0.045, max_words: int = 4) -> list[dict]:
    """Phase 4 (libass-free): render each caption card as a transparent PNG
    (Pillow), first word in brand gold, rest white, black outline. Composited
    later with ffmpeg's `overlay` filter, works on minimal ffmpeg builds
    that lack libass/drawtext. `scale`/`max_words` come from the style
    profile (shorts = bigger cards, fewer words per card)."""
    from PIL import Image, ImageDraw, ImageFont
    size = max(28, int(vid_h * scale))
    font = ImageFont.truetype(font_file, size)
    gold, white, outline = (232, 199, 167, 255), (255, 255, 255, 255), (0, 0, 0, 255)
    cards, chunk = [], []

    def flush(chunk, idx):
        text_words = [c["w"].replace(", ", "-") for c in chunk]
        img = Image.new("RGBA", (vid_w, int(size * 2.2)), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        widths = [dr.textlength(w + " ", font=font) for w in text_words]
        total = sum(widths)
        x = max(10, (vid_w - total) / 2)
        y = int(size * 0.4)
        for i, w in enumerate(text_words):
            dr.text((x, y), w, font=font, fill=gold if i == 0 else white,
                    stroke_width=max(2, size // 14), stroke_fill=outline)
            x += widths[i]
        p = workdir / f"cap_{idx:04d}.png"
        img.save(p)
        cards.append({"png": str(p), "s": chunk[0]["s"], "e": chunk[-1]["e"]})

    for w in words:
        chunk.append(w)
        if len(chunk) >= max_words or (w["w"] and w["w"][-1] in ".!?"):
            flush(chunk, len(cards)); chunk = []
    if chunk:
        flush(chunk, len(cards))
    return cards

def build_caption_band(words: list[dict], workdir: Path, font_file: str,
                       vid_w: int, vid_h: int, fps: str, duration: float,
                       scale: float = 0.045, max_words: int = 4,
                       ) -> dict | None:
    """KARAOKE captions . Renders the caption strip as a transparent PNG frame-sequence:
    per video frame, the word being SPOKEN right now is gold, the rest
    white. Unique (chunk, active-word) states are rendered once and
    hardlinked per frame, so 6k frames cost ~600 renders. Composited as ONE
    overlay input."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        num, den = (fps.split("/") + ["1"])[:2]
        f_fps = float(num) / float(den or 1)
    except Exception:
        f_fps, fps = 30.0, "30"
    size = max(28, int(vid_h * scale))
    band_h = int(size * 2.2)
    font = ImageFont.truetype(font_file, size)
    gold, white, outline = (232, 199, 167, 255), (255, 255, 255, 255), (0, 0, 0, 255)
    # chunking identical to the card system
    chunks, cur = [], []
    for w in words:
        cur.append(dict(w, w=w["w"].replace(", ", "-")))
        if len(cur) >= max_words or (w["w"] and w["w"][-1] in ".!?"):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    seq = workdir / "capband"
    seq.mkdir(exist_ok=True)
    blank = seq / "_blank.png"
    Image.new("RGBA", (vid_w, band_h), (0, 0, 0, 0)).save(blank)

    state_cache: dict = {}

    def state_png(ci: int, ai: int) -> Path:
        key = (ci, ai)
        if key in state_cache:
            return state_cache[key]
        ch = chunks[ci]
        img = Image.new("RGBA", (vid_w, band_h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        widths = [dr.textlength(c["w"] + " ", font=font) for c in ch]
        x = max(10, (vid_w - sum(widths)) / 2)
        y = int(size * 0.4)
        for i, c in enumerate(ch):
            dr.text((x, y), c["w"], font=font,
                    fill=gold if i == ai else white,
                    stroke_width=max(2, size // 14), stroke_fill=outline)
            x += widths[i]
        p = seq / f"state_{ci:03d}_{ai:02d}.png"
        img.save(p)
        state_cache[key] = p
        return p

    total = int(duration * f_fps) + 1
    ci = 0
    for fi in range(total):
        t = fi / f_fps
        while ci < len(chunks) - 1 and t >= chunks[ci + 1][0]["s"]:
            ci += 1
        ch = chunks[ci]
        if ch[0]["s"] - 0.05 <= t <= ch[-1]["e"] + 0.05:
            ai = 0
            for i, c in enumerate(ch):
                if t >= c["s"]:
                    ai = i
            src_png = state_png(ci, ai)
        else:
            src_png = blank
        dst = seq / f"f_{fi:05d}.png"
        if dst.exists():
            dst.unlink()
        os.link(src_png, dst)
    log(f"captions: karaoke band, {len(chunks)} chunks, "
        f"{len(state_cache)} states, {total} frames")
    return {"seq": str(seq), "fps": fps, "band_h": band_h}


def build_srt(words: list[dict], out: Path):
    def ts(t):
        h = int(t // 3600); m = int(t % 3600 // 60); s = int(t % 60)
        ms = int((t - int(t)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    blocks, chunk, n = [], [], 1
    for w in words:
        chunk.append(w)
        if len(chunk) >= 8 or (w["w"] and w["w"][-1] in ".!?"):
            blocks.append(f"{n}\n{ts(chunk[0]['s'])} --> {ts(chunk[-1]['e'])}\n"
                          + " ".join(c["w"] for c in chunk).replace(", ", "-") + "\n")
            chunk = []; n += 1
    if chunk:
        blocks.append(f"{n}\n{ts(chunk[0]['s'])} --> {ts(chunk[-1]['e'])}\n"
                      + " ".join(c["w"] for c in chunk) + "\n")
    out.write_text("\n".join(blocks))

# ---------------------------------------------------------------- phase 5+6
def render_master(cut: Path, cards: list[dict], music: Path | None,
                  workdir: Path, vid_h: int, vid_w: int = 0,
                  gfx: list[dict] | None = None,
                  broll: list[dict] | None = None,
                  caption_margin_frac: float = 0.10,
                  sfx: list | None = None,
                  caption_band: dict | None = None) -> Path:
    gfx, broll, sfx = gfx or [], broll or [], sfx or []
    log(f"phase 5/6: composite {len(broll)} b-roll + {len(gfx)} graphics + "
        f"{len(cards)} caption cards + loudness pass 1")
    graded = workdir / "graded.mp4"
    margin = int(vid_h * caption_margin_frac)
    inputs = [FFMPEG, "-y", "-i", cut]
    pre, chain, cur, idx = [], [], "0:v", 0
    # 1) b-roll video overlays (bottom layer; audio untouched = J-cut feel)
    for b in broll:
        dur = max(0.5, b["e"] - b["s"])
        inputs += ["-ss", "0", "-t", f"{dur:.3f}", "-i", b["video"]]
        idx += 1
        pre.append(f"[{idx}:v]scale={vid_w}:{vid_h}:force_original_aspect_ratio=increase,"
                   f"crop={vid_w}:{vid_h},setpts=PTS-STARTPTS+{b['s']:.3f}/TB[br{idx}]")
        nxt = f"v{len(chain)+1}"
        chain.append(f"[{cur}][br{idx}]overlay="
                     f"enable='between(t,{b['s']:.3f},{b['e']:.3f})'[{nxt}]")
        cur = nxt
    # 2) animated branded graphics (alpha frame-sequences; motion + fades
    #    are baked into the frames by premium.build_graphics)
    for g in gfx:
        inputs += ["-framerate", "30", "-i", f"{g['seq']}/f_%04d.png"]
        idx += 1
        pre.append(f"[{idx}:v]format=rgba,"
                   f"setpts=PTS-STARTPTS+{g['s']:.3f}/TB[gx{idx}]")
        nxt = f"v{len(chain)+1}"
        chain.append(f"[{cur}][gx{idx}]overlay=x=0:y={g.get('y', int(vid_h*0.12))}"
                     f":enable='between(t,{g['s']:.3f},{g['e']:.3f})'[{nxt}]")
        cur = nxt
    # 3) word-synced captions (top layer): karaoke band preferred, cards legacy
    if caption_band:
        inputs += ["-framerate", caption_band["fps"], "-i",
                   f"{caption_band['seq']}/f_%05d.png"]
        idx += 1
        pre.append(f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS[capband]")
        nxt = f"v{len(chain)+1}"
        chain.append(f"[{cur}][capband]overlay=x=0:"
                     f"y=main_h-{caption_band['band_h']}-{margin}[{nxt}]")
        cur = nxt
    for c in cards:
        inputs += ["-i", c["png"]]
        idx += 1
        nxt = f"v{len(chain)+1}"
        chain.append(f"[{cur}][{idx}:v]overlay=x=0:y=main_h-overlay_h-{margin}"
                     f":enable='between(t,{c['s']:.3f},{c['e']:.3f})'[{nxt}]")
        cur = nxt
    vgraph = ";".join(pre + chain) if chain else "[0:v]null[vout]"
    if not chain:
        cur = "vout"
    # SFX bed . Each cue is
    # delayed to its timestamp and mixed UNDER the voice (normalize=0 keeps
    # dialogue level; cues carry their own gains).
    sfx_labels = []
    sparts = []
    for w, t, g in sfx:
        inputs += ["-i", str(w)]
        idx += 1
        ms = max(0, int(float(t) * 1000))
        sparts.append(f"[{idx}:a]adelay={ms}|{ms},volume={g:.2f}[sx{idx}]")
        sfx_labels.append(f"[sx{idx}]")
    if music and music.exists():
        inputs += ["-stream_loop", "-1", "-i", music]
        mi = idx + 1
        fc = (vgraph + ";" if chain else "[0:v]null[vout];") + (
            ";".join(sparts) + (";" if sparts else "") +
            f"[{mi}:a]volume=0.35[m];[0:a]asplit=2[voq][vok];"
            "[m][voq]sidechaincompress=threshold=0.03:ratio=12:attack=25:release=350[duck];"
            f"[vok][duck]{''.join(sfx_labels)}amix="
            f"inputs={2+len(sfx_labels)}:duration=first:normalize=0[a]")
        run(inputs + ["-filter_complex", fc, "-map", f"[{cur}]", "-map", "[a]",
                      "-shortest", "-c:v", "libx264", "-preset", "medium",
                      "-crf", "18", graded])
    elif sfx_labels:
        fc = (vgraph + ";" if chain else "[0:v]null[vout];") + \
             ";".join(sparts) + ";" + \
             f"[0:a]{''.join(sfx_labels)}amix=" \
             f"inputs={1+len(sfx_labels)}:duration=first:normalize=0[a]"
        run(inputs + ["-filter_complex", fc, "-map", f"[{cur}]",
                      "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                      "-crf", "18", "-c:a", "aac", "-b:a", "192k", graded])
    else:
        run(inputs + ["-filter_complex", vgraph, "-map", f"[{cur}]",
                      "-map", "0:a", "-c:v", "libx264", "-preset", "medium",
                      "-crf", "18", "-c:a", "aac", "-b:a", "192k", graded])
    # loudnorm 2-pass to -14 LUFS / -1 dBTP
    p1 = run([FFMPEG, "-y", "-i", graded, "-af",
              "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
             check=False)
    stats = {}
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p1.stderr.decode(errors="replace"))
    if m:
        stats = json.loads(m.group(0))
    master = workdir / "MASTER_16x9.mp4"
    ln = ("loudnorm=I=-14:TP=-1:LRA=11:linear=true:"
          f"measured_I={stats.get('input_i','-24')}:measured_TP={stats.get('input_tp','-2')}:"
          f"measured_LRA={stats.get('input_lra','7')}:measured_thresh={stats.get('input_thresh','-34')}")
    run([FFMPEG, "-y", "-i", graded, "-af", ln, "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", master])
    return master

def variants(master: Path, outdir: Path, w: int, h: int) -> dict:
    log("phase 6: aspect variants 9:16 + 1:1")
    out = {"16x9": outdir / "PSE_MASTER_16x9.mp4",
           "9x16": outdir / "PSE_VERTICAL_9x16.mp4",
           "1x1": outdir / "PSE_SQUARE_1x1.mp4"}
    if h > w:
        # PORTRAIT source: a real 16:9 needs a canvas, not a relabel
        # (2026-07-23: the "16x9" for a vertical lesson was just the vertical
        # master, wrong for YouTube). Blurred-fill pillarbox, subject
        # centered, the standard vertical-on-YouTube treatment. The minimal
        # ffmpeg build has no blur filter, so scale-down/up IS the blur.
        run([FFMPEG, "-y", "-i", master, "-filter_complex",
             "[0:v]split=2[a][b];"
             "[a]scale=64:36,scale=1920:1080:flags=bicubic,crop=1920:1080[bg];"
             "[b]scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "copy", out["16x9"]])
    else:
        shutil.copy(master, out["16x9"])
    # aspect-aware center crops, valid for landscape AND portrait sources
    run([FFMPEG, "-y", "-i", master, "-vf",
         "crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9),scale=1080:1920",
         "-c:a", "copy", out["9x16"]])
    run([FFMPEG, "-y", "-i", master, "-vf",
         "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080",
         "-c:a", "copy", out["1x1"]])
    return out

# ---------------------------------------------------------------- phase 7+8
def qa_and_release(outs: dict, ass_font_ok: bool, words: list[dict],
                   outdir: Path, retention: float = 1.0,
                   edl: dict | None = None) -> dict:
    log("phase 7: QA gate")
    qa = {"checks": {}, "pass": True}
    # 2026-07-23 incident guard: a silence-cut that deletes actual speech
    # must NEVER pass QA silently. retention==1.0 means source-uncut fallback.
    qa["checks"]["speech_retention"] = {
        "kept_ratio": round(retention, 3),
        "ok": retention >= 0.55,
        "note": "" if retention >= 0.55 else
                "silence-cut removed too much, likely quiet audio; "
                "re-record closer to mic or re-run (guardrail should have "
                "shipped source uncut)"}
    primary = next(iter(outs.values()))
    p = run([FFMPEG, "-i", primary, "-af",
             "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"], check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr.decode(errors="replace"))
    li = float(json.loads(m.group(0))["input_i"]) if m else None
    qa["checks"]["loudness_-14LUFS"] = {"measured": li,
                                        "ok": li is not None and -15.5 <= li <= -12.5}
    bd = run([FFMPEG, "-i", primary, "-vf", "blackdetect=d=0.5:pix_th=0.10",
              "-an", "-f", "null", "-"], check=False)
    runs = [(float(m.group(1)), float(m.group(2))) for m in re.finditer(
        r"black_start:([\d.]+) black_end:([\d.]+)",
        bd.stderr.decode(errors="replace"))]
    # BRAND-AWARE (2026-07-25): brand diagrams and stat cards are gold-on-black
    # by design, so their fade-in reads as "black frames". A dark run inside a
    # viz/graphic window is the look you asked for, not a dropped frame.
    dark_ok = []
    for k in ("broll", "graphics"):
        for ev in (edl or {}).get(k, []):
            if k == "graphics" or ev.get("viz"):
                dark_ok.append((float(ev["s"]) - 0.5, float(ev["e"]) + 0.5))
    real = [r for r in runs
            if not any(a <= r[0] and r[1] <= b for a, b in dark_ok)]
    qa["checks"]["no_black_frames"] = {
        "black_runs": len(real), "ok": not real,
        "note": (f"{len(runs) - len(real)} dark run(s) inside intentional "
                 "diagram/card windows, not counted") if len(runs) != len(real) else ""}
    qa["checks"]["no_em_dash"] = {"ok": not any(", " in w["w"] for w in words)}
    qa["checks"]["captions_present"] = {"ok": len(words) > 0}
    qa["checks"]["brand_font_worksans"] = {"ok": ass_font_ok,
        "note": "" if ass_font_ok else "WorkSans not installed, fell back to Arial Black. Install Work Sans for full brand compliance."}
    qa["checks"]["all_variants"] = {"ok": all(v.exists() and v.stat().st_size > 0
                                              for v in outs.values())}
    qa["pass"] = all(c["ok"] for c in qa["checks"].values()
                     if isinstance(c, dict) and "ok" in c and
                     # font fallback is a warning, not a release blocker
                     c is not qa["checks"]["brand_font_worksans"])
    log("phase 8: hash-lock release")
    qa["release"] = {}
    for k, v in outs.items():
        qa["release"][k] = {"file": str(v),
                            "sha256": hashlib.sha256(v.read_bytes()).hexdigest()}
    (outdir / "QA_REPORT.json").write_text(json.dumps(qa, indent=2))
    return qa

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(prog="autoedit")
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--music", type=Path, default=None)
    ap.add_argument("--no-burn", action="store_true",
                    help="don't burn captions; sidecar srt only")
    ap.add_argument("--style", choices=["auto", "short", "long"], default="auto",
                    help="edit grammar: 'short' = reels/shorts pacing (dense, "
                         "hook-first, big captions), 'long' = talking-head "
                         "lesson pacing. auto = portrait + <=95s -> short")
    ap.add_argument("--no-premium", action="store_true",
                    help="skip punch-ins / b-roll / graphics (baseline edit)")
    ap.add_argument("--no-llm", action="store_true",
                    help="premium EDL via heuristic only (skip DeepSeek call)")
    ap.add_argument("--aspects", choices=["auto", "16x9", "9x16", "all"],
                    default="auto",
                    help="long-form ships ONE 16:9 file, shorts ship ONE 9:16 "
                         "file. 'auto' picks by --style; "
                         "explicit values override; 'all' renders everything")
    ap.add_argument("--edl", type=Path, default=None,
                    help="use a hand-authored EDL json (director mode); "
                         "skips DeepSeek/heuristic")
    ap.add_argument("--background", type=Path, default=None,
                    help="backdrop image: chromakey the green screen and "
                         "composite this behind you (zone-key chain)")
    ap.add_argument("--script", type=Path, default=None,
                    help="the teleprompter script you read (md/txt): ground "
                         "truth for caption text + word-integrity QA")
    ap.add_argument("--av-offset", type=int, default=AV_OFFSET_MS,
                    help="source AV offset correction in ms; positive = delay "
                         "audio (audio leads video). Default comes from brand.yaml "
                         f"(currently {AV_OFFSET_MS}ms; run `make calibrate`)")
    a = ap.parse_args()
    src = a.video.expanduser().resolve()
    if not src.exists():
        sys.exit(f"no such file: {src}")
    orig_src = src   # the raw recording: reference for verify_sync_source
    outdir = (a.out or src.parent / f"{src.stem}_PSE_EDIT").resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pse-edit-"))
    t0 = time.time()
    info = preflight(src)
    fixed = deletterbox(src, work)
    if fixed != src:
        src = fixed
    # CERTIFIED OFFSET: the only trusted source of a nonzero correction is a
    # human calibration stored in a sidecar next to the recording
    # ("<video>.avoffset", integer ms). A bare --av-offset still renders, but
    # gate 5 refuses to certify a correction that no human certified.
    cert_file = Path(str(orig_src) + ".avoffset")
    certified = 0
    if cert_file.exists():
        try:
            certified = int(cert_file.read_text().strip())
            log(f"av-offset: certified {certified:+d}ms from {cert_file.name}")
        except ValueError:
            log(f"av-offset: unreadable sidecar {cert_file.name}, treating as 0")
    offset = a.av_offset if a.av_offset else certified
    if offset:
        log(f"av-offset: applying {offset:+d}ms"
            + ("" if offset == certified else " (NOT CERTIFIED)"))
    src = cfr_normalize(src, work, av_offset_ms=offset)
    info = preflight(src)   # re-probe: TRUE orientation + exact CFR fps
    # ---- style profile: shorts/reels grammar vs long-form lesson grammar
    style = a.style
    if style == "auto":
        style = ("short" if info["height"] > info["width"]
                 and info["duration"] <= 95 else "long")
    PROFILE = {
        # margin: silence padding | caption scale/words/margin: bigger cards,
        # fewer words, lifted clear of the platform UI on shorts
        "long":  {"margin": "0.15s", "cap_scale": 0.045, "cap_words": 4,
                  "cap_margin": 0.10},
        "short": {"margin": "0.06s", "cap_scale": 0.062, "cap_words": 3,
                  "cap_margin": 0.24},
    }[style]
    log(f"phase 1: {info['width']}x{info['height']} {info['duration']:.1f}s "
        f"ok, style={style}")
    cut, retention, raw_words = word_guarded_cut(
        src, work, min_pause=(0.55 if style == "short" else 0.9))
    # every downstream layer (caption band length above all) is built against
    # info["duration"], leaving the PRE-cut value stretched the master ~21s
    # past the end of speech with a dead tail (2026-07-24).
    info["duration"] = _dur(cut)
    words = transcribe(cut, work)
    log(f"phase 3: {len(words)} words post-cut "
        f"(raw had {len(raw_words)})")
    # ---- cleanup pass: flubbed retakes + dead air the raw pass missed.
    # Runs in AUTO mode only; in director mode (--edl) you owns every cut.
    if not (a.edl and a.edl.exists()):
        cleanup = (detect_retakes(words, script_path=a.script)
                   + detect_false_starts(words, a.script)
                   + detect_lead_noise(words)
                   + detect_head_noise_audio(cut)
                   + detect_dead_air(words, _dur(cut),
                                     min_pause=(0.55 if style == "short" else 0.9)))
        merged = []
        for c in sorted(cleanup, key=lambda x: x["s"]):
            if merged and c["s"] <= merged[-1]["e"] + 0.05:
                merged[-1]["e"] = max(merged[-1]["e"], c["e"])
            else:
                merged.append(dict(c))
        merged = [c for c in merged if c["e"] - c["s"] > 0.15]
        if merged:
            cut = apply_cuts(cut, merged, work)
            info["duration"] = _dur(cut)
            log("phase 2B: re-transcribing after retake/dead-air cleanup")
            words = transcribe(cut, work)
    if a.script and a.script.exists():
        words = script_correct(words, a.script)
    # auto anomaly removal (coughs/garbled audio). AUTO MODE ONLY; in
    # director mode (--edl) the director owns every cut decision.
    if not (a.edl and a.edl.exists()):
        anomalies = detect_anomaly_cuts(cut, words, a.script)
        if anomalies:
            cut = apply_cuts(cut, anomalies, work)
            log("phase 3A: re-transcribing post-anomaly timeline")
            words = transcribe(cut, work)
            info["duration"] = _dur(cut)
    font_file, font_ok = _font_file(CFG.brand)
    # ---- premium layer: DeepSeek EDL -> punch-ins, b-roll, graphic cards
    gfx_layers, broll_lyrs, edl_src = [], [], "off"
    if not a.no_premium and words:
        from . import premium as prem
        if a.background and a.background.exists():
            cut = prem.apply_background(cut, a.background, work, FFMPEG,
                                        info["width"], info["height"])
        clips = prem.load_kling()
        if a.edl and a.edl.exists():
            edl, edl_src = json.loads(a.edl.read_text()), "director"
            for k in ("punch_ins", "broll", "graphics"):
                edl.setdefault(k, [])
            if edl.get("cuts"):
                cut = apply_cuts(cut, edl["cuts"], work)
                log("phase 3R: re-transcribing post-cut timeline")
                words = transcribe(cut, work)
                info["duration"] = _dur(cut)
        else:
            edl, edl_src = prem.make_edl(words, clips, info["duration"],
                                         use_llm=not a.no_llm, style=style)
        log(f"phase 4p: EDL via {edl_src}, {len(edl['punch_ins'])} punch-ins, "
            f"{len(edl['broll'])} b-roll ({len(clips)} clips avail), "
            f"{len(edl['graphics'])} graphics")
        (outdir / "EDL.json").write_text(json.dumps(
            {"source": edl_src, **edl}, indent=2))
        cut = prem.apply_punchins(cut, edl, work, FFMPEG,
                                  info["width"], info["height"],
                                  fps=str(info.get("fps", "30")))
        if font_file:
            gfx_layers = prem.build_graphics(edl, work, font_file,
                                             info["width"], info["height"])
        broll_lyrs = prem.broll_layers(
            edl, clips, portrait=info["height"] > info["width"],
            vid_w=info["width"], vid_h=info["height"])
    cards, caption_band = [], None
    if words and not a.no_burn and font_file:
        caption_band = build_caption_band(
            words, work, font_file, info["width"], info["height"],
            str(info.get("fps", "30")), info["duration"],
            scale=PROFILE["cap_scale"], max_words=PROFILE["cap_words"])
        if not caption_band:
            cards = build_caption_pngs(words, work, font_file,
                                       info["width"], info["height"],
                                       scale=PROFILE["cap_scale"],
                                       max_words=PROFILE["cap_words"])
    srt = outdir / "PSE_CAPTIONS.srt"
    if words:
        build_srt(words, srt)
    sfx_plan = []
    if not a.no_premium and words:
        sfx_plan = prem.build_sfx_plan(edl)
        log(f"sound design: {len(sfx_plan)} SFX cues")
    master = render_master(cut, cards, a.music, work, info["height"],
                           vid_w=info["width"], gfx=gfx_layers,
                           broll=broll_lyrs,
                           caption_margin_frac=PROFILE["cap_margin"],
                           sfx=sfx_plan, caption_band=caption_band)
    aspects = a.aspects
    if aspects == "auto":
        # Standing law 2026-07-23: long-form -> 16:9 only, shorts -> 9:16 only
        aspects = "9x16" if style == "short" else "16x9"
    if aspects == "all":
        outs = variants(master, outdir, info["width"], info["height"])
    elif aspects == "9x16":
        only = outdir / "PSE_SHORT_9x16.mp4"
        if info["width"] > info["height"]:
            run([FFMPEG, "-y", "-i", master, "-vf",
                 "crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9),scale=1080:1920",
                 "-c:a", "copy", only])
        else:
            shutil.copy(master, only)
        outs = {"9x16": only}
    else:
        only = outdir / "PSE_MASTER_16x9.mp4"
        if info["height"] > info["width"]:
            run([FFMPEG, "-y", "-i", master, "-filter_complex",
                 "[0:v]split=2[a][b];"
                 "[a]scale=64:36,scale=1920:1080:flags=bicubic,crop=1920:1080[bg];"
                 "[b]scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                 "-c:a", "copy", only])
        else:
            shutil.copy(master, only)
        outs = {"16x9": only}
    qa = qa_and_release(outs, font_ok, words, outdir, retention=retention,
                        edl=(edl if (not a.no_premium and words) else None))
    # HARD GATE : mechanical lip-sync verification. The
    # video is never delivered unless every probe passes.
    main_out_v = next(iter(outs.values()))
    sync = verify_sync(main_out_v, cut,
                       edl if (not a.no_premium and words) else {},
                       _dur(main_out_v))
    qa["checks"]["lip_sync_verified"] = {"ok": sync["ok"],
                                         "probes": sync["probes"]}
    # GATE 4: no flubbed take may survive into the delivered file.
    residue = verify_no_retakes(final_words, a.script, work)
    qa["checks"]["retake_residue"] = residue
    qa["pass"] = qa["pass"] and residue["ok"]
    qa["pass"] = qa["pass"] and sync["ok"]
    # HARD GATE 2 : the delivered
    # master must still CONTAIN the speech. Transcribe the final master and
    # sequence-align against the post-cut transcript; if >3% of words went
    # missing anywhere in the chain, delivery is blocked.
    import difflib as _dl
    final_words = transcribe(main_out_v, work)
    _n = lambda t: re.sub(r"[^a-z0-9']", "", t.lower())
    _sm = _dl.SequenceMatcher(a=[_n(w["w"]) for w in words],
                              b=[_n(w["w"]) for w in final_words],
                              autojunk=False)
    _kept = sum(i2 - i1 for op, i1, i2, _, _ in _sm.get_opcodes()
                if op == "equal")
    word_ratio = _kept / max(1, len(words))
    # 0.92, not 0.97: this compares whisper against whisper on the SAME audio,
    # and its own run-to-run variance is ~1-3% (v6 read 96.3% on a master the
    # semantic judge passed clean). Real damage is nothing like marginal, # the 2026-07-24 incident scored 75%. script_integrity is the sharp gate.
    missing = len(words) - _kept
    wi_ok = word_ratio >= 0.96 and missing <= 40
    qa["checks"]["word_integrity"] = {
        "expected_words": len(words), "found_in_master": _kept,
        "ratio": round(word_ratio, 3), "ok": wi_ok,
        "note": "" if wi_ok else "words missing from final master, "
                "speech was damaged after the cut phase"}
    qa["pass"] = qa["pass"] and wi_ok
    log(f"word integrity: {_kept}/{len(words)} words in master "
        f"({word_ratio:.1%}), {'PASS' if wi_ok else 'FAIL - DELIVERY BLOCKED'}")
        # GATE 5: true end-to-end sync, master vs the raw recording.
    ssync = verify_sync_source(main_out_v, orig_src,
                               edl if (not a.no_premium and words) else {},
                               offset, certified, final_words, work)
    qa["checks"]["sync_to_source"] = ssync
    qa["pass"] = qa["pass"] and ssync["ok"]
    # HARD GATE 3: semantic comparison to the teleprompter script. Paraphrase,
    # elaboration and skipped sentences are FINE ; only sentences
    # the edit damaged mid-thought block delivery.
    if a.script and a.script.exists():
        si = script_integrity(final_words, a.script, work)
        qa["checks"]["script_integrity"] = si
        qa["pass"] = qa["pass"] and si["ok"]
        shutil.copy(work / "script_integrity.json",
                    outdir / "SCRIPT_INTEGRITY.json") if (
                        work / "script_integrity.json").exists() else None
    (outdir / "QA_REPORT.json").write_text(json.dumps(qa, indent=2))
    log(f"lip-sync verification: {'PASS' if sync['ok'] else 'FAIL - DELIVERY BLOCKED'}")
    if not qa["pass"]:
        # a failed master must not sit on disk under a final-looking name
        demoted = {}
        for k, v in list(outs.items()):
            q = v.with_name(v.stem + ".UNVERIFIED" + v.suffix)
            try:
                v.rename(q)
                demoted[k] = q
                qa["release"][k]["file"] = str(q)
            except OSError:
                pass
        if demoted:
            outs.update(demoted)
            (outdir / "QA_REPORT.json").write_text(json.dumps(qa, indent=2))
            log("QA failed: master(s) renamed *.UNVERIFIED - not for upload")
    log(f"DONE in {time.time()-t0:.0f}s → {outdir}")
    log(f"QA: {'PASS ✅' if qa['pass'] else 'FAIL ❌ (see QA_REPORT.json)'}")
    # One Telegram ping per COMPLETED render (full pipeline: master + all
    # variants + QA + hash-lock). Previews/partials never reach this line.
    try:
        mins = int(_dur(next(iter(outs.values()))) // 60)
        secs = int(_dur(next(iter(outs.values()))) % 60)
        verdict = "QA PASS ✅" if qa["pass"] else "QA NEEDS REVIEW ❌"
        providers.notify(f"Render complete: {src.stem}\n"
                         f"{mins}:{secs:02d} - {verdict}\n-> {outdir}")
        # deliver the video itself ONLY when lip-sync verification passed
        # .
        if not qa["checks"].get("lip_sync_verified", {}).get("ok"):
            raise RuntimeError("sync unverified - video delivery blocked")
        if not qa["checks"].get("word_integrity", {}).get("ok"):
            raise RuntimeError("words missing - video delivery blocked")
        if not qa["checks"].get("script_integrity", {"ok": True}).get("ok"):
            raise RuntimeError("script damage - video delivery blocked")
        if not qa["checks"].get("retake_residue", {"ok": True}).get("ok"):
            raise RuntimeError("flubbed take survived - video delivery blocked")
        if not qa["checks"].get("sync_to_source", {"ok": True}).get("ok"):
            raise RuntimeError("master out of sync with the raw recording - "
                               "video delivery blocked")
        # Most chat APIs cap uploads around 50MB. Master fits -> send as-is (full
        # quality). Too big -> 1080p phone copy; full master stays on disk.
        main_out = next(iter(outs.values()))
        if main_out.stat().st_size <= 49 * 1024 * 1024:
            tg_file = main_out
        else:
            tg_file = work / "tg_copy.mp4"   # was `workdir` (undefined), # NameError was swallowed by the catch-all below, so large
            # masters silently never reached Telegram (2026-07-24).
            d = _dur(main_out) or 1
            vbit = max(800, int(46 * 8192 / d - 128))
            run([FFMPEG, "-y", "-i", main_out, "-vf",
                 "scale='min(1920,iw)':-2",
                 "-c:v", "libx264", "-preset", "medium",
                 "-b:v", f"{vbit}k", "-maxrate", f"{vbit+300}k",
                 "-bufsize", f"{vbit*2}k", "-c:a", "aac", "-b:a", "128k",
                 "-movflags", "+faststart", tg_file], check=False)
        if tg_file != main_out and tg_file.exists():
            if abs((_dur(tg_file) or 0) - (_dur(main_out) or 0)) > 0.05:
                raise RuntimeError("watch copy duration differs from the "
                                   "gated master - not sending it")
        if tg_file.exists():
            caption = (f"{src.stem} - watch copy"
                       + ("" if tg_file == main_out else
                          " (1080p; full-quality master is on disk)"))
            # explicit dimensions or the player renders a square bubble
            providers.send_video(tg_file, caption,
                                 width=info["width"], height=info["height"])
    except Exception as e:
        # delivery must never fail the render -- but it must never fail
        # SILENTLY either: an undefined name here once hid every large-file
        # send, and the only symptom was "the video never arrived".
        log(f"delivery: {type(e).__name__}: {e}")
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(0 if qa["pass"] else 2)

if __name__ == "__main__":
    main()
