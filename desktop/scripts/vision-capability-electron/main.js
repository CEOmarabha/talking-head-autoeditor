'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  app,
  BrowserWindow,
  ipcMain,
  protocol,
  session,
} = require('electron');
const {
  createVisionProtocolHandler,
  sourceVisionModelPackPath,
} = require('../../helper/lib/vision-model-pack');
const {
  createVisualQualityFixtures,
} = require('../../helper/lib/visual-quality-fixtures');
const {
  runVisualQualityRuntimeProbe,
} = require('../../helper/lib/visual-quality-runtime-probe');
const { writeStdoutSync } = require('./safe-output');

const EVENT_SCHEMA_VERSION = 'autoeditor-visual-quality-electron-probe/v1';
const DEFAULT_TIMEOUT_MS = 12 * 60 * 1000;
const MAX_FRAME_BYTES = 3 * 1024 * 1024;
let failureOutputPath = '';

protocol.registerSchemesAsPrivileged([{
  scheme: 'autoeditor-vision',
  privileges: {
    standard: true, secure: true, supportFetchAPI: true, corsEnabled: true,
  },
}]);

function stableJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
}

function digest(value) {
  return crypto.createHash('sha256').update(stableJson(value)).digest('hex');
}

function argument(name, fallback = '') {
  const index = process.argv.indexOf(name);
  if (index < 0) return fallback;
  const value = process.argv[index + 1];
  if (!value || value.startsWith('--')) throw new Error('probe argument is invalid');
  return value;
}

function authoritativeOutputPath() {
  // Bind --output before any later configuration throw. A missing FFmpeg path
  // must still treat the result file as the only delivery channel.
  const outputRaw = argument('--output', '');
  if (!outputRaw) return '';
  const outputPath = path.resolve(outputRaw);
  if (!path.isAbsolute(outputPath)) throw new Error('probe configuration is invalid');
  return outputPath;
}

function options() {
  const repository = path.resolve(__dirname, '..', '..', '..');
  const modelPackRoot = path.resolve(argument(
    '--model-pack', sourceVisionModelPackPath(repository)));
  const ffmpegPath = path.resolve(argument(
    '--ffmpeg', process.env.AUTOEDITOR_FFMPEG || ''));
  const outputPath = authoritativeOutputPath();
  const repetitions = Number(argument('--repetitions', '1'));
  const timeoutMs = Number(argument('--timeout-ms', String(DEFAULT_TIMEOUT_MS)));
  if (!path.isAbsolute(modelPackRoot) || !path.isAbsolute(ffmpegPath) ||
      !fs.statSync(ffmpegPath).isFile() ||
      !Number.isSafeInteger(repetitions) || repetitions < 1 || repetitions > 3 ||
      !Number.isSafeInteger(timeoutMs) || timeoutMs < 10_000 ||
      timeoutMs > 30 * 60 * 1000) {
    throw new Error('probe configuration is invalid');
  }
  return { repository, modelPackRoot, ffmpegPath, outputPath, repetitions,
    timeoutMs };
}

function readJpeg(file, expectedSha256) {
  const descriptor = fs.openSync(file, 'r');
  try {
    const before = fs.fstatSync(descriptor);
    if (!before.isFile() || before.size < 4 || before.size > MAX_FRAME_BYTES) {
      throw new Error('probe JPEG size is invalid');
    }
    const bytes = Buffer.allocUnsafe(before.size);
    if (fs.readSync(descriptor, bytes, 0, before.size, 0) !== before.size) {
      throw new Error('probe JPEG changed while read');
    }
    const after = fs.fstatSync(descriptor);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs ||
        before.dev !== after.dev || before.ino !== after.ino ||
        !/^[0-9a-f]{64}$/.test(expectedSha256 || '') ||
        crypto.createHash('sha256').update(bytes).digest('hex') !==
          expectedSha256 ||
        bytes[0] !== 0xff || bytes[1] !== 0xd8 ||
        bytes.at(-2) !== 0xff || bytes.at(-1) !== 0xd9) {
      throw new Error('probe JPEG identity is invalid');
    }
    return `data:image/jpeg;base64,${bytes.toString('base64')}`;
  } finally { fs.closeSync(descriptor); }
}

function reviewProjection(value) {
  return {
    schema: value.schema,
    pass: value.pass,
    score: value.score,
    checks: value.checks,
    issues: value.issues,
    valid: value.valid,
    observedTargetIds: value.observedTargetIds,
  };
}

