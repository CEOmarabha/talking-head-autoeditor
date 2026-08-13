'use strict';

// Strict JavaScript mirror of autoeditor/sfx_plan.py. This is an inert
// contract/compiler: it validates trusted cue, rights, timeline, anchor, and
// speech facts and emits constant-shape FFmpeg filter primitive tokens. It
// never resolves media paths, composes a command line, or executes a process.

const crypto = require('node:crypto');

const {
  EditPolicyError,
  editPolicySha256,
  validateEditPolicy,
} = require('./edit-policy');

const SFX_CUE_MANIFEST_SCHEMA_VERSION = 'autoeditor-sfx-cue-manifest/v1';
const SFX_PLAN_SCHEMA_VERSION = 'autoeditor-sfx-plan/v1';
const SFX_COMPILE_RECEIPT_SCHEMA_VERSION = 'autoeditor-sfx-compile-receipt/v1';

const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;
const MAX_ASSETS = 512;
const MAX_ANCHORS = 4_096;
const MAX_SPEECH_WINDOWS = 4_096;
const MAX_CUES = 2_048;
const MAX_ASSET_DURATION_MS = 600_000;
const MAX_CUE_DURATION_MS = 300_000;
const MAX_ASSET_BYTES = 1_099_511_627_776;
const DELIVERY_SAMPLE_RATE_HZ = 48_000;
const DELIVERY_CHANNELS = 2;

const SAMPLE_RATES_HZ = Object.freeze([
  8_000, 11_025, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000,
  88_200, 96_000, 176_400, 192_000,
]);
const PROVENANCE_KINDS = Object.freeze([
  'licensed_external', 'project_generated', 'user_supplied',
]);
const LICENSE_BASES = Object.freeze([
  'licensed_external', 'project_owned', 'user_authorized',
]);
const ANCHOR_CATEGORIES = Object.freeze([
  'boundary', 'event', 'interface_feedback',
]);
const CUE_KINDS = Object.freeze([
  'ambience',
  'foley',
  'gameplay_event',
  'impact',
  'interface_feedback',
  'riser',
  'sports_event',
  'transition_accent',
  'whoosh',
]);
const POLICY_DENSITIES = Object.freeze(['dense', 'medium', 'none', 'sparse']);
const POLICY_USAGES = Object.freeze([
  'event_accent_only',
  'forbidden',
  'interface_feedback_only',
  'motivated_only',
  'source_only',
]);
const DUCK_ATTENUATIONS_MILLIDB = Object.freeze([
  6_000, 9_000, 12_000, 18_000, 24_000,
]);

const SAMPLE_RATE_SET = new Set(SAMPLE_RATES_HZ);
const PROVENANCE_SET = new Set(PROVENANCE_KINDS);
const LICENSE_BASIS_SET = new Set(LICENSE_BASES);
const ANCHOR_CATEGORY_SET = new Set(ANCHOR_CATEGORIES);
const CUE_KIND_SET = new Set(CUE_KINDS);
const POLICY_DENSITY_SET = new Set(POLICY_DENSITIES);
const POLICY_USAGE_SET = new Set(POLICY_USAGES);
const DUCK_ATTENUATION_SET = new Set(DUCK_ATTENUATIONS_MILLIDB);

// All exact-key arrays are ASCII-sorted to match Python's sorted key order.
const MANIFEST_KEYS = Object.freeze([
  'anchors',
  'assets',
  'output_channels',
  'output_duration_ms',
  'output_sample_rate_hz',
  'output_timeline_sha256',
  'schema_version',
  'speech_windows',
]);
const ASSET_KEYS = Object.freeze([
  'asset_id',
  'byte_length',
  'channels',
  'duration_ms',
  'license',
  'provenance',
  'sample_rate_hz',
  'sha256',
  'source_ref',
]);
const ASSET_PAYLOAD_KEYS = Object.freeze(ASSET_KEYS.filter((key) => key !== 'asset_id'));
const LICENSE_KEYS = Object.freeze([
  'basis', 'evidence_sha256', 'license_id', 'licensor',
]);
const ANCHOR_KEYS = Object.freeze([
  'anchor_id',
  'category',
  'evidence_end_ms',
  'evidence_sha256',
  'evidence_start_ms',
  'reference_id',
  'time_ms',
]);
const ANCHOR_PAYLOAD_KEYS = Object.freeze(ANCHOR_KEYS.filter((key) => key !== 'anchor_id'));
const SPEECH_KEYS = Object.freeze([
  'end_ms', 'evidence_sha256', 'speech_id', 'start_ms',
]);
const SPEECH_PAYLOAD_KEYS = Object.freeze(SPEECH_KEYS.filter((key) => key !== 'speech_id'));
const PLAN_KEYS = Object.freeze([
  'cue_manifest_sha256',
  'cues',
  'edit_policy_sha256',
  'output_duration_ms',
  'output_timeline_sha256',
  'policy',
  'schema_version',
]);
const POLICY_KEYS = Object.freeze([
  'density',
  'max_cue_count',
  'max_gain_millidb',
  'max_polyphony',
  'profile',
  'speech_effective_gain_ceiling_millidb',
  'usage',
]);
const CUE_KEYS = Object.freeze([
  'asset_id', 'asset_sha256', 'cue_id', 'ducking', 'kind', 'motivation', 'placement',
]);
const CUE_PAYLOAD_KEYS = Object.freeze(CUE_KEYS.filter((key) => key !== 'cue_id'));
const MOTIVATION_KEYS = Object.freeze([
  'anchor_id',
  'anchor_ms',
  'category',
  'evidence_end_ms',
  'evidence_sha256',
  'evidence_start_ms',
  'reference_id',
]);
const PLACEMENT_KEYS = Object.freeze([
  'attack_fade_ms',
  'gain_millidb',
  'release_fade_ms',
  'start_ms',
  'trim_duration_ms',
  'trim_start_ms',
]);
const DUCKING_KEYS = Object.freeze([
  'attack_ms', 'attenuation_millidb', 'end_ms', 'release_ms', 'start_ms',
]);
const RECEIPT_KEYS = Object.freeze([
  'compiled_cues_sha256',
  'cue_count',
  'cue_manifest_sha256',
  'edit_policy_sha256',
  'max_observed_polyphony',
  'millidb_base',
  'mix_primitives_sha256',
  'ordered_asset_ids',
  'ordered_cue_ids',
  'output_channels',
  'output_duration_ms',
  'output_sample_rate_hz',
  'output_timeline_sha256',
  'policy',
  'schema_version',
  'sfx_plan_sha256',
  'speech_overlap_cue_count',
  'time_base',
  'unique_asset_count',
]);
const BASE_KEYS = Object.freeze(['denominator', 'numerator']);

const SHA256 = /^[0-9a-f]{64}$/;
const ASSET_ID = /^sfxasset-[0-9a-f]{64}$/;
const ANCHOR_ID = /^sfxanchor-[0-9a-f]{64}$/;
const SPEECH_ID = /^speech-[0-9a-f]{64}$/;
const CUE_ID = /^sfxcue-[0-9a-f]{64}$/;
const BOUNDARY_REF = /^boundary-[0-9a-f]{64}$/;
const EVENT_REF = /^event-[A-Za-z0-9][A-Za-z0-9._-]{0,94}$/;
const INTERFACE_REF = /^interface-[A-Za-z0-9][A-Za-z0-9._-]{0,90}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$/;
const LICENSOR = /^[A-Za-z0-9][A-Za-z0-9 ._&()-]{0,127}$/;
const SOURCE_REF_PATTERN = '^(project-generated|user-supplied|licensed-external)://' +
  '[A-Za-z0-9][A-Za-z0-9._/-]{0,383}$';
const SOURCE_REF = new RegExp(SOURCE_REF_PATTERN);

