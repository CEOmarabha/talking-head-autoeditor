'use strict';

const assert = require('assert');

const {
  JOURNAL_SCHEMA,
  RECORD_SCHEMA,
  MAX_JOURNAL_BYTES,
  createPreferenceJournal,
  appendPreferenceRecord,
  validatePreferenceJournal,
  serializeForEncryption,
  parsePreferenceJournal,
  isTrainingEligibleRecord,
  retrieveTrainingPreferences,
  getEvaluationRecords,
  buildEditingContext,
} = require('../helper/lib/preference-learning');

const hashes = Object.freeze({
  accountA: 'a'.repeat(64),
  accountB: 'b'.repeat(64),
  projectA: 'c'.repeat(64),
  projectB: 'd'.repeat(64),
  source: 'e'.repeat(64),
  sourceTwo: 'f'.repeat(64),
  beforeOutput: '1'.repeat(64),
  beforePlan: '2'.repeat(64),
  afterOutput: '3'.repeat(64),
  afterPlan: '4'.repeat(64),
  alternateBefore: '5'.repeat(64),
  alternateAfter: '6'.repeat(64),
  alternatePlan: '7'.repeat(64),
});

function explicitFeedback(overrides = {}) {
  return {
    capturedAt: overrides.capturedAt || '2026-08-12T08:00:00.000Z',
    consent: {
      given: overrides.consentGiven ?? true,
      purpose: 'personalization',
      method: 'explicit-pairwise-feedback',
      policyVersion: '2026-08-12',
    },
    split: overrides.split || 'training',
    profile: {
      scope: overrides.scope || 'project',
      accountProfileSha256: overrides.account || hashes.accountA,
      projectProfileSha256: overrides.project || hashes.projectA,
    },
    context: {
      projectType: overrides.projectType || 'short',
      style: overrides.style || 'premium talking head',
      aspectRatio: '9:16',
      locale: 'en-US',
      tags: overrides.tags || ['talking-head', 'high-contrast-captions'],
    },
    artifacts: {
      sourceSha256: overrides.source || hashes.source,
      before: {
        outputSha256: overrides.beforeOutput || hashes.beforeOutput,
        planSha256: overrides.beforePlan || hashes.beforePlan,
        origin: 'system-output',
        reviewStatus: overrides.beforeReview || 'explicit-human-review',
      },
      after: {
        outputSha256: overrides.afterOutput || hashes.afterOutput,
        planSha256: overrides.afterPlan || hashes.afterPlan,
        origin: overrides.afterOrigin || 'system-output',
        reviewStatus: overrides.afterReview || 'explicit-human-review',
      },
    },
    preference: {
      preferred: overrides.preferred || 'after',
      strength: overrides.strength || 5,
      rationale: overrides.rationale ||
        'The after version has readable captions and keeps the speaker unobstructed.',
    },
    defectCategories: overrides.defectCategories || ['captions', 'framing'],
    timecodes: overrides.timecodes || [{
      artifact: 'before',
      startMs: 1200,
      endMs: 3400,
      category: 'captions',
      note: 'Caption overlaps the face and lacks sufficient contrast.',
    }],
  };
}

const empty = createPreferenceJournal();
assert.strictEqual(empty.schema, JOURNAL_SCHEMA);
assert.deepStrictEqual(empty.records, []);
assert.ok(Object.isFrozen(empty));

const trainingPayload = explicitFeedback();
const projectJournal = appendPreferenceRecord(empty, trainingPayload);
assert.strictEqual(empty.records.length, 0, 'append must not mutate the prior journal');
assert.strictEqual(projectJournal.records.length, 1);
assert.ok(Object.isFrozen(projectJournal));
assert.ok(Object.isFrozen(projectJournal.records[0].payload));
assert.strictEqual(projectJournal.records[0].schema, RECORD_SCHEMA);
assert.strictEqual(projectJournal.records[0].sequence, 1);
assert.match(projectJournal.records[0].recordSha256, /^[0-9a-f]{64}$/);
assert.strictEqual(projectJournal.records[0].payload.artifacts.sourceSha256,
  hashes.source);
assert.strictEqual(projectJournal.records[0].payload.artifacts.before.planSha256,
  hashes.beforePlan);
assert.strictEqual(projectJournal.records[0].payload.artifacts.after.outputSha256,
  hashes.afterOutput);
assert.deepStrictEqual(projectJournal.records[0].payload.defectCategories,
  ['captions', 'framing']);
assert.strictEqual(projectJournal.records[0].payload.timecodes[0].startMs, 1200);
assert.strictEqual(isTrainingEligibleRecord(projectJournal.records[0]), true);
assert.strictEqual(validatePreferenceJournal(projectJournal), true);

const encryptedPayloadReady = serializeForEncryption(projectJournal);
assert.strictEqual(typeof encryptedPayloadReady, 'string');
assert.ok(Buffer.byteLength(encryptedPayloadReady, 'utf8') < MAX_JOURNAL_BYTES);
assert.deepStrictEqual(parsePreferenceJournal(encryptedPayloadReady), projectJournal);

const tampered = JSON.parse(encryptedPayloadReady);
tampered.records[0].payload.preference.rationale = 'silently changed';
assert.throws(() => parsePreferenceJournal(JSON.stringify(tampered)),
  /hash does not match/);

