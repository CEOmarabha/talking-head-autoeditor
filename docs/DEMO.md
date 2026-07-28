# Demo: your first edit, start to finish

Fifteen minutes from `git clone` to a finished video. No footage required for the first two steps.

---

## 0 · Install

```bash
git clone https://github.com/CEOmarabha/talking-head-autoeditor.git
cd talking-head-autoeditor
make install
```

You'll see each dependency resolve:

```
==> Checking system dependencies
 ok ffmpeg 7.1
 ok python 3.12.13
==> Creating virtualenv at ./.venv
 ok python packages installed
==> Warming the speech model (one-time ~150MB download)
 ok transcription ready
==> Optional: animated diagram renderer (Remotion, needs Node 18+)
 ok diagram renderer installed
```

Confirm:

```bash
make check
```

```
python deps  ok
ffmpeg       ok
llm          not configured (heuristic fallback will be used)
```

That last line is fine, it will still produce a complete, verified video. Add a key when you want authored edits.

---

## 1 · Add one key (optional, ~1¢ per video)

```bash
cp .env.example .env
```

Put a DeepSeek key in it. That single key buys you the creative layer *and* the semantic verification gate:

```
DEEPSEEK_API_KEY=sk-...
PEXELS_API_KEY=...        # free, gives you stock b-roll
```

`make check` should now print `llm ok`.

---

## 2 · Calibrate your camera, once ever

Do not skip this. Many phone apps record USB-microphone audio out of sync with the video, and no editor can detect it from the inside. Five minutes here prevents every video you ever make from feeling subtly wrong.

```bash
make calibrate VIDEO=~/Movies/any-take.mov
```

```
Building sync ladder from any-take.mov

  wrote sync_CONTROL.mp4   (untouched original)
  wrote sync_E200.mp4      (audio -200ms)
  wrote sync_E100.mp4      (audio -100ms)
  wrote sync_L100.mp4      (audio +100ms)
  wrote sync_L200.mp4      (audio +200ms)
```

Watch all five. Pick the one where the lips look right. Put it in `brand.yaml`:

```yaml
rules:
  av_offset_ms: 100     # L100 won
```

> If two look acceptable, choose the **smaller** correction. Late audio is perceptually forgiving (~125ms of tolerance versus ~45ms for early audio), so an overshoot can masquerade as correct.

---

## 3 · Set your look

```yaml
# brand.yaml
brand:
  accent: "#E8C7A7"        # your highlight colour
  font_pattern: "WorkSans" # a font you actually have installed
  caption_words: 4
```

---

## 4 · Edit

```bash
make edit VIDEO=~/Movies/lesson1.mov SCRIPT=~/scripts/lesson1.txt
```

`SCRIPT` is optional but worth supplying: it powers caption correction and the semantic gate.

### Watching it work

```
[1.5]  letterbox detected, true content 2160x1220 at (0,1312); canvas -> 1920x1080
[1.6]  CFR normalize -> 30fps strict grid + AV offset (audio +100ms delay)
[1]    1920x1080 262.3s ok, style=long
[3]    faster-whisper word-level transcript
[2]    word-guarded cut removed 18 pause(s), kept 92%, all 622 words preserved
       retake cut: [73.3-75.7] retake (7-word repeat), keeping the later take
       retake cut: [141.9-155.2] retake (3-word repeat) + self-correction aside
       false-start cut: [220.0-223.7] false start (2-word prefix repeat)
       lead-noise cut: [2.48-3.00] lead-in noise (cough/throat clear, p=0.54)
[3]    623 words post-cut
       captions: script alignment: 467 exact, 9 misheard corrected, 5 paraphrases kept
       anomaly SKIPPED [107.9-110.6]: low confidence but the words are in the
                                      script, real content, not a flub
[4p]   EDL via deepseek: 9 punch-ins, 10 b-roll, 9 graphics
       remotion viz: StepsViz 'THREE SIGNALS'
       pexels: 'neurons firing brain activity' -> neurons_firing__37101560.mp4
[5/6]  composite 10 b-roll + 9 graphics + loudness pass 1
[7]    QA gate
       sync probe @31.93s: mae=0.1 offset=0.0ms OK
       sync probe @89.38s: mae=0.1 offset=0.0ms OK
       sync probe @132.61s: mae=0.1 offset=0.0ms OK
       sync probe @195.06s: mae=0.1 offset=0.0ms OK
       sync probe @221.81s: mae=0.1 offset=0.0ms OK
       word integrity: 616/619 words in master (99.5%) PASS
       script integrity: 27 delivered, 1 skipped by choice, 0 DAMAGED
[8]    hash-lock release
QA: PASS
```

Read that middle block closely, it's the system explaining its editorial reasoning. It found five flubbed takes, kept the good read of each, corrected nine misheard caption words while leaving five deliberate paraphrases alone, and **declined** to cut a passage it would previously have deleted because the words were in the script.

---

## 5 · What a blocked render looks like

This is the behaviour worth understanding, because it's the reason to use this over a simpler tool:

```
word integrity: 616/619 words in master (99.5%) PASS
script integrity: 26 delivered, 1 skipped by choice, 8 reviewed -> 1 DAMAGED
  ✗ script: 'There are three signals your Lizard Brain broadcasts and reads
             in every single human interaction: Superiority, Autonomy, and Certainty.'
    heard : '...reads in every single human interaction and certainty. S -A'
    why   : script names three signals; heard version loses Superiority and
            Autonomy, leaving only Certainty named
QA: FAIL
delivery: RuntimeError: script damage, video delivery blocked
```

The file is still on disk, nothing is deleted, but it is **not delivered**, and the report tells you the exact sentence and why. In this real case the cause was the anomaly detector removing 2.9 seconds it had misjudged as garble. The fix shipped as the script shield described in [PIPELINE.md](PIPELINE.md#anomaly-cuts-and-the-script-shield).

---

## 6 · Your output

```
~/Desktop/autoedit-out/lesson1/
├── MASTER_16x9.mp4          upload this
├── CAPTIONS.srt             sidecar subtitles
├── EDL.json                 every creative decision + timings
├── QA_REPORT.json           gate results + SHA-256 hash-lock
└── SCRIPT_INTEGRITY.json    sentence-by-sentence verdicts
```

---

## Recording tips that make the editor's job easy

- **Flub freely.** Pause a beat, say the line again, keep rolling. Retake detection keeps the last read. This is faster than restarting a take.
- **Talk to yourself.** *"Let me say that again"* is recognised as a restart marker and removed along with the bad attempt.
- **Pause between sentences.** Anything over ~0.9s is removed automatically, so generous pauses cost nothing and make cuts cleaner.
- **Stay near the mic.** Sync and cutting are reliable; nothing fixes room echo.
- **Supply the script.** It's what lets the editor tell a mishearing from a paraphrase, and a flub from an unusual word.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `llm not configured` | No key in `.env`, or `.env` wasn't copied from `.env.example` |
| Video feels out of sync, gates all pass | Source offset, run `make calibrate` |
| Only 1 b-roll clip appeared | The model call failed; check `PEXELS_API_KEY` and rerun. Retries make this rare. |
| `brand_font` flagged in QA | Your `font_pattern` font isn't installed; a system font was substituted |
| Diagrams missing | Node 18+ wasn't present at install time, install Node, re-run `make install` |
| Render feels slow | It is CPU-bound. 20 to 35 minutes per 4-minute video on Apple Silicon is normal. |