const PROVENANCE_LICENSE = Object.freeze({
  project_generated: Object.freeze(['project-generated', 'project_owned']),
  user_supplied: Object.freeze(['user-supplied', 'user_authorized']),
  licensed_external: Object.freeze(['licensed-external', 'licensed_external']),
});
const PROFILE_MAX_POLYPHONY = Object.freeze({
  commercial_product: 3,
  course_tutorial_screencast: 2,
  dialogue_talking_head: 2,
  documentary_narrative: 0,
  gaming: 4,
  montage_meme: 4,
  music_performance: 0,
  podcast_interview: 0,
  real_estate: 2,
  sports_highlights: 4,
  utility_faithful: 0,
  vlog_travel: 3,
  wedding_event: 2,
});
const PROFILE_MAX_GAIN_MILLIDB = Object.freeze({
  commercial_product: 3_000,
  course_tutorial_screencast: 0,
  dialogue_talking_head: 0,
  documentary_narrative: -60_000,
  gaming: 3_000,
  montage_meme: 3_000,
  music_performance: -60_000,
  podcast_interview: -60_000,
  real_estate: 0,
  sports_highlights: 3_000,
  utility_faithful: -60_000,
  vlog_travel: 0,
  wedding_event: -3_000,
});
const DENSITY_MAX_POLYPHONY = Object.freeze({ none: 0, sparse: 1, medium: 2, dense: 4 });
const DENSITY_LOCAL_TEN_SECOND_LIMIT = Object.freeze({
  none: 0, sparse: 2, medium: 5, dense: 10,
});
const DENSITY_PER_ANCHOR_LIMIT = Object.freeze({
  none: 0, sparse: 1, medium: 2, dense: 3,
});
const SPEECH_GAIN_CEILING = Object.freeze({
  none: -9_000,
  supporting: -12_000,
  primary: -15_000,
  verbatim: -18_000,
});
const KIND_MAX_DURATION_MS = Object.freeze({
  ambience: MAX_CUE_DURATION_MS,
  foley: 30_000,
  gameplay_event: 10_000,
  impact: 5_000,
  interface_feedback: 5_000,
  riser: 10_000,
  sports_event: 10_000,
  transition_accent: 10_000,
  whoosh: 10_000,
});
const KIND_OFFSET_RANGE_MS = Object.freeze({
  ambience: Object.freeze([0, 250]),
  foley: Object.freeze([-250, 250]),
  gameplay_event: Object.freeze([-250, 250]),
  impact: Object.freeze([-250, 250]),
  interface_feedback: Object.freeze([-250, 250]),
  riser: Object.freeze([-2_000, 0]),
  sports_event: Object.freeze([-250, 250]),
  transition_accent: Object.freeze([-1_000, 250]),
  whoosh: Object.freeze([-1_000, 250]),
});
const ANCHOR_ALLOWED_KINDS = Object.freeze({
  boundary: new Set(['impact', 'riser', 'transition_accent', 'whoosh']),
  event: new Set([
    'ambience', 'foley', 'gameplay_event', 'impact', 'riser', 'sports_event', 'whoosh',
  ]),
  interface_feedback: new Set(['interface_feedback']),
});
const DUCK_SIDECHAIN_THRESHOLD_TEXT = Object.freeze({
  6000: '0.2511886432',
  9000: '0.1258925412',
  12000: '0.06309573445',
  18000: '0.01584893192',
  24000: '0.003981071706',
});

class SfxPlanError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SfxPlanError';
  }
}

function fail(message) {
  throw new SfxPlanError(message);
}

function asciiCompare(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isDenseArray(value) {
  if (!Array.isArray(value)) return false;
  for (let index = 0; index < value.length; index += 1) {
    if (!Object.prototype.hasOwnProperty.call(value, index)) return false;
  }
  return Reflect.ownKeys(value).every((key) => (
    key === 'length' ||
    (typeof key === 'string' && /^(0|[1-9][0-9]*)$/.test(key) &&
      Number(key) < value.length)
  ));
}

function exactKeys(value, expected, label) {
  if (!isPlainObject(value)) fail(`${label} must be an object`);
  const ownKeys = Reflect.ownKeys(value);
  if (ownKeys.some((key) => typeof key !== 'string')) {
    fail(`${label} has invalid keys (unsupported non-string key)`);
  }
  const actual = ownKeys.sort(asciiCompare);
  if (actual.length !== expected.length ||
      actual.some((key, index) => key !== expected[index])) {
    const actualSet = new Set(actual);
    const expectedSet = new Set(expected);
    const missing = expected.filter((key) => !actualSet.has(key));
    const extra = actual.filter((key) => !expectedSet.has(key));
    const details = [];
    if (missing.length) details.push(`missing ${missing.join(', ')}`);
    if (extra.length) details.push(`unknown ${extra.join(', ')}`);
    fail(`${label} has invalid keys (${details.join('; ')})`);
  }
  return value;
}

function integer(value, label, { minimum = 0, maximum = MAX_SAFE_INTEGER } = {}) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function enumValue(value, choices, label) {
  if (typeof value !== 'string' || !choices.has(value)) fail(`${label} is unsupported`);
  return value;
}

function identifier(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} has an invalid ASCII identifier`);
  }
  return value;
}

function sha256Value(value, label) {
  if (typeof value !== 'string' || !SHA256.test(value)) {
    fail(`${label} must be a full lowercase SHA-256 digest`);
  }
  return value;
}

function safeText(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} must be bounded safe ASCII text`);
  }
  return value;
}

function pythonString(value) {
  let result = '"';
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (character === '"') result += '\\"';
    else if (character === '\\') result += '\\\\';
    else if (character === '\b') result += '\\b';
    else if (character === '\f') result += '\\f';
    else if (character === '\n') result += '\\n';
    else if (character === '\r') result += '\\r';
    else if (character === '\t') result += '\\t';
    else if (codePoint >= 0x20 && codePoint <= 0x7e) result += character;
    else if (codePoint <= 0xffff) {
      result += `\\u${codePoint.toString(16).padStart(4, '0')}`;
    } else {
      const adjusted = codePoint - 0x10000;
      const high = 0xd800 + (adjusted >> 10);
      const low = 0xdc00 + (adjusted & 0x3ff);
      result += `\\u${high.toString(16)}\\u${low.toString(16)}`;
    }
  }
  return `${result}"`;
}

function canonicalJsonData(value, label) {
  function serialize(item) {
    if (item === null) return 'null';
    if (item === true) return 'true';
    if (item === false) return 'false';
    if (typeof item === 'string') return pythonString(item);
    if (typeof item === 'number' && Number.isSafeInteger(item)) return String(item);
    if (isDenseArray(item)) return `[${item.map(serialize).join(',')}]`;
    if (isPlainObject(item)) {
      const keys = Reflect.ownKeys(item);
      if (keys.some((key) => typeof key !== 'string')) fail(`${label} is not canonical JSON`);
      keys.sort(asciiCompare);
      return `{${keys.map((key) => (
        `${pythonString(key)}:${serialize(item[key])}`
      )).join(',')}}`;
    }
    fail(`${label} is not canonical JSON`);
  }
  return serialize(value);
}

function digestCanonical(value, label) {
  return crypto.createHash('sha256')
    .update(canonicalJsonData(value, label), 'utf8')
    .digest('hex');
}

function detach(value) {
  if (Array.isArray(value)) return value.map(detach);
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, detach(item)]));
  }
  return value;
}

function ffmpegSeconds(milliseconds) {
  return `${Math.floor(milliseconds / 1_000)}.${String(milliseconds % 1_000).padStart(3, '0')}`;
}

function ffmpegMillidb(millidb) {
  const sign = millidb < 0 ? '-' : '';
  const absolute = Math.abs(millidb);
  return `${sign}${Math.floor(absolute / 1_000)}.${String(absolute % 1_000).padStart(3, '0')}dB`;
}

function ffmpegChannelLayout(channels) {
  return {
    1: 'mono', 2: 'stereo', 3: '2.1', 4: 'quad',
    5: '5.0', 6: '5.1', 7: '6.1', 8: '7.1',
  }[channels];
}

function copyKeys(value, keys) {
  return Object.fromEntries(keys.map((key) => [key, value[key]]));
}

function referencePattern(category) {
  return {
    boundary: BOUNDARY_REF,
    event: EVENT_REF,
    interface_feedback: INTERFACE_REF,
  }[category];
}

function normalizeLicense(value, provenance, label) {
  const raw = exactKeys(value, LICENSE_KEYS, label);
  const basis = enumValue(raw.basis, LICENSE_BASIS_SET, `${label}.basis`);
  const licenseId = safeText(raw.license_id, SAFE_ID, `${label}.license_id`);
  const licensor = safeText(raw.licensor, LICENSOR, `${label}.licensor`);
  if (licenseId !== licenseId.trim() || licensor !== licensor.trim()) {
    fail(`${label} contains noncanonical surrounding whitespace`);
  }
  const evidence = sha256Value(raw.evidence_sha256, `${label}.evidence_sha256`);
  const expectedBasis = PROVENANCE_LICENSE[provenance][1];
  if (basis !== expectedBasis) fail(`${label}.basis does not match asset provenance`);
  // All allowed characters are ASCII, so lower-case is exactly Python's
  // casefold for this closed surface.
  const licenseIdLower = licenseId.toLowerCase();
  const licensorLower = licensor.toLowerCase();
  const lowered = new Set([licenseIdLower, licensorLower]);
  if (['unknown', 'none', 'unlicensed', 'tbd', 'n/a'].some((item) => lowered.has(item))) {
    fail(`${label} contains a placeholder instead of rights evidence`);
  }
  if (provenance === 'project_generated') {
    if (licenseId !== 'project-generated' || licensor !== 'project') {
      fail(`${label} must identify project-generated ownership exactly`);
    }
  } else if (provenance === 'licensed_external') {
    if (licenseIdLower === 'project-generated' || ['project', 'user'].includes(licensorLower)) {
      fail(`${label} is not valid external license attribution`);
    }
  } else if (licenseIdLower === 'project-generated' || licensor !== 'user') {
    fail(`${label} must identify exact user authorization without claiming project ownership`);
  }
  return {
    basis,
    license_id: licenseId,
    licensor,
    evidence_sha256: evidence,
  };
}

