# AutoEditor Helper launch checklist

No friend release is approved from source tests alone. Acceptance is against
the exact Windows `.exe` and Mac `.dmg` files friends will download.

## One-time release credentials

- Recommended Windows route, Microsoft Azure Artifact Signing:
  `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
  `WIN_AZURE_PUBLISHER_NAME`, `WIN_AZURE_ENDPOINT`,
  `WIN_AZURE_CERTIFICATE_PROFILE_NAME`, and
  `WIN_AZURE_CODE_SIGNING_ACCOUNT_NAME`, plus the durable
  `WIN_AZURE_SUBSCRIBER_IDENTITY_EKU` OID.
- Windows fallback: `WIN_CSC_LINK`, `WIN_CSC_KEY_PASSWORD`, and
  `WIN_PFX_CERT_THUMBPRINT` for an exportable code-signing PFX.
- `CSC_LINK`: Apple Developer ID Application certificate for electron-builder.
- `CSC_KEY_PASSWORD`: certificate password.
- `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`: notarization.
- `R2_CANDIDATE_ACCESS_KEY_ID`, `R2_CANDIDATE_SECRET_ACCESS_KEY`, and
  `CLOUDFLARE_ACCOUNT_ID`: let tagged signing jobs write only to the expiring
  candidate bucket.
- `R2_RELEASE_ACCESS_KEY_ID`, `R2_RELEASE_SECRET_ACCESS_KEY`, and
  `CLOUDFLARE_ACCOUNT_ID`: put these only in the protected
  `helper-live-release` GitHub environment. That environment is used by the
  separate manual promotion workflow and never receives signing credentials.
- `CLOUDFLARE_R2_LOCKS_READ_TOKEN`: a separate Cloudflare bearer token in
  `helper-live-release`, scoped only to the account permission
  `Workers R2 Storage Read`. Promotion uses it only with Cloudflare's official
  bucket-lock GET API. Do not reuse either R2 Secret Access Key as this token.
- Indefinite R2 bucket locks on `dist/helper/objects/` and
  `dist/helper/checksums/` in `autoeditor-releases`. Keep only
  `dist/helper/current.json` mutable.

As last verified on August 7, 2026, GitHub had none of these secrets configured.
A signed-candidate build remains blocked until they exist. Manual workflow runs
may create unsigned acceptance artifacts, but those files are never friend
releases. Follow `OWNER_SIGNING_SETUP.md` once. Friends never perform signing
setup.

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
5. Bundle exactly the six friend profiles (`generic_short`, `generic_long`,
   `generic_commercial`, `generic_podcast`, `generic_course`, and
   `generic_custom`), Work Sans, Montserrat, and the CA certificate bundle.
   Keep PSE in its separate product channel. Do not ship named personal
   profiles in the generic Helper.
6. Bundle Node 22.23.2, HyperFrames 0.7.99, Remotion 4.0.507, GSAP 3.15.0,
   React 19.0.0, the fixed visualization templates, and Chrome Headless Shell
   152.0.7928.2.
7. Run a real HyperFrames check and MP4 render.
8. Run a real Remotion MP4 render with the bundled browser.
9. Write `runtime-manifest.json` with component file counts, sizes, and hashes.
10. Build the installer, install or mount it, and run the packaged Helper smoke
    test from its installed resource paths. Windows must produce exactly one
    signed web-bootstrap EXE and one required `.nsis.7z` runtime package smaller
    than 4,294,967,295 bytes. Every adjacent, explicit, or downloaded package
    path must verify the EXE's embedded SHA-512 before extraction.
11. Verify Authenticode for tagged Windows releases.
12. Verify codesign, Gatekeeper assessment, notarization, and stapled tickets
    for tagged Mac releases.
13. Verify the installed or freshly mounted resources against every component
    receipt in `runtime-manifest.json`.
14. Multipart-upload each signed installer, plus the Windows runtime package,
    to content-addressed R2 candidate keys. Upload the same signed files and
    receipts as seven-day GitHub Actions artifacts for physical acceptance.
15. Stop. A successful tagged build must not publish a GitHub release, copy an
    object to the live bucket, or write `dist/helper/current.json`.

After physical acceptance, the separate `Promote accepted AutoEditor Helper
release` workflow must:

16. Require Omar to enter the accepted tag, 40-character commit, and signed
    build run ID, then check the explicit physical-acceptance box.
17. Prove that run was a successful tag-push execution of
    `helper-release.yml`, resolve the tag to the same commit, recover the exact
    run attempt, and download exactly the three receipt artifacts from that run.
18. Before any release mutation, fetch the exact public
    `/download/helper/runtime/contract` route and require the Helper runtime and
    release v2 schemas. Then GET the official Cloudflare lock endpoint and
    require exactly two enabled `Indefinite` rules for
    `dist/helper/objects/` and `dist/helper/checksums/`.
19. Require all receipts to bind the same tag, commit, run ID, and run attempt.
    Stream-hash all four candidate objects, three installers plus the Windows
    runtime package, before and after their content-addressed copies into the
    live bucket.
20. Publish and reread the metadata-only GitHub release, then expose all three
    platforms together by conditionally writing `dist/helper/current.json`
    last. A rerun may succeed only when the existing release has the same
    provenance and installer receipts.
21. Confirm the live object and checksum prefixes are protected by Cloudflare
    R2 bucket locks, so a later token mistake cannot overwrite referenced
    installer bytes.

The release locks are `packaging/requirements-windows-x64.txt`,
`packaging/requirements-mac-arm64.txt`, and
`packaging/requirements-mac-x64.txt`. The current Windows FFmpeg archive is
bound to its audited SHA-256. Each Mac architecture has a committed exact
formula version, runner bottle tag, bottle rebuild, and bottle SHA-256
inventory. The build also pins the audited Homebrew release, refetches and
reinstalls those bottles, derives the recursive linked-library closure, and
stops if the package manager, closure, or any bottle bytes change. A dependency
change is a review and repin event, not an automatic release update.

## Website and local Helper gates

Before production deployment:

1. Run `npm ci`, `npm audit --audit-level=high`, and `npx wrangler deploy
   --dry-run` from `webapp/worker`.
2. Apply the ordered D1 migrations to a clean local database and run the
   Worker locally.
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
9. Back up production D1, check for duplicate user names and revision numbers,
   apply `npx wrangler d1 migrations apply autoeditor-web --remote`, verify the
   lease columns, render upload table, and unique indexes, then deploy only with
   owner approval.
10. Confirm the browser offers exactly Short, long talking head, Commercial,
    Podcast, Course, and Custom. Confirm the Worker and daemon share the exact
    five-operation allowlist and the claimed revision job contains the
    server-stored approved proposal.

The local two-user, ownership, output-path, upload-resume, and rate-limit tests
passed on August 7, 2026. Production deployment and live two-user acceptance
remain separate gates.

Because the current encoder requires libx264, the bundled FFmpeg is GPL. Before
any third-party handoff, confirm a GPL-compliant corresponding-source delivery
method for the exact Windows and Mac builds. For installer downloads, provide
equivalent source access alongside the installer.
This review must cover the top-level FFmpeg tools and linked libraries plus the
native media copies inside PyAV, Electron or Chromium, and the Remotion
compositor. License texts, formula receipts, and build configuration are
required provenance, but they do not replace exact corresponding source.

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
- Remotion is required. Each friend must explicitly confirm free-license
  eligibility or enter a paid public license key. HyperFrames is also required
  and local. Neither capability can be marked skipped.
- Provider secrets are encrypted by the OS keystore and must never appear in
  logs, receipts, runtime manifests, API responses, or crash messages.

## Physical acceptance before sending links

Use only the `signed-candidate-helper-*` artifacts from one successful tagged
build run. Record its tag, full commit SHA, run ID, run attempt, and the three
receipt SHA-256 values in the acceptance record. Do not test an unsigned build
and then promote different signed bytes.

1. Follow every step in `WINDOWS_FIRST_SETUP.md` on a clean Windows 11 PC.
2. Install the Apple Silicon DMG from the same run on a clean supported Mac and
   repeat the setup,
   six-type render, five-operation revision, download, deletion, quit, reopen,
   and uninstall flow. A Windows pass does not imply Mac parity.
3. Install the Intel DMG from that run on real Intel hardware or record the gate
   as untested. An untested Intel candidate cannot be promoted.
4. Run real Short, long talking-head, Commercial, Podcast, Course, and Custom
   edits before claiming those modes are accepted. Confirm long-to-clips is not
   offered.
5. Connect real Pexels, Pixabay, and ElevenLabs accounts once, then separately
   exercise every Skip choice.
6. Watch every output from beginning to end. Inspect captions, speech cuts,
   source sync, stock relevance, graphics, Remotion diagrams, loudness, and the
   final QA receipt.
7. Exercise all five exact DeepSeek changes: edit style, aspect ratio, caption
   mode, full or baseline visuals, and generic profile. Ask it to remove speech,
   retarget duration, and split the source into clips. Each unsupported request
   must be rejected before a render job exists.
8. Delete a project and confirm its R2 objects and database records are gone.

## Signed candidate and release sequence

After the branch is pushed and the signing plus candidate-bucket secrets are
configured, create a tag to build signed candidates. This tag does not publish
them to friends:

```bash
git tag helper-v0.1.0
git push origin helper-v0.1.0
```

1. Open the successful **Build AutoEditor Helper installers** run for that tag.
2. Record its run ID, run attempt, and full commit SHA.
3. Download all three `signed-candidate-helper-*` artifacts. Extract each ZIP
   and verify its installer against the included candidate receipt.
4. Complete every physical acceptance step above against those exact files.
5. Open **Actions**, choose **Promote accepted AutoEditor Helper release**, and
   press **Run workflow**.
6. Enter the exact tag, signed build run ID, and full commit SHA. Check the
   physical-acceptance box only when the acceptance record is complete.
7. After the promotion succeeds, sign in to the private website and verify all
   three download buttons resolve through the new `current.json` receipt.

Never send friends an unsigned artifact or a signed candidate directly. Do not
run promotion for a build that has not passed physical acceptance on all three
platforms.
