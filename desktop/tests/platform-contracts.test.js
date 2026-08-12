const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {UUID} = require('builder-util-runtime');

const readNormalized = (file) =>
  fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');

const desktop = path.resolve(__dirname, '..');
const main = fs.readFileSync(path.join(desktop, 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8');
const renderer = fs.readFileSync(
  path.join(desktop, 'renderer', 'app.js'), 'utf8');
const workflow = readNormalized(
  path.join(desktop, '..', '.github', 'workflows', 'release.yml'));
const product = fs.readFileSync(path.join(desktop, 'product.js'), 'utf8');
const legacyBuilder = fs.readFileSync(
  path.join(desktop, 'electron-builder.yml'), 'utf8');
const helperMain = fs.readFileSync(
  path.join(desktop, 'helper', 'main.js'), 'utf8');
const helperBuilder = fs.readFileSync(
  path.join(desktop, 'electron-builder.helper.yml'), 'utf8');
const helperWorkflow = readNormalized(
  path.join(desktop, '..', '.github', 'workflows', 'helper-release.yml'));
const helperPromotion = readNormalized(
  path.join(desktop, '..', '.github', 'workflows', 'helper-promote.yml'));
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
const electronChromiumProvenance = fs.readFileSync(
  path.join(desktop, '..', 'packaging',
    'stage_electron_chromium_provenance.py'), 'utf8');
const electronChromiumLock = JSON.parse(fs.readFileSync(
  path.join(desktop, '..', 'packaging',
    'electron-chromium-provenance.lock.json'), 'utf8'));
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
const remotionWindowsPruner = fs.readFileSync(
  path.join(desktop, '..', 'packaging',
    'prune_remotion_windows_runtime.py'), 'utf8');
const onnxRuntimeNodePruner = fs.readFileSync(
  path.join(desktop, '..', 'packaging',
    'prune_onnxruntime_node.py'), 'utf8');
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
assert.ok(helperBuilder.includes('appId: com.marabha.autoeditor.helper'));
const electronBuilderNamespace = UUID.parse(
  '50e065bc-3134-11e6-9bab-38c9862bdaf3');
const helperInstallGuid = UUID.v5(
  'com.marabha.autoeditor.helper', electronBuilderNamespace);
assert.strictEqual(helperInstallGuid, '35e34d8c-801d-53c1-a216-54f6187b5698');
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
  assert.match(spec, /excludes=\[[^\]]*"av"/s);
}
assert.ok(helperMain.includes('AUTOEDITOR_CREATIVE_SMOKE_TEST'));
assert.ok(helperMain.includes('spawn(p.daemon, [mode]'));
assert.ok(helperMain.includes("localProcess('--local-render'"));
assert.ok(helperMain.includes("DEEPSEEK_API_KEY: settings.deepseekApiKey || ''"));
assert.ok(!helperMain.includes('AUTOEDITOR_WEB_API:'));
assert.ok(!helperMain.includes('WORKER_TOKEN:'));
assert.ok(helperWorkflow.includes('windows-2022'));
assert.ok(!helperWorkflow.includes('macos-15-intel'));
assert.ok(helperWorkflow.includes(
  'Package and smoke-test the Windows x64 portable build'));
assert.ok(helperWorkflow.includes('*-portable.zip'));
assert.ok(helperWorkflow.includes('Render real HyperFrames and Remotion probes'));
assert.ok(helperWorkflow.includes('STAGE=$(realpath "$STAGE")'));
assert.ok(helperWorkflow.includes(
  '"$NODE" "$STAGE/creative-runtime/node_modules/hyperframes/bin/hyperframes.mjs"'));
assert.ok(!helperWorkflow.includes('"$GITHUB_WORKSPACE/$STAGE/creative-runtime'));
assert.ok(helperWorkflow.includes(
  'stage_electron_chromium_provenance.py stage'));
assert.ok(helperWorkflow.includes(
  'stage_electron_chromium_provenance.py verify'));
assert.ok(helperWorkflow.includes('--product helper'));
assert.ok(helperWorkflow.includes('--browser-dir "$STAGE/browser"'));
assert.ok(helperWorkflow.includes(
  '--electron-dist-dir "$RUNNER_TEMP/electron-dist"'));
assert.ok(!helperWorkflow.includes('browser ensure'));
assert.strictEqual(
  (helperWorkflow.match(/npx (?:--no-install )?electron-builder /g) || []).length,
  4);
assert.strictEqual(
  (helperWorkflow.match(
    /--config\.electronDist="\$RUNNER_TEMP\/electron-dist"/g) || []).length,
  4);
assert.strictEqual(
  (helperWorkflow.match(
    /stage_electron_chromium_provenance\.py electron-dist/g) || []).length,
  2);
const helperProvenanceStageAt = helperWorkflow.indexOf(
  'stage_electron_chromium_provenance.py stage');
const helperRenderProbeAt = helperWorkflow.indexOf(
  '- name: Render real HyperFrames and Remotion probes');
const helperProvenanceVerifyAt = helperWorkflow.indexOf(
  'stage_electron_chromium_provenance.py verify');
const helperManifestGenerationAt = helperWorkflow.indexOf(
  'python packaging/generate_helper_manifest.py');
assert.ok(helperProvenanceStageAt >= 0);
assert.ok(helperRenderProbeAt > helperProvenanceStageAt);
assert.ok(helperProvenanceVerifyAt > helperRenderProbeAt);
assert.ok(helperManifestGenerationAt > helperProvenanceVerifyAt);
assert.ok(workflow.includes('Stage hash-locked Electron and Chromium notices'));
assert.ok(workflow.includes('stage_electron_chromium_provenance.py stage'));
assert.ok(workflow.includes('stage_electron_chromium_provenance.py verify'));
assert.ok(workflow.includes('--product pse'));
assert.ok(workflow.includes(
  '--electron-dist-dir "$RUNNER_TEMP/electron-dist"'));
assert.strictEqual(
  (workflow.match(/npx (?:--no-install )?electron-builder /g) || []).length,
  3);
assert.strictEqual(
  (workflow.match(
    /--config\.electronDist="\$RUNNER_TEMP\/electron-dist"/g) || []).length,
  3);
assert.strictEqual(
  (workflow.match(
    /stage_electron_chromium_provenance\.py electron-dist/g) || []).length,
  2);
const pseProvenanceStageAt = workflow.indexOf(
  'stage_electron_chromium_provenance.py stage');
const pseProvenanceVerifyAt = workflow.indexOf(
  'stage_electron_chromium_provenance.py verify');
const pseManifestGenerationAt = workflow.indexOf(
  '- name: Generate byte-verifiable product runtime manifest');
assert.ok(pseProvenanceStageAt >= 0);
assert.ok(pseProvenanceVerifyAt > pseProvenanceStageAt);
assert.ok(pseManifestGenerationAt > pseProvenanceStageAt);
assert.ok(pseProvenanceVerifyAt > pseManifestGenerationAt);
assert.ok(electronChromiumProvenance.includes(
  'Electron npm package SHA-512 integrity drifted'));
assert.ok(electronChromiumProvenance.includes(
  'Chrome Headless Shell archive'));
assert.ok(electronChromiumProvenance.includes(
  'def prepare_electron_distribution('));
assert.ok(electronChromiumProvenance.includes(
  'retained Electron binary archive'));
assert.ok(electronChromiumProvenance.includes('os.O_EXCL'));
assert.strictEqual(electronChromiumLock.provenance_status, 'complete');
assert.strictEqual(electronChromiumLock.electron.version, '43.3.0');
assert.strictEqual(electronChromiumLock.electron.source.commit,
  '1aa21d231aeaf5634880a6e60187256e9f2fd4f9');
assert.strictEqual(electronChromiumLock.electron.chromium.commit,
  '69bf1c67cb894365d151bd020bb0171fd583633a');
assert.strictEqual(electronChromiumLock.chrome_headless_shell.version,
  '152.0.7928.2');
assert.strictEqual(electronChromiumLock.chrome_headless_shell.source.commit,
  '8e122fd6ce1b7bb7bcef0fd0b2e96018ff110c4d');
for (const product of ['electron', 'chrome_headless_shell']) {
  assert.deepStrictEqual(Object.keys(electronChromiumLock[product].archives).sort(),
    ['mac-arm64', 'mac-x64', 'windows-x64']);
  assert.ok(Object.values(electronChromiumLock[product].archives).every(
    (archive) => /^[0-9a-f]{64}$/.test(archive.sha256)));
}
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
  'uses: ./.github/workflows/windows-ffmpeg.yml'));
