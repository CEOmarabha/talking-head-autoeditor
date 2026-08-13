'use strict';

// Strict JavaScript mirror of autoeditor/music_plan.py. This module is an
// inert contract/compiler: it validates trusted media, rights, source-music,
// transcript, beat, policy, timing, and gain facts and emits only bounded
// FFmpeg primitive/argument tokens. It never resolves paths or runs a process.

const crypto = require('node:crypto');

const {
  EditPolicyError,
  editPolicySha256,
  validateEditPolicy,
} = require('./edit-policy');

const MUSIC_ASSET_MANIFEST_SCHEMA_VERSION = 'autoeditor-music-asset-manifest/v1';
const MUSIC_PLAN_SCHEMA_VERSION = 'autoeditor-music-plan/v1';
const MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION = 'autoeditor-music-compile-receipt/v1';

const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;
const MAX_ASSETS = 128;
const MAX_BEAT_GRIDS = 128;
const MAX_DIALOGUE_WINDOWS = 4_096;
const MAX_SOURCE_MUSIC_REGIONS = 4_096;
const MAX_MUSIC_REGIONS = 256;
const MAX_TRACKS = 8;
const MAX_ASSET_BYTES = 1_099_511_627_776;
const MAX_ASSET_DURATION_MS = 14_400_000;
const MAX_OUTPUT_DURATION_MS = 86_400_000;

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
const MUSIC_USAGES = Object.freeze([
  'forbidden', 'optional', 'primary', 'source_primary', 'supporting',
]);
const SOURCE_MUSIC_STATUSES = Object.freeze(['absent', 'present']);
const SOURCE_MUSIC_ACTIONS = Object.freeze(['none', 'preserve']);
const PLAYBACK_MODES = Object.freeze(['loop', 'once']);
const EVIDENCE_KINDS = Object.freeze(['audio_analysis', 'transcript']);
const DUCK_ATTENUATIONS_MILLIDB = Object.freeze([9_000, 12_000, 18_000, 24_000]);
const DUCK_THRESHOLDS_MILLIDBFS = Object.freeze([-36_000, -30_000, -24_000, -18_000]);

const SAMPLE_RATE_SET = new Set(SAMPLE_RATES_HZ);
const PROVENANCE_SET = new Set(PROVENANCE_KINDS);
const LICENSE_BASE_SET = new Set(LICENSE_BASES);
const MUSIC_USAGE_SET = new Set(MUSIC_USAGES);
const SOURCE_MUSIC_STATUS_SET = new Set(SOURCE_MUSIC_STATUSES);
const SOURCE_MUSIC_ACTION_SET = new Set(SOURCE_MUSIC_ACTIONS);
const PLAYBACK_MODE_SET = new Set(PLAYBACK_MODES);
const EVIDENCE_KIND_SET = new Set(EVIDENCE_KINDS);
const DUCK_ATTENUATION_SET = new Set(DUCK_ATTENUATIONS_MILLIDB);
const DUCK_THRESHOLD_SET = new Set(DUCK_THRESHOLDS_MILLIDBFS);

// Exact-key lists are ASCII sorted to match Python's sorted diagnostics and
// make sparse arrays/prototype/symbol tricks fail at the contract boundary.
const MANIFEST_KEYS = Object.freeze([
  'assets', 'beat_grids', 'dialogue_windows', 'output_channels',
  'output_duration_ms', 'output_sample_rate_hz', 'output_timeline_sha256',
  'schema_version', 'source_music', 'transcript_sha256',
]);
const SOURCE_MUSIC_KEYS = Object.freeze([
  'evidence_sha256', 'exclusion_authorization_sha256', 'regions', 'status',
]);
const SOURCE_REGION_KEYS = Object.freeze([
  'end_ms', 'evidence_sha256', 'source_region_id', 'start_ms',
]);
const SOURCE_REGION_PAYLOAD_KEYS = Object.freeze(
  SOURCE_REGION_KEYS.filter((key) => key !== 'source_region_id'),
);
const ASSET_KEYS = Object.freeze([
  'asset_id', 'byte_length', 'channels', 'decoded_duration_ms', 'license',
  'provenance', 'rights_receipt', 'sample_rate_hz', 'sha256', 'source_ref',
]);
const ASSET_PAYLOAD_KEYS = Object.freeze(ASSET_KEYS.filter((key) => key !== 'asset_id'));
const LICENSE_KEYS = Object.freeze([
  'basis', 'evidence_sha256', 'license_id', 'license_name', 'licensor',
]);
const RIGHTS_KEYS = Object.freeze([
  'permits_delivery', 'permits_editing', 'permits_looping',
  'permits_synchronization', 'receipt_id', 'receipt_sha256',
]);
const BEAT_GRID_KEYS = Object.freeze([
  'analysis_receipt_sha256', 'asset_id', 'asset_sha256', 'beat_grid_id',
  'beats_ms', 'downbeats_ms',
]);
const BEAT_GRID_PAYLOAD_KEYS = Object.freeze(
  BEAT_GRID_KEYS.filter((key) => key !== 'beat_grid_id'),
);
const DIALOGUE_KEYS = Object.freeze([
  'dialogue_window_id', 'end_ms', 'evidence_kind', 'evidence_sha256', 'start_ms',
]);
const DIALOGUE_PAYLOAD_KEYS = Object.freeze(
  DIALOGUE_KEYS.filter((key) => key !== 'dialogue_window_id'),
);
const PLAN_KEYS = Object.freeze([
  'edit_policy_sha256', 'mastering', 'music_asset_manifest_sha256',
  'output_duration_ms', 'output_timeline_sha256', 'policy', 'regions',
  'schema_version', 'source_music_action',
]);
const POLICY_KEYS = Object.freeze([
  'duck_under_dialogue', 'max_added_coverage_ms', 'max_added_track_count',
  'max_gain_millidb', 'max_polyphony', 'max_region_count', 'profile',
  'speech_effective_gain_ceiling_millidb', 'usage',
]);
const MASTERING_KEYS = Object.freeze([
  'target_loudness_millilufs', 'true_peak_ceiling_millidbtp',
]);
const REGION_KEYS = Object.freeze([
  'asset_id', 'asset_sha256', 'beat_sync', 'crossfade_in_ms',
  'crossfade_out_ms', 'dialogue_ducking', 'duration_ms', 'fade_in_ms',
  'fade_out_ms', 'gain_millidb', 'loop_crossfade_ms', 'loop_length_ms',
  'playback_mode', 'region_id', 'start_ms', 'track_index', 'trim_start_ms',
]);
const REGION_PAYLOAD_KEYS = Object.freeze(REGION_KEYS.filter((key) => key !== 'region_id'));
const BEAT_SYNC_KEYS = Object.freeze([
  'analysis_receipt_sha256', 'asset_beat_ms', 'beat_grid_id', 'output_beat_ms',
]);
const DUCKING_KEYS = Object.freeze([
  'attack_ms', 'attenuation_millidb', 'dialogue_window_ids', 'release_ms',
  'threshold_millidbfs',
]);
const RECEIPT_KEYS = Object.freeze([
  'added_coverage_ms', 'added_track_count', 'beat_synced_region_count',
  'compiled_regions_sha256', 'dialogue_overlap_region_count',
  'edit_policy_sha256', 'looped_region_count', 'max_observed_polyphony',
  'millidb_base', 'mix_primitives_sha256', 'music_asset_manifest_sha256',
  'music_plan_sha256', 'ordered_asset_ids', 'ordered_region_ids',
  'output_channels', 'output_duration_ms', 'output_sample_rate_hz',
  'output_timeline_sha256', 'policy', 'region_count', 'schema_version',
  'source_music_action', 'target_loudness_millilufs', 'time_base',
  'true_peak_ceiling_millidbtp', 'unique_asset_count',
]);
const BASE_KEYS = Object.freeze(['denominator', 'numerator']);
const COMPILE_RESULT_KEYS = Object.freeze([
  'compiled_regions', 'music_bus_ffmpeg_primitive_tokens',
  'output_ffmpeg_argument_tokens', 'program_mix_ffmpeg_primitive_tokens',
  'receipt', 'receipt_sha256', 'schema_version',
  'track_crossfade_ffmpeg_primitive_tokens',
]);

const SHA256 = /^[0-9a-f]{64}$/;
const ASSET_ID = /^musicasset-[0-9a-f]{64}$/;
const BEAT_GRID_ID = /^beatgrid-[0-9a-f]{64}$/;
const DIALOGUE_ID = /^dialogue-[0-9a-f]{64}$/;
const SOURCE_REGION_ID = /^sourcemusic-[0-9a-f]{64}$/;
const REGION_ID = /^musicregion-[0-9a-f]{64}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$/;
const SOURCE_REF = /^(project-generated|user-supplied|licensed-external):\/\/[A-Za-z0-9][A-Za-z0-9._/-]{0,383}$/;
const TOKEN = /^[A-Za-z0-9_=.:,+*/-]{1,512}$/;