function semanticEvidenceProjection(value) {
  const assertions = Array.isArray(value?.batches)
    ? value.batches.flatMap((batch) =>
      Array.isArray(batch?.semanticReceipts)
        ? batch.semanticReceipts.map((item) => ({
          key: item.key,
          receipt: item.receipt,
          receipt_sha256: item.receiptSha256,
          target_id: item.targetId,
          target_sha256: item.targetSha256,
        })) : [])
    : [];
  return {
    assertions,
    reviewed_frame_ids: Array.isArray(value?.reviewedFrameIds)
      ? [...value.reviewedFrameIds] : [],
    reviewed_target_ids: Array.isArray(value?.reviewedTargetIds)
      ? [...value.reviewedTargetIds] : [],
  };
}

function fixtureProjection(fixtures) {
  const project = (frames) => frames.map((frame) => ({
    id: frame.id,
    sha256: frame.sha256,
    size_bytes: frame.size_bytes,
    target_ids: frame.targets.map((target) => target.id),
  }));
  return {
    schema_version: fixtures.schema_version,
    positive: project(fixtures.positiveFrames),
    defective: project(fixtures.defectiveFrames),
  };
}

function writeResult(file, value) {
  const bytes = Buffer.from(`${stableJson(value)}\n`, 'utf8');
  if (file) {
    fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 });
    return;
  }
  // The Electron harness is normally supervised through a stdout pipe. The
  // receipt on disk is authoritative; a parent that exits early must not turn
  // an otherwise complete probe into an uncaught main-process EPIPE dialog.
  writeStdoutSync(bytes);
}

