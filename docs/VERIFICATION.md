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

Five points rather than one because timeline drift can accumulate. This is a local render-equivalence check, not proof that the source itself was synchronized. Gate 5 supplies that independent reference.

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

At probe points chosen outside every overlay window, take 1.2 seconds of the master's audio and find where it sits in the raw recording by cross-correlation. Then find which raw frame the master is showing at that moment, matching a three-frame temporal band against spatially normalized RAW frames. Video time minus audio time is the true end-to-end desync, measured with no model and no opinion.

An external review of the first version found two holes, both fixed:

The applied offset was also the oracle. The gate compared its measurement against the correction the pipeline had just applied, so a wrong `--av-offset -200` would measure -200, match -200, and pass. Now the oracle is independent: the only trusted nonzero correction is one a human calibration stored in `<recording>.avoffset`. The sidecar contains the selected offset and the exact RAW SHA-256, so replacing a file under the same name invalidates the calibration. An applied value that does not match the certified value is rejected before rendering, and gate 5 checks the value again as defense in depth.

The frame reference was the CFR intermediate, which inherits the same defects as the master. Frames are now matched against the raw file itself, replaying only the spatial deletterbox chain.

The review also hardened the acceptance rules: every probe must individually sit within 67ms, since a median hides staircase drift; usable probes must cover both ends of the delivered speech and may not be more than 75 seconds apart, including edge coverage; audio matches need a uniqueness margin over the second-best peak so a repeated sentence cannot match the wrong take; frame matches need a margin over the runner-up so a static shot cannot match ambiguously; probes require transcript words inside the needle, not just waveform energy; and the master-to-raw time mapping must strictly increase, because cuts only remove material. A backward high-confidence match now blocks the run instead of being silently discarded. The frame score weights pixels that move across the three-frame sample, so facial motion is not drowned out by a static background. Container audio/video start-time differences are included when mapping decoded samples back to RAW presentation time.

Validated against a render a viewer had rejected by eye: blocked at median -233ms, which named the bogus -200ms correction plus one frame of CFR bias.

The hardened gate also passed an aligned synthetic master at six distributed
probes with median 0ms, worst 0ms, and maximum gap 8 seconds. The same source
with audio delayed by 200ms failed at every usable probe with median and worst
both 200ms.

### The cut-boundary fix that rides along

Video trims quantize to the frame grid while audio trims cut at sample precision. The first fix snapped boundaries to the grid but then serialized them as three-decimal strings, and a rounded value flips whether the boundary frame is admitted: a three-range repro measured 65ms of A/V mismatch. Trims are now built from integers only, video by frame index and audio by sample index at exactly 1600 samples per frame. After every cut the stream durations are compared, and a mismatch above one frame aborts the render.

The regression suite reproduces the former off-grid ranges and requires the
encoded audio and video stream durations to remain within 2ms. The current
result is below 1ms.

### Calibration workflow

`make calibrate VIDEO=/path/to/raw.mov` builds the human comparison ladder. After watching it, `make certify VIDEO=/path/to/raw.mov OFFSET=0` writes the source-bound sidecar. Use the selected signed value instead of zero when another ladder clip wins. Calibration is per RAW file, not a reusable camera-rig constant.

### Known fail-closed boundaries

These cases can block a good video, but they do not certify a bad one:

- A loud music or SFX bed can push needle correlation below 0.6. The concrete trigger is a 1.2-second speech window where the added bed carries enough unshared energy to erase the RAW speech peak. That probe is discarded; fewer than four usable probes blocks delivery.
- A visually static talking head can leave too little timing evidence. The concrete trigger is fewer than 0.5 percent of pixels changing by four gray levels across the three-frame band, or a runner-up frame score within 1.0 of the winner. The probe is discarded.
- B-roll or graphics can cover too much of the program. The concrete trigger is fewer than four speech probes outside the recorded overlay windows, missing either speech endpoint by more than ten seconds, or a gap above 75 seconds. Delivery blocks for insufficient coverage.
- Silence cannot become evidence. The concrete trigger is fewer than two transcript word midpoints inside a 1.2-second needle. The candidate is skipped.
- VFR RAW files are searched by presentation time and their audio/video stream start-time delta is preserved. Irregular cadence can still make the 30fps neighborhood ambiguous, in which case the frame margin rejects the probe.
- A staircase can hide between sampled probes if it begins and ends inside one unsampled interval. The per-probe worst-case rule prevents the median from hiding a sampled staircase, but the 75-second coverage ceiling is still sampling, not a continuous proof.

These are deliberate false-block conditions. A face-tracked mouth ROI and a music-robust speech matcher would reduce them, but neither is claimed by the current implementation.

## Foundational release checks

These populate `QA_REPORT.json`. A failed check leaves the artifact under an `*.UNVERIFIED.mp4` quarantine name and blocks upload. Completed renders enter quarantine before QA begins, so an exception inside a gate cannot strand an ungated file under a final-looking name. Only a full PASS promotes the file to its delivery name.

Loudness has to sit within 1.5 LUFS of target. The black-frame check is brand-aware, so dark runs inside diagram and card windows are treated as intentional rather than dropped frames. Without that exemption it false-fails on every gold-on-black card. The font check warns when your font is not installed and a system fallback was used. Speech retention confirms a sane fraction of the source survived, and there are sanity checks on captions and the selected output.

The release CLI produces one aspect only. The former `--aspects all` path was removed because only the first derivative was being gated. A large Telegram watch copy is also compared directly against the gated master in both audio and video after transcoding; matching duration alone is not accepted as proof.

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
