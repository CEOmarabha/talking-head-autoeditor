# AutoEditor Helper launch checklist

No friend release is approved from source tests alone. Acceptance is against
the exact Windows `.exe` and Mac `.dmg` files friends will download.

## One-time release credentials

- Recommended Windows route, Microsoft Azure Artifact Signing:
  `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
  `WIN_AZURE_PUBLISHER_NAME`, `WIN_AZURE_ENDPOINT`,
  `WIN_AZURE_CERTIFICATE_PROFILE_NAME`, and
  `WIN_AZURE_CODE_SIGNING_ACCOUNT_NAME`.
- Windows fallback: `WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD` for an
  exportable code-signing PFX.
- `CSC_LINK`: Apple Developer ID Application certificate for electron-builder.
- `CSC_KEY_PASSWORD`: certificate password.
- `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`: notarization.
- `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`: upload the approved
  installers to the private website’s R2 bucket.

GitHub currently has none of these repository secrets configured. A tagged
release must remain blocked until they exist. Manual workflow runs may create
unsigned acceptance artifacts, but those files are never friend releases.
Follow `OWNER_SIGNING_SETUP.md` once. Friends never perform signing setup.

## Automated gates

The `Build AutoEditor Helper installers` workflow must pass on:

- Windows x64 on `windows-2022`.
- Mac Apple Silicon on `macos-15`.
- Mac Intel on `macos-15-intel`.

Each platform must:

1. Install the exact Python 3.12 lock for that operating system and CPU with
   `--require-hashes`, run `pip check`, then run the Python safety suite.
2. Freeze the editing engine and website render daemon with PyInstaller on the
   target operating system.
3. Bundle FFmpeg and FFprobe, then verify libx264, AAC, and every required
   filter.
4. Bundle the pinned small and medium faster-whisper models and force offline
   model loading.
5. Bundle all approved creator profiles, Work Sans, Montserrat, and the CA
   certificate bundle.
6. Bundle Node 22.23.2, HyperFrames 0.7.99, Remotion 4.0.507, GSAP 3.15.0,
   React 19.0.0, the fixed visualization templates, and Chrome Headless Shell
   152.0.7928.2.
7. Run a real HyperFrames check and MP4 render.
8. Run a real Remotion MP4 render with the bundled browser.
9. Write `runtime-manifest.json` with component file counts, sizes, and hashes.
10. Build the installer, install or mount it, and run the packaged Helper smoke
    test from its installed resource paths.
11. Verify Authenticode for tagged Windows releases.
12. Verify codesign, Gatekeeper assessment, notarization, and stapled tickets
    for tagged Mac releases.
13. Upload artifacts only after all three jobs pass.
14. Publish to both the GitHub release and private R2 download paths.

The release locks are `packaging/requirements-windows-x64.txt`,
`packaging/requirements-mac-arm64.txt`, and
`packaging/requirements-mac-x64.txt`. The current Windows FFmpeg archive is
bound to its audited SHA-256. The Mac job stops if Homebrew moves away from
the audited FFmpeg 8.1.2 formula version. A dependency change is a review and
repin event, not an automatic release update.

## Website and local Helper gates

Before production deployment:

1. Run `npm ci`, `npm audit --audit-level=high`, and `npx wrangler deploy
   --dry-run` from `webapp/worker`.
2. Apply `schema.sql` to a clean local D1 database and run the Worker locally.
3. Create two test users. Prove a personal Helper token cannot claim, update,
   complete, read, or write the other user’s job or media.
4. Prove a queued job is claimed once, only an allowlisted progress status is
   accepted, and an output path outside the claimed user and project is
   rejected.
5. Upload at least two parts, interrupt, select the same file again, confirm
   the saved parts are reused, and complete the object.
6. Confirm the project response gives the browser its applied output path and
   that the authenticated player can stream and download the MP4.
7. Confirm 15 sign-in attempts in ten minutes trigger HTTP 429, dynamic project
   and proposal text is never inserted as HTML, and the site returns its CSP
   and privacy headers.
8. Confirm installer availability and downloads return HTTP 401 while signed
   out, support byte ranges while signed in, and the legacy unsigned ZIP route
   does not exist.
9. Back up production D1, apply the idempotent `schema.sql` remotely, verify the
   `rate_limits` table, then deploy only with owner approval.

The local two-user, ownership, output-path, upload-resume, and rate-limit tests
passed on August 7, 2026. Production deployment and live two-user acceptance
remain separate gates.

Because the current encoder requires libx264, the bundled FFmpeg is GPL. Before
distribution beyond private acceptance testers, confirm the corresponding
source delivery or written-offer process for the exact Windows and Mac builds.
License notices alone are not treated as a complete GPL distribution gate.

The owner approved proceeding with each friend’s own local free-license
eligibility on August 7, 2026. Recheck Remotion’s terms before any public,
paid, company-wide, or hosted rendering launch because that is a different
distribution and licensing scope.

## Friend account behavior

- DeepSeek is required and is checked before the dashboard unlocks.
- Pexels can be connected and live-tested, or explicitly skipped.
- Pixabay can be connected and live-tested, or explicitly skipped.
- ElevenLabs can be connected and live-tested, or explicitly skipped. If
  skipped, generated ElevenLabs sound effects must be shown as unavailable.
- HyperFrames is always local and always required.
- Remotion requires one explicit choice: free-license eligibility, paid key, or
  skip. A skipped capability must be shown as skipped, never as ready.
- Provider secrets are encrypted by the OS keystore and must never appear in
  logs, receipts, runtime manifests, API responses, or crash messages.

## Physical acceptance before sending links

1. Follow every step in `WINDOWS_FIRST_SETUP.md` on a clean Windows 11 PC.
2. Install the Apple Silicon DMG on a clean supported Mac and repeat the setup,
   render, revision, download, deletion, quit, reopen, and uninstall flow.
3. Install the Intel DMG on real Intel hardware or record the gate as untested.
4. Run real Short, long talking-head, and commercial edits. Add podcast, course,
   long-to-clips, and custom samples before claiming those modes are fully
   accepted.
5. Connect real Pexels, Pixabay, and ElevenLabs accounts once, then separately
   exercise every Skip choice.
6. Watch every output from beginning to end. Inspect captions, speech cuts,
   source sync, stock relevance, graphics, Remotion diagrams, loudness, and the
   final QA receipt.
7. Ask DeepSeek for at least one safe visual change and one speech-affecting
   change that must wait for approval.
8. Delete a project and confirm its R2 objects and database records are gone.

## Release command

After credentials and physical acceptance are ready:

```bash
git tag helper-v0.1.0
git push origin helper-v0.1.0
```

Do not create the tag until the branch is pushed and the GitHub repository
secrets are configured. Do not send friends a manual unsigned artifact.
