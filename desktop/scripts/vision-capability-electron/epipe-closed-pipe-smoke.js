'use strict';

// Prove the current vision Electron harness, not an older Helper binary.
// Spawn the worktree Electron against this directory, require --output, omit
// a valid FFmpeg so configuration fails fast, and close stdout. The process
// must write the failure receipt to the output file and exit without an
// uncaught EPIPE dialog.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

function electronPath() {
  const candidates = [
    path.resolve(__dirname, '..', '..', 'node_modules', 'electron', 'dist',
      'electron.exe'),
    path.resolve(__dirname, '..', '..', '..', '.local-tools', 'desktop-npm',
      'node_modules', 'electron', 'dist', 'electron.exe'),
  ];
  const found = candidates.find((file) => fs.existsSync(file));
  if (!found) throw new Error('current Electron binary is unavailable');
  return found;
}

async function main() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-epipe-smoke-'));
  const output = path.join(work, 'result.json');
  const userData = path.join(work, 'user-data');
  fs.mkdirSync(userData);
  const electron = electronPath();
  const child = spawn(electron, [
    __dirname,
    '--output', output,
    '--ffmpeg', path.join(work, 'missing-ffmpeg.exe'),
    '--user-data-dir', userData,
    '--no-sandbox',
  ], {
    stdio: ['ignore', 'ignore', 'pipe'],
    windowsHide: true,
    env: {
      ...process.env,
      ELECTRON_ENABLE_LOGGING: '1',
    },
  });
  const stdout = Buffer.alloc(0);
  let stderr = Buffer.alloc(0);
  child.stderr.on('data', (chunk) => {
    stderr = Buffer.concat([stderr, chunk]);
  });
  const code = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error('EPIPE smoke timed out'));
    }, 30_000);
    child.once('error', reject);
    child.once('close', (value) => {
      clearTimeout(timer);
      resolve(value);
    });
  });
  const receipt = {
    schema_version: 'autoeditor-vision-epipe-smoke/v1',
    electron,
    harness: __dirname,
    exit_code: code,
    output_exists: fs.existsSync(output),
    output_bytes: fs.existsSync(output) ? fs.statSync(output).size : 0,
    stdout_bytes: stdout.length,
    stderr_preview: stderr.toString('utf8').slice(0, 800),
  };
  if (receipt.output_exists) {
    receipt.output = JSON.parse(fs.readFileSync(output, 'utf8'));
  }
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
  const failed = receipt.exit_code === 0 || !receipt.output_exists ||
    receipt.output?.pass === true ||
    /EPIPE|broken pipe|uncaughtException/i.test(receipt.stderr_preview);
  fs.rmSync(work, { recursive: true, force: true });
  process.exitCode = failed ? 1 : 0;
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
