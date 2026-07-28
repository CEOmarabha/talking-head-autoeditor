#!/usr/bin/env python3
"""premium, the creative layer: punch-ins, b-roll, motion graphics, SFX.

One cheap LLM pass (DeepSeek V4 Flash by default) turns the word-level transcript into an EDL:

  { "punch_ins": [{"s","e","scale"}],          # zoom on emphasis
    "broll":     [{"s","e","family"}],         # local clip-library overlays
    "graphics":  [{"s","e","text"}] }          # branded keyword cards

A deterministic heuristic produces the same EDL shape when the LLM is
unavailable, times out, or returns junk, the pipeline NEVER blocks on a
model. Renderers are pure ffmpeg/Pillow:

  * punch-ins, segment-wise 1.08x center zoom, original audio remuxed
                 untouched (so audio pacing is never damaged)
  * b-roll, video-only overlays from non-REJECT user clip-catalog rows
                 (audio continues under the insert = natural J-cut feel)
  * graphics. Pillow gold/white keyword cards, upper third, faded via
                 ffmpeg fade (restrained enterprise motion, no slideshow)
"""
from __future__ import annotations
import csv, json, os, re, shutil, subprocess, tempfile, time
from pathlib import Path

from . import providers
from .config import (Config, CACHE, SFX_DIR as _SFX_DIR,
                     HOME_DATA as CFGH, VIZ_PROJECT)

CFG = Config.load()

# Free stock B-roll (Pexels). Key file is created once by you (free account,
# https://www.pexels.com/api/): echo 'KEY' > ~/.autoeditor/pexels.key
PEXELS_KEY_FILE = CFGH / "pexels.key"
PIXABAY_KEY_FILE = CFGH / "pixabay.key"
BROLL_CACHE = CACHE
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 autoeditor/1.0")
CLIP_CATALOGS = [
    *[Path(x) for x in os.environ.get("CLIP_CATALOGS", "").split(":") if x],
]


def _api_key(env_var: str, key_file: Path) -> str:
    """Env var first (what .env and the docs use), then a key file on disk."""
    return (os.environ.get(env_var, "").strip()
            or (key_file.read_text().strip() if key_file.exists() else ""))


def _run(cmd, **kw):
    kw.setdefault("check", True)
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    return subprocess.run([str(c) for c in cmd], **kw)