assert.ok(helperWorkflow.includes(
  'artifact-ids: ${{ needs.windows_ffmpeg.outputs.artifact_id }}'));
assert.ok(helperWorkflow.includes('verify_windows_ffmpeg.py verify-receipt'));
assert.ok(helperWorkflow.includes('verify_windows_ffmpeg.py assert-promotable'));
assert.ok(!helperWorkflow.includes('BtbN'));
assert.ok(!helperWorkflow.includes('FFMPEG-GPL-3.0.txt'));
assert.ok(workflow.includes('FFMPEG-GPL-3.0.txt'));
for (const releaseSource of [workflow, helperWorkflow]) {
  assert.ok(releaseSource.includes('FFMPEG_FORMULAE.txt'));
  assert.ok(releaseSource.includes('verify_macos_ffmpeg_formulae.py'));
  assert.ok(releaseSource.includes(
    'macos-ffmpeg-formulae-${{ matrix.arch }}.txt'));
  assert.ok(releaseSource.includes(
    'done < "$STAGE/licenses/FFMPEG_FORMULAE.txt"'));
  assert.ok(releaseSource.includes('brew fetch --force "$FORMULA"'));
  assert.ok(releaseSource.includes('HOMEBREW_NO_AUTO_UPDATE=1'));
  assert.ok(releaseSource.includes('HOMEBREW_NO_INSTALL_CLEANUP=1'));
  assert.ok(releaseSource.includes('BREW_VERSION=$(brew --version)'));
  assert.ok(releaseSource.includes(
    'test "${BREW_VERSION%%$\'\\n\'*}" = \'Homebrew 6.0.12\''));
  assert.ok(releaseSource.indexOf('HOMEBREW_NO_AUTO_UPDATE=1') <
   ×]6òÚ$z{-®éÜj×æ–æ6ÇVFW2‚v6öçFVçG3¢w&—FRr’“°Ð Ð¢òòg&÷¦VâVæv–æW2&R'V–ÇBöæÇ’g&öÒF†RÆFf÷&ÒæB&6†—FV7GW&R†6‚Æö6²àÐ¦f÷"†6öç7B·Vç6–væVD¦ö"Âff×Vu7FWÒöb°Ð¢¶†VÇW%Vç6–væVBÂu7FvR66WFVB6÷W&6RÖ'V–ÇBv–æF÷w2df×VruÒÀÐ¢·6UVç6–væVBÂt'VæFÆRfW&–f–VBdf×VræBdg&ö&RuÒÀÐ¥Ò’°Ð¢76W'Bæö²‡Vç6–væVD¦ö"æ–æ6ÇVFW2€Ð¢w&WV—&VÖVçG2ÒG·²ÖG&—‚çF&vWEö÷2×ÒÒG·²ÖG&—‚æ&6‚×ÒçG‡Br’“°Ð¢76W'Bæö²‡Vç6–væVD¦ö"æ–æ6ÇVFW2‚w—F†öâÖÒ—–ç7FÆÂÒ×&WV—&RÖ†6†W2r’“°Ð¢76W'Bæö²‡Vç6–væVD¦ö"æ–æ6ÇVFW2‚w—F†öâÖÒ—6†V6²r’“°Ð¢76W'Bæö²‚Vç6–væVD¦ö"æ–æ6ÇVFW2‚w—–ç7FÆÂÒ×Ww&FR—r’“°Ð¢6öç7B6fWG”BÒVç6–væVD¦ö"æ–æFW„öb€Ð¢rÒæÖS¢'Vâ6fWG’FW7G2v–ç7BF†RfW&–f–VBÆFf÷&Òdf×Vrr“°Ð¢6öç7Bff×VtBÒVç6–væVD¦ö"æ–æFW„öb†ff×Vu7FW“°Ð¢6öç7BFW6·F÷–ç7FÆÄBÒVç6–væVD¦ö"æ–æFW„öb‚vçÒ6’Ò×&Vf—‚FW6·F÷r“°Ð¢76W'Bæö²†ff×VtBâ“°Ð¢76W'Bæö²†FW6·F÷–ç7FÆÄBâff×VtB“°Ð¢76W'Bæö²‡6fWG”BâFW6·F÷–ç7FÆÄB“°Ð¢76W'Bæö²‡6fWG”Bâff×VtB“°Ð¢6öç7B6fWG•7FWÒVç6–væVD¦ö"ç6Æ–6R‡6fWG”BÀÐ¢Vç6–væVD¦ö"æ–æFW„öb‚uÆâÒrÂ6fWG”B²‚’“°Ð¢76W'Bæö²‡6fWG•7FWæ–æ6ÇVFW2‚vW‡÷'BUDôTD•Dõ%ôddÕTsÒ"DddÕTr"r’“°Ð¢76W'Bæö²‡6fWG•7FWæ–æ6ÇVFW2‚vW‡÷'BUDôTD•Dõ%ôde$ô$SÒ"Dde$ô$R"r’“°Ð¢76W'Bæö²‡6fWG•7FWæ–æ6ÇVFW2‚w—F†öâÖÒVæ—GFW7BFW7G2çFW7E÷6fWG’r’“°Ð§ÐÐ¦76W'Bæö²†Ö–âæ–æ6ÇVFW2‚&Vçbå•D„ôåUDc‚Òsr"’“°Ð¦76W'Bæö²†Ö–âæ–æ6ÇVFW2‚&Vçbå•D„ôä”ôTä4ôD”ärÒwWFbÓ‚r"’“°Ð¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2‚u•D„ôåUDcƒ¢#"r’“°Ð¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2‚u•D„ôä”ôTä4ôD”äs¢WFbÓ‚r’“°Ð¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2€Ð¢s†SC†C6S†FF6“33&c3V36ƒS#&#Cƒ“CcF&c363c#sCcs33r’“°Ð¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2‚s…ÅÂãÅÂã%ó…µ³§76S¥Õ×ÂB’r’“°Ð¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2‚s&CƒVS#C“#ƒ“Vf#v6Cc#s&Cc33“cƒVFc#ƒ#r’“°Ð¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2€Ð¢scv#3#&c3#s–SFVVc–#&c“c†&6F&#fS#†cFFV#cC–cFc#s†“&&6Cƒ&crr’“°Ð¦76W'Bæö²‚v÷&¶fÆ÷ræ–æ6ÇVFW2‚r÷&röÖ7FW"òr’“°Ð Ð¢òò&VÆV6R76WG27F’&—fFR2G&gBVçF–ÂF†R6ö×ÆWFR&VÖ÷FR6WBæ@Ð¢òò—G26†V6·7V×2ÖF6‚â6ö×ÆWFVB&W'VâfW&–f–W2v—F†÷WB×WFF–ærV&Æ–2&—G2àÐ¦76W'Bæö²‡&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚u4„#Se5TÕ2çG‡Br’“°Ð¦76W'Bæö²‡&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚vv‚&VÆV6R7&VFR"EDr"r’“°Ð¦76W'Bæö²‡&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚rÒ×fW&–g’×Frr’“°Ð¦76W'Bæö²‡&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚rÒÖG&gBr’“°Ð¦76W'Bæö²‚‡&VÆV6Uv÷&¶fÆ÷ræÖF6‚‚÷fW&–g•÷&VÖ÷FUö76WG2G'VRör’ÇÂµÒ’æÆVæwF‚ãÒ"“°Ð¦76W'Bæö²‚&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚wfW&–g•÷&VÖ÷FUö76WG2fÇ6Rr’“°Ð¦76W'Bæö²‡&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚vv‚&VÆV6RF÷væÆöB"EDr"r’“°Ð¦76W'Bæö²‡&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚w6†#Sg7VÒÖ24„#Se5TÕ2çG‡Br’“°Ð¦76W'Bæö²‡&VÆV6Uv÷&¶fÆ÷ræ–æ6ÇVFW2‚rÒÖG&gCÖfÇ6Rr’“°Ð¦6öç7B7&VFTG&gDBÒ&VÆV6Uv÷&¶fÆ÷ræ–æFW„öb‚vv‚&VÆV6R7&VFR"EDr"r“°Ð¦6öç7BWÆöD76WG4BÒ&VÆV6Uv÷&¶fÆ÷ræ–æFW„öb‚vv‚&VÆV6RWÆöB"EDr"r“°Ð¦6öç7Bf–æÅ&VÖ÷FUfW&–g”BÒ&VÆV6Uv÷&¶fÆ÷ræ–æFW„öb€Ð¢wfW&–g•÷&VÖ÷FUö76WG2G'VRrÂWÆöD76WG4B“°Ð¦6öç7BV&Æ—6„BÒ&VÆV6Uv÷&¶fÆ÷ræ–æFW„öb‚rÒÖG&gCÖfÇ6Rr“°Ð¦76W'Bæö²†7&VFTG&gDBâ“°Ð¦76W'Bæö²‡WÆöD76WG4Bâ7&VFTG&gDB“°Ð¦76W'Bæö²†f–æÅ&VÖ÷FUfW&–g”BâWÆöD76WG4B“°Ð¦76W'Bæö²‡V&Æ—6„Bâf–æÅ&VÖ÷FUfW&–g”B“°Ð Ð¢òò†VÇW"Fw2&öGV6R6–væVB6æF–FFW2öæÇ’âÆ—fRV&Æ–6F–öâ&WV—&W2Ð¢òò6W&FR÷væW"F—7F6‚F†B&–æG2F†R66WFVBFrÂ6öÖÖ—BÂ'VâÂGFV×BÀÐ¢òò&V6V—G2ÂæBâW‡Æ–6—B‡—6–6ÂÖ66WFæ6R6†V6¶&÷‚àÐ¦76W'Bæö²‚†VÇW%v÷&¶fÆ÷ræ–æ6ÇVFW2‚uÆâV&Æ—6ƒ¢r’“°Ð¦76W'Bæö²††VÇW%v–æF÷w2æ–æ6ÇVFW2€Ð¢uWÆöBF†R6–væVBv–æF÷w26æF–FFRf÷"‡—6–6Â66WFæ6Rr’“°Ð¦76W'Bæö²††VÇW$Ö2æ–æ6ÇVFW2€Ð¢uWÆöBF†R6–væVBÖ26æF–FFRf÷"‡—6–6Â66WFæ6Rr’“°Ð¦76W'Bæö²††VÇW%v–æF÷w2æ–æ6ÇVFW2‚w6–væVBÖ6æF–FFRÖ†VÇW"×v–æF÷w2×ƒcBr’“°Ð¦76W'Bæö²††VÇW$Ö2æ–æ6ÇVFW2‚w6–væVBÖ6æF–FFRÖ†VÇW"ÖÖ2ÒG·²ÖG&—‚æ&6‚×Òr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷F–öâæ–æ6ÇVFW2‚w‡—6–6Åö66WFæ6S¢r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢t&–æB÷væW"66WFæ6RFòF†RW†7B7V66W76gVÂ6–væVBÖ6æF–FFR'Vâr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢r'F‚#¢"æv—F‡V"÷v÷&¶fÆ÷w2ö†VÇW"×&VÆV6Rç–ÖÂ"r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚r&WfVçB#¢'W6‚"r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚r&6öæ6ÇW6–öâ#¢'7V66W72"r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚r&†VEö'&æ6‚#¢÷2æVçf—&öå²$44UDTEõDr%Òr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚r&†VE÷6†#¢÷2æVçf—&öå²$44UDTEô4ôÔÔ•B%Òr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚w'VâÖ–C¢G·²–çWG2æ'V–ÆE÷'Våö–B×Òr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚vv—F‡V"×Fö¶Vã¢G·²v—F‡V"çFö¶Vâ×Òr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚rÒÖ6öÖÖ—B"D44UDTEô4ôÔÔ•B"r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚rÒ×'VâÖ–B"D44UDTEõ%Tåô”B"r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚rÒ×'VâÖGFV×B"D44UDTEõ%TåôEDTÕB"r’“°Ð¦6öç7B†VÇW$6†V6¶÷WDBÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢v7F–öç2ö6†V6¶÷WD6C63C&SV3V&ƒSƒ#VFscC3ƒ#s6&“#r“°Ð¦6öç7B†VÇW$6†V6¶÷WEfW&–g”BÒ†VÇW%&öÖ÷FRæ–æFW„öb‚vv—B&Wb×'6R„TBr“°Ð¦6öç7B†VÇW%&÷fVææ6TBÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢t&–æB÷væW"66WFæ6RFòF†RW†7B7V66W76gVÂ6–væVBÖ6æF–FFR'Vâr“°Ð¦6öç7B†VÇW$çÔ–ç7FÆÄBÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢vçÒ6’Ò×&Vf—‚FW6·F÷ÒÖ–væ÷&R×67&—G2r“°Ð¦6öç7B†VÇW%&W÷6—F÷'”6öFTBÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢w—F†öâ6¶v–ærö†VÇW%÷&VÆV6UöÖWFFFç’76VÖ&ÆRr“°Ð¦76W'Bæö²††VÇW$6†V6¶÷WDBâ“°Ð¦76W'Bæö²††VÇW$6†V6¶÷WEfW&–g”Bâ†VÇW$6†V6¶÷WDB“°Ð¦76W'Bæö²††VÇW%&÷fVææ6TBâ†VÇW$6†V6¶÷WEfW&–g”B“°Ð¦76W'Bæö²††VÇW$çÔ–ç7FÆÄBâ†VÇW%&÷fVææ6TB“°Ð¦76W'Bæö²††VÇW%&W÷6—F÷'”6öFTBâ†VÇW$6†V6¶÷WEfW&–g”B“°Ð¦76W'Bæö²††VÇW%&VÆV6TÖWFFFæ–æ6ÇVFW2€Ð¢r'Fr"Â'fW'6–öâ"Â'6÷W&6R"Â&6†V6·7V×2"Â'ÆFf÷&×2"Âr’“°Ð¦76W'Bæö²††VÇW%&VÆV6TÖWFFFæ–æ6ÇVFW2€Ð¢r'&VÆV6RfW'6–öâÇ&VG’W†—7G2v—F‚F–ffW&VçB&÷fVææ6R÷""r’“°Ð Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚rÒ×fW&–g’×FrÒÖG&gBr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢w—F†öâ6¶v–ærö†VÇW%÷&VÆV6UöÖWFFFç’v—F‡V"Ö76WG2r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢rÒ×Æâ&VÆV6RÖÖWFFFöv—F‡V"Ö76WG2æ§6öâr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢sâ&VÆV6RÖÖWFFFöv—F‡V"Ö76WG2æçVÂr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢&Öf–ÆRÖBrrd”ÄU2Â&VÆV6RÖÖWFFFöv—F‡V"Ö76WG2æçVÂ"’“°Ð¦76W'Bæö²‚†VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢&Öf–ÆRÖBrrd”ÄU2ÂÂ‚"’“°Ð¦76W'Bæö²‚†VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢"ÖæÖRw'VçF–ÖRÖÖæ–fW7BÒ¢æ§6öâr"’“°Ð¦76W'Bæö²††VÇW%&VÆV6TÖWFFFæ–æ6ÇVFW2€Ð¢w&VÆV6R6öçF–ç2âVç&VfW&Væ6VB÷"Ö—76–ær'VçF–ÖRÖæ–fW7Br’“°Ð¦76W'Bæö²††VÇW%&VÆV6TÖWFFFæ–æ6ÇVFW2€Ð¢tv—D‡V"76WBÆâ×W7B6öçF–âW†7FÇ’6—‚76WG2r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚wfW&–g•öv—F‡V%÷&VÆV6Rr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2€Ð¢tv—D‡V"ÖWFFF76WG2Fòæ÷BW†7FÇ’ÖF6‚F†RW‡V7FVB6WBr’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚v6××2"Ff–ÆR"r’“°Ð¦76W'Bæö²††VÇW%&öÖ÷FRæ–æ6ÇVFW2‚rÒ×6†#Sb"D4„T4µ5TÕõ4„"ÒÖ–bÖæöæRÖÖF6‚r’“°Ð¦6öç7B†VÇW$G&gDBÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢vv‚&VÆV6R7&VFR"D44UDTEõDr"r“°Ð¦6öç7B†VÇW%WÆöDBÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢vv‚&VÆV6RWÆöB"D44UDTEõDr"r“°Ð¦6öç7B†VÇW%fW&–g”BÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢wfW&–g•öv—F‡V%÷&VÆV6RrÂ†VÇW%WÆöDB“°Ð¦6öç7B†VÇW%V&Æ—6„BÒ†VÇW%&öÖ÷FRæ–æFW„öb‚rÒÖG&gCÖfÇ6Rr“°Ð¦6öç7B†VÇW%ö–çFW$BÒ†VÇW%&öÖ÷FRæ–æFW„öb€Ð¢tFöÖ–6ÆÇ’W‡÷6RF†R‡—6–6ÆÇ’66WFVB&VÆV6RFò&—fFRF÷væÆöG2r“°Ð¦76W'Bæö²††VÇW$G&gDBâ“°Ð¦76W'Bæö²††VÇW%WÆöDBâ†VÇW$G&gDB“°Ð¦76W'Bæö²††VÇW%fW&–g”Bâ†VÇW%WÆöDB“°Ð¦76W'Bæö²††VÇW%V&Æ—6„Bâ†VÇW%fW&–g”B“°Ð¦76W'Bæö²††VÇW%ö–çFW$Bâ†VÇW%V&Æ—6„B“°Ð Ð¢òòWfW'’†VÇW"'F–f7BW†V7WFW2—G2–ç7FÆÆVB÷"Ö÷VçFVBg&÷¦VâVæv–æRæ@Ð¢òò&÷fW2F†BF†Ræ÷&ÖÂÆö6ÂÖöæÇ’VÆV7G&öâ&VæFW&W"6â–çB&VÂäràÐ¢òòF†R67&VVç6†÷BFöW2æ÷BæVVB&÷f–FW"66÷VçG2&V6W6RF†RÆö6ÂVF—F÷ Ð¢òò÷Vç2v—F†÷WBvV'6—FR6öææV7F–öâ÷"6WGW6öFRàÐ¦76W'Bæö²††VÇW$Ö–âæ–æ6ÇVFW2€Ð¢&6öç7B6GW&UF‚Ò&ö6W72æVçbäUDôTD•Dõ%õ45$TTå4„õEõD‚ÇÂrr"’“°Ð¦76W'Bæö²‚†VÇW$Ö–âæ–æ6ÇVFW2‚tUDôTD•Dõ%õ45$TTå4„õEõ4´•ô44õTåE2r’“°Ð¦76W'Bæö²††VÇW$Ö–âæ–æ6ÇVFW2€Ð¢'v–âæÆöDf–ÆR‡F‚æ¦ö–â…õöF—&æÖRÂw&VæFW&W"rÂv–æFW‚æ‡FÖÂr’’"’“°Ð Ð¦gVæ7F–öâ76W'Ev–æF÷w4†VÇW$66WFæ6R†vFR’°Ð¢6öç7BÖæ–fW7DBÒvFRæ–æFW„öb‚wfW&–g•ö†VÇW%öÖæ–fW7Bç’r“°Ð¢6öç7BÖæ–fW7DW†—DBÒvFRæ–æFW„öb€Ð¢w'VçF–ÖRÖæ–fW7BfW&–f–6F–öâf–ÆVBrÂÖæ–fW7DB“°Ð¢6öç7B6VÆeFW7DBÒvFRæ–æFW„öb‚rbFVæv–æRÒ×6VÆb×FW7Br“°Ð¢6öç7B67&VVç6†÷DBÒvFRæ–æFW„öb€Ð¢rFVçc¤UDôTD•Dõ%õ45$TTå4„õEõD‚ÒG67&VVç6†÷Br“°Ð¢6öç7B6¶—66÷VçG4BÒvFRæ–æFW„öb€Ð¢rFVçc¤UDôTD•Dõ%õ45$TTå4„õEõ4´•ô44õTåE2Ò#"r“°Ð¢6öç7B6GW&TBÒvFRæ–æFW„öb€Ð¢rF6GW&RÒ7F'BÕ&ö6W72FÕv—BÕ75F‡'Rr“°Ð¢6öç7BFV6öFTBÒvFRæ–æFW„öb€Ð¢uµ7—7FVÒäG&v–ærä–ÖvUÓ£¤g&öÕ7G&VÒ‚G7G&VÒÂFfÇ6RÂGG'VR’r“°Ð¢6öç7BfÆ–FFVDBÒvFRæ–æFW„öb€Ð¢rF–ÖvRåv–GF‚ÖÆRÖ÷"F–ÖvRä†V–v‡BÖÆRr“°Ð¢6öç7BFV6öFW$6Æ÷6VDBÒvFRæ–æFW„öb‚rG7G&VÒäF—7÷6R‚’r“°Ð¢6öç7B6Öö¶TBÒvFRæ–æFW„öb‚rFVçc¤UDôTD•Dõ%õ4Ôô´UõDU5BÒ#"r“°Ð¢6öç7BVæ–ç7FÆÄBÒvFRæ–æFW„öb‚rG&VÖ÷fRÒ7F'BÕ&ö6W72GVæ–ç7FÆÆW"r“°Ð¢6öç7B&Vv—7G'”BÒvFRæ–æFW„öb€Ð¢t„´5S¥ÅÅ6ögGv&UÅÃ3VS3FC†2ÓƒBÓS63Ö#bÓSFccƒv#Sc“‚r“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢rFVæv–æRÒ¦ö–âÕF‚G&ö÷B'&W6÷W&6W2öVæv–æRöWFöVF—F÷"ÖVæv–æRæW†R"r’“°Ð¢76W'Bæö²‡&Vv—7G'”BãÒ“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢rÔÆ—FW&ÅF‚F–ç7FÆÅ&Vv—7G'”¶W’ÔæÖR–ç7FÆÄÆö6F–öâr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢uµ7—7FVÒä”òåF…Ó£¤vWE&VÆF—fUF‚‚G&öw&×5&ö÷BÂG&ö÷B’r’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚v÷WG6–FRW"×W6W"&öw&×2r’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢rÖ÷"…FW7BÕF‚ÔÆ—FW&ÅF‚F–ç7FÆÅ&Vv—7G'”¶W’’r’“°Ð¢76W'Bæö²‚vFRæ–æ6ÇVFW2‚u&öw&×2ôWFôVF—F÷"†VÇW"r’“°Ð¢76W'Bæö²†Öæ–fW7DBâ&Vv—7G'”B“°Ð¢76W'Bæö²†Öæ–fW7DW†—DBâÖæ–fW7DB“°Ð¢76W'Bæö²†vFRç6Æ–6R†Öæ–fW7DBÂÖæ–fW7DW†—DB’æ–æ6ÇVFW2€Ð¢rDÄ5DU„•D4ôDRÖæRr’“°Ð¢76W'Bæö²‡6VÆeFW7DBâÖæ–fW7DW†—DB“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚rG67&VVç6†÷BÒ¦ö–âÕF‚FVçc¥%TääU%õDTÕr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚rF6GW&RÒ7F'BÕ&ö6W72FÕv—BÕ75F‡'Rr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢u&VÖ÷fRÔ—FVÒVçc¤UDôTD•Dõ%õ45$TTå4„õEõD‚ÔW'&÷$7F–öâ6–ÆVçFÇ”6öçF–çVRr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢u&VÖ÷fRÔ—FVÒVçc¤UDôTD•Dõ%õ45$TTå4„õEõ4´•ô44õTåE2ÔW'&÷$7F–öâ6–ÆVçFÇ”6öçF–çVRr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚r„vWBÔ—FVÒG67&VVç6†÷B’äÆVæwF‚ÖWr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚tFBÕG—RÔ76VÖ&Ç”æÖR7—7FVÒäG&v–ærr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢uµ7—7FVÒäG&v–ærä–Öv–ærä–ÖvTf÷&ÖEÓ£¥æräwV–Br’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚rF–ÖvRåv–GF‚ÖÆRÖ÷"F–ÖvRä†V–v‡BÖÆRr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚w67&VVç6†÷B—2æ÷BFV6öF&ÆRärr’“°Ð¢76W'Bæö²‡67&VVç6†÷DBâ6VÆeFW7DB“°Ð¢76W'Bæö²‡6¶—66÷VçG4Bâ67&VVç6†÷DB“°Ð¢76W'Bæö²†6GW&TBâ6¶—66÷VçG4B“°Ð¢76W'Bæö²†FV6öFTBâ6GW&TB“°Ð¢76W'Bæö²‡fÆ–FFVDBâFV6öFTB“°Ð¢76W'Bæö²†FV6öFW$6Æ÷6VDBâfÆ–FFVDB“°Ð¢76W'Bæö²‡6Öö¶TBâFV6öFW$6Æ÷6VDB“°Ð¢76W'Bæö²‡Væ–ç7FÆÄBâ6Öö¶TB“°Ð§ÐÐ Ð¦gVæ7F–öâ76W'DÖ4†VÇW$66WFæ6R†vFR’°Ð¢6öç7B6VÆeFW7DBÒvFRæ–æFW„öb€Ð¢t6öçFVçG2õ&W6÷W&6W2öVæv–æRöWFöVF—F÷"ÖVæv–æR"Ò×6VÆb×FW7Br“°Ð¢6öç7B67&VVç6†÷DBÒvFRæ–æFW„öb€Ð¢tUDôTD•Dõ%õ45$TTå4„õEõDƒÒ"E45$TTå4„õB"r“°Ð¢6öç7B6¶—66÷VçG4BÒvFRæ–æFW„öb€Ð¢tUDôTD•Dõ%õ45$TTå4„õEõ4´•ô44õTåE3Ór“°Ð¢6öç7BæöæV×G”BÒvFRæ–æFW„öb‚wFW7B×2"E45$TTå4„õB"r“°Ð¢6öç7BFV6öFTBÒvFRæ–æFW„öb‚r÷W7"ö&–â÷6—2×2f÷&ÖBærr“°Ð¢6öç7BF–ÖVç6–öç4BÒvFRæ–æFW„öb€Ð¢wFW7B"Et”ED‚"ÖwBbbFW7B"D„T”t…B"ÖwBr“°Ð¢6öç7B6Öö¶TBÒvFRæ–æFW„öb‚tUDôTD•Dõ%õ4Ôô´UõDU5CÓrÂ6¶—66÷VçG4B“°Ð¢6öç7BÖæ–fW7DBÒvFRæ–æFW„öb‚wfW&–g•ö†VÇW%öÖæ–fW7Bç’r“°Ð¢6öç7B6–væGW&TBÒvFRæ–æFW„öb‚v6öFW6–vâÒ×fW&–g’ÒÖFVWÒ×7G&–7Br“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚u45$TTå4„õCÒ"E%TääU%õDTÕòr’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚wFW7B×2"E45$TTå4„õB"r’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚r÷W7"ö&–â÷6—2Ör—†VÅv–GF‚r’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2‚r÷W7"ö&–â÷6—2Ör—†VÄ†V–v‡Br’“°Ð¢76W'Bæö²†vFRæ–æ6ÇVFW2€Ð¢wFW7B"Et”ED‚"ÖwBbbFW7B"D„T”t…B"ÖwBr’“°Ð¢76W'Bæö²‡6VÆeFW7DBãÒ“°Ð¢76W'Bæö²‡6–væGW&TBãÒbb6–væGW&TBÂ6VÆeFW7DB“°Ð¢76W'Bæö²‡67&VVç6†÷DBâ6VÆeFW7DB“°Ð¢76W'Bæö²‡6¶—66÷VçG4Bâ67&VVç6†÷DB“°Ð¢76W'Bæö²†æöæV×G”Bâ6¶—66÷VçG4B“°Ð¢76W'Bæö²†FV6öFTBâæöæV×G”B“°Ð¢76W'Bæö²†F–ÖVç6–öç4BâFV6öFTB“°Ð¢76W'Bæö²‡6Öö¶TBâF–ÖVç6–öç4B“°Ð¢76W'Bæö²†Öæ–fW7DBâ6Öö¶TB“°Ð§ÐÐ Ð¦f÷"†6öç7BvFRöb°Ð¢†VÇW%Vç6–væVEv–æF÷w4vFRÀÐ¢†VÇW%6–væVEv–æF÷w4vFRÀÐ¥Ò’°Ð¢76W'Ev–æF÷w4†VÇW$66WFæ6R†vFR“°Ð§ÐÐ¦f÷"†6öç7BvFRöb¶†VÇW%Vç6–væVDÖ4vFRÂ†VÇW%6–væVDÖ4vFUÒ’°Ð¢76W'DÖ4†VÇW$66WFæ6R†vFR“°Ð§ÐÐ Ð¢òò–ç7FÆÆVBv–æF÷w2&W6÷W&6W2æBF†Rg&W6‚Ö÷VçFVBÖ2&÷F‚fÆ–FFPÐ¢òòF&vWB÷fW'6–öâ&V6V—G2æB'—FRÖ&–æB&öGV7Bæ§6öâFò7Fv–æràÐ¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2‚vWFöVF—F÷"ÖFW6·F÷×'VçF–ÖR÷cr’“°Ð¦76W'Bæö²‡v÷&¶fÆ÷ræ–æ6ÇVFW2‚w'VçF–ÖTÖæ–fW7Br’“°Ð¦6öç7Bv–æF÷w56Öö¶TBÒ6UVç6–væVBæ–æFW„öb€Ð¢rÒæÖS¢6Öö¶R×FW7Bv–æF÷w2–ç7FÆÆW"r“°Ð¦6öç7BÖ56Öö¶TBÒ6UVç6–væVBæ–æFW„öb‚rÒæÖS¢6Öö¶R×FW7BÖ4õ2æBDÔrr“°Ð¦6öç7B'F–f7EWÆöDBÒ6UVç6–væVBæ–æFW„öb€Ð¢rÒæÖS¢6VÂ&W&VB4R'VçF–ÖRrÂÖ56Öö¶TB“°Ð¦76W'Bæö²‡v–æF÷w56Öö¶TBâ“°Ð¦76W'Bæö²†Ö56Öö¶TBâv–æF÷w56Öö¶TB“°Ð¦76W'Bæö²†'F–f7EWÆöDBâÖ56Öö¶TB“°Ð¦6öç7Bv–æF÷w56Öö¶RÒ6UVç6–væVBç6Æ–6R‡v–æF÷w56Öö¶TBÂÖ56Öö¶TB“°Ð¦6öç7BÖ56Öö¶RÒ6UVç6–væVBç6Æ–6R†Ö56Öö¶TBÂ'F–f7EWÆöDB“°Ð¦f÷"†6öç7B·6Öö¶RÂ'—FT&–æDf–ÇW&UÒöb°Ð¢·v–æF÷w56Öö¶RÂt–ç7FÆÆVB&öGV7BÖæ–fW7B—2æ÷B'—FRÖ–FVçF–6ÂFò7Fv–æruÒÀÐ¢¶Ö56Öö¶RÂtÖ÷VçFVB&öGV7BÖæ–fW7B—2æ÷B'—FRÖ–FVçF–6ÂFò7Fv–æruÒÀÐ¥Ò’°Ð¢76W'Bæö²‡6Öö¶Ræ–æ6ÇVFW2†'—FT&–æDf–ÇW&R’“°Ð¢76W'Bæö²‡6Öö¶Ræ–æ6ÇVFW2‚vWFöVF—F÷"ÖFW6·F÷×'VçF–ÖR÷cr’“°Ð¢76W'Bæö²‡6Öö¶Ræ–æ6ÇVFW2‚v6ö×öæVçG2ÓÒ7GVÂr’“°Ð¢76W'Bæö²‡6Öö¶Ræ–æ6ÇVFW2‚w'VçF–ÖRævWB‚'fW'6–öâ"’ÓÒfW'6–öâr’“°Ð¢76W'Bæö²‡6Öö¶Ræ–æ6ÇVFW2‚w'VçF–ÖRævWB‚'F&vWB"’ÓÒF&vWBr’“°Ð¢76W'Bæö²‡6Öö¶Ræ–æ6ÇVFW2‚rÒ×6VÆb×FW7Br’“°Ð§ÐÐ¦76W'Bæö²‡6Uv–æF÷w2æ–æ6ÇVFW2‚tvWBÔWF†VçF–6öFU6–væGW&Rr’“°Ð¦76W'Bæö²‡6Uv–æF÷w2æ–æ6ÇVFW2‚v6ö×öæVçG2ÓÒ7GVÂr’“°Ð¦76W'Bæö²‡6TÖ2æ–æ6ÇVFW2‚tWF†÷&—G“ÔFWfVÆ÷W"”BÆ–6F–öâr’“°Ð¦76W'Bæö²‡6TÖ2æ–æ6ÇVFW2‚w†7'Vâ7FÆW"fÆ–FFR"DDÔr"r’“°Ð¦76W'Bæö²‡6TÖ2æ–æ6ÇVFW2‚v6ö×öæVçG2ÓÒ7GVÂr’“°Ð¦76W'Bæö²††VÇW%v–æF÷w2æ–æ6ÇVFW2‚tvWBÔWF†VçF–6öFU6–væGW&Rr’“°Ð¦76W'Bæö²††VÇW%v–æF÷w2æ–æ6ÇVFW2€Ð¢tvWBÔ6†–ÆD—FVÒG&W6÷W&6W2Õ&V7W'6RÔf–ÇFW"¢æW†RÔf–ÆRr’“°Ð¦76W'Bæö²††VÇW%v–æF÷w2æ–æ6ÇVFW2€Ð¢rFf–ÆRägVÆÄæÖRFf–ÆUF‡VÖ'&–çBF&÷fVD–FVçF—G”V·Rr’“°Ð¦76W'Bæö²††VÇW%v–æF÷w2æ–æ6ÇVFW2‚wfW&–g•ö†VÇW%öÖæ–fW7Bç’r’“°Ð¦76W'Bæö²††VÇW$Ö2æ–æ6ÇVFW2‚tWF†÷&—G“ÔFWfVÆ÷W"”BÆ–6F–öâr’“°Ð¦76W'Bæö²††VÇW$Ö2æ–æ6ÇVFW2‚w†7'Vâ7FÆW"fÆ–FFR"DDÔr"r’“°Ð¦76W'Bæö²††VÇW$Ö2æ–æ6ÇVFW2‚wfW&–g•ö†VÇW%öÖæ–fW7Bç’r’“°Ð¦76W'Bæö²‡6Uv–æF÷w2æ–æ6ÇVFW2€Ð¢tvWBÔ6†–ÆD—FVÒG&W6÷W&6W2Õ&V7W'6RÔf–ÇFW"¢æW†RÔf–ÆRr’“°Ð¦76W'Bæö²‡6Uv–æF÷w2æ–æ6ÇVFW2€Ð¢væ÷&ÖÆ—¦U÷v–æF÷w5öW†V7WF&ÆW3ÕG'VRr’“°Ð¦76W'Bæö²‡6TÖ2æ–æ6ÇVFW2€Ð¢w'VçF–ÖRævWB‚'&V6V—DÆv÷&—F†Ò"’ÓÒ'&r×6†#Sb×c"r’“°Ð¦6öç6öÆRæÆör‚wÆFf÷&Ò6öçG&7G2ö²r“°Ð