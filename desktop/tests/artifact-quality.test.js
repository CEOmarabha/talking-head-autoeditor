const assert = require('assert');

const {
  artifactReviewPrompt,
  parseArtifactReview,
  reviewPasses,
} = require('../helper/lib/artifact-quality');
const fs = require('fs');
const path = require('path');

const prompt = artifactReviewPrompt('Use bold captions and purposeful visual changes.');
assert.match(prompt, /caption/i);
assert.match(prompt, /sound design/i);
assert.match(prompt, /transitions/i);
assert.match(prompt, /Return JSON only/i);

const passing = parseArtifactReview(JSON.stringify({
  schema: 'autoeditor-artifact-review/v1',
  pass: true,
  score: 96,
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

for (const raw of [
  '{"pass":true,"score":100}',
  JSON.stringify({
    schema: 'autoeditor-artifact-review/v1', pass: true, score: 96,
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
assert.ok(main.indexOf('stageArtifactForVision(artifact)') <
  main.indexOf('const raw = await requestVision(frames, action'));
assert.ok(main.indexOf('fs.renameSync(staged.pending, staged.approved)') <
  main.indexOf('rememberResult(event, action.outputDir, metadata)'));
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

const worker = fs.readFileSync(path.join(
  __dirname, '..', 'helper', 'vision', 'vision-worker.js'), 'utf8');
assert.match(worker, /mode === 'artifact-quality'/);
assert.match(worker, /productionDesign/);

console.log('artifact quality contracts passed');
