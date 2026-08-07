# AutoEditor setup for friends

You install one app, connect your own accounts, and then use the AutoEditor
website. You never install Python, Node, FFmpeg, Whisper models, HyperFrames,
Remotion, GitHub repositories, or command-line tools yourself. They are inside
the AutoEditor Helper installer.

Allow 10 to 20 minutes for the first setup. Normal edits are much simpler:
open the Helper, open the website, choose a video type, upload footage, and
press **Make It**.

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
- Pexels and Pixabay accounts only if you want stock footage from those
  services. The Helper lets you skip either one.
- An ElevenLabs account only if you want generated sound effects. The Helper
  lets you skip it and keep using AutoEditor’s built-in sound effects.
- No HyperFrames account. HyperFrames renders locally and is already included.
- Usually no Remotion account. Individuals and organizations of up to three
  people can select the free license without signing up. Larger collaborations
  or organizations need a paid Remotion license, or they can skip Remotion
  diagrams.

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
its Windows signature passes. Do not train friends to bypass SmartScreen for a
release build.

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
plan edits or understand requests such as “make the opening faster.”

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

Pexels is not required. Connect it for automatic Pexels video clips, or select
**Skip Pexels**. If you skip it, no Pexels results will be searched or
downloaded.

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

Pixabay is not required. Connect it for a second stock source, or select
**Skip Pixabay**. If skipped, no Pixabay result will be searched or downloaded.

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

ElevenLabs is not required. Connect it when you want AutoEditor to generate a
sound effect for a specific moment. Select **Skip ElevenLabs** if you do not
want to create an account. If skipped, generated ElevenLabs sounds are
unavailable, but AutoEditor can still use its bundled sound effects.

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

For Remotion, choose one option in the Helper:

- **Free license:** choose this if you are an individual or your organization
  has one to three people. No Remotion account is needed.
- **Paid license:** collaborations and organizations of four or more people
  must follow the Remotion license page, purchase the applicable plan, open the
  Remotion dashboard, copy the public `rm_pub_...` rendering license key, and paste it into
  the Helper.
- **Skip Remotion:** Remotion diagrams are unavailable, but HyperFrames and all
  other connected sources remain available.

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
   **Skipped** row means you deliberately chose not to connect that source.
5. Leave AutoEditor Helper open while an edit is running. You can close it
   when you are finished for the day.

## Make a video

1. Open AutoEditor Helper and confirm it says **Running**.
2. Open the AutoEditor website.
3. Choose what you are making:
   - **Short / Reel** for vertical TikTok, Instagram Reel, or YouTube Short.
   - **Long Talking Head** for a YouTube lesson, commentary, or presentation.
   - **Commercial / Ad** for a short product or service promotion.
   - **Podcast / Interview** for a conversation or multi-speaker recording.
   - **Course / Lesson** for structured teaching content.
   - **Turn Long Video Into Clips** to select short moments from a longer file.
   - **Custom** when you want to describe a different result.
4. Drop in the footage. Files upload to private AutoEditor cloud storage so
   the website and your local Helper can exchange them. The actual render runs
   on your computer.
5. Paste the exact script if you have it. This makes transcript and word-safety
   checks stricter.
6. Press **Make It** and leave the Helper running.
7. Wait for transcription, planning, stock or graphic resolution, rendering,
   and final QA.
8. If the result says **Ready**, watch it once and download the MP4.
9. If it says **Needs Review**, do not publish yet. Watch the file, read the
   stated failure, and request a correction.

## Ask DeepSeek for changes

Use normal language in **Ask for changes**. Examples:

- “Make the first ten seconds faster.”
- “Use fewer punch-ins.”
- “Make the captions larger.”
- “Replace the stock clip at 18 seconds with something about construction.”
- “Remove the part where I repeat the pricing.”
- “Turn this into three separate Shorts.”

AutoEditor converts the request into a typed edit proposal. A change that can
affect spoken words or remove content must show what will happen and wait for
approval. DeepSeek cannot bypass transcript locks or QA checks.

## Storage and privacy

- Rendering happens on the friend’s Windows PC or Mac.
- Uploaded footage and finished outputs also live in private Cloudflare R2
  storage so the website can hand work to the Helper and return the result.
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
