---
name: pse-talking-head-autoedit
description: "Run the canonical PSE talking-head compiler with DeepSeek V4 Pro, mandatory script evidence, artifact QA, and fail-closed delivery."
version: 2.0.0
metadata:
  hermes:
    tags: [video, editing, talking-head, pse, deepseek-v4, ffmpeg, qa]
    category: media
---

# PSE Talking-Head Auto-Edit

This skill operates the existing compiler. It does not invent a parallel edit
workflow. The canonical code is
`~/Desktop/talking-head-autoeditor/autoeditor/`. The live command is
`hermes-pse-edit`, which imports that code through
`~/cinematic-autopilot/tools/hermes_pse_edit.py`.

## Required inputs

Every run needs:

1. One real RAW recording path.
2. The teleprompter script used for that recording.

Optional inputs are a music file, a background image, a human EDL, and a
human-certified A/V offset sidecar.

Never guess a missing path. If a script was not provided, accept only one
unambiguous same-stem sidecar next to the video, such as `take.txt` for
`take.mov`. Otherwise ask Omar for the script. Do not start a render without
it. The script is the artifact gate's ground truth, not creative source copy.

## Exact operating recipe

1. Resolve the RAW video to an existing absolute file.
2. Resolve the script to an existing absolute file.
3. Choose one delivery aspect:
   - long lesson or YouTube video: `16x9`
   - short or reel: `9x16`
   - if Omar specifies style or aspect, use his value
4. Check for `<RAW>.avoffset`. A missing certification means the trusted
   offset is zero. Never infer or auto-measure a correction.
5. Run one canonical command:

   ```bash
   hermes-pse-edit "<absolute RAW path>" \
     --script "<absolute script path>" \
     --style long \
     --aspects 16x9
   ```

   Add `--music`, `--background`, `--edl`, or `--no-burn` only when the input
   was explicitly supplied. Use `--no-llm` only when Omar explicitly requests
   deterministic heuristic mode.
6. Wait for the process to exit. Do not kill a healthy render because it is
   taking longer than an estimate.
7. Treat exit code 0 plus `QA_REPORT.json` with `"pass": true` as the only
   release result. A file containing `.UNVERIFIED` is never deliverable.
8. Report:
   - absolute output folder
   - QA pass or the exact failed checks
   - EDL counts and resolved sources
   - released file path, only when QA passed

## What DeepSeek V4 is allowed to do

DeepSeek V4 Pro is an untrusted creative planner and semantic critic. It runs
with JSON mode, thinking enabled, and maximum reasoning effort. It receives the
complete post-cut timed transcript and the allowed local clip families.

It may propose only:

- punch-ins on spoken emphasis
- stock search queries or typed flow, steps, and stat visualizations
- short graphics grounded to spoken words

It may not cut speech, choose an A/V correction, invent on-screen facts, write
arbitrary renderer commands, or certify its own output.

Every creative response must match
`pse-creative-edl/2026-07-28.1`. Deterministic code then:

- requires all schema fields and rejects unknown fields
- requires an exact 5-20 word transcript quote for every event
- retimes every event to measured word timing
- proves displayed copy and numbers were spoken near the anchor
- enforces duration, spacing, density, opening, coverage, diagram, and
  collision rules
- resolves and hashes every planned asset

The critic receives the same full contract, the current candidate, and every
deterministic validator error. Remaining errors feed the next full replacement
round, up to three bounded critic rounds. Exhaustion blocks the render. It
never becomes a successful heuristic result. Heuristic editing exists only
behind `--no-llm`.

## Deterministic media stages

1. Preflight container, streams, geometry, and duration.
2. Normalize to 30 fps and 48 kHz using only a certified A/V offset.
3. Transcribe with word timing.
4. Iterate silence, retake, false-start, noise, and dead-air cleanup.
5. Re-transcribe after every cut and restore script-backed caption spelling.
6. Build and validate the typed creative EDL.
7. Snap cuts to integer 30 fps frames and 1,600 audio samples per frame.
8. Apply continuous-stream punch-ins.
9. Resolve diagrams, stock, local catalog visuals, graphics, captions, SFX,
   music ducking, color, and loudness.
10. Render one quarantined aspect.
11. Run every artifact gate.
12. Promote the quarantined file only after the complete QA report passes.

## Artifact gates

The finished artifact must pass all of these:

- media integrity, duration, stream presence, black-frame, loudness, font,
  caption delivery, and banned-copy checks
- exact creative provenance and complete asset resolution
- visible evidence for every planned visual event
- native-canvas master versus pre-overlay A/V sync
- delivered aspect versus native master frame, audio, duration, and stream
  timing binding
- re-transcribed word integrity
- script integrity, with a whole sentence removed across a large splice
  mechanically blocked even if the semantic judge says it is fine
- retake and false-start residue detection on the final transcript
- master-to-RAW source sync using an independent certified oracle, unique
  speech needles, motion-aware frame matches, endpoint coverage, and
  monotonic raw mapping

There is no manual override that turns a failed gate into a released file.

## Failure handling

- Missing input: stop and request the exact missing path.
- Missing DeepSeek key: stop, unless Omar explicitly requested `--no-llm`.
- Creative contract or asset failure: report the validator error.
- QA failure: report the failed checks and the `.UNVERIFIED` path.
- Telegram failure: report that local release succeeded but remote delivery
  did not.
- Never delete or move the RAW recording after a failed render.

## Quality boundary

This workflow makes DeepSeek follow the same typed, evidence-backed compiler
path used by a strong human or coding agent. It can enforce fidelity, timing,
coverage, provenance, and delivery safety. It cannot mathematically guarantee
subjective taste on every possible recording. Aesthetic signoff remains a
human judgment when a project demands a particular emotional or editorial
voice.
