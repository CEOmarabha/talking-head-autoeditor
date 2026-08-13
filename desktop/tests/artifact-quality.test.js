const assert = require('assert');

const {
  artifactAudioQaReceipt,
  artifactReviewPrompt,
  parseArtifactReview,
  reviewArtifactFrames,
  reviewPasses,
} = require('../helper/lib/artifact-quality');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');

const prompt = artifactReviewPrompt('Use bold captions and purposeful visual changes.');
assert.match(prompt, /caption/i);
assert.match(prompt, /sound design/i);
assert.match(prompt, /transitions/i);
assert.match(prompt, /Return JSON only/i);
const batchPrompt = artifactReviewPrompt('Approved brief', {
  number: 2, count: 3,
  frames: [{ id: 'vision-frame-009', timeSeconds: 13, categories: ['graphics'] }],
});
assert.match(batchPrompt, /batch 2 of 3/i);
assert.match(batchPrompt, /13/);
assert.match(batchPrompt, /do not claim to have seen/i);
const sidecarPrompt = artifactReviewPrompt(
  'Captions must be delivered with the video.', null, 'sidecar');
assert.match(sidecarPrompt, /intentionally external sidecar text/i);
assert.match(sidecarPrompt, /Do not reject missing visible captions/i);
assert.match(sidecarPrompt, /not applicable/i);

const passing = parseArtifactReview(JSON.stringify({
  schema: 'autoeditor-artifact-review/v2',
  pass: true,
  score: 96,
  observedTargetIds: ['target-1'],
  checks: {
    captions: true,
    framing: true,
    visualVariety: true,
    graphics: true,
    transitions: true,
    productionDesign: true,
  },
  issues: [],
}));
assert.strictEqual(reviewPasses(passing), true);

const roundedThresholdTrap = parseArtifactReview(JSON.stringify({
  schema: 'autoeditor-artifact-review/v2', pass: true, score: 91.6,
  observedTargetIds: ['target-1'],
  checks: {
    captions: true, framing: true, visualVariety: true, graphics: true,
    transitions: true, productionDesign: true,
  },
  issues: [],
}));
assert.strictEqual(roundedThresholdTrap.score, 91.6);
assert.strictEqual(reviewPasses(roundedThresholdTrap), false,
  'the 92 threshold must apply to the raw model score, not a rounded display value');

const artifactSha256 = 'a'.repeat(64);
const qaReceipt = {
  file: 'QA_REPORT.json', sha256: 'b'.repeat(64),
  contract: { audio_mix: {
    file: 'AUDIO_MIX_RECEIPT.json', sha256: 'd'.repeat(64),
  } },
  report: {
    pass: true,
    checks: {
      'loudness_-14LUFS': { ok: true, measured: -14.2 },
      audio_true_peak: { ok: true, measured_dbtp: -1.1 },
      delivery_derivative_verified: { ok: true, audio_hash_match: true },
    },
    release: { '9x16': { sha256: artifactSha256, file: 'PSE_SHORT_9x16.mp4' } },
  },
};
const mixReport = {
  schema: 'autoeditor-audio-mix-receipt/v1', mix_succeeded: true,
  perceptual_quality_assessed: false,
  master: { file: 'master.mp4', bytes: 1234, sha256: '9'.repeat(64),
    duration_seconds: 45,
    audio: { codec: 'aac', sample_rate: 48000, channels: 2 } },
  music: null,
  sfx: [{ index: 0, cue: 'boom', file: 'boom.wav', bytes: 321,
    timestamp_seconds: 4, gain: 0.45,
    sha256: 'c'.repeat(64) }],
};
qaReceipt.report.checks.audio_mix_receipt = {
  ok: true, schema: 'autoeditor-audio-mix-receipt/v1',
  receipt_sha256: 'f'.repeat(64),
  planned_sfx: 1, bound_sfx: 1, music_present: false,
  sample_rate: 48000, channels: 2,
};
const audioReceipt = artifactAudioQaReceipt(qaReceipt, {
  file: 'AUDIO_MIX_RECEIPT.json', sha256: 'd'.repeat(64), report: mixReport,
}, artifactSha256);
assert.strictEqual(audioReceipt.pass, true);
assert.strictEqual(audioReceipt.sfx.plannedCueCount, 1);
assert.strictEqual(audioReceipt.sfx.status, 'deterministically-mixed');
assert.strictEqual(audioReceipt.sfx.heard, null,
  'still-frame vision must never claim that a planned sound was heard');
