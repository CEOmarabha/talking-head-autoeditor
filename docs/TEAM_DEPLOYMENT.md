# AutoEditor Helper 0.1.5 — team handoff

This is the local team package from the current Windows worktree. It is not a
signed CI `nsis-web` installer. Semantic visual evaluation is **not**
production-ready.

All numbers below come from the measured receipt pack:

`desktop/team-dist/handoff-receipts/20260813T-team/INDEX.json`

## Share and install

Upload the **zip**, not the raw 21,032-file folder:

`C:\AutoEditor\AutoEditor-Helper-0.1.5-windows-x64.zip`

Friends extract to a **short** path, then verify before launch. A 4 GB
Proton Drive hop is where a truncated model pack hides.

```
C:\AutoEditor\Helper-0.1.5
verify-model-pack.cmd
```

That runs official `--verify-only`:

```
python verify\extract_cached_vision_model.py --verify-only --output C:\AutoEditor\Helper-0.1.5\resources\models\vision\smolvlm2-067788b187b95ebe
```

Expected: lock `adc37855602e89d80260fbb8768aa2b87fb4b928f34d9765a4e6c267f554a1fa`,
tree `5ab9f376a07e111ed08957c6db3847e4531b55589f6dbfe3fdb35619171bbc21`.

Do not share the nested `desktop\team-dist\...` copy. MAX_PATH breaks the verifier.

| Role | Path |
| --- | --- |
| Zip to upload | `C:\AutoEditor\AutoEditor-Helper-0.1.5-windows-x64.zip` |
| Extract to | `C:\AutoEditor\Helper-0.1.5` |
| Launch | `C:\AutoEditor\Helper-0.1.5\AutoEditor Helper.exe` |
| Rollback | untouched 0.1.4 portable |

Do not launch 0.1.4. On this machine, 11 0.1.4 processes were closed first.
After that close: 0 remaining 0.1.4 processes, 0 WerFault, 0 EPIPE lines in
the 0.1.5 `debug.log`.

## Hash identity

| Object | SHA-256 |
| --- | --- |
| Installed `app.asar` | `d1472123107a7d7ff5349d8e8fdafea3e7382d9ce8116182a0b0ba463b2a4cd2` |
| Installed engine | `8407087d3d6aaeb02b7849e7ca1ec72a9683da5a962635ef8629f9b9a55d138c` |
| Worktree engine | same as installed |
| Helper `main.js` in asar vs worktree | `788f3e784b50e2a6261e3364eb64af1a0e99c6b9ccbe1f51fe9ae762cc119481` match |
| Model pack lock | `adc37855602e89d80260fbb8768aa2b87fb4b928f34d9765a4e6c267f554a1fa` |
| Model pack tree | `5ab9f376a07e111ed08957c6db3847e4531b55589f6dbfe3fdb35619171bbc21` |
| Model pack size | 267,802,713 bytes (9 files) |

Official `--verify-only` passed on `C:\AutoEditor\Helper-0.1.5\resources\models\vision\smolvlm2-067788b187b95ebe`.
Model: `HuggingFaceTB/SmolVLM2-256M-Video-Instruct` revision
`067788b187b95ebe7b2e040b3e4299e342e5b8fd`.

## Machine requirements (this box)

- Windows 11 Home, Intel i7-1185G7, 16 GiB RAM, Intel Iris Xe ~1 GiB
- Deterministic QA: 16 GiB RAM is enough
- Semantic training/qualification: needs 32 GiB RAM and 16 GiB dedicated VRAM. This box cannot do that.

## Measured latency

| Step | Measured |
| --- | --- |
| Desktop `npm test` (37 suites) | 17.4 s, exit 0 |
| Python visual/render/FFmpeg tests (56) | 8.0 s, exit 0 |
| Frozen engine `--self-test` | pass |
| Installed engine E2E render | **97 s** |
| Qwen3-VL 2B screen (not production) | ~18 min, 5.5 GiB RAM |

## Installed render receipts

A sine-only clip still fail-closes, as it should. A spoken 44 s take through
the same installed engine produced a **verified** master:

- File: `handoff-receipts/20260813T-team/verified-master-2/out/PSE_SHORT_9x16.mp4`
- No `*.UNVERIFIED` sibling
- SHA-256: `6658decb4d3ae51c8d44adc36c45a694746dac0ede21adda300b082537820a08`
- Size: 11,184,221 bytes
- Runtime: 136 s
- `qa.pass`: **true**
- Word integrity 100/100, lip-sync pass, sync-to-source 0 ms / 5 probes,
  retake residue none, script integrity pass, loudness -14.76 LUFS
- `deterministic_visual_quality.ok`: **true**, 15/15,
  `semantic_evaluation`: **false**

The spoken take is a unique verification script, not a camera talking-head.
A real camera take (`IMG_0827_STORY_PROXY_V4.mp4`) was also run: the same
gates blocked promotion for a surviving retake and a 300 ms sync probe. That
refusal is also receipted.

## Network and orphans

- After the render: 0 `autoeditor-engine.exe` leftovers, 0 ffmpeg leftovers
- Established remote TCP from the engine/Helper during and after the render: **none**
- Live Helper from `C:\AutoEditor\Helper-0.1.5`: 4 processes, 0 remote established, 0 engine orphans, 0.1.4 still gone

Vision is not advertised. The Electron harness still cancels `http://*/*` and
`https://*/*`. Semantic inference is not run in production.

## QA policy in this release

Release-blocking visual checks are deterministic: black/blank frames, freezes,
flashes, geometry, overlay presence/contrast/state, supported transitions.
They are not semantic, OCR, aesthetic, or intent evaluation.

`visual_quality_analysis` stays in `FIXTURELESS_CHECKS`. Do not remove it to
turn policy checks green.

## Semantic QA status

**Blocked. Not trained. Not reliable. Not advertised.**

Qwen3-VL 2B screen: 12/82 accepted, 70/82 abstained, 6.45% affirmative recall.
Abstentions count as errors, so the clean-pass ceiling is 14.63% against a 90%
floor. Defect recall is about 14.7× short. Prompt or threshold changes cannot
close that. Labels were not fabricated. Qualification still needs 1,680
human-labeled cases.

## Rollback

1. Quit `C:\AutoEditor\Helper-0.1.5\AutoEditor Helper.exe`.
2. Launch the untouched 0.1.4 portable.
3. Leave `C:\AutoEditor\Helper-0.1.5` in place for comparison.
