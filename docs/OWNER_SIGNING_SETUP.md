# Owner-only signing setup

Friends never do anything in this file. They receive one normal Windows `.exe`
or Mac `.dmg`. Signing is a one-time owner setup in Microsoft, Apple, and
GitHub so their computers can verify the installer came from Omar and was not
changed after it was built.

## Protect signing credentials before creating them

Do this before adding any Apple, Windows, Azure, PFX, or release-candidate
secret. The workflow already names `helper-windows-signing` and
`helper-macos-signing`; the GitHub environments must exist and be protected
before a `helper-v*` tag is created.

1. In GitHub, open **Settings**, **Environments**, and create
   `helper-windows-signing` and `helper-macos-signing`.
2. Add a required reviewer to each environment. If the repository is private
   and the current GitHub plan does not support required reviewers and
   environment secrets, stop and upgrade the plan before adding credentials.
3. Under **Deployment branches and tags**, choose **Selected branches and
   tags**. Add only the tag pattern `helper-v*`. Do not allow every branch,
   every tag, or the default branch.
4. Open **Settings**, **Rules**, **Rulesets**, and create an active tag ruleset
   for `helper-v*`. Restrict tag creation, updates, and deletion. Give bypass
   permission only to Omar or a dedicated release role. A signing tag must
   point to a reviewed commit on the protected default branch.
5. Put Windows secrets only in `helper-windows-signing`. Put Apple secrets only
   in `helper-macos-signing`. Put the candidate-upload secrets in both signing
   environments because both signed jobs upload their own candidate.
6. Remove any repository-level copies of those secrets. Environment approval
   must happen before a signing job can read them.

GitHub documents that environment secrets are limited to jobs that reference
the environment and stay unavailable until configured protection rules pass.
The tag ruleset separately prevents unapproved creation, replacement, or
deletion of a matching release tag.

PSE is a separate product channel. If PSE releases remain active, create
`pse-windows-signing` and `pse-macos-signing` with the same required-reviewer
rule, but allow only `pse-v*` tags. Put `WIN_CSC_LINK`,
`WIN_CSC_KEY_PASSWORD`, and `WIN_PFX_CERT_THUMBPRINT` only in
`pse-windows-signing`. Put the Apple certificate and notarization secrets only
in `pse-macos-signing`. The PSE Windows workflow rejects any trusted signature
whose leaf thumbprint does not match that approved PFX.

