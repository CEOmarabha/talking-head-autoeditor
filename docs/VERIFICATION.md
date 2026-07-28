# Verification

The editor's job is not to make cuts. It is to make cuts and then prove it did not break anything.

## The problem gates solve

An automatic editor makes thousands of decisions per video, and almost all of them are invisible when wrong. A dropped word does not crash anything. It produces a video of the right length, with correct captions, that plays fine and is missing a sentence you needed.

The obvious checks pass too. Here is the report from the run that deleted 152 of 623 words:

```
speech_retention  kept_ratio 0.55  ok: true     <- threshold was >= 0.55
loudness          -14.2 LUFS      ok: true
captions_present                   ok: true
lip_sync          5/5 probes 0.0ms ok: true
QA: PASS
```

Everything passed and the video was destroyed. `speech_retention` was measuring duration, which is a proxy for content, and the proxy lied.

The fix was not a better threshold. It was checking a different thing: re-analyse the delivered file and compare it against what should be in it.

## Gate 1, lip-sync verification

Blocks delivery.

Five probe points get spread across the master, then shifted so each one lands outside every punch-in, b-roll and graphic window in the EDL. During those windows the speaker's face is not on screen and the comparison would be meaningless.

At each probe the video check crops the frame band below the caption area, where no overlays live, scales it to 160x45 greyscale, and computes mean absolute error against the same timestamp in the pre-overlay cut. The audio check extracts a window at 8kHz from both, normalizes, and cross-correlates across 200 lags in each direction to find the offset with the highest correlation.

Five points rather than one because timeline drift accumulates. If the first and last probes are both aligned, nothing between them can be off without one of them showing it.

It passes when every probe reports frame MAE below 12 and audio offset inside `sync_tolerance_ms`, which defaults to 25.

This gate found four separate root causes, each because it refused to pass:

1. Per-segment concat accumulating AAC frame-rounding at every boundary, roughly 20 to 40ms each. Rebuilt as single-pass filter graphs.
2. Trim and concat dropping frames. Punch-ins were re-implemented as in-place `zoompan`.
3. A variable-frame-rate source with dropped frames. CFR normalization is now always on, before anything else runs.
4. A 21-second dead tail, caught when a probe landed inside it and returned `mae=99.0`.

### The blind spot, and how it is covered

This gate compares the master against the cut. Both inherit whatever offset is baked into the source recording, so both agree, and it reports a clean 0.0ms on footage whose lips never matched to begin with.

That is not a flaw in the check. There is no un-offset reference inside the pipeline to compare against. But leaving it uncovered cost nine consecutive renders that all passed this gate and were all visibly out of sync, because a constant measured on one recording was reused on a different one without re-measuring.

So the source offset is now measured on every render, before any correction is applied. Mouth-region motion is cross-correlated against the audio envelope, and the result is only trusted when three disjoint slices of the window agree within 100ms. Bearded faces and soft consonants produce weak correlation peaks, and that agreement test is what separates a real peak from noise.

When the measurement is reliable it overrides the configured value and logs the substitution. When it is not, the pipeline says so plainly and falls back to your configured number:

```
av-offset measured: +333ms (corr 0.150, slices [333, 400, 133], UNRELIABLE, spread too wide)
av-offset: measurement unreliable, falling back to configured -200ms.
```

Either way it lands in `QA_REPORT.json` under `source_av_offset`, with the correlation and the slice spread, so a render can never again be silently wrong about this. For footage the estimator cannot read, [`calibrate.py`](../autoeditor/calibrate.py) still gives you a ladder to judge by eye, which remains the ground truth.

## Gate 2, word integrity

Blocks delivery.

Transcribes the delivered master, not any intermediate file, and sequence-aligns it against the transcript taken right after cutting. Reports what fraction of words survived.

This one is about mechanical damage after the cut stage: a bad filter graph, a truncated encode, an overlay that clobbered audio. It compares the pipeline against itself, so it does not care what the speaker said or whether they followed a script.

It passes when `found_in_master / expected` clears `word_integrity_min`, which defaults to 0.97.

On tuning: two transcriptions of identical audio disagree by 1 to 3 percent, since speech models are not deterministic across runs. So 0.97 sits just above the noise floor. Real damage is not subtle. The incident that motivated this gate scored 0.75. Dropping to 0.92 is reasonable if you see it flapping, but below 0.90 it stops meaning anything.

