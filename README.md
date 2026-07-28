# Verified Talking-Head Auto-Editor

**Raw camera file in, upload-ready video out — with mechanical gates that refuse to deliver a broken edit.**

Point it at a talking-head recording. It removes silence, deletes the takes you flubbed and re-read, cuts your coughs, adds punch-ins, pulls topical b-roll, animates diagrams for the frameworks you teach, burns word-synced captions, normalises loudness, and hands you a finished file.

Then — and this is the part most auto-editors don't have — it **re-watches its own work** and blocks delivery if it broke anything.

```bash
make edit VIDEO=~/Movies/lesson1.mov SCRIPT=lesson1.txt
```

```
phase 1.6  CFR normalize -> 30fps grid + AV offset (audio +100ms)
phase 2    word-guarded cut removed 18 pause(s) — kept 92%, all 622 words preserved
           retake cut: [73.3-75.7]  7-word repeat — keeping the later take
           retake cut: [141.9-155.2] 3-word repeat + self-correction aside
           false-start cut: [220.0-223.7] 2-word prefix repeat
           lead-noise cut: [2.48-3.00] cough/throat clear, p=0.54
phase 4p   EDL via deepseek — 9 punch-ins, 10 b-roll, 9 graphics
phase 7    QA gate
           sync probe @31.9s: offset=0.0ms OK      (x5)
           word integrity: 616/619 words in master (99.5%) — PASS
           script integrity: 27 delivered, 1 skipped by choice, 0 DAMAGED — PASS
QA: PASS
```

---

## Why this exists

Automatic editors are easy to build and easy to trust wrongly. The failure mode isn't a crash — it's a video that looks fine, runs the right length, and quietly has **your words missing from it**.

This project was built by repeatedly shipping exactly that, and then engineering it out. Three real examples, all of which now have permanent detectors:

| What happened | Why the editor did it | The fix |
|---|---|---|
| 152 of 623 words deleted mid-sentence — *"assigning status for around five hundred million years"* became *"...around Philly"* | The cutter classified speech by **loudness**, and soft word-endings fell under the threshold. Duration-kept was 55%, which passed the guardrail on a technicality. | Cutting is now driven by the **transcript**, not the waveform. Silence may only be removed *between* padded word spans. |
| *"Superiority, Autonomy,"* deleted from the sentence introducing the framework | A "garble detector" cut spans where the speech model's confidence dropped below 40%. The model was simply unsure of an unusual word — the delivery was perfect. | Low confidence is no longer proof of a flub. Words that appear in the script are **shielded**. |
| A 21-second dead tail after the speech ended | A stale duration value meant the caption layer was built to the *pre-cut* length and stretched the render. | Duration is recomputed after every cut; the sync probe that landed in the tail caught it. |

The lesson generalised: **every signal the editor trusts is a proxy, and every proxy eventually lies.** Loudness is a proxy for speech. Model confidence is a proxy for clarity. Duration is a proxy for content. So the architecture stopped relying on proxies alone and added verification against ground truth.

---

## The three gates

After rendering, the pipeline **re-analyses its own output file** and must pass all three before the video is released. Two of them block delivery outright.