qaReceipt.report.checks.delivery_derivative_verified.audio_hash_match = false;
assert.strictEqual(artifactAudioQaReceipt(qaReceipt, {
  file: 'AUDIO_MIX_RECEIPT.json', sha256: 'd'.repeat(64), report: mixReport,
}, artifactSha256).pass, false,
  'the final delivery decoded-audio hash must match the receipt-bound master');
qaReceipt.report.checks.delivery_derivative_verified.audio_hash_match = true;
assert.strictEqual(artifactAudioQaReceipt(qaReceipt, null, 'e'.repeat(64)).pass,
  false, 'audio QA must be bound to the exact released artifact hash');

for (const raw of [
  '{"pass":true,"score":100}',
  JSON.stringify({
    schema: 'autoeditor-artifact-review/v2', pass: true, score: 96,
    observedTargetIds: ['target-1'],
    checks: { captions: false, framing: true, visualVariety: true,
      graphics: true, transitions: true, productionDesign: true },
    issues: ['Captions overlap the speaker.'],
  }),
  'not json',
]) {
  assert.strictEqual(reviewPasses(parseArtifactReview(raw)), false);
}

const main = fs.readFileSync(path.join(__dirname, '..', 'helper', 'main.js'), 'utf8');
assert.match(main, /void reviewArtifact\(event, action\)/);
assert.match(main, /The draft was not exposed as a finished video/);
assert.match(main, /retryRejectedRender\(action, artifact, issue\)/);
assert.match(main, /VISION-REJECTED/);
assert.ok(main.indexOf('rememberResult(event, action.outputDir, metadata)') >
  main.indexOf('if (!reviewPasses(review))'));
assert.ok(main.indexOf('stageArtifactForVision(artifact, promotion.approved)') <
  main.indexOf('reviewed = await reviewArtifactFrames(capture.captured'));
const reviewArtifactSource = main.slice(main.indexOf('async function reviewArtifact('),
  main.indexOf('function createRevisionOutputDir('));
assert.ok(reviewArtifactSource.indexOf('coverage = artifactVisionCoverage(') <
  reviewArtifactSource.indexOf('promoteVisionArtifact(staged,'));
assert.match(reviewArtifactSource,
  /assertVisionAction\(action\);\s*promoteVisionArtifact\(staged, artifactStat\.size, artifactSha256\)/);
