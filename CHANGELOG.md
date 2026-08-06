## v2.2.0-dev (friend-ready desktop build)

- Creator profile packages (`profiles/`, `--profile`): pse, ryan_duffy,
  ryan_humes, shared_skit. Global brand.yaml stays as legacy fallback.
- Desktop app (`desktop/`): Ryan Reels Editor / PSE AutoEditor from one
  codebase; OS-keystore key storage; transcript review; QA-gated delivery
  with explicit Needs Review; auto-update channels.
- `--transcribe-only`, JSON progress events (`AUTOEDITOR_PROGRESS_JSON`),
  `AUTOEDITOR_FFMPEG`/`AUTOEDITOR_FFPROBE`/`AUTOEDITOR_PROFILES_DIR`/
  `AUTOEDITOR_PACKAGED` for packaged builds; Windows font discovery.
- Fixed: quoted "#RRGGBB" values in yaml configs were parsed as comments.
- `scripts/profile_measure.py`: measure a creator's style from finished
  reels into a profile draft.
- CI: `release.yml` builds Mac/Windows installers per product tag.

# Changelog

## 2.0.0 - 2026-07-28

Version 2 changes the editor's trust boundary. DeepSeek V4 Pro plans the edit,
while deterministic code owns transcript grounding, timing, rendering, and
release. Finished videos stay quarantined until the artifact gates pass.

The source-sync gate now compares the finished native-canvas master with the
RAW recording. A human-certified offset sidecar is the only accepted source
for a nonzero correction. The old automatic A/V estimator no longer makes
production decisions.

Cut boundaries now use integer frame indices and matching 1,600-sample audio
indices at 30 fps and 48 kHz. Delivery derivatives are checked against the
gated native master in both image and decoded audio.

The DeepSeek path now requires V4 Pro, JSON mode, maximum reasoning, a complete
transcript, exact spoken anchors, a score of 100, and a successful critic
receipt. Failed calls and invalid plans stop the render.

Provider responses now have a true wall-clock deadline. A server cannot keep a
request alive indefinitely by sending small chunks. The tracked V4 smoke tool
runs in a separate worker so its total deadline can stop the whole planning
loop.

The release adds mechanical checks for fabricated visual copy, missing
scripted sentences, stale or corrupt visual assets, incomplete semantic
judgments, retake residue, caption damage, and watch-copy substitution.

See [the full v2 release notes](docs/RELEASE_V2.md) and
[the worked regression proofs](docs/examples/V2_REGRESSION_PROOFS.md).

## 1.0.0 - 2026-07-28

The first public version added transcript-driven cutting, retake removal,
creative overlays, captions, audio finishing, and finished-file verification.
Its release notes and original demo remain available on the
[v1.0.0 release page](https://github.com/CEOmarabha/talking-head-autoeditor/releases/tag/v1.0.0).