const PROVENANCE_LICENSE = Object.freeze({
  project_generated: Object.freeze(['project-generated', 'project_owned']),
  user_supplied: Object.freeze(['user-supplied', 'user_authorized']),
  licensed_external: Object.freeze(['licensed-external', 'licensed_external']),
});
const PROFILE_REGION_INTERVAL_MS = Object.freeze({
  commercial_product: 30_000,
  course_tutorial_screencast: 90_000,
  dialogue_talking_head: 120_000,
  documentary_narrative: 120_000,
  gaming: 60_000,
  montage_meme: 15_000,
  music_performance: MAX_OUTPUT_DURATION_MS,
  podcast_interview: 180_000,
  real_estate: 60_000,
  sports_highlights: 45_000,
  utility_faithful: MAX_OUTPUT_DURATION_MS,
  vlog_travel: 45_000,
  wedding_event: 90_000,
});
const PROFILE_TRACK_CEILING = Object.freeze({
  commercial_product: 2,
  course_tutorial_screencast: 1,
  dialogue_talking_head: 1,
  documentary_narrative: 1,
  gaming: 2,
  montage_meme: 3,
  music_performance: 0,
  podcast_interview: 1,
  real_estate: 1,
  sports_highlights: 2,
  utility_faithful: 0,
  vlog_travel: 2,
  wedding_event: 2,
});
const USAGE_TRACK_CEILING = Object.freeze({
  forbidden: 0, optional: 1, supporting: 2, primary: 3, source_primary: 0,
});
const USAGE_POLYPHONY_CEILING = Object.freeze({
  forbidden: 0, optional: 1, supporting: 1, primary: 2, source_primary: 0,
});
const PROFILE_GAIN_CEILING = Object.freeze({
  commercial_product: 0,
  course_tutorial_screencast: -3_000,
  dialogue_talking_head: -6_000,
  documentary_narrative: -6_000,
  gaming: 0,
  montage_meme: 0,
  music_performance: -60_000,
  podcast_interview: -9_000,
  real_estate: -3_000,
  sports_highlights: 0,
  utility_faithful: -60_000,
  vlog_travel: -3_000,
  wedding_event: -6_000,
});
const SPEECH_GAIN_CEILING = Object.freeze({
  none: 0, supporting: -15_000, primary: -18_000, verbatim: -21_000,
});

class MusicPlanError extends Error {
  constructor(message) {
    super(message);
    this.name = 'MusicPlanError';
  }
}