- [GitHub deployment environments and secrets](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub branch and tag ruleset controls](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

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
   Capitalization, punctuation, and spacing must match. Before adding GitHub
   secrets, open PowerShell on a trusted owner computer and retrieve the durable
   customer EKU directly from the approved account and profile:

   ```powershell
   Install-Module Az.ArtifactSigning -Scope CurrentUser
   Connect-AzAccount
   $customerEku = Get-AzArtifactSigningCustomerEku `
     -AccountName '<artifact-signing-account>' `
     -ProfileName '<certificate-profile>' `
     -EndpointUrl '<artifact-signing-endpoint>'
   $customerEku
   ```

   The command is documented by
   [Microsoft](https://learn.microsoft.com/en-us/powershell/module/az.artifactsigning/get-azartifactsigningcustomereku).
   Record the returned subscriber identity OID that begins
   `1.3.6.1.4.1.311.97.`. Stop if the command returns nothing or a different
   OID family. Do not use the daily leaf certificate thumbprint. Azure renews
   that certificate every day.
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
12. In GitHub, open **Settings**, **Environments**,
    **helper-windows-signing**, then add all eight as environment secrets:

    - `AZURE_TENANT_ID`: Directory tenant ID from step 9.
    - `AZURE_CLIENT_ID`: Application client ID from step 9.
    - `AZURE_CLIENT_SECRET`: client secret value from step 10.
    - `WIN_AZURE_PUBLISHER_NAME`: exact certificate publisher from step 7.
    - `WIN_AZURE_ENDPOINT`: exact account endpoint from step 4.
    - `WIN_AZURE_CERTIFICATE_PROFILE_NAME`: exact profile name from step 6.
    - `WIN_AZURE_CODE_SIGNING_ACCOUNT_NAME`: exact account name from step 4.
    - `WIN_AZURE_SUBSCRIBER_IDENTITY_EKU`: exact durable subscriber identity
      OID from step 7.

13. Run the Helper workflow manually first. A manual build is an unsigned
    engineering-acceptance build and is never published to friends.
14. When the unsigned engineering checks pass, create a `helper-v*` tag. The
    tagged workflow selects Azure signing, verifies Authenticode on the
    installer and installed app, uploads an exact signed candidate for physical
    acceptance, then stops without changing live downloads.
15. Download the signed Windows candidate from that Actions run and complete
    `WINDOWS_FIRST_SETUP.md`. Promote only after the Windows and both Mac
    candidates from the same run pass the complete physical checklist.

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
5. Copy the certificate SHA-1 thumbprint from the certificate authority or
   Windows certificate viewer. Add `WIN_CSC_LINK`, `WIN_CSC_KEY_PASSWORD`, and
   `WIN_PFX_CERT_THUMBPRINT` only as `helper-windows-signing` environment
   secrets. The workflow removes spaces and punctuation before comparing the
   expected thumbprint with the installer, installed app, and uninstaller.
6. Leave the eight Azure secrets unset. The workflow uses PFX signing only when
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
4. Base64-encode the `.p12` as one line. Save that value only in the
   `helper-macos-signing` environment secret `CSC_LINK`, and save its export
   password there as `CSC_KEY_PASSWORD`.
5. At [Apple Account](https://account.apple.com/), open **Sign-In and Security**,
   choose **App-Specific Passwords**, create one for AutoEditor notarization,
   and save it as the `helper-macos-signing` environment secret
   `APPLE_APP_SPECIFIC_PASSWORD`.
6. Save the Apple ID email in that environment as `APPLE_ID`.
7. Copy the 10-character Team ID from the Apple Developer membership page and
   save it in that environment as `APPLE_TEAM_ID`.
8. Run a manual acceptance build first. For a tagged build, the workflow signs
   the app with hardened runtime, submits the app and both DMGs to Apple’s
   notary service, staples the tickets, validates Gatekeeper, and uploads signed
   candidates for physical acceptance. The tagged build cannot publish them.

Apple setup references:

- [Apple Developer Program enrollment and price](https://developer.apple.com/programs/)
- [Distribute outside the Mac App Store](https://developer.apple.com/developer-id/)
- [Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)

## Private website publishing

The installers are larger than Wrangler's upload limit, so tagged builds use a
pinned S3-compatible multipart client. Release files must not share credentials
or a bucket with friends' private footage. This is owner setup. Friends do not
need a Cloudflare account.

1. Open the Cloudflare dashboard and select **R2 Object Storage**.
2. Create `autoeditor-release-candidates`. Open its lifecycle settings and add
   a rule that deletes objects after seven days. Failed or superseded build
   candidates then clean themselves up.
3. Create `autoeditor-releases` with no expiry rule. The Worker reads friend
   installers only from this bucket. Private footage stays in the separate
   `autoeditor-media` bucket.
4. Lock the content-addressed live objects before the first release. From
   `webapp/worker`, run:

   ```bash
   npx wrangler r2 bucket lock set autoeditor-releases \
     --file r2-release-locks.json
   npx wrangler r2 bucket lock list autoeditor-releases
   ```

   Confirm the list contains indefinite rules for `dist/helper/objects/` and
   `dist/helper/checksums/`. Do not add a rule for
   `dist/helper/current.json`; that one pointer must remain replaceable for a
   release or rollback. Cloudflare bucket locks apply to existing and future
   objects and prevent both deletion and overwrite. The strictest matching
   rule wins.
5. Open **Manage R2 API Tokens**, choose **Create API token**, and create a
   candidate token with object read and write access only to
   `autoeditor-release-candidates`.
6. Copy that token's **Access Key ID** and **Secret Access Key** while they are
   shown. Cloudflare does not show the secret again.
7. Create a second promotion token with access only to
   `autoeditor-release-candidates` and `autoeditor-releases`. The separate manual
   promotion workflow uses it to verify candidates, copy them into the live
   bucket, and update the live pointer. Build and signing jobs never receive
   this token.
8. Copy the second token's Access Key ID and Secret Access Key, then copy the
   Cloudflare account ID from the dashboard.
9. Open [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens),
   choose **Create Custom Token**, and give it one account permission:
   **Workers R2 Storage**, **Read**. Under **Account Resources**, include only
   the Cloudflare account that owns `autoeditor-releases`. Create the token and
   copy its bearer-token value while it is shown. This dedicated
   `Workers R2 Storage Read` token can inspect bucket configuration, but cannot
   change lock rules or release objects. It is separate from both pairs of R2
   Access Key ID and Secret Access Key credentials above.
10. In each GitHub signing environment, add these three environment secrets for
   signed candidate upload. Add them to both `helper-windows-signing` and
   `helper-macos-signing`; do not add repository-level copies:

   - `R2_CANDIDATE_ACCESS_KEY_ID`: candidate token Access Key ID.
   - `R2_CANDIDATE_SECRET_ACCESS_KEY`: candidate token Secret Access Key.
   - `CLOUDFLARE_ACCOUNT_ID`: account ID from step 8.

11. Protect the repository's default branch with a branch protection rule or
    ruleset. Do not allow direct, unreviewed changes to the release workflow on
    that branch.
12. Open **Settings**, **Environments**, create `helper-live-release`, and add
    Omar as a required reviewer. Under **Deployment branches and tags**, choose
    **Selected branches and tags**, then add only the exact protected default
    branch name. Do not allow every branch, tags, or wildcard patterns. Put only
    these promotion secrets in that environment:

    - `R2_RELEASE_ACCESS_KEY_ID`: promotion token Access Key ID.
    - `R2_RELEASE_SECRET_ACCESS_KEY`: promotion token Secret Access Key.
    - `CLOUDFLARE_ACCOUNT_ID`: account ID from step 8.
    - `CLOUDFLARE_R2_LOCKS_READ_TOKEN`: dedicated read-only bearer token from
      step 9, scoped to the account permission `Workers R2 Storage Read`.

    Do not put Apple, Windows, Azure, candidate-bucket, or user-media secrets in
    this environment. The promotion workflow has no reason to receive them.

Each signed platform job uploads its installer under a content-addressed key in
the candidate bucket, records its byte count and SHA-256 digest, and adds a
seven-day signed-candidate artifact to that Actions run. Windows also uploads
the separately hash-bound `.nsis.7z` runtime package. The tagged build ends
there. It has no live-release credentials and cannot change `current.json`.

After every signed candidate from that exact run passes physical acceptance,
open **Actions**, choose **Promote accepted AutoEditor Helper release**, enter
the accepted tag, build run ID, and 40-character commit SHA, check the physical
acceptance box, then press **Run workflow**. The protected promotion job rejects
version downgrades and same-version provenance changes. It verifies all three
receipt-bound candidates, copies all three installers and the Windows runtime
package to the live bucket, and creates or
refreshes a metadata-only GitHub release. One conditional `current.json` write
exposes all three platforms together at the end. A failed build or promotion
can leave expiring, unreferenced candidates, but it cannot partially change live
downloads or access user footage. The large installers are never attached to
GitHub Releases because a single GitHub release asset must remain under 2 GiB.

Before any copy, checksum write, GitHub Release change, or `current.json`
write, promotion fetches the exact public
`/download/helper/runtime/contract` route and requires the Helper runtime and
release v2 schemas. It then uses Cloudflare's official bucket-lock GET API to
require exactly two enabled, indefinite rules, one for
`dist/helper/objects/` and one for `dist/helper/checksums/`. A missing token,
older live Worker, API error, disabled rule, extra rule, changed prefix, or
non-indefinite condition stops promotion before live release state changes.

Cloudflare references:

- [Get Bucket Lock Rules API](https://developers.cloudflare.com/api/resources/r2/subresources/buckets/subresources/locks/methods/get/)
- [R2 API token permissions](https://developers.cloudflare.com/r2/api/tokens/#permissions)

## Secret safety check

Repository files contain secret names only. Before tagging, run `gh secret
list --env helper-windows-signing` and `gh secret list --env
helper-macos-signing`. Confirm that the signing and candidate-upload names are
present only in their intended environments, then run `gh secret list` and
remove any repository-level duplicates. Before promotion, run `gh secret list
--env helper-live-release` for the four promotion names. Never paste a secret
into an issue, commit, workflow input, chat message, screenshot, log, or friend
guide.
