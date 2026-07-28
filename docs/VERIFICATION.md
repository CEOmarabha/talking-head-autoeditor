# Verification

The editor's job isn't to make cuts. It's to make cuts **and prove it didn't break anything.**

This document explains the three gates: what each measures, why it exists, how it fails, and how to tune it.

---

## The problem gates solve

An automatic editor makes thousands of decisions per video. Almost all of them are invisible when wrong. A dropped word doesn't crash anything — it produces a video of the right length, with correct captions, that plays fine and is missing a sentence you needed.

Worse, the obvious checks pass. Consider the run that deleted 152 of 623 words:

```
speech_retention  kept_ratio 0.55  ok: true     <- threshold was >= 0.55
loudness          -14.2 LUFS      ok: true
captions_present                   ok: true
lip_sync          5/5 probes 0.0ms ok: true
QA: PASS
```

Every check passed. The video was destroyed. `speech_retention` measured *duration*, which is a proxy for content, and the proxy lied.

The fix isn't a better threshold. It's checking a different thing: **re-analyse the delivered file and compare it to what should be in it.**

---

## Gate 1 — Lip-sync verification

**Blocks delivery.**

### What it does

Picks five probe points spread across the master, then shifts each one so it lands *outside* every punch-in, b-roll and graphic window recorded in the EDL — because during those the speaker's face isn't on screen and a comparison would be meaningless.

At each probe:

- **Video:** crops the frame band below the caption area (no overlays there), scales to 160×45 greyscale, and computes mean absolute error against the same timestamp in the pre-overlay cut.
- **Audio:** extracts a window at 8kHz from both, normalises, and cross-correlates across ±200 lags to find the offset that maximises correlation.

### Why five points and not one

Timeline drift is monotonic — it accumulates. If the first and last probes are both aligned, nothing in between can be off without one of them showing it. Five spread points is cheap and conclusive.

### Passes when

Every probe reports frame MAE < 12 **and** audio offset within `sync_tolerance_ms` (default ±25ms).

### What it caught

Four distinct root causes, each found because this gate refused to pass:

1. Per-segment concat accumulating AAC frame-rounding at every boundary (~20–40ms each) → rebuilt as single-pass filter graphs
2. Trim/concat dropping frames → punch-ins re-implemented as in-place `zoompan`
3. Variable-frame-rate source with dropped frames → always-on CFR normalisation before anything else
4. A 21-second dead tail (a probe landed in it and returned `mae=99.0`)

### What it cannot catch

**Offset baked into the source recording.** The gate compares the master against the cut — both inherit the source's offset, so both agree, and it reports a clean 0.0ms on a file whose lips never matched.

This is not a flaw in the check; it's a category error to expect otherwise. Nothing internal can detect it. That's what [`calibrate.py`](../autoeditor/calibrate.py) is for: a human watches a ladder of candidate offsets once per recording setup, and the winner goes in `brand.yaml`. See the module docstring for why automated mouth-motion correlation was tried and abandoned.

---

## Gate 2 — Word integrity

**Blocks delivery.**

### What it does

Transcribes the **delivered master** — not any intermediate file — and sequence-aligns it against the transcript taken right after cutting. Reports the fraction of words that survived.

### Why it's separate from gate 3

This one is about **mechanical damage after the cut stage**: a bad filter graph, a truncated encode, an overlay that clobbered audio. It compares the pipeline against itself, so it is completely indifferent to what the speaker said or whether they followed a script.

### Passes when

`found_in_master / expected >= word_integrity_min` (default 0.97).

### Tuning

Two transcriptions of identical audio disagree by roughly 1–3% — speech models are not deterministic across runs. So 0.97 sits just above the noise floor. Real damage is not subtle: the incident that motivated this gate scored **0.75**. Lowering to 0.92 is reasonable if you see flapping; going below 0.90 makes it decorative.

---

## Gate 3 — Script integrity

**Blocks delivery.** Requires `--script` and a configured LLM.

### The hard part

A speaker reading from a teleprompter does not read it verbatim. They paraphrase, elaborate, and skip. All of that is *correct behaviour*, and none of it is damage. Meanwhile a cut that removes two words from a sentence **is** damage.

A similarity threshold cannot separate these. Both look like "the delivery differs from the script."

### What it does

1. Word-aligns the delivered speech to the script (`difflib.SequenceMatcher`).
2. Scores every script sentence by how much of it was matched:
   - **≥80% matched** → delivered, no review needed
   - **<15% matched** → skipped on purpose, allowed
   - **in between** → ambiguous, needs judgment
3. Sends every ambiguous sentence to an LLM with both texts and asks for one verdict: **FINE** or **DAMAGED**, with a reason.

The prompt is explicit that paraphrase, elaboration, and skipping are all fine, and gives worked examples of each. The only failure is speech destroyed by the editor: garbled, truncated mid-thought, or a concrete fact (number, name, key term) replaced by nonsense.

### Why an LLM instead of rules

Because the distinction is semantic, and the model sees both texts at once:

```
FINE — script: "Superiority is not a comparison you win. It is a fact you carry."
       heard : "superiority isn't something you win against people, you just carry it"
       -> same idea, speaker's own wording

DAMAGED — script: "it has been assigning status for around five hundred million years"
          heard : "it's been a signing status for around Philly"
          -> concrete figure lost, sentence ends in nonsense
```

No rule distinguishes those two rows. The judge does it reliably.

### Fallback when no model is configured

A mechanical heuristic: a sentence is damaged if an interior run of ≥3 script words is missing while **both flanks matched**. That's the signature of a cut through the middle of a sentence, and it's the only pattern detectable without semantics. It's meaningfully weaker — it can't recognise paraphrase — so it errs toward flagging.

### Validation

Run against the known-bad master, this gate flagged **14 damaged sentences** and correctly passed the 2 the speaker had skipped deliberately. Against the repaired render: **0 damaged, 27 delivered, 1 skipped.**

---

## The non-blocking checks

These populate `QA_REPORT.json` and mark the run for review, but don't stop delivery:

| Check | Notes |
|---|---|
| `loudness` | Integrated LUFS within ±1.5 of target |
| `no_black_frames` | **Brand-aware** — dark runs inside diagram/card windows are intentional, not dropped frames. Without this exemption it false-fails on every gold-on-black card. |
| `brand_font` | Warns when your font isn't installed and a system fallback was used |
| `speech_retention` | Kept a sane fraction of the source |
| `captions_present`, `all_variants` | Sanity |

---

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

The `sha256` is a hash-lock: it identifies exactly the bytes that passed. If the file changes afterwards, it no longer matches the report that cleared it.