assert.match(main, /delivery\.file !== desiredBasename/);
assert.match(main, /path\.resolve\(release\.file\) !== promotion\.approved/);
assert.match(main,
  /captionRenderReceipt[\s\S]*\? 'burned' : \(captionReceipt \? 'sidecar'/);
assert.ok(!main.includes(': captionReceipt?.events || []'),
  'sidecar captions must not be presented to still-frame vision as burned text');
const qaBindingSource = main.slice(main.indexOf('function artifactQaReleaseBinding('),
  main.indexOf('function readArtifactQaReport('));
const qaBindingContext = { path };
vm.runInNewContext(`${qaBindingSource}; this.artifactQaReleaseBinding = artifactQaReleaseBinding;`,
  qaBindingContext);
const qaSha = 'a'.repeat(64);
const qaPromotion = {
  key: '9x16', approved: path.resolve('PSE_SHORT_9x16.mp4'),
};
const qaContract = {
  delivery: { file: 'PSE_SHORT_9x16.mp4', bytes: 123, sha256: qaSha },
};
const qaReport = { release: {
  '9x16': { file: qaPromotion.approved, bytes: 123, sha256: qaSha },
} };
assert.strictEqual(qaBindingContext.artifactQaReleaseBinding(
  qaReport, qaContract, qaPromotion, qaSha, 123).file, qaPromotion.approved);
assert.throws(() => qaBindingContext.artifactQaReleaseBinding({
  release: { '16x9': qaReport.release['9x16'] },
}, qaContract, qaPromotion, qaSha, 123), /exact released artifact/,
'the QA release key must match the event finalOutputs key');
assert.throws(() => qaBindingContext.artifactQaReleaseBinding(qaReport, {
  delivery: { ...qaContract.delivery, file: 'wrong.mp4' },
}, qaPromotion, qaSha, 123), /exact released artifact/,
'the QA delivery basename must match the exact desired final path');
assert.match(main, /coverageComplete: true/);
assert.match(main, /VISION_QA_REPORT\.json/);
assert.match(main, /autoeditor-final-vision-qa\/v3/);
assert.match(main, /readArtifactQaReport/);
assert.match(main, /readArtifactCaptions/);
assert.match(main, /artifactCaptionRenderEvents/);
assert.match(main, /artifactAudioQaReceipt/);
assert.match(main, /audioQa\?\.pass === true/);
assert.match(main, /sendVisionCancel/);
assert.match(main, /assertVisionAction/);
assert.match(main, /contract\.mode === 'premium-edl'/);
assert.match(main, /contract\.mode !== 'generic-baseline'/);
assert.match(main, /sidecarBinding\(contract, 'edl', edlReceipt\)/);
assert.match(main, /createRevisionOutputDir\(selectedRoot, revisionInput\)/);
assert.match(main, /priorResult: revisionInput/);
const revisionSource = main.slice(main.indexOf('function createRevisionOutputDir('),
  main.indexOf('function applyLocal('));
const revisionContext = { fs, path };
vm.runInNewContext(`${revisionSource}; this.createRevisionOutputDir = createRevisionOutputDir;`,
  revisionContext);
const revisionFixture = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-revisions-'));
const revisionFixtureReal = fs.realpathSync.native(revisionFixture);
try {
  const prior = path.join(revisionFixture, 'PSE_SHORT_9x16.mp4');
  const priorBytes = Buffer.from('immutable accepted version');
  fs.writeFileSync(prior, priorBytes);
  const firstRevision = revisionContext.createRevisionOutputDir(revisionFixture, prior);
  const secondRevision = revisionContext.createRevisionOutputDir(revisionFixture, prior);
  assert.notStrictEqual(firstRevision, secondRevision,
    'every revision attempt must receive a collision-safe immutable output folder');
  assert.strictEqual(path.dirname(firstRevision), path.join(revisionFixtureReal, 'Revisions'));
  assert.strictEqual(path.dirname(secondRevision), path.join(revisionFixtureReal, 'Revisions'));
  assert.deepStrictEqual(fs.readFileSync(prior), priorBytes,
    'starting or failing a revision must not mutate the prior accepted result');
  assert.notStrictEqual(path.join(firstRevision, path.basename(prior)), prior,
    'a successful revision result path must be distinct for before/after feedback');
  for (const generated of [firstRevision, secondRevision]) {
    const relative = path.relative(revisionFixtureReal, generated);
    assert.ok(relative && !relative.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relative), 'generated revision folders may not escape the selected root');
  }
} finally {
  fs.rmSync(revisionFixture, { recursive: true, force: true });
}
const promotionSource = main.slice(
  main.indexOf('function validateFinalOutputTarget('),
  main.indexOf('function replaceEventArtifactPath('));
const promotionContext = { fs, path, crypto: require('crypto'), Buffer };
vm.runInNewContext(`${promotionSource}; this.artifactPromotionTarget = artifactPromotionTarget; ` +
  'this.stageArtifactForVision = stageArtifactForVision; ' +
  'this.promoteVisionArtifact = promoteVisionArtifact;', promotionContext);
