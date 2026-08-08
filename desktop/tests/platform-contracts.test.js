const assert = require('assert');
const fs = require('fs');
const path = require('path');

const desktop = path.resolve(__dirname, '..');
const main = fs.readFileSync(path.join(desktop, 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8');
const renderer = fs.readFileSync(
  path.join(desktop, 'renderer', 'app.js'), 'utf8');
const workflow = fs.readFileSync(
  path.join(desktop, '..', '.github', 'workflows', 'release.yml'), 'utf8');
const product = fs.readFileSync(path.join(desktop, 'product.js'), 'utf8');
const legacyBuilder = fs.readFileSync(
  path.join(desktop, 'electron-builder.yml'), 'utf8');
const helperMain = fs.readFileSync(
  path.join(desktop, 'helper', 'main.js'), 'utf8');
const helperWorkflow = fs.readFileSync(
  path.join(desktop, '..', '.github', 'workflows', 'helper-release.yml'), 'utf8');
const helperPromotion = fs.readFileSync(
  path.join(desktop, '..', '.github', 'workflows', 'helper-promote.yml'), 'utf8');
const helperAzure = fs.readFileSync(
  path.join(desktop, 'electron-builder.helper.azure.js'), 'utf8');
const helperInstaller = fs.readFileSync(
  path.join(desktop, 'build', 'helper-installer.nsh'), 'utf8');
const nsisWebPatch = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'patch_nsis_web_integrity.py'), 'utf8');
const nsisWebPrepare = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'prepare_nsis_web.py'), 'utf8');
const releaseStorage = fs.readFileSync(
  path.join(desktop, 'scripts', 'r2-release-storage.js'), 'utf8');
const helperReleaseMetadata = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'helper_release_metadata.py'), 'utf8');
const helperManifestGenerator = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'generate_helper_manifest.py'), 'utf8');
const helperManifestVerifier = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'verify_helper_manifest.py'), 'utf8');
const workerSource = fs.readFileSync(
  path.join(desktop, '..', 'webapp', 'worker', 'src', 'index.js'), 'utf8');
const engineSpec = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'engine.spec'), 'utf8');
const helperDaemonSpec = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'helper_daemon.spec'), 'utf8');
const thirdPartyNotices = fs.readFileSync(
  path.join(desktop, '..', 'packaging', 'THIRD_PARTY_NOTICES.md'), 'utf8');
const ffmpegFormulaVerifier = fs.readFileSync(
  path.join(desktop, '..', 'packaging',
    'verify_macos_ffmpeg_formulae.py'), 'utf8');
const ffmpegFormulaInventories = ['arm64', 'x64'].map((arch) =>
  fs.readFileSync(path.join(desktop, '..', 'packaging',
    `macos-ffmpeg-formulae-${arch}.txt`), 'utf8'));
const desktopPackage = JSON.parse(fs.readFileSync(
  path.join(desktop, 'package.json'), 'utf8'));
const ownerSigning = fs.readFileSync(
  path.join(desktop, '..', 'docs', 'OWNER_SIGNING_SETUP.md'), 'utf8');
const launchChecklist = fs.readFileSync(
  path.join(desktop, '..', 'docs', 'LAUNCH_CHECKLIST.md'), 'utf8');
const releaseGateStatus = fs.readFileSync(
  path.join(desktop, '..', 'docs', 'RELEASE_GATE_STATUS.md'), 'utf8');
const ignoreRules = fs.readFileSync(
  path.join(desktop, '..', '.gitignore'), 'utf8');

assert.ok((main.match(/windowsHide: true/g) || []).length >= 3);
assert.ok(main.includes('stopProcessTree(active)'));
assert.ok(main.includes("AUTOEDITOR_SMOKE_TEST === '1'"));
assert.ok(main.includes('safeStorage.encryptString(secret)'));
assert.ok(preload.includes('webUtils.getPathForFile(file)'));
assert.ok(renderer.includes('window.api.filePath(f)'));
assert.ok(!renderer.includes('.map((f) => f.path)'));
assert.ok(!main.includes("require('electron-updater')"));
assert.ok(!main.includes('checkForUpdatesAndNotify'));
assert.ok(!desktopPackage.dependencies?.['electron-updater']);
assert.ok(!desktopPackage.devDependencies?.['electron-updater']);
assert.ok(!product.includes('ryan:'));
assert.ok(product.includes("process.env.PRODUCT || 'pse'"));
assert.ok(legacyBuilder.includes('appId: com.marabha.pseautoeditor'));
assert.ok(legacyBuilder.includes('productName: PSE AutoEditor'));
assert.ok(legacyBuilder.includes('writeUpdateInfo: false'));
assert.ok(legacyBuilder.includes('differentialPackage: false'));
assert.ok(workflow.includes('Smoke-test Windows installer'));
assert.ok(workflow.includes('Smoke-test macOS app and DMG'));
assert.ok(workflow.includes('Publish only after every platform passes'));
assert.ok(helperMain.includes("AUTOEDITOR_REQUIRE_HYPERFRAMES: '1'"));
assert.ok(helperMain.includes("AUTOEDITOR_REQUIRE_REMOTION: '1'"));
assert.ok(helperMain.includes("PYTHONUTF8: '1'"));
assert.ok(helperMain.includes("PYTHONIOENCODING: 'utf-8'"));
for (const spec of [engineSpec, helperDaemonSpec]) {
  assert.ok(spec.includes('options = [("X utf8", None, "OPTION")]'));
  assert.ok(spec.includes('EXE(pyz, a.scripts, options'));
}
assert.ok(helperMain.includes('AUTOEDITOR_CREATIVE_SMOKE_TEST'));
assert.ok(helperMain.includes('validateProviderKeys'));
assert.ok(helperWorkflow.includes('windows-2022'));
assert.ok(helperWorkflow.includes('macos-15-intel'));
assert.ok(helperWorkflow.includes('Render real HyperFrames and Remotion probes'));
assert.ok(helperWorkflow.includes('STAGE=$(realpath "$STAGE")'));
assert.ok(helperWorkflow.includes(
  '"$NODE" "$STAGE/creative-runtime/node_modules/hyperframes/bin/hyperframes.mjs"'));
assert.ok(!helperWorkflow.includes('"$GITHUB_WORKSPACE/$STAGE/creative-runtime'));
assert.ok(helperWorkflow.includes('Get-AuthenticodeSignature'));
assert.ok(helperWorkflow.includes('kind=azure'));
assert.ok(helperWorkflow.includes('WIN_PFX_CERT_THUMBPRINT'));
assert.ok(helperWorkflow.includes('WIN_AZURE_SUBSCRIBER_IDENTITY_EKU'));
assert.ok(helperWorkflow.includes('Normalize-Thumbprint'));
assert.ok(helperWorkflow.includes('Assert-AuthenticodeSigner'));
assert.ok(helperWorkflow.includes('Get-EnhancedKeyUsageValues'));
assert.ok(helperWorkflow.includes('1.3.6.1.4.1.311.97.1.0'));
assert.ok(helperWorkflow.includes(
  'signer thumbprint does not match the approved certificate'));
assert.ok(helperWorkflow.includes(
  'approved Artifact Signing subscriber identity EKU'));
