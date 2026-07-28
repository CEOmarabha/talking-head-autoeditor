# DeepSeek V4 Production Contract

This file is the operating contract for a model-driven edit. DeepSeek proposes
creative intent. Python and FFmpeg own media timing, rendering, and release.
The model cannot cut speech, alter A/V offset, waive a gate, or deliver a file.

## Required Inputs

- One raw camera recording with audio and video.
- One teleprompter script passed with `--script`.
- A valid `DEEPSEEK_API_KEY`.
- `DEEPSEEK_MODEL=deepseek-v4-pro`.
- A source-bound `.avoffset` sidecar for any nonzero A/V correction.
- Stock API keys or local clip catalogs when the plan calls for b-roll.

`rules.require_script_gate: true` blocks the command before transcription when
the script is missing. `--no-llm` is the explicit path for a deterministic
heuristic edit. A failed DeepSeek call never selects that path by itself.

## Phase Contract

| Phase | Input | DeepSeek responsibility | Deterministic responsibility | Output or stop condition |
|---|---|---|---|---|
| 0. Preflight | Raw file, script, calibration | None | Check streams, duration, orientation, script, and certified A/V offset | Stop on missing input or uncertified offset |
| 1. Normalize | Raw file | None | Deletterbox, convert to 30 fps, preserve certified offset | CFR source and measured media facts |
| 2. Speech edit | CFR source | None | Transcribe, detect pauses and retakes, cut on integer frame and sample indices, iterate to convergence | Post-cut master timeline and word timings |
| 3. Director | Complete post-cut transcript and clip families | Propose punch-ins, b-roll, diagrams, and graphics | Send JSON mode request with thinking enabled and maximum reasoning effort | Complete `pse-creative-edl/2026-07-28.1` object or stop |
| 4. Contract check | Director JSON | None | Require every key and type, ground every event and displayed claim to spoken evidence, replace proposed times with measured word times, check duration tolerance, minimum spacing, density, collisions, hook, coverage, and framework diagram use | Canonical EDL or validator errors |
| 5. Critic | Complete transcript, current JSON, validator errors | Rewrite the full EDL after checking meaning, pacing, and every contract rule | Re-run the same validator and feed exact remaining errors into up to three bounded repair rounds | Score 100 or stop |
| 6. Asset resolution | Canonical EDL | None | Render planned diagrams exactly; resolve ordinary b-roll through Pexels, Pixabay, or the local catalog; render graphics | Every planned event gets the requested asset class or stop |
| 7. Render | Canonical EDL and post-cut media | None | Apply continuous-stream punch-ins, composite visuals, burn captions, mix SFX and music, normalize loudness | Quarantined `*.UNVERIFIED` master |
| 8. Artifact gates | Native master, delivered aspect, raw file, script | Judge only ambiguous script sentences with V4 Pro | Check speech retention, word integrity, retake residue, source sync, aspect-derivative binding, stream properties, planned visual presence, receipts, and file hashes | Promote only when every gate passes |
| 9. Delivery | Promoted master | None | Confirm watch-copy duration and send only the gated artifact | Delivery receipt |

## DeepSeek Request

The provider sends:

```json
{
  "model": "deepseek-v4-pro",
  "response_format": {"type": "json_object"},
  "thinking": {"type": "enabled"},
  "reasoning_effort": "max",
  "max_tokens": 32768
}
```

The user prompt contains the word `json`, the full output example, all ten
planning steps, the complete post-cut transcript, the measured duration, the
style, and the allowed clip families. Transcript text is labeled untrusted
data in both the system message and the user message.

The provider rejects retired aliases, non-stop finish reasons, empty content,
partial top-level objects, malformed JSON, transport failures, and validator
failures. It retries transient failures, does not retry permanent 4xx
configuration failures, handles truncated HTTP bodies, and writes a safe
receipt without the API key or response body.

## Creative EDL Schema

Every response contains these top-level fields:

```json
{
  "protocol_version": "pse-creative-edl/2026-07-28.1",
  "timeline_space": "post_cut_seconds",
  "punch_ins": [],
  "broll": [],
  "graphics": []
}
```

Every event contains numeric `s` and `e`, a 5-20 word `anchor_quote` copied
exactly from the transcript, and a concrete `reason`. Punch-ins add `scale`.
B-roll adds a stock `query`, a valid or empty `family`, and an optional typed
`viz`. Graphics add a supported `kind`, uppercase `text`, and only the fields
used by that kind. Display copy rejects markup and control characters before
it can reach an HTML or frame renderer. Titles, labels, list items, and
displayed numbers must also match words or numeric meaning spoken near the
anchor. A real anchor cannot launder invented on-screen claims.

