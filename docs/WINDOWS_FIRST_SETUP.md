# Windows-First Notes

Friends on Windows 11 need only Chrome or Edge; everything runs server
side. There is nothing to install: no Python, FFmpeg, models, or repos.

## What was verified where (honest ledger, 2026-08-07)

- Full-stack end-to-end (invite -> sign-in -> key -> multipart upload of
  real footage -> Make It -> engine render -> QA gates -> authenticated
  download -> cross-account isolation -> key-leak sweep): PASS, executed
  against `wrangler dev --local` plus the real Python engine in a Linux
  environment, driven over HTTP exactly as a browser would be.
- Vertical Short sample: PASS (25s real-narration fixture; engine cut it
  to 22.6s, speech/sync/loudness/word-integrity gates passed; delivery
  correctly quarantined as Needs Review because the synthetic fixture has
  blank frames and the render host lacked the brand font: both gates
  behaving as designed).
- Long talking-head sample (16:9): run started during acceptance; result
  recorded in the handoff report.
- Commercial-style sample: NOT RUN yet (synthetic fixture allowed; run it
  after deploy with the same script as the Short).
- Real Windows 11 + Chrome/Edge browser acceptance: NOT RUN. It requires
  the deployed preview URL (wrangler deploy needs Omar's Cloudflare
  login). The client code sticks to boring, universally supported APIs
  (fetch, FormData-free multipart PUTs, <video>, drag-and-drop) precisely
  to minimize Windows-browser risk, but per the release gate this does
  NOT count as Windows-ready.
- Live DeepSeek revision round-trip: exercised with a fake key to verify
  the graceful-failure path (planner unavailable -> chat explains, no
  broken revision); the real-key path needs one run after deploy.

## Windows acceptance script (run after deploy)

On a Windows 11 machine with Chrome and Edge:

1. Redeem a fresh invite; sign in on Chrome.
2. Add a real DeepSeek key; confirm it never appears in DevTools network
   responses, page source, or localStorage (it is posted once and never
   echoed).
3. Upload a real phone clip (>100MB ideally) and watch the resume
   behavior by toggling airplane mode mid-upload.
4. Make It; verify the state progression through queued -> transcribing
   -> planning -> rendering preview -> quality checks -> ready or needs
   review.
5. Ask for "bigger captions" (auto-applies) and "remove the part where I
   say X" (must show a proposal and wait for OK).
6. Download the MP4; play it in Windows Media Player.
7. Sign out; confirm the project URL now returns the sign-in screen; sign
   in as a second user and confirm the first user's project is not
   listed and its media URL returns 403.
8. Repeat sign-in on Edge to confirm parity.