assert.throws(() => appendPreferenceRecord(empty,
  explicitFeedback({ consentGiven: false })), /explicit consent/);
assert.throws(() => appendPreferenceRecord(empty,
  explicitFeedback({ beforeReview: 'unreviewed' })), /explicit human review/);
assert.throws(() => appendPreferenceRecord(empty, explicitFeedback({
  afterOutput: hashes.beforeOutput,
})), /before and after outputs must be different/);
assert.throws(() => appendPreferenceRecord(empty, {
  ...explicitFeedback(),
  sourcePath: 'C:\\private\\source.mov',
}), /unsupported or missing fields/);
assert.throws(() => appendPreferenceRecord(empty, explicitFeedback({
  rationale: 'x'.repeat(1201),
})), /at most 1200/);
assert.throws(() => appendPreferenceRecord(empty, explicitFeedback({
  defectCategories: ['audio'],
})), /must also appear in defect categories/);

const unreviewedSystemOutput = JSON.parse(JSON.stringify(projectJournal.records[0]));
unreviewedSystemOutput.payload.artifacts.after.reviewStatus = 'unreviewed';
assert.strictEqual(isTrainingEligibleRecord(unreviewedSystemOutput), false);

let journal = projectJournal;
journal = appendPreferenceRecord(journal, explicitFeedback({
  capturedAt: '2026-08-12T08:01:00.000Z',
  scope: 'account',
  project: hashes.projectB,
  source: hashes.sourceTwo,
  beforeOutput: hashes.alternateBefore,
  beforePlan: hashes.alternatePlan,
  afterOutput: hashes.alternateAfter,
  afterPlan: hashes.afterPlan,
  strength: 3,
  style: 'clean educational',
  tags: ['talking-head'],
}));
journal = appendPreferenceRecord(journal, explicitFeedback({
  capturedAt: '2026-08-12T08:02:00.000Z',
  project: hashes.projectB,
  source: hashes.sourceTwo,
  beforeOutput: hashes.alternateBefore,
  afterOutput: hashes.alternateAfter,
}));
journal = appendPreferenceRecord(journal, explicitFeedback({
  capturedAt: '2026-08-12T08:03:00.000Z',
  split: 'held-out',
  rationale: 'HELD_OUT_MUST_NEVER_ENTER_EDITING_CONTEXT.',
  beforeOutput: hashes.alternateBefore,
  afterOutput: hashes.alternateAfter,
}));
journal = appendPreferenceRecord(journal, explicitFeedback({
  capturedAt: '2026-08-12T08:04:00.000Z',
  split: 'golden',
  rationale: 'GOLDEN_MUST_NEVER_ENTER_EDITING_CONTEXT.',
  beforeOutput: hashes.alternateBefore,
  afterOutput: hashes.alternateAfter,
  afterOrigin: 'reference-output',
}));
journal = appendPreferenceRecord(journal, explicitFeedback({
  capturedAt: '2026-08-12T08:05:00.000Z',
  account: hashes.accountB,
  beforeOutput: hashes.alternateBefore,
  afterOutput: hashes.alternateAfter,
}));

const ranked = retrieveTrainingPreferences(journal, {
  accountProfileSha256: hashes.accountA,
  projectProfileSha256: hashes.projectA,
  projectType: 'short',
  style: 'premium talking head',
  defectCategories: ['captions'],
  tags: ['high-contrast-captions'],
});
assert.strictEqual(ranked.length, 2,
  'only matching project/account training records may be retrieved');
assert.strictEqual(ranked[0].recordSha256, journal.records[0].recordSha256,
  'the exact project/style/defect match must rank first');
assert.strictEqual(ranked[1].payload.profile.scope, 'account');
assert.ok(ranked.every((match) => match.payload.split === 'training'));
assert.ok(ranked.every((match) =>
  match.payload.artifacts.before.reviewStatus === 'explicit-human-review' &&
  match.payload.artifacts.after.reviewStatus === 'explicit-human-review'));
assert.strictEqual(retrieveTrainingPreferences(journal, {
  accountProfileSha256: hashes.accountA,
  projectProfileSha256: hashes.projectA,
}, { limit: 1 }).length, 1);

const heldOut = getEvaluationRecords(journal, 'held-out');
const golden = getEvaluationRecords(journal, 'golden');
assert.strictEqual(heldOut.length, 1);
assert.strictEqual(golden.length, 1);
assert.strictEqual(isTrainingEligibleRecord(heldOut[0]), false);
assert.strictEqual(isTrainingEligibleRecord(golden[0]), false);
assert.throws(() => getEvaluationRecords(journal, 'training'),
  /held-out or golden/);

const editingContext = buildEditingContext(journal, {
  accountProfileSha256: hashes.accountA,
  projectProfileSha256: hashes.projectA,
  projectType: 'short',
}, { maxChars: 700 });
assert.match(editingContext, /Explicit reviewed preferences/);
assert.match(editingContext, /readable captions/);
assert.ok(!editingContext.includes('HELD_OUT_MUST_NEVER_ENTER_EDITING_CONTEXT'));
assert.ok(!editingContext.includes('GOLDEN_MUST_NEVER_ENTER_EDITING_CONTEXT'));
assert.ok(editingContext.length <= 700);

console.log('preference learning contracts passed');
