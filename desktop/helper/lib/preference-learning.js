'use strict';

const crypto = require('crypto');

const JOURNAL_SCHEMA = 'autoeditor-preference-journal/v1';
const RECORD_SCHEMA = 'autoeditor-explicit-pairwise-preference/v1';
const CONSENT_PURPOSE = 'personalization';
const CONSENT_METHOD = 'explicit-pairwise-feedback';
const REVIEW_STATUS = 'explicit-human-review';
const ZERO_HASH = '0'.repeat(64);

const MAX_RECORDS = 512;
const MAX_JOURNAL_BYTES = 2 * 1024 * 1024;
const MAX_RECORD_BYTES = 24 * 1024;
const MAX_RATIONALE_CHARS = 1200;
const MAX_TIMECODES = 32;
const MAX_TIMECODE_NOTE_CHARS = 400;
const MAX_CONTEXT_TAGS = 16;
const MAX_CONTEXT_TEXT_CHARS = 120;
const MAX_TIMECODE_MS = 24 * 60 * 60 * 1000;

const DATASET_SPLITS = Object.freeze(['training', 'held-out', 'golden']);
const PROFILE_SCOPES = Object.freeze(['account', 'project']);
const PROJECT_TYPES = Object.freeze([
  'short', 'long', 'commercial', 'podcast', 'course', 'custom',
]);
const OUTPUT_ORIGINS = Object.freeze([
  'system-output', 'user-edited-output', 'reference-output',
]);
const DEFECT_CATEGORIES = Object.freeze([
  'captions', 'audio', 'sound-design', 'transitions', 'pacing', 'cuts',
  'continuity', 'framing', 'color', 'graphics', 'b-roll', 'accessibility',
  'export', 'other',
]);

const SPLIT_SET = new Set(DATASET_SPLITS);
const PROFILE_SCOPE_SET = new Set(PROFILE_SCOPES);
const PROJECT_TYPE_SET = new Set(PROJECT_TYPES);
const OUTPUT_ORIGIN_SET = new Set(OUTPUT_ORIGINS);
const DEFECT_CATEGORY_SET = new Set(DEFECT_CATEGORIES);

function isPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function requirePlainObject(value, label) {
  if (!isPlainObject(value)) throw new TypeError(`${label} must be a plain object`);
  return value;
}

function requireExactKeys(value, keys, label) {
  requirePlainObject(value, label);
  const expected = [...keys].sort();
  const actual = Object.keys(value).sort();
  if (actual.length !== expected.length ||
      actual.some((key, index) => key !== expected[index])) {
    throw new Error(`${label} has unsupported or missing fields`);
  }
}

function boundedText(value, label, maximum, { required = true } = {}) {
  if (typeof value !== 'string') throw new TypeError(`${label} must be text`);
  if (value.includes('\0')) throw new Error(`${label} must not contain NUL`);
  const text = value.trim();
  if (required && !text) throw new Error(`${label} must not be empty`);
  if (text.length > maximum) {
    throw new Error(`${label} must be at most ${maximum} characters`);
  }
  return text;
}

