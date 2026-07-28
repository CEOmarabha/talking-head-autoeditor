# Pipeline

Every phase, in order, with the reasoning behind each choice.

The guiding rule: **route each phase to the tool that's genuinely best at it, and give every layer a fallback so the pipeline never blocks on an API.**

```
 raw camera file
      |
 [1]  preflight ............ probe dimensions, duration, codecs
 [1.5] deletterbox ......... detect and crop baked-in black bars
 [1.6] CFR normalize ....... force a constant frame grid + apply AV offset
      |
 [2]  word-guarded cut ..... transcript-driven silence removal
      retake detection ..... drop flubbed takes, keep the last read
      false starts ......... drop abandoned sentence openings
      lead noise ........... drop the opening cough
      dead-air sweep ....... catch pauses the first pass missed
      |
 [3]  transcribe ........... word-level timings on the cut timeline
      script correction .... fix misheard words, preserve paraphrase
      |
 [4]  EDL ................. V4 Pro director + critic, typed contract
 [4p] asset resolution ..... diagrams -> stock -> local library -> skip
      |
 [5]  composite ............ overlays, captions, sound design
 [6]  loudness ............. two-pass normalisation
      |
 [7]  QA + THREE GATES ..... re-analyse the render; block if broken
 [8]  release .............. hash-lock, receipts, optional delivery
```

---

## Phase 1, preflight and source repair

### 1.5 · Deletterboxing

Phone editing apps often export a landscape recording inside a portrait canvas, with black bars baked into the pixels. Every downstream crop then operates on the wrong geometry. `cropdetect` finds the real content box and crops to it before anything else runs.

### 1.6 · Constant frame rate, always on

Phone recordings are nominally 30fps but actually variable: frames get dropped under thermal load, leaving gaps in presentation timestamps. Downstream tools assume a constant grid, so cuts land offset from the audio and lips drift.

This phase rebuilds the source on a strict grid (`fps=30`, 48kHz audio). It costs a full re-encode and it is not optional, it eliminated an entire class of sync bug that three previous fixes had only moved around.