## Gate 3, script integrity

Blocks delivery. Needs `--script` and a configured model.

### Why it is hard

A speaker reading from a teleprompter does not read it verbatim. They paraphrase, they elaborate, they skip. All of that is correct behaviour and none of it is damage. Meanwhile a cut that removes two words from a sentence is damage.

A similarity threshold cannot separate those cases. Both look like "the delivery differs from the script."

### How it works

Word-align the delivered speech to the script with `difflib.SequenceMatcher`. Score every script sentence by how much of it matched. Above 80 percent it counts as delivered and needs no review. Below 15 percent it was skipped on purpose and is allowed. Everything in between is ambiguous and goes to a model, with both texts in front of it, for a single verdict of FINE or DAMAGED plus a reason.

The prompt says outright that paraphrase, elaboration and skipping are all acceptable, and gives worked examples of each. The only failure is speech the editor destroyed.

### The splice ledger

A model judging a transcript can be wrong in a way the audio is not. That happened here: the gate flagged "it sounds like having all the answers" delivered as "it sounds like head is all the answer," and blocked the render. The audio was fine. The speech model had misheard, with confidence of 0.34 on "head" and 0.48 on "answer."

So the pipeline keeps a ledger of every splice position, remapped through each subsequent cut into the final timeline. A sentence can only be ruled damaged when a cut actually landed inside it. If no splice falls in that span, the edit did not touch those words, whatever the transcript claims, and it gets logged as a transcription artifact for review instead of blocking.

The catch that motivated this gate had a splice running straight through it, so it still blocks.

### Without a model

A mechanical heuristic takes over: a sentence is damaged when an interior run of three or more script words is missing while both flanks matched. That is the signature of a cut through the middle of a sentence, and it is the only pattern detectable without semantics. It is meaningfully weaker, since it cannot recognize a paraphrase, so it errs toward flagging.

### How it was validated

Run against the known-bad master it flagged 14 damaged sentences and correctly passed the 2 the speaker had skipped deliberately. Against the repaired render: 0 damaged, 27 delivered, 1 skipped.

## Gate 4, retake residue

Blocks delivery.

Re-transcribes the delivered master and runs the same repeated-phrase detection the cutter uses. Anything it finds is a flubbed take that survived into the finished video.

Every other guarantee in this pipeline checks the artifact rather than the plan. Retake removal was the one job still trusted to simply run correctly, and it failed in a way that was invisible from the inside: the detector removed a spoken self-correction and the bad take following it, but its walk-back to catch the aborted fragment in front stopped at the fragment's own sentence boundary. The stumble stayed in the video while everything around it was cleaned up, and no check was looking at the output for repeats, so it shipped.

Repeats that appear twice in the script are ignored, the same shield the cutter uses, since a phrase written twice is deliberate.

Run against the render that shipped wrong, it blocks and names each survivor:

```
retake residue: 4 flubbed take(s) SURVIVED - DELIVERY BLOCKED
  x [139.6-155.2] "A man with in or woman. Alright, let's make that clear..."
```

## The non-blocking checks

These populate `QA_REPORT.json` and mark a run for review without stopping delivery.

Loudness has to sit within 1.5 LUFS of target. The black-frame check is brand-aware, so dark runs inside diagram and card windows are treated as intentional rather than dropped frames. Without that exemption it false-fails on every gold-on-black card. The font check warns when your font is not installed and a system fallback was used. Speech retention confirms a sane fraction of the source survived, and there are sanity checks on captions and output variants.

## Reading a report

```json
{
  "checks": {
    "lip_sync_verified": {
      "ok": true,
      "probes": [{"t": 31.93, "mae": 0.1, "offset_ms": 0.0, "ok": true}]
    },
    "word_integrity": {
      "expected_words": 619, "found_in_master": 616,
      "ratio": 0.995, "ok": true
    },
    "script_integrity": {
      "script_sentences": 35, "delivered": 27,
      "skipped_by_speaker": 1, "suspects": 8,
      "damaged": [], "judge": "deepseek", "ok": true
    }
  },
  "pass": true,
  "release": {"16x9": {"file": "...", "sha256": "d740ac21..."}}
}
```

The `sha256` is a hash-lock. It identifies exactly the bytes that passed, so if the file changes afterwards it no longer matches the report that cleared it.
