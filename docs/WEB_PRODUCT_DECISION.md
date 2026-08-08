# Web Product Architecture Decision

Date: 2026-08-07. Scope: private hosted AutoEditor for a small group of
nontechnical friends, Windows Chrome/Edge first.

## Verdict in one paragraph

The selected system is a single Cloudflare Worker (invite-only site + API +
job queue) with D1 for state and private R2 transfer storage. Each friend’s
signed Helper pulls that friend’s jobs and runs the Python engine on that
friend’s Windows PC or Mac. DeepSeek uses a small typed proposal loop for chat
revisions; no agent framework is added. PydanticAI and Supabase are not part of
this release, E2B and RunPod remain deferred, and Hermes stays a private admin
sidecar. Production deployment and signed-artifact acceptance are still open.

## Evidence log (what kind of evidence each item is)

- OFFICIAL/GitHub issue: PydanticAI's DeepSeekProvider currently fails with
  400 errors on tool-based structured output against `deepseek-v4-pro` /
  `deepseek-v4-flash` (the exact models this repo uses):
  [pydantic-ai issue #5193](https://github.com/pydantic/pydantic-ai/issues/5193).
  The documented workaround (pin the `deepseek-chat` legacy alias) died
  when the alias sunset on July 24, 2026, which has already passed. The fix
  PR is not merged at time of writing.
- OFFICIAL security press: a June 2026 flaw chain exposing self-hosted
  LangGraph agents to remote code execution:
  [The Hacker News](https://thehackernews.com/2026/06/langgraph-flaw-chain-exposes-self.html).
  Not disqualifying forever, but a bad fit for "expose to nontechnical
  friends this month."
- OFFICIAL docs: R2 multipart uploads driven from a Worker are a
  documented first-class pattern:
  [Cloudflare R2 docs](https://developers.cloudflare.com/r2/api/workers/workers-multipart-usage/).
- OFFICIAL/community consensus: ffmpeg cannot meaningfully run inside
  Cloudflare Workers (wasm experiments only:
  [ffmpeg.wasm discussion #782](https://github.com/ffmpegwasm/ffmpeg.wasm/discussions/782)),
  so rendering must happen on real compute regardless of framework choice.
- VENDOR pricing pages (secondary): E2B bills per-second with a limited
  free tier ([Beam's pricing breakdown](https://www.beam.cloud/blog/e2b-pricing-explained),
  [Morph](https://www.morphllm.com/e2b-pricing)); RunPod is metered GPU
  billing. Both require activating billing, which this project's authority
  limits forbid without asking.
- ACCESS NOTE: I could not read Reddit threads or X posts directly from
  this environment; searches surfaced blogs and official docs instead. No
  community anecdotes are cited as evidence, and nothing above depends on
  them.
- REPO evidence: `autoeditor/providers.py` + `autoeditor/creative_contract.py`
  implement a fail-closed DeepSeek JSON contract with deterministic scoring
  (every plan must score 100), retry, and no silent fallback. This is the small
  custom DeepSeek loop described in the v2 incident writeup in
  `docs/RELEASE_V2.md`. Signed friend-artifact acceptance remains separate.
- REPO evidence: there is no AGENTS.md in the repository (the task brief
  said to read it; it does not exist on `main` or `friend-ready-app`).

## Options compared

1. Small custom DeepSeek loop (exists in repo). The direct v4 path and typed
   deterministic validators exist without a new framework dependency. The
   signed friend product still needs end-to-end acceptance. CHOSEN.
2. PydanticAI. Good library, but tool-based structured output against the
   v4 models is broken today (#5193) with the alias workaround already
   sunset, and it would wrap a contract the repo already enforces better
   (deterministic 100-score gate). Adopting it now means adopting a known
   open bug on our exact model IDs. REJECTED for v1; revisit if the repo
   ever needs multi-model routing.
3. Hermes Agent. Full agentic terminal; per-user isolation and
   authorization for nontechnical friends is unproven here, and friends
   never need a terminal. Stays as Omar's private research/admin sidecar.
   AGREED with original plan.
4. LangGraph / Deep Agents. Graph orchestration solves problems this
   product does not have (the pipeline is a linear, deterministic DAG the
   engine already owns), and the June 2026 RCE chain argues against
   exposing a self-hosted instance to invited outsiders now. REJECTED.
5. OpenHands. An autonomous software-engineering agent, wrong shape for a
   render service with strict determinism requirements. REJECTED.
6. Simpler option found: no framework at all. The engine is the agent
   harness; the web layer is a queue. CHOSEN (this is option 1).

## Infrastructure choices

- Web/API/auth/state/storage: one Cloudflare Worker + D1 + private R2. The repo
  carries the intended bindings, but the production resources and billing
  state must be verified in Cloudflare before launch. Supabase remains outside
  this release.
- Rendering v1: each friend’s signed Helper renders on that friend’s computer.
  The browser first uploads footage to private R2, the Helper downloads it,
  renders locally, and uploads the finished MP4 and QA receipt. An optional
  owner-wide daemon uses the same queue but is not required for the normal
  friend path. RunPod or another hosted render service requires a separate
  cost, privacy, licensing, and deployment decision.
- Resource acquisition v1: the engine's existing licensed-API b-roll path
  (Pexels/Pixabay) wrapped in receipts (source URL, license, hash,
  project). Arbitrary repo cloning / package installs for friends is
  DEFERRED: that capability plus E2B-style sandboxing lands only behind
  Omar-approved admin flow (Hermes side), per the Resource Broker rules.
  Nothing in v1 implies arbitrary internet media is legally usable.

## Executable friend contract

The six friend profiles are `generic_short`, `generic_long`,
`generic_commercial`, `generic_podcast`, `generic_course`, and
`generic_custom`. They back Short, long talking head, Commercial, Podcast,
Course, and Custom. PSE stays separate. Long-to-clips is excluded until the
engine can select moments and produce several independently gated outputs.

Revision chat can change only edit style, aspect ratio, burned or sidecar
captions, full or baseline visuals, and the selected generic profile. Baseline
is the engine’s complete no-premium mode. The contract does not relabel it as
fewer punch-ins. Speech deletion, duration targeting, clip splitting, specific
asset replacement, caption scaling, grading, and granular punch-in or b-roll
controls are rejected before rendering.

## DeepSeek key threat model (summary; full doc in WEB_SECURITY.md)

Browser -> TLS -> Worker: the key is AES-GCM encrypted immediately with a key
derived from a Worker secret and stored as ciphertext in D1. It is never
logged, placed in job rows, queue payloads, URLs, or R2. A personal Helper can
receive only its own user’s unwrapped key over the authenticated HTTPS claim
path. The optional global owner daemon receives ciphertext and unwraps it with
the local KEK. The daemon injects the key into the engine child environment,
and the in-process reference is dropped when the job ends. The D1 queue itself
contains no key fields.

## Cost today

Local Helper rendering avoids a separate hosted GPU bill. It does not remove
Cloudflare storage and request usage, DeepSeek API usage, or paid provider and
license costs. Each friend pays DeepSeek usage through that friend’s own key.
Cloudflare cost depends on the active account plan, stored footage, request
volume, and current pricing. Check the real dashboard before launch. No fixed
monthly or per-edit total has been accepted.

## Migration path

- More users or heavier renders: containerize the daemon and point isolated
  hosted instances at the queue only after the separate cost, privacy,
  licensing, and operational review passes.
- PydanticAI: if #5193 lands and multi-model routing becomes real, wrap
  `providers.llm_json` behind the same interface; the typed proposal
  schema is already pydantic-shaped dataclasses.
- Capability installs: Resource Broker tool surface is specified in
  WEB_SECURITY.md; implement against an isolated sandbox vendor only after
  a paid-service decision.