The measured **AV offset** from `brand.yaml` is applied here too, as an `adelay` or `atrim` on the audio. See [VERIFICATION.md](VERIFICATION.md#gate-1--lip-sync-verification) for why this must be measured by ear rather than detected.

---

## Phase 2, cutting

Four detectors, all working from the **transcript** rather than the waveform. This is the central architectural decision of the project.

### Why not loudness

The obvious approach, and what `auto-editor` and most tools do, is to cut where the audio is quiet. It fails on soft speakers: trailing consonants and sentence-final words fall below any threshold that also removes real silence. Raise the threshold and you keep dead air; lower it and you eat words.

There is no correct threshold. The signal is wrong.

### `word_guarded_cut`

Transcribe first. Now the boundaries of every word are known, so silence can only be removed **between** word spans, with padding (`pad_tail` after a word, `pad_head` before the next). A cut landing inside a word is no longer a bug to be caught, it's unrepresentable.

The loudness cutter remains as a fallback for footage where transcription finds almost nothing (fewer than 10 words), which usually means it isn't a talking head.

### `detect_retakes`

Speakers flub a line and immediately say it again. The transcript then contains the same word sequence twice in quick succession.

Find repeated runs of ≥3 words whose second occurrence starts within 14 seconds, then cut **from the start of the first attempt to the start of the last**. Longest match wins, so partial restarts collapse correctly:

```
"a stranger cuts in front of you,"                      <- cut
"a stranger cuts in front of you and nobody objects."   <- keep
```

It also absorbs the *wind-up*: spoken self-corrections (`"let me say that again"`, `"scratch that"`, `"alright, let's make that clear"`, see `RESTART_MARKERS`) plus any short aborted fragment immediately before them. Those belong to the bad take.

### `detect_false_starts`

When a retake changes the *ending*, only a short prefix repeats, too short for the run matcher:

```
"You never hesitate."     <- cut
"You never compromise."   <- keep
```

Signature: two adjacent sentences sharing a ≥2-word opening, where the first is short and abandoned. Guarded against deliberate parallel structure (*"What is my Superiority signal… What is my Autonomy signal…"*) by requiring the first sentence to be short, and by shielding any phrase that appears verbatim in the script.

### `detect_lead_noise`

The cough on the opening frame. Ordinary cough detection looks for loud spans containing **no words**, but a speech model transcribes a cough as a low-confidence *word* (in the case that motivated this, a cough became `"Your"` at p=0.54), so it slips through and becomes frame one of your video.

Signature: the first word has confidence below 0.70 **and** a ≥0.25s gap before the next word. A genuine opening word runs straight into its phrase; a cough sits alone.

### Anomaly cuts, and the script shield

A separate detector removes genuine garbles (≥2 consecutive words under 40% confidence) and coughs mid-video.

It carries an important safeguard: **low confidence is not proof of a flub.** This detector once deleted *"Superiority, Autonomy,"*, perfectly delivered, but unusual vocabulary the model wasn't sure of. When a script is supplied, any "garble" whose words appear in the script is recognised as real content and left alone.

---

## Phase 3, transcription and script correction

Word-level timestamps come from `faster-whisper` (`small`, int8, which trades a little accuracy for speed on CPU). Timings from this phase drive every downstream decision.

With `--script`, captions get corrected against the script, but **only for genuine mishearings**. A word is corrected when the model was unsure of it *or* what it heard is phonetically close to the scripted word. A word the model heard confidently that simply differs is the speaker paraphrasing, and their wording wins:

```
captions: script alignment: 467 exact, 9 misheard corrected, 5 paraphrases kept as spoken
```

---

## Phase 4, the edit decision list

DeepSeek V4 Pro receives the complete post-cut transcript and produces the
creative layer as JSON. A V4 Pro critic sees the complete transcript, the
current candidate, and every validator error, then returns a full replacement
EDL. If deterministic validation still finds errors, the compiler feeds those
exact errors into the next bounded repair round, up to three critic rounds.

The prompt gives the model ten ordered steps, exact field types, duration and
density limits, a worked JSON object, local clip families, style rules, and the
versioned protocol identifier. Every event must copy an exact 5-20 word spoken
quote and state why that moment earns the event.

`creative_contract.validate_edl` treats model times as proposals. It locates
the full contiguous quote in word-level ASR, rejects short, paraphrased, or
invented matches, writes measured word times, and checks hook placement,
opening visual coverage, maximum visual gap, framework diagrams, minimum event
spacing, density, and collisions. Displayed titles, items, labels, and numbers
must be supported by speech near the anchor. The critic output must score 100.

Model mode blocks if either call or the final contract fails. The deterministic
heuristic is selected only through `--no-llm`.

### Parsing the model's JSON

Models wrap JSON in prose and code fences. A greedy `\{.*\}` regex swallows the trailing text and throws, which silently degraded this pipeline's entire creative layer to the heuristic, with no symptom except a video that looked plain.

`providers.extract_json` scans for the first **balanced, string-aware** object
and requires every requested key. DeepSeek calls use JSON mode, thinking
enabled, maximum reasoning effort, a 32,768-token output allowance, finish
reason checks, empty-content retries, and safe receipts.

### Asset chain

An event planned as a diagram must render through Remotion as that exact typed
diagram. It cannot retain diagram credit by degrading to unrelated stock.
Ordinary b-roll resolves through a chain, taking the first source that
succeeds:

**Pexels** → **Pixabay** → **your local clip library** → **unresolved**

The renderer records which source resolved every event. Empty local families
never select arbitrary footage, and any path rated REJECT in any catalog stays
rejected. Cache hits are checked for duration and orientation. Downloads and
diagram renders use a temporary file, validate it, then atomically publish the
cache entry. A skipped planned beat fails `creative_assets_resolved` and leaves
the master quarantined. It measures the resolved file itself, so a short clip
cannot freeze its last frame through a longer planned window.

The full model protocol is in
[DEEPSEEK_WORKFLOW.md](DEEPSEEK_WORKFLOW.md).

---

## Phases 5 and 6, composite and finish

**Punch-ins** are rendered as in-place `zoompan` zooms rather than cut-and-rescale segments, because segmenting the timeline reintroduces frame-boundary drift.

**Captions** are PNG frame sequences composited with `overlay`, not `drawtext` or `libass`, minimal ffmpeg builds ship without those filters, and this way the pipeline works on any build. Each word highlights in the accent colour as it's spoken; identical states are hard-linked so a 4-minute video costs a few hundred unique images instead of seven thousand.

**Sound design** follows a sparsity law: cues mark only structural moments (a diagram assembling, a stat landing, a hard punch-in). Sound on every event reads as desperate.

**Loudness** is two-pass `loudnorm` to −14 LUFS integrated, −1 dBTP ceiling.

---

## Phases 7 and 8, gates and release

Covered in full in [VERIFICATION.md](VERIFICATION.md). In short: the native
master, delivered aspect, final transcript, source recording, script, EDL,
resolved assets, and receipts are re-analysed as artifacts. Every release
check can block, and the output is hash-locked with a JSON receipt.

Delivery failures are **logged, never swallowed**. A silently caught `NameError` here once disabled every large-file delivery for days, and the only symptom was "the video never arrived."
