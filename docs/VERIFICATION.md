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

### The blind spot, and what finally covered it

This gate compares the master against the cut. Both inherit whatever the correction stage did to the audio, so the gate reports a clean 0.0ms even when the correction itself was wrong. Ten renders shipped that way.

The first attempt to cover this was an automatic mouth-motion measurement of the source. It is retired from decision-making, and the story is instructive. Its audio envelope was binned with an integer-truncated hop, which skewed the audio timebase to 30.075Hz against the video's 30Hz. That looks exactly like the audio drifting late by 150ms per minute. Every measurement it produced pointed the same direction, each "correction" based on it created real desync where none existed, and a self-validation test passed because a known shift moves a biased peak by the same amount either way. An estimator validating itself proves consistency, not truth.

What covers the blind spot now is gate 5 below: measuring the finished master against the raw recording, which is the one reference that cannot inherit a mistake.

## Gate 5, sync to source

Blocks delivery.

At probe points chosen outside every overlay window, take 1.2 seconds of the master's audio and find where it sits in the raw recording by cross-correlation. That match is sample-accurate and survives loudness normalization at 0.99+ correlation. Then find which raw-timeline frame the master is showing at that same moment, by comparing a mid-frame band against the raw frames around the audio position. Video time minus audio time is the true end-to-end desync, measured with no model, no mouth heuristics, and no opinion.

The median across probes must sit within 60ms of the intended correction and the spread within 100ms, since two frame-grid quantizations alone account for about 66ms of spread.

Validated against the render a viewer had rejected by eye: the gate blocked it and reported the desync at -233ms, which matched the bogus -200ms "correction" that had been applied, plus one frame of CFR bias. The measurement found not just that the render was wrong but exactly what had made it wrong.

One structural fix rides along with this gate. Video trims quantize to the frame grid while audio trims cut at sample precision, so every cut boundary used to contribute up to 33ms of mismatch, and thirty boundaries random-walk that past 100ms. Cut boundaries are now snapped to the frame grid before cutting, which makes each segment's audio and video durations exactly equal.

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