function safeFailure(error) {
  const name = String(error?.name || 'Error').replace(/[^A-Za-z0-9_-]/g, '')
    .slice(0, 80) || 'Error';
  const reason = String(error?.message || 'local visual-quality probe failed')
    .replace(/[A-Za-z]:\\[^\s"']+/g, '<path>')
    .replace(/\0/g, '').trim().slice(0, 300);
  const projectEvidence = (evidence) => evidence &&
    Array.isArray(evidence.expectedTargetIds) &&
    Array.isArray(evidence.reviewedTargetIds) && evidence.review
    ? {
      expected_target_ids: evidence.expectedTargetIds,
      reviewed_target_ids: evidence.reviewedTargetIds,
      review: reviewProjection(evidence.review),
    } : null;
  const evaluation = error?.evaluationEvidence;
  const evaluationEvidence = evaluation &&
    Object.keys(evaluation).sort().join('\0') === 'defective\0positive'
    ? {
      positive: projectEvidence(evaluation.positive),
      defective: projectEvidence(evaluation.defective),
    } : null;
  const single = error?.reviewEvidence;
  const reviewEvidence = evaluationEvidence || (single &&
    ['positive', 'defective'].includes(single.kind)
    ? { kind: single.kind, ...projectEvidence(single) } : null);
  return {
    event: 'autoeditor-visual-quality-electron-probe',
    schema_version: EVENT_SCHEMA_VERSION,
    pass: false,
    failure: name,
    reason,
    review_evidence: reviewEvidence,
  };
}

async function run() {
  failureOutputPath = authoritativeOutputPath();
  const configuration = options();
  if (configuration.outputPath !== failureOutputPath) {
    throw new Error('probe configuration is invalid');
  }
  const visionRoot = path.join(configuration.repository,
    'desktop', 'helper', 'vision');
  const handler = createVisionProtocolHandler({
    modelPackRoot: configuration.modelPackRoot,
    runtimeRoot: visionRoot,
  });
  await protocol.handle('autoeditor-vision', handler);
  let remoteRequests = 0;
  session.defaultSession.webRequest.onBeforeRequest({
    urls: ['http://*/*', 'https://*/*'],
  }, (_details, callback) => {
    remoteRequests += 1;
    callback({ cancel: true });
  });
  session.defaultSession.setPermissionRequestHandler((_contents, _permission,
    callback) => callback(false));

  const window = new BrowserWindow({
    show: false,
    width: 640,
    height: 360,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  await window.loadFile(path.join(__dirname, 'index.html'));
  const pending = new Map();
  let sequence = 0;
  ipcMain.on('autoeditor-vision-probe-result', (event, value) => {
    if (event.sender !== window.webContents || !value ||
        typeof value !== 'object' || Array.isArray(value) ||
        !Number.isSafeInteger(value.id)) return;
    const entry = pending.get(value.id);
    if (!entry) return;
    pending.delete(value.id);
    clearTimeout(entry.timer);
    if (value.status === 'complete' && typeof value.result === 'string') {
      entry.resolve({ result: value.result, runtime: value.runtime });
    } else {
      entry.reject(new Error('local vision worker returned an error'));
    }
  });
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), configuration.timeoutMs);
  const requestChoice = ({
    framePath, frameSha256, mode, modelRequest, signal,
  }) => {
    if (signal.aborted || window.isDestroyed() ||
        mode !== 'artifact-assertion' || !modelRequest ||
        typeof modelRequest !== 'object' || Array.isArray(modelRequest)) {
      return Promise.reject(new Error('local vision request was canceled'));
    }
    const id = ++sequence;
    const images = [readJpeg(framePath, frameSha256)];
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error('local vision request timed out'));
      }, configuration.timeoutMs);
      pending.set(id, { resolve, reject, timer });
      window.webContents.send('autoeditor-vision-probe-request', {
        id, images, mode, model_request: modelRequest,
      });
    });
  };
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-vision-probe-'));
  try {
    const fixtures = await createVisualQualityFixtures({
      workDir,
      ffmpegPath: configuration.ffmpegPath,
      signal: controller.signal,
    });
    const iterations = [];
    const results = [];
    const started = Date.now();
    for (let index = 0; index < configuration.repetitions; index += 1) {
      const iterationStarted = Date.now();
      const result = await runVisualQualityRuntimeProbe({
        positiveFrames: fixtures.positiveFrames,
        defectiveFrames: fixtures.defectiveFrames,
        signal: controller.signal,
        requestChoice,
      });
      const projection = {
        positive: reviewProjection(result.positive.review),
        defective: reviewProjection(result.defective.review),
        semantic_evidence: {
          positive: semanticEvidenceProjection(result.positive),
          defective: semanticEvidenceProjection(result.defective),
        },
        runtime: result.runtime,
      };
      results.push(projection);
      iterations.push({
        index,
        duration_ms: Date.now() - iterationStarted,
        result_sha256: digest(projection),
      });
    }
    if (remoteRequests !== 0 ||
        new Set(iterations.map(({ result_sha256 }) => result_sha256)).size !== 1) {
      throw new Error('local vision probe was not offline and repeatable');
    }
    const first = results[0];
    const receipt = {
      event: 'autoeditor-visual-quality-electron-probe',
      schema_version: EVENT_SCHEMA_VERSION,
      pass: true,
      checks: {
        positive_pass: first.positive.pass === true,
        positive_targets_exact: first.positive.observedTargetIds.join('\0') ===
          fixtures.positiveFrames.flatMap((frame) =>
            frame.targets.map((target) => target.id)).join('\0'),
        defective_rejected: first.defective.pass === false,
        defective_targets_exact: first.defective.observedTargetIds.join('\0') ===
          fixtures.defectiveFrames.flatMap((frame) =>
            frame.targets.map((target) => target.id)).join('\0'),
        defective_captions_false: first.defective.checks.captions === false,
        defective_production_design_false:
          first.defective.checks.productionDesign === false,
        remote_requests_zero: true,
        repeatable: true,
      },
      fixture: fixtureProjection(fixtures),
      runtime: first.runtime,
      reviews: { positive: first.positive, defective: first.defective },
      semantic_evidence: first.semantic_evidence,
      timing: {
        repetitions: configuration.repetitions,
        total_ms: Date.now() - started,
        iterations,
      },
    };
    if (Object.values(receipt.checks).some((value) => value !== true)) {
      throw new Error('local vision probe checks failed');
    }
    writeResult(configuration.outputPath, receipt);
  } finally {
    clearTimeout(deadline);
    controller.abort();
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(new Error('local vision probe ended'));
    }
    pending.clear();
    fs.rmSync(workDir, { recursive: true, force: true });
    window.destroy();
  }
}

app.whenReady().then(async () => {
  try {
    failureOutputPath = authoritativeOutputPath();
  } catch (error) {
    try { writeStdoutSync(Buffer.from(`${stableJson(safeFailure(error))}\n`, 'utf8')); }
    catch (_) { /* closed delivery channel */ }
    app.exit(1);
    return;
  }
  try {
    await run();
    app.exit(0);
  } catch (error) {
    try { writeResult(failureOutputPath, safeFailure(error)); }
    catch (_) { /* no recovery */ }
    app.exit(1);
  }
});