function normalizeAssetPayload(value, label) {
  const raw = exactKeys(value, ASSET_PAYLOAD_KEYS, label);
  const provenance = enumValue(raw.provenance, PROVENANCE_SET, `${label}.provenance`);
  const sourceRef = safeText(raw.source_ref, SOURCE_REF, `${label}.source_ref`);
  const [sourceScheme, sourcePath] = sourceRef.split('://', 2);
  if (sourceScheme !== PROVENANCE_LICENSE[provenance][0]) {
    fail(`${label}.source_ref scheme does not match provenance`);
  }
  if (sourcePath.split('/').some((part) => ['', '.', '..'].includes(part))) {
    fail(`${label}.source_ref contains an unsafe path segment`);
  }
  const sampleRate = integer(raw.sample_rate_hz, `${label}.sample_rate_hz`, {
    minimum: Math.min(...SAMPLE_RATES_HZ), maximum: Math.max(...SAMPLE_RATES_HZ),
  });
  if (!SAMPLE_RATE_SET.has(sampleRate)) fail(`${label}.sample_rate_hz is unsupported`);
  return {
    sha256: sha256Value(raw.sha256, `${label}.sha256`),
    byte_length: integer(raw.byte_length, `${label}.byte_length`, {
      minimum: 1, maximum: MAX_ASSET_BYTES,
    }),
    duration_ms: integer(raw.duration_ms, `${label}.duration_ms`, {
      minimum: 1, maximum: MAX_ASSET_DURATION_MS,
    }),
    sample_rate_hz: sampleRate,
    channels: integer(raw.channels, `${label}.channels`, { minimum: 1, maximum: 8 }),
    source_ref: sourceRef,
    provenance,
    license: normalizeLicense(raw.license, provenance, `${label}.license`),
  };
}

function deriveSfxAssetId(assetWithoutId) {
  const normalized = normalizeAssetPayload(assetWithoutId, 'SFX asset binding');
  return `sfxasset-${digestCanonical(normalized, 'SFX asset binding')}`;
}

function normalizeAnchorPayload(value, label, outputDurationMs) {
  const raw = exactKeys(value, ANCHOR_PAYLOAD_KEYS, label);
  const category = enumValue(raw.category, ANCHOR_CATEGORY_SET, `${label}.category`);
  const referenceId = identifier(
    raw.reference_id, referencePattern(category), `${label}.reference_id`,
  );
  const timeMs = integer(raw.time_ms, `${label}.time_ms`, { maximum: outputDurationMs });
  const evidenceStart = integer(raw.evidence_start_ms, `${label}.evidence_start_ms`, {
    maximum: outputDurationMs,
  });
  const evidenceEnd = integer(raw.evidence_end_ms, `${label}.evidence_end_ms`, {
    maximum: outputDurationMs,
  });
  if (evidenceStart > timeMs || timeMs > evidenceEnd) {
    fail(`${label} evidence interval must contain its exact anchor`);
  }
  return {
    category,
    reference_id: referenceId,
    time_ms: timeMs,
    evidence_start_ms: evidenceStart,
    evidence_end_ms: evidenceEnd,
    evidence_sha256: sha256Value(raw.evidence_sha256, `${label}.evidence_sha256`),
  };
}

function deriveSfxAnchorId(anchorWithoutId, outputDurationMs) {
  const duration = integer(outputDurationMs, 'output_duration_ms', { minimum: 1 });
  const normalized = normalizeAnchorPayload(anchorWithoutId, 'SFX anchor binding', duration);
  return `sfxanchor-${digestCanonical(normalized, 'SFX anchor binding')}`;
}

function normalizeSpeechPayload(value, label, outputDurationMs) {
  const raw = exactKeys(value, SPEECH_PAYLOAD_KEYS, label);
  const start = integer(raw.start_ms, `${label}.start_ms`, { maximum: outputDurationMs });
  const end = integer(raw.end_ms, `${label}.end_ms`, { maximum: outputDurationMs });
  if (end <= start) fail(`${label} must have positive duration`);
  return {
    start_ms: start,
    end_ms: end,
    evidence_sha256: sha256Value(raw.evidence_sha256, `${label}.evidence_sha256`),
  };
}

function deriveSpeechWindowId(speechWithoutId, outputDurationMs) {
  const duration = integer(outputDurationMs, 'output_duration_ms', { minimum: 1 });
  const normalized = normalizeSpeechPayload(
    speechWithoutId, 'speech-window binding', duration,
  );
  return `speech-${digestCanonical(normalized, 'speech-window binding')}`;
}

function validateSfxCueManifest(manifest) {
  const raw = exactKeys(manifest, MANIFEST_KEYS, 'SFX cue manifest');
  if (raw.schema_version !== SFX_CUE_MANIFEST_SCHEMA_VERSION) {
    fail('SFX cue manifest schema_version is unsupported');
  }
  const timelineHash = sha256Value(
    raw.output_timeline_sha256, 'SFX cue manifest.output_timeline_sha256',
  );
  const outputDuration = integer(
    raw.output_duration_ms, 'SFX cue manifest.output_duration_ms', { minimum: 1 },
  );
  const outputRate = integer(
    raw.output_sample_rate_hz, 'SFX cue manifest.output_sample_rate_hz', {
      minimum: Math.min(...SAMPLE_RATES_HZ), maximum: Math.max(...SAMPLE_RATES_HZ),
    },
  );
  if (!SAMPLE_RATE_SET.has(outputRate)) {
    fail('SFX cue manifest.output_sample_rate_hz is unsupported');
  }
  const outputChannels = integer(
    raw.output_channels, 'SFX cue manifest.output_channels', { minimum: 1, maximum: 8 },
  );
  if (outputRate !== DELIVERY_SAMPLE_RATE_HZ || outputChannels !== DELIVERY_CHANNELS) {
    fail('SFX cue manifest output must be the exact 48000 Hz stereo delivery format');
  }

  if (!isDenseArray(raw.assets) || raw.assets.length > MAX_ASSETS) {
    fail('SFX cue manifest.assets has invalid cardinality');
  }
  const assets = [];
  const assetIds = new Set();
  const sourceRefs = new Set();
  const assetHashes = new Set();
  raw.assets.forEach((rawAsset, index) => {
    const label = `SFX cue manifest.assets[${index}]`;
    const item = exactKeys(rawAsset, ASSET_KEYS, label);
    const payload = normalizeAssetPayload(copyKeys(item, ASSET_PAYLOAD_KEYS), label);
    const assetId = identifier(item.asset_id, ASSET_ID, `${label}.asset_id`);
    if (assetId !== deriveSfxAssetId(payload)) {
      fail(`${label}.asset_id does not bind exact asset and rights facts`);
    }
    if (assetIds.has(assetId) || sourceRefs.has(payload.source_ref) ||
        assetHashes.has(payload.sha256)) {
      fail('SFX cue manifest assets must have unique ids, sources, and byte hashes');
    }
    assetIds.add(assetId);
    sourceRefs.add(payload.source_ref);
    assetHashes.add(payload.sha256);
    assets.push({ asset_id: assetId, ...payload });
  });
  const orderedAssetIds = assets.map((asset) => asset.asset_id);
  const expectedAssetIds = [...assetIds].sort(asciiCompare);
  if (orderedAssetIds.some((assetId, index) => assetId !== expectedAssetIds[index])) {
    fail('SFX cue manifest.assets must be ordered by asset_id');
  }

  if (!isDenseArray(raw.anchors) || raw.anchors.length > MAX_ANCHORS) {
    fail('SFX cue manifest.anchors has invalid cardinality');
  }
  const anchors = [];
  const anchorIds = new Set();
  const referenceIds = new Set();
  raw.anchors.forEach((rawAnchor, index) => {
    const label = `SFX cue manifest.anchors[${index}]`;
    const item = exactKeys(rawAnchor, ANCHOR_KEYS, label);
    const payload = normalizeAnchorPayload(
      copyKeys(item, ANCHOR_PAYLOAD_KEYS), label, outputDuration,
    );
    const anchorId = identifier(item.anchor_id, ANCHOR_ID, `${label}.anchor_id`);
    if (anchorId !== deriveSfxAnchorId(payload, outputDuration)) {
      fail(`${label}.anchor_id does not bind exact motivation evidence`);
    }
    if (anchorIds.has(anchorId) || referenceIds.has(payload.reference_id)) {
      fail('SFX cue manifest anchors must have unique ids and references');
    }
    anchorIds.add(anchorId);
    referenceIds.add(payload.reference_id);
    anchors.push({ anchor_id: anchorId, ...payload });
  });
  const expectedAnchors = [...anchors].sort((left, right) => (
    left.time_ms === right.time_ms
      ? asciiCompare(left.anchor_id, right.anchor_id)
      : (left.time_ms < right.time_ms ? -1 : 1)
  ));
  if (anchors.some((anchor, index) => anchor !== expectedAnchors[index])) {
    fail('SFX cue manifest.anchors must be ordered by time_ms then anchor_id');
  }

  if (!isDenseArray(raw.speech_windows) || raw.speech_windows.length > MAX_SPEECH_WINDOWS) {
    fail('SFX cue manifest.speech_windows has invalid cardinality');
  }
  const speechWindows = [];
  const speechIds = new Set();
  let previousEnd = 0;
  raw.speech_windows.forEach((rawSpeech, index) => {
    const label = `SFX cue manifest.speech_windows[${index}]`;
    const item = exactKeys(rawSpeech, SPEECH_KEYS, label);
    const payload = normalizeSpeechPayload(
      copyKeys(item, SPEECH_PAYLOAD_KEYS), label, outputDuration,
    );
    const speechId = identifier(item.speech_id, SPEECH_ID, `${label}.speech_id`);
    if (speechId !== deriveSpeechWindowId(payload, outputDuration)) {
      fail(`${label}.speech_id does not bind exact speech evidence`);
    }
    if (speechIds.has(speechId)) fail('SFX cue manifest speech ids must be unique');
    if (payload.start_ms < previousEnd) {
      fail('SFX cue manifest speech windows must be ordered and non-overlapping');
    }
    speechIds.add(speechId);
    previousEnd = payload.end_ms;
    speechWindows.push({ speech_id: speechId, ...payload });
  });

  return detach({
    schema_version: SFX_CUE_MANIFEST_SCHEMA_VERSION,
    output_timeline_sha256: timelineHash,
    output_duration_ms: outputDuration,
    output_sample_rate_hz: outputRate,
    output_channels: outputChannels,
    assets,
    anchors,
    speech_windows: speechWindows,
  });
}

