'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const PreferenceForm = require('../helper/renderer/preference-form');

assert.strictEqual(PreferenceForm.parseTimestamp('00:12.345'), 12345);
assert.strictEqual(PreferenceForm.parseTimestamp('01:02:03.004'), 3723004);
assert.deepStrictEqual(PreferenceForm.parseTimecodes(
  'before | 00:12.000 | 00:15.500 | captions | Covers the face\n' +
  'after | 20 | 21.250 | audio | Dialogue is cleaner'), [{
  artifact: 'before', startMs: 12000, endMs: 15500,
  category: 'captions', note: 'Covers the face',
}, {
  artifact: 'after', startMs: 20000, endMs: 21250,
  category: 'audio', note: 'Dialogue is cleaner',
}]);
assert.throws(() => PreferenceForm.parseTimecodes(''), /at least one/);
assert.throws(() => PreferenceForm.parseTimecodes(
  'before | 5 | 4 | captions | bad range'), /ends before/);
assert.throws(() => PreferenceForm.parseTimecodes(
  'before | 1 | 2 | unsupported | note'), /unsupported category/);

assert.strictEqual(PreferenceForm.resultTarget(
  ['C:\\new-source.mov'], 'C:\\old-result.mp4'), '',
'new attachments must never target a prior result');
assert.strictEqual(PreferenceForm.resultTarget([], 'C:\\old-result.mp4'),
  'C:\\old-result.mp4');
assert.deepStrictEqual(PreferenceForm.comparisonPair({
  resultPath: 'C:\\prior.mp4',
}, 'C:\\revision.mp4'), {
  beforeResultPath: 'C:\\prior.mp4',
  afterResultPath: 'C:\\revision.mp4',
});
assert.strictEqual(PreferenceForm.comparisonPair({}, 'C:\\first.mp4'), null,
  'an initial render must not expose preference feedback');

const helperRoot = path.join(__dirname, '..', 'helper');
const main = fs.readFileSync(path.join(helperRoot, 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(helperRoot, 'preload.js'), 'utf8');
const renderer = fs.readFileSync(path.join(helperRoot, 'renderer', 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(helperRoot, 'renderer', 'index.html'), 'utf8');

assert.match(main, /preference-journal\.enc/);
assert.match(main, /preference-profile-key\.enc/);
assert.match(main, /safeStorage\.encryptString\(plain\)/);
assert.match(main, /safeStorage\.decryptString/);
assert.match(main, /crypto\.createHmac\('sha256', key\)/);
assert.match(main, /appendPreferenceRecord\(journal, payload\)/);
assert.match(main, /buildEditingContext\(loadPreferenceJournal\(\)/);
assert.match(main, /historyWithPreferenceContext\(request\.history, preferenceContext\)/);
assert.match(main, /ipcMain\.handle\('helper:save-preference-feedback'/);
assert.strictEqual((main.match(/appendPreferenceRecord\(/g) || []).length, 1,
  'no implicit render/QA path may append preference records');
assert.ok(!main.includes('sourcePath:'), 'raw source paths must not enter the journal payload');
assert.ok(!main.includes('accountId:'), 'raw account IDs must not enter the journal payload');

assert.match(preload, /savePreferenceFeedback: \(feedback\)/);
assert.match(renderer, /save-preference-feedback.*addEventListener\('click'/s);
assert.match(renderer, /window\.helper\.savePreferenceFeedback\(/);
const invalidateBody = renderer.match(
  /function invalidateAttachmentAnalysis\(\) \{([\s\S]*?)\n\}/)?.[1] || '';
for (const sourceBoundReset of [
  "app.resultPath = ''", "app.transcript = ''", 'app.proposal = null',
  "app.proposalBrief = ''", "app.proposalTargetResultPath = ''",
  'app.lastRenderPayload = null', 'hidePreferenceFeedback()',
]) {
  assert.ok(invalidateBody.includes(sourceBoundReset),
    `attachment changes must clear ${sourceBoundReset}`);
}
assert.ok(!invalidateBody.includes('app.outputDir'),
  'attachment changes must preserve the selected output folder');
assert.ok(!invalidateBody.includes('settings'),
  'attachment changes must preserve settings');
assert.match(renderer,
  /targetResultPath: PreferenceForm\.resultTarget\(attachments, app\.resultPath\)/);
assert.strictEqual((renderer.match(/savePreferenceFeedback\(/g) || []).length, 1,
  'the explicit Save button must be the only renderer submission path');

assert.match(html, /id="preference-feedback" class="preference-feedback hidden"/);
assert.match(html, /id="feedback-consent" type="checkbox"/);
assert.ok(!html.includes('id="feedback-consent" type="checkbox" checked'));
assert.match(html, /AutoEditor will not learn from renders, retries, watch time, or silence/);
assert.match(html, /<script src="preference-form\.js"><\/script>/);

console.log('preference integration contracts passed');