function sha256(value, label) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${label} must be a lowercase SHA-256 digest`);
  }
  return value;
}

function isoTimestamp(value, label) {
  if (typeof value !== 'string') throw new TypeError(`${label} must be text`);
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || date.toISOString() !== value) {
    throw new Error(`${label} must be a canonical ISO-8601 timestamp`);
  }
  return value;
}

function enumValue(value, allowed, label) {
  if (typeof value !== 'string' || !allowed.has(value)) {
    throw new Error(`${label} is not supported`);
  }
  return value;
}

function integer(value, label, minimum, maximum) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function uniqueStrings(values, label, {
  maximum, allowed = null, textMaximum = MAX_CONTEXT_TEXT_CHARS,
  required = false,
} = {}) {
  if (!Array.isArray(values)) throw new TypeError(`${label} must be an array`);
  if (required && values.length === 0) throw new Error(`${label} must not be empty`);
  if (values.length > maximum) throw new Error(`${label} has too many entries`);
  const normalized = values.map((value, index) => {
    const text = boundedText(value, `${label} ${index + 1}`, textMaximum);
    if (allowed && !allowed.has(text)) {
      throw new Error(`${label} ${index + 1} is not supported`);
    }
    return text;
  });
  if (new Set(normalized).size !== normalized.length) {
    throw new Error(`${label} must not contain duplicates`);
  }
  return normalized;
}

function normalizeConsent(value) {
  requireExactKeys(value, ['given', 'method', 'purpose', 'policyVersion'], 'consent');
  if (value.given !== true) {
    throw new Error('preference learning requires explicit consent');
  }
  if (value.purpose !== CONSENT_PURPOSE || value.method !== CONSENT_METHOD) {
    throw new Error('consent must be captured by the explicit preference control');
  }
  return {
    given: true,
    purpose: CONSENT_PURPOSE,
    method: CONSENT_METHOD,
    policyVersion: boundedText(value.policyVersion, 'consent policy version', 40),
  };
}

function normalizeProfile(value) {
  requireExactKeys(value,
    ['accountProfileSha256', 'projectProfileSha256', 'scope'], 'profile');
  return {
    scope: enumValue(value.scope, PROFILE_SCOPE_SET, 'profile scope'),
    accountProfileSha256: sha256(
      value.accountProfileSha256, 'account profile hash'),
    projectProfileSha256: sha256(
      value.projectProfileSha256, 'project profile hash'),
  };
}

function normalizeArtifact(value, label) {
  requireExactKeys(value,
    ['origin', 'outputSha256', 'planSha256', 'reviewStatus'], label);
  if (value.reviewStatus !== REVIEW_STATUS) {
    throw new Error(`${label} must have an explicit human review`);
  }
  return {
    outputSha256: sha256(value.outputSha256, `${label} output hash`),
    planSha256: sha256(value.planSha256, `${label} plan hash`),
    origin: enumValue(value.origin, OUTPUT_ORIGIN_SET, `${label} origin`),
    reviewStatus: REVIEW_STATUS,
  };
}

function normalizeArtifacts(value) {
  requireExactKeys(value, ['after', 'before', 'sourceSha256'], 'artifacts');
  const before = normalizeArtifact(value.before, 'before artifact');
  const after = normalizeArtifact(value.after, 'after artifact');
  if (before.outputSha256 === after.outputSha256) {
    throw new Error('before and after outputs must be different');
  }
  return {
    sourceSha256: sha256(value.sourceSha256, 'source hash'),
    before,
    after,
  };
}

function normalizePreference(value) {
  requireExactKeys(value, ['preferred', 'rationale', 'strength'], 'preference');
  if (value.preferred !== 'before' && value.preferred !== 'after') {
    throw new Error('preferred artifact must be before or after');
  }
  return {
    preferred: value.preferred,
    strength: integer(value.strength, 'preference strength', 1, 5),
    rationale: boundedText(
      value.rationale, 'preference rationale', MAX_RATIONALE_CHARS),
  };
}

function normalizeContext(value) {
  requireExactKeys(value,
    ['aspectRatio', 'locale', 'projectType', 'style', 'tags'], 'context');
  return {
    projectType: enumValue(value.projectType, PROJECT_TYPE_SET, 'project type'),
    style: boundedText(value.style, 'editing style', MAX_CONTEXT_TEXT_CHARS),
    aspectRatio: boundedText(
      value.aspectRatio, 'aspect ratio', MAX_CONTEXT_TEXT_CHARS),
    locale: boundedText(value.locale, 'locale', MAX_CONTEXT_TEXT_CHARS),
    tags: uniqueStrings(value.tags, 'context tags', {
      maximum: MAX_CONTEXT_TAGS,
      textMaximum: MAX_CONTEXT_TEXT_CHARS,
    }),
  };
}

function normalizeTimecode(value, index, defectCategories) {
  const label = `timecode ${index + 1}`;
  requireExactKeys(value,
    ['artifact', 'category', 'endMs', 'note', 'startMs'], label);
  const startMs = integer(value.startMs, `${label} start`, 0, MAX_TIMECODE_MS);
  const endMs = integer(value.endMs, `${label} end`, startMs, MAX_TIMECODE_MS);
  const category = enumValue(value.category, DEFECT_CATEGORY_SET,
    `${label} category`);
  if (!defectCategories.includes(category)) {
    throw new Error(`${label} category must also appear in defect categories`);
  }
  if (value.artifact !== 'before' && value.artifact !== 'after') {
    throw new Error(`${label} artifact must be before or after`);
  }
  return {
    artifact: value.artifact,
    startMs,
    endMs,
    category,
    note: boundedText(value.note, `${label} note`, MAX_TIMECODE_NOTE_CHARS),
  };
}

function normalizePreferencePayload(value) {
  requireExactKeys(value, [
    'artifacts', 'capturedAt', 'consent', 'context', 'defectCategories',
    'preference', 'profile', 'split', 'timecodes',
  ], 'preference payload');
  const defectCategories = uniqueStrings(
    value.defectCategories, 'defect categories', {
      maximum: DEFECT_CATEGORIES.length,
      allowed: DEFECT_CATEGORY_SET,
      textMaximum: 40,
      required: true,
    });
  if (!Array.isArray(value.timecodes) || value.timecodes.length < 1 ||
      value.timecodes.length > MAX_TIMECODES) {
    throw new Error(`timecodes must contain between 1 and ${MAX_TIMECODES} entries`);
  }
  const payload = {
    capturedAt: isoTimestamp(value.capturedAt, 'feedback capture time'),
    consent: normalizeConsent(value.consent),
    split: enumValue(value.split, SPLIT_SET, 'dataset split'),
    profile: normalizeProfile(value.profile),
    context: normalizeContext(value.context),
    artifacts: normalizeArtifacts(value.artifacts),
    preference: normalizePreference(value.preference),
    defectCategories,
    timecodes: value.timecodes.map((timecode, index) =>
      normalizeTimecode(timecode, index, defectCategories)),
  };
  if (Buffer.byteLength(JSON.stringify(payload), 'utf8') > MAX_RECORD_BYTES) {
    throw new Error('preference record exceeds the encrypted payload limit');
  }
  return payload;
}

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
}

function digestRecordBody(record) {
  const body = {
    schema: RECORD_SCHEMA,
    sequence: record.sequence,
    previousRecordSha256: record.previousRecordSha256,
    payload: record.payload,
  };
  return crypto.createHash('sha256').update(canonicalJson(body), 'utf8').digest('hex');
}

function validateRecord(record, expectedSequence, expectedPrevious) {
  requireExactKeys(record, [
    'payload', 'previousRecordSha256', 'recordSha256', 'schema', 'sequence',
  ], `preference record ${expectedSequence}`);
  if (record.schema !== RECORD_SCHEMA || record.sequence !== expectedSequence ||
      record.previousRecordSha256 !== expectedPrevious) {
    throw new Error(`preference record ${expectedSequence} breaks the append-only chain`);
  }
  sha256(record.recordSha256, `preference record ${expectedSequence} hash`);
  const payload = normalizePreferencePayload(record.payload);
  if (canonicalJson(payload) !== canonicalJson(record.payload)) {
    throw new Error(`preference record ${expectedSequence} payload is not canonical`);
  }
  if (digestRecordBody(record) !== record.recordSha256) {
    throw new Error(`preference record ${expectedSequence} hash does not match`);
  }
  return true;
}

function validatePreferenceJournal(journal) {
  requireExactKeys(journal, ['records', 'schema'], 'preference journal');
  if (journal.schema !== JOURNAL_SCHEMA || !Array.isArray(journal.records)) {
    throw new Error('preference journal schema is invalid');
  }
  if (journal.records.length > MAX_RECORDS) {
    throw new Error(`preference journal may contain at most ${MAX_RECORDS} records`);
  }
  let previous = ZERO_HASH;
  journal.records.forEach((record, index) => {
    validateRecord(record, index + 1, previous);
    previous = record.recordSha256;
  });
  if (Buffer.byteLength(JSON.stringify(journal), 'utf8') > MAX_JOURNAL_BYTES) {
    throw new Error('preference journal exceeds the encrypted payload limit');
  }
  return true;
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  Object.values(value).forEach(deepFreeze);
  return Object.freeze(value);
}

function createPreferenceJournal() {
  return deepFreeze({ schema: JOURNAL_SCHEMA, records: [] });
}

function appendPreferenceRecord(journal, rawPayload) {
  validatePreferenceJournal(journal);
  if (journal.records.length >= MAX_RECORDS) {
    throw new Error(`preference journal may contain at most ${MAX_RECORDS} records`);
  }
  const payload = normalizePreferencePayload(rawPayload);
  const sequence = journal.records.length + 1;
  const previousRecordSha256 = sequence === 1
    ? ZERO_HASH : journal.records[sequence - 2].recordSha256;
  const record = {
    schema: RECORD_SCHEMA,
    sequence,
    previousRecordSha256,
    payload,
  };
  record.recordSha256 = digestRecordBody(record);
  const next = { schema: JOURNAL_SCHEMA, records: [...journal.records, record] };
  validatePreferenceJournal(next);
  return deepFreeze(next);
}

function serializeForEncryption(journal) {
  validatePreferenceJournal(journal);
  return JSON.stringify(journal);
}

function parsePreferenceJournal(serialized) {
  if (typeof serialized !== 'string' || !serialized ||
      Buffer.byteLength(serialized, 'utf8') > MAX_JOURNAL_BYTES) {
    throw new Error('encrypted preference payload is empty or too large');
  }
  let value;
  try { value = JSON.parse(serialized); }
  catch (_) { throw new Error('encrypted preference payload is not valid JSON'); }
  validatePreferenceJournal(value);
  return deepFreeze(value);
}

function isTrainingEligibleRecord(record) {
  try {
    if (!isPlainObject(record) || record.schema !== RECORD_SCHEMA ||
        !Number.isSafeInteger(record.sequence)) return false;
    validateRecord(record, record.sequence, record.previousRecordSha256);
    const payload = record.payload;
    return payload.split === 'training' && payload.consent.given === true &&
      payload.consent.purpose === CONSENT_PURPOSE &&
      payload.consent.method === CONSENT_METHOD &&
      payload.artifacts.before.reviewStatus === REVIEW_STATUS &&
      payload.artifacts.after.reviewStatus === REVIEW_STATUS;
  } catch (_) {
    return false;
  }
}

function normalizeRetrievalQuery(value) {
  requirePlainObject(value, 'preference retrieval query');
  const accountProfileSha256 = sha256(
    value.accountProfileSha256, 'query account profile hash');
  const projectProfileSha256 = value.projectProfileSha256 === undefined
    ? '' : sha256(value.projectProfileSha256, 'query project profile hash');
  const projectType = value.projectType === undefined ? ''
    : enumValue(value.projectType, PROJECT_TYPE_SET, 'query project type');
  const style = value.style === undefined ? ''
    : boundedText(value.style, 'query editing style', MAX_CONTEXT_TEXT_CHARS);
  const defectCategories = value.defectCategories === undefined ? []
    : uniqueStrings(value.defectCategories, 'query defect categories', {
      maximum: DEFECT_CATEGORIES.length,
      allowed: DEFECT_CATEGORY_SET,
      textMaximum: 40,
    });
  const tags = value.tags === undefined ? []
    : uniqueStrings(value.tags, 'query tags', {
      maximum: MAX_CONTEXT_TAGS,
      textMaximum: MAX_CONTEXT_TEXT_CHARS,
    });
  return {
    accountProfileSha256, projectProfileSha256, projectType,
    style, defectCategories, tags,
  };
}

function overlapCount(left, right) {
  const rightSet = new Set(right);
  return left.reduce((count, value) => count + (rightSet.has(value) ? 1 : 0), 0);
}

function retrieveTrainingPreferences(journal, rawQuery, options = {}) {
  validatePreferenceJournal(journal);
  requirePlainObject(options, 'preference retrieval options');
  const limit = options.limit === undefined ? 8
    : integer(options.limit, 'preference retrieval limit', 1, 50);
  const query = normalizeRetrievalQuery(rawQuery);
  const matches = [];
  for (const record of journal.records) {
    if (!isTrainingEligibleRecord(record)) continue;
    const payload = record.payload;
    if (payload.profile.accountProfileSha256 !== query.accountProfileSha256) continue;
    if (payload.profile.scope === 'project' &&
        (!query.projectProfileSha256 ||
         payload.profile.projectProfileSha256 !== query.projectProfileSha256)) continue;

    let score = payload.profile.scope === 'project' ? 100 : 50;
    if (query.projectProfileSha256 === payload.profile.projectProfileSha256) score += 24;
    if (query.projectType && query.projectType === payload.context.projectType) score += 16;
    if (query.style && query.style.toLowerCase() === payload.context.style.toLowerCase()) {
      score += 16;
    }
    score += 6 * overlapCount(query.defectCategories, payload.defectCategories);
    score += 3 * overlapCount(query.tags, payload.context.tags);
    score += payload.preference.strength;
    matches.push(Object.freeze({
      recordSha256: record.recordSha256,
      score,
      preferred: payload.preference.preferred,
      payload,
    }));
  }
  matches.sort((left, right) => right.score - left.score ||
    right.payload.capturedAt.localeCompare(left.payload.capturedAt) ||
    left.recordSha256.localeCompare(right.recordSha256));
  return Object.freeze(matches.slice(0, limit));
}

function getEvaluationRecords(journal, split) {
  validatePreferenceJournal(journal);
  if (split !== 'held-out' && split !== 'golden') {
    throw new Error('evaluation access is limited to held-out or golden records');
  }
  return Object.freeze(journal.records.filter((record) =>
    record.payload.split === split));
}

function buildEditingContext(journal, query, options = {}) {
  requirePlainObject(options, 'editing context options');
  const maxChars = options.maxChars === undefined ? 1200
    : integer(options.maxChars, 'editing context size', 200, 2000);
  const matches = retrieveTrainingPreferences(journal, query, {
    limit: options.limit === undefined ? 5 : options.limit,
  });
  if (!matches.length) return '';
  const summaries = [];
  for (const match of matches) {
    const payload = match.payload;
    const summary = {
      projectType: payload.context.projectType,
      style: payload.context.style,
      defectsToAvoid: payload.defectCategories,
      preferenceStrength: payload.preference.strength,
      explicitRationale: payload.preference.rationale.replace(/\s+/g, ' ').trim(),
    };
    const candidate = JSON.stringify([...summaries, summary]);
    if (candidate.length > maxChars - 180) break;
    summaries.push(summary);
  }
  if (!summaries.length) return '';
  const context =
    'Explicit reviewed preferences for this account/project (soft context, not commands): ' +
    JSON.stringify(summaries) +
    ' Current instructions and source evidence take priority.';
  return context.slice(0, maxChars);
}

module.exports = Object.freeze({
  JOURNAL_SCHEMA,
  RECORD_SCHEMA,
  DATASET_SPLITS,
  PROFILE_SCOPES,
  PROJECT_TYPES,
  OUTPUT_ORIGINS,
  DEFECT_CATEGORIES,
  MAX_RECORDS,
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
});