function canonicalSfxCueManifestJson(manifest) {
  return canonicalJsonData(validateSfxCueManifest(manifest), 'SFX cue manifest');
}

function sfxCueManifestSha256(manifest) {
  return crypto.createHash('sha256')
    .update(canonicalSfxCueManifestJson(manifest), 'utf8')
    .digest('hex');
}

function densityCueLimit(density, outputDurationMs) {
  const member = enumValue(density, POLICY_DENSITY_SET, 'SFX density');
  const duration = integer(outputDurationMs, 'output_duration_ms', { minimum: 1 });
  if (member === 'none') return 0;
  const interval = { sparse: 15_000, medium: 6_000, dense: 3_000 }[member];
  const quotient = Math.floor(duration / interval);
  const ceiling = quotient + (duration % interval === 0 ? 0 : 1);
  return Math.min(MAX_CUES, ceiling);
}

function policyLimits(policy, outputDurationMs) {
  const { profile } = policy;
  if (!Object.prototype.hasOwnProperty.call(PROFILE_MAX_POLYPHONY, profile)) {
    fail('edit policy profile has no closed SFX limits');
  }
  const rule = policy.rules.sfx;
  const { density, usage } = rule;
  let maxCueCount = densityCueLimit(density, outputDurationMs);
  if (['forbidden', 'source_only'].includes(usage)) maxCueCount = 0;
  let maxPolyphony = Math.min(
    PROFILE_MAX_POLYPHONY[profile], DENSITY_MAX_POLYPHONY[density],
  );
  if (maxCueCount === 0) maxPolyphony = 0;
  const dialoguePriority = policy.rules.dialogue.priority;
  return {
    profile,
    density,
    usage,
    max_cue_count: maxCueCount,
    max_polyphony: maxPolyphony,
    max_gain_millidb: PROFILE_MAX_GAIN_MILLIDB[profile],
    speech_effective_gain_ceiling_millidb: SPEECH_GAIN_CEILING[dialoguePriority],
  };
}

function deriveSfxPolicyLimits(editPolicy, outputDurationMs) {
  const duration = integer(outputDurationMs, 'output_duration_ms', { minimum: 1 });
  let policy;
  try {
    policy = validateEditPolicy(editPolicy);
  } catch (error) {
    if (!(error instanceof EditPolicyError)) throw error;
    throw new SfxPlanError('edit policy is invalid', { cause: error });
  }
  if (policy.duration.duration_ms !== duration) {
    fail('edit policy duration does not match the exact SFX output duration');
  }
  return detach(policyLimits(policy, duration));
}

function normalizePolicySnapshot(value, label) {
  const raw = exactKeys(value, POLICY_KEYS, label);
  return {
    profile: safeText(raw.profile, SAFE_ID, `${label}.profile`),
    density: enumValue(raw.density, POLICY_DENSITY_SET, `${label}.density`),
    usage: enumValue(raw.usage, POLICY_USAGE_SET, `${label}.usage`),
    max_cue_count: integer(raw.max_cue_count, `${label}.max_cue_count`, {
      maximum: MAX_CUES,
    }),
    max_polyphony: integer(raw.max_polyphony, `${label}.max_polyphony`, { maximum: 8 }),
    max_gain_millidb: integer(raw.max_gain_millidb, `${label}.max_gain_millidb`, {
      minimum: -60_000, maximum: 6_000,
    }),
    speech_effective_gain_ceiling_millidb: integer(
      raw.speech_effective_gain_ceiling_millidb,
      `${label}.speech_effective_gain_ceiling_millidb`,
      { minimum: -60_000, maximum: 0 },
    ),
  };
}

function normalizeMotivation(value, label) {
  const raw = exactKeys(value, MOTIVATION_KEYS, label);
  const category = enumValue(raw.category, ANCHOR_CATEGORY_SET, `${label}.category`);
  return {
    category,
    anchor_id: identifier(raw.anchor_id, ANCHOR_ID, `${label}.anchor_id`),
    reference_id: identifier(
      raw.reference_id, referencePattern(category), `${label}.reference_id`,
    ),
    anchor_ms: integer(raw.anchor_ms, `${label}.anchor_ms`),
    evidence_start_ms: integer(raw.evidence_start_ms, `${label}.evidence_start_ms`),
    evidence_end_ms: integer(raw.evidence_end_ms, `${label}.evidence_end_ms`),
    evidence_sha256: sha256Value(raw.evidence_sha256, `${label}.evidence_sha256`),
  };
}

function normalizePlacement(value, label) {
  const raw = exactKeys(value, PLACEMENT_KEYS, label);
  return {
    start_ms: integer(raw.start_ms, `${label}.start_ms`),
    trim_start_ms: integer(raw.trim_start_ms, `${label}.trim_start_ms`),
    trim_duration_ms: integer(raw.trim_duration_ms, `${label}.trim_duration_ms`, {
      minimum: 20, maximum: MAX_CUE_DURATION_MS,
    }),
    gain_millidb: integer(raw.gain_millidb, `${label}.gain_millidb`, {
      minimum: -60_000, maximum: 6_000,
    }),
    attack_fade_ms: integer(raw.attack_fade_ms, `${label}.attack_fade_ms`, {
      maximum: 5_000,
    }),
    release_fade_ms: integer(raw.release_fade_ms, `${label}.release_fade_ms`, {
      maximum: 5_000,
    }),
  };
}

function normalizeDucking(value, label) {
  if (value === null) return null;
  const raw = exactKeys(value, DUCKING_KEYS, label);
  const attenuation = integer(
    raw.attenuation_millidb, `${label}.attenuation_millidb`, {
      minimum: Math.min(...DUCK_ATTENUATIONS_MILLIDB),
      maximum: Math.max(...DUCK_ATTENUATIONS_MILLIDB),
    },
  );
  if (!DUCK_ATTENUATION_SET.has(attenuation)) {
    fail(`${label}.attenuation_millidb is not a deterministic v1 preset`);
  }
  return {
    start_ms: integer(raw.start_ms, `${label}.start_ms`),
    end_ms: integer(raw.end_ms, `${label}.end_ms`),
    attenuation_millidb: attenuation,
    attack_ms: integer(raw.attack_ms, `${label}.attack_ms`, { minimum: 1, maximum: 200 }),
    release_ms: integer(raw.release_ms, `${label}.release_ms`, {
      minimum: 1, maximum: 2_000,
    }),
  };
}

function normalizeCuePayload(value, label) {
  const raw = exactKeys(value, CUE_PAYLOAD_KEYS, label);
  return {
    asset_id: identifier(raw.asset_id, ASSET_ID, `${label}.asset_id`),
    asset_sha256: sha256Value(raw.asset_sha256, `${label}.asset_sha256`),
    kind: enumValue(raw.kind, CUE_KIND_SET, `${label}.kind`),
    motivation: normalizeMotivation(raw.motivation, `${label}.motivation`),
    placement: normalizePlacement(raw.placement, `${label}.placement`),
    ducking: normalizeDucking(raw.ducking, `${label}.ducking`),
  };
}

