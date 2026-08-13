'use strict';

const {
  ASSERTION_CLASSES,
  BACKENDS,
  LABELS,
  REQUIRED_POLICY,
  SUBJECTIVE_ASSERTION_CLASSES,
  THRESHOLDS,
} = require('../../helper/lib/semantic-visual-qualification');

const WORKSPACE_SCHEMA = 'autoeditor-semantic-visual-training-workspace/v1';
const INVENTORY_SCHEMA = 'autoeditor-semantic-visual-hardware-inventory/v1';
const LABEL_RECORD_SCHEMA = 'autoeditor-semantic-visual-label-record/v1';
const SPLIT_REPORT_SCHEMA = 'autoeditor-semantic-visual-split-report/v1';
const BLOCKED_REPORT_SCHEMA = 'autoeditor-semantic-visual-blocked-report/v1';

const TRAINING_HARDWARE_FLOOR = Object.freeze({
  minRamBytes: 32 * 1024 * 1024 * 1024,
  minDedicatedVramBytes: 16 * 1024 * 1024 * 1024,
  minFreeDiskBytes: 80 * 1024 * 1024 * 1024,
});

function qualificationCaseBudget() {
  const perClass = REQUIRED_POLICY.minimumCasesPerQualificationClass;
  return Object.freeze({
    classes: [...ASSERTION_CLASSES],
    perClass,
    qualificationCases: ASSERTION_CLASSES.length * (
      perClass.clean + perClass.defect + perClass.ambiguous),
    backends: [...BACKENDS],
    repetitionsPerBackend: REQUIRED_POLICY.repetitionsPerBackend,
    thresholds: { ...THRESHOLDS },
  });
}

module.exports = {
  ASSERTION_CLASSES,
  BACKENDS,
  BLOCKED_REPORT_SCHEMA,
  INVENTORY_SCHEMA,
  LABEL_RECORD_SCHEMA,
  LABELS,
  REQUIRED_POLICY,
  SPLIT_REPORT_SCHEMA,
  SUBJECTIVE_ASSERTION_CLASSES,
  THRESHOLDS,
  TRAINING_HARDWARE_FLOOR,
  WORKSPACE_SCHEMA,
  qualificationCaseBudget,
};
