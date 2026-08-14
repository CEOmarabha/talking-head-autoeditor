# AutoEditor 2026 to 2034 Contract

Status: contract version 1 is implemented. Migration of the current v2 to v5
engine receipts into this format is still open.

This contract preserves the trust rules without making Electron, Python,
FFmpeg, DeepSeek, or one frozen binary permanent. The reference reader lives
in `autoeditor_law/`. The schemas and their written meaning are the authority.
The package is replaceable.

## Claim Levels

An archive states one assurance grade. A higher grade must contain every role
required by the lower grades.

| Grade | Claim |
| --- | --- |
| `identity` | The master bytes still match the recorded SHA-256. |
| `historical_record` | The archive contains the policy, receipts, schemas, specification, and build identity that recorded the 2026 decision. This grade does not prove who signed it or when. |
| `fresh_reverification` | A new implementation has the RAW bytes and the transitive evidence needed to recompute the required checks. |
| `resumption` | A new editor has the approved intent, project state, revision state, render profile, reference source, and every dependency needed to make another revision. |

The verifier rejects a claimed grade when a required role is absent. A source
hash or locator cannot satisfy `fresh_reverification` when the RAW bytes are
gone. The archive can still retain the lower grade it can prove.

## Item Zero: Preserve RAW and Its Clocks

Every archive intended for fresh re-verification or resumption carries the
original camera bytes. It also carries a source map that records:

- container and stream identities;
- video frame ordinal, presentation timestamp, duration, and rational timebase;
- audio sample index, sample rate, channel layout, and stream start;
- known dropped frames, independent clocks, and declared source defects;
- each human AV correction, its scope, subject hashes, reason, and signer authority.

RAW is the provenance root. It is not assumed to be free of capture defects.
The verifier preserves the observed clock relationship and checks any declared
correction instead of copying a source defect into the master.

## What Freezes

The following meaning freezes when an archive is issued:

- manifest bytes and every bound digest;
- schema, policy, algorithm, unit, and canonicalization identifiers;
- source frame, timestamp, and sample mapping;
- receipt result, evidence reference, promotion event, and human exception;
- incident fixtures and their expected outcomes;
- the ability to evaluate the artifact under its historical policy.

The system keeps these rules across new projects:

- a planner proposal cannot authorize promotion;
- missing or unsupported required evidence blocks promotion;
- final timing comes from integer positions on a declared rational grid;
- speech edits remain grounded to protected transcript spans and source audio;
- old receipts remain immutable;
- promotion binds the exact master bytes to the full required evidence set.

The current `*.UNVERIFIED` name and missing final sibling remain a safety
barrier. The archive manifest is the lasting evidence. A filename by itself is
never proof that checks ran.

## What Can Change

These parts can change under new identifiers:

- planner model, vendor, prompts, and critic;
- desktop shell, implementation language, packaging, and installer;
- decoder, encoder, renderer, and media preservation profile;
- check algorithm or threshold;
- policy composition for a new project;
- semantic model, taxonomy, calibration, and qualification set;
- hash or signature algorithm for new archives.

A changed unit, default, threshold meaning, required field, result meaning, or
algorithm gets a new identifier. It never changes the meaning of an old one.

## Registry and Compatibility

`autoeditor_law/schema_registry.json` is the schema inventory. It binds every
supported schema ID to exact local schema bytes. It also freezes the legacy
schema IDs currently emitted by the engine, desktop, packaging, and training
tools.

Compatibility rules:

1. A reader accepts only an explicitly supported schema ID whose schema digest
   matches the registry.
2. An unknown required schema returns `unsupported`. It cannot count as a pass.
3. A writer emits one declared version. An archive never stores `latest`.
4. Algorithm and policy changes receive new IDs even when the JSON shape stays
   the same.
5. A migration creates a new linked artifact. It does not rewrite an old
   receipt.
6. Historical verification uses the historical policy. Current
   requalification writes a separate receipt under the current policy.
7. Every issued compatibility archive stays in the corpus.
8. CI fails when production code emits an unregistered schema literal.

The old `visual_quality_analysis` capability name is retired as ambiguous.
The registry separates:

```text
urn:autoeditor:capability:deterministic.visual.rgb24
urn:autoeditor:capability:semantic.visual.calibrated
```

Capability, check, algorithm, payload schema, policy, and artifact-contract IDs
have separate namespaces. A capability claim does not double as a receipt.

## Planner Adapter

The planner adapter emits `urn:autoeditor:schema:planner-proposal:1`. Provider
and model names are provenance fields. The proposal carries a hash-bound
`urn:autoeditor:schema:edit-intent:1` payload and a qualification receipt for
the exact adapter bytes.

The planner intent contains:

