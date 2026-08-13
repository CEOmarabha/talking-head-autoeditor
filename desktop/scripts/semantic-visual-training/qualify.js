'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {
  BLOCKED_REPORT_SCHEMA,
  REQUIRED_POLICY,
  THRESHOLDS,
  qualificationCaseBudget,
} = require('./contract');
const {
  loadWorkspaceRecords,
  qualificationCoverage,
  splitDisjointness,
} = require('./labels');
const { collectInventory } = require('./inventory');

function argument(name, fallback = '') {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || '') : fallback;
}

function screenQwenBakeoff(resultPath) {
  if (!resultPath || !fs.existsSync(resultPath)) return null;
  const result = JSON.parse(fs.readFileSync(resultPath, 'utf8'));
  return {
    path: resultPath,
    schema_version: result.schema_version || '',
    disposition: result.summary?.screen_disposition || '',
    labeled_decisions: result.summary?.labeled_decisions ?? null,
    accepted_decisions: result.summary?.accepted_decisions ?? null,
    abstained_decisions: result.summary?.abstained_decisions ?? null,
    expected_affirmed_recall: result.summary?.expected_affirmed_recall ?? null,
    balanced_recall: result.summary?.balanced_recall ?? null,
    elapsed_ms: result.elapsed_ms ?? null,
    peak_working_set_bytes:
      result.resource?.peak_app_metric_working_set_bytes ?? null,
    remote_requests: result.network?.remote_requests ?? null,
    qualification_limit: result.qualification_limit || null,
  };
}

function buildBlockedReport({ workspace, inventory, candidateScreen }) {
  const records = workspace && fs.existsSync(workspace)
    ? loadWorkspaceRecords(workspace) : [];
  const splits = splitDisjointness(records);
  const coverage = qualificationCoverage(records);
  const budget = qualificationCaseBudget();
  const failures = [];
  if (!inventory.assessment.can_parameter_efficient_train) {
    failures.push(...inventory.assessment.blocking_reasons.map((reason) =>
      `hardware: ${reason}`));
  }
  if (!splits.disjoint) {
    failures.push('development and qualification sources or templates overlap');
  }
  if (!coverage.complete) {
    for (const gap of coverage.gaps) {
      failures.push(
        `${gap.assertion_class}/${gap.label}: ${gap.have}/${gap.need} labeled qualification cases`);
    }
  }
  failures.push('no sealed WebGPU/WASM qualification run exists');
  failures.push('visual_quality_analysis remains in FIXTURELESS_CHECKS');
  return {
    schema_version: BLOCKED_REPORT_SCHEMA,
    capability: 'visual_quality_analysis',
    qualified: false,
    advertised: false,
    policy: REQUIRED_POLICY,
    thresholds: THRESHOLDS,
    budget,
    inventory,
    splits,
    coverage,
    candidate_screens: candidateScreen ? [candidateScreen] : [],
    failures,
    next_actions: [
      'Collect source- and template-disjoint media for every assertion class',
      'Label subjective classes with three blind annotators and a distinct adjudicator',
      'Train only on the development split using parameter-efficient methods on a machine that meets the hardware floor',
      'Export a pinned local ONNX/Transformers.js package',
      'Run the production evaluator three times on WebGPU and three times on WASM with the network disabled',
      'Persist a sealed qualification result only if every gate passes',
    ],
  };
}

function main() {
  const workspace = argument('--workspace');
  const output = argument('--output');
  const bakeoff = argument('--qwen-bakeoff', path.resolve(
    __dirname, '..', '..', '..', '.local-tools',
    'qwen3vl-bakeoff-1ee355f', 'results',
    '20260813T143335Z-ccf84e41', 'result.json'));
  const inventory = collectInventory();
  const report = buildBlockedReport({
    workspace,
    inventory,
    candidateScreen: screenQwenBakeoff(bakeoff),
  });
  const text = `${JSON.stringify(report, null, 2)}\n`;
  if (output) {
    fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
    fs.writeFileSync(path.resolve(output), text);
  }
  process.stdout.write(text);
  process.exitCode = report.qualified ? 0 : 2;
}

if (require.main === module) {
  try { main(); }
  catch (error) {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { buildBlockedReport, screenQwenBakeoff };