assert.ok(helperAzure.includes('azureSignOptions'));
assert.ok(ownerSigning.includes('AZURE_TENANT_ID'));
assert.ok(ownerSigning.includes('WIN_PFX_CERT_THUMBPRINT'));
assert.ok(ownerSigning.includes('WIN_AZURE_SUBSCRIBER_IDENTITY_EKU'));
assert.ok(ownerSigning.includes('Install-Module Az.ArtifactSigning'));
assert.ok(ownerSigning.includes('Get-AzArtifactSigningCustomerEku'));
assert.ok(ownerSigning.includes("-AccountName '<artifact-signing-account>'"));
assert.ok(ownerSigning.includes('Signing Certificate Profile Signer'));
assert.ok(ownerSigning.includes('APPLE_APP_SPECIFIC_PASSWORD'));
// Signing and candidate credentials stay behind reviewer-approved platform
// environments. The guide must never send them back to repository scope.
assert.ok(ownerSigning.includes('helper-windows-signing'));
assert.ok(ownerSigning.includes('helper-macos-signing'));
assert.ok(ownerSigning.includes('Add a required reviewer to each environment'));
assert.ok(ownerSigning.includes('create an active tag ruleset'));
assert.ok(ownerSigning.includes('Remove any repository-level copies'));
assert.ok(!ownerSigning.includes('**New repository secret**'));
assert.ok(!ownerSigning.includes(
  'repository secrets for signed candidate upload'));
assert.ok(helperWorkflow.includes('xcrun stapler validate'));
assert.ok(helperWorkflow.includes(
  'Upload the verified Windows candidate'));
assert.ok(helperWorkflow.includes('python -m pip install --require-hashes'));
assert.ok(helperWorkflow.includes('PYTHONUTF8: "1"'));
assert.ok(helperWorkflow.includes('PYTHONIOENCODING: utf-8'));
assert.ok(helperWorkflow.includes(
  'requirements-${{ matrix.target_os }}-${{ matrix.arch }}.txt'));
assert.ok(helperWorkflow.includes(
  '8e148d10ce8da1dca931c2f35c3a180100520bb48940f4bf1c0a3c1627467331'));
for (const releaseSource of [workflow, helperWorkflow]) {
  assert.ok(releaseSource.includes('FFMPEG-GPL-3.0.txt'));
  assert.ok(releaseSource.includes('FFMPEG_FORMULAE.txt'));
  assert.ok(releaseSource.includes('verify_macos_ffmpeg_formulae.py'));
  assert.ok(releaseSource.includes(
    'macos-ffmpeg-formulae-${{ matrix.arch }}.txt'));
  assert.ok(releaseSource.includes(
    'done < "$STAGE/licenses/FFMPEG_FORMULAE.txt"'));
  assert.ok(releaseSource.includes('brew fetch --force "$FORMULA"'));
  assert.ok(releaseSource.includes('HOMEBREW_NO_AUTO_UPDATE=1'));
  assert.ok(releaseSource.includes('HOMEBREW_NO_INSTALL_CLEANUP=1'));
  assert.ok(releaseSource.includes("grep -Fx 'Homebrew 6.0.15'"));
  assert.ok(releaseSource.includes(
    'brew reinstall --force-bottle "$FORMULA"'));
  assert.ok(releaseSource.includes('brew reinstall --force-bottle ffmpeg'));
  assert.ok(releaseSource.includes('--expected-arch "${{ matrix.arch }}"'));
  assert.ok(releaseSource.includes('8\\.1\\.2_1([[:space:]]|$)'));
  assert.ok(!releaseSource.includes('FORMULAE=('));
  assert.ok(!releaseSource.includes('8\\.1\\.2(_[0-9]+)?'));
  assert.ok(releaseSource.includes('ffmpeg-components'));
  assert.ok(releaseSource.includes('INSTALL_RECEIPT.json'));
  assert.ok(releaseSource.includes('FFMPEG_BUILDCONF.txt'));
}
assert.ok(ffmpegFormulaVerifier.includes('otool_dependencies'));
assert.ok(ffmpegFormulaVerifier.includes('compare_inventories'));
assert.ok(ffmpegFormulaVerifier.includes('verify_bottle_archive'));
assert.ok(ffmpegFormulaVerifier.includes('verify_cached_bottles'));
assert.ok(ffmpegFormulaVerifier.includes('poured_from_bottle'));
assert.ok(ffmpegFormulaVerifier.includes('outside Homebrew Cellar'));
for (const inventory of ffmpegFormulaInventories) {
  assert.ok(inventory.includes('ffmpeg 8.1.2_1'));
  assert.ok(inventory.includes('x264 r3222'));
  const rows = inventory.trim().split('\n');
  assert.strictEqual(rows.length, 11);
  assert.ok(rows.every((row) =>
    /^[^ ]+ [^ ]+ [^ ]+ \d+ [0-9a-f]{64}$/.test(row)));
}
assert.ok(ffmpegFormulaInventories[0].includes('arm64_sequoia'));
assert.ok(ffmpegFormulaInventories[1].includes(' sonoma '));
assert.ok(ffmpegFormulaInventories[0].includes(
  'openssl@3 3.6.3 arm64_sequoia 1'));
assert.ok(ffmpegFormulaInventories[1].includes(
  'openssl@3 3.6.3 sonoma 1'));
assert.ok(thirdPartyNotices.includes('Before any third-party handoff'));
assert.ok(!thirdPartyNotices.includes('private acceptance testers'));
assert.ok(helperWorkflow.includes('r2-release-storage.js upload'));
assert.ok(helperWorkflow.includes('R2_CANDIDATE_ACCESS_KEY_ID'));
assert.ok(!helperWorkflow.includes('R2_RELEASE_ACCESS_KEY_ID'));
assert.ok(helperPromotion.includes('R2_RELEASE_ACCESS_KEY_ID'));
assert.ok(helperWorkflow.includes('"$ENGINE" --self-test'));
for (const nativeMediaRuntime of ['PyAV', 'Electron', 'Remotion compositor']) {
  assert.ok(thirdPartyNotices.includes(nativeMediaRuntime));
}
assert.strictEqual(desktopPackage.devDependencies['@aws-sdk/client-s3'],
  '3.1106.0');
assert.strictEqual(desktopPackage.devDependencies['@aws-sdk/lib-storage'],
  '3.1106.0');
assert.ok(releaseStorage.includes('request.IfMatch = ifMatch'));
assert.ok(releaseStorage.includes('request.IfNoneMatch = ifNoneMatch'));
assert.ok(releaseStorage.includes('conditional pointer write blocked'));
assert.ok(ignoreRules.includes('!packaging/helper-runtime/package-lock.json'));
assert.ok(ignoreRules.includes('!templates/remotion-viz/package-lock.json'));
assert.ok(ignoreRules.includes('!webapp/worker/package-lock.json'));
const helperHtml = fs.readFileSync(
  path.join(desktop, 'helper', 'renderer', 'index.html'), 'utf8');
assert.ok(helperHtml.includes('Built by Omar Marabha'));

// 2026-08 Mac acceptance regressions must stay fixed.
const helperBuilder = fs.readFileSync(
  path.join(desktop, 'electron-builder.helper.yml'), 'utf8');
