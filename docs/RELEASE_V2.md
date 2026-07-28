# v2.0.0: I stopped letting the editor grade itself

I shipped ten videos with lip-sync drift. The source recordings were within
15ms. The editor introduced the error, rendered it, and passed its own QA.

That failure changed the design of this project. Version 2 treats every model
answer, intermediate file, cache entry, and delivery encode as untrusted until
the finished artifact proves the claim.

## Watch the code walkthrough

[![Watch the narrated v2 walkthrough](https://github.com/CEOmarabha/talking-head-autoeditor/releases/download/v2.0.0/mainframe-v2-walkthrough.jpg)](https://github.com/CEOmarabha/talking-head-autoeditor/releases/download/v2.0.0/mainframe-v2-walkthrough.mp4)

[Watch or download the 1:06 MP4](https://github.com/CEOmarabha/talking-head-autoeditor/releases/download/v2.0.0/mainframe-v2-walkthrough.mp4).
It is hosted on this release and does not require a Mainframe account.

Mainframe narrated this walkthrough from the v2 pull request. It finished a
few minutes after the release was published, which is why it was missing from
the first version of this page. The
[successful GitHub check](https://github.com/CEOmarabha/talking-head-autoeditor/runs/90422810538)
is the build receipt.

![Existing before and after demo](https://raw.githubusercontent.com/CEOmarabha/talking-head-autoeditor/v2.0.0/docs/media/demo.gif)

The clip above is the original before-and-after demo. It shows the editor
removing a repeated take, cropping the camera file, adding punch-ins, and
burning timed captions. The v2 evidence below comes from measured failures,
synthetic media fixtures, and the real DeepSeek API.

## The bug that forced the rewrite

The RAW files were already synchronized. Container audio and video durations
were within 15ms, and the raw-referenced result was about -33ms, one frame of
ordinary 30 fps bias.

The automatic offset estimator binned an 8 kHz audio envelope with
`8000 // 30`, or 266 samples per bin. That clock runs at 30.075 Hz. The video
clock runs at 30 Hz. The mismatch looks like audio drifting late by roughly
150ms per minute.

Every reading pointed the same way. The pipeline applied +100ms on one pass
and -200ms on another, creating drift in files that started clean. The
estimator's shift test still passed because a known shift moves a biased peak
by the expected amount. It proved internal consistency.

The old sync gate compared the master with the internal cut file. Both files
inherited the same correction, so visibly broken output reported 0.0ms.

The first source-referenced gate caught the bad master at -233ms. That result
matched the bogus -200ms correction plus one 30 fps frame.

| Check | Old result | v2 result |
|---|---:|---:|
| RAW stream duration difference | within 15ms | accepted as source evidence |
| Biased automatic estimate | about +150ms per minute | retired from decisions |
| Bad applied correction | certified itself | rejected against RAW sidecar |
| Internal master-to-cut probe | 0.0ms | kept as a local render check |
| Finished master-to-RAW probe | absent | blocked at -233ms |

## The new trust boundary

DeepSeek handles creative planning. Python and FFmpeg handle evidence, timing,
rendering, and release.

```text
RAW + script
    |
    v
transcribe and cut on integer frame/sample indices
    |
    v
DeepSeek V4 Pro director -> deterministic validator -> V4 Pro critic
    |
    v
resolve every planned asset -> render to *.UNVERIFIED.mp4
    |
    v
finished-artifact gates -> hash lock -> promote or block
```

The model cannot cut speech, change A/V offset, choose final timecodes, waive a
gate, or move a file out of quarantine.

## Source sync now has an independent oracle

The production default is 0ms. A nonzero correction must come from a human
calibration ladder written to `<RAW>.avoffset`. That sidecar records the exact
RAW SHA-256. Replacing the recording under the same filename invalidates the
certification.

Gate 5 runs on the native-canvas finished master. It picks speech probes
outside every recorded overlay window, matches 1.2 seconds of audio into the
RAW recording, then finds the corresponding RAW video frames. Its acceptance
rules include:

- at least four usable probes;
- a per-probe error no greater than 67ms;
- usable speech near both ends of the program;
- no coverage gap above 30 seconds;
- a unique audio peak;
- a motion-weighted three-frame visual match with a runner-up margin;
- at least two transcript words inside each audio needle;
- a strictly increasing master-to-RAW timeline.

Loud music, silence, repeated sentences, static frames, dense b-roll, and
irregular source cadence can make a good probe unusable. They cannot turn an
ambiguous probe into a pass. Too few usable probes keeps the master in
quarantine.

The delivery aspect is checked separately. A 9:16 center crop or a 16:9
portrait pillarbox must match the gated native master at distributed frames
and every planned visual midpoint. Decoded audio hashes must match too. A
correct-looking crop with replaced audio fails.

## Cut math is integer math

The first boundary fix snapped to 30 fps and then serialized seconds to three
decimal places. That decimal conversion changed which boundary frame FFmpeg
admitted. Two off-grid cut windows, leaving three kept ranges, produced 65ms
of stream mismatch.

Version 2 expresses video trims as integer frame indices. Audio trims use the
same indices multiplied by 1,600 samples per frame at 48 kHz. One filter graph
trims and concatenates the streams before the final AAC encode.

The reproduced case measured 0.3ms on the review machine. The regression limit
is 2ms. Audio is not snapped to 1,024-sample AAC packet boundaries because the
filter graph cuts decoded samples before one final encode.

## DeepSeek receives a production contract

V4 Pro sees the complete post-cut transcript and the available clip families.
It returns one versioned JSON edit plan with punch-ins, b-roll, and graphics.
Every event must carry an exact 5-to-20-word transcript quote.

Code finds that quote in measured word timings and replaces the proposed
timecode. It also checks:

- field names, types, ranges, durations, and layer spacing;
- opening punch-in and opening visual coverage;
- maximum gaps and event density;
- b-roll and graphic collisions;
- framework diagrams when the speaker teaches steps, signals, parts, or rules;
- every displayed word and number against nearby speech;
- every requested asset against its declared media type and duration.

A V4 Pro critic receives the candidate plus the exact validator errors. It can
rewrite the full plan up to three times. The render starts only after the same
deterministic validator returns 100.

There is no automatic model downgrade. An empty response, truncated JSON,
retired model alias, incomplete HTTP body, failed critic, unresolved diagram,
or corrupt cache file stops model mode. `--no-llm` is the explicit
deterministic mode.

The credentialed release fixture uses a framework lesson with spoken numbers.
The fixture is checked into
[`scripts/smoke_deepseek_v4.py`](https://github.com/CEOmarabha/talking-head-autoeditor/blob/v2.0.0/scripts/smoke_deepseek_v4.py), so this
claim can be repeated without reconstructing a private terminal command.

The completed post-fix run returned score 100 with a valid director, a valid
critic in one repair round, two punch-ins, two b-roll events, and one graphic.
A later three-run campaign caught a different invalid draft in every run:
invented graphic copy, an ungrounded punch quote, and an on-screen collision.
All three entered another repair round. The provider kept those responses open
past the smoke runner's original 10-minute ceiling, so I stopped them and fixed
the runner.

This release claims a working fail-closed V4 contract backed by one completed
live pass. It does not claim a three-run creative parity benchmark. Run the
tracked fixture three times, then watch a finished reference video before
making that stronger claim for a production setup.

## The artifact gets the last word

The finished master is re-transcribed. The release gates check word retention,
script meaning, retake residue, source sync, internal render sync, delivery
geometry, audio identity, planned visual presence, loudness, captions, and
provenance receipts.

One mechanical rule matters more than it sounds. If a splice of at least two
seconds crosses an almost absent script sentence, the sentence is marked
missing even when the semantic judge says `FINE`. A model cannot excuse
evidence that the cutter removed a whole thought.

Every finished render enters quarantine first:

```text
lesson.PSE_MASTER_16x9.UNVERIFIED.mp4
```

Every gate must pass before promotion:

```text
lesson.PSE_MASTER_16x9.mp4
```

The QA report records the promoted file's SHA-256. Any later byte change breaks
the link between the file and the report that cleared it. Telegram receives
the promoted file only, and a transcoded watch copy must match the gated
master in decoded audio, video geometry, stream start, and duration.

## Worked failures

[The regression proof file](https://github.com/CEOmarabha/talking-head-autoeditor/blob/v2.0.0/docs/examples/V2_REGRESSION_PROOFS.md) walks through
the exact input and expected result for the circular offset oracle, decimal
cut boundaries, invented on-screen facts, a missing sentence overruled by a
model, poisoned media cache, and aspect exports with replaced audio.

The safety suite contains 68 tests, including FFmpeg-generated media for both
aspect transformations. The release also runs `make check`, the writing
standard checker, and a credentialed V4 Pro plan fixture:

```bash
python3.11 scripts/smoke_deepseek_v4.py --run-id 1
python3.11 scripts/smoke_deepseek_v4.py --run-id 2
python3.11 scripts/smoke_deepseek_v4.py --run-id 3
```

The runner defaults to a 15-minute total deadline. It launches V4 in a child
process, so a streaming response cannot swallow the outer timeout.

## Upgrade

```bash
git pull
make install

make calibrate VIDEO=/path/to/raw.mov
make certify VIDEO=/path/to/raw.mov OFFSET=0
make edit VIDEO=/path/to/raw.mov SCRIPT=/path/to/script.txt
```

`SCRIPT` is required by the default policy. Existing nonzero `--av-offset`
arguments must be replaced by a source-bound certification for that exact RAW
file.

Outputs and policy details:

- [DeepSeek production contract](https://github.com/CEOmarabha/talking-head-autoeditor/blob/v2.0.0/docs/DEEPSEEK_WORKFLOW.md)
- [pipeline phases](https://github.com/CEOmarabha/talking-head-autoeditor/blob/v2.0.0/docs/PIPELINE.md)
- [artifact gate specification](https://github.com/CEOmarabha/talking-head-autoeditor/blob/v2.0.0/docs/VERIFICATION.md)
- [full changelog](https://github.com/CEOmarabha/talking-head-autoeditor/blob/v2.0.0/CHANGELOG.md)

## What this release can claim

DeepSeek V4 Pro now receives the same explicit production path every time, and
the pipeline blocks any plan that violates it. That closes the silent fallback
paths that made a weaker run look successful.

Creative taste still needs a person. A score of 100 proves grounding, pacing,
coverage, assets, and artifact integrity. It does not prove that a punch-in is
the exact one Omar would choose after watching a reference. The workflow now
makes that remaining judgment visible instead of hiding technical failures
inside it.
