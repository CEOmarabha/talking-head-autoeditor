# AutoEditor: blocked report and semantic-QA gap analysis

**Date:** 2026-08-13  
**Target worktree:** `C:\Users\MyEye\Documents\Codex\2026-08-11\files-mentioned-by-the-user-fix\work\autoeditor`  
**Status on this Windows host:** items 1, 3, and 6 are receipted, including a
QA-passing verified master. Items 2, 4, and 5 stay decided: semantic visual QA
remains disabled. See `docs/VERIFICATION_RECORD_0.1.5.md`.

This file supersedes the MacBook-bridged note that claimed items 1, 3, and 6 were
not startable. That note was written from `ceomarabhas-macbook-pro-local` with no
mount of this worktree. The diagnosis of the **model gap** in that note is
still correct and is preserved below.

---

## Current Windows-host status

| Item | Mac note | Actual state on this worktree |
| --- | --- | --- |
| 1 EPIPE | not started | Fixed and proven on current Electron, not 0.1.4 |
| 2 Semantic QA | stay disabled | Stay disabled. Still in `FIXTURELESS_CHECKS` |
| 3 Hybrid architecture | not started | Preserved. Deterministic QA is the release gate |
| 4 Training / labels | stay disabled | Tooling exists. No fabricated labels. Corpus still 0 |
| 5 Qualification | stay disabled | Blocked. No sealed receipt. Not advertised |
| 6 Package / smoke / deploy | not started | 0.1.5 portable built, launched, E2E rendered |

Evidence paths:

- EPIPE harness: `desktop/scripts/vision-capability-electron/safe-output.js`, `main.js`
- Fixtureless lock: `desktop/helper/lib/runtime-capability-check-runner.js`
- Qwen screen: `.local-tools/qwen3vl-bakeoff-1ee355f/results/20260813T143335Z-ccf84e41/result.json`
- Machine-readable gap: `desktop/team-dist/semantic-visual-blocked-report.json`
- Team portable: `desktop/team-dist/AutoEditor-Helper-0.1.5-windows-x64-portable`
- Deployment: `docs/TEAM_DEPLOYMENT.md`
- E2E deterministic sidecar: `desktop/team-dist/e2e/render-out-6c/DETERMINISTIC_VISUAL_QA.json`

`requireSemanticVisualQualification()` exists in preflight as a **fail-closed
reader**. With no sealed documents it throws
`semantic_visual_qualification_unavailable`. It does not persist a result, does
not bind a qualification hash into a capability or promotion receipt, and does
not take `visual_quality_analysis` out of `FIXTURELESS_CHECKS`. Helper
production still requires that capability to be advertised first, which the
fixtureless check prevents.

---

## Why semantic visual QA cannot qualify

Source: `.local-tools/qwen3vl-bakeoff-1ee355f/results/20260813T143335Z-ccf84e41/result.json`

Qwen3-VL 2B:

| Measure | Observed |
| --- | --- |
| Total decisions | 82 |
| Accepted (non-abstained) | 12 |
| Abstained | 70 |
| Abstention rate | 85.37% |
| Affirmative recall | 6.45% |
| Wall-clock | ~18 minutes |
| Peak RAM | ~5.5 GB |

The qualification contract counts abstentions as errors for normal clean/defect
metrics. That rule decides the outcome:

- **Clean-pass ceiling.** Even if all 12 non-abstained decisions were perfect,
  the maximum clean-pass rate is 12/82 = **14.63%**. Required floor: 90%.
  Shortfall: **75.37 percentage points.** The ceiling is below the floor.
- **Defect recall.** Observed 6.45% against a required 95%. Shortfall:
  **88.55 percentage points**, about **14.73x**.
- **MCC.** With ~85% of decisions scored as errors, MCC sits near zero against
  a required floor of 0.84.

SmolVLM2 256M and 500M were worse: reject-everything classifiers, the same
failure mode at lower capability.

### What this rules out

No prompt rewrite, threshold change, protocol reordering, or counterbalancing
tweak closes a gap of this size. A 14.73x recall deficit is a model-capability
problem, not a calibration problem. Lowering thresholds to pass is out of
scope.

### Required state, preserved

- `visual_quality_analysis` **remains** in `FIXTURELESS_CHECKS`.
- No sealed qualification result is persisted.
- No qualification hash is bound into a capability or promotion receipt.
- Deterministic QA remains the release-blocking gate: black/blank frames,
  freezes, flashes, geometry, overlay presence/contrast/state, supported
  transitions. Those are not semantic, OCR, aesthetic, or intent evaluation.

### Guardrail

Removing `visual_quality_analysis` from `FIXTURELESS_CHECKS` to turn policy
checks green is forbidden. That would mark an unqualified capability as
available. If a proposed change makes policy checks pass without a sealed
qualification receipt, that change is wrong.

---

## Second blocker: corpus and annotators

Minimum qualification corpus:

```
(100 clean + 100 defective + 40 ambiguous) x 7 assertion classes = 1,680 cases
```

Classes: `target`, `captions`, `framing`, `visualVariety`, `graphics`,
`transitions`, `productionDesign`.

The development split must be source- and template-disjoint, so total labeled
volume exceeds 1,680.

- Labels must not be fabricated.
- Subjective cases need three blind annotators plus a distinct adjudicator.
- Qualification labels are sealed: never used for training, tuning, or
  development evaluation.

An automated agent cannot be those annotators. Semantic activation cannot
finish in one session. Tooling can be built; the gate is human annotator time.

Labeler and split tooling already live under
`desktop/scripts/semantic-visual-training/`.

---

## One-line summary

Semantic visual QA stays disabled: the measured abstention rate puts the
clean-pass ceiling (14.63%) below the required floor (90%) and leaves defect
recall about 14.7x short. Deterministic QA remains the release-blocking gate.
The Windows EPIPE fix, current 0.1.5 portable, and installed E2E smoke are
already on this worktree.