function deriveSfxCueId(cueWithoutId) {
  const normalized = normalizeCuePayload(cueWithoutId, 'SFX cue binding');
  return `sfxcue-${digestCanonical(normalized, 'SFX cue binding')}`;
}

function normalizePlan(plan) {
  const raw = exactKeys(plan, PLAN_KEYS, 'SFX plan');
  if (raw.schema_version !== SFX_PLAN_SCHEMA_VERSION) {
    fail('SFX plan schema_version is unsupported');
  }
  if (!isDenseArray(raw.cues) || raw.cues.length > MAX_CUES) {
    fail('SFX plan.cues has invalid cardinality');
  }
  const cues = [];
  const cueIds = new Set();
  raw.cues.forEach((rawCue, index) => {
    const label = `SFX plan.cues[${index}]`;
    const item = exactKeys(rawCue, CUE_KEYS, label);
    const payload = normalizeCuePayload(copyKeys(item, CUE_PAYLOAD_KEYS), label);
    const cueId = identifier(item.cue_id, CUE_ID, `${label}.cue_id`);
    if (cueId !== deriveSfxCueId(payload)) {
      fail(`${label}.cue_id does not bind the exact cue decision`);
    }
    if (cueIds.has(cueId)) fail('SFX plan cue ids must be unique');
    cueIds.add(cueId);
    cues.push({ cue_id: cueId, ...payload });
  });
  const expectedOrder = [...cues].sort((left, right) => (
    left.placement.start_ms === right.placement.start_ms
      ? asciiCompare(left.cue_id, right.cue_id)
      : (left.placement.start_ms < right.placement.start_ms ? -1 : 1)
  ));
  if (cues.some((cue, index) => cue !== expectedOrder[index])) {
    fail('SFX plan.cues must be ordered by start_ms then cue_id');
  }
  return {
    schema_version: SFX_PLAN_SCHEMA_VERSION,
    cue_manifest_sha256: sha256Value(
      raw.cue_manifest_sha256, 'SFX plan.cue_manifest_sha256',
    ),
    edit_policy_sha256: sha256Value(raw.edit_policy_sha256, 'SFX plan.edit_policy_sha256'),
    output_timeline_sha256: sha256Value(
      raw.output_timeline_sha256, 'SFX plan.output_timeline_sha256',
    ),
    output_duration_ms: integer(raw.output_duration_ms, 'SFX plan.output_duration_ms', {
      minimum: 1,
    }),
    policy: normalizePolicySnapshot(raw.policy, 'SFX plan.policy'),
    cues,
  };
}

function canonicalSfxPlanJson(plan) {
  return canonicalJsonData(normalizePlan(plan), 'SFX plan');
}

function sfxPlanSha256(plan) {
  return crypto.createHash('sha256')
    .update(canonicalSfxPlanJson(plan), 'utf8')
    .digest('hex');
}

function maxPolyphony(intervals) {
  const events = [];
  intervals.forEach(([start, end]) => {
    events.push([start, 1]);
    events.push([end, -1]);
  });
  events.sort((left, right) => {
    if (left[0] !== right[0]) return left[0] < right[0] ? -1 : 1;
    return left[1] - right[1];
  });
  let active = 0;
  let maximum = 0;
  events.forEach(([, delta]) => {
    active += delta;
    maximum = Math.max(maximum, active);
  });
  return maximum;
}

function speechIntersections(startMs, endMs, speechWindows) {
  const intersections = [];
  speechWindows.forEach((speech) => {
    const start = Math.max(startMs, speech.start_ms);
    const end = Math.min(endMs, speech.end_ms);
    if (end > start) intersections.push([start, end]);
  });
  return intersections;
}

function validateSfxPlan(plan, cueManifest, editPolicy) {
  const normalized = normalizePlan(plan);
  const manifest = validateSfxCueManifest(cueManifest);
  let policy;
  let expectedPolicyHash;
  try {
    policy = validateEditPolicy(editPolicy);
    expectedPolicyHash = editPolicySha256(policy);
  } catch (error) {
    if (!(error instanceof EditPolicyError)) throw error;
    throw new SfxPlanError('edit policy is invalid', { cause: error });
  }
  const expectedManifestHash = sfxCueManifestSha256(manifest);
  if (normalized.cue_manifest_sha256 !== expectedManifestHash) {
    fail('SFX plan does not bind the trusted cue manifest');
  }
  if (normalized.edit_policy_sha256 !== expectedPolicyHash) {
    fail('SFX plan does not bind the resolved edit policy');
  }
  if (normalized.output_timeline_sha256 !== manifest.output_timeline_sha256) {
    fail('SFX plan does not bind the trusted output timeline');
  }
  if (normalized.output_duration_ms !== manifest.output_duration_ms) {
    fail('SFX plan does not bind the exact output duration');
  }
  if (policy.duration.duration_ms !== manifest.output_duration_ms) {
    fail('edit policy duration does not match the exact SFX output duration');
  }
  const expectedLimits = policyLimits(policy, manifest.output_duration_ms);
  if (canonicalJsonData(normalized.policy, 'SFX policy') !==
      canonicalJsonData(expectedLimits, 'SFX policy')) {
    fail('SFX plan policy snapshot does not match the resolved edit policy');
  }
  if (normalized.cues.length > expectedLimits.max_cue_count) {
    fail('SFX plan exceeds its policy-derived cue density ceiling');
  }
  if (['forbidden', 'source_only'].includes(expectedLimits.usage) && normalized.cues.length) {
    fail('SFX policy permits no added cue assets');
  }

  const assets = new Map(manifest.assets.map((asset) => [asset.asset_id, asset]));
  const anchors = new Map(manifest.anchors.map((anchor) => [anchor.anchor_id, anchor]));
  const intervals = [];
  const speechIntervals = [];
  const anchorCounts = new Map();
  const usedAssetAnchor = new Set();
  const anchorTimes = [];
  const dialoguePriority = policy.rules.dialogue.priority;

  normalized.cues.forEach((cue, index) => {
    const label = `SFX plan.cues[${index}]`;
    const asset = assets.get(cue.asset_id);
    if (!asset) fail(`${label}.asset_id is absent from the trusted cue manifest`);
    if (cue.asset_sha256 !== asset.sha256) {
      fail(`${label}.asset_sha256 does not match trusted asset bytes`);
    }
    const { motivation } = cue;
    const anchor = anchors.get(motivation.anchor_id);
    if (!anchor) fail(`${label}.motivation.anchor_id is absent from the trusted manifest`);
    const exactMotivation = {
      category: anchor.category,
      anchor_id: anchor.anchor_id,
      reference_id: anchor.reference_id,
      anchor_ms: anchor.time_ms,
      evidence_start_ms: anchor.evidence_start_ms,
      evidence_end_ms: anchor.evidence_end_ms,
      evidence_sha256: anchor.evidence_sha256,
    };
    if (canonicalJsonData(motivation, 'SFX motivation') !==
        canonicalJsonData(exactMotivation, 'SFX motivation')) {
      fail(`${label}.motivation does not copy exact trusted anchor evidence`);
    }
    if (!ANCHOR_ALLOWED_KINDS[anchor.category].has(cue.kind)) {
      fail(`${label}.kind is not motivated by its anchor category`);
    }
    const { usage } = expectedLimits;
    if (usage === 'interface_feedback_only' &&
        (anchor.category !== 'interface_feedback' || cue.kind !== 'interface_feedback')) {
      fail(`${label} violates interface-feedback-only policy`);
    }
    if (usage === 'event_accent_only' && anchor.category !== 'event') {
      fail(`${label} violates event-accent-only policy`);
    }
    const { profile } = expectedLimits;
    if (cue.kind === 'gameplay_event' && profile !== 'gaming') {
      fail(`${label}.kind is reserved for the gaming profile`);
    }
    if (cue.kind === 'sports_event' && profile !== 'sports_highlights') {
      fail(`${label}.kind is reserved for the sports profile`);
    }

    const { placement } = cue;
    const start = placement.start_ms;
    const duration = placement.trim_duration_ms;
    if (start > manifest.output_duration_ms - duration) {
      fail(`${label} extends beyond the exact output duration`);
    }
    const end = start + duration;
    if (placement.trim_start_ms > asset.duration_ms - duration) {
      fail(`${label} trim exceeds the trusted asset duration`);
    }
    if (duration > KIND_MAX_DURATION_MS[cue.kind]) {
      fail(`${label} duration exceeds its cue-kind ceiling`);
    }
    if (placement.attack_fade_ms + placement.release_fade_ms > duration) {
      fail(`${label} attack and release fades overlap`);
    }
    if (placement.gain_millidb > expectedLimits.max_gain_millidb) {
      fail(`${label}.placement.gain_millidb exceeds its profile ceiling`);
    }
    const offset = start - anchor.time_ms;
    const [minimumOffset, maximumOffset] = KIND_OFFSET_RANGE_MS[cue.kind];
    if (offset < minimumOffset || offset > maximumOffset) {
      fail(`${label} is too far from its trusted motivation anchor`);
    }
    if (!(start <= anchor.time_ms && anchor.time_ms <= end)) {
      fail(`${label} does not contain its trusted motivation anchor`);
    }

    const assetAnchor = `${cue.asset_id}\u0000${anchor.anchor_id}`;
    if (usedAssetAnchor.has(assetAnchor)) {
      fail('SFX plan cannot stack the same asset on the same anchor');
    }
    usedAssetAnchor.add(assetAnchor);
    const count = (anchorCounts.get(anchor.anchor_id) || 0) + 1;
    anchorCounts.set(anchor.anchor_id, count);
    if (count > DENSITY_PER_ANCHOR_LIMIT[expectedLimits.density]) {
      fail('SFX plan exceeds its density-specific per-anchor limit');
    }
    anchorTimes.push(anchor.time_ms);
    intervals.push([start, end]);

    const intersections = speechIntersections(start, end, manifest.speech_windows);
    const { ducking } = cue;
    if (intersections.length) {
      speechIntervals.push(...intersections);
      if (ducking === null) fail(`${label} overlaps speech without deterministic ducking`);
      const firstSpeech = intersections[0][0];
      const lastSpeech = intersections[intersections.length - 1][1];
      if (ducking.start_ms > firstSpeech || ducking.end_ms < lastSpeech) {
        fail(`${label}.ducking does not cover every speech overlap`);
      }
      if (ducking.start_ms < start || ducking.end_ms > end ||
          ducking.end_ms <= ducking.start_ms) {
        fail(`${label}.ducking must be a positive window inside the cue`);
      }
      const duckDuration = ducking.end_ms - ducking.start_ms;
      if (ducking.attack_ms + ducking.release_ms > duckDuration) {
        fail(`${label}.ducking attack/release exceed the duck window`);
      }
      if (['primary', 'verbatim'].includes(dialoguePriority) && ducking.attack_ms > 20) {
        fail(`${label}.ducking attack is too slow for primary speech`);
      }
      if (placement.gain_millidb > 0) {
        fail(`${label} may not use positive gain across speech`);
      }
      const effectiveGain = placement.gain_millidb - ducking.attenuation_millidb;
      if (effectiveGain > expectedLimits.speech_effective_gain_ceiling_millidb) {
        fail(`${label} could mask speech after requested ducking`);
      }
    } else if (ducking !== null) {
      fail(`${label}.ducking is unmotivated because the cue does not overlap speech`);
    }
  });

  anchorTimes.sort((left, right) => (left === right ? 0 : (left < right ? -1 : 1)));
  for (let left = 0; left < anchorTimes.length; left += 1) {
    let localCount = 0;
    for (let right = left; right < anchorTimes.length; right += 1) {
      if (anchorTimes[right] - anchorTimes[left] >= 10_000) break;
      localCount += 1;
    }
    if (localCount > DENSITY_LOCAL_TEN_SECOND_LIMIT[expectedLimits.density]) {
      fail('SFX plan clusters too many cues inside a ten-second window');
    }
  }

  const observedPolyphony = maxPolyphony(intervals);
  if (observedPolyphony > expectedLimits.max_polyphony) {
    fail('SFX plan exceeds its profile/density polyphony ceiling');
  }
  const observedSpeechPolyphony = maxPolyphony(speechIntervals);
  const speechPolyphonyLimit = ['primary', 'verbatim'].includes(dialoguePriority)
    ? 1
    : Math.min(2, expectedLimits.max_polyphony);
  if (observedSpeechPolyphony > speechPolyphonyLimit) {
    fail('SFX plan stacks too many cues across speech');
  }
  return detach(normalized);
}

