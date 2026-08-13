'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  ASSERTION_CLASSES,
  REQUIRED_POLICY,
  SUBJECTIVE_ASSERTION_CLASSES,
} = require('../scripts/semantic-visual-training/contract');
const {
  qualificationCoverage,
  splitDisjointness,
  validateLabelRecord,
} = require('../scripts/semantic-visual-training/labels');
const {
  FIXTURELESS_CHECKS,
} = require('../helper/lib/runtime-capability-check-runner');
const runnerSource = fs.readFileSync(
  path.join(__dirname, '..', 'helper', 'lib', 'runtime-capability-check-runner.js'),
  'utf8');

assert.deepEqual(FIXTURELESS_CHECKS, ['visual_quality_analysis']);
assert.match(runnerSource,
  /const FIXTURELESS_CHECKS = new Set\(\[\s*'visual_quality_analysis',\s*\]\)/,
  'visual_quality_analysis must stay fixtureless until a sealed qualification exists');
assert.ok(!runnerSource.includes("FIXTURELESS_CHECKS = new Set([])"),
  'do not empty FIXTURELESS_CHECKS to turn policy checks green');

assert.deepEqual(ASSERTION_CLASSES, [
  'target', 'captions', 'framing', 'visualVariety', 'graphics',
  'transitions', 'productionDesign',
]);
assert.ok(SUBJECTIVE_ASSERTION_CLASSES.includes('captions'));
assert.ok(!SUBJECTIVE_ASSERTION_CLASSES.includes('target'));
assert.equal(REQUIRED_POLICY.minimumCasesPerQualificationClass.clean, 100);
assert.equal(REQUIRED_POLICY.minimumCasesPerQualificationClass.defect, 100);
assert.equal(REQUIRED_POLICY.minimumCasesPerQualificationClass.ambiguous, 40);

assert.throws(() => validateLabelRecord({
  schema_version: 'autoeditor-semantic-visual-label-record/v1',
  assertion_class: 'captions',
  label: 'clean',
  split: 'development',
  source_id: 'src-a',
  template_id: 'tpl-a',
}), /three blind annotators/);

const records = [{
  schema_version: 'autoeditor-semantic-visual-label-record/v1',
  assertion_class: 'target',
  label: 'clean',
  split: 'development',
  source_id: 'src-a',
  template_id: 'tpl-a',
  annotations: null,
}, {
  schema_version: 'autoeditor-semantic-visual-label-record/v1',
  assertion_class: 'target',
  label: 'defect',
  split: 'qualification',
  source_id: 'src-a',
  template_id: 'tpl-b',
  annotations: null,
}];
records.forEach(validateLabelRecord);
const splits = splitDisjointness(records);
assert.equal(splits.disjoint, false);
assert.deepEqual(splits.source_overlap, ['src-a']);
const coverage = qualificationCoverage(records);
assert.equal(coverage.complete, false);
assert.ok(coverage.gaps.some((gap) =>
  gap.assertion_class === 'captions' && gap.missing === 100));

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'svq-train-'));
try {
  const { saveAnnotation } = require(
    '../scripts/semantic-visual-training/labeler/server');
  const record = saveAnnotation(root, {
    annotator_id: 'ann-a',
    role: 'annotator',
    assertion_class: 'framing',
    split: 'development',
    source_id: 'src-b',
    template_id: 'tpl-c',
    label: 'defect',
    assertion: 'The framing clips the speaker.',
    asset: { sha256: 'a'.repeat(64), relative_path: 'inbox/x.jpg' },
  });
  assert.equal(record.gold_complete, false);
  assert.ok(fs.readdirSync(path.join(root, 'annotations')).length === 1);
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}

console.log('semantic visual training workflow contracts passed');