const promotionFixture = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-promotion-'));
try {
  const pending = path.join(promotionFixture, 'PSE_SHORT_9x16.UNVERIFIED.mp4');
  const desired = path.join(promotionFixture, 'PSE_SHORT_9x16.mp4');
  const pendingBytes = Buffer.from('engine and vision verified bytes');
  fs.writeFileSync(pending, pendingBytes);
  const event = {
    output: pending,
    outputs: { '9x16': pending },
    finalOutputs: { '9x16': desired },
  };
  const target = promotionContext.artifactPromotionTarget(event, promotionFixture);
  assert.strictEqual(target.key, '9x16');
  const staged = promotionContext.stageArtifactForVision(
    target.pending, target.approved);
  assert.strictEqual(fs.existsSync(desired), false,
    'the final-looking path must remain absent throughout visual review');
  assert.deepStrictEqual(fs.readFileSync(pending), pendingBytes);
  // Cancel/fail means promotion is never called; the desired path remains absent.
  assert.strictEqual(fs.existsSync(desired), false);
  const pendingSha = require('crypto').createHash('sha256')
    .update(pendingBytes).digest('hex');
  promotionContext.promoteVisionArtifact(staged, pendingBytes.length, pendingSha);
  assert.strictEqual(fs.existsSync(pending), false);
  assert.deepStrictEqual(fs.readFileSync(desired), pendingBytes,
    'only the pass path may expose the exact reviewed bytes at the desired name');

  const fallbackPending = path.join(promotionFixture, 'fallback.UNVERIFIED.mp4');
  const fallbackDesired = path.join(promotionFixture, 'fallback.mp4');
  const fallbackBytes = Buffer.from('reviewed bytes on an exFAT-like folder');
  fs.writeFileSync(fallbackPending, fallbackBytes);
  const fallbackFs = Object.assign(Object.create(fs), {
    linkSync: () => {
      const error = new Error('hard links unsupported');
      error.code = 'EPERM';
      throw error;
    },
  });
  const fallbackContext = {
    fs: fallbackFs, path, crypto: require('crypto'), Buffer,
  };
  vm.runInNewContext(`${promotionSource}; this.promoteVisionArtifact = promoteVisionArtifact;`,
    fallbackContext);
  const fallbackSha = require('crypto').createHash('sha256')
    .update(fallbackBytes).digest('hex');
  fallbackContext.promoteVisionArtifact({
    pending: fallbackPending, approved: fallbackDesired,
  }, fallbackBytes.length, fallbackSha);
  assert.strictEqual(fs.existsSync(fallbackPending), false);
  assert.deepStrictEqual(fs.readFileSync(fallbackDesired), fallbackBytes,
    'unsupported hard links must fall back to an exclusive hash-verified copy');

  const nextPending = path.join(promotionFixture, 'next.UNVERIFIED.mp4');
  fs.writeFileSync(nextPending, Buffer.from('next'));
  assert.throws(() => promotionContext.artifactPromotionTarget({
    output: nextPending,
    outputs: { '9x16': nextPending },
    finalOutputs: { '16x9': path.join(promotionFixture, 'next.mp4') },
  }, promotionFixture), /keys do not match/);
  assert.throws(() => promotionContext.artifactPromotionTarget({
    output: nextPending,
    outputs: { '9x16': nextPending },
    finalOutputs: { '9x16': path.join(path.dirname(promotionFixture), 'escape.mp4') },
  }, promotionFixture), /unsafe/);
  const collision = path.join(promotionFixture, 'collision.mp4');
  fs.writeFileSync(collision, Buffer.from('existing'));
  assert.throws(() => promotionContext.artifactPromotionTarget({
    output: nextPending,
    outputs: { '9x16': nextPending },
    finalOutputs: { '9x16': collision },
  }, promotionFixture), /already exists/);
} finally {
  fs.rmSync(promotionFixture, { recursive: true, force: true });
}
const requestVisionBody = main.slice(main.indexOf('function requestVision('),
  main.indexOf('function sendVisionCancel('));
assert.ok(requestVisionBody.indexOf("sendVisionCancel(id, 'timeout')") <
  requestVisionBody.indexOf("reject(new Error('the local vision model exceeded"),
  'timeout must reset the renderer worker before the main promise rejects');
const actionRejectBody = main.match(
  /function rejectPendingVisionForAction\(action, message\) \{([\s\S]*?)\n\}/)?.[1] || '';
assert.match(actionRejectBody, /sendVisionCancel\(id, message\)/);
assert.ok(reviewArtifactSource.indexOf(
  'const metadata = await approvedResultMetadata(action)') <
  reviewArtifactSource.indexOf('promoteVisionArtifact(staged,'),
  'all late metadata awaits must finish before the final-looking name is restored');
assert.ok(reviewArtifactSource.indexOf('promoteVisionArtifact(staged,') <
  reviewArtifactSource.indexOf('rememberResult(event, action.outputDir, metadata)'));
const metadataIndex = reviewArtifactSource.indexOf(
  'const metadata = await approvedResultMetadata(action)');
const finalIdentityIndex = reviewArtifactSource.indexOf(
  'await assertVisionArtifactUnchanged(', metadataIndex);
assert.ok(finalIdentityIndex > metadataIndex && finalIdentityIndex <
  reviewArtifactSource.indexOf('promoteVisionArtifact(staged,'),
  'artifact identity must be rechecked after the last metadata await and before promotion');
const identitySource = main.slice(
  main.indexOf('async function assertVisionArtifactUnchanged('),
  main.indexOf('async function sourceManifestSha256('));