- a declared rational tick grid;
- the transcript hash;
- 5-to-20-word transcript anchors;
- an integer duration for each proposed visual;
- closed parameters for punch-ins, b-roll, graphics, and diagrams.

It contains no speech-cut authority and no final timecodes. Deterministic code
locates each anchor in measured word timing, compiles the final EDL, and owns
frame and sample placement. A replacement planner must pass the incident suite
before its proposals are accepted.

## Render Adapter

The render adapter accepts `urn:autoeditor:schema:render-request:1`. The request
binds:

- archive manifest;
- planner proposal;
- compiled EDL;
- source map;
- render profile;
- policy;
- renderer, FFmpeg, and FFprobe hashes.

The stable boundary is a CLI-readable JSON request and receipt chain. Electron
can call it, but Electron does not define it.

## Evidence Receipt

Every new receipt uses `urn:autoeditor:schema:receipt-envelope:1` and separates:

```text
capability_id
check_id
algorithm_id
payload_schema_id
policy_id
artifact_contract_id
```

The envelope binds the subject digest, result, evidence files, producer source
hash, and typed payload. Results are `pass`, `fail`, `unsupported`, or
`accepted_with_exception`.

A nonzero AV correction uses `accepted_with_exception`. It records the
measurement, allowed bound, exact RAW and output hashes, affected policy,
reason, signer authority, and scope. A bare boolean cannot certify it.

## Archive Layout

The logical layout is:

```text
manifest.json
schemas/
spec/
conformance/
media/original/
media/canonical/
media/assets/
project/
evidence/receipts/
evidence/blobs/
exceptions/
output/master.mp4
provenance/
signatures/
reference-source/
```

`manifest.json` is a closed inventory. Every file except the manifest is listed
with role, byte length, and digest. Unlisted files, missing files, symlinks,
path escapes, changed bytes, and unsupported required schemas fail closed.

An archive may declare an external signature anchor. Contract version 1 binds
the signature file and reports it as
`declared_not_cryptographically_verified`. A future signature adapter must
check the signature and the outside trust anchor before making a stronger
authorship or timestamp claim.

## Semantic Vision Decision

The fixed 1,680-label build is parked as the next milestone. Qualification
tooling remains, and semantic promotion authority stays disabled.

The current evidence is technical screening:

- 82 Qwen3-VL decisions;
- 12 accepted and 70 abstained;
- 6.45% affirmative recall;
- 14.63% maximum clean-pass rate against a 90% floor;
- zero real semantic labels in the repository.

This is not usage research. No longitudinal installed-app study, organic
accept/reject/re-edit history, user interview set, or real usage cohort exists.

The next research lane is local and consented:

1. Record a receipt-bound reason when a person accepts, rejects, or re-edits a
   visual decision.
2. Keep raw video and labels on the device unless the person explicitly exports
   a research bundle.
3. Measure the real class distribution before setting per-class quotas.
4. Revisit a sealed qualification run after about 1,000 organic labels and a
   local model passes a separate 100-case screen.
5. Split by person, camera session, client, and device. Near-duplicate frames
   cannot cross development and qualification sets.
6. Keep required semantic checks fail-closed. Advisory checks may abstain, but
   they cannot confer promotion authority.

## Migration Gates

Contract version 1 has completed the first gate:

- standard-library reader and CLI;
- hash-locked JSON schemas;
- schema registry and legacy inventory;
- planner, edit-intent, render-request, and receipt validators;
- one committed 2026 identity archive;
- tests for tamper, missing RAW roles, unknown schemas, planner qualification,
  and unregistered production schema IDs.

The remaining gates are ordered:

1. Write an archive builder that imports one current `QA_REPORT.json` and its
   bound sidecars without changing them.
2. Publish the source-map schema and produce one real
   `fresh_reverification` archive from a verified 2026 master.
3. Wrap the current DeepSeek path in the planner envelope and qualify the exact
   adapter against the v2 incident suite.
4. Put the current engine behind the render-request CLI and emit the new
   evidence envelope beside legacy receipts.
5. Add signature verification and an outside trust anchor.
6. Build Mac and Windows from one commit, then install and run the same archive
   corpus on both shipped artifacts.
7. Add consented local usage-research hooks. Semantic qualification stays a
   separate later decision.

## 2034 Acceptance Test

A 2034 tool passes when it can:

1. verify every archive file and schema digest;
2. state the archive grade without overstating it;
3. evaluate the historical policy with the historical fixtures;
4. recompute required checks when RAW and transitive evidence are present;
5. import approved intent and project state into a new revision;
6. keep the 2026 master immutable;
7. write new receipts under new identifiers.

The committed identity fixture proves only the first archive grade. No current
delivery has been converted into a fresh-reverification or resumption archive
yet. The current engine still emits its v2 to v5 contracts until the migration
gates above pass.