// The creative runtime's node_modules ships as an explicit file set so
// electron-builder cannot prune HyperFrames/Remotion out of the installer.
assert.ok(helperBuilder.includes(
  'from: helper-staging/creative-runtime/node_modules'));
// The DMG stays plain. Null selects dmg-builder's bundled image, while an
// explicit color is its supported no-background-image path.
assert.ok(helperBuilder.includes('backgroundColor: "#0b0d10"'));
assert.ok(!helperBuilder.includes('background: null'));
// Both products ship a real icon, not the default Electron one.
assert.ok(helperBuilder.includes('icon: build/icon.icns'));
// Windows remains one friend-facing EXE, with the multi-gigabyte required
// runtime carried as an immutable external package because NSIS cannot embed it.
assert.ok(helperBuilder.includes('- target: nsis-web'));
assert.ok(helperBuilder.includes('differentialPackage: false'));
assert.ok(helperBuilder.includes('include: helper-installer.nsh'));
assert.ok(helperInstaller.includes('!macro customUnInstall'));
assert.ok(helperInstaller.includes('${ifNot} ${isUpdated}'));
assert.ok(helperInstaller.includes(
  'Delete "$LOCALAPPDATA\\${APP_PACKAGE_STORE_FILE}"'));
assert.ok(helperInstaller.includes(
  'RMDir "$LOCALAPPDATA\\autoeditor-desktop-updater"'));
assert.ok(nsisWebPrepare.includes('INETC_VERSION = "1.0.5.7"'));
assert.ok(nsisWebPrepare.includes(
  '447625a39809f1df19ddeba9cb1c30e26ca741be'));
assert.ok(nsisWebPrepare.includes(
  'b01077e56ebb19c005b45d40f837958ca6a92f51a5a937dc1bb497c7c7f2aa93'));
assert.ok(nsisWebPatch.includes('ELECTRON_BUILDER_VERSION = "26.15.3"'));
assert.ok(nsisWebPatch.includes('APP_64_HASH'));
assert.ok(nsisWebPatch.includes('AutoEditorINetC::get'));
assert.ok(nsisWebPatch.includes('write_bytes('));
assert.ok(!nsisWebPatch.includes('installer.write_text('));
assert.ok(helperManifestVerifier.includes('empty_directory_receipt'));
assert.ok(helperManifestVerifier.includes(
  'component path is not a directory'));
assert.ok(fs.existsSync(path.join(desktop, 'build', 'icon.icns')));
assert.ok(fs.existsSync(path.join(desktop, 'build', 'icon.ico')));
// CI inspects the PACKED app for the creative runtime and verifies the app
// from a fresh DMG mount, resolving the executable from Info.plist.
assert.ok(helperWorkflow.includes(
  'Verify the packed app ships the complete creative runtime'));
assert.ok(helperWorkflow.includes('CFBundleExecutable'));
assert.ok(helperWorkflow.includes('hdiutil attach'));
assert.ok(helperWorkflow.includes(
  '--config.directories.output="$HELPER_DIST"'));
assert.ok(helperWorkflow.includes('verify_helper_manifest.py'));
assert.ok(helperManifestGenerator.includes('pe-authenticode-content-v1'));
assert.ok(workflow.includes('pe-authenticode-content-v1'));
assert.ok(workflow.includes(
  'normalize_windows_executables=normalize_windows'));
assert.ok(!helperWorkflow.includes('dist/helper/current.json'));
assert.ok(helperPromotion.includes('dist/helper/current.json'));
assert.ok(helperPromotion.includes('release-receipt-helper-*'));
assert.ok(helperPromotion.includes('--if-match "$ETAG"'));
assert.ok(helperPromotion.includes("--if-none-match '*'"));
assert.ok(!helperWorkflow.includes('wrangler r2 object put'));
assert.ok(!helperWorkflow.includes('aws s3 cp'));
assert.ok(!helperPromotion.includes('wrangler r2 object put'));
assert.ok(!helperPromotion.includes('aws s3 cp'));
assert.ok(workflow.includes('CFBundleExecutable'));

const ciWorkflow = fs.readFileSync(
  path.join(desktop, '..', '.github', 'workflows', 'ci.yml'), 'utf8');