const identityContext = {
  fs,
  sha256File: async (file) => require('crypto').createHash('sha256')
    .update(fs.readFileSync(file)).digest('hex'),
};
vm.runInNewContext(
  `${identitySource}; this.assertVisionArtifactUnchanged = assertVisionArtifactUnchanged;`,
  identityContext);
assert.ok(main.indexOf("event.qaPass !== true") <
  main.indexOf('void reviewArtifact(event, action)'));
const retryBody = main.match(
  /function retryRejectedRender\(action, artifact, issue\) \{([\s\S]*?)\n\}/)?.[1] || '';
assert.match(retryBody, /\.\.\.action\.payload/);
assert.match(retryBody, /normalizeApplyRequest\(payload\)/);
assert.match(retryBody, /visionAttempt: priorAttempts \+ 1/);
assert.ok(!retryBody.includes('delete payload.proposal'));
const cancelBody = main.match(
  /async function cancelLocal\(\) \{([\s\S]*?)\n\}/)?.[1] || '';
assert.match(cancelBody, /action\.canceled = true/);
assert.match(cancelBody, /rejectPendingVisionForAction/);
assert.match(cancelBody, /await stopProcessTree\(action\.proc\)/);
assert.ok(cancelBody.indexOf('action.canceled = true') <
  cancelBody.indexOf('await stopProcessTree(action.proc)'));

const renderer = fs.readFileSync(path.join(
  __dirname, '..', 'helper', 'renderer', 'app.js'), 'utf8');
assert.match(renderer, /cachedTranscript:/);
assert.match(renderer, /creativeBrief:/);
assert.match(renderer, /onVisionCancel/);
assert.match(renderer, /resetVisionWorker/);
const preload = fs.readFileSync(path.join(
  __dirname, '..', 'helper', 'preload.js'), 'utf8');
assert.match(preload, /onVisionCancel:.*helper-vision-cancel/);

const worker = fs.readFileSync(path.join(
  __dirname, '..', 'helper', 'vision', 'vision-worker.js'), 'utf8');
assert.match(worker, /mode === 'artifact-quality'/);
assert.match(worker, /productionDesign/);

function reviewJson({ pass = true, issue = '', observedTargetIds = [] } = {}) {
  return JSON.stringify({
    schema: 'autoeditor-artifact-review/v2',
    pass,
    score: pass ? 97 : 40,
    observedTargetIds,
    checks: {
      captions: pass,
      framing: true,
      visualVariety: true,
      graphics: pass,
      transitions: true,
      productionDesign: pass,
    },
    issues: issue ? [issue] : [],
  });
}

