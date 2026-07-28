# Verified talking-head auto-editor

[![release](https://img.shields.io/github/v/release/CEOmarabha/talking-head-autoeditor)](https://github.com/CEOmarabha/talking-head-autoeditor/releases/latest)
[![safety tests](https://github.com/CEOmarabha/talking-head-autoeditor/actions/workflows/ci.yml/badge.svg)](https://github.com/CEOmarabha/talking-head-autoeditor/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![license](https://img.shields.io/github/license/CEOmarabha/talking-head-autoeditor)](LICENSE)

Point it at a raw camera file. It removes silence, deletes the takes you flubbed and re-read, cuts your coughs, adds punch-ins, pulls topical b-roll, animates diagrams for the frameworks you teach, burns word-synced captions, normalizes loudness, and hands you a finished file.

Then it re-watches its own work and refuses to deliver the video if it broke anything. That second part is the reason this project exists.

```bash
make edit VIDEO=~/Movies/lesson1.mov SCRIPT=lesson1.txt
```

```
phase 1.6  CFR normalize -> 30fps grid + AV offset (audio +100ms)
phase 2    word-guarded cut removed 18 pause(s), kept 92%, all 622 words preserved
           retake cut: [73.3-75.7]  7-word repeat, keeping the later take
           retake cut: [141.9-155.2] 3-word repeat plus self-correction aside
           false-start cut: [220.0-223.7] 2-word prefix repeat
           head-noise cut: [0.00-0.35] opening cough
phase 4p   EDL via deepseek-v4-pro: 9 punch-ins, 10 b-roll, 9 graphics
phase 7    QA gate
           sync probe @31.9s: offset=0.0ms OK      (x5)
           word integrity: 616/619 words in master (99.5%) PASS
           script integrity: 27 delivered, 1 skipped by choice, 0 DAMAGED
QA: PASS
```

## Current release

[Version 2.0.0](https://github.com/CEOmarabha/talking-head-autoeditor/releases/tag/v2.0.0)
changes the trust boundary after ten renders shipped with lip-sync drift. The
source files were synchronized. A biased automatic estimator applied a bad
correction, then the old gate compared two files that shared the same mistake
and reported 0.0ms.

The correction estimator is retired from production decisions. Source sync is
measured from the finished master back to the RAW recording, nonzero offsets
need a source-bound human certification, cut math uses integer frames and
samples, and every DeepSeek plan must pass a deterministic score of 100.

Read [the complete incident and v2 design](docs/RELEASE_V2.md), or jump to the
[worked regression inputs](docs/examples/V2_REGRESSION_PROOFS.md).

## See it run

![Before and after](docs/media/demo.gif)

Left is the raw camera file, letterboxed, 50 seconds, containing a line the speaker flubbed and immediately said again. Right is what came back: 41 seconds, the flubbed take gone, black bars cropped, punch-ins and word-synced captions applied, loudness normalized.

That is a real run of this repo, not a mockup. The [v1.0.0 release](https://github.com/CEOmarabha/talking-head-autoeditor/releases/tag/v1.0.0) has the full clip with audio, and the terminal log from the same run is in [docs/DEMO.md](docs/DEMO.md).


## Why it works this way

Automatic editors are easy to build and easy to trust wrongly. The failure mode is not a crash. It is a video that looks fine, runs the right length, and quietly has your words missing from it.

This one was built by shipping exactly that, repeatedly, and then engineering it out. These failures now have permanent detectors:

A run once deleted 152 of 623 words mid-sentence. "Assigning status for around five hundred million years" came out as "around Philly." The cutter was classifying speech by loudness, and soft word-endings fell under the threshold. Duration retained was 55 percent, which cleared the guardrail on a technicality. Cutting is now driven by the transcript instead of the waveform, so silence can only be removed between padded word spans.

A second detector deleted the phrase "Superiority, Autonomy," from the sentence that introduces the whole framework. It cut spans where the speech model's confidence dropped below 40 percent, on the theory that low confidence meant a flub. The model was simply unsure of an unusual word. The delivery was perfect. Words that appear in the script are now shielded from that detector.

A third bug left a 21-second dead tail after the speech ended, because a stale duration value meant the caption layer was built to the pre-cut length. Duration is recomputed after every cut now, and the sync probe that landed in that tail is what caught it.

The pattern connecting all three: every signal the editor trusts is a proxy, and proxies lie. Loudness stands in for speech. Model confidence stands in for clarity. Duration stands in for content. So the architecture stopped relying on proxies alone and started checking the finished artifact against what should be in it.

## The artifact gates

After rendering, the pipeline re-analyses its own output file. Every release gate can stop delivery outright. The completed render stays under an `*.UNVERIFIED.mp4` quarantine name until all gates pass, then it is promoted to the final delivery name.

### Lip-sync verification

Five probe points spread across the finished master, each shifted so it lands outside every punch-in, b-roll and graphic window recorded in the EDL, since the speaker's face is not on screen during those. At each point it compares the master against the pre-overlay cut in both streams: image match on the upper frame band above the captions, and normalized cross-correlation on the audio.

Fails if any local render-equivalence probe drifts more than 25ms. The independent source gate also requires four usable probes, endpoint and gap coverage, a unique audio match, an unambiguous motion-weighted frame match, a strictly increasing RAW mapping, and a per-probe error no greater than 67ms. It derives raw spatial normalization inside the gate and searches a bounded neighborhood around fixed timeline anchors, so a fresh verifier process and an overlay on one exact endpoint cannot silently change coverage.

This check has one blind spot: it compares the master against the cut, and
both inherit whatever the correction stage did, so it passes happily on a
wrong correction. A separate gate covers it by measuring the native-canvas
master directly against the raw recording, matching audio by cross-correlation
and video by frame comparison. That gate blocked a render at -233ms and named
the exact bad correction that caused it.

The released aspect is then bound back to that native master. The gate
reconstructs the exact 9:16 center crop or 16:9 portrait foreground, checks
distributed frames and every planned visual midpoint, and requires matching
decoded audio, duration, and stream start. This lets source sync remain
geometrically meaningful without trusting an ungated recrop. Details are in
the verification doc.

### Word integrity

Re-transcribes the delivered master and sequence-aligns it against the transcript from the cut stage. This catches damage introduced after cutting, by compositing or re-encoding or a bad filter graph. Fails below 96 percent retention or above 40 missing words.

### Script integrity

The interesting one. It word-aligns the delivered speech against the script that was read, scores every script sentence, and hands each ambiguous one to a model that classifies it.

Paraphrasing is fine. Skipping a sentence is fine. Adding your own elaboration is fine. The only failure is speech the editor destroyed: chopped mid-thought, a concrete fact replaced by nonsense, a sentence that ends in garble.

That distinction is the hard part, and it is why a model does the judging instead of a similarity threshold. Both of these differ from the script, and only one is a problem:

```
FINE      script: "Superiority is not a comparison you win. It is a fact you carry."
          heard : "superiority isn't something you win against people, you just carry it"

DAMAGED   script: "it has been assigning status for around five hundred million years"
          heard : "it's been a signing status for around Philly"
```

The gate also cross-references its own splice ledger. A sentence can only be
ruled damaged if a cut actually landed inside it. Without that check it would
block videos over words the speech model merely misheard, which happened
before the ledger existed.

A nearly absent sentence with a recorded splice of at least two seconds in its
script gap is different: deterministic evidence marks it mechanically missing.
The semantic model cannot certify that loss as an intentional skip.

When a splice-implicated sentence would block, the gate transcribes only that
window from the finished master again with the medium speech model. It clears
the blocker only if the second pass recovers all meaningful script terms
missing from the first pass and covers at least 80 percent of the sentence.
Cut labels never exempt a sentence, and disagreement still blocks.

Real output from a blocked render:

```
script integrity: 26 delivered, 1 skipped by choice, 8 reviewed -> 1 DAMAGED
  script: 'There are three signals your Lizard Brain broadcasts... Superiority, Autonomy, and Certainty.'
  heard : '...reads in every single human interaction and certainty. S -A'
  why   : lost Superiority and Autonomy, only one of three named
delivery: RuntimeError: script damage, video delivery blocked
```

### Retake residue

The cutting stage removes flubbed takes. This gate proves it worked, by running the same repeat detection over the finished master. A duplicate phrase found here means a flub shipped.

It exists because retake removal was the last job still trusted to run correctly, and it did not. A self-correction and the bad take after it were removed while the aborted fragment in front of them stayed in the video, and nothing caught it, because no check was looking at the delivered file for repeats. Run against that render, this gate blocks and names all four survivors.

Full detail in [docs/VERIFICATION.md](docs/VERIFICATION.md).

## What it does to your footage

Four cutting detectors run in sequence. All of them work from the transcript, so a cut can never land inside a word.

`word_guarded_cut` removes silence between words, padded on both sides. `detect_retakes` finds lines you said twice, keeps the last read, and swallows the self-correction you muttered in between ("let me say that again"). It checks your script first, since a phrase that repeats there is deliberate writing rather than a flub. `detect_false_starts` catches restarts that change the ending, like "You never hesitate" becoming "You never compromise," where the repeat is too short for the run matcher to see. `detect_head_noise_audio` removes the cough on the opening frame, which speech models transcribe as a low-confidence word and ordinary cough detectors therefore miss.

DeepSeek V4 Pro authors the edit decision list, then a V4 Pro critic rewrites
it. Remaining deterministic errors feed up to three bounded critic repair
rounds. Every event must quote the words that justify it.
Deterministic code finds that quote in the measured word timeline, replaces the
model's proposed time, proves every displayed word and number was spoken
nearby, and checks the opening hook, visual coverage, event spacing, density,
collisions, and framework diagrams. Model mode fails closed. `--no-llm` is the
explicit deterministic heuristic mode.

Finishing is karaoke captions where each word lights up as it is spoken, sparse sound design, two-pass loudness to -14 LUFS, aspect-correct export, and a SHA-256 hash-lock with a QA receipt.

Every phase is explained in [docs/PIPELINE.md](docs/PIPELINE.md). The exact
model contract and stop conditions are in
[docs/DEEPSEEK_WORKFLOW.md](docs/DEEPSEEK_WORKFLOW.md).

## Install

macOS or Linux, Python 3.10 or newer, about 2GB of disk for models and cache.

```bash
git clone https://github.com/CEOmarabha/talking-head-autoeditor.git
cd talking-head-autoeditor
make install
```

That checks for ffmpeg and installs it if missing, builds a virtualenv, installs four Python packages, downloads the speech model, and sets up the Remotion diagram renderer if you have Node.

```bash
cp .env.example .env      # add the keys used by your selected mode
make check                # confirm everything resolves
```

### What each key buys you

| Key | Cost | Without it |
|---|---|---|
| `DEEPSEEK_API_KEY` | usage priced by DeepSeek | Use explicit `--no-llm`; ambiguous script damage follows the mechanical fail-closed path |
| `PEXELS_API_KEY` | free | Pixabay or local catalog must resolve each planned stock beat |
| `PIXABAY_API_KEY` | free | One fewer b-roll source |
| `ELEVENLABS_API_KEY` | optional | Synthesized sound-effect kit instead |
| `TELEGRAM_BOT_TOKEN` | free | No push to your phone, files land on disk |

DeepSeek V4 Pro runs the creative director and critic passes with thinking
enabled, maximum reasoning effort, and JSON mode. A third V4 Pro call runs only
when the artifact transcript leaves an ambiguous script sentence. Transcription,
cutting, timing, compositing, captions, diagrams, and every release gate remain
deterministic.

Every planned event must carry a contiguous 5-20 word quote copied exactly from
the complete post-cut transcript. Model timecodes are only proposals. The
validator finds that quote in measured word timings and writes the canonical
time before rendering.

## Use it

```bash
# build the ladder for this recording
make calibrate VIDEO=~/Movies/lesson1.mov

# certify the human-selected result for this exact RAW
make certify VIDEO=~/Movies/lesson1.mov OFFSET=0

# then edit
make edit VIDEO=~/Movies/lesson1.mov SCRIPT=lesson1.txt

# vertical pacing for short-form
make edit VIDEO=~/Movies/clip.mov STYLE=short ASPECT=9x16
```

`SCRIPT` is required by the default brand policy. It powers caption correction,
which fixes misheard words while leaving deliberate paraphrases alone, and it
feeds the semantic gate. Change `rules.require_script_gate` only when a
scriptless production is an intentional policy decision.

You get back the master, an SRT sidecar, `EDL.json` with every creative decision and its timing, `QA_REPORT.json` with the gate results and hash-lock, and `SCRIPT_INTEGRITY.json` with the sentence-by-sentence verdicts.

A 4-minute video takes 20 to 35 minutes on Apple Silicon. It is CPU-bound, and transcription and compositing dominate.

## Make it yours

Colours, font, caption density, how aggressively it cuts, and the gate thresholds all live in [brand.yaml](brand.yaml). You never edit Python to change a look.

The creative instincts live as director principles in `autoeditor/premium.py`. They are prose inside the prompt, covering what earns a punch-in, when a diagram beats stock footage, and how sparse the sound design should be. Rewrite them in your own voice.

## Ideas worth stealing

Verify against the artifact rather than the plan. Re-analysing the rendered file catches a class of bug that inspecting intermediate state never will.

Let the judge see both texts. Asking a model whether something is damaged, with the script and the delivery side by side, beats any similarity threshold, because it separates intent from accident.

Fail loudly in the log. A swallowed NameError silently disabled every large-file delivery here for days, and the only symptom was that videos never arrived.

Parse model JSON by scanning for balanced braces. A greedy regex swallows trailing prose and throws, which quietly degrades whatever depended on it.

Retry the model call. One dropped request collapsed 12 b-roll clips down to 1, and the video just looked a bit plain.

## License

MIT, see [LICENSE](LICENSE). Use it commercially, fork it, sell what you make with it.

Built by [Omar](https://github.com/CEOmarabha).