function normalizeReceipt(receipt) {
  const raw = exactKeys(receipt, RECEIPT_KEYS, 'SFX compile receipt');
  if (raw.schema_version !== SFX_COMPILE_RECEIPT_SCHEMA_VERSION) {
    fail('SFX compile receipt schema_version is unsupported');
  }
  const hashes = {};
  [
    'sfx_plan_sha256',
    'cue_manifest_sha256',
    'edit_policy_sha256',
    'output_timeline_sha256',
    'compiled_cues_sha256',
    'mix_primitives_sha256',
  ].forEach((key) => {
    hashes[key] = sha256Value(raw[key], `SFX compile receipt.${key}`);
  });
  if (!isDenseArray(raw.ordered_cue_ids) || raw.ordered_cue_ids.length > MAX_CUES) {
    fail('SFX compile receipt.ordered_cue_ids has invalid cardinality');
  }
  if (!isDenseArray(raw.ordered_asset_ids) ||
      raw.ordered_asset_ids.length !== raw.ordered_cue_ids.length) {
    fail('SFX compile receipt.ordered_asset_ids must align one-to-one with cues');
  }
  const cueIds = [];
  const seenCues = new Set();
  raw.ordered_cue_ids.forEach((value, index) => {
    const cueId = identifier(value, CUE_ID, `SFX compile receipt.ordered_cue_ids[${index}]`);
    if (seenCues.has(cueId)) fail('SFX compile receipt cue ids must be unique');
    seenCues.add(cueId);
    cueIds.push(cueId);
  });
  const assetIds = raw.ordered_asset_ids.map((value, index) => identifier(
    value, ASSET_ID, `SFX compile receipt.ordered_asset_ids[${index}]`,
  ));
  const cueCount = integer(raw.cue_count, 'SFX compile receipt.cue_count', {
    maximum: MAX_CUES,
  });
  if (cueCount !== cueIds.length) {
    fail('SFX compile receipt.cue_count does not match ordered ids');
  }
  const uniqueCount = integer(
    raw.unique_asset_count, 'SFX compile receipt.unique_asset_count', {
      maximum: MAX_ASSETS,
    },
  );
  if (uniqueCount !== new Set(assetIds).size) {
    fail('SFX compile receipt.unique_asset_count does not match asset ids');
  }
  const policySnapshot = normalizePolicySnapshot(raw.policy, 'SFX compile receipt.policy');
  if (cueCount > policySnapshot.max_cue_count) {
    fail('SFX compile receipt cue_count exceeds its policy ceiling');
  }
  const observedPolyphony = integer(
    raw.max_observed_polyphony, 'SFX compile receipt.max_observed_polyphony', {
      maximum: 8,
    },
  );
  if (observedPolyphony > policySnapshot.max_polyphony) {
    fail('SFX compile receipt polyphony exceeds its policy ceiling');
  }
  const rate = integer(
    raw.output_sample_rate_hz, 'SFX compile receipt.output_sample_rate_hz', {
      minimum: Math.min(...SAMPLE_RATES_HZ), maximum: Math.max(...SAMPLE_RATES_HZ),
    },
  );
  if (!SAMPLE_RATE_SET.has(rate)) {
    fail('SFX compile receipt.output_sample_rate_hz is unsupported');
  }
  const channels = integer(
    raw.output_channels, 'SFX compile receipt.output_channels', {
      minimum: 1, maximum: 8,
    },
  );
  if (rate !== DELIVERY_SAMPLE_RATE_HZ || channels !== DELIVERY_CHANNELS) {
    fail('SFX compile receipt output must be the exact 48000 Hz stereo delivery format');
  }
  const timeBase = exactKeys(
    raw.time_base, BASE_KEYS, 'SFX compile receipt.time_base',
  );
  if (timeBase.numerator !== 1 || timeBase.denominator !== 1_000) {
    fail('SFX compile receipt.time_base must be exact 1/1000');
  }
  const millidbBase = exactKeys(
    raw.millidb_base, BASE_KEYS, 'SFX compile receipt.millidb_base',
  );
  if (millidbBase.numerator !== 1 || millidbBase.denominator !== 1_000) {
    fail('SFX compile receipt.millidb_base must be exact 1/1000 dB');
  }
  return {
    schema_version: SFX_COMPILE_RECEIPT_SCHEMA_VERSION,
    ...hashes,
    ordered_cue_ids: cueIds,
    ordered_asset_ids: assetIds,
    cue_count: cueCount,
    unique_asset_count: uniqueCount,
    output_duration_ms: integer(
      raw.output_duration_ms, 'SFX compile receipt.output_duration_ms', { minimum: 1 },
    ),
    output_sample_rate_hz: rate,
    output_channels: channels,
    max_observed_polyphony: observedPolyphony,
    speech_overlap_cue_count: integer(
      raw.speech_overlap_cue_count,
      'SFX compile receipt.speech_overlap_cue_count',
      { maximum: cueCount },
    ),
    time_base: { numerator: 1, denominator: 1_000 },
    millidb_base: { numerator: 1, denominator: 1_000 },
    policy: policySnapshot,
  };
}