(async () => {
  const frames = Array.from({ length: 18 }, (_, index) => ({
    id: `frame-${String(index + 1).padStart(2, '0')}`,
    path: `frame-${String(index + 1).padStart(2, '0')}.jpg`,
    timeSeconds: index,
    targets: [{ id: `target-${String(index + 1).padStart(2, '0')}`,
      category: index === 13 ? 'graphics' : 'timeline' }],
  }));
  const calls = [];
  const caughtDefect = await reviewArtifactFrames(frames, {
    approvedBrief: 'The 12-14 second graphic must be premium quality.',
    requestBatch: async (batch, context, descriptor) => {
      calls.push({ ids: batch.map((frame) => frame.id), context });
      const observedTargetIds = descriptor.frames.flatMap((frame) =>
        frame.targets.map((target) => target.id));
      return batch.some((frame) => frame.timeSeconds === 13)
        ? reviewJson({ pass: false, issue: 'The graphic at 13s is unreadable.',
          observedTargetIds })
        : reviewJson({ observedTargetIds });
    },
  });
  assert.deepStrictEqual(calls.map((call) => call.ids.length), [8, 8, 2]);
  assert.deepStrictEqual(calls.flatMap((call) => call.ids),
    frames.map((frame) => frame.id));
  assert.ok(calls.every((call) => call.ids.length <= 8),
    'every local vision request must preserve the eight-image hard limit');
  assert.strictEqual(caughtDefect.review.pass, false,
    'a defect visible only at 13s must reject the complete artifact');
  assert.match(caughtDefect.review.issues.join(' '), /Batch 2.*13s/);
  assert.deepStrictEqual(caughtDefect.reviewedFrameIds,
    frames.map((frame) => frame.id));
  assert.deepStrictEqual(caughtDefect.reviewedTargetIds,
    frames.flatMap((frame) => frame.targets.map((target) => target.id)));

  const allPassing = await reviewArtifactFrames(frames, {
    requestBatch: async (_batch, _context, descriptor) => reviewJson({
      observedTargetIds: descriptor.frames.flatMap((frame) =>
        frame.targets.map((target) => target.id)),
    }),
  });
  assert.strictEqual(reviewPasses(allPassing.review), true);
  assert.deepStrictEqual(allPassing.batches.map((batch) => batch.frameIds.length),
    [8, 8, 2]);

  const denseFrames = Array.from({ length: 4 }, (_, frameIndex) => ({
    id: `dense-${frameIndex + 1}`, path: `dense-${frameIndex + 1}.jpg`,
    timeSeconds: 13,
    targets: Array.from({ length: 3 }, (_, targetIndex) => ({
      id: `dense-target-${frameIndex * 3 + targetIndex + 1}`,
      category: 'graphics', expectation: 'Verify the exact co-timed graphic.',
    })),
  }));
  const dense = await reviewArtifactFrames(denseFrames, {
    requestBatch: async (_batch, context, descriptor) => {
      const expected = descriptor.frames.flatMap((frame) =>
        frame.targets.map((target) => target.id));
      for (const id of expected) assert.ok(context.includes(id));
      return reviewJson({ observedTargetIds: expected });
    },
  });
  assert.strictEqual(reviewPasses(dense.review), true);
  assert.deepStrictEqual(dense.reviewedTargetIds,
    denseFrames.flatMap((frame) => frame.targets.map((target) => target.id)),
  'more than eight co-timed targets must be chunked and explicitly acknowledged');

  const identityFixture = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-identity-'));
  try {
    const identityFile = path.join(identityFixture, 'artifact.UNVERIFIED.mp4');
    fs.writeFileSync(identityFile, Buffer.from('reviewed bytes'));
    const identityStat = fs.statSync(identityFile);
    const identitySha = require('crypto').createHash('sha256')
      .update(fs.readFileSync(identityFile)).digest('hex');
    // Models a mutation while approvedResultMetadata(action) was awaiting.
    fs.writeFileSync(identityFile, Buffer.from('different unreviewed bytes'));
    await assert.rejects(() => identityContext.assertVisionArtifactUnchanged(
      identityFile, identityStat, identitySha), /changed during final visual QA/);
  } finally {
    fs.rmSync(identityFixture, { recursive: true, force: true });
  }

  const missingTarget = await reviewArtifactFrames(frames.slice(0, 2), {
    requestBatch: async (_batch, _context, descriptor) => {
      const expected = descriptor.frames.flatMap((frame) =>
        frame.targets.map((target) => target.id));
      return reviewJson({ observedTargetIds: expected.slice(0, -1) });
    },
  });
  assert.strictEqual(reviewPasses(missingTarget.review), false,
    'a missing target acknowledgement must fail closed');
  assert.deepStrictEqual(missingTarget.reviewedTargetIds, ['target-01']);
  const extraTarget = await reviewArtifactFrames(frames.slice(0, 2), {
    requestBatch: async (_batch, _context, descriptor) => reviewJson({
      observedTargetIds: [
        ...descriptor.frames.flatMap((frame) =>
          frame.targets.map((target) => target.id)),
        'not-in-this-batch',
      ],
    }),
  });
  assert.strictEqual(reviewPasses(extraTarget.review), false,
    'an extra target acknowledgement must fail closed');

  await assert.rejects(() => reviewArtifactFrames(frames, {
    requestBatch: async (_batch, _context, descriptor) => {
      if (descriptor.number === 3) throw new Error('vision worker stopped');
      return reviewJson({
        observedTargetIds: descriptor.frames.flatMap((frame) =>
          frame.targets.map((target) => target.id)),
      });
    },
  }), (error) => {
    assert.match(error.message, /batch 3 failed/);
    assert.deepStrictEqual(error.visionProgress.reviewedFrameIds,
      frames.slice(0, 16).map((frame) => frame.id));
    assert.deepStrictEqual(error.visionProgress.reviewedTargetIds,
      frames.slice(0, 16).flatMap((frame) =>
        frame.targets.map((target) => target.id)));
    return true;
  });

  console.log('artifact quality contracts passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
