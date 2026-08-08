# AutoEditor setup for friends

You install one app, connect your own accounts, and then use the AutoEditor
website. You never install Python, Node, FFmpeg, Whisper models, HyperFrames,
Remotion, GitHub repositories, or command-line tools yourself. They are inside
the AutoEditor Helper installer.

Allow 10 to 20 minutes for the first setup. Normal edits are much simpler:
open the Helper, open the website, choose a video type, upload footage, and
press **Make It**.

Windows is the first acceptance target. The Mac app has the same accounts,
video types, edit controls, local rendering, and QA behavior. Only the
installer steps differ.

## What you need

- A 64-bit Windows 10 or 11 PC, or a Mac running macOS 12 or newer.
- At least 20 GB of free disk space. Sixteen GB of memory is recommended for
  faster speech recognition and rendering.
- Chrome, Edge, or Safari.
- An internet connection for the website, DeepSeek, and any connected stock
  footage accounts.
- Your private invite code from Omar.
- A DeepSeek account and API key. This one is required because DeepSeek plans
  the edit and handles change requests.
- A required Connect-or-Skip choice for Pexels and Pixabay. Connect both for
  the full stock-footage library. If you skip one, AutoEditor clearly disables
  that source and cannot download from it.
- A required Connect-or-Skip choice for ElevenLabs. If you skip the account,
  generated ElevenLabs sound effects are disabled and only bundled effects
  remain.
- No HyperFrames account. HyperFrames renders locally and is already included.
- Usually no Remotion account. Individuals and organizations of up to three
  people can select the free license without signing up. Larger collaborations
  or organizations need a paid Remotion license. Remotion and HyperFrames are
  built-in editing capabilities and are required.

## Windows setup

1. Open the private AutoEditor website Omar sends you.
2. Sign in with your name and invite code.
3. Find **One-time: connect your computer**.
4. Press **Windows PC** to download `AutoEditor-Helper-Windows.exe`.
5. Open your Downloads folder and double-click that file.
6. If Windows asks **Do you want to allow this app to make changes?**, verify
   that the publisher name matches the signed release, then press **Yes**.
7. Let the installer finish. It creates an AutoEditor Helper shortcut in the
   Start menu and on the desktop.
8. Open **AutoEditor Helper**. Do not open PowerShell or Command Prompt. No
   terminal is part of the friend workflow.
9. Return to the website, press **Copy** beside **Your Setup code**, return to
   the Helper, paste it into Step 1, and continue through the account steps
   below.

If Windows SmartScreen says **Windows protected your PC** on a final friend
release, stop and tell Omar. A tagged release is not allowed to publish unless
its Windows signature passes and the signed candidate is physically accepted.
Do not train friends to bypass SmartScreen for a release build.

## Mac setup

1. On the AutoEditor website, choose **Mac, Apple Silicon** for most Macs made
   since late 2020. Choose **Mac, Intel** only for an Intel Mac. To check, open
   Apple menu, **About This Mac**, and read **Chip** or **Processor**.
2. Open the downloaded `.dmg` file.
3. Drag **AutoEditor Helper** into **Applications**.
4. Open Applications and double-click **AutoEditor Helper**.
5. Return to the website, copy **Your Setup code**, paste it into the Helper,
   and continue through the account steps below.

A final friend release is signed with Developer ID and notarized by Apple. If
macOS says the app cannot be checked for malicious software, stop and tell
Omar. Do not use a right-click bypass for the final release.

## Required DeepSeek account

DeepSeek is the only account you cannot skip. Without it, AutoEditor cannot
plan edits or understand supported requests such as “make it vertical” or
“use the commercial edit profile.”

1. Open https://platform.deepseek.com/sign_up.
2. Create an account with an email address and password, then complete any
   verification DeepSeek requests.
3. Sign in at https://platform.deepseek.com.
4. Open **Billing** or **Top up** and add a small balance. Pricing can change,
   so read the current price shown by DeepSeek before paying.
