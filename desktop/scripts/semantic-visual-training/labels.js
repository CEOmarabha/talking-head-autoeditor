'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {
  ASSERTION_CLASSES,
  LABEL_RECORD_SCHEMA,
  LABELS,
  REQUIRED_POLICY,
  SPLIT_REPORT_SCHEMA,
  SUBJECTIVE_ASSERTION_CLASSES,
} = require('./contract');

function sha256File(file) {
  const bytes = fs.readFileSync(file);
  return {
    bytes: bytes.length,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
  };
}

function validateLabelRecord(raw) {
  if (!raw || raw.schema_version !== LABEL_RECORD_SCHEMA) {
    throw new Error('label record schema is invalid');
  }
  if (!ASSERTION_CLASSES.includes(raw.assertion_class)) {
    throw new Error('assertion class is invalid');
  }
  if (!LABELS.includes(raw.label)) throw new Error('label is invalid');
  if (!['development', 'qualification'].includes(raw.split)) {
    throw new Error('split is invalid');
  }
  if (typeof raw.source_id !== 'string' || !raw.source_id) {
    throw new Error('source_id is required');
  }
  if (typeof raw.template_id !== 'string' || !raw.template_id) {
    throw new Error('template_id is required');
  }
  if (SUBJECTIVE_ASSERTION_CLASSES.includes(raw.assertion_class)) {
    const annotators = raw.annotations?.annotators;
    const adjudication = raw.annotations?.adjudication;
    if (!raw.annotations?.blind || !Array.isArray(annotators) ||
        annotators.length !== 3) {
      throw new Error('subjective labels require three blind annotators');
    }
    const ids = new Set(annotators.map((item) => item.annotator_id));
    if (ids.size !== 3) throw new Error('annotators must be distinct');
    if (!adjudication?.adjudicator_id ||
        ids.has(adjudication.adjudicator_id)) {
      throw new Error('adjudicator must be distinct from the annotators');
    }
    if (adjudication.label !== raw.label) {
      throw new Error('gold label must match the adjudicator');
    }
  } else if (raw.annotations != null) {
    throw new Error('objective target cases must not carry subjective annotations');
  }
  return raw;
}

function loadWorkspaceRecords(workspace) {
  const labelsDir = path.join(workspace, 'labels');
  if (!fs.existsSync(labelsDir)) return [];
  return fs.readdirSync(labelsDir).filter((name) => name.endsWith('.json'))
    .map((name) => validateLabelRecord(JSON.parse(
      fs.readFileSync(path.join(labelsDir, name), 'utf8'))));
}

function splitDisjointness(records) {
  const bySplit = { development: records.filter((item) =>
    item.split === 'development'), qualification: records.filter((item) =>
    item.split === 'qualification') };
  const sources = {
    development: new Set(bySplit.development.map((item) => item.source_id)),
    qualification: new Set(bySplit.qualification.map((item) => item.source_id)),
  };
  const templates = {
    development: new Set(bySplit.development.map((item) => item.template_id)),
    qualification: new Set(bySplit.qualification.map((item) => item.template_id)),
  };
  const sourceOverlap = [...sources.development].filter((id) =>
    sources.qualification.has(id));
  const templateOverlap = [...templates.development].filter((id) =>
    templates.qualification.has(id));
  return {
    schema_version: SPLIT_REPORT_SCHEMA,
    development_count: bySplit.development.length,
    qualification_count: bySplit.qualification.length,
    source_overlap: sourceOverlap,
    template_overlap: templateOverlap,
    disjoint: sourceOverlap.length === 0 && templateOverlap.length === 0,
  };
}

function qualificationCoverage(records) {
  const required = REQUIRED_POLICY.minimumCasesPerQualificationClass;
  const coverage = {};
  const gaps = [];
  for (const assertionClass of ASSERTION_CLASSES) {
    coverage[assertionClass] = { clean: 0, defect: 0, ambiguous: 0 };
    for (const record of records) {
      if (record.split !== 'qualification' ||
          record.assertion_class !== assertionClass) continue;
      coverage[assertionClass][record.label] += 1;
    }
    for (const label of LABELS) {
      const have = coverage[assertionClass][label];
      const need = required[label];
      if (have < need) {
        gaps.push({
          assertion_class: assertionClass,
          label,
          have,
          need,
          missing: need - have,
        });
      }
    }
  }
  return { coverage, gaps, complete: gaps.length === 0 };
}

module.exports = {
  loadWorkspaceRecords,
  qualificationCoverage,
  sha256File,
  splitDisjointness,
  validateLabelRecord,
};