function fail(message) {
  throw new MusicPlanError(message);
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
    (typeof key === 'string' && /^(0|[1-9][0-9]*)$/.test(key) && Number(key) < value.length)
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

function booleanValue(value, label) {
  if (typeof value !== 'boolean') fail(`${label} must be boolean`);
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

function nullableSha256(value, label) {
  return value === null ? null : sha256Value(value, label);
}

function safeAscii(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} must be bounded safe ASCII text`);
  }
  return value;
}

function unicodeText(value, label, maximum = 160) {
  if (typeof value !== 'string' ||
      Array.from(value).length < 1 || Array.from(value).length > maximum) {
    fail(`${label} must be bounded non-empty text`);
  }
  if (value.normalize('NFC') !== value) fail(`${label} must use NFC Unicode normalization`);
  if (/[\p{Cc}\p{Cf}\p{Cn}\p{Co}\p{Cs}\p{Zl}\p{Zp}]/u.test(value)) {
    fail(`${label} contains control, formatting, private, or surrogate characters`);
  }
  return value;
}

function pythonCasefold(value) {
  // Python casefold differs from JavaScript lowercasing for a small set of
  // compatibility letters that can otherwise spell reserved ASCII claims.
  return value.toLowerCase()
    .replace(/[ßẞ]/gu, 'ss')
    .replace(/ſ/gu, 's')
    .replace(/ﬀ/gu, 'ff')
    .replace(/ﬁ/gu, 'fi')
    .replace(/ﬂ/gu, 'fl')
    .replace(/ﬃ/gu, 'ffi')
    .replace(/ﬄ/gu, 'ffl')
    .replace(/[ﬅﬆ]/gu, 'st');
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
      return `{${keys.map((key) => `${pythonString(key)}:${serialize(item[key])}`).join(',')}}`;
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

function digestText(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function detach(value) {
  if (Array.isArray(value)) return value.map(detach);
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, detach(item)]));
  }
  return value;
}

function pick(value, keys) {
  return Object.fromEntries(keys.map((key) => [key, value[key]]));
}

function equalCanonical(left, right) {
  return canonicalJsonData(left, 'comparison') === canonicalJsonData(right, 'comparison');
}

function ffmpegSeconds(milliseconds) {
  return `${Math.floor(milliseconds / 1_000)}.${String(milliseconds % 1_000).padStart(3, '0')}`;
}

function ffmpegMillidb(millidb, suffix = 'dB') {
  const sign = millidb < 0 ? '-' : '';
  const absolute = Math.abs(millidb);
  return `${sign}${Math.floor(absolute / 1_000)}.${String(absolute % 1_000).padStart(3, '0')}${suffix}`;
}

function validateTokens(tokens, label) {
  if (!isDenseArray(tokens) || tokens.length > 512) {
    fail(`${label} has invalid token cardinality`);
  }
  return tokens.map((token, index) => {
    if (typeof token !== 'string' || !TOKEN.test(token)) {
      fail(`${label}[${index}] is not a safe inert token`);
    }
    return token;
  });
}

function normalizeLicense(value, provenance, label) {
  const raw = exactKeys(value, LICENSE_KEYS, label);
  const basis = enumValue(raw.basis, LICENSE_BASE_SET, `${label}.basis`);
  if (basis !== PROVENANCE_LICENSE[provenance][1]) {
    fail(`${label}.basis does not match asset provenance`);
  }
  const licenseId = safeAscii(raw.license_id, SAFE_ID, `${label}.license_id`);
  const licenseName = unicodeText(raw.license_name, `${label}.license_name`);
  const licensor = unicodeText(raw.licensor, `${label}.licensor`);
  if (licenseId !== licenseId.trim() || licenseName !== licenseName.trim() ||
      licensor !== licensor.trim()) {
    fail(`${label} values must not have surrounding whitespace`);
  }
  const licenseIdFolded = pythonCasefold(licenseId);
  const licenseNameFolded = pythonCasefold(licenseName);
  const licensorFolded = pythonCasefold(licensor);
  const placeholders = new Set([
    licenseIdFolded, licenseNameFolded, licensorFolded,
  ]);
  if (['unknown', 'none', 'unlicensed', 'tbd', 'n/a'].some((item) => placeholders.has(item))) {
    fail(`${label} contains a placeholder rather than license evidence`);
  }
  if (provenance === 'project_generated') {
    if (licenseId !== 'project-generated' ||
        licenseName !== 'Project ownership' || licensor !== 'project') {
      fail(`${label} must identify project-generated ownership exactly`);
    }
  } else if (provenance === 'licensed_external') {
    if (licenseIdFolded === 'project-generated' ||
        ['project', 'user'].includes(licensorFolded)) {
      fail(`${label} does not establish an external license`);
    }
  } else {
    if (licenseIdFolded === 'project-generated') {
      fail(`${label}.license_id falsely claims project ownership`);
    }
    if (licensor !== 'user') {
      fail(`${label}.licensor must identify user authorization exactly`);
    }
  }
  return {
    basis,
    license_id: licenseId,
    license_name: licenseName,
    licensor,
    evidence_sha256: sha256Value(raw.evidence_sha256, `${label}.evidence_sha256`),
  };
}

function normalizeRights(value, label) {
  const raw = exactKeys(value, RIGHTS_KEYS, label);
  const receiptId = safeAscii(raw.receipt_id, SAFE_ID, `${label}.receipt_id`);
  if (receiptId !== receiptId.trim() ||
      ['unknown', 'none', 'tbd', 'n/a'].includes(pythonCasefold(receiptId))) {
    fail(`${label}.receipt_id is a placeholder`);
  }
  return {
    receipt_id: receiptId,
    receipt_sha256: sha256Value(raw.receipt_sha256, `${label}.receipt_sha256`),
    permits_synchronization: booleanValue(
      raw.permits_synchronization, `${label}.permits_synchronization`,
    ),
    permits_editing: booleanValue(raw.permits_editing, `${label}.permits_editing`),
    permits_looping: booleanValue(raw.permits_looping, `${label}.permits_looping`),
    permits_delivery: booleanValue(raw.permits_delivery, `${label}.permits_delivery`),
  };
}

function normalizeAssetPayload(value, label) {
  const raw = exactKeys(value, ASSET_PAYLOAD_KEYS, label);
  const provenance = enumValue(raw.provenance, PROVENANCE_SET, `${label}.provenance`);
  const sourceRef = safeAscii(raw.source_ref, SOURCE_REF, `${label}.source_ref`);
  const [scheme, tail] = sourceRef.split('://', 2);
  if (scheme !== PROVENANCE_LICENSE[provenance][0]) {
    fail(`${label}.source_ref scheme does not match provenance`);
  }
  if (tail.split('/').some((part) => ['', '.', '..'].includes(part))) {
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
    decoded_duration_ms: integer(raw.decoded_duration_ms, `${label}.decoded_duration_ms`, {
      minimum: 1, maximum: MAX_ASSET_DURATION_MS,
    }),
    sample_rate_hz: sampleRate,
    channels: integer(raw.channels, `${label}.channels`, { minimum: 1, maximum: 8 }),
    source_ref: sourceRef,
    provenance,
    license: normalizeLicense(raw.license, provenance, `${label}.license`),
    rights_receipt: normalizeRights(raw.rights_receipt, `${label}.rights_receipt`),
  };
}

function deriveMusicAssetId(assetWithoutId) {
  const normalized = normalizeAssetPayload(assetWithoutId, 'music asset binding');
  return `musicasset-${digestCanonical(normalized, 'music asset binding')}`;
}

function normalizeSourceRegionPayload(value, label, duration) {
  const raw = exactKeys(value, SOURCE_REGION_PAYLOAD_KEYS, label);
  const start = integer(raw.start_ms, `${label}.start_ms`, { maximum: duration });
  const end = integer(raw.end_ms, `${label}.end_ms`, { maximum: duration });
  if (end <= start) fail(`${label} must have positive duration`);
  return {
    start_ms: start,
    end_ms: end,
    evidence_sha256: sha256Value(raw.evidence_sha256, `${label}.evidence_sha256`),
  };
}

function deriveSourceMusicRegionId(regionWithoutId, outputDurationMs) {
  const duration = integer(outputDurationMs, 'output_duration_ms', {
    minimum: 1, maximum: MAX_OUTPUT_DURATION_MS,
  });
  const normalized = normalizeSourceRegionPayload(
    regionWithoutId, 'source music region binding', duration,
  );
  return `sourcemusic-${digestCanonical(normalized, 'source music region binding')}`;
}

function normalizeDialoguePayload(value, label, duration, transcript) {
  const raw = exactKeys(value, DIALOGUE_PAYLOAD_KEYS, label);
  const start = integer(raw.start_ms, `${label}.start_ms`, { maximum: duration });
  const end = integer(raw.end_ms, `${label}.end_ms`, { maximum: duration });
  if (end <= start) fail(`${label} must have positive duration`);
  const evidenceKind = enumValue(raw.evidence_kind, EVIDENCE_KIND_SET, `${label}.evidence_kind`);
  if (evidenceKind === 'transcript' && transcript === null) {
    fail(`${label} claims transcript evidence without a trusted transcript`);
  }
  return {
    start_ms: start,
    end_ms: end,
    evidence_kind: evidenceKind,
    evidence_sha256: sha256Value(raw.evidence_sha256, `${label}.evidence_sha256`),
  };
}

function deriveDialogueWindowId(windowWithoutId, outputDurationMs, transcriptSha256 = null) {
  const duration = integer(outputDurationMs, 'output_duration_ms', {
    minimum: 1, maximum: MAX_OUTPUT_DURATION_MS,
  });
  const transcript = nullableSha256(transcriptSha256, 'transcript_sha256');
  const normalized = normalizeDialoguePayload(
    windowWithoutId, 'dialogue window binding', duration, transcript,
  );
  return `dialogue-${digestCanonical(normalized, 'dialogue window binding')}`;
}

function normalizeBeatGridPayload(value, label, assets) {
  const raw = exactKeys(value, BEAT_GRID_PAYLOAD_KEYS, label);
  const assetId = identifier(raw.asset_id, ASSET_ID, `${label}.asset_id`);
  const asset = assets.get(assetId);
  if (!asset) fail(`${label}.asset_id is absent from the trusted asset manifest`);
  const assetHash = sha256Value(raw.asset_sha256, `${label}.asset_sha256`);
  if (assetHash !== asset.sha256) fail(`${label}.asset_sha256 does not match trusted bytes`);
  if (!isDenseArray(raw.beats_ms) || raw.beats_ms.length < 1 || raw.beats_ms.length > 65_536) {
    fail(`${label}.beats_ms has invalid cardinality`);
  }
  const beats = raw.beats_ms.map((item, index) => integer(
    item, `${label}.beats_ms[${index}]`, { maximum: asset.decoded_duration_ms },
  ));
  if (beats.some((item, index) => index > 0 && item <= beats[index - 1])) {
    fail(`${label}.beats_ms must be strictly increasing and unique`);
  }
  if (!isDenseArray(raw.downbeats_ms) || raw.downbeats_ms.length > beats.length) {
    fail(`${label}.downbeats_ms has invalid cardinality`);
  }
  const downbeats = raw.downbeats_ms.map((item, index) => integer(
    item, `${label}.downbeats_ms[${index}]`, { maximum: asset.decoded_duration_ms },
  ));
  const beatSet = new Set(beats);
  if (downbeats.some((item, index) =>
    (index > 0 && item <= downbeats[index - 1]) || !beatSet.has(item))) {
    fail(`${label}.downbeats_ms must be a sorted subset of beats_ms`);
  }
  return {
    asset_id: assetId,
    asset_sha256: assetHash,
    analysis_receipt_sha256: sha256Value(
      raw.analysis_receipt_sha256, `${label}.analysis_receipt_sha256`,
    ),
    beats_ms: beats,
    downbeats_ms: downbeats,
  };
}

function deriveBeatGridId(gridWithoutId, assets) {
  if (!isDenseArray(assets)) fail('assets must be a list');
  const assetMap = new Map();
  assets.forEach((value, index) => {
    const item = exactKeys(value, ASSET_KEYS, `assets[${index}]`);
    const payload = normalizeAssetPayload(pick(item, ASSET_PAYLOAD_KEYS), `assets[${index}]`);
    const assetId = identifier(item.asset_id, ASSET_ID, `assets[${index}].asset_id`);
    if (assetId !== deriveMusicAssetId(payload)) {
      fail(`assets[${index}].asset_id does not bind exact facts`);
    }
    assetMap.set(assetId, { asset_id: assetId, ...payload });
  });
  const normalized = normalizeBeatGridPayload(gridWithoutId, 'beat grid binding', assetMap);
  return `beatgrid-${digestCanonical(normalized, 'beat grid binding')}`;
}

function validateMusicAssetManifest(manifest) {
  const raw = exactKeys(manifest, MANIFEST_KEYS, 'music asset manifest');
  if (raw.schema_version !== MUSIC_ASSET_MANIFEST_SCHEMA_VERSION) {
    fail('music asset manifest schema_version is unsupported');
  }
  const timelineHash = sha256Value(
    raw.output_timeline_sha256, 'music asset manifest.output_timeline_sha256',
  );
  const duration = integer(raw.output_duration_ms, 'music asset manifest.output_duration_ms', {
    minimum: 1, maximum: MAX_OUTPUT_DURATION_MS,
  });
  const sampleRate = integer(
    raw.output_sample_rate_hz,
    'music asset manifest.output_sample_rate_hz',
    { minimum: 48_000, maximum: 48_000 },
  );
  const channels = integer(raw.output_channels, 'music asset manifest.output_channels', {
    minimum: 2, maximum: 2,
  });
  const transcript = nullableSha256(
    raw.transcript_sha256, 'music asset manifest.transcript_sha256',
  );

  if (!isDenseArray(raw.assets) || raw.assets.length > MAX_ASSETS) {
    fail('music asset manifest.assets has invalid cardinality');
  }
  const assets = [];
  const seenIds = new Set();
  const seenHashes = new Set();
  const seenRefs = new Set();
  raw.assets.forEach((rawAsset, index) => {
    const label = `music asset manifest.assets[${index}]`;
    const item = exactKeys(rawAsset, ASSET_KEYS, label);
    const payload = normalizeAssetPayload(pick(item, ASSET_PAYLOAD_KEYS), label);
    const assetId = identifier(item.asset_id, ASSET_ID, `${label}.asset_id`);
    if (assetId !== deriveMusicAssetId(payload)) {
      fail(`${label}.asset_id does not bind exact media and rights facts`);
    }
    if (seenIds.has(assetId) || seenHashes.has(payload.sha256) || seenRefs.has(payload.source_ref)) {
      fail('music assets must have unique ids, byte hashes, and source references');
    }
    seenIds.add(assetId);
    seenHashes.add(payload.sha256);
    seenRefs.add(payload.source_ref);
    assets.push({ asset_id: assetId, ...payload });
  });
  if (assets.some((item, index) => index > 0 &&
      asciiCompare(assets[index - 1].asset_id, item.asset_id) >= 0)) {
    fail('music asset manifest.assets must be ordered by asset_id');
  }
  const assetMap = new Map(assets.map((item) => [item.asset_id, item]));

  if (!isDenseArray(raw.beat_grids) || raw.beat_grids.length > MAX_BEAT_GRIDS) {
    fail('music asset manifest.beat_grids has invalid cardinality');
  }
  const grids = [];
  const gridIds = new Set();
  const gridAssets = new Set();
  raw.beat_grids.forEach((rawGrid, index) => {
    const label = `music asset manifest.beat_grids[${index}]`;
    const item = exactKeys(rawGrid, BEAT_GRID_KEYS, label);
    const payload = normalizeBeatGridPayload(pick(item, BEAT_GRID_PAYLOAD_KEYS), label, assetMap);
    const gridId = identifier(item.beat_grid_id, BEAT_GRID_ID, `${label}.beat_grid_id`);
    const expected = `beatgrid-${digestCanonical(payload, label)}`;
    if (gridId !== expected) {
      fail(`${label}.beat_grid_id does not bind exact trusted beat evidence`);
    }
    if (gridIds.has(gridId) || gridAssets.has(payload.asset_id)) {
      fail('music asset manifest permits only one unique beat grid per asset');
    }
    gridIds.add(gridId);
    gridAssets.add(payload.asset_id);
    grids.push({ beat_grid_id: gridId, ...payload });
  });
  if (grids.some((item, index) => index > 0 && (() => {
    const previous = grids[index - 1];
    return previous.asset_id > item.asset_id ||
      (previous.asset_id === item.asset_id && previous.beat_grid_id >= item.beat_grid_id);
  })())) {
    fail('music asset manifest.beat_grids must be ordered by asset_id then beat_grid_id');
  }

  if (!isDenseArray(raw.dialogue_windows) ||
      raw.dialogue_windows.length > MAX_DIALOGUE_WINDOWS) {
    fail('music asset manifest.dialogue_windows has invalid cardinality');
  }
  const dialogue = [];
  const dialogueIds = new Set();
  raw.dialogue_windows.forEach((rawWindow, index) => {
    const label = `music asset manifest.dialogue_windows[${index}]`;
    const item = exactKeys(rawWindow, DIALOGUE_KEYS, label);
    const payload = normalizeDialoguePayload(
      pick(item, DIALOGUE_PAYLOAD_KEYS), label, duration, transcript,
    );
    const windowId = identifier(
      item.dialogue_window_id, DIALOGUE_ID, `${label}.dialogue_window_id`,
    );
    const expected = `dialogue-${digestCanonical(payload, label)}`;
    if (windowId !== expected) fail(`${label}.dialogue_window_id does not bind exact evidence`);
    if (dialogueIds.has(windowId)) fail('dialogue window ids must be unique');
    dialogueIds.add(windowId);
    dialogue.push({ dialogue_window_id: windowId, ...payload });
  });
  if (dialogue.some((item, index) => index > 0 && (() => {
    const previous = dialogue[index - 1];
    return previous.start_ms > item.start_ms ||
      (previous.start_ms === item.start_ms &&
       previous.dialogue_window_id >= item.dialogue_window_id);
  })())) {
    fail('dialogue windows must be ordered by start_ms then id');
  }
  for (let index = 1; index < dialogue.length; index += 1) {
    if (dialogue[index - 1].end_ms > dialogue[index].start_ms) {
      fail('trusted dialogue windows must not overlap');
    }
  }

  const sourceRaw = exactKeys(
    raw.source_music, SOURCE_MUSIC_KEYS, 'music asset manifest.source_music',
  );
  const status = enumValue(
    sourceRaw.status, SOURCE_MUSIC_STATUS_SET, 'music asset manifest.source_music.status',
  );
  const sourceEvidence = sha256Value(
    sourceRaw.evidence_sha256, 'music asset manifest.source_music.evidence_sha256',
  );
  const authorization = nullableSha256(
    sourceRaw.exclusion_authorization_sha256,
    'music asset manifest.source_music.exclusion_authorization_sha256',
  );
  if (!isDenseArray(sourceRaw.regions) ||
      sourceRaw.regions.length > MAX_SOURCE_MUSIC_REGIONS) {
    fail('music asset manifest.source_music.regions has invalid cardinality');
  }
  const sourceRegions = [];
  const sourceIds = new Set();
  sourceRaw.regions.forEach((rawRegion, index) => {
    const label = `music asset manifest.source_music.regions[${index}]`;
    const item = exactKeys(rawRegion, SOURCE_REGION_KEYS, label);
    const payload = normalizeSourceRegionPayload(
      pick(item, SOURCE_REGION_PAYLOAD_KEYS), label, duration,
    );
    const regionId = identifier(
      item.source_region_id, SOURCE_REGION_ID, `${label}.source_region_id`,
    );
    if (regionId !== deriveSourceMusicRegionId(payload, duration)) {
      fail(`${label}.source_region_id does not bind exact source evidence`);
    }
    if (sourceIds.has(regionId)) fail('source music region ids must be unique');
    sourceIds.add(regionId);
    sourceRegions.push({ source_region_id: regionId, ...payload });
  });
  if (sourceRegions.some((item, index) => index > 0 && (() => {
    const previous = sourceRegions[index - 1];
    return previous.start_ms > item.start_ms ||
      (previous.start_ms === item.start_ms &&
       previous.source_region_id >= item.source_region_id);
  })())) {
    fail('source music regions must be ordered by start_ms then id');
  }
  for (let index = 1; index < sourceRegions.length; index += 1) {
    if (sourceRegions[index - 1].end_ms > sourceRegions[index].start_ms) {
      fail('source music regions must not overlap');
    }
  }
  if (status === 'absent' && (sourceRegions.length || authorization !== null)) {
    fail('absent source music cannot have regions or exclusion authority');
  }
  if (status === 'present' && !sourceRegions.length) {
    fail('present source music requires trusted detected regions');
  }

  return detach({
    schema_version: MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
    output_timeline_sha256: timelineHash,
    output_duration_ms: duration,
    output_sample_rate_hz: sampleRate,
    output_channels: channels,
    transcript_sha256: transcript,
    source_music: {
      status,
      evidence_sha256: sourceEvidence,
      exclusion_authorization_sha256: authorization,
      regions: sourceRegions,
    },
    assets,
    beat_grids: grids,
    dialogue_windows: dialogue,
  });
}

function canonicalMusicAssetManifestJson(manifest) {
  return canonicalJsonData(validateMusicAssetManifest(manifest), 'music asset manifest');
}

function musicAssetManifestSha256(manifest) {
  return digestText(canonicalMusicAssetManifestJson(manifest));
}

function masteringFromPolicy(policy) {
  const platform = policy.delivery.platform;
  if (platform === 'broadcast') {
    return { target_loudness_millilufs: -23_000, true_peak_ceiling_millidbtp: -2_000 };
  }
  if (platform === 'archive') {
    return { target_loudness_millilufs: -18_000, true_peak_ceiling_millidbtp: -2_000 };
  }
  return { target_loudness_millilufs: -14_000, true_peak_ceiling_millidbtp: -1_000 };
}

function policyLimits(policy, duration) {
  const profile = policy.profile;
  if (!Object.prototype.hasOwnProperty.call(PROFILE_REGION_INTERVAL_MS, profile)) {
    fail('edit policy profile has no closed music limits');
  }
  const usage = policy.rules.music.usage;
  const maxTracks = Math.min(PROFILE_TRACK_CEILING[profile], USAGE_TRACK_CEILING[usage]);
  const maxPolyphony = Math.min(maxTracks, USAGE_POLYPHONY_CEILING[usage]);
  let maxRegions;
  let coverage;
  if (['forbidden', 'source_primary'].includes(usage)) {
    maxRegions = 0;
    coverage = 0;
  } else {
    const interval = PROFILE_REGION_INTERVAL_MS[profile];
    maxRegions = Math.min(MAX_MUSIC_REGIONS, Math.floor((duration + interval - 1) / interval));
    coverage = usage === 'optional' ? Math.floor(duration / 2) : duration;
  }
  const dialoguePriority = policy.rules.dialogue.priority;
  return {
    profile,
    usage,
    duck_under_dialogue: policy.rules.music.duck_under_dialogue,
    max_added_track_count: maxTracks,
    max_region_count: maxRegions,
    max_polyphony: maxPolyphony,
    max_added_coverage_ms: coverage,
    max_gain_millidb: PROFILE_GAIN_CEILING[profile],
    speech_effective_gain_ceiling_millidb: SPEECH_GAIN_CEILING[dialoguePriority],
  };
}

function validatePolicyForMusic(editPolicy) {
  try {
    return validateEditPolicy(editPolicy);
  } catch (error) {
    if (error instanceof EditPolicyError) throw new MusicPlanError('edit policy is invalid');
    throw error;
  }
}

function deriveMusicPolicyLimits(editPolicy, outputDurationMs) {
  const duration = integer(outputDurationMs, 'output_duration_ms', {
    minimum: 1, maximum: MAX_OUTPUT_DURATION_MS,
  });
  const policy = validatePolicyForMusic(editPolicy);
  if (policy.duration.duration_ms !== duration) {
    fail('edit policy duration does not match the exact output duration');
  }
  return detach(policyLimits(policy, duration));
}

function deriveMusicMastering(editPolicy) {
  return detach(masteringFromPolicy(validatePolicyForMusic(editPolicy)));
}

function normalizePolicySnapshot(value, label) {
  const raw = exactKeys(value, POLICY_KEYS, label);
  return {
    profile: safeAscii(raw.profile, SAFE_ID, `${label}.profile`),
    usage: enumValue(raw.usage, MUSIC_USAGE_SET, `${label}.usage`),
    duck_under_dialogue: booleanValue(
      raw.duck_under_dialogue, `${label}.duck_under_dialogue`,
    ),
    max_added_track_count: integer(
      raw.max_added_track_count, `${label}.max_added_track_count`, { maximum: MAX_TRACKS },
    ),
    max_region_count: integer(
      raw.max_region_count, `${label}.max_region_count`, { maximum: MAX_MUSIC_REGIONS },
    ),
    max_polyphony: integer(
      raw.max_polyphony, `${label}.max_polyphony`, { maximum: MAX_TRACKS },
    ),
    max_added_coverage_ms: integer(
      raw.max_added_coverage_ms, `${label}.max_added_coverage_ms`,
      { maximum: MAX_OUTPUT_DURATION_MS },
    ),
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

function normalizeMastering(value, label) {
  const raw = exactKeys(value, MASTERING_KEYS, label);
  return {
    target_loudness_millilufs: integer(
      raw.target_loudness_millilufs, `${label}.target_loudness_millilufs`,
      { minimum: -40_000, maximum: -5_000 },
    ),
    true_peak_ceiling_millidbtp: integer(
      raw.true_peak_ceiling_millidbtp, `${label}.true_peak_ceiling_millidbtp`,
      { minimum: -9_000, maximum: -100 },
    ),
  };
}

function normalizeBeatSync(value, label) {
  if (value === null) return null;
  const raw = exactKeys(value, BEAT_SYNC_KEYS, label);
  return {
    beat_grid_id: identifier(raw.beat_grid_id, BEAT_GRID_ID, `${label}.beat_grid_id`),
    analysis_receipt_sha256: sha256Value(
      raw.analysis_receipt_sha256, `${label}.analysis_receipt_sha256`,
    ),
    asset_beat_ms: integer(raw.asset_beat_ms, `${label}.asset_beat_ms`, {
      maximum: MAX_ASSET_DURATION_MS,
    }),
    output_beat_ms: integer(raw.output_beat_ms, `${label}.output_beat_ms`, {
      maximum: MAX_OUTPUT_DURATION_MS,
    }),
  };
}

function normalizeDucking(value, label) {
  if (value === null) return null;
  const raw = exactKeys(value, DUCKING_KEYS, label);
  if (!isDenseArray(raw.dialogue_window_ids) ||
      raw.dialogue_window_ids.length < 1 ||
      raw.dialogue_window_ids.length > MAX_DIALOGUE_WINDOWS) {
    fail(`${label}.dialogue_window_ids has invalid cardinality`);
  }
  const ids = raw.dialogue_window_ids.map((item, index) => identifier(
    item, DIALOGUE_ID, `${label}.dialogue_window_ids[${index}]`,
  ));
  if (ids.some((item, index) => index > 0 && item <= ids[index - 1])) {
    fail(`${label}.dialogue_window_ids must be sorted and unique`);
  }
  const threshold = integer(raw.threshold_millidbfs, `${label}.threshold_millidbfs`, {
    minimum: -60_000, maximum: 0,
  });
  if (!DUCK_THRESHOLD_SET.has(threshold)) {
    fail(`${label}.threshold_millidbfs is not a deterministic v1 preset`);
  }
  const attenuation = integer(raw.attenuation_millidb, `${label}.attenuation_millidb`, {
    minimum: 1, maximum: 60_000,
  });
  if (!DUCK_ATTENUATION_SET.has(attenuation)) {
    fail(`${label}.attenuation_millidb is not a deterministic v1 preset`);
  }
  return {
    dialogue_window_ids: ids,
    threshold_millidbfs: threshold,
    attenuation_millidb: attenuation,
    attack_ms: integer(raw.attack_ms, `${label}.attack_ms`, { minimum: 1, maximum: 200 }),
    release_ms: integer(raw.release_ms, `${label}.release_ms`, {
      minimum: 1, maximum: 2_000,
    }),
  };
}

function normalizeRegionPayload(value, label) {
  const raw = exactKeys(value, REGION_PAYLOAD_KEYS, label);
  return {
    track_index: integer(raw.track_index, `${label}.track_index`, { maximum: MAX_TRACKS - 1 }),
    asset_id: identifier(raw.asset_id, ASSET_ID, `${label}.asset_id`),
    asset_sha256: sha256Value(raw.asset_sha256, `${label}.asset_sha256`),
    start_ms: integer(raw.start_ms, `${label}.start_ms`, { maximum: MAX_OUTPUT_DURATION_MS }),
    duration_ms: integer(raw.duration_ms, `${label}.duration_ms`, {
      minimum: 20, maximum: MAX_OUTPUT_DURATION_MS,
    }),
    trim_start_ms: integer(raw.trim_start_ms, `${label}.trim_start_ms`, {
      maximum: MAX_ASSET_DURATION_MS,
    }),
    playback_mode: enumValue(raw.playback_mode, PLAYBACK_MODE_SET, `${label}.playback_mode`),
    loop_length_ms: integer(raw.loop_length_ms, `${label}.loop_length_ms`, {
      maximum: MAX_ASSET_DURATION_MS,
    }),
    loop_crossfade_ms: integer(raw.loop_crossfade_ms, `${label}.loop_crossfade_ms`, {
      maximum: 2_000,
    }),
    gain_millidb: integer(raw.gain_millidb, `${label}.gain_millidb`, {
      minimum: -60_000, maximum: 6_000,
    }),
    fade_in_ms: integer(raw.fade_in_ms, `${label}.fade_in_ms`, { maximum: 10_000 }),
    fade_out_ms: integer(raw.fade_out_ms, `${label}.fade_out_ms`, { maximum: 10_000 }),
    crossfade_in_ms: integer(raw.crossfade_in_ms, `${label}.crossfade_in_ms`, {
      maximum: 5_000,
    }),
    crossfade_out_ms: integer(raw.crossfade_out_ms, `${label}.crossfade_out_ms`, {
      maximum: 5_000,
    }),
    beat_sync: normalizeBeatSync(raw.beat_sync, `${label}.beat_sync`),
    dialogue_ducking: normalizeDucking(raw.dialogue_ducking, `${label}.dialogue_ducking`),
  };
}

function deriveMusicRegionId(regionWithoutId) {
  const normalized = normalizeRegionPayload(regionWithoutId, 'music region binding');
  return `musicregion-${digestCanonical(normalized, 'music region binding')}`;
}

function normalizePlan(plan) {
  const raw = exactKeys(plan, PLAN_KEYS, 'music plan');
  if (raw.schema_version !== MUSIC_PLAN_SCHEMA_VERSION) {
    fail('music plan schema_version is unsupported');
  }
  if (!isDenseArray(raw.regions) || raw.regions.length > MAX_MUSIC_REGIONS) {
    fail('music plan.regions has invalid cardinality');
  }
  const regions = [];
  const ids = new Set();
  raw.regions.forEach((rawRegion, index) => {
    const label = `music plan.regions[${index}]`;
    const item = exactKeys(rawRegion, REGION_KEYS, label);
    const payload = normalizeRegionPayload(pick(item, REGION_PAYLOAD_KEYS), label);
    const regionId = identifier(item.region_id, REGION_ID, `${label}.region_id`);
    if (regionId !== deriveMusicRegionId(payload)) {
      fail(`${label}.region_id does not bind the exact region decision`);
    }
    if (ids.has(regionId)) fail('music region ids must be unique');
    ids.add(regionId);
    regions.push({ region_id: regionId, ...payload });
  });
  if (regions.some((item, index) => index > 0 && (() => {
    const previous = regions[index - 1];
    return previous.start_ms > item.start_ms ||
      (previous.start_ms === item.start_ms && previous.track_index > item.track_index) ||
      (previous.start_ms === item.start_ms && previous.track_index === item.track_index &&
       previous.region_id >= item.region_id);
  })())) {
    fail('music regions must be ordered by start_ms, track_index, then id');
  }
  return {
    schema_version: MUSIC_PLAN_SCHEMA_VERSION,
    music_asset_manifest_sha256: sha256Value(
      raw.music_asset_manifest_sha256, 'music plan.music_asset_manifest_sha256',
    ),
    edit_policy_sha256: sha256Value(
      raw.edit_policy_sha256, 'music plan.edit_policy_sha256',
    ),
    output_timeline_sha256: sha256Value(
      raw.output_timeline_sha256, 'music plan.output_timeline_sha256',
    ),
    output_duration_ms: integer(raw.output_duration_ms, 'music plan.output_duration_ms', {
      minimum: 1, maximum: MAX_OUTPUT_DURATION_MS,
    }),
    policy: normalizePolicySnapshot(raw.policy, 'music plan.policy'),
    mastering: normalizeMastering(raw.mastering, 'music plan.mastering'),
    source_music_action: enumValue(
      raw.source_music_action, SOURCE_MUSIC_ACTION_SET, 'music plan.source_music_action',
    ),
    regions,
  };
}

function canonicalMusicPlanJson(plan) {
  return canonicalJsonData(normalizePlan(plan), 'music plan');
}

function musicPlanSha256(plan) {
  return digestText(canonicalMusicPlanJson(plan));
}

function intersects(start, end, otherStart, otherEnd) {
  return Math.max(start, otherStart) < Math.min(end, otherEnd);
}

function maxPolyphony(intervals) {
  const events = [];
  for (const [start, end] of intervals) {
    events.push([start, 1], [end, -1]);
  }
  events.sort((left, right) => left[0] - right[0] || left[1] - right[1]);
  let active = 0;
  let observed = 0;
  for (const [, delta] of events) {
    active += delta;
    observed = Math.max(observed, active);
  }
  return observed;
}

function coverageMs(intervals) {
  if (!intervals.length) return 0;
  const ordered = intervals.map((item) => [...item]).sort(
    (left, right) => left[0] - right[0] || left[1] - right[1],
  );
  let total = 0;
  let [start, end] = ordered[0];
  for (const [nextStart, nextEnd] of ordered.slice(1)) {
    if (nextStart > end) {
      total += end - start;
      start = nextStart;
      end = nextEnd;
    } else {
      end = Math.max(end, nextEnd);
    }
  }
  return total + end - start;
}

function validateMusicPlan(plan, assetManifest, editPolicy) {
  const normalized = normalizePlan(plan);
  const manifest = validateMusicAssetManifest(assetManifest);
  const policy = validatePolicyForMusic(editPolicy);
  const policyHash = editPolicySha256(policy);
  if (policy.duration.duration_ms !== manifest.output_duration_ms) {
    fail('resolved edit policy duration does not match the trusted output duration');
  }
  if (normalized.music_asset_manifest_sha256 !== musicAssetManifestSha256(manifest)) {
    fail('music plan does not bind the trusted asset manifest');
  }
  if (normalized.edit_policy_sha256 !== policyHash) {
    fail('music plan does not bind the resolved edit policy');
  }
  if (normalized.output_timeline_sha256 !== manifest.output_timeline_sha256) {
    fail('music plan does not bind the trusted output timeline');
  }
  if (normalized.output_duration_ms !== manifest.output_duration_ms) {
    fail('music plan does not bind the exact output duration');
  }
  const expectedPolicy = policyLimits(policy, manifest.output_duration_ms);
  if (!equalCanonical(normalized.policy, expectedPolicy)) {
    fail('music plan policy snapshot does not match the resolved edit policy');
  }
  if (!equalCanonical(normalized.mastering, masteringFromPolicy(policy))) {
    fail('music plan mastering target does not match delivery policy');
  }
  if (normalized.regions.length > expectedPolicy.max_region_count) {
    fail('music plan exceeds its profile/duration region density ceiling');
  }

  const source = manifest.source_music;
  const action = normalized.source_music_action;
  if (source.status === 'absent') {
    if (action !== 'none') fail('source music action must be none when source music is absent');
  } else {
    if (action !== 'preserve') fail('present source music must be preserved by music contract v1');
  }
  const usage = expectedPolicy.usage;
  if (['forbidden', 'source_primary'].includes(usage) && normalized.regions.length) {
    fail('music policy permits no added music assets');
  }
  if (usage === 'source_primary' && (source.status !== 'present' || action !== 'preserve')) {
    fail('source-primary music requires detected source music to be preserved');
  }
  if (usage === 'forbidden' && source.status === 'present' && action !== 'preserve') {
    fail('forbidden added music does not authorize deleting source programme audio');
  }

  const assets = new Map(manifest.assets.map((item) => [item.asset_id, item]));
  const grids = new Map(manifest.beat_grids.map((item) => [item.beat_grid_id, item]));
  const dialogue = new Map(
    manifest.dialogue_windows.map((item) => [item.dialogue_window_id, item]),
  );
  const intervals = [];
  const trackRegions = new Map();
  const usedTracks = new Set();
  normalized.regions.forEach((region, index) => {
    const label = `music plan.regions[${index}]`;
    const asset = assets.get(region.asset_id);
    if (!asset) fail(`${label}.asset_id is absent from the trusted manifest`);
    if (region.asset_sha256 !== asset.sha256) {
      fail(`${label}.asset_sha256 does not match trusted bytes`);
    }
    const rights = asset.rights_receipt;
    if (!rights.permits_synchronization || !rights.permits_editing || !rights.permits_delivery) {
      fail(`${label} lacks explicit synchronization, editing, or delivery rights`);
    }
    const start = region.start_ms;
    const end = start + region.duration_ms;
    if (end > manifest.output_duration_ms) {
      fail(`${label} extends beyond the exact output duration`);
    }
    if (region.gain_millidb > expectedPolicy.max_gain_millidb) {
      fail(`${label}.gain_millidb exceeds its profile ceiling`);
    }
    if (region.fade_in_ms + region.fade_out_ms > region.duration_ms) {
      fail(`${label} fade-in and fade-out overlap`);
    }
    if (region.crossfade_in_ms > region.fade_in_ms ||
        region.crossfade_out_ms > region.fade_out_ms) {
      fail(`${label} crossfade must be covered by its edge fade`);
    }
    if (region.crossfade_in_ms || region.crossfade_out_ms) {
      fail(`${label} crossfade topology is not executable in music contract v1`);
    }
    const mode = region.playback_mode;
    if (mode === 'once') {
      if (region.loop_length_ms !== 0 || region.loop_crossfade_ms !== 0) {
        fail(`${label} once playback cannot carry loop parameters`);
      }
      if (region.trim_start_ms + region.duration_ms > asset.decoded_duration_ms) {
        fail(`${label} trim exceeds trusted decoded asset duration`);
      }
    } else fail(`${label} loop playback is not executable in music contract v1`);

    const beat = region.beat_sync;
    if (beat !== null) {
      const grid = grids.get(beat.beat_grid_id);
      if (!grid || grid.asset_id !== asset.asset_id) {
        fail(`${label}.beat_sync is not grounded in a trusted grid for this asset`);
      }
      if (beat.analysis_receipt_sha256 !== grid.analysis_receipt_sha256) {
        fail(`${label}.beat_sync does not copy the trusted analysis receipt`);
      }
      if (!grid.beats_ms.includes(beat.asset_beat_ms)) {
        fail(`${label}.beat_sync asset beat is absent from trusted evidence`);
      }
      if (beat.asset_beat_ms !== region.trim_start_ms || beat.output_beat_ms !== start) {
        fail(`${label}.beat_sync does not map the selected source beat to region start`);
      }
      if (mode === 'loop' &&
          !grid.beats_ms.includes(region.trim_start_ms + region.loop_length_ms)) {
        fail(`${label} loop endpoint is not grounded in the trusted beat grid`);
      }
    }

    const overlappingDialogue = [...dialogue.entries()]
      .filter(([, window]) => intersects(start, end, window.start_ms, window.end_ms))
      .map(([windowId]) => windowId)
      .sort(asciiCompare);
    const duck = region.dialogue_ducking;
    if (duck !== null) {
      fail(`${label} dialogue sidechain topology is not executable in music contract v1`);
    }
    if (overlappingDialogue.length && expectedPolicy.duck_under_dialogue) {
      fail(`${label} overlaps dialogue that requires an unimplemented v1 sidechain`);
    } else if (duck !== null) {
      fail(`${label}.dialogue_ducking is unmotivated by policy-grounded dialogue overlap`);
    }

    if (action === 'preserve') {
      for (const sourceRegion of source.regions) {
        if (intersects(start, end, sourceRegion.start_ms, sourceRegion.end_ms)) {
          fail(`${label} overlaps source music that must be preserved exclusively`);
        }
      }
    }
    intervals.push([start, end]);
    usedTracks.add(region.track_index);
    if (!trackRegions.has(region.track_index)) trackRegions.set(region.track_index, []);
    trackRegions.get(region.track_index).push(region);
  });

  if (usedTracks.size) {
    const highest = Math.max(...usedTracks);
    for (let track = 0; track <= highest; track += 1) {
      if (!usedTracks.has(track)) fail('music track indices must be contiguous from zero');
    }
  }
  if (usedTracks.size > expectedPolicy.max_added_track_count) {
    fail('music plan exceeds its profile/usage added-track ceiling');
  }
  if (maxPolyphony(intervals) > expectedPolicy.max_polyphony) {
    fail('music plan exceeds its profile/usage polyphony ceiling');
  }
  if (coverageMs(intervals) > expectedPolicy.max_added_coverage_ms) {
    fail('music plan exceeds its usage coverage ceiling');
  }

  for (const [trackIndex, regions] of trackRegions.entries()) {
    const ordered = [...regions].sort((left, right) =>
      left.start_ms - right.start_ms || asciiCompare(left.region_id, right.region_id));
    if (ordered[0].crossfade_in_ms !== 0 ||
        ordered[ordered.length - 1].crossfade_out_ms !== 0) {
      fail(`music track ${trackIndex} has an unpaired edge crossfade`);
    }
    for (let index = 1; index < ordered.length; index += 1) {
      const left = ordered[index - 1];
      const right = ordered[index];
      const overlap = Math.max(0, left.start_ms + left.duration_ms - right.start_ms);
      if (left.crossfade_out_ms !== overlap || right.crossfade_in_ms !== overlap) {
        fail(`music track ${trackIndex} crossfade does not equal exact region overlap`);
      }
      if (overlap > Math.min(
        5_000, Math.floor(left.duration_ms / 2), Math.floor(right.duration_ms / 2),
      )) {
        fail(`music track ${trackIndex} crossfade exceeds adjacent duration guards`);
      }
      if (overlap) {
        fail(`music track ${trackIndex} crossfade topology is not executable in music contract v1`);
      }
    }
  }
  return detach(normalized);
}

function normalizeReceipt(receipt) {
  const raw = exactKeys(receipt, RECEIPT_KEYS, 'music compile receipt');
  if (raw.schema_version !== MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION) {
    fail('music compile receipt schema_version is unsupported');
  }
  const hashes = {};
  for (const key of [
    'music_plan_sha256', 'music_asset_manifest_sha256', 'edit_policy_sha256',
    'output_timeline_sha256', 'compiled_regions_sha256', 'mix_primitives_sha256',
  ]) {
    hashes[key] = sha256Value(raw[key], `music compile receipt.${key}`);
  }
  if (!isDenseArray(raw.ordered_region_ids) ||
      raw.ordered_region_ids.length > MAX_MUSIC_REGIONS) {
    fail('music compile receipt.ordered_region_ids has invalid cardinality');
  }
  if (!isDenseArray(raw.ordered_asset_ids) ||
      raw.ordered_asset_ids.length !== raw.ordered_region_ids.length) {
    fail('music compile receipt.ordered_asset_ids must align one-to-one');
  }
  const regionIds = raw.ordered_region_ids.map((item, index) => identifier(
    item, REGION_ID, `music compile receipt.ordered_region_ids[${index}]`,
  ));
  if (new Set(regionIds).size !== regionIds.length) {
    fail('music compile receipt region ids must be unique');
  }
  const assetIds = raw.ordered_asset_ids.map((item, index) => identifier(
    item, ASSET_ID, `music compile receipt.ordered_asset_ids[${index}]`,
  ));
  const regionCount = integer(raw.region_count, 'music compile receipt.region_count', {
    maximum: MAX_MUSIC_REGIONS,
  });
  if (regionCount !== regionIds.length) {
    fail('music compile receipt.region_count does not match ids');
  }
  const uniqueCount = integer(
    raw.unique_asset_count, 'music compile receipt.unique_asset_count',
    { maximum: MAX_ASSETS },
  );
  if (uniqueCount !== new Set(assetIds).size) {
    fail('music compile receipt.unique_asset_count does not match ids');
  }
  const timeBase = exactKeys(
    raw.time_base, BASE_KEYS, 'music compile receipt.time_base',
  );
  const millidbBase = exactKeys(
    raw.millidb_base, BASE_KEYS, 'music compile receipt.millidb_base',
  );
  if (timeBase.numerator !== 1 || timeBase.denominator !== 1_000 ||
      millidbBase.numerator !== 1 || millidbBase.denominator !== 1_000) {
    fail('music compile receipt bases must be exact 1/1000');
  }
  const outputRate = integer(
    raw.output_sample_rate_hz, 'music compile receipt.output_sample_rate_hz',
    { minimum: 48_000, maximum: 48_000 },
  );
  const outputDuration = integer(
    raw.output_duration_ms, 'music compile receipt.output_duration_ms',
    { minimum: 1, maximum: MAX_OUTPUT_DURATION_MS },
  );
  const addedTracks = integer(
    raw.added_track_count, 'music compile receipt.added_track_count',
    { maximum: MAX_TRACKS },
  );
  const polyphony = integer(
    raw.max_observed_polyphony, 'music compile receipt.max_observed_polyphony',
    { maximum: MAX_TRACKS },
  );
  const coverage = integer(
    raw.added_coverage_ms, 'music compile receipt.added_coverage_ms',
    { maximum: MAX_OUTPUT_DURATION_MS },
  );
  if (addedTracks > regionCount || polyphony > regionCount || coverage > outputDuration) {
    fail('music compile receipt aggregate counts exceed their bound timeline/regions');
  }
  if (regionCount === 0 && (addedTracks || polyphony || coverage)) {
    fail('empty music compile receipt must have zero aggregate usage');
  }
  return {
    schema_version: MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
    ...hashes,
    ordered_region_ids: regionIds,
    ordered_asset_ids: assetIds,
    region_count: regionCount,
    unique_asset_count: uniqueCount,
    added_track_count: addedTracks,
    max_observed_polyphony: polyphony,
    added_coverage_ms: coverage,
    dialogue_overlap_region_count: integer(
      raw.dialogue_overlap_region_count,
      'music compile receipt.dialogue_overlap_region_count',
      { maximum: regionCount },
    ),
    beat_synced_region_count: integer(
      raw.beat_synced_region_count, 'music compile receipt.beat_synced_region_count',
      { maximum: regionCount },
    ),
    looped_region_count: integer(
      raw.looped_region_count, 'music compile receipt.looped_region_count',
      { maximum: regionCount },
    ),
    source_music_action: enumValue(
      raw.source_music_action, SOURCE_MUSIC_ACTION_SET,
      'music compile receipt.source_music_action',
    ),
    output_duration_ms: outputDuration,
    output_sample_rate_hz: outputRate,
    output_channels: integer(
      raw.output_channels, 'music compile receipt.output_channels',
      { minimum: 2, maximum: 2 },
    ),
    target_loudness_millilufs: integer(
      raw.target_loudness_millilufs,
      'music compile receipt.target_loudness_millilufs',
      { minimum: -40_000, maximum: -5_000 },
    ),
    true_peak_ceiling_millidbtp: integer(
      raw.true_peak_ceiling_millidbtp,
      'music compile receipt.true_peak_ceiling_millidbtp',
      { minimum: -9_000, maximum: -100 },
    ),
    time_base: { numerator: 1, denominator: 1_000 },
    millidb_base: { numerator: 1, denominator: 1_000 },
    policy: normalizePolicySnapshot(raw.policy, 'music compile receipt.policy'),
  };
}

function musicCompileReceiptSha256(receipt) {
  return digestCanonical(normalizeReceipt(receipt), 'music compile receipt');
}

function compileMusicPlan(plan, assetManifest, editPolicy) {
  const validated = validateMusicPlan(plan, assetManifest, editPolicy);
  const manifest = validateMusicAssetManifest(assetManifest);
  const assets = new Map(manifest.assets.map((item) => [item.asset_id, item]));
  const dialogue = manifest.dialogue_windows;
  const compiled = [];
  const intervals = [];
  const dialogueOverlapCount = 0;
  let beatCount = 0;
  const loopCount = 0;

  validated.regions.forEach((region, index) => {
    const asset = assets.get(region.asset_id);
    const start = region.start_ms;
    const end = start + region.duration_ms;
    intervals.push([start, end]);
    const sourceTokens = [
      `atrim=start=${ffmpegSeconds(region.trim_start_ms)}` +
      `:duration=${ffmpegSeconds(region.duration_ms)}`,
      'asetpts=PTS-STARTPTS',
      'aresample=48000',
      'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
    ];
    const loopTokens = [];
    const edgeTokens = [];
    if (region.fade_in_ms) {
      edgeTokens.push(
        `afade=t=in:st=0.000:d=${ffmpegSeconds(region.fade_in_ms)}:curve=qsin`,
      );
    }
    if (region.fade_out_ms) {
      edgeTokens.push(
        `afade=t=out:st=${ffmpegSeconds(region.duration_ms - region.fade_out_ms)}` +
        `:d=${ffmpegSeconds(region.fade_out_ms)}:curve=qsin`,
      );
    }
    edgeTokens.push(`volume=${ffmpegMillidb(region.gain_millidb)}:precision=fixed`);
    const duckTokens = [];
    if (region.beat_sync !== null) beatCount += 1;
    const timelineTokens = [`adelay=delays=${start}:all=1`];
    for (const [name, tokens] of [
      ['source', sourceTokens], ['loop', loopTokens], ['edge', edgeTokens],
      ['duck', duckTokens], ['timeline', timelineTokens],
    ]) {
      validateTokens(tokens, `compiled region ${index} ${name} tokens`);
    }
    compiled.push({
      region_index: index,
      region_id: region.region_id,
      track_index: region.track_index,
      asset_id: asset.asset_id,
      asset_sha256: asset.sha256,
      asset_byte_length: asset.byte_length,
      asset_decoded_duration_ms: asset.decoded_duration_ms,
      asset_sample_rate_hz: asset.sample_rate_hz,
      asset_channels: asset.channels,
      source_ref: asset.source_ref,
      provenance: asset.provenance,
      license: asset.license,
      rights_receipt: asset.rights_receipt,
      output_start_ms: start,
      output_end_ms: end,
      playback_mode: region.playback_mode,
      beat_sync: region.beat_sync,
      dialogue_ducking: region.dialogue_ducking,
      dialogue_overlap_ms: dialogue.reduce(
        (total, item) => total + Math.max(
          0, Math.min(end, item.end_ms) - Math.max(start, item.start_ms),
        ),
        0,
      ),
      source_ffmpeg_primitive_tokens: sourceTokens,
      loop_ffmpeg_primitive_tokens: loopTokens,
      edge_ffmpeg_primitive_tokens: edgeTokens,
      dialogue_sidechain_ffmpeg_primitive_tokens: duckTokens,
      timeline_ffmpeg_primitive_tokens: timelineTokens,
    });
  });

  const tracks = [...new Set(validated.regions.map((item) => item.track_index))]
    .sort((left, right) => left - right);
  const crossfadeTokens = [];
  const musicBusTokens = compiled.length === 0 ? [] : [
    `amix=inputs=${tracks.length}:duration=longest:dropout_transition=0:normalize=0`,
    `apad=whole_dur=${ffmpegSeconds(manifest.output_duration_ms)}`,
    `atrim=start=0.000:duration=${ffmpegSeconds(manifest.output_duration_ms)}`,
    'asetpts=PTS-STARTPTS',
  ];
  const mastering = validated.mastering;
  const programTokens = compiled.length === 0 ? [] : [
    'aresample=48000',
    'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
    `apad=whole_dur=${ffmpegSeconds(manifest.output_duration_ms)}`,
    `atrim=start=0.000:duration=${ffmpegSeconds(manifest.output_duration_ms)}`,
    'asetpts=PTS-STARTPTS',
    'amix=inputs=2:duration=first:dropout_transition=0:normalize=0',
    `loudnorm=I=${ffmpegMillidb(mastering.target_loudness_millilufs, '')}` +
    `:TP=${ffmpegMillidb(mastering.true_peak_ceiling_millidbtp, '')}` +
    ':LRA=11.000:linear=true',
  ];
  const outputArgs = [
    '-map', 'AUTOEDITOR_PROGRAM_AUDIO', '-ar', String(manifest.output_sample_rate_hz),
    '-ac', String(manifest.output_channels),
  ];
  for (const [name, tokens] of [
    ['track crossfade', crossfadeTokens], ['music bus', musicBusTokens],
    ['program mix', programTokens], ['output arguments', outputArgs],
  ]) {
    validateTokens(tokens, `compiled ${name} tokens`);
  }
  const mixPrimitives = {
    track_crossfade_ffmpeg_primitive_tokens: crossfadeTokens,
    music_bus_ffmpeg_primitive_tokens: musicBusTokens,
    program_mix_ffmpeg_primitive_tokens: programTokens,
    output_ffmpeg_argument_tokens: outputArgs,
  };
  const compiledHash = digestCanonical(compiled, 'compiled music regions');
  const mixHash = digestCanonical(mixPrimitives, 'compiled music mix primitives');
  const receipt = normalizeReceipt({
    schema_version: MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
    music_plan_sha256: musicPlanSha256(validated),
    music_asset_manifest_sha256: musicAssetManifestSha256(manifest),
    edit_policy_sha256: editPolicySha256(editPolicy),
    output_timeline_sha256: manifest.output_timeline_sha256,
    compiled_regions_sha256: compiledHash,
    mix_primitives_sha256: mixHash,
    ordered_region_ids: compiled.map((item) => item.region_id),
    ordered_asset_ids: compiled.map((item) => item.asset_id),
    region_count: compiled.length,
    unique_asset_count: new Set(compiled.map((item) => item.asset_id)).size,
    added_track_count: new Set(compiled.map((item) => item.track_index)).size,
    max_observed_polyphony: maxPolyphony(intervals),
    added_coverage_ms: coverageMs(intervals),
    dialogue_overlap_region_count: dialogueOverlapCount,
    beat_synced_region_count: beatCount,
    looped_region_count: loopCount,
    source_music_action: validated.source_music_action,
    output_duration_ms: manifest.output_duration_ms,
    output_sample_rate_hz: manifest.output_sample_rate_hz,
    output_channels: manifest.output_channels,
    target_loudness_millilufs: mastering.target_loudness_millilufs,
    true_peak_ceiling_millidbtp: mastering.true_peak_ceiling_millidbtp,
    time_base: { numerator: 1, denominator: 1_000 },
    millidb_base: { numerator: 1, denominator: 1_000 },
    policy: validated.policy,
  });
  return {
    schema_version: MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
    compiled_regions: detach(compiled),
    ...detach(mixPrimitives),
    receipt: detach(receipt),
    receipt_sha256: musicCompileReceiptSha256(receipt),
  };
}

function validateMusicCompileResult(result, plan, assetManifest, editPolicy) {
  const raw = exactKeys(result, COMPILE_RESULT_KEYS, 'music compile result');
  const expected = compileMusicPlan(plan, assetManifest, editPolicy);
  if (canonicalJsonData(raw, 'music compile result') !==
      canonicalJsonData(expected, 'expected music compile result')) {
    fail('music compile result does not exactly match deterministic compilation');
  }
  return detach(expected);
}

const POLICY_JSON_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [...POLICY_KEYS],
  properties: {
    profile: { type: 'string', pattern: '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$' },
    usage: { type: 'string', enum: [...MUSIC_USAGES] },
    duck_under_dialogue: { type: 'boolean' },
    max_added_track_count: { type: 'integer', minimum: 0, maximum: MAX_TRACKS },
    max_region_count: { type: 'integer', minimum: 0, maximum: MAX_MUSIC_REGIONS },
    max_polyphony: { type: 'integer', minimum: 0, maximum: MAX_TRACKS },
    max_added_coverage_ms: {
      type: 'integer', minimum: 0, maximum: MAX_OUTPUT_DURATION_MS,
    },
    max_gain_millidb: { type: 'integer', minimum: -60_000, maximum: 6_000 },
    speech_effective_gain_ceiling_millidb: {
      type: 'integer', minimum: -60_000, maximum: 0,
    },
  },
};
const MASTERING_JSON_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [...MASTERING_KEYS],
  properties: {
    target_loudness_millilufs: {
      type: 'integer', minimum: -40_000, maximum: -5_000,
    },
    true_peak_ceiling_millidbtp: {
      type: 'integer', minimum: -9_000, maximum: -100,
    },
  },
};
const BEAT_SYNC_JSON_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [...BEAT_SYNC_KEYS],
  properties: {
    beat_grid_id: { type: 'string', pattern: '^beatgrid-[0-9a-f]{64}$' },
    analysis_receipt_sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
    asset_beat_ms: { type: 'integer', minimum: 0, maximum: MAX_ASSET_DURATION_MS },
    output_beat_ms: { type: 'integer', minimum: 0, maximum: MAX_OUTPUT_DURATION_MS },
  },
};
const DUCKING_JSON_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [...DUCKING_KEYS],
  properties: {
    dialogue_window_ids: {
      type: 'array',
      minItems: 1,
      maxItems: MAX_DIALOGUE_WINDOWS,
      uniqueItems: true,
      items: { type: 'string', pattern: '^dialogue-[0-9a-f]{64}$' },
    },
    threshold_millidbfs: { type: 'integer', enum: [...DUCK_THRESHOLDS_MILLIDBFS] },
    attenuation_millidb: { type: 'integer', enum: [...DUCK_ATTENUATIONS_MILLIDB] },
    attack_ms: { type: 'integer', minimum: 1, maximum: 200 },
    release_ms: { type: 'integer', minimum: 1, maximum: 2_000 },
  },
};
const REGION_JSON_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [...REGION_KEYS],
  properties: {
    region_id: { type: 'string', pattern: '^musicregion-[0-9a-f]{64}$' },
    track_index: { type: 'integer', minimum: 0, maximum: MAX_TRACKS - 1 },
    asset_id: { type: 'string', pattern: '^musicasset-[0-9a-f]{64}$' },
    asset_sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
    start_ms: { type: 'integer', minimum: 0, maximum: MAX_OUTPUT_DURATION_MS },
    duration_ms: { type: 'integer', minimum: 20, maximum: MAX_OUTPUT_DURATION_MS },
    trim_start_ms: { type: 'integer', minimum: 0, maximum: MAX_ASSET_DURATION_MS },
    playback_mode: { const: 'once' },
    loop_length_ms: { const: 0 },
    loop_crossfade_ms: { const: 0 },
    gain_millidb: { type: 'integer', minimum: -60_000, maximum: 6_000 },
    fade_in_ms: { type: 'integer', minimum: 0, maximum: 10_000 },
    fade_out_ms: { type: 'integer', minimum: 0, maximum: 10_000 },
    crossfade_in_ms: { const: 0 },
    crossfade_out_ms: { const: 0 },
    beat_sync: { oneOf: [{ type: 'null' }, detach(BEAT_SYNC_JSON_SCHEMA)] },
    dialogue_ducking: { const: null },
  },
};

const MUSIC_PLAN_JSON_SCHEMA = Object.freeze({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  additionalProperties: false,
  required: [...PLAN_KEYS],
  properties: {
    schema_version: { const: MUSIC_PLAN_SCHEMA_VERSION },
    music_asset_manifest_sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
    edit_policy_sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
    output_timeline_sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
    output_duration_ms: {
      type: 'integer', minimum: 1, maximum: MAX_OUTPUT_DURATION_MS,
    },
    policy: detach(POLICY_JSON_SCHEMA),
    mastering: detach(MASTERING_JSON_SCHEMA),
    source_music_action: { type: 'string', enum: [...SOURCE_MUSIC_ACTIONS] },
    regions: {
      type: 'array',
      maxItems: MAX_MUSIC_REGIONS,
      items: {
        ...detach(REGION_JSON_SCHEMA),
      },
    },
  },
});

module.exports = Object.freeze({
  MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
  MUSIC_PLAN_SCHEMA_VERSION,
  MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
  MAX_SAFE_INTEGER,
  MAX_ASSETS,
  MAX_BEAT_GRIDS,
  MAX_DIALOGUE_WINDOWS,
  MAX_SOURCE_MUSIC_REGIONS,
  MAX_MUSIC_REGIONS,
  MAX_TRACKS,
  MAX_ASSET_BYTES,
  MAX_ASSET_DURATION_MS,
  MAX_OUTPUT_DURATION_MS,
  SAMPLE_RATES_HZ,
  PROVENANCE_KINDS,
  LICENSE_BASES,
  MUSIC_USAGES,
  SOURCE_MUSIC_STATUSES,
  SOURCE_MUSIC_ACTIONS,
  PLAYBACK_MODES,
  EVIDENCE_KINDS,
  DUCK_ATTENUATIONS_MILLIDB,
  DUCK_THRESHOLDS_MILLIDBFS,
  MUSIC_PLAN_JSON_SCHEMA,
  MusicPlanError,
  deriveMusicAssetId,
  deriveSourceMusicRegionId,
  deriveDialogueWindowId,
  deriveBeatGridId,
  validateMusicAssetManifest,
  canonicalMusicAssetManifestJson,
  musicAssetManifestSha256,
  deriveMusicPolicyLimits,
  deriveMusicMastering,
  deriveMusicRegionId,
  canonicalMusicPlanJson,
  musicPlanSha256,
  validateMusicPlan,
  musicCompileReceiptSha256,
  compileMusicPlan,
  validateMusicCompileResult,
});
