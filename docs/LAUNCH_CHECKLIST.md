# Ryan Reels Editor: Omar's launch checklist

What exists after the friend-ready build (branch `friend-ready-app`):

- Creator profile system in the engine (`profiles/`, `--profile`,
  `$AUTOEDITOR_PROFILE`), with pse / ryan_duffy / ryan_humes / shared_skit
  packages. Ryan profiles force the short-form pipeline and pass distinct
  skit/list direction into both DeepSeek planning rounds. Comment-safe yaml
  parsing (quoted `#RRGGBB` colours now work,
  a latent bug that silently ate accent colours).
- Desktop app (`desktop/`): one-screen flow, DeepSeek key via OS keystore
  (safeStorage: Keychain on Mac, DPAPI vault on Windows), multi-clip join,
  transcript review step (`--transcribe-only`), progress from engine JSON
  events, QA-gated result with an explicit Needs Review state, auto-update
  per product, platform, and architecture channel.
- CI (`.github/workflows/release.yml`): tag `ryan-v0.1.0` or `pse-v0.1.0`
  (or run manually) -> native Apple Silicon DMG, Intel Mac DMG, and Windows
  installer with the frozen engine,
  bundled ffmpeg, per-product profiles, and Montserrat font. Unsigned
  builds work today; signing activates automatically when secrets exist.
- Safety and desktop contract suites: 73 Python safety tests plus Windows/Mac
  packaging checks, clip-catalog checks, and process-tree cancellation checks.
- Measurement toolkit (`scripts/profile_measure.py`): finished reels in,
  profile draft + report out.

## To ship the first build

1. Push the branch, open a PR, merge to main.
2. Tag: `git tag ryan-v0.1.0 && git push --tags`.
3. Download every installer from the GitHub release. Validate the Windows
   installer on Windows first, including install, launch, transcription, one
   complete edit, Needs Review behavior, update check, and uninstall. Then
   validate Apple Silicon on Apple Silicon and Intel on Intel. Run one real
   edit per profile before sharing.
4. Send the release link + docs/FRIEND_SETUP.md text to the Ryans.

## To remove install friction (whenever, not blocking)

- Apple Developer account ($99/yr) -> repo secrets CSC_LINK,
  CSC_KEY_PASSWORD, APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID.
  Until then: Mac users right-click the app -> Open on first launch.
- Windows code-signing cert -> WIN_CSC_LINK, WIN_CSC_KEY_PASSWORD.
  Until then: SmartScreen shows "More info -> Run anyway" once.

## To approve the Ryan reference drafts

1. Get from each Ryan: 15-25 finished exports, 5+ raw-to-final pairs,
   fonts/overlays/logos they actually use, preferred export settings.
2. Run: `python scripts/profile_measure.py <their_reels>/ --name ryan_duffy`
3. Merge `profile_draft.yaml` numbers into their `profile.yaml`, drop their
   fonts into `profiles/<id>/assets/fonts/`.
4. Run held-out raw clips, compare side by side, and get each Ryan's approval
   before changing `status` from `reference-draft` to `approved`.

## Asset licensing reminders

- Bundled font is Montserrat (OFL: redistribution allowed).
- Do NOT bundle SFX/music/b-roll unless the license explicitly allows
  redistribution in software (most royalty-free licenses do not). Friends'
  b-roll goes in via the Extras button; Pexels/Pixabay keys stay optional.
- Trending IG audio: added inside Instagram after export, never bundled.

## Known limits of v0.1

- Remotion graphics templates are not bundled; the engine's Pillow-based
  graphics run everywhere. Revisit if the Ryans want the animated
  stat/steps/flow cards.
- No hardware acceleration tuning on Windows yet (x264 CPU encode).
- Engine progress is parsed from phase logs; granular percent within long
  phases (transcribe/render) is approximate.
