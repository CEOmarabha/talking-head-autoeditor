# Owner-only signing setup

Friends never do anything in this file. They receive one normal Windows `.exe`
or Mac `.dmg`. Signing is a one-time owner setup in Microsoft, Apple, and
GitHub so their computers can verify the installer came from Omar and was not
changed after it was built.

## Windows, recommended: Azure Artifact Signing

Microsoft renamed Trusted Signing to Azure Artifact Signing. This route avoids
buying, exporting, and protecting a local USB or PFX certificate. Microsoft
currently lists the Basic plan at about USD $9.99 per month for 5,000 signatures.
Check the current price and identity-eligibility list before opening the account.

1. Open the [Azure portal](https://portal.azure.com/) and sign in with the
   Microsoft account that will own the product.
2. Create or select a paid Azure subscription. A free-only Azure subscription
   is not accepted for Artifact Signing.
3. Search the portal for **Artifact Signing**. Some portal pages and older
   documentation still say **Trusted Signing**.
4. Create an Artifact Signing account in an available region. Record the exact
   account name and the endpoint shown by Azure.
5. Open **Identity validations**, choose **New identity**, and complete the
   public identity validation. Enter the legal person or organization that
   should appear as the Windows publisher. Microsoft may request identity or
   business records. Approval is controlled by Microsoft and cannot be
   automated by this repository.
6. After validation succeeds, open **Certificate profiles**, choose **Create**,
   select **Public Trust**, and create the profile. Record its exact name.
7. Copy the certificate subject or publisher name exactly as Azure displays it.
   Capitalization, punctuation, and spacing must match.
8. In Microsoft Entra ID, open **App registrations**, select **New
   registration**, and create a private CI application such as
   `autoeditor-github-signing`.
9. Copy its **Application (client) ID** and **Directory (tenant) ID**.
10. Open **Certificates & secrets**, choose **New client secret**, set a short
    practical expiration, and copy the secret value immediately. Azure shows
    the value only once. Put the rotation date on the owner calendar.
11. Return to the Artifact Signing account or certificate profile, open
    **Access control (IAM)**, and assign the CI application the **Artifact
    Signing Certificate Profile Signer** role. Keep identity-validation roles
    on the owner account, not the CI application.
12. In GitHub, open the repository, then **Settings**, **Secrets and
    variables**, **Actions**, **New repository secret**. Add all seven secrets:

    - `AZURE_TENANT_ID`: Directory tenant ID from step 9.
    - `AZURE_CLIENT_ID`: Application client ID from step 9.
    - `AZURE_CLIENT_SECRET`: client secret value from step 10.
    - `WIN_AZURE_PUBLISHER_NAME`: exact certificate publisher from step 7.
    - `WIN_AZURE_ENDPOINT`: exact account endpoint from step 4.
    - `WIN_AZURE_CERTIFICATE_PROFILE_NAME`: exact profile name from step 6.
    - `WIN_AZURE_CODE_SIGNING_ACCOUNT_NAME`: exact account name from step 4.

13. Run the Helper workflow manually first. A manual build is an acceptance
    build and is not published to friends.
14. After the clean-PC tests pass, create a `helper-v*` tag. The tagged workflow
    selects Azure signing, verifies Authenticode on both the installer and the
    installed app, and stops before publishing if either signature is invalid.

Microsoft setup references:

- [Artifact Signing overview and pricing](https://learn.microsoft.com/en-us/azure/artifact-signing/overview)
- [Create Artifact Signing resources](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)
- [Roles used by Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/tutorial-assign-roles)
- [Electron Builder Azure signing options](https://www.electron.build/code-signing-win.html#using-azure-trusted-signing)

## Windows fallback: an exportable PFX

Use this only if Azure Artifact Signing is unavailable for the owner’s country
or identity type.

1. Buy a public code-signing certificate from a certificate authority accepted
   by current Windows trust policy.
2. Follow that authority’s identity verification and hardware-key requirements.
3. If the certificate is exportable, export the certificate and private key as
   a password-protected `.pfx`. Never commit it to Git.
4. Convert the PFX to base64 locally or use a private authenticated download
   URL supported by Electron Builder.
5. Add `WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD` as GitHub Actions repository
   secrets.
6. Leave the seven Azure secrets unset. The workflow uses PFX signing only when
   the complete Azure setup is absent.

Extended-validation certificates stored only on a USB hardware token often
cannot be used by a hosted GitHub runner. Confirm unattended CI support with
the certificate authority before paying.

## Mac: Developer ID and notarization

Apple currently charges USD $99 per year for the Apple Developer Program.
Friends do not need Apple developer accounts.

1. Open [Apple Developer enrollment](https://developer.apple.com/programs/enroll/)
   and enroll the person or organization that will distribute the app outside
   the Mac App Store.
2. After approval, open Xcode on the owner Mac, choose **Settings**, **Accounts**,
   sign in, select the team, and use **Manage Certificates** to create a
   **Developer ID Application** certificate. Do not use an Apple Development
   certificate for friend distribution.
3. Open **Keychain Access**, find that Developer ID Application certificate
   with its private key, export both as a password-protected `.p12`, and keep
   the file outside the repository.
4. Base64-encode the `.p12` as one line. Save that value in the GitHub secret
   `CSC_LINK` and its export password in `CSC_KEY_PASSWORD`.
5. At [Apple Account](https://account.apple.com/), open **Sign-In and Security**,
   choose **App-Specific Passwords**, create one for AutoEditor notarization,
   and save it as `APPLE_APP_SPECIFIC_PASSWORD`.
6. Save the Apple ID email as `APPLE_ID`.
7. Copy the 10-character Team ID from the Apple Developer membership page and
   save it as `APPLE_TEAM_ID`.
8. Run a manual acceptance build first. For a tagged build, the workflow signs
   the app with hardened runtime, submits the app and both DMGs to Apple’s
   notary service, staples the tickets, and validates Gatekeeper before it can
   publish.

Apple setup references:

- [Apple Developer Program enrollment and price](https://developer.apple.com/programs/)
- [Distribute outside the Mac App Store](https://developer.apple.com/developer-id/)
- [Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)

## Private website publishing

The tagged workflow also requires `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID`. The token needs only the account and R2 object-write
permissions required for the `autoeditor-media` bucket. Never reuse a global
Cloudflare API key. A tagged build stops before the release is announced if
private download publishing cannot complete.

## Secret safety check

Repository files contain secret names only. Before tagging, run `gh secret
list` and confirm each required name exists. Never paste a secret into an issue,
commit, workflow input, chat message, screenshot, log, or friend guide.
