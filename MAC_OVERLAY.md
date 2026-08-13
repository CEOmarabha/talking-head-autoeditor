# work/general-editor-v020 — Windows 0.1.5 overlay for Mac

This branch is the dirty Windows 0.1.5 worktree Mac packaging needs.
It is not on `main`. Clone / checkout this branch, do not use Desktop `main` @ 4c41c58.

## Required identity hashes

- `desktop/helper/main.js` `788f3e784b50e2a6261e3364eb64af1a0e99c6b9ccbe1f51fe9ae762cc119481`
- `desktop/scripts/vision-capability-electron/safe-output.js` `3f47e7bb106093ffef5f846bf0f3facd6758ed4a8afe25a3f68643ca24a5da4e`
- `desktop/helper/lib/runtime-capability-preflight.js` `ee22f49bd9e838d85e26aa19cce9d0e7e145fbd3e5be6e93a5b7b526d59399a4`
- `desktop/helper/lib/runtime-capability-check-runner.js` `61ce4115ca0ab48781866129cbd776a173404eb868951dc5d004b8246fa42dbd`
- `packaging/extract_cached_vision_model.py` `c8d9ac344917ad6e776ca708f6f21275667b90e4b802a3234a95331f66041869`
- `packaging/vision-model-packs/smolvlm2-067788b187b95ebe/model-pack.lock.json` `adc37855602e89d80260fbb8768aa2b87fb4b928f34d9765a4e6c267f554a1fa`

ONNX weights are not on this branch (GitHub 100 MB limit). Take the SmolVLM2 weights from the 0.1.5 CI DMG (`AutoEditor-Helper-0.1.5-mac-arm64.dmg`, CI run 31658325081 artifact `helper-mac-arm64`). Official `--verify-only` tree must still be `5ab9f376a07e111ed08957c6db3847e4531b55589f6dbfe3fdb35619171bbc21`.

Semantic visual QA stays disabled. Do not empty `FIXTURELESS_CHECKS`.