### 1. Lip-sync verification
Samples five points spread across the finished master, deliberately chosen *outside* every punch-in, b-roll and graphic window (where the face isn't on screen). At each point it compares the master against the pre-overlay cut in both streams: image match on the frame band below the captions, and normalised cross-correlation on the audio. Drift is monotonic, so alignment at spread points proves the whole timeline.

**Fails if:** any probe drifts more than ±25ms.

### 2. Word integrity
Re-transcribes the delivered master and sequence-aligns it against the transcript from the cut stage. This catches damage introduced *after* cutting — by compositing, re-encoding, or an overlay filter.

**Fails if:** more than 3% of words vanished between the cut and the master.

### 3. Script integrity (semantic)
The interesting one. Word-aligns the delivered speech against the script that was read, scores every script sentence, and hands each ambiguous one to an LLM judge that classifies it:

- **paraphrased** — said differently, meaning intact → fine
- **skipped** — deliberately dropped → fine
- **elaborated** — extra sentences added → fine
- **DAMAGED** — chopped mid-thought, a concrete fact lost, ends in nonsense → **blocks delivery**

This distinction is the whole point. A speaker who paraphrases freely must not be flagged, while *"the room already belongs to you"* collapsing into *"the room already"* must be. A naive diff can't tell those apart; a judge with both texts in front of it can.

Real output from a blocked render:

```
script integrity: 26 delivered, 1 skipped by choice, 8 reviewed -> 1 DAMAGED
  script: 'There are three signals your Lizard Brain broadcasts... Superiority, Autonomy, and Certainty.'
  heard : '...reads in every single human interaction and certainty. S -A'
  why   : lost Superiority and Autonomy; only one of three named
delivery: RuntimeError: script damage - video delivery blocked
```

Details and tuning: **[docs/VERIFICATION.md](docs/VERIFICATION.md)**

---

## What it does to your footage

**Cutting** — four detectors run in sequence, all transcript-driven so a cut can never land inside a word:

| Detector | Catches |
|---|---|
| `word_guarded_cut` | Silence between words (pauses ≥0.9s), padded so speech is never clipped |
| `detect_retakes` | You flubbed a line and said it again — keeps the **last** take, drops the earlier attempts, and swallows your out-loud corrections (*"let me say that again"*) |
| `detect_false_starts` | You restarted a sentence with the same opening but a different ending (*"You never hesitate." → "You never compromise."*) — too short for the repeat matcher to see |
| `detect_lead_noise` | The cough or throat-clear on the opening frame, which speech models transcribe as a low-confidence *word* and so ordinary cough detectors miss |

**Production** — one LLM call authors an edit decision list: punch-ins on emphasis, b-roll queries matched to what's being said, animated diagrams for frameworks and lists, stat cards for numbers. A deterministic heuristic produces the same shape when no model is configured, so the pipeline never blocks on an API.

**Finishing** — karaoke captions (each word highlights as spoken), sparse sound design, two-pass loudness to −14 LUFS, aspect-correct export, SHA-256 hash-lock, and a `QA_REPORT.json` receipt.

Full walkthrough of every phase: **[docs/PIPELINE.md](docs/PIPELINE.md)**

---

## Install

Requires macOS or Linux, Python 3.10+, and about 2GB of disk for models and cache.

```bash
git clone https://github.com/CEOmarabha/talking-head-autoeditor.git
cd talking-head-autoeditor
make install
```

`make install` checks for ffmpeg (installs it via Homebrew/apt if missing), builds a virtualenv, installs four Python packages, downloads the speech model, and optionally sets up the Remotion diagram renderer if you have Node.

Then:

```bash
cp .env.example .env      # add your keys — all optional
make check                # confirm everything resolves
```

### Keys, and what each one buys you

| Key | Cost | Without it |
|---|---|---|
| `DEEPSEEK_API_KEY` | **~1¢ per video** | Heuristic edit decisions; no semantic script gate |
| `PEXELS_API_KEY` | free | No stock b-roll (diagrams still render) |
| `PIXABAY_API_KEY` | free | One fewer b-roll source |
| `ELEVENLABS_API_KEY` | optional | Synthesised sound-effect kit instead |
| `TELEGRAM_BOT_TOKEN` | free | No push to your phone; files just land on disk |

**DeepSeek V4 Flash alone runs the entire creative layer.** Everything heavy — transcription, cutting, compositing, captions, diagrams — is local and free. The model is called exactly twice per video: once to author the edit, once to judge script integrity.

---

## Use it

```bash
# 1. ONE TIME: measure your camera rig's audio offset
make calibrate VIDEO=~/Movies/any-take.mov
#    watch the five clips, put the winner in brand.yaml

# 2. edit
make edit VIDEO=~/Movies/lesson1.mov SCRIPT=lesson1.txt

# vertical/short-form pacing
make edit VIDEO=~/Movies/clip.mov STYLE=short ASPECT=9x16
```

`SCRIPT` is optional but recommended — it's what powers caption correction (fixing misheard words while leaving your paraphrases alone) and the semantic gate.

**Output:**

```
MASTER_16x9.mp4      your video
CAPTIONS.srt         sidecar subtitles
EDL.json             every creative decision, with timings
QA_REPORT.json       all gate results + SHA-256 hash-lock
SCRIPT_INTEGRITY.json  sentence-by-sentence verdicts
```

Expect **20–35 minutes** for a 4-minute video on Apple Silicon. It's CPU-bound; transcription and compositing dominate.

---

## Make it yours

Everything visual and editorial lives in [`brand.yaml`](brand.yaml) — colours, font, caption density, how aggressively it cuts, gate thresholds. The engine reads that file; you never edit Python to change a look.

The creative instincts (what deserves a punch-in, when a diagram beats stock footage, how sparse sound design should be) live as editable **director principles** in `autoeditor/premium.py`. They're written as prose in the prompt, so you can rewrite them in your own voice.

---

## Design notes worth stealing

Even if you never run this, a few pieces generalise:

- **Verify against the artifact, not the plan.** Re-analysing the rendered file catches an entire class of bugs that inspecting intermediate state cannot.
- **Let the judge see both texts.** Asking a model *"is this damaged?"* with the script and the delivery side by side beats any similarity threshold, because it separates intent from accident.
- **Fail loudly, in the log.** A swallowed `NameError` silently disabled every large-file delivery here for days. The `except` clause now logs.
- **Parse JSON by balanced braces.** A greedy `\{.*\}` regex against model output swallows trailing prose and throws — silently degrading the whole creative layer. `providers.extract_json` scans for the first balanced, string-aware object.
- **Retry the model.** One dropped call collapsed 12 b-roll clips to 1, and the only symptom was a video that looked a bit plain.

---

## License

MIT — see [LICENSE](LICENSE). Use it commercially, fork it, sell what you make with it.

Built by [Omar](https://github.com/CEOmarabha). If it saves you an afternoon, a star helps.