for (const candidate of [workflow, helperWorkflow, helperPromotion, ciWorkflow]) {
  assert.ok(!/uses:\s+actions\/[^@\s]+@v\d/.test(candidate));
  const actionRefs = [...candidate.matchAll(
    /uses:\s+actions\/[^@\s]+@([^\s#]+)/g)].map((match) => match[1]);
  assert.ok(actionRefs.length > 0);
  assert.ok(actionRefs.every((ref) => /^[0-9a-f]{40}$/.test(ref)));
}
assert.ok(ciWorkflow.includes('Run desktop platform contracts'));
assert.ok(ciWorkflow.includes('Run Worker integration contracts'));
assert.ok(ciWorkflow.includes('npm ci --prefix webapp/worker'));
assert.ok(ciWorkflow.includes('npm test --prefix webapp/worker'));
assert.ok(ciWorkflow.includes('webapp/worker/package-lock.json'));
assert.ok(ciWorkflow.includes('persist-credentials: false'));
assert.ok(ciWorkflow.includes('packaging/requirements-linux-x64.txt'));
assert.ok(ciWorkflow.includes('--require-hashes --only-binary=:all:'));
assert.ok(ciWorkflow.includes('python -m pytest -q tests webapp/tests'));
const ciDesktopInstallAt = ciWorkflow.indexOf('npm ci --prefix desktop');
const ciPythonSafetyAt = ciWorkflow.indexOf(
  'python -m pytest -q tests webapp/tests');
assert.ok(ciDesktopInstallAt >= 0);
assert.ok(ciPythonSafetyAt > ciDesktopInstallAt);
assert.ok(ciWorkflow.includes('npm test --prefix desktop'));
assert.ok(!ciWorkflow.includes('pip install -r requirements.txt'));

// The generic Helper is the sole friend product. The creator-specific Ryan
// release trigger/default is retired, while PSE remains its own channel.
assert.ok(!workflow.includes('ryan-v'));
assert.ok(!workflow.includes('Ryan Reels'));
assert.ok(workflow.includes('tags: ["pse-v*"]'));
assert.ok(workflow.includes('product=pse'));
assert.ok(helperWorkflow.includes('AutoEditor Helper'));
assert.ok(!legacyBuilder.includes('\npublish:'));
assert.ok(!workflow.includes("-name '*.yml'"));
assert.ok(!workflow.includes("-name '*.blockmap'"));

function jobSlice(source, start, end) {
  const startAt = source.indexOf(start);
  assert.ok(startAt >= 0, `missing workflow marker: ${start}`);
  const endAt = end ? source.indexOf(end, startAt + start.length) : source.length;
  assert.ok(endAt > startAt, `missing workflow marker: ${end}`);
  return source.slice(startAt, endAt);
}

const helperUnsigned = jobSlice(helperWorkflow, '\n  build:', '\n  sign-windows:');
const helperWindows = jobSlice(
  helperWorkflow, '\n  sign-windows:', '\n  sign-macos:');
const helperMac = jobSlice(helperWorkflow, '\n  sign-macos:', null);
const helperPromotionPreflight = jobSlice(
  helperPromotion, '\n  preflight:', '\n  promote:');
const helperPromote = jobSlice(helperPromotion, '\n  promote:', null);
const pseUnsigned = jobSlice(workflow, '\n  build:', '\n  sign-windows:');
const pseWindows = jobSlice(workflow, '\n  sign-windows:', '\n  sign-macos:');
const pseMac = jobSlice(workflow, '\n  sign-macos:', '\n  release:');
const releaseWorkflow = jobSlice(workflow, '\n  release:', null);

for (const windowsInstallerJob of [helperUnsigned, helperWindows]) {
  const prepareAt = windowsInstallerJob.indexOf('prepare_nsis_web.py');
  const patchAt = windowsInstallerJob.indexOf('patch_nsis_web_integrity.py');
  const buildAt = windowsInstallerJob.indexOf('electron-builder --config');
  assert.ok(prepareAt >= 0);
  assert.ok(patchAt > prepareAt);
  assert.ok(buildAt > patchAt);
  assert.ok(windowsInstallerJob.includes(
    '/download/helper/runtime/windows-x64/'));
  assert.ok(windowsInstallerJob.includes('/$GITHUB_SHA'));
  assert.ok(windowsInstallerJob.includes('nsis-web/*.exe'));
  assert.ok(windowsInstallerJob.includes('nsis-web/*.nsis.7z'));
  assert.ok(windowsInstallerJob.includes('[uint64]4294967295'));
  assert.ok(windowsInstallerJob.includes('--package-file=$corrupt'));
  assert.ok(windowsInstallerJob.includes(
    'autoeditor-desktop-updater/package.7z'));
  assert.ok(windowsInstallerJob.includes('(Test-Path $runtimeCache)'));
}
assert.ok(helperWindows.includes('--runtime-package "$RUNTIME_PACKAGE"'));
assert.ok(helperWindows.includes('["runtime_package"]["key"]'));
assert.ok(helperWindows.includes('["runtime_package"]["sha256"]'));
assert.ok(helperWindows.includes('["runtime_package"]["content_type"]'));
assert.ok(helperPromotion.includes('release-metadata/copy-plan.tsv'));
assert.ok(helperPromotion.includes(
  'test "$(wc -l < release-metadata/copy-plan.tsv'));
assert.ok(helperPromotion.includes('if package is not None:'));
assert.ok(helperReleaseMetadata.includes(
  'SCHEMA = "autoeditor-helper-candidate/v2"'));
assert.ok(helperReleaseMetadata.includes(
  'RELEASE_SCHEMA = "autoeditor-helper-release/v2"'));
assert.ok(helperReleaseMetadata.includes('MAX_NSIS_WEB_PACKAGE_BYTES'));
assert.ok(helperReleaseMetadata.includes('"runtime_package"'));
assert.ok(workerSource.includes(
  "const HELPER_RELEASE_SCHEMA = 'autoeditor-helper-release/v2'"));
assert.ok(workerSource.includes('HELPER_RUNTIME_ROUTE'));
assert.ok(workerSource.includes("release.platforms['windows-x64'].runtime_package"));
assert.ok(workerSource.includes('route[1] !== release.tag'));
assert.ok(workerSource.includes('route[2] !== release.commit'));

// A tagged build must upload its sealed stage before electron-builder creates
// another multi-gigabyte unpacked payload and installer. Standard hosted
// runners have limited disk, so the local tar is removed before packaging.
const helperManifestAt = helperUnsigned.indexOf(
  '- name: Write exact runtime manifest');
const helperSealAt = helperUnsigned.indexOf(
  '- name: Seal prepared runtime for tag-only signing jobs');
const helperStageUploadAt = helperUnsigned.indexOf(
  '- name: Upload prepared runtime to isolated signing job');
const helperArchiveReleaseAt = helperUnsigned.indexOf(
  '- name: Release local signing archive before packaging');
const helperBuildAt = helperUnsigned.indexOf('- name: Build installer');
const helperPackedAt = helperUnsigned.indexOf(
  '- name: Verify the packed app ships the complete creative runtime');
const helperStagePruneAt = helperUnsigned.indexOf(
  '- name: Release duplicate staging bytes before artifact acceptance');
assert.ok(helperManifestAt >= 0);
assert.ok(helperSealAt > helperManifestAt);
assert.ok(helperStageUploadAt > helperSealAt);
assert.ok(helperArchiveReleaseAt > helperStageUploadAt);
assert.ok(helperBuildAt > helperArchiveReleaseAt);
assert.ok(helperPackedAt > helperBuildAt);
assert.ok(helperStagePruneAt > helperPackedAt);
const helperStageUpload = jobSlice(
  helperUnsigned,
  '\n      - name: Upload prepared runtime to isolated signing job',
  '\n      - name: Release local signing archive before packaging');
assert.ok(helperStageUpload.includes('compression-level: 0'));
assert.ok(helperStageUpload.includes('retention-days: 1'));

// The runner context is unavailable while GitHub evaluates job-level env.
// Resolve native temp paths from RUNNER_TEMP at runtime so the workflows are
// accepted by GitHub and still build outside File Provider workspaces.
assert.ok(!workflow.includes('DESKTOP_DIST: ${{ runner.temp }}'));
assert.ok(!helperWorkflow.includes('HELPER_DIST: ${{ runner.temp }}'));
assert.ok(pseUnsigned.includes(
  'echo "DESKTOP_DIST=$RUNNER_TEMP/desktop-dist" >> "$GITHUB_ENV"'));
for (const signedJob of [pseWindows, pseMac]) {
  assert.ok(signedJob.includes(
    'echo "DESKTOP_DIST=$RUNNER_TEMP/desktop-signed-dist" >> "$GITHUB_ENV"'));
}
assert.ok(helperUnsigned.includes(
  'echo "HELPER_DIST=$RUNNER_TEMP/helper-dist" >> "$GITHUB_ENV"'));
for (const signedJob of [helperWindows, helperMac]) {
  assert.ok(signedJob.includes(
    'echo "HELPER_DIST=$RUNNER_TEMP/helper-signed-dist" >> "$GITHUB_ENV"'));
}

const helperUnsignedWindowsGate = jobSlice(
  helperUnsigned,
  '\n      - name: Smoke-test installed Windows app and signature',
  '\n      - name: Smoke-test macOS app, DMG, signing and notarization');
const helperUnsignedMacGate = jobSlice(
  helperUnsigned,
  '\n      - name: Smoke-test macOS app, DMG, signing and notarization',
  '\n      - name: Upload unsigned acceptance artifact');
const helperSignedWindowsGate = jobSlice(
  helperWindows,
  '\n      - name: Verify installed Windows signatures and exact runtime',
  '\n      - name: Upload the verified Windows candidate');
const helperSignedMacGate = jobSlice(
  helperMac,
  '\n      - name: Verify the final mounted Mac artifact',
  '\n      - name: Upload the verified Mac candidate');

// Helper ships only generic profiles. PSE and creator-specific profiles stay
// outside the friend installer even when they exist in the source tree.
const helperProfileBlock = helperUnsigned.match(
  /HELPER_PROFILES=\(\n([\s\S]*?)\n\s*\)/);
assert.ok(helperProfileBlock, 'missing Helper profile allowlist');
const stagedHelperProfiles = helperProfileBlock[1]
  .split('\n').map((line) => line.trim()).filter(Boolean);
assert.deepStrictEqual(stagedHelperProfiles, [
  'generic_short',
  'generic_long',
  'generic_commercial',
  'generic_podcast',
  'generic_course',
  'generic_custom',
]);
assert.ok(!helperUnsigned.includes('cp -R profiles/.'));
assert.ok(helperUnsigned.includes(
  'test -f "profiles/$PROFILE/profile.yaml" || {'));
assert.ok(helperUnsigned.includes(
  'Helper profile allowlist did not stage exactly'));
for (const creatorProfile of [
  'pse', 'ryan_duffy', 'ryan_humes', 'shared_skit',
]) {
  assert.ok(!stagedHelperProfiles.includes(creatorProfile));
}

// Manual acceptance jobs never receive signing or publication credentials.
// Tag-only signing jobs receive only their platform's credential family.
for (const unsignedJob of [helperUnsigned, pseUnsigned]) {
  assert.ok(!unsignedJob.includes('secrets.'));
  assert.ok(!unsignedJob.includes('GH_TOKEN'));
  assert.ok(unsignedJob.includes('CSC_IDENTITY_AUTO_DISCOVERY: false'));
  assert.ok(unsignedJob.includes('persist-credentials: false'));
}
const helperTagPushGuard =
  "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/helper-v')";
const pseTagPushGuard =
  "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/pse-v')";
for (const taggedJob of [helperWindows, helperMac]) {
  assert.ok(taggedJob.includes(helperTagPushGuard));
}
assert.ok(helperWindows.includes('environment: helper-windows-signing'));
assert.ok(helperMac.includes('environment: helper-macos-signing'));
assert.ok(!helperWindows.includes('secrets.CSC_LINK'));
assert.ok(!helperWindows.includes('APPLE_'));
assert.ok(!helperMac.includes('WIN_CSC'));
assert.ok(!helperMac.includes('WIN_AZURE'));
assert.ok(!helperMac.includes('AZURE_'));
for (const taggedJob of [pseWindows, pseMac, releaseWorkflow]) {
  assert.ok(taggedJob.includes(pseTagPushGuard));
}
assert.ok(pseWindows.includes('environment: pse-windows-signing'));
assert.ok(pseMac.includes('environment: pse-macos-signing'));
assert.ok(!pseWindows.includes('secrets.CSC_LINK'));
assert.ok(!pseWindows.includes('APPLE_'));
assert.ok(pseWindows.includes('WIN_PFX_CERT_THUMBPRINT'));
assert.ok(pseWindows.includes('Assert-ApprovedSigner'));
assert.ok(pseWindows.includes('1.3.6.1.5.5.7.3.3'));
assert.ok(pseWindows.includes(
  'signer does not match the approved PSE certificate'));
assert.ok(!pseMac.includes('WIN_CSC'));
assert.ok(!pseMac.includes('WIN_AZURE'));
assert.ok(!pseMac.includes('AZURE_'));
for (const signingJob of [helperWindows, helperMac, pseWindows, pseMac]) {
  assert.ok(signingJob.includes('needs: build'));
  assert.ok(!signingJob.includes('GH_TOKEN'));
}
assert.ok(helperPromotion.includes('workflow_dispatch:'));
assert.ok(!helperPromotion.includes('\n  push:'));
assert.ok(helperPromote.includes('environment: helper-live-release'));
assert.ok(helperPromotion.includes('\npermissions: {}\n'));
assert.ok(helperPromotionPreflight.includes('permissions: {}'));
assert.ok(!helperPromotionPreflight.includes('environment:'));
assert.ok(!helperPromotionPreflight.includes('actions/checkout'));
assert.ok(!helperPromotionPreflight.includes('contents: write'));
assert.ok(helperPromotionPreflight.includes(
  'Require dispatch from the protected default branch'));
assert.ok(helperPromotionPreflight.includes(
  'DISPATCH_REF: ${{ github.ref }}'));
assert.ok(helperPromotionPreflight.includes(
  'DISPATCH_REF_TYPE: ${{ github.ref_type }}'));
assert.ok(helperPromotionPreflight.includes(
  'DISPATCH_REF_PROTECTED: ${{ github.ref_protected }}'));
assert.ok(helperPromotionPreflight.includes(
  'DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}'));
assert.ok(helperPromotionPreflight.includes(
  'test "$DISPATCH_REF" = "$EXPECTED_REF"'));
assert.ok(helperPromotionPreflight.includes(
  'test "$DISPATCH_REF_PROTECTED" = true'));
assert.ok(helperPromote.includes('needs: preflight'));
assert.ok(helperPromote.includes(
  'permissions:\n      actions: read\n      contents: write'));
assert.ok(helperPromote.includes(
  'LIVE_WORKER_CONTRACT_URL: https://autoeditor-web.mromarmarabha.workers.dev/download/helper/runtime/contract'));
assert.ok(helperPromote.includes(
  '"schema": "autoeditor-helper-runtime-route/v2"'));
assert.ok(helperPromote.includes(
  '"release_schema": "autoeditor-helper-release/v2"'));
assert.ok(helperPromote.includes(
  '"route": "/download/helper/runtime/windows-x64/{tag}/{commit}"'));
assert.ok(helperPromote.includes('"max_package_bytes": 4_294_967_294'));
assert.ok(helperPromote.includes(
  '/r2/buckets/autoeditor-releases/lock'));
assert.ok(helperPromote.includes(
  'CLOUDFLARE_R2_LOCKS_READ_TOKEN: ${{ secrets.CLOUDFLARE_R2_LOCKS_READ_TOKEN }}'));
assert.strictEqual((helperPromotion.match(
  /secrets\.CLOUDFLARE_R2_LOCKS_READ_TOKEN/g) || []).length, 2);
assert.ok(!helperWorkflow.includes('CLOUDFLARE_R2_LOCKS_READ_TOKEN'));
assert.ok(helperPromote.includes('len(rules) != 2'));
assert.ok(helperPromote.includes('rule.get("enabled") is not True'));
assert.ok(helperPromote.includes(
  'condition.get("type") != "Indefinite"'));
assert.ok(helperPromote.includes('"dist/helper/objects/"'));
assert.ok(helperPromote.includes('"dist/helper/checksums/"'));
assert.ok(!helperPromote.includes(
  'print(os.environ["CLOUDFLARE_R2_LOCKS_READ_TOKEN"]'));
assert.ok(!helperPromote.includes('print(token)'));

// Live compatibility and immutable-storage checks are read-only and must run
// before the first R2, GitHub Release, or live-pointer mutation.
const liveContractAt = helperPromote.indexOf(
  '- name: Verify the live Worker v2 runtime contract before any mutation');
const bucketLocksAt = helperPromote.indexOf(
  '- name: Verify immutable live R2 bucket locks before any mutation');
const candidateCopyAt = helperPromote.indexOf(
  'r2-release-storage.js copy');
const checksumPutAt = helperPromote.indexOf(
  '--bucket autoeditor-releases --key "$CHECKSUM_KEY"');
const githubReleaseAt = helperPromote.indexOf('gh release create');
const livePointerAt = helperPromote.indexOf(
  '- name: Atomically expose the physically accepted release');
assert.ok(liveContractAt > 0);
assert.ok(bucketLocksAt > liveContractAt);
for (const mutationAt of [
  candidateCopyAt, checksumPutAt, githubReleaseAt, livePointerAt,
]) {
  assert.ok(mutationAt > bucketLocksAt);
}
for (const doc of [ownerSigning, launchChecklist]) {
  assert.ok(doc.includes('CLOUDFLARE_R2_LOCKS_READ_TOKEN'));
  assert.ok(doc.includes('Workers R2 Storage Read'));
  assert.ok(doc.includes('/download/helper/runtime/contract'));
}
assert.ok(releaseGateStatus.includes('CLOUDFLARE_R2_LOCKS_READ_TOKEN'));
assert.ok(helperPromote.includes('ref: ${{ inputs.expected_commit }}'));
assert.ok(helperPromote.includes('fetch-depth: 1'));
assert.ok(helperPromote.includes('git rev-parse HEAD'));
assert.ok(helperPromote.includes(
  'test "$ACTUAL_COMMIT" = "$ACCEPTED_COMMIT"'));
assert.ok(ownerSigning.includes('**Selected branches and tags**'));
assert.ok(ownerSigning.includes('only the exact protected default'));
assert.ok(ownerSigning.includes('Omar as a required reviewer'));
for (const signingSecret of [
  'CSC_LINK', 'CSC_KEY_PASSWORD', 'APPLE_ID', 'APPLE_TEAM_ID',
  'WIN_CSC_LINK', 'WIN_AZURE', 'AZURE_TENANT_ID',
  'R2_CANDIDATE_ACCESS_KEY_ID',
]) {
  assert.ok(!helperPromotion.includes(signingSecret));
}

// workflow_dispatch accepts a tag ref, so release classification and every
// secret-bearing signing/publish job must also require the push event.
const taggedPushClassifier =
  'if [[ "$GITHUB_EVENT_NAME" == "push" && "$GITHUB_REF_TYPE" == "tag" ]]; then';
assert.ok(helperUnsigned.includes(taggedPushClassifier));
assert.ok(pseUnsigned.includes(taggedPushClassifier));
assert.ok(!helperWorkflow.includes(
  "\n    if: startsWith(github.ref, 'refs/tags/helper-v')"));
assert.ok(!workflow.includes(
  "\n    if: startsWith(github.ref, 'refs/tags/pse-v')"));

// A signing tag must be created from the protected default-branch head. Live
// promotion rechecks ancestry so a later main commit does not invalidate an
// already accepted release while an unmerged release commit still fails.
for (const [unsignedJob, tagPrefix, failure] of [
  [helperUnsigned, 'helper-v', 'A Helper release tag must point'],
  [pseUnsigned, 'pse-v', 'A PSE release tag must point'],
]) {
  assert.ok(unsignedJob.includes(
    `startsWith(github.ref, 'refs/tags/${tagPrefix}')`));
  assert.ok(unsignedJob.includes('TAG_REF_PROTECTED: ${{ github.ref_protected }}'));
  assert.ok(unsignedJob.includes('test "$TAG_REF_PROTECTED" = true'));
  assert.ok(unsignedJob.includes(
    'git ls-remote --exit-code origin'));
  assert.ok(unsignedJob.includes('test "$TAG_COMMIT" = "$DEFAULT_COMMIT"'));
  assert.ok(unsignedJob.includes(failure));
}
assert.ok(helperPromote.includes(
  '"repos/$GITHUB_REPOSITORY/compare/$ACCEPTED_COMMIT...$DEFAULT_BRANCH"'));
assert.ok(helperPromote.includes('identical|ahead'));
assert.ok(helperPromote.includes(
  'Accepted release commit is not on the protected default branch'));
const helperAncestryAt = helperPromote.indexOf(
  'compare/$ACCEPTED_COMMIT...$DEFAULT_BRANCH');
const helperCandidateDownloadAt = helperPromote.indexOf(
  'actions/download-artifact@');
assert.ok(helperAncestryAt > 0);
assert.ok(helperCandidateDownloadAt > helperAncestryAt);

// A failed version regex must terminate before any output can mask its status.
const hardVersionGuard =
  '[[ "$VERSION" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || {';
assert.ok(helperUnsigned.includes(hardVersionGuard));
assert.ok(pseUnsigned.includes(hardVersionGuard));

// Tagged builds cannot publish. Repository write access exists only in the
// separate, manually dispatched, physically accepted Helper promotion.
assert.ok(helperWorkflow.includes('permissions:\n  contents: read'));
assert.ok(workflow.includes('permissions:\n  contents: read'));
assert.strictEqual((helperWorkflow.match(/contents: write/g) || []).length, 0);
assert.strictEqual((helperPromotion.match(/contents: write/g) || []).length, 1);
assert.strictEqual((workflow.match(/contents: write/g) || []).length, 1);
assert.ok(helperPromotion.includes('actions: read'));
assert.ok(releaseWorkflow.includes('contents: write'));

// Frozen engines are built only from the platform and architecture hash lock.
for (const unsignedJob of [helperUnsigned, pseUnsigned]) {
  assert.ok(unsignedJob.includes(
    'requirements-${{ matrix.target_os }}-${{ matrix.arch }}.txt'));
  assert.ok(unsignedJob.includes('python -m pip install --require-hashes'));
  assert.ok(unsignedJob.includes('python -m pip check'));
  assert.ok(!unsignedJob.includes('pip install --upgrade pip'));
  const safetyAt = unsignedJob.indexOf(
    '- name: Run safety tests against the verified platform FFmpeg');
  const ffmpegAt = unsignedJob.indexOf('Bundle verified FFmpeg and FFprobe');
  assert.ok(ffmpegAt > 0);
  assert.ok(safetyAt > ffmpegAt);
  const safetyStep = unsignedJob.slice(safetyAt,
    unsignedJob.indexOf('\n      - ', safetyAt + 8));
  assert.ok(safetyStep.includes('export AUTOEDITOR_FFMPEG="$FFMPEG"'));
  assert.ok(safetyStep.includes('export AUTOEDITOR_FFPROBE="$FFPROBE"'));
  assert.ok(safetyStep.includes('python -m unittest tests.test_safety'));
}
assert.ok(main.includes("env.PYTHONUTF8 = '1'"));
assert.ok(main.includes("env.PYTHONIOENCODING = 'utf-8'"));
assert.ok(workflow.includes('PYTHONUTF8: "1"'));
assert.ok(workflow.includes('PYTHONIOENCODING: utf-8'));
assert.ok(workflow.includes(
  '8e148d10ce8da1dca931c2f35c3a180100520bb48940f4bf1c0a3c1627467331'));
assert.ok(workflow.includes('8\\.1\\.2_1([[:space:]]|$)'));
assert.ok(workflow.includes('2d85e20401920891efb7cd6272d6339685df2820'));
assert.ok(workflow.includes(
  '0f7b311b2f3279e4eef9b2f968bcdbab6e28f4daeb1f049f4f278a902bcd82f7'));
assert.ok(!workflow.includes('/raw/master/'));

// Release assets stay private as a draft until the complete remote set and
// its checksums match. A completed rerun verifies without mutating public bits.
assert.ok(releaseWorkflow.includes('SHA256SUMS.txt'));
assert.ok(releaseWorkflow.includes('gh release create "$TAG"'));
assert.ok(releaseWorkflow.includes('--verify-tag'));
assert.ok(releaseWorkflow.includes('--draft'));
assert.ok((releaseWorkflow.match(/verify_remote_assets true/g) || []).length >= 2);
assert.ok(!releaseWorkflow.includes('verify_remote_assets false'));
assert.ok(releaseWorkflow.includes('gh release download "$TAG"'));
assert.ok(releaseWorkflow.includes('sha256sum -c SHA256SUMS.txt'));
assert.ok(releaseWorkflow.includes('--draft=false'));
const createDraftAt = releaseWorkflow.indexOf('gh release create "$TAG"');
const uploadAssetsAt = releaseWorkflow.indexOf('gh release upload "$TAG"');
const finalRemoteVerifyAt = releaseWorkflow.indexOf(
  'verify_remote_assets true', uploadAssetsAt);
const publishAt = releaseWorkflow.indexOf('--draft=false');
assert.ok(createDraftAt > 0);
assert.ok(uploadAssetsAt > createDraftAt);
assert.ok(finalRemoteVerifyAt > uploadAssetsAt);
assert.ok(publishAt > finalRemoteVerifyAt);

// Helper tags produce signed candidates only. Live publication requires a
// separate owner dispatch that binds the accepted tag, commit, run, attempt,
// receipts, and an explicit physical-acceptance checkbox.
assert.ok(!helperWorkflow.includes('\n  publish:'));
assert.ok(helperWindows.includes(
  'Upload the signed Windows candidate for physical acceptance'));
assert.ok(helperMac.includes(
  'Upload the signed Mac candidate for physical acceptance'));
assert.ok(helperWindows.includes('signed-candidate-helper-windows-x64'));
assert.ok(helperMac.includes('signed-candidate-helper-mac-${{ matrix.arch }}'));
assert.ok(helperPromotion.includes('physical_acceptance:'));
assert.ok(helperPromote.includes(
  'Bind owner acceptance to the exact successful signed-candidate run'));
assert.ok(helperPromote.includes(
  '"path": ".github/workflows/helper-release.yml"'));
assert.ok(helperPromote.includes('"event": "push"'));
assert.ok(helperPromote.includes('"conclusion": "success"'));
assert.ok(helperPromote.includes('"head_branch": os.environ["ACCEPTED_TAG"]'));
assert.ok(helperPromote.includes('"head_sha": os.environ["ACCEPTED_COMMIT"]'));
assert.ok(helperPromote.includes('run-id: ${{ inputs.build_run_id }}'));
assert.ok(helperPromote.includes('github-token: ${{ github.token }}'));
assert.ok(helperPromote.includes('--commit "$ACCEPTED_COMMIT"'));
assert.ok(helperPromote.includes('--run-id "$ACCEPTED_RUN_ID"'));
assert.ok(helperPromote.includes('--run-attempt "$ACCEPTED_RUN_ATTEMPT"'));
const helperCheckoutAt = helperPromote.indexOf(
  'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1');
const helperCheckoutVerifyAt = helperPromote.indexOf('git rev-parse HEAD');
const helperProvenanceAt = helperPromote.indexOf(
  'Bind owner acceptance to the exact successful signed-candidate run');
const helperNpmInstallAt = helperPromote.indexOf(
  'npm ci --prefix desktop --ignore-scripts');
const helperRepositoryCodeAt = helperPromote.indexOf(
  'python packaging/helper_release_metadata.py assemble');
assert.ok(helperCheckoutAt > 0);
assert.ok(helperCheckoutVerifyAt > helperCheckoutAt);
assert.ok(helperProvenanceAt > helperCheckoutVerifyAt);
assert.ok(helperNpmInstallAt > helperProvenanceAt);
assert.ok(helperRepositoryCodeAt > helperCheckoutVerifyAt);
assert.ok(helperReleaseMetadata.includes(
  '"tag", "version", "source", "checksums", "platforms",'));
assert.ok(helperReleaseMetadata.includes(
  '"release version already exists with different provenance or "'));

assert.ok(helperPromote.includes('--verify-tag --draft'));
assert.ok(helperPromote.includes(
  'python packaging/helper_release_metadata.py github-assets'));
assert.ok(helperPromote.includes(
  '--plan release-metadata/github-assets.json'));
assert.ok(helperPromote.includes(
  '> release-metadata/github-assets.nul'));
assert.ok(helperPromote.includes(
  "mapfile -d '' FILES < release-metadata/github-assets.nul"));
assert.ok(!helperPromote.includes(
  "mapfile -d '' FILES < <("));
assert.ok(!helperPromote.includes(
  "-name 'runtime-manifest-*.json'"));
assert.ok(helperReleaseMetadata.includes(
  'release contains an unreferenced or missing runtime manifest'));
assert.ok(helperReleaseMetadata.includes(
  'GitHub asset plan must contain exactly six assets'));
assert.ok(helperPromote.includes('verify_github_release'));
assert.ok(helperPromote.includes(
  'GitHub metadata assets do not exactly match the expected set'));
assert.ok(helperPromote.includes('cmp -s "$file"'));
assert.ok(helperPromote.includes('--sha256 "$CHECKSUM_SHA" --if-none-match'));
const helperDraftAt = helperPromote.indexOf(
  'gh release create "$ACCEPTED_TAG"');
const helperUploadAt = helperPromote.indexOf(
  'gh release upload "$ACCEPTED_TAG"');
const helperVerifyAt = helperPromote.indexOf(
  'verify_github_release', helperUploadAt);
const helperPublishAt = helperPromote.indexOf('--draft=false');
const helperPointerAt = helperPromote.indexOf(
  'Atomically expose the physically accepted release to private downloads');
assert.ok(helperDraftAt > 0);
assert.ok(helperUploadAt > helperDraftAt);
assert.ok(helperVerifyAt > helperUploadAt);
assert.ok(helperPublishAt > helperVerifyAt);
assert.ok(helperPointerAt > helperPublishAt);

// Every Helper artifact executes its installed or mounted frozen engine and
// proves that the normal Electron renderer can paint a real PNG. Screenshot
// setup skips only provider accounts that may be absent in CI. Remotion stays
// required and is never skipped.
const screenshotSkipBlock = jobSlice(
  helperMain,
  "\n      if (process.env.AUTOEDITOR_SCREENSHOT_SKIP_ACCOUNTS === '1') {",
  '\n      const height =');
assert.ok(screenshotSkipBlock.includes(
  "['pexels-mode', 'pixabay-mode', 'eleven-mode']"));
assert.ok(!/remotion/i.test(screenshotSkipBlock));
assert.ok(helperMain.includes(
  "const capturePath = process.env.AUTOEDITOR_SCREENSHOT_PATH || ''"));
assert.ok(helperMain.includes(
  "win.loadFile(path.join(__dirname, 'renderer', 'index.html'))"));

function assertWindowsHelperAcceptance(gate) {
  const selfTestAt = gate.indexOf('& $engine --self-test');
  const screenshotAt = gate.indexOf(
    '$env:AUTOEDITOR_SCREENSHOT_PATH = $screenshot');
  const skipAccountsAt = gate.indexOf(
    '$env:AUTOEDITOR_SCREENSHOT_SKIP_ACCOUNTS = "1"');
  const captureAt = gate.indexOf(
    '$capture = Start-Process $app -Wait -PassThru');
  const decodeAt = gate.indexOf(
    '[System.Drawing.Image]::FromStream($stream, $false, $true)');
  const validatedAt = gate.indexOf(
    '$image.Width -le 0 -or $image.Height -le 0');
  const decoderClosedAt = gate.indexOf('$stream.Dispose()');
  const smokeAt = gate.indexOf('$env:AUTOEDITOR_SMOKE_TEST = "1"');
  const uninstallAt = gate.indexOf('$remove = Start-Process $uninstaller');
  assert.ok(gate.includes(
    '$engine = Join-Path $root "resources/engine/autoeditor-engine.exe"'));
  assert.ok(gate.includes('$screenshot = Join-Path $env:RUNNER_TEMP'));
  assert.ok(gate.includes('$capture = Start-Process $app -Wait -PassThru'));
  assert.ok(gate.includes(
    'Remove-Item Env:AUTOEDITOR_SCREENSHOT_PATH -ErrorAction SilentlyContinue'));
  assert.ok(gate.includes(
    'Remove-Item Env:AUTOEDITOR_SCREENSHOT_SKIP_ACCOUNTS -ErrorAction SilentlyContinue'));
  assert.ok(gate.includes('(Get-Item $screenshot).Length -eq 0'));
  assert.ok(gate.includes('Add-Type -AssemblyName System.Drawing'));
  assert.ok(gate.includes(
    '[System.Drawing.Imaging.ImageFormat]::Png.Guid'));
  assert.ok(gate.includes('$image.Width -le 0 -or $image.Height -le 0'));
  assert.ok(gate.includes('screenshot is not a decodable PNG'));
  assert.ok(selfTestAt >= 0);
  assert.ok(screenshotAt > selfTestAt);
  assert.ok(skipAccountsAt > screenshotAt);
  assert.ok(captureAt > skipAccountsAt);
  assert.ok(decodeAt > captureAt);
  assert.ok(validatedAt > decodeAt);
  assert.ok(decoderClosedAt > validatedAt);
  assert.ok(smokeAt > decoderClosedAt);
  assert.ok(uninstallAt > smokeAt);
}

function assertMacHelperAcceptance(gate) {
  const selfTestAt = gate.indexOf(
    'Contents/Resources/engine/autoeditor-engine" --self-test');
  const screenshotAt = gate.indexOf(
    'AUTOEDITOR_SCREENSHOT_PATH="$SCREENSHOT"');
  const skipAccountsAt = gate.indexOf(
    'AUTOEDITOR_SCREENSHOT_SKIP_ACCOUNTS=1');
  const nonemptyAt = gate.indexOf('test -s "$SCREENSHOT"');
  const decodeAt = gate.indexOf('/usr/bin/sips -s format png');
  const dimensionsAt = gate.indexOf(
    'test "$WIDTH" -gt 0 && test "$HEIGHT" -gt 0');
  const smokeAt = gate.indexOf('AUTOEDITOR_SMOKE_TEST=1', skipAccountsAt);
  const manifestAt = gate.indexOf('verify_helper_manifest.py');
  const signatureAt = gate.indexOf('codesign --verify --deep --strict');
  assert.ok(gate.includes('SCREENSHOT="$RUNNER_TEMP/'));
  assert.ok(gate.includes('test -s "$SCREENSHOT"'));
  assert.ok(gate.includes('/usr/bin/sips -g pixelWidth'));
  assert.ok(gate.includes('/usr/bin/sips -g pixelHeight'));
  assert.ok(gate.includes(
    'test "$WIDTH" -gt 0 && test "$HEIGHT" -gt 0'));
  assert.ok(selfTestAt >= 0);
  assert.ok(signatureAt >= 0 && signatureAt < selfTestAt);
  assert.ok(screenshotAt > selfTestAt);
  assert.ok(skipAccountsAt > screenshotAt);
  assert.ok(nonemptyAt > skipAccountsAt);
  assert.ok(decodeAt > nonemptyAt);
  assert.ok(dimensionsAt > decodeAt);
  assert.ok(smokeAt > dimensionsAt);
  assert.ok(manifestAt > smokeAt);
}

for (const gate of [
  helperUnsignedWindowsGate,
  helperSignedWindowsGate,
]) {
  assertWindowsHelperAcceptance(gate);
}
for (const gate of [helperUnsignedMacGate, helperSignedMacGate]) {
  assertMacHelperAcceptance(gate);
}

// Installed Windows resources and the fresh mounted Mac app both validate
// target/version receipts and byte-bind product.json to staging.
assert.ok(workflow.includes('autoeditor-desktop-runtime/v1'));
assert.ok(workflow.includes('runtimeManifest'));
const windowsSmokeAt = pseUnsigned.indexOf(
  '- name: Smoke-test Windows installer');
const macSmokeAt = pseUnsigned.indexOf('- name: Smoke-test macOS app and DMG');
const artifactUploadAt = pseUnsigned.indexOf(
  '- name: Seal prepared PSE runtime', macSmokeAt);
assert.ok(windowsSmokeAt > 0);
assert.ok(macSmokeAt > windowsSmokeAt);
assert.ok(artifactUploadAt > macSmokeAt);
const windowsSmoke = pseUnsigned.slice(windowsSmokeAt, macSmokeAt);
const macSmoke = pseUnsigned.slice(macSmokeAt, artifactUploadAt);
for (const [smoke, byteBindFailure] of [
  [windowsSmoke, 'Installed product manifest is not byte-identical to staging'],
  [macSmoke, 'Mounted product manifest is not byte-identical to staging'],
]) {
  assert.ok(smoke.includes(byteBindFailure));
  assert.ok(smoke.includes('autoeditor-desktop-runtime/v1'));
  assert.ok(smoke.includes('components == actual'));
  assert.ok(smoke.includes('runtime.get("version") == version'));
  assert.ok(smoke.includes('runtime.get("target") == target'));
  assert.ok(smoke.includes('--self-test'));
}
assert.ok(pseWindows.includes('Get-AuthenticodeSignature'));
assert.ok(pseWindows.includes('components == actual'));
assert.ok(pseMac.includes('Authority=Developer ID Application'));
assert.ok(pseMac.includes('xcrun stapler validate "$DMG"'));
assert.ok(pseMac.includes('components == actual'));
assert.ok(helperWindows.includes('Get-AuthenticodeSignature'));
assert.ok(helperWindows.includes(
  'Get-ChildItem $resources -Recurse -Filter *.exe -File'));
assert.ok(helperWindows.includes(
  '$file.FullName $fileThumbprint $approvedIdentityEku'));
assert.ok(helperWindows.includes('verify_helper_manifest.py'));
assert.ok(helperMac.includes('Authority=Developer ID Application'));
assert.ok(helperMac.includes('xcrun stapler validate "$DMG"'));
assert.ok(helperMac.includes('verify_helper_manifest.py'));
assert.ok(pseWindows.includes(
  'Get-ChildItem $resources -Recurse -Filter *.exe -File'));
assert.ok(pseWindows.includes(
  'normalize_windows_executables=True'));
assert.ok(pseMac.includes(
  'runtime.get("receiptAlgorithm") == "raw-sha256-v1"'));
console.log('platform contracts ok');
