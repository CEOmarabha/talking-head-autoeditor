'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const REPOSITORY = path.resolve(__dirname, '..', '..');
const DESKTOP = path.join(REPOSITORY, 'desktop');
const PORTABLE = path.join(DESKTOP, 'team-dist',
  'AutoEditor-Helper-0.1.5-windows-x64-portable');
const ASAR = path.join(PORTABLE, 'resources', 'app.asar');
const ASAR_JS = path.join(DESKTOP, 'node_modules', '.pnpm',
  '@electron+asar@3.4.1', 'node_modules', '@electron', 'asar', 'bin', 'asar.js');
const WORKTREE_PACK = path.join(REPOSITORY, 'packaging', 'vision-model-packs',
  'smolvlm2-067788b187b95ebe');
const INSTALLED_PACK = path.join(PORTABLE, 'resources', 'models', 'vision',
  'smolvlm2-067788b187b95ebe');
const {
  MODEL_PACK_LOCK_SHA256,
  MODEL_PACK_TREE_SHA256,
  MODEL_PACK_TOTAL_BYTES,
  MODEL_FILES,
} = require('../helper/lib/vision-model-pack');

function sha256File(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function treeSha256(root) {
  const files = [];
  const walk = (directory, relative = '') => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => Buffer.from(left.name).compare(Buffer.from(right.name)))) {
      const child = path.join(directory, entry.name);
      const name = relative ? `${relative}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(child, name);
      else if (entry.isFile()) {
        const stat = fs.statSync(child);
        files.push(`${name}\0${stat.size}\0${sha256File(child)}\n`);
      }
    }
  };
  walk(root);
  return {
    files: files.length,
    sha256: crypto.createHash('sha256').update(files.join(''), 'utf8').digest('hex'),
  };
}

function extractAsar(destination) {
  fs.rmSync(destination, { recursive: true, force: true });
  fs.mkdirSync(destination, { recursive: true });
  const result = spawnSync(process.execPath, [ASAR_JS, 'extract', ASAR, destination], {
    encoding: 'utf8',
  });
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || 'asar extract failed');
  }
}

function comparePair(label, left, right) {
  const leftHash = sha256File(left);
  const rightHash = sha256File(right);
  return {
    label,
    left,
    right,
    left_sha256: leftHash,
    right_sha256: rightHash,
    match: leftHash === rightHash,
  };
}

function modelPackReceipt(root) {
  const lock = path.join(root, 'model-pack.lock.json');
  const files = MODEL_FILES.map((file) => {
    const candidate = path.join(root, 'HuggingFaceTB',
      'SmolVLM2-256M-Video-Instruct', ...file.path.split('/'));
    const exists = fs.existsSync(candidate);
    const actual = exists ? fs.statSync(candidate).size : 0;
    const digest = exists ? sha256File(candidate) : '';
    return {
      path: file.path,
      expected_bytes: file.bytes,
      expected_sha256: file.sha256,
      actual_bytes: actual,
      actual_sha256: digest,
      match: exists && actual === file.bytes && digest === file.sha256,
    };
  });
  return {
    root,
    lock_exists: fs.existsSync(lock),
    lock_sha256: fs.existsSync(lock) ? sha256File(lock) : '',
    lock_matches_contract: fs.existsSync(lock) &&
      sha256File(lock) === MODEL_PACK_LOCK_SHA256,
    files,
    all_files_match: files.every((item) => item.match),
  };
}

function main() {
  const extractRoot = path.join(DESKTOP, 'team-dist', 'handoff-extract-asar');
  extractAsar(extractRoot);
  const pairs = [
    comparePair('helper/main.js',
      path.join(extractRoot, 'helper', 'main.js'),
      path.join(DESKTOP, 'helper', 'main.js')),
    comparePair('helper/lib/runtime-capability-preflight.js',
      path.join(extractRoot, 'helper', 'lib', 'runtime-capability-preflight.js'),
      path.join(DESKTOP, 'helper', 'lib', 'runtime-capability-preflight.js')),
    comparePair('helper/lib/runtime-capability-check-runner.js',
      path.join(extractRoot, 'helper', 'lib', 'runtime-capability-check-runner.js'),
      path.join(DESKTOP, 'helper', 'lib', 'runtime-capability-check-runner.js')),
    comparePair('helper/lib/vision-model-pack.js',
      path.join(extractRoot, 'helper', 'lib', 'vision-model-pack.js'),
      path.join(DESKTOP, 'helper', 'lib', 'vision-model-pack.js')),
    comparePair('helper/lib/calibrated-semantic-choice.js',
      path.join(extractRoot, 'helper', 'lib', 'calibrated-semantic-choice.js'),
      path.join(DESKTOP, 'helper', 'lib', 'calibrated-semantic-choice.js')),
    comparePair('lib/process-tree.js',
      path.join(extractRoot, 'lib', 'process-tree.js'),
      path.join(DESKTOP, 'lib', 'process-tree.js')),
    comparePair('engine.exe',
      path.join(PORTABLE, 'resources', 'engine', 'autoeditor-engine.exe'),
      path.join(REPOSITORY, 'packaging', 'dist', 'autoeditor-engine',
        'autoeditor-engine.exe')),
    comparePair('safe-output.js worktree only',
      path.join(DESKTOP, 'scripts', 'vision-capability-electron', 'safe-output.js'),
      path.join(DESKTOP, 'scripts', 'vision-capability-electron', 'safe-output.js')),
  ];
  const worktreePack = modelPackReceipt(WORKTREE_PACK);
  const installedPack = modelPackReceipt(INSTALLED_PACK);
  const worktreeTree = treeSha256(path.join(WORKTREE_PACK,
    'HuggingFaceTB', 'SmolVLM2-256M-Video-Instruct'));
  const installedTree = treeSha256(path.join(INSTALLED_PACK,
    'HuggingFaceTB', 'SmolVLM2-256M-Video-Instruct'));
  const asarPackage = JSON.parse(fs.readFileSync(
    path.join(extractRoot, 'package.json'), 'utf8'));
  const receipt = {
    schema_version: 'autoeditor-team-handoff-hash-receipt/v1',
    collected_at: new Date().toISOString(),
    portable: PORTABLE,
    app_asar_sha256: sha256File(ASAR),
    portable_version_file: fs.readFileSync(path.join(PORTABLE, 'version'), 'utf8').trim(),
    asar_package: asarPackage,
    file_pairs: pairs,
    all_worktree_file_pairs_match: pairs
      .filter((item) => item.label !== 'safe-output.js worktree only')
      .every((item) => item.match),
    model_pack: {
      contract_lock_sha256: MODEL_PACK_LOCK_SHA256,
      contract_tree_sha256: MODEL_PACK_TREE_SHA256,
      contract_total_bytes: MODEL_PACK_TOTAL_BYTES,
      worktree: worktreePack,
      installed: installedPack,
      worktree_model_tree_sha256: worktreeTree.sha256,
      installed_model_tree_sha256: installedTree.sha256,
      trees_match_each_other: worktreeTree.sha256 === installedTree.sha256,
      trees_match_contract: worktreeTree.sha256 === MODEL_PACK_TREE_SHA256 &&
        installedTree.sha256 === MODEL_PACK_TREE_SHA256,
    },
  };
  const output = process.argv.includes('--output')
    ? path.resolve(process.argv[process.argv.indexOf('--output') + 1])
    : '';
  const text = `${JSON.stringify(receipt, null, 2)}\n`;
  if (output) {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, text);
  }
  process.stdout.write(text);
  const failed = !receipt.all_worktree_file_pairs_match ||
    !receipt.model_pack.worktree.all_files_match ||
    !receipt.model_pack.installed.all_files_match ||
    !receipt.model_pack.trees_match_contract ||
    asarPackage.version !== '0.1.5';
  process.exitCode = failed ? 1 : 0;
}

main();
