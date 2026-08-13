'use strict';

// Build a team portable from *this* worktree. The 0.1.4 portable is used only
// as a runtime donor (FFmpeg, models, Remotion, Node). App code, engine, and
// the vision model pack always come from the current tree.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const REPOSITORY = path.resolve(__dirname, '..', '..');
const DESKTOP = path.join(REPOSITORY, 'desktop');
const VERSION = JSON.parse(fs.readFileSync(
  path.join(DESKTOP, 'package.json'), 'utf8')).version;

function argument(name, fallback = '') {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || '') : fallback;
}

function fail(message) {
  throw new Error(message);
}

function sha256File(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function resolveAsarJs() {
  const candidates = [
    path.join(DESKTOP, 'node_modules', '@electron', 'asar', 'bin', 'asar.js'),
    path.join(DESKTOP, 'node_modules', '.pnpm',
      '@electron+asar@3.4.1', 'node_modules', '@electron', 'asar', 'bin',
      'asar.js'),
  ];
  const found = candidates.find((file) => fs.existsSync(file));
  if (!found) fail('asar.js is not installed in desktop/node_modules');
  return found;
}

function defaultRuntimeBase() {
  return path.resolve(
    REPOSITORY, '..', '..', '..', 'look-into-my-computer-settings-mak',
    'outputs', 'AutoEditor-0.1.4-Private-Beta',
    'AutoEditor-Helper-0.1.4-windows-x64-portable');
}

function copyTree(source, destination) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  if (process.platform === 'win32') {
    const result = spawnSync('robocopy', [
      source, destination, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns',
      '/np',
    ], { windowsHide: true });
    if (result.status >= 8) {
      fail(`robocopy failed with status ${result.status}`);
    }
    return;
  }
  fs.cpSync(source, destination, { recursive: true });
}

function packAppAsar(destinationAsar) {
  const stage = fs.mkdtempSync(path.join(DESKTOP, 'team-dist', 'asar-stage-'));
  const packageJson = {
    name: 'autoeditor-helper',
    version: VERSION,
    main: 'helper/main.js',
    author: 'Omar Marabha',
    private: true,
  };
  fs.writeFileSync(path.join(stage, 'package.json'),
    `${JSON.stringify(packageJson, null, 2)}\n`);
  copyTree(path.join(DESKTOP, 'helper'), path.join(stage, 'helper'));
  copyTree(path.join(DESKTOP, 'lib'), path.join(stage, 'lib'));
  const asarJs = resolveAsarJs();
  if (fs.existsSync(destinationAsar)) fs.unlinkSync(destinationAsar);
  const packed = spawnSync(process.execPath, [
    asarJs, 'pack', stage, destinationAsar,
  ], {
    windowsHide: true, encoding: 'utf8',
  });
  fs.rmSync(stage, { recursive: true, force: true });
  if (packed.status !== 0) {
    fail(packed.stderr || packed.stdout || 'asar pack failed');
  }
}

function overlayCurrentRuntime(destination) {
  const resources = path.join(destination, 'resources');
  const engineSource = path.join(REPOSITORY, 'packaging', 'dist',
    'autoeditor-engine');
  const daemonSource = path.join(REPOSITORY, 'packaging', 'dist',
    'autoeditor-helper-daemon');
  const visionSource = path.join(REPOSITORY, 'packaging', 'vision-model-packs',
    'smolvlm2-067788b187b95ebe');
  if (!fs.existsSync(path.join(engineSource, 'autoeditor-engine.exe'))) {
    fail('current frozen engine is missing from packaging/dist');
  }
  copyTree(engineSource, path.join(resources, 'engine'));
  if (fs.existsSync(daemonSource)) {
    copyTree(daemonSource, path.join(resources, 'helper'));
  }
  if (fs.existsSync(visionSource)) {
    copyTree(visionSource, path.join(resources, 'models', 'vision',
      'smolvlm2-067788b187b95ebe'));
  }
  const profilesSource = path.join(REPOSITORY, 'profiles');
  const engineProfiles = path.join(resources, 'engine', '_internal', 'profiles');
  for (const name of [
    'generic_short', 'generic_long', 'generic_commercial', 'generic_podcast',
    'generic_course', 'generic_custom',
  ]) {
    const from = path.join(profilesSource, name);
    if (fs.existsSync(from)) copyTree(from, path.join(engineProfiles, name));
  }
}

function writeIdentity(destination, runtimeBase) {
  const asar = path.join(destination, 'resources', 'app.asar');
  const engine = path.join(destination, 'resources', 'engine',
    'autoeditor-engine.exe');
  const main = path.join(DESKTOP, 'helper', 'main.js');
  const safeOutput = path.join(DESKTOP, 'scripts',
    'vision-capability-electron', 'safe-output.js');
  const identity = {
    schema_version: 'autoeditor-team-portable-identity/v1',
    product: 'AutoEditor Helper',
    version: VERSION,
    built_at: new Date().toISOString(),
    worktree: REPOSITORY,
    runtime_donor: runtimeBase,
    files: {
      app_asar_sha256: sha256File(asar),
      engine_sha256: fs.existsSync(engine) ? sha256File(engine) : '',
      helper_main_sha256: sha256File(main),
      safe_output_sha256: sha256File(safeOutput),
    },
    notes: [
      'App code is from this worktree, not the 0.1.4 asar.',
      'Semantic visual evaluation stays disabled until a sealed qualification exists.',
    ],
  };
  fs.writeFileSync(path.join(destination, 'TEAM_BUILD_IDENTITY.json'),
    `${JSON.stringify(identity, null, 2)}\n`);
  fs.writeFileSync(path.join(destination, 'version'), `${VERSION}\n`);
  return identity;
}

function main() {
  const runtimeBase = path.resolve(argument('--runtime-base', defaultRuntimeBase()));
  const destination = path.resolve(argument('--output',
    path.join(DESKTOP, 'team-dist',
      `AutoEditor-Helper-${VERSION}-windows-x64-portable`)));
  if (!fs.existsSync(path.join(runtimeBase, 'AutoEditor Helper.exe'))) {
    fail(`runtime donor is missing: ${runtimeBase}`);
  }
  const exe = path.join(destination, 'AutoEditor Helper.exe');
  if (fs.existsSync(destination) && !fs.existsSync(exe)) {
    fail(`incomplete portable at ${destination}; delete it and rebuild`);
  }
  if (!fs.existsSync(exe)) {
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    copyTree(runtimeBase, destination);
  }
  if (!fs.existsSync(exe)) fail(`runtime donor copy is missing: ${exe}`);
  packAppAsar(path.join(destination, 'resources', 'app.asar'));
  overlayCurrentRuntime(destination);
  const identity = writeIdentity(destination, runtimeBase);
  process.stdout.write(`${JSON.stringify(identity, null, 2)}\n`);
}

if (require.main === module) {
  try { main(); }
  catch (error) {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { VERSION };
