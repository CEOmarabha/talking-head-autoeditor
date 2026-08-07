# Web Product Architecture Decision

Date: 2026-08-07. Scope: private hosted AutoEditor for a small group of
nontechnical friends, Windows Chrome/Edge first.

## Verdict in one paragraph

The selected system is a single Cloudflare Worker (invite-only site + API +
job queue) with D1 for state and R2 for footage, and the ALREADY-VERIFIED
Python AutoEditor engine running as a render daemon on Omar's Mac, pulling
jobs over HTTPS. DeepSeek is driven by the engine's existing deterministic
contract plus a small typed proposal loop for chat revisions; no agent
framework is added. This disagrees with the proposed PydanticAI harness and
with Supabase, defers E2B and RunPod, and agrees that Hermes stays a
private admin sidecar. Reasoning and evidence below.

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
  already implement a fail-closed DeepSeek JSON contract with deterministic
  scoring (every plan must score 100), retry, and no silent fallback. This
  IS the "small custom DeepSeek tool loop", production-hardened by the v2
  incident writeup in `docs/RELEASE_V2.md`.
- REPO evidence: there is no AGENTS.md in the repository (the task brief
  said to read it; it does not exist on `main` or `friend-ready-app`).

## Options compared

1. Small custom DeepSeek loop (exists in repo). Native v4 support proven in
   production here; typed contract + deterministic validation already
   written; zero new deps; we add only a typed "edit proposal" schema for
   chat. CHOSEN.
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

- Web/API/auth/state/storage: one Cloudflare Worker + D1 + R2. The
  Cloudflare account is already connected and authorized in this
  workspace; free tier covers a friend group; no new vendor, no billing
  activation. Supabase REJECTED: a second vendor and auth stack to secure
  for a ~10-user invite list D1 handles in three tables.
- Rendering v1: a daemon on Omar's Mac (the machine where the engine is
  already verified, with ffmpeg, fonts, and the speech model warm). Zero
  cost, zero new attack surface, capacity is fine for friends. RunPod (or
  similar) is the documented scale-out path and is a PAID decision that
  will be asked about explicitly when needed.
- Resource acquisition v1: the engine's existing licensed-API b-roll path
  (Pexels/Pixabay) wrapped in receipts (source URL, license, hash,
  project). Arbitrary repo cloning / package installs for friends is
  DEFERRED: that capability plus E2B-style sandboxing lands only behind
  Omar-approved admin flow (Hermes side), per the Resource Broker rules.
  Nothing in v1 implies arbitrary internet media is legally usable.

## DeepSeek key threat model (summary; full doc in WEB_SECURITY.md)

Browser -> TLS -> Worker: key is AES-GCM encrypted immediately with a key
derived from a Worker secret and stored as ciphertext in D1. It is never
returned by any API, never logged, never placed in job rows, queue
payloads, URLs, or R2. The render daemon fetches ciphertext over an
authenticated channel and decrypts in process memory with the KEK (an env
var that exists only on the render host), injects it into the engine child
environment (`AUTOEDITOR_PACKAGED=1` mode reads env only, writes no
dotfiles), and drops it when the job ends. No third-party render queue
ever sees key material because the only queue is our own D1 table carrying
no key fields at all.

## Cost today

Cloudflare free tier (Workers, D1, R2 within free limits; R2 egress is
free), $0. Render compute: Omar's existing Mac, $0. Per-edit DeepSeek
usage: paid by each friend's own key, cents per edit. Total new billing
commitments: none.

## Migration path

- More users / heavier renders: containerize the daemon (it is a plain
  Python process with env-var config) and point N instances at the same
  queue from RunPod/EC2; the Worker API already treats workers as
  pull-based and stateless.
- PydanticAI: if #5193 lands and multi-model routing becomes real, wrap
  `providers.llm_json` behind the same interface; the typed proposal
  schema is already pydantic-shaped dataclasses.
- Capability installs: Resource Broker tool surface is specified in
  WEB_SECURITY.md; implement against an isolated sandbox vendor only after
  a paid-service decision.
