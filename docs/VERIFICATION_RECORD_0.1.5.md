# AutoEditor 0.1.5: verification record and semantic-QA gap analysis (2026-08-13)

Worktree: `C:\Users\MyEye\Documents\Codex\2026-08-11\files-mentioned-by-the-user-fix\work\autoeditor` (Windows host).
Team install: `C:\AutoEditor\Helper-0.1.5` (short path; nested worktree copy hits MAX_PATH).
Receipts: `desktop/team-dist/handoff-receipts/20260813T-team/INDEX.json`.
Guide: `docs/TEAM_DEPLOYMENT.md`.

## FINAL STATUS: team-proven on the installed path. Semantic QA stays disabled.

The earlier “one proof outstanding” line is obsolete. The installed engine has
now produced a **verified** (non-UNVERIFIED) master. Rechecked on disk this
session.

## Receipted and closed

- **EPIPE.** 0.1.4 closed (11 killed, 0 left). Current Electron smoke wrote
  `--output`, empty stderr, 0 WerFault, 0 EPIPE lines. Stale vision trees: 0.
- **Install provenance.**
  - asar `d1472123107a7d7ff5349d8e8fdafea3e7382d9ce8116182a0b0ba463b2a4cd2`
  - engine install=worktree `8407087d3d6aaeb02b7849e7ca1ec72a9683da5a962635ef8629f9b9a55d138c`
  - model lock `adc37855602e89d80260fbb8768aa2b87fb4b928f34d9765a4e6c267f554a1fa`
  - model tree `5ab9f376a07e111ed08957c6db3847e4531b55589f6dbfe3fdb35619171bbc21`
    (267,802,713 bytes, 9 files)
  - Official `--verify-only` passed on `C:\AutoEditor\Helper-0.1.5`.
- **Sine-only render (negative control).** 97 s. Deterministic visual 15/15,
  `semantic_evaluation: false`. Overall QA fail-closed (no speech). Master
  stayed `*.UNVERIFIED`. Correct refusal.
- **Spoken verified master (the last box).** 136 s from
  `C:\AutoEditor\Helper-0.1.5\resources\engine\autoeditor-engine.exe`.
  - File: `handoff-receipts/20260813T-team/verified-master-2/out/PSE_SHORT_9x16.mp4`
  - No `.UNVERIFIED` sibling
  - SHA-256 `6658decb4d3ae51c8d44adc36c45a694746dac0ede21adda300b082537820a08`
  - 11,184,221 bytes
  - `qa.pass: true`
  - Word integrity 100/100, lip-sync pass, sync-to-source 0 ms / 5 probes,
    retake residue none, script integrity pass, loudness -14.76 LUFS
  - Deterministic visual 15/15, `semantic_evaluation: false`
- **Camera take (negative control).** `IMG_0827_STORY_PROXY_V4.mp4` (45 s)
  was also run. Same build refused promotion: surviving retake 15.3–17.6 s,
  one lip-sync MAE 15.5, one 300 ms sync probe. Receipted.
- **Zero network / no orphans.** No established remote TCP; 0 leftover
  `autoeditor-engine.exe`; 0.1.4 gone.
- **Test sweep.** Desktop `npm test` exit 0 (17.4 s). Python 56 tests including
  real FFmpeg exit 0 (8.0 s). Frozen engine `--self-test` pass.

## Semantic QA (standing)

Stays disabled. `visual_quality_analysis` stays in `FIXTURELESS_CHECKS`.
Qwen3-VL clean-pass ceiling 14.63% vs 90% floor (12/82 accepted, 85.37%
abstention). Defect recall ~14.7× short. MCC ≈ 0 vs 0.84. Deterministic QA
is the release gate.

**Guardrail:** do not remove `visual_quality_analysis` from
`FIXTURELESS_CHECKS` to turn policy checks green. Do not treat a fail-closed
`requireSemanticVisualQualification()` reader as activation. Activation still
requires the sealed qualification contract (both backends, three identical
runs each, zero network, ≥1,680 human-labeled cases, the published
thresholds, exact hash binding, same evaluator in production).

## History

A Mac-bridged session on 2026-08-13 could not see this worktree and left
items 1/3/6 marked unstarted. Windows execution produced the receipts above.
A later note still said “no verified master”; that is no longer true.