def log(msg):
    print(f"[pse-premium {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ kling
def load_kling(limit: int = 200) -> list[dict]:
    """Usable (non-REJECT, on-disk) clips from the clip catalogs."""
    clips, seen = [], set()
    for cat in CLIP_CATALOGS:
        if not cat.exists():
            continue
        try:
            for row in csv.DictReader(cat.open()):
                p = (row.get("path") or "").strip()
                rating = (row.get("rating") or "").strip().upper()
                fam = (row.get("scene_family") or row.get("category") or "").strip()
                if not p or p in seen or rating.startswith("REJECT"):
                    continue
                if not Path(p).exists():
                    continue
                seen.add(p)
                clips.append({"path": p, "family": fam,
                              "dur": float(row.get("duration_sec") or 5)})
                if len(clips) >= limit:
                    return clips
        except Exception as e:
            log(f"clip catalog {cat.name}: skip ({e})")
    return clips


# ------------------------------------------------------------------ EDL
def _sentences(words: list[dict]) -> list[dict]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if w["w"] and w["w"][-1] in ".!?":
            out.append({"text": " ".join(c["w"] for c in cur),
                        "s": cur[0]["s"], "e": cur[-1]["e"]})
            cur = []
    if cur:
        out.append({"text": " ".join(c["w"] for c in cur),
                    "s": cur[0]["s"], "e": cur[-1]["e"]})
    return out


_STYLE_SPACING = {
    # min seconds between events: (punch, broll, gfx)
    "long": (10, 14, 20),
    "short": (5, 7, 8),
}


def heuristic_edl(words: list[dict], clips: list[dict], duration: float,
                  style: str = "long") -> dict:
    """Deterministic fallback: alternate punch-ins on emphasis sentences,
    b-roll on scene-family keyword hits, graphic cards on number/keyword
    sentences. Spacing comes from the style profile (shorts = denser)."""
    sp_punch, sp_broll, sp_gfx = _STYLE_SPACING.get(style, _STYLE_SPACING["long"])
    sents = _sentences(words)
    edl = {"punch_ins": [], "broll": [], "graphics": []}
    last_punch = last_broll = last_gfx = -99.0
    fams = {c["family"]: c for c in clips if c["family"]}
    for i, s in enumerate(sents):
        txt = s["text"].lower()
        emphatic = ("?" in s["text"] or any(ch.isdigit() for ch in txt)
                    or i == 0 or len(txt.split()) <= 6)
        if i == 0:
            # HOOK: the opening line always gets a punch-in, even if short, # dead-static first seconds are the #1 retention killer.
            edl["punch_ins"].append({"s": round(s["s"], 2),
                                     "e": round(max(s["e"], s["s"] + 2.5), 2),
                                     "scale": 1.1})
            last_punch = s["s"]
        elif emphatic and s["s"] - last_punch >= sp_punch and s["e"] - s["s"] >= 1.2:
            edl["punch_ins"].append({"s": round(s["s"], 2), "e": round(s["e"], 2),
                                     "scale": 1.08})
            last_punch = s["s"]
        for fam in fams:
            toks = [t for t in re.split(r"[_\s]+", fam.lower()) if len(t) > 3]
            if toks and any(t in txt for t in toks) and s["s"] - last_broll >= sp_broll:
                dur = min(3.5, max(2.0, s["e"] - s["s"]))
                edl["broll"].append({"s": round(s["s"], 2),
                                     "e": round(s["s"] + dur, 2), "family": fam})
                last_broll = s["s"]
                break
        m = re.search(r"\b(\d[\d.]*%?|status|system|autopilot|research)\b", txt)
        if m and s["s"] - last_gfx >= sp_gfx:
            edl["graphics"].append({"s": round(s["s"], 2),
                                    "e": round(min(s["s"] + 3.0, duration), 2),
                                    "text": m.group(1).upper()})
            last_gfx = s["s"]
    return edl


def deepseek_edl(words: list[dict], clips: list[dict], duration: float,
                 style: str = "long") -> dict | None:
    """One cheap LLM pass -- ~1 cent per video on DeepSeek V4 Flash."""
    sp_punch, sp_broll, sp_gfx = _STYLE_SPACING.get(style, _STYLE_SPACING["long"])
    style_rules = (
        f"STYLE: SHORTS/REELS. This is a retention-first vertical short: land a HOOK "
        f"in the first 2s (a punch-in or a graphic on the opening line), keep energy "
        f"high, punch-ins up to one per {sp_punch}s with scale 1.08-1.15, b-roll "
        f"1.5-3s up to one per {sp_broll}s, graphics up to one per {sp_gfx}s. "
        f"Still enterprise-premium: NO cheesy zoom spam, every event must map to "
        f"the words being said."
        if style == "short" else
        f"STYLE: LONG-FORM LESSON. Restrained enterprise pacing: punch-ins at most "
        f"one per {sp_punch}s, b-roll one per {sp_broll}s, graphics one per {sp_gfx}s. "
        f"EXCEPTION - MANDATORY HOOK WINDOW (first 15s is retention-critical): "
        f"place a punch-in (1.08-1.12) ON the very first spoken sentence starting "
        f"within 1s of speech, plus at least one b-roll or graphic event inside the "
        f"first 8s, and keep at least one visual event per 8s until 15s. After 15s, "
        f"relax to the restrained pacing above."
    )
    sents = _sentences(words)
    transcript = "\n".join(f"[{s['s']:.1f}-{s['e']:.1f}] {s['text']}" for s in sents)[:6000]
    families = sorted({c["family"] for c in clips if c["family"]})[:40]
    prompt = f"""You are an edit-decision engine for a premium talking-head video (enterprise education, restrained motion). Return ONLY valid JSON, no prose, exactly this shape:
{{"punch_ins":[{{"s":0.0,"e":0.0,"scale":1.08}}],"broll":[{{"s":0.0,"e":0.0,"query":"<2-4 word stock footage search>","family":"<name or empty>","viz":{{"template":"flow|steps|stat","title":"<max 4 words>","items":["<short>"],"value":"<number - stat only>"}}}}],"graphics":[{{"s":0.0,"e":0.0,"kind":"keyword|stat|callout|bars","text":"<max 4 words>","value":"<number like 87% - stat kind only>","items":[{{"label":"<short>","value":0}}]}}]}}

{style_rules}
Rules: punch-ins ONLY on genuinely emphatic sentences. B-roll overlays 2-4s (viz may run 3-6s). Choose the SOURCE per moment: include "viz" ONLY when the speaker is explaining a process/method/system/statistic that an ANIMATED DIAGRAM shows better than footage, "flow" = pipeline/stages assembling (items = 2-5 stage names), "steps" = numbered method steps (items = 2-5 step labels), "stat" = one dominant number scene (value + title). Otherwise omit "viz" and give "query": a concrete visual stock-footage search matching what is being SAID (e.g. "city skyline aerial night", "hands typing laptop closeup"), premium/enterprise imagery only, no cheesy stock-people-smiling. "family" is an optional local-library fallback from this list (or ""): {families}. Always include query as fallback even with viz. Graphics: ALL CAPS text <=4 words, never an em dash. Choose the kind that VISUALIZES the moment: "stat" when a number/percentage is spoken (put the number in "value", the description in "text"); "bars" when 2-3 quantities are compared (fill "items"); "callout" for a floating side-note or emphasis phrase; "keyword" for a plain concept card. Only include "items" for bars, only "value" for stat. Times must lie within 0-{duration:.1f}s and not overlap within the same list. Fewer, well-chosen events beat many.

DIRECTOR PRINCIPLES (learned from hand-edited exemplars, follow them):
1. Numbers that are SPOKEN become stat scenes ("500 million years" -> value 500,000,000 counting up while the words land).
2. The flagship framework moment gets the ANIMATED DIAGRAM (viz), timed so the diagram plays while the voice lists the parts, then the face returns for the punchline.
3. Named laws and definitions become cards AT the sentence that states them ("one goes weak, the others come down" -> callout ONE FALLS, ALL THREE FALL). Short, ALL CAPS, max 4 words preferred.
4. Story beats (a meeting, a memory, a scene the speaker paints) get literal stock b-roll; abstract claims get punch-ins instead, never literal b-roll.
5. Parallel concepts get a SYSTEM: same graphic kind, same rhythm, one per concept (three pillars -> three keyword cards, one each, consistent style).
6. Punch-ins land on verdict sentences (short, declarative, conclusive), NOT on transitions. Vary 1.08 for emphasis, 1.10 for the biggest lines.
7. Ad-libbed authentic moments (off-script energy spikes) get HONORED with an event, not ignored.
8. B-roll taste: prefer ABSTRACT MACRO, animated-looking footage (neurons firing, particles, light trails, ink in water, cosmos) for abstract concepts. Literal office/people stock only for literal story beats. Abstract macro reads as intentional; literal stock reads as filler.
9. Density: at least ONE animated diagram (viz) whenever a framework, list, or numbered idea is taught. When in doubt, add the diagram.
EXAMPLE (from a hand-directed edit of a lesson opening "Your brain ran a verdict on your worth today.. the Lizard Brain has been assigning status for 500 million years.. three signals: Superiority, Autonomy, Certainty.. when one goes weak the others come down"):
{{"punch_ins":[{{"s":0.0,"e":4.8,"scale":1.1}},{{"s":40.9,"e":43.4,"scale":1.08}}],"broll":[{{"s":59.2,"e":63.2,"query":"tense business meeting interruption","family":""}},{{"s":86.5,"e":92.5,"query":"three marble pillars columns","family":"","viz":{{"template":"steps","title":"THE THREE SIGNALS","items":["SUPERIORITY","AUTONOMY","CERTAINTY"]}}}}],"graphics":[{{"s":17.2,"e":20.8,"kind":"stat","text":"YEARS OF STATUS SCANNING","value":"500,000,000"}},{{"s":99.0,"e":101.9,"kind":"callout","text":"ONE FALLS, ALL THREE FALL"}}]}}

Transcript with [start-end] seconds:
{transcript}"""
    try:
        # timeout scales with transcript size: a 6-minute lesson needs far
        # longer than a 60-second reel, and a premature timeout silently
        # downgrades the whole creative layer to the heuristic.
        edl_timeout = min(600, 180 + len(transcript) // 15)
        parsed = providers.llm_json(
            prompt, require=("punch_ins", "broll", "graphics"),
            timeout=edl_timeout)
        if parsed is None:
            log("LLM EDL: unavailable or unparsable reply")
            return None
        edl = {}
        for key in ("punch_ins", "broll", "graphics"):
            evs = parsed.get(key) or []
            edl[key] = [ev for ev in evs
                        if isinstance(ev, dict)
                        and 0 <= float(ev.get("s", -1)) < float(ev.get("e", 0)) <= duration + 1]
        fams = {c["family"] for c in clips}
        # keep a b-roll slot if it has a viz template, stock query, or family
        edl["broll"] = [b for b in edl["broll"]
                        if (isinstance(b.get("viz"), dict)
                            and str(b["viz"].get("template", "")).lower() in _VIZ_TEMPLATES)
                        or (b.get("query") or "").strip()
                        or b.get("family") in fams]
        # only trust the LLM result if it produced at least one usable event
        if not any(edl[k] for k in ("punch_ins", "broll", "graphics")):
            return None
        return edl
    except Exception as e:
        log(f"deepseek EDL failed ({type(e).__name__}), heuristic fallback")
        return None


STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
             "your", "you", "it", "is", "are", "that", "this", "with", "not",
             "was", "be", "as", "at", "but", "they", "their", "all", "one",
             "years", "never", "every", "what", "when", "how", "why", "who"}


def align_edl_to_speech(edl: dict, words: list[dict], duration: float) -> dict:
    """PLACEMENT GUARD (2026-07-25): DeepSeek put the THREE SIGNALS diagram at
    79s while the speaker was mid-sentence -- the actual
    SAC reveal was at 104s. A visual that names concepts the speaker has not
    reached yet is the most visible possible error.

    Every visual carries its own keywords (viz title+items, graphic text and
    value, b-roll query). Find where those words are ACTUALLY spoken and snap
    the event there, keeping its duration. Events whose keywords never appear
    (mood/abstract b-roll like 'light particles') are left alone."""
    if not words:
        return edl

    def toks(*parts):
        out = set()
        for p in parts:
            for t in re.findall(r"[A-Za-z0-9']+", str(p or "")):
                t = t.lower()
                if len(t) > 3 and t not in STOPWORDS:
                    out.add(t)
        return out

    spoken = [(re.sub(r"[^a-z0-9']", "", w["w"].lower()), float(w["s"]))
              for w in words]
    moved = 0
    for key in ("broll", "graphics"):
        for ev in edl.get(key, []):
            viz = ev.get("viz") or {}
            kw = toks(viz.get("title"), " ".join(viz.get("items") or []),
                      ev.get("text"), ev.get("value"))
            if not kw or len(kw) < 2:
                continue          # abstract/mood visual, nothing to anchor to
            span = float(ev["e"]) - float(ev["s"])
            # densest 6s window of keyword hits across the whole transcript
            hits = [(t, w) for w, t in spoken if w in kw]
            if len(hits) < 2:
                continue
            best_t, best_n = None, 0
            for t0, _ in hits:
                n = sum(1 for t, _ in hits if t0 <= t < t0 + max(6.0, span))
                if n > best_n:
                    best_t, best_n = t0, n
            if best_t is None or best_n < 2:
                continue
            s_new = max(0.0, best_t - 0.4)
            s_new = min(s_new, max(0.0, duration - span))
            if abs(s_new - float(ev["s"])) > 2.0:
                log(f"placement fix: '{viz.get('title') or ev.get('text')}' "
                    f"{float(ev['s']):.1f}s -> {s_new:.1f}s "
                    f"(where those words are actually spoken)")
                ev["s"], ev["e"] = round(s_new, 2), round(s_new + span, 2)
                moved += 1
    # de-overlap within each layer after moving
    for key in ("broll", "graphics"):
        evs = sorted(edl.get(key, []), key=lambda e: float(e["s"]))
        for prev, cur in zip(evs, evs[1:]):
            if float(cur["s"]) < float(prev["e"]) + 0.3:
                shift = float(prev["e"]) + 0.3 - float(cur["s"])
                cur["s"] = round(float(cur["s"]) + shift, 2)
                cur["e"] = round(float(cur["e"]) + shift, 2)
        edl[key] = [e for e in evs if float(e["e"]) <= duration + 0.5]
    # CROSS-LAYER: a keyword/stat card stacked on top of an animated diagram
    # is a text collision (banned by the brand standard). Push graphics clear
    # of every viz b-roll window.
    viz_windows = [(float(e["s"]), float(e["e"])) for e in edl.get("broll", [])
                   if e.get("viz")]
    for g in edl.get("graphics", []):
        for vs, ve in viz_windows:
            if float(g["s"]) < ve + 0.3 and float(g["e"]) > vs - 0.3:
                span = float(g["e"]) - float(g["s"])
                if ve + 0.4 + span <= duration:
                    log(f"collision fix: '{g.get('text')}' moved off the "
                        f"diagram ({float(g['s']):.1f}s -> {ve + 0.4:.1f}s)")
                    g["s"], g["e"] = round(ve + 0.4, 2), round(ve + 0.4 + span, 2)
                else:
                    g["_drop"] = True
                break
    edl["graphics"] = [g for g in edl.get("graphics", []) if not g.get("_drop")]
    if moved:
        log(f"placement guard: re-timed {moved} visual(s) to match speech")
    return edl


def make_edl(words, clips, duration, use_llm=True,
             style: str = "long") -> tuple[dict, str]:
    if use_llm and words:
        edl = deepseek_edl(words, clips, duration, style=style)
        if edl and any(edl.values()):
            return align_edl_to_speech(edl, words, duration), "deepseek"
    return (align_edl_to_speech(
        heuristic_edl(words, clips, duration, style=style), words, duration),
        "heuristic")


# ------------------------------------------------------------------ render
def apply_punchins(src: Path, edl: dict, workdir: Path, ffmpeg: str,
                   vid_w: int, vid_h: int, fps: str = "30") -> Path:
    """In-place center zoom on a continuous stream (zoompan). The video
    timeline is never cut, so lips can never drift."""
    pins = sorted(edl.get("punch_ins", []), key=lambda p: p["s"])
    if not pins:
        return src
    log(f"punch-ins: {len(pins)} zoom windows (zoompan, no segmentation)")
    # ZOOMPAN, ZERO SEGMENTATION (2026-07-24 lip-sync fix #3): trim/concat
    # (even single-pass) can drop a frame per punch boundary and lips drift
    # ~33ms per punch. zoompan zooms IN PLACE on one continuous stream: the
    # video timeline is never cut, so audio sync is structurally impossible
    # to break. Zoom windows become one per-frame expression.
    zexpr = "1" + "".join(
        f"+{(min(1.10, max(1.05, float(p.get('scale', 1.08)))) - 1):.3f}"
        f"*between(in_time,{float(p['s']):.3f},{float(p['e']):.3f})"
        for p in pins)
    out = workdir / "punched.mp4"
    _run([ffmpeg, "-y", "-i", src, "-filter_complex",
          f"[0:v]zoompan=z='{zexpr}':d=1"
          f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":s={vid_w}x{vid_h}:fps={fps}[vout]",
          "-map", "[vout]", "-map", "0:a",
          "-c:v", "libx264", "-preset", "fast", "-crf", "18",
          "-c:a", "copy", out], timeout=3600)
    return out


# ------------------------------------------------------- sound design
SFX_DIR = _SFX_DIR
ELEVEN_KEY_FILE = CFGH / "elevenlabs.key"
# July-2026 consensus (sonilo/elevenlabs guides): ElevenLabs SFX V2 is the
# standard generative cue source for AI pipelines; commercial license on
# paid plans. Prompts tuned for premium, weighty, restrained cues.
_ELEVEN_PROMPTS = {
    "boom":   ("deep cinematic sub bass impact, clean and short, premium "
               "documentary, no reverb tail", 1.0),
    "whoosh": ("soft airy cinematic whoosh transition, subtle and elegant, "
               "premium", 0.8),
    "pop":    ("minimal soft interface pop, premium product UI sound, "
               "very short", 0.4),
    "riser":  ("subtle cinematic tension riser swell, building "
               "anticipation, minimal and clean", 1.6),
    "impact": ("cinematic impact hit with tight sub bass and fast decay, "
               "premium trailer sound", 1.0),
}


def _resolve_sfx(name: str) -> Path:
    """ElevenLabs-generated cue if a key exists (cached forever), else the
    synthesized fallback. Drop an API key in ~/.autoeditor/elevenlabs.key to
    upgrade every cue automatically on the next render."""
    eleven = SFX_DIR / f"eleven_{name}.wav"
    if eleven.exists():
        return eleven
    _ek = _api_key("ELEVENLABS_API_KEY", ELEVEN_KEY_FILE)
    if _ek:
        try:
            import urllib.request, tempfile
            key = _ek
            prompt, dur = _ELEVEN_PROMPTS[name]
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/sound-generation",
                data=json.dumps({"text": prompt, "duration_seconds": dur,
                                 "prompt_influence": 0.4}).encode(),
                headers={"xi-api-key": key,
                         "Content-Type": "application/json"})
            audio = urllib.request.urlopen(req, timeout=120).read()
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio); tmp = f.name
            _run(["/opt/homebrew/bin/ffmpeg", "-y", "-i", tmp,
                  "-ar", "48000", eleven])
            log(f"sfx: generated '{name}' via ElevenLabs (cached)")
            return eleven
        except Exception as e:
            log(f"sfx: ElevenLabs '{name}' failed ({type(e).__name__}), "
                "using synth fallback")
    return SFX_DIR / f"{name}.wav"


def build_sfx_plan(edl: dict) -> list:
    """SPARSITY LAW. Sound marks
    only the monuments; everything else stays silent (sound on every event
    reads desperate, and desperate undercuts authority).
    Grammar: animated diagram = whoosh + a pop per step · stat counter =
    riser then impact at landing · VERDICT punch-ins only (scale >= 1.10)
    = sub boom. Cards, b-roll entries, minor punch-ins: SILENT."""
    S = SFX_DIR
    plan = []
    if not S.exists():
        return plan
    for p in edl.get("punch_ins", []):
        if float(p.get("scale", 1.08)) >= 1.10:
            plan.append((_resolve_sfx("boom"), max(0, float(p["s"])), 0.45))
    for b in edl.get("broll", []):
        viz = b.get("viz") or {}
        if str(viz.get("template", "")).lower() == "steps":
            plan.append((_resolve_sfx("whoosh"), max(0, float(b["s"]) - 0.15), 0.55))
            for i, _ in enumerate(viz.get("items", [])[:5]):
                # StepsViz reveals land at s + 0.5 + i*0.6 (template timing)
                plan.append((_resolve_sfx("pop"),
                             float(b["s"]) + 0.5 + i * 0.6, 0.65))
    for g in edl.get("graphics", []):
        if str(g.get("kind", "keyword")).lower() == "stat":
            plan.append((_resolve_sfx("riser"), max(0, float(g["s"])), 0.50))
            plan.append((_resolve_sfx("impact"), float(g["s"]) + 1.45, 0.55))
    plan = [(w, t, g) for w, t, g in plan if w.exists()]
    plan.sort(key=lambda x: x[1])
    return plan