The model's `s` and `e` values are proposals. The validator requires the full
normalized quote to occur contiguously in word-level ASR, rejects short,
paraphrased, or invented anchors, and writes the measured time into the
canonical EDL. This prevents a fluent model from placing a correct visual on
the wrong sentence.

## Mechanical Quality Score

A model plan ships only at 100:

- 25 points for an opening punch-in grounded to the opening spoken line.
- 20 points for b-roll or graphics inside the style opening window.
- 25 points for keeping the maximum visual gap within 12 seconds for shorts or
  75 seconds for long lessons.
- 20 points for a diagram when the transcript teaches numbered steps, signals,
  parts, pillars, stages, rules, principles, or ways.
- 10 points for typed, grounded, non-colliding events within density limits.

Every item is mandatory. The score is a receipt format, not a way to average
away a failed rule. Per-layer event starts must also remain at least the style
spacing apart, so a model cannot spend its entire punch-in budget during the
opening and still receive density credit.

## Production Receipt

`EDL.json` records:

- protocol version;
- source and exact model;
- reasoning effort;
- prompt SHA-256 for director and critic;
- attempt results and finish reasons;
- complete transcript SHA-256 and word count;
- SHA-256 of the exact validated EDL that reached the renderer;
- director and critic contract results, including director errors and every
  bounded critic repair round;
- asset source for each planned b-roll event;
- SHA-256 for every resolved b-roll asset;
- planned, resolved, and unresolved counts for b-roll and graphics.
- measured duration for every resolved b-roll asset.

`QA_REPORT.json` recomputes the transcript, contract-code, and validated-plan
hashes, then checks the asset counts again from the render run. It also probes
the midpoint of every b-roll and graphic window in the caption-free upper 55
percent of the composited master. Each probe must differ from the pre-overlay
frame by more than a dynamically sampled off-window compression baseline.
At least two off-event controls must exist. The delivered aspect is separately
bound to the native-canvas master at distributed frames and every planned
visual midpoint. That gate also requires the decoded audio hash, stream start,
and duration to match. A file cannot pass by claiming
`source: deepseek` without two successful V4 Pro receipts, a contract score of
100, resolved assets, and measured visual changes in the artifact.

## Failure Policy

- Missing DeepSeek key in model mode: stop.
- Missing operator-supplied script, EDL, music, or background path: stop.
- Contradictory options that would ignore an EDL, background, or model choice:
  stop.
- Retired or unknown DeepSeek model: stop.
- Empty, partial, truncated, or malformed model output after retries: stop.
- Director contract error: send the errors to the critic.
- Critic contract error: stop.
- Planned visual without a renderable asset: render may finish in quarantine,
  but release fails.
- Invalid, short, corrupt, or wrong-orientation cache entry: remove it and
  retry resolution. Downloads and diagram renders publish atomically only
  after media validation.
- Resolved b-roll shorter than its planned window: stop instead of freezing its
  last frame through the event.
- Planned diagram that does not render: stop at asset QA; never substitute stock
  footage while retaining diagram credit.
- Missing or incomplete semantic judgment: mark every cut-implicated suspect as
  damaged and keep the master quarantined.
- Whole scripted sentence absent across a recorded splice of at least two
  seconds: block mechanically. A model verdict cannot clear it.
- Any artifact gate failure: retain `*.UNVERIFIED` and do not send video.

## Operator Commands

Model-driven production:

```bash
python -m autoeditor RAW.mp4 --script SCRIPT.md --out OUTPUT
```

Explicit deterministic production:

```bash
python -m autoeditor RAW.mp4 --script SCRIPT.md --no-llm --out OUTPUT
```

Live compatibility command:

```bash
~/cinematic-autopilot/tools/hermes_pse_edit.py RAW.mp4 \
  --script SCRIPT.md --out OUTPUT
```

The live command imports the canonical repository module. It does not carry a
second copy of the production code. `make install` also publishes the tracked
Hermes operator skill, which requires both RAW and script paths and documents
the V4 Pro fail-closed workflow.

## Verification Before Claiming Parity

Run the unit and fault tests, then a credentialed DeepSeek smoke plan. For a
release candidate, run the same transcript fixture three times. Each run must
produce complete JSON, score 100, resolve every planned asset, and pass the
finished-master gates. Human review still decides whether the editorial taste
meets the current reference video. That human decision cannot be replaced by a
schema score.
