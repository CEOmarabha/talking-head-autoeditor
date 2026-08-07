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
const helperMain = fs.readFileSync(
  path.join(desktop, 'helper', 'main.js'), 'utf8');
const helperWorkflow = fs.readFileSync(
  path.join(desktop, '..', '.github', 'workflows', 'helper-release.yml'), 'utf8');
const helperAzure = fs.readFileSync(
  path.join(desktop, 'electron-builder.helper.azure.js'), 'utf8');
const ownerSigning = fs.readFileSync(
  path.join(desktop, '..', 'docs', 'OWNER_SIGNING_SETUP.md'), 'utf8');
const ignoreRules = fs.readFileSync(
  path.join(desktop, '..', '.gitignore'), 'utf8');

assert.ok((main.match(/windowsHide: true/g) || []).length >= 3);
assert.ok(main.includes('stopProcessTree(active)'));
assert.ok(main.includes("AUTOEDITOR_SMOKE_TEST === '1'"));
assert.ok(main.includes('safeStorage.encryptString(secret)'));
assert.ok(preload.includes('webUtils.getPathForFile(file)'));
assert.ok(renderer.includes('window.api.filePath(f)'));
assert.ok(!renderer.includes('.map((f) => f.path)'));
assert.ok(workflow.includes('Smoke-test Windows installer'));
assert.ok(workflow.includes('Smoke-test macOS app and DMG'));
assert.ok(workflow.includes('Publish only after every platform passes'));
assert.ok(helperMain.includes("AUTOEDITOR_REQUIRE_HYPERFRAMES: '1'"));
assert.ok(helperMain.includes('AUTOEDITOR_CREATIVE_SMOKE_TEST'));
assert.ok(helperMain.includes('validateProviderKeys'));
assert.ok(helperWorkflow.includes('windows-2022'));
assert.ok(helperWorkflow.includes('macos-15-intel'));
assert.ok(helperWorkflow.includes('Render real HyperFrames and Remotion probes'));
assert.ok(helperWorkflow.includes('Get-AuthenticodeSignature'));
assert.ok(helperWorkflow.includes('win_signing=azure'));
assert.ok(helperAzure.includes('azureSignOptions'));
assert.ok(ownerSigning.includes('AZURE_TENANT_ID'));
assert.ok(ownerSigning.includes('Signing Certificate Profile Signer'));
assert.ok(ownerSigning.includes('APPLE_APP_SPECIFIC_PASSWORD'));
assert.ok(helperWorkflow.includes('xcrun stapler validate'));
assert.ok(helperWorkflow.includes('Publish installers to private website storage'));
assert.ok(helperWorkflow.includes('python -m pip install --require-hashes'));
assert.ok(helperWorkflow.includes(
  'requirements-${{ matrix.target_os }}-${{ matrix.arch }}.txt'));
assert.ok(helperWorkflow.includes(
  '8e148d10ce8da1dca931c2f35c3a180100520bb48940f4bf1c0a3c1627467331'));
assert.ok(helperWorkflow.includes('wrangler@4.120.0'));
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
// The DMG stays plain: Finder customization attached metadata after sealing.
assert.ok(helperBuilder.includes('background: null'));
// Both products ship a real icon, not the default Electron one.
assert.ok(helperBuilder.includes('icon: build/icon.icns'));
assert.ok(fs.existsSync(path.join(desktop, 'build', 'icon.icns')));
assert.ok(fs.existsSync(path.join(desktop, 'build', 'icon.ico')));
// CI inspects the PACKED app for the creative runtime and verifies the app
// from a fresh DMG mount, resolving the executable from Info.plist.
assert.ok(helperWorkflow.includes(
  'Verify the packed app ships the complete creative runtime'));
assert.ok(helperWorkflow.includes('CFBundleExecutable'));
assert.ok(helperWorkflow.includes('hdiutil attach'));
// Homebrew bottle revisions (8.1.2_1) of the audited FFmpeg are accepted.
assert.ok(helperWorkflow.includes('8\\.1\\.2(_[0-9]+)?'));
assert.ok(workflow.includes('CFBundleExecutable'));
console.log('platform contracts ok');