5. Open **API keys**.
6. Press **Create new API key** and name it `AutoEditor`.
7. Copy the key immediately. DeepSeek normally shows a new secret key once.
8. Return to AutoEditor, paste the key into **Step 1: connect DeepSeek**, and
   press **Check & unlock**.
9. AutoEditor checks the key before showing the dashboard. If it is rejected,
   delete the pasted value, create a new key in DeepSeek, and try again.

Never send an API key in a text message or screenshot. The website encrypts the
DeepSeek key. Pexels, Pixabay, ElevenLabs, and Remotion keys are encrypted by Windows
Credential Protection or macOS Keychain inside the Helper.

Treat the one-time Helper Setup code like a password too. Paste it only into
the signed AutoEditor Helper. Do not send it to another friend or paste it into
DeepSeek chat.

## Pexels stock footage

You must choose **Connect Pexels** or **Skip Pexels** during setup. Connect it
for the full editing resource set. If you skip it, no Pexels result can be
searched or downloaded and the Helper shows that source as unavailable.

1. In the Helper, keep **Connect Pexels** selected.
2. Press **Open Pexels signup**.
3. Create a free account with your email, Google, or Apple login.
4. Complete email verification if Pexels requests it.
5. Return to the Helper and press **Open Pexels API**.
6. Choose **Get Started** or **Your API Key**. If asked about the app, describe
   it as personal video editing.
7. Copy the API key and paste it into the Helper.
8. The Helper makes one small video search to verify the key. A rejected key
   does not get saved.

Pexels API limits and content terms apply. A stock clip can still contain a
person, logo, building, or property that needs additional permission for a
particular commercial use. AutoEditor records the source page and contributor
when available, but the person publishing the video remains responsible for
the final use.

## Pixabay stock footage

You must choose **Connect Pixabay** or **Skip Pixabay** during setup. Connect
it for the full editing resource set. If skipped, no Pixabay result can be
searched or downloaded and the Helper shows that source as unavailable.

1. In the Helper, keep **Connect Pixabay** selected.
2. Press **Open Pixabay signup**.
3. Create a free account and complete any email verification.
4. Return to the Helper and press **Open Pixabay API page**.
5. Make sure you are signed in. The page displays your API key beside the
   required `key` field.
6. Copy the key and paste it into the Helper.
7. The Helper makes one small video search to verify the key. A rejected key
   does not get saved.

Pixabay requires API responses to be cached and prohibits systematic mass
downloads. Its content terms and third-party rights still apply to the final
published video.

## ElevenLabs generated sound effects

You must choose **Connect ElevenLabs** or **Skip ElevenLabs** during setup.
Connect it when you want AutoEditor to generate a sound effect for a specific
moment. If you do not want an account, select Skip. Generated ElevenLabs sounds
then stay unavailable, but AutoEditor can still use bundled sound effects.

1. In the Helper, keep **Connect ElevenLabs** selected.
2. Press **Open ElevenLabs signup**.
3. Create a free account and complete any email verification.
4. Return to the Helper and press **Open ElevenLabs API keys**.
5. Press **Create API Key** and name it `AutoEditor`.
6. Turn on restrictions and allow **Sound Effects**. Set a small credit limit
   so the key cannot use more than you expect. Do not add an IP restriction,
   because the Helper runs from your own computer and your IP can change.
7. Create the key and copy it immediately. Paste it into the Helper.
8. The Helper calls ElevenLabs’ user endpoint once to verify the key. A
   rejected key is not saved.

ElevenLabs plans, credits, and prices can change. Read the current plan shown
at https://elevenlabs.io/pricing/api. Generated effects consume your account’s
credits. Do not share the key or paste it into the website help chat.

## HyperFrames and Remotion

HyperFrames is installed and checked automatically. It does not need a local
rendering account. The Helper renders a tiny HyperFrames graphic during setup;
setup fails if the real renderer does not work.

For Remotion, choose the license that applies in the Helper. Remotion is
required because AutoEditor uses it for animated diagrams and visual systems:

- **Free license:** choose this if you are an individual or your organization
  has one to three people. No Remotion account is needed.
- **Paid license:** collaborations and organizations of four or more people
  must follow the Remotion license page, purchase the applicable plan, open the
  Remotion dashboard, copy the public `rm_pub_...` rendering license key, and paste it into
  the Helper.

The current rules and prices are at
https://www.remotion.dev/docs/license/pricing. The Helper runs a real Remotion
test render whenever Remotion is enabled. When a license key is supplied,
Remotion receives a limited usage event containing the key, render event type,
and success or failure. It does not receive the rendered media or its content.

## Finish Helper setup

1. Review the choices on the screen.
2. Press **Check My Setup and Start**.
3. Wait while the Helper verifies connected account keys, checks disk space,
   validates FFmpeg codecs and filters, and renders tiny HyperFrames and
   Remotion samples.
4. A green check means the capability is installed and working. A yellow
   **Skipped** row can appear only for an account-backed source such as Pexels,
   Pixabay, or ElevenLabs. HyperFrames and Remotion must both pass.
5. Leave AutoEditor Helper open while an edit is running. You can close it
   when you are finished for the day.

## Make a video

1. Open AutoEditor Helper and confirm it says **Running**.
2. Open the AutoEditor website.
3. Choose what you are making:
   - **Short / Reel** for vertical TikTok, Instagram Reel, or YouTube Short.
   - **Long Talking Head** for a YouTube lesson, commentary, or presentation.
   - **Commercial / Ad** for an offer-focused product or service promotion.
   - **Podcast / Interview** for a conversation or multi-speaker recording.
   - **Course / Lesson** for structured teaching content.
   - **Custom** when you want to describe a different result.
   Each choice uses its own generic profile. The profiles are Social Short,
   Long Talking Head, Commercial, Podcast, Course, and Custom. They do not use
   another friend’s name or personal creator profile. PSE remains a separate
   owner product.
4. Drop in the footage. The browser uploads it to private AutoEditor cloud
   storage. Your Helper downloads the job and renders it on your computer,
   then uploads the finished MP4 and QA report so the website can show them.
5. Paste the exact script if you have it. This makes transcript and word-safety
   checks stricter.
6. Press **Make It** and leave the Helper running.
7. Wait for transcription, planning, stock or graphic resolution, rendering,
   and final QA.
8. If the result says **Ready**, watch it once and download the MP4.
9. If it says **Needs Review**, do not publish yet. Watch the file, read the
   stated failure, and request a correction.

## Ask DeepSeek for changes

Use normal language in **Ask for changes**. This release can apply five kinds
of change, each tied to a real engine setting:

1. Change edit pacing to **Auto**, **Short**, or **Long**.
2. Change delivery to **Auto**, **9:16**, or **16:9**.
3. Use **Burned captions** or a **Sidecar caption file**.
4. Use **Full visuals** or **Baseline visuals**. Baseline intentionally turns
   off the premium punch-in, b-roll, and graphic layer as one complete mode.
5. Switch among the six generic profiles: Social Short, Long Talking Head,
   Commercial, Podcast, Course, and Custom.

Examples that work are “make it 9:16,” “use long pacing,” “give me sidecar
captions,” “use baseline visuals,” and “switch to the podcast profile.”

This release rejects requests that do not have an exact engine control. It
cannot remove a spoken segment, rewrite which words survive, target a new
duration, split one upload into several clips, choose one specific stock shot,
resize captions, apply a separate cinematic grade, or tune only the punch-ins
or b-roll density. DeepSeek must say it cannot apply that request. It must not
rerender the same edit and claim the change happened.

Every accepted change reruns the speech-protection and QA gates. DeepSeek
cannot bypass them.

## Storage and privacy

- Rendering happens on the friend’s Windows PC or Mac.
- The browser copy of uploaded footage, finished outputs, and QA files lives in
  private Cloudflare R2 storage so the website and Helper can exchange it.
- The Helper also creates temporary local work files and provider caches while
  editing. Cloud storage is still required for the website workflow. A local
  render does not mean the only copy stays on the computer.
- Press **Delete Project and Cloud Files** to remove that project’s uploads,
  outputs, and QA files from AutoEditor storage. Deletion waits if an edit is
  currently running.
- DeepSeek receives the text and planning context required for editing.
- Pexels and Pixabay receive stock search terms only when connected.
- ElevenLabs receives sound-effect prompts only when connected and when the
  edit actually requests a generated effect.
- Remotion receives limited license telemetry when its license key is used. It
  does not receive the video, video metadata, or user content through that
  telemetry event.
- Stock files are cached locally to respect provider limits.

Do not upload confidential client footage until Omar has confirmed the current
privacy policy, retention policy, and provider agreements match that job.
There is no documented automatic deletion period yet. Delete finished test
projects yourself until Omar publishes one.

## Change accounts, update, reinstall, or uninstall

AutoEditor Helper does not update itself. Omar will tell you when a newer signed
version has passed testing. Never install a Helper update from a link sent by
someone else.

To update or reinstall on Windows:

1. Wait for any running edit to finish, then close AutoEditor Helper.
2. Sign in to the private AutoEditor website and download the current **Windows
   PC** installer.
3. Open the downloaded `.exe`, verify the expected publisher, and let it replace
   the existing app.
4. Reopen AutoEditor Helper. Your encrypted setup normally remains in place.

To update or reinstall on Mac:

1. Wait for any running edit to finish, then quit AutoEditor Helper.
2. Download the current DMG for the correct Mac chip from the private website.
3. Open the DMG and drag AutoEditor Helper into Applications. Choose **Replace**
   when macOS asks.
4. Reopen the app. Your encrypted setup normally remains in place.

To change the Helper Setup code or locally saved Pexels, Pixabay, ElevenLabs,
or Remotion choice, open the Helper and press **Change Accounts or Setup**. This
stops the Helper and removes its encrypted setup file, then takes you through
setup again. It does not delete website projects or remove the DeepSeek key from
your AutoEditor website account. Revoke an old provider key on that provider’s
website if you no longer want it to work.

To remove AutoEditor completely:

1. Delete any website projects and cloud files you no longer want. Uninstalling
   the Helper does not delete cloud projects.
2. In the Helper, press **Change Accounts or Setup** to remove the encrypted
   local setup, then close the app.
3. On Windows, open **Settings**, **Apps**, **Installed apps**, find
   **AutoEditor Helper**, open its menu, and press **Uninstall**.
4. On Mac, quit AutoEditor Helper, open Applications, and move it to the Trash.
5. The uninstaller intentionally leaves local work and cache files in case you
   reinstall. For a full local cleanup, open the Run box on Windows and remove
   `%APPDATA%\AutoEditor Helper`, or on Mac use Finder, **Go**, **Go to Folder**,
   and move `~/Library/Application Support/AutoEditor Helper` to the Trash.
   Do this only after every edit is finished and anything you need is downloaded.

## If something fails

- **DeepSeek key rejected:** check billing, create a new key, and paste it
  again. Do not add spaces before or after it.
- **Pexels, Pixabay, or ElevenLabs key rejected:** return to that service while signed in,
  copy the API key again, and retry. You can select Skip and continue without
  that provider.
- **Built-in component is red:** make sure at least 20 GB is free, restart the
  computer, reopen the Helper, and retry.
- **HyperFrames or Remotion test failed:** restart the Helper once. If it fails
  again, open **Activity**, copy the error text without any keys, and send it
  to Omar.
- **Helper stopped:** press **Start Helper**. If it stops again, copy the
  Activity text.
- **Website says waiting in queue:** confirm the Helper is open and says
  Running.
- **Edit says Needs Review:** this is a safety stop, not a finished result.
  Watch it and request a change.
- **Installer warning on a final release:** stop and tell Omar. Final releases
  must have a valid Windows signature or Apple notarization.