# ------------------------------------------------------- background swap
def apply_background(cut: Path, bg_image: Path, workdir: Path, ffmpeg: str,
                     vid_w: int, vid_h: int,
                     center=(0.28, 0.72)) -> Path:
    """Replace the green screen with a backdrop image using the tuned
    zone-key chain (2026-07-23): strict key + morphological hole-sealing +
    despill + cyan desat in the CENTER zone (face/lens region), loose key on
    the outer wall, invisible seams. Key color is sampled from the footage
    automatically. Falls back to the untouched cut on any failure."""
    try:
        from PIL import Image, ImageFilter, ImageEnhance
        # -- sample the wall green from a real frame (border columns)
        probe = workdir / "_bgprobe.png"
        _run([ffmpeg, "-y", "-ss", "2", "-i", cut, "-frames:v", "1", probe])
        im = Image.open(probe).convert("RGB")
        w, h = im.size
        greens = []
        for x in list(range(10, int(w*0.15), 24)) + list(range(int(w*0.9), w-10, 24)):
            for y in range(10, int(h*0.6), 30):
                c = im.getpixel((x, y))
                if c[1] > c[0] + 20 and c[1] > c[2] + 20:
                    greens.append(c)
        if len(greens) < 10:
            log("background: could not sample wall green, skipping swap")
            return cut
        key = tuple(sum(c[i] for c in greens)//len(greens) for i in range(3))
        keyhex = f"0x{key[0]:02X}{key[1]:02X}{key[2]:02X}"
        # -- prep backdrop: cover-crop, DOF blur, sit-behind grade
        bg = Image.open(bg_image).convert("RGB")
        s = max(vid_w/bg.width, vid_h/bg.height)
        bg = bg.resize((int(bg.width*s)+1, int(bg.height*s)+1))
        bx, by = (bg.width-vid_w)//2, (bg.height-vid_h)//2
        bg = bg.crop((bx, by, bx+vid_w, by+vid_h))
        if "pse_branded" not in str(bg_image):
            bg = bg.filter(ImageFilter.GaussianBlur(7))
            bg = ImageEnhance.Brightness(bg).enhance(0.82)
        bgp = workdir / "_bgprepped.png"
        bg.save(bgp)
        # -- zone boundaries in pixels
        c0, c1 = int(vid_w*center[0]), int(vid_w*center[1])
        out = workdir / "bgswapped.mp4"
        chain = (
            f"[1:v]scale={vid_w}:{vid_h}[bg];"
            f"[0:v]split=3[l0][c0][r0];"
            f"[l0]crop={c0}:{vid_h}:0:0,chromakey={keyhex}:0.12:0.05,despill=type=green[L];"
            f"[c0]crop={c1-c0}:{vid_h}:{c0}:0,chromakey={keyhex}:0.045:0.03,split[k1][k2];"
            f"[k1]alphaextract,dilation,dilation,dilation,erosion,erosion,erosion[ka];"
            f"[k2][ka]alphamerge,despill=type=green,"
            f"huesaturation=saturation=-0.92:colors=c+g:strength=8[C];"
            f"[r0]crop={vid_w-c1}:{vid_h}:{c1}:0,chromakey={keyhex}:0.12:0.05,despill=type=green[R];"
            f"[bg][L]overlay=0:0[t1];[t1][C]overlay={c0}:0[t2];"
            f"[t2][R]overlay={c1}:0,format=yuv420p")
        _run([ffmpeg, "-y", "-i", cut, "-i", bgp, "-filter_complex", chain,
              "-c:v", "libx264", "-preset", "medium", "-crf", "18",
              "-c:a", "copy", out], timeout=3600)
        if out.exists() and out.stat().st_size > 0:
            log(f"background: swapped (key {keyhex}, zones {center})")
            return out
    except Exception as e:
        log(f"background swap failed ({type(e).__name__}), keeping original")
    return cut


# ------------------------------------------------------- motion graphics
GFX_FPS = 30
GOLD_RGB = CFG.brand.accent_rgb[:3]
WHITE_RGB = (255, 255, 255)
GOLD_HEX = CFG.brand.accent
HF_PROJECT = CFGH / "graphics-project"
HF_TIMEOUT = 120   # per-graphic render cap; Pillow fallback beyond this

_HF_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width={w}, height={h}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:{w}px; height:{h}px; overflow:hidden; background:transparent; }}
body {{ font-family:"Work Sans","Arial Black",sans-serif; font-weight:900; }}
.gold {{ color:{gold}; }}
.white {{ color:#fff; }}
.stroke {{ text-shadow:-3px -3px 0 #000,3px -3px 0 #000,-3px 3px 0 #000,3px 3px 0 #000,0 4px 12px rgba(0,0,0.6); }}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}"
     data-width="{w}" data-height="{h}">
{body}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{anim}
window.__timelines["main"] = tl;
</script>
</body></html>"""


def _hf_kind_markup(kind: str, g: dict, dur: float,
                    vid_w: int, vid_h: int) -> tuple[str, str] | None:
    """Return (body_html, gsap_anim) for a graphic event, or None if the
    kind can't be expressed. Restrained enterprise motion, brand palette only."""
    text = str(g.get("text", "")).replace(", ", "-").strip()[:40]
    y = int(vid_h * 0.12)
    fs = max(40, int(vid_h * 0.05))
    out_at = max(0.4, dur - 0.4)
    if kind == "stat":
        m = re.search(r"([\d.]+)\s*(%|x|k|m\b)?", str(g.get("value", text)), re.I)
        if not m:
            return None
        num = float(m.group(1).replace(",", ""))
        suffix = m.group(2) or ""
        body = (f'<div class="clip" data-start="0" data-duration="{dur}" '
                f'style="position:absolute;top:{y}px;width:100%;text-align:center;">'
                f'<div id="num" class="gold stroke" style="font-size:{int(fs*1.9)}px;'
                f'line-height:1.05;">0{suffix}</div>'
                f'<div id="lbl" class="white stroke" style="font-size:{int(fs*0.62)}px;'
                f'margin-top:8px;">{text}</div></div>')
        dec = 1 if (num < 10 and num % 1) else 0
        anim = (
            f'const o={{v:0}};'
            f'tl.to(o,{{v:{num},duration:{min(1.6, dur*0.45):.2f},ease:"power3.out",'
            f'onUpdate:()=>{{document.getElementById("num").textContent='
            f'o.v.toFixed({dec}).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g,",")+"{suffix}";}}}},0);'
            f'tl.from("#num",{{opacity:0,y:30,duration:0.4,ease:"power2.out"}},0);'
            f'tl.from("#lbl",{{opacity:0,y:20,duration:0.4,ease:"power2.out"}},0.15);'
            f'tl.to(["#num","#lbl"],{{opacity:0,duration:0.35}},{out_at:.2f});')
        return body, anim
    if kind == "callout":
        if not text:
            return None
        body = (f'<div id="co" class="clip" data-start="0" data-duration="{dur}" '
                f'style="position:absolute;top:{y}px;width:100%;text-align:center;">'
                f'<span id="dot" style="display:inline-block;width:{int(fs*0.4)}px;'
                f'height:{int(fs*0.4)}px;border-radius:50%;background:{GOLD_HEX};'
                f'margin-right:{int(fs*0.35)}px;vertical-align:middle;"></span>'
                f'<span id="ct" class="white stroke" style="font-size:{fs}px;'
                f'vertical-align:middle;">{text}</span></div>')
        anim = (
            f'tl.from("#ct",{{opacity:0,x:120,duration:0.5,ease:"power3.out"}},0);'
            f'tl.from("#dot",{{scale:0,duration:0.35,ease:"back.out(2)"}},0.1);'
            f'tl.to("#co",{{opacity:0,duration:0.35}},{out_at:.2f});')
        return body, anim
    if kind == "bars":
        items = [(str(it.get("label", ""))[:18], float(it.get("value", 0)))
                 for it in (g.get("items") or []) if isinstance(it, dict)][:3]
        if not items:
            return None
        vmax = max(v for _, v in items) or 1
        rows, anims = [], []
        for bi, (lbl, val) in enumerate(items):
            pct = int(52 * val / vmax)
            rows.append(
                f'<div style="display:flex;align-items:center;margin-bottom:{int(fs*0.5)}px;">'
                f'<div class="white stroke" style="width:22%;text-align:right;'
                f'padding-right:14px;font-size:{int(fs*0.55)}px;">{lbl}</div>'
                f'<div id="bar{bi}" style="height:{int(fs*0.62)}px;width:{pct}%;'
                f'background:{GOLD_HEX};border-radius:{int(fs*0.2)}px;'
                f'box-shadow:0 3px 10px rgba(0,0,0.5);"></div>'
                f'<div class="gold stroke" style="padding-left:12px;'
                f'font-size:{int(fs*0.55)}px;">{val:g}</div></div>')
            anims.append(f'tl.from("#bar{bi}",{{width:0,duration:0.8,'
                         f'ease:"power3.out"}},{0.15*bi:.2f});')
        body = (f'<div id="bwrap" class="clip" data-start="0" data-duration="{dur}" '
                f'style="position:absolute;top:{y}px;width:100%;">{"".join(rows)}</div>')
        anims.append(f'tl.from("#bwrap",{{opacity:0,duration:0.3}},0);')
        anims.append(f'tl.to("#bwrap",{{opacity:0,duration:0.35}},{out_at:.2f});')
        return body, "".join(anims)
    # keyword / default
    if not text:
        return None
    body = (f'<div id="kw" class="clip" data-start="0" data-duration="{dur}" '
            f'style="position:absolute;top:{y}px;width:100%;text-align:center;">'
            f'<div id="kt" class="gold stroke" style="font-size:{fs}px;'
            f'display:inline-block;">{text}'
            f'<div id="rule" style="height:{max(4,int(fs*0.08))}px;background:#fff;'
            f'margin-top:{int(fs*0.3)}px;transform-origin:left;"></div></div></div>')
    anim = (
        f'tl.from("#kt",{{opacity:0,y:26,duration:0.5,ease:"power3.out"}},0);'
        f'tl.from("#rule",{{scaleX:0,duration:0.45,ease:"power2.inOut"}},0.25);'
        f'tl.to("#kw",{{opacity:0,duration:0.35}},{out_at:.2f});')
    return body, anim


def _hf_render_graphic(kind: str, g: dict, dur: float, vid_w: int, vid_h: int,
                       out_seq: Path) -> bool:
    """Render one graphic via HyperFrames to an RGBA png-sequence in out_seq
    (f_%04d.png, GFX_FPS). Returns False on any failure (caller falls back
    to the Pillow engine, the render never blocks the pipeline)."""
    if not (HF_PROJECT / "package.json").exists():
        return False
    mk = _hf_kind_markup(kind, g, dur, vid_w, vid_h)
    if not mk:
        return False
    body, anim = mk
    try:
        (HF_PROJECT / "index.html").write_text(_HF_PAGE.format(
            w=vid_w, h=vid_h, dur=f"{dur:.2f}", gold=GOLD_HEX,
            body=body, anim=anim))
        before = {p.name for p in (HF_PROJECT / "renders").glob("*") } \
            if (HF_PROJECT / "renders").exists() else set()
        npx = shutil.which("npx") or str(Path.home() / ".local/bin/npx")
        _run([npx, "hyperframes", "render", "--format", "png-sequence",
              "--quality", "draft"], cwd=HF_PROJECT, timeout=HF_TIMEOUT)
        rdirs = [p for p in (HF_PROJECT / "renders").glob("*")
                 if p.is_dir() and p.name not in before]
        if not rdirs:
            return False
        rdir = max(rdirs, key=lambda p: p.stat().st_mtime)
        frames = sorted(rdir.glob("frame_*.png"))
        need = max(2, int(dur * GFX_FPS))
        if len(frames) < 2:
            return False
        out_seq.mkdir(exist_ok=True)
        for i, fr in enumerate(frames[:need]):
            shutil.copy(fr, out_seq / f"f_{i:04d}.png")
        shutil.rmtree(rdir, ignore_errors=True)
        return True
    except Exception as e:
        log(f"hyperframes {kind} failed ({type(e).__name__}), pillow fallback")
        return False


def _ease(t: float) -> float:
    """ease-out cubic, clamped 0.1"""
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _alpha_env(t: float, dur: float, fade: float = 0.35) -> float:
    """fade-in / hold / fade-out envelope"""
    fade = min(fade, dur / 3)
    if t < fade:
        return t / fade
    if t > dur - fade:
        return max(0.0, (dur - t) / fade)
    return 1.0


def build_graphics(edl: dict, workdir: Path, font_file: str,
                   vid_w: int, vid_h: int) -> list[dict]:
    """Animated branded graphics as alpha PNG frame-sequences (Pillow),
    composited by ffmpeg overlay. Deterministic, no browser renderer.

    Kinds (DeepSeek chooses; anything unknown degrades to 'keyword'):
      keyword. ALL-CAPS card, fade + subtle rise, white rule sweeps in
      stat, big gold number COUNTS UP (e.g. 0->87%), label below
      callout, floating element: gold bullet + text slides in from right
      bars, up to 3 horizontal bars grow (label left, value right)
    """
    from PIL import Image, ImageDraw, ImageFont
    base = max(34, int(vid_h * 0.055))
    f_big = ImageFont.truetype(font_file, int(base * 1.9))
    f_med = ImageFont.truetype(font_file, base)
    f_sml = ImageFont.truetype(font_file, int(base * 0.62))
    stroke = max(2, base // 12)
    layers = []

    def canvas():
        return Image.new("RGBA", (vid_w, int(vid_h * 0.30)), (0, 0, 0, 0))

    def fade_img(img, a):
        if a >= 0.999:
            return img
        r, g, b, al = img.split()
        return Image.merge("RGBA", (r, g, b, al.point(lambda p: int(p * a))))

    def render_seq(idx, dur, draw_frame):
        n = max(2, int(dur * GFX_FPS))
        seq = workdir / f"gfxseq_{idx:03d}"
        seq.mkdir(exist_ok=True)
        for fi in range(n):
            t = fi / GFX_FPS
            img = canvas()
            draw_frame(ImageDraw.Draw(img), img, t, dur)
            fade_img(img, _alpha_env(t, dur)).save(seq / f"f_{fi:04d}.png")
        return seq

    for i, g in enumerate(edl.get("graphics", [])):
        try:
            s, e = float(g["s"]), float(g["e"])
            dur = max(1.0, e - s)
            kind = str(g.get("kind", "keyword")).lower()
            text = str(g.get("text", "")).replace(", ", "-").strip()[:40]
            if not text and kind != "bars":
                continue

            # HyperFrames first (consensus-best graphics quality), Pillow
            # fallback (deterministic, never blocks), same chain pattern
            # as Pexels -> Pixabay -> Kling for b-roll.
            hf_seq = workdir / f"gfxseq_{i:03d}"
            if _hf_render_graphic(kind, g, dur, vid_w, vid_h, hf_seq):
                log(f"graphic {i} ({kind}) via hyperframes")
                # full-frame render: position is baked into the HTML -> y=0
                layers.append({"seq": str(hf_seq), "s": s, "e": e, "y": 0})
                continue

            if kind == "stat":
                m = re.search(r"([\d.]+)\s*(%|x|k|m\b)?",
                              str(g.get("value", text)), re.I)
                num = float(m.group(1).replace(",", "")) if m else 0
                suffix = (m.group(2) or "") if m else ""
                label = text

                def df(dr, img, t, dur, num=num, suffix=suffix, label=label):
                    cur = num * _ease(t / (dur * 0.45))
                    shown = (f"{cur:.1f}" if num < 10 and num % 1
                             else f"{int(round(cur)):,}") + suffix
                    tw = dr.textlength(shown, font=f_big)
                    dr.text(((vid_w - tw) / 2, 6), shown, font=f_big,
                            fill=(*GOLD_RGB, 255), stroke_width=stroke,
                            stroke_fill=(0, 0, 0, 255))
                    lw = dr.textlength(label, font=f_sml)
                    dr.text(((vid_w - lw) / 2, int(base * 2.15)), label,
                            font=f_sml, fill=(*WHITE_RGB, 255),
                            stroke_width=stroke - 1, stroke_fill=(0, 0, 0, 255))
            elif kind == "callout":
                def df(dr, img, t, dur, text=text):
                    slide = (1 - _ease(t / 0.5)) * vid_w * 0.12
                    tw = dr.textlength(text, font=f_med)
                    x = (vid_w - tw) / 2 + slide
                    y = int(base * 0.5)
                    r = int(base * 0.28)
                    dr.ellipse([x - r * 2.6, y + base * 0.28 - r,
                                x - r * 2.6 + 2 * r, y + base * 0.28 + r],
                               fill=(*GOLD_RGB, 255))
                    dr.text((x, y), text, font=f_med, fill=(*WHITE_RGB, 255),
                            stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            elif kind == "bars":
                items = [(str(it.get("label", ""))[:18],
                          float(it.get("value", 0)))
                         for it in (g.get("items") or [])
                         if isinstance(it, dict)][:3]
                if not items:
                    continue
                vmax = max(v for _, v in items) or 1

                def df(dr, img, t, dur, items=items, vmax=vmax):
                    grow = _ease(t / (dur * 0.5))
                    x0 = int(vid_w * 0.16)
                    bar_max = int(vid_w * 0.52)
                    bh = int(base * 0.62)
                    for bi, (lbl, val) in enumerate(items):
                        y = int(base * 0.3 + bi * bh * 1.7)
                        dr.text((x0 - dr.textlength(lbl, font=f_sml) - 14, y),
                                lbl, font=f_sml, fill=(*WHITE_RGB, 255),
                                stroke_width=stroke - 1,
                                stroke_fill=(0, 0, 0, 255))
                        w = int(bar_max * (val / vmax) * grow)
                        dr.rounded_rectangle([x0, y, x0 + max(w, 4), y + bh],
                                             radius=bh // 3,
                                             fill=(*GOLD_RGB, 255))
                        if grow > 0.95:
                            dr.text((x0 + w + 12, y),
                                    f"{val:g}", font=f_sml,
                                    fill=(*GOLD_RGB, 255),
                                    stroke_width=stroke - 1,
                                    stroke_fill=(0, 0, 0, 255))
            else:  # keyword card (default / unknown kinds degrade here)
                def df(dr, img, t, dur, text=text):
                    rise = (1 - _ease(t / 0.5)) * base * 0.5
                    tw = dr.textlength(text, font=f_med)
                    x = (vid_w - tw) / 2
                    y = int(base * 0.4 + rise)
                    dr.text((x, y), text, font=f_med, fill=(*GOLD_RGB, 255),
                            stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
                    sweep = _ease((t - 0.25) / 0.45)
                    if sweep > 0:
                        dr.rectangle([x, y + base * 1.45,
                                      x + tw * sweep,
                                      y + base * 1.45 + max(3, base // 12)],
                                     fill=(*WHITE_RGB, 230))

            seq = render_seq(i, dur, df)
            layers.append({"seq": str(seq), "s": s, "e": e,
                           "y": int(vid_h * 0.12)})
        except Exception as ex:
            log(f"graphic {i} ({g.get('kind')}) skipped: {type(ex).__name__}")
    return layers


def _pexels_fetch(query: str, portrait: bool, min_dur: float) -> str | None:
    """Fetch one license-clean stock clip from Pexels (free commercial use,
    no attribution). Cached by query so repeat topics cost zero calls."""
    key = _api_key("PEXELS_API_KEY", PEXELS_KEY_FILE)
    if not key:
        return None
    BROLL_CACHE.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower())[:60]
    cached = sorted(BROLL_CACHE.glob(f"{slug}__*.mp4"))
    if cached:
        return str(cached[0])
    try:
        import urllib.request, urllib.parse
        # Cloudflare rejects the default python UA (403/1010), send a real one
        ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 autoeditor/1.0")
        orient = "portrait" if portrait else "landscape"
        req = urllib.request.Request(
            "https://api.pexels.com/videos/search?"
            + urllib.parse.urlencode({"query": query, "per_page": 5,
                                      "orientation": orient, "size": "medium"}),
            headers={"Authorization": key, "User-Agent": ua})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        for vid in data.get("videos", []):
            if vid.get("duration", 0) < min_dur:
                continue
            files = sorted((f for f in vid.get("video_files", [])
                            if f.get("file_type") == "video/mp4"
                            and (f.get("height") or 0) >= 720),
                           key=lambda f: f.get("height") or 0)
            if not files:
                continue
            dst = BROLL_CACHE / f"{slug}__{vid['id']}.mp4"
            dreq = urllib.request.Request(files[-1]["link"],
                                          headers={"User-Agent": ua})
            with urllib.request.urlopen(dreq, timeout=120) as r, open(dst, "wb") as fh:
                shutil.copyfileobj(r, fh)
            log(f"pexels: '{query}' -> {dst.name}")
            return str(dst)
    except Exception as e:
        log(f"pexels '{query}' failed ({type(e).__name__}), trying next source")
    return None


def _pixabay_fetch(query: str, portrait: bool, min_dur: float) -> str | None:
    """Second free source (Pixabay license: free commercial use, no
    attribution). Same cache dir; tried when Pexels has no key/match."""
    key = _api_key("PIXABAY_API_KEY", PIXABAY_KEY_FILE)
    if not key:
        return None
    BROLL_CACHE.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower())[:60]
    cached = sorted(BROLL_CACHE.glob(f"px_{slug}__*.mp4"))
    if cached:
        return str(cached[0])
    try:
        import urllib.request, urllib.parse
        req = urllib.request.Request(
            "https://pixabay.com/api/videos/?"
            + urllib.parse.urlencode({"key": key, "q": query, "per_page": 8,
                                      "safesearch": "true"}),
            headers={"User-Agent": _UA})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        for vid in data.get("hits", []):
            if vid.get("duration", 0) < min_dur:
                continue
            sizes = [v for v in (vid.get("videos") or {}).values()
                     if (v.get("height") or 0) >= 720 and v.get("url")]
            if not sizes:
                continue
            # prefer orientation match, then highest resolution
            sizes.sort(key=lambda v: ((v["height"] > v["width"]) == portrait,
                                      v["height"]))
            best = sizes[-1]
            dst = BROLL_CACHE / f"px_{slug}__{vid['id']}.mp4"
            dreq = urllib.request.Request(best["url"], headers={"User-Agent": _UA})
            with urllib.request.urlopen(dreq, timeout=120) as r, open(dst, "wb") as fh:
                shutil.copyfileobj(r, fh)
            log(f"pixabay: '{query}' -> {dst.name}")
            return str(dst)
    except Exception as e:
        log(f"pixabay '{query}' failed ({type(e).__name__})")
    return None


REMOTION_PROJ = Path.home() / "cinematic-autopilot/remotion-viz"
_VIZ_TEMPLATES = {"flow": "FlowViz", "steps": "StepsViz", "stat": "StatViz"}


def _remotion_viz(viz: dict, dur: float, vid_w: int, vid_h: int) -> str | None:
    """Render a template visualization (generated b-roll) via Remotion.
    Deterministic: DeepSeek only supplies template + parameters; the React
    compositions are fixed brand templates. Cached by parameter hash."""
    comp = _VIZ_TEMPLATES.get(str(viz.get("template", "")).lower())
    if not comp or not (REMOTION_PROJ / "package.json").exists():
        return None
    props = {"durSec": round(max(2.5, dur), 2), "w": vid_w, "h": vid_h,
             "title": str(viz.get("title", ""))[:36].replace(", ", "-"),
             "items": [str(x)[:26].replace(", ", "-")
                       for x in (viz.get("items") or [])][:5],
             "value": str(viz.get("value", ""))[:12],
             "label": str(viz.get("title", viz.get("label", "")))[:36]}
    BROLL_CACHE.mkdir(parents=True, exist_ok=True)
    import hashlib as _h
    key = _h.sha256(json.dumps([comp, props], sort_keys=True).encode()).hexdigest()[:16]
    dst = BROLL_CACHE / f"viz_{comp}_{key}.mp4"
    if dst.exists():
        return str(dst)
    try:
        import tempfile as _tf
        with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(props, fh)
            pfile = fh.name
        npx = shutil.which("npx") or str(Path.home() / ".local/bin/npx")
        _run([npx, "remotion", "render", "src/index.ts", comp, dst,
              f"--props={pfile}", "--log=error"],
             cwd=REMOTION_PROJ, timeout=300)
        if dst.exists() and dst.stat().st_size > 0:
            log(f"remotion viz: {comp} '{props['title']}' -> {dst.name}")
            return str(dst)
    except Exception as e:
        log(f"remotion viz {comp} failed ({type(e).__name__}), stock fallback")
    return None


def broll_layers(edl: dict, clips: list[dict],
                 portrait: bool = True, vid_w: int = 1080,
                 vid_h: int = 1920) -> list[dict]:
    """Resolve each EDL b-roll slot, best source first:
    Remotion viz (generated animation) -> Pexels -> Pixabay -> Kling -> skip.
    Never blocks the render."""
    by_fam = {}
    for c in clips:
        by_fam.setdefault(c["family"], []).append(c)
    layers = []
    for b in edl.get("broll", []):
        dur = float(b["e"]) - float(b["s"])
        path = None
        viz = b.get("viz")
        if isinstance(viz, dict) and viz.get("template"):
            path = _remotion_viz(viz, dur, vid_w, vid_h)
        q = (b.get("query") or "").strip()
        if not path and q:
            path = _pexels_fetch(q, portrait, dur) or \
                   _pixabay_fetch(q, portrait, dur)
        if not path:
            pool = by_fam.get(b.get("family"))
            if pool:
                path = pool[len(layers) % len(pool)]["path"]
        if not path:
            continue
        layers.append({"video": path, "s": float(b["s"]), "e": float(b["e"])})
    return layers