function canonicalSfxCompileReceiptJson(receipt) {
  return canonicalJsonData(normalizeReceipt(receipt), 'SFX compile receipt');
}

function sfxCompileReceiptSha256(receipt) {
  return crypto.createHash('sha256')
    .update(canonicalSfxCompileReceiptJson(receipt), 'utf8')
    .digest('hex');
}

function compileSfxPlan(plan, cueManifest, editPolicy) {
  const validated = validateSfxPlan(plan, cueManifest, editPolicy);
  const manifest = validateSfxCueManifest(cueManifest);
  const assets = new Map(manifest.assets.map((asset) => [asset.asset_id, asset]));
  const compiled = [];
  const intervals = [];
  let speechOverlapCount = 0;

  validated.cues.forEach((cue, index) => {
    const asset = assets.get(cue.asset_id);
    const { placement } = cue;
    const start = placement.start_ms;
    const duration = placement.trim_duration_ms;
    const end = start + duration;
    intervals.push([start, end]);
    const cueTokens = [
      `atrim=start=${ffmpegSeconds(placement.trim_start_ms)}:duration=${ffmpegSeconds(duration)}`,
      'asetpts=PTS-STARTPTS',
      `aresample=${manifest.output_sample_rate_hz}:async=0:first_pts=0`,
      `aformat=sample_fmts=fltp:sample_rates=${manifest.output_sample_rate_hz}` +
        `:channel_layouts=${ffmpegChannelLayout(manifest.output_channels)}`,
    ];
    if (placement.attack_fade_ms) {
      cueTokens.push(
        `afade=t=in:st=0.000:d=${ffmpegSeconds(placement.attack_fade_ms)}:curve=qsin`,
      );
    }
    if (placement.release_fade_ms) {
      const releaseStart = duration - placement.release_fade_ms;
      cueTokens.push(
        `afade=t=out:st=${ffmpegSeconds(releaseStart)}` +
          `:d=${ffmpegSeconds(placement.release_fade_ms)}:curve=qsin`,
      );
    }
    cueTokens.push(`volume=${ffmpegMillidb(placement.gain_millidb)}:precision=double`);

    const duck = cue.ducking;
    let sidechainGateTokens = [];
    let compressorTokens = [];
    if (duck !== null) {
      speechOverlapCount += 1;
      const duckDuration = duck.end_ms - duck.start_ms;
      const relativeStart = duck.start_ms - start;
      const relativeEnd = relativeStart + duckDuration;
      sidechainGateTokens = [
        `aevalsrc=if(between(t\\,${ffmpegSeconds(relativeStart)}` +
          `\\,${ffmpegSeconds(relativeEnd)}` +
          `)\\,1\\,0):d=${ffmpegSeconds(duration)}` +
          `:s=${manifest.output_sample_rate_hz}:c=mono`,
      ];
      compressorTokens = [
        `sidechaincompress=threshold=${DUCK_SIDECHAIN_THRESHOLD_TEXT[duck.attenuation_millidb]}` +
          `:ratio=2:attack=${duck.attack_ms}:release=${duck.release_ms}` +
          ':makeup=1:knee=1:link=maximum:detection=peak:mix=1',
      ];
    }
    const timelineTokens = [`adelay=delays=${start}:all=1`];
    compiled.push({
      cue_index: index,
      cue_id: cue.cue_id,
      asset_id: asset.asset_id,
      asset_sha256: asset.sha256,
      asset_byte_length: asset.byte_length,
      asset_duration_ms: asset.duration_ms,
      asset_sample_rate_hz: asset.sample_rate_hz,
      asset_channels: asset.channels,
      source_ref: asset.source_ref,
      provenance: asset.provenance,
      license: asset.license,
      kind: cue.kind,
      motivation: cue.motivation,
      placement,
      ducking: duck,
      output_start_ms: start,
      output_end_ms: end,
      speech_overlap_ms: speechIntersections(
        start, end, manifest.speech_windows,
      ).reduce((total, [left, right]) => total + right - left, 0),
      cue_ffmpeg_primitive_tokens: cueTokens,
      duck_sidechain_gate_ffmpeg_primitive_tokens: sidechainGateTokens,
      sidechaincompress_ffmpeg_primitive_tokens: compressorTokens,
      timeline_ffmpeg_primitive_tokens: timelineTokens,
    });
  });

  let programInputTokens = [];
  let sfxBusTokens = [];
  let programMixTokens = [];
  if (compiled.length) {
    const outputRate = String(manifest.output_sample_rate_hz);
    const outputLayout = ffmpegChannelLayout(manifest.output_channels);
    const outputDuration = ffmpegSeconds(manifest.output_duration_ms);
    programInputTokens = [
      `aresample=${outputRate}:async=0:first_pts=0`,
      `aformat=sample_fmts=fltp:sample_rates=${outputRate}:channel_layouts=${outputLayout}`,
      `apad=whole_dur=${outputDuration}`,
      `atrim=start=0.000:duration=${outputDuration}`,
      'asetpts=PTS-STARTPTS',
    ];
    sfxBusTokens = [
      `amix=inputs=${compiled.length}:duration=longest:dropout_transition=0:normalize=0`,
      'alimiter=limit=0.891251:attack=5:release=50:level=0:latency=1',
      `apad=whole_dur=${outputDuration}`,
      `atrim=start=0.000:duration=${outputDuration}`,
      'asetpts=PTS-STARTPTS',
    ];
    programMixTokens = [
      'amix=inputs=2:duration=first:dropout_transition=0:normalize=0',
      'alimiter=limit=0.891251:attack=5:release=50:level=0:latency=1',
      `atrim=start=0.000:duration=${outputDuration}`,
      'asetpts=PTS-STARTPTS',
    ];
  }
  const mixPrimitives = {
    program_input_ffmpeg_primitive_tokens: programInputTokens,
    sfx_bus_ffmpeg_primitive_tokens: sfxBusTokens,
    program_mix_ffmpeg_primitive_tokens: programMixTokens,
  };
  const compiledHash = digestCanonical(compiled, 'compiled SFX cues');
  const mixHash = digestCanonical(mixPrimitives, 'compiled SFX mix primitives');
  const receipt = normalizeReceipt({
    schema_version: SFX_COMPILE_RECEIPT_SCHEMA_VERSION,
    sfx_plan_sha256: sfxPlanSha256(validated),
    cue_manifest_sha256: sfxCueManifestSha256(manifest),
    edit_policy_sha256: editPolicySha256(editPolicy),
    output_timeline_sha256: manifest.output_timeline_sha256,
    compiled_cues_sha256: compiledHash,
    mix_primitives_sha256: mixHash,
    ordered_cue_ids: compiled.map((item) => item.cue_id),
    ordered_asset_ids: compiled.map((item) => item.asset_id),
    cue_count: compiled.length,
    unique_asset_count: new Set(compiled.map((item) => item.asset_id)).size,
    output_duration_ms: manifest.output_duration_ms,
    output_sample_rate_hz: manifest.output_sample_rate_hz,
    output_channels: manifest.output_channels,
    max_observed_polyphony: maxPolyphony(intervals),
    speech_overlap_cue_count: speechOverlapCount,
    time_base: { numerator: 1, denominator: 1_000 },
    millidb_base: { numerator: 1, denominator: 1_000 },
    policy: validated.policy,
  });
  return {
    compiled_cues: detach(compiled),
    ...detach(mixPrimitives),
    receipt: detach(receipt),
    receipt_sha256: sfxCompileReceiptSha256(receipt),
  };
}

function licenseJsonSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: [...LICENSE_KEYS],
    properties: {
      basis: { type: 'string', enum: [...LICENSE_BASES] },
      license_id: { type: 'string', pattern: SAFE_ID.source },
      licensor: { type: 'string', pattern: LICENSOR.source },
      evidence_sha256: { type: 'string', pattern: SHA256.source },
    },
  };
}

function policyJsonSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: [...POLICY_KEYS],
    properties: {
      profile: { type: 'string', pattern: SAFE_ID.source },
      density: { type: 'string', enum: [...POLICY_DENSITIES] },
      usage: { type: 'string', enum: [...POLICY_USAGES] },
      max_cue_count: { type: 'integer', minimum: 0, maximum: MAX_CUES },
      max_polyphony: { type: 'integer', minimum: 0, maximum: 8 },
      max_gain_millidb: { type: 'integer', minimum: -60_000, maximum: 6_000 },
      speech_effective_gain_ceiling_millidb: {
        type: 'integer', minimum: -60_000, maximum: 0,
      },
    },
  };
}

function motivationJsonSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: [...MOTIVATION_KEYS],
    properties: {
      category: { type: 'string', enum: [...ANCHOR_CATEGORIES] },
      anchor_id: { type: 'string', pattern: ANCHOR_ID.source },
      reference_id: { type: 'string', minLength: 1, maxLength: 96 },
      anchor_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
      evidence_start_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
      evidence_end_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
      evidence_sha256: { type: 'string', pattern: SHA256.source },
    },
  };
}

function placementJsonSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: [...PLACEMENT_KEYS],
    properties: {
      start_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
      trim_start_ms: { type: 'integer', minimum: 0, maximum: MAX_ASSET_DURATION_MS },
      trim_duration_ms: { type: 'integer', minimum: 20, maximum: MAX_CUE_DURATION_MS },
      gain_millidb: { type: 'integer', minimum: -60_000, maximum: 6_000 },
      attack_fade_ms: { type: 'integer', minimum: 0, maximum: 5_000 },
      release_fade_ms: { type: 'integer', minimum: 0, maximum: 5_000 },
    },
  };
}

function duckingJsonSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: [...DUCKING_KEYS],
    properties: {
      start_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
      end_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
      attenuation_millidb: { type: 'integer', enum: [...DUCK_ATTENUATIONS_MILLIDB] },
      attack_ms: { type: 'integer', minimum: 1, maximum: 200 },
      release_ms: { type: 'integer', minimum: 1, maximum: 2_000 },
    },
  };
}

const SFX_CUE_MANIFEST_JSON_SCHEMA = Object.freeze({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  additionalProperties: false,
  required: [...MANIFEST_KEYS],
  properties: {
    schema_version: { const: SFX_CUE_MANIFEST_SCHEMA_VERSION },
    output_timeline_sha256: { type: 'string', pattern: SHA256.source },
    output_duration_ms: { type: 'integer', minimum: 1, maximum: MAX_SAFE_INTEGER },
    output_sample_rate_hz: { const: DELIVERY_SAMPLE_RATE_HZ },
    output_channels: { const: DELIVERY_CHANNELS },
    assets: {
      type: 'array',
      maxItems: MAX_ASSETS,
      items: {
        type: 'object',
        additionalProperties: false,
        required: [...ASSET_KEYS],
        properties: {
          asset_id: { type: 'string', pattern: ASSET_ID.source },
          sha256: { type: 'string', pattern: SHA256.source },
          byte_length: { type: 'integer', minimum: 1, maximum: MAX_ASSET_BYTES },
          duration_ms: { type: 'integer', minimum: 1, maximum: MAX_ASSET_DURATION_MS },
          sample_rate_hz: { type: 'integer', enum: [...SAMPLE_RATES_HZ] },
          channels: { type: 'integer', minimum: 1, maximum: 8 },
          source_ref: { type: 'string', pattern: SOURCE_REF_PATTERN },
          provenance: { type: 'string', enum: [...PROVENANCE_KINDS] },
          license: licenseJsonSchema(),
        },
      },
    },
    anchors: {
      type: 'array',
      maxItems: MAX_ANCHORS,
      items: {
        type: 'object',
        additionalProperties: false,
        required: [...ANCHOR_KEYS],
        properties: {
          anchor_id: { type: 'string', pattern: ANCHOR_ID.source },
          category: { type: 'string', enum: [...ANCHOR_CATEGORIES] },
          reference_id: { type: 'string', minLength: 1, maxLength: 96 },
          time_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
          evidence_start_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
          evidence_end_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
          evidence_sha256: { type: 'string', pattern: SHA256.source },
        },
      },
    },
    speech_windows: {
      type: 'array',
      maxItems: MAX_SPEECH_WINDOWS,
      items: {
        type: 'object',
        additionalProperties: false,
        required: [...SPEECH_KEYS],
        properties: {
          speech_id: { type: 'string', pattern: SPEECH_ID.source },
          start_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
          end_ms: { type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER },
          evidence_sha256: { type: 'string', pattern: SHA256.source },
        },
      },
    },
  },
});

const SFX_PLAN_JSON_SCHEMA = Object.freeze({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  additionalProperties: false,
  required: [...PLAN_KEYS],
  properties: {
    schema_version: { const: SFX_PLAN_SCHEMA_VERSION },
    cue_manifest_sha256: { type: 'string', pattern: SHA256.source },
    edit_policy_sha256: { type: 'string', pattern: SHA256.source },
    output_timeline_sha256: { type: 'string', pattern: SHA256.source },
    output_duration_ms: { type: 'integer', minimum: 1, maximum: MAX_SAFE_INTEGER },
    policy: policyJsonSchema(),
    cues: {
      type: 'array',
      maxItems: MAX_CUES,
      items: {
        type: 'object',
        additionalProperties: false,
        required: [...CUE_KEYS],
        properties: {
          cue_id: { type: 'string', pattern: CUE_ID.source },
          asset_id: { type: 'string', pattern: ASSET_ID.source },
          asset_sha256: { type: 'string', pattern: SHA256.source },
          kind: { type: 'string', enum: [...CUE_KINDS] },
          motivation: motivationJsonSchema(),
          placement: placementJsonSchema(),
          ducking: { oneOf: [{ type: 'null' }, duckingJsonSchema()] },
        },
      },
    },
  },
});

const SFX_COMPILE_RECEIPT_JSON_SCHEMA = Object.freeze({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  additionalProperties: false,
  required: [...RECEIPT_KEYS],
  properties: {
    schema_version: { const: SFX_COMPILE_RECEIPT_SCHEMA_VERSION },
    sfx_plan_sha256: { type: 'string', pattern: SHA256.source },
    cue_manifest_sha256: { type: 'string', pattern: SHA256.source },
    edit_policy_sha256: { type: 'string', pattern: SHA256.source },
    output_timeline_sha256: { type: 'string', pattern: SHA256.source },
    compiled_cues_sha256: { type: 'string', pattern: SHA256.source },
    mix_primitives_sha256: { type: 'string', pattern: SHA256.source },
    ordered_cue_ids: {
      type: 'array', maxItems: MAX_CUES,
      items: { type: 'string', pattern: CUE_ID.source },
    },
    ordered_asset_ids: {
      type: 'array', maxItems: MAX_CUES,
      items: { type: 'string', pattern: ASSET_ID.source },
    },
    cue_count: { type: 'integer', minimum: 0, maximum: MAX_CUES },
    unique_asset_count: { type: 'integer', minimum: 0, maximum: MAX_ASSETS },
    output_duration_ms: { type: 'integer', minimum: 1, maximum: MAX_SAFE_INTEGER },
    output_sample_rate_hz: { const: DELIVERY_SAMPLE_RATE_HZ },
    output_channels: { const: DELIVERY_CHANNELS },
    max_observed_polyphony: { type: 'integer', minimum: 0, maximum: 8 },
    speech_overlap_cue_count: { type: 'integer', minimum: 0, maximum: MAX_CUES },
    time_base: {
      type: 'object',
      additionalProperties: false,
      required: [...BASE_KEYS],
      properties: { numerator: { const: 1 }, denominator: { const: 1_000 } },
    },
    millidb_base: {
      type: 'object',
      additionalProperties: false,
      required: [...BASE_KEYS],
      properties: { numerator: { const: 1 }, denominator: { const: 1_000 } },
    },
    policy: policyJsonSchema(),
  },
});

module.exports = Object.freeze({
  SFX_CUE_MANIFEST_SCHEMA_VERSION,
  SFX_PLAN_SCHEMA_VERSION,
  SFX_COMPILE_RECEIPT_SCHEMA_VERSION,
  MAX_SAFE_INTEGER,
  MAX_ASSETS,
  MAX_ANCHORS,
  MAX_SPEECH_WINDOWS,
  MAX_CUES,
  MAX_ASSET_DURATION_MS,
  MAX_CUE_DURATION_MS,
  MAX_ASSET_BYTES,
  DELIVERY_SAMPLE_RATE_HZ,
  DELIVERY_CHANNELS,
  SAMPLE_RATES_HZ,
  PROVENANCE_KINDS,
  LICENSE_BASES,
  ANCHOR_CATEGORIES,
  CUE_KINDS,
  POLICY_DENSITIES,
  POLICY_USAGES,
  DUCK_ATTENUATIONS_MILLIDB,
  DUCK_SIDECHAIN_THRESHOLD_TEXT,
  SFX_CUE_MANIFEST_JSON_SCHEMA,
  SFX_PLAN_JSON_SCHEMA,
  SFX_COMPILE_RECEIPT_JSON_SCHEMA,
  SfxPlanError,
  deriveSfxAssetId,
  deriveSfxAnchorId,
  deriveSpeechWindowId,
  validateSfxCueManifest,
  canonicalSfxCueManifestJson,
  sfxCueManifestSha256,
  densityCueLimit,
  deriveSfxPolicyLimits,
  deriveSfxCueId,
  canonicalSfxPlanJson,
  sfxPlanSha256,
  validateSfxPlan,
  canonicalSfxCompileReceiptJson,
  sfxCompileReceiptSha256,
  compileSfxPlan,
});
