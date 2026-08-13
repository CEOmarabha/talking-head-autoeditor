'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const test = require('node:test');

const {
  CAPABILITIES,
  EDIT_POLICY_REQUEST_SCHEMA_VERSION,
  editPolicySha256,
  resolveEditPolicy,
} = require('../helper/lib/edit-policy');
const {
  MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
  MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION,
  MUSIC_PLAN_JSON_SCHEMA,
  MUSIC_PLAN_SCHEMA_VERSION,
  MusicPlanError,
  canonicalMusicAssetManifestJson,
  canonicalMusicPlanJson,
  compileMusicPlan,
  deriveBeatGridId,
  deriveDialogueWindowId,
  deriveMusicAssetId,
  deriveMusicMastering,
  deriveMusicPolicyLimits,
  deriveMusicRegionId,
  deriveSourceMusicRegionId,
  musicAssetManifestSha256,
  musicCompileReceiptSha256,
  musicPlanSha256,
  validateMusicAssetManifest,
  validateMusicCompileResult,
  validateMusicPlan,
} = require('../helper/lib/music-plan');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function hash(label) {
  return crypto.createHash('sha256').update(label, 'utf8').digest('hex');
}

function autoValues() {
  return {
    cut_density: 'auto',
    sfx_density: 'auto',
    transition_density: 'auto',
    dialogue_rule: 'auto',
    music_rule: 'auto',
    caption_rule: 'auto',
    visualization_rule: 'auto',
  };
}

function makePolicy({
  profile = 'montage_meme',
  durationMs = 6_000,
  musicRule = 'auto',
  platform = 'web',
} = {}) {
  const explicit = autoValues();
  explicit.music_rule = musicRule;
  return resolveEditPolicy({
    schema_version: EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    profile,
    duration_ms: durationMs,
    delivery: { platform, aspect: 'auto' },
    explicit_intent: explicit,
    consented_preferences: { consented: false, values: autoValues() },
    available_capabilities: [...CAPABILITIES].sort(),
  });
}

function makeAssetPayload({
  name = 'vector',
  unicodeLicense = true,
  sampleRateHz = 44_100,
  channels = 1,
} = {}) {
  return {
    sha256: hash(`music-${name}-bytes`),
    byte_length: name === 'vector' ? 123_456 : 123_456 + name.length,
    decoded_duration_ms: 12_000,
    sample_rate_hz: sampleRateHz,
    channels,
    source_ref: `licensed-external://music/${name}.wav`,
    provenance: 'licensed_external',
    license: {
      basis: 'licensed_external',
      license_id: `license-${name}`,
      license_name: unicodeLicense ? 'Édition 🌍' : 'Worldwide music license',
      licensor: unicodeLicense ? 'Música Société' : 'Example Music Ltd',
      evidence_sha256: hash(`music-${name}-license`),
    },
    rights_receipt: {
      receipt_id: `rights-${name}`,
      receipt_sha256: hash(`music-${name}-rights`),
      permits_synchronization: true,
      permits_editing: true,
      permits_looping: true,
      permits_delivery: true,
    },
  };
}

function bindAsset(payload) {
  const clean = clone(payload);
  return { asset_id: deriveMusicAssetId(clean), ...clean };
}

function makeAsset(options) {
  return bindAsset(makeAssetPayload(options));
}

function makeBeatGrid(asset) {
  const payload = {
    asset_id: asset.asset_id,
    asset_sha256: asset.sha256,
    analysis_receipt_sha256: hash('music-vector-beats'),
    beats_ms: Array.from({ length: 13 }, (_, index) => index * 1_000),
    downbeats_ms: [0, 4_000, 8_000, 12_000],
  };
  return { beat_grid_id: deriveBeatGridId(payload, [asset]), ...payload };
}

function makeManifest({ includeDialogue = false, asset = makeAsset() } = {}) {
  const grid = makeBeatGrid(asset);
  const transcript = includeDialogue ? hash('trusted-transcript') : null;
  const dialogue = [];
  if (includeDialogue) {
    const payload = {
      start_ms: 2_000,
      end_ms: 4_000,
      evidence_kind: 'transcript',
      evidence_sha256: hash('dialogue-2000-4000'),
    };
    dialogue.push({
      dialogue_window_id: deriveDialogueWindowId(payload, 6_000, transcript),
      ...payload,
    });
  }
  return {
    schema_version: MUSIC_ASSET_MANIFEST_SCHEMA_VERSION,
    output_timeline_sha256: hash('music-vector-timeline'),
    output_duration_ms: 6_000,
    output_sample_rate_hz: 48_000,
    output_channels: 2,
    transcript_sha256: transcript,
    source_music: {
      status: 'absent',
      evidence_sha256: hash('music-vector-source-analysis'),
      exclusion_authorization_sha256: null,
      regions: [],
    },
    assets: [asset],
    beat_grids: [grid],
    dialogue_windows: dialogue,
  };
}

function makeBeatSync(manifest) {
  const grid = manifest.beat_grids[0];
  return {
    beat_grid_id: grid.beat_grid_id,
    analysis_receipt_sha256: grid.analysis_receipt_sha256,
    asset_beat_ms: 0,
    output_beat_ms: 0,
  };
}

function makeRegion(manifest, overrides = {}) {
  const asset = manifest.assets[0];
  const payload = {
    track_index: 0,
    asset_id: asset.asset_id,
    asset_sha256: asset.sha256,
    start_ms: 0,
    duration_ms: 6_000,
    trim_start_ms: 0,
    playback_mode: 'once',
    loop_length_ms: 0,
    loop_crossfade_ms: 0,
    gain_millidb: -6_000,
    fade_in_ms: 500,
    fade_out_ms: 500,
    crossfade_in_ms: 0,
    crossfade_out_ms: 0,
    beat_sync: makeBeatSync(manifest),
    dialogue_ducking: null,
    ...clone(overrides),
  };
  return { region_id: deriveMusicRegionId(payload), ...payload };
}

function refreshRegion(region) {
  const payload = clone(region);
  delete payload.region_id;
  region.region_id = deriveMusicRegionId(payload);
}

function makePlan(manifest = makeManifest(), policy = makePolicy(), regions = null, {
  sourceMusicAction = 'none',
} = {}) {
  const selected = regions === null ? [makeRegion(manifest)] : clone(regions);
  selected.sort((left, right) =>
    left.start_ms - right.start_ms || left.track_index - right.track_index ||
    left.region_id.localeCompare(right.region_id));
  return {
    schema_version: MUSIC_PLAN_SCHEMA_VERSION,
    music_asset_manifest_sha256: musicAssetManifestSha256(manifest),
    edit_policy_sha256: editPolicySha256(policy),
    output_timeline_sha256: manifest.output_timeline_sha256,
    output_duration_ms: manifest.output_duration_ms,
    policy: deriveMusicPolicyLimits(policy, manifest.output_duration_ms),
    mastering: deriveMusicMastering(policy),
    source_music_action: sourceMusicAction,
    regions: selected,
  };
}

function withSourceMusic(manifest, { authorized = false } = {}) {
  const clean = clone(manifest);
  const payload = {
    start_ms: 0,
    end_ms: 6_000,
    evidence_sha256: hash('source-music-region'),
  };
  clean.source_music = {
    status: 'present',
    evidence_sha256: hash('music-vector-source-analysis'),
    exclusion_authorization_sha256: authorized ? hash('source-exclusion') : null,
    regions: [{
      source_region_id: deriveSourceMusicRegionId(payload, 6_000),
      ...payload,
    }],
  };
  return clean;
}

function canonicalSchemaJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalSchemaJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => (
    `${JSON.stringify(key)}:${canonicalSchemaJson(value[key])}`
  )).join(',')}}`;
}

// Frozen from CPython 3 against the corrected autoeditor/music_plan.py v1.
// Hashes bind every byte; the base64 payloads additionally compare the two
// canonical JSON byte strings directly, including ensure_ascii surrogate text.
const PYTHON_VECTOR = Object.freeze({
  asset_id: 'musicasset-c8810df9744db19034a3cd3a97acf4274debcdae1b7a7cf3a88cd6f8c69631ea',
  beat_grid_id: 'beatgrid-555e507e16cfe9f83c02bc52ab208c6ad9b7417a5f3d88d76d5ae7957f3ffedb',
  region_id: 'musicregion-bc76976a8ce1152c42883f436e373cfd8d716bb50fc0fc946bb92e46907ca80c',
  manifest_sha256: '8772004ae79946649d089ef7aa3a49f6bd87c92f2d0fc07627d49f7883aa1324',
  policy_sha256: 'c9e1d6ba261647b4f0568b26e5993a1bae615403a0454b07de522b609123a1ae',
  plan_sha256: '5124e3c7883ec85ee4d5ceb56a2d7df22506a5c2448d9eb2d47eb0a7cb045ef5',
  compiled_regions_sha256: 'be5bfe2fe65668ffa8061bd65e89a71f29774ffa19fc43d75435592e2cfc117b',
  mix_primitives_sha256: '30835048bb24f36482feb5f692fe81d2f7c6d2959b13c4ef9ae2e08d3df09c4e',
  receipt_sha256: '44feefd18172c8d98f701b1554ec888ba97ddef90c27c9071ef1e5b282bee5fe',
  schema_sha256: '4957c4a037dc4a3407ca3cf7fc656a3343b5cce8e08e1ce83c7f523bcba42d6e',
  manifest_json_b64:
    'eyJhc3NldHMiOlt7ImFzc2V0X2lkIjoibXVzaWNhc3NldC1jODgxMGRmOTc0NGRiMTkwMzRhM2NkM2E5N2FjZjQyNzRkZWJjZGFlMWI3YTdjZjNhODhjZDZmOGM2OTYzMWVhIiwiYnl0ZV9sZW5ndGgiOjEyMzQ1NiwiY2hhbm5lbHMiOjEsImRlY29kZWRfZHVyYXRpb25fbXMiOjEyMDAwLCJsaWNlbnNlIjp7ImJhc2lzIjoibGljZW5zZWRfZXh0ZXJuYWwiLCJldmlkZW5jZV9zaGEyNTYiOiJlZGE2MTliZDRiZTE0ZDIzMjFmZjJkODg0NTZhYTliYmJmMjM4MzRmYWI5NjQxZmVmMmJmOTBlYjM3ZWY4YzM5IiwibGljZW5zZV9pZCI6ImxpY2Vuc2UtdmVjdG9yIiwibGljZW5zZV9uYW1lIjoiXHUwMGM5ZGl0aW9uIFx1ZDgzY1x1ZGYwZCIsImxpY2Vuc29yIjoiTVx1MDBmYXNpY2EgU29jaVx1MDBlOXRcdTAwZTkifSwicHJvdmVuYW5jZSI6ImxpY2Vuc2VkX2V4dGVybmFsIiwicmlnaHRzX3JlY2VpcHQiOnsicGVybWl0c19kZWxpdmVyeSI6dHJ1ZSwicGVybWl0c19lZGl0aW5nIjp0cnVlLCJwZXJtaXRzX2xvb3BpbmciOnRydWUsInBlcm1pdHNfc3luY2hyb25pemF0aW9uIjp0cnVlLCJyZWNlaXB0X2lkIjoicmlnaHRzLXZlY3RvciIsInJlY2VpcHRfc2hhMjU2IjoiMjAxN2QwZGIzZWE2NzE3MmExOGQzM2I2MDg3NmI4NjJmN2QxOThjMDFiYTEzNWFkYWI4OTA1MWQ2ZWE2ZWYzNCJ9LCJzYW1wbGVfcmF0ZV9oeiI6NDQxMDAsInNoYTI1NiI6IjFlN2NkOGEyNmFjNDFlZjQ4NWQ4ZjE5ODRmZDk4ODE5OTYyNjdmZTUzY2Q4NjhkMjAxMTk0MjAxYTljMDBjODciLCJzb3VyY2VfcmVmIjoibGljZW5zZWQtZXh0ZXJuYWw6Ly9tdXNpYy92ZWN0b3Iud2F2In1dLCJiZWF0X2dyaWRzIjpbeyJhbmFseXNpc19yZWNlaXB0X3NoYTI1NiI6IjNiY2FmYjZkMjRjOTUwNjliNDllNTRkNzYyOTRkYzg4NmI2N2FhY2IzOGFhMjgyNjJkMWE5ODM5YmNjMDAwZjYiLCJhc3NldF9pZCI6Im11c2ljYXNzZXQtYzg4MTBkZjk3NDRkYjE5MDM0YTNjZDNhOTdhY2Y0Mjc0ZGViY2RhZTFiN2E3Y2YzYTg4Y2Q2ZjhjNjk2MzFlYSIsImFzc2V0X3NoYTI1NiI6IjFlN2NkOGEyNmFjNDFlZjQ4NWQ4ZjE5ODRmZDk4ODE5OTYyNjdmZTUzY2Q4NjhkMjAxMTk0MjAxYTljMDBjODciLCJiZWF0X2dyaWRfaWQiOiJiZWF0Z3JpZC01NTVlNTA3ZTE2Y2ZlOWY4M2MwMmJjNTJhYjIwOGM2YWQ5Yjc0MTdhNWYzZDg4ZDc2ZDVhZTc5NTdmM2ZmZWRiIiwiYmVhdHNfbXMiOlswLDEwMDAsMjAwMCwzMDAwLDQwMDAsNTAwMCw2MDAwLDcwMDAsODAwMCw5MDAwLDEwMDAwLDExMDAwLDEyMDAwXSwiZG93bmJlYXRzX21zIjpbMCw0MDAwLDgwMDAsMTIwMDBdfV0sImRpYWxvZ3VlX3dpbmRvd3MiOltdLCJvdXRwdXRfY2hhbm5lbHMiOjIsIm91dHB1dF9kdXJhdGlvbl9tcyI6NjAwMCwib3V0cHV0X3NhbXBsZV9yYXRlX2h6Ijo0ODAwMCwib3V0cHV0X3RpbWVsaW5lX3NoYTI1NiI6IjJmNjY5NThhYTM1MTZmZDllYWRjYmM2M2YxNGFlNWMwYTJjYThlNTc5NDViNDcyYzE0NDhiMGFiZGQyNTk0MTEiLCJzY2hlbWFfdmVyc2lvbiI6ImF1dG9lZGl0b3ItbXVzaWMtYXNzZXQtbWFuaWZlc3QvdjEiLCJzb3VyY2VfbXVzaWMiOnsiZXZpZGVuY2Vfc2hhMjU2IjoiYmVmMzE4NzMxNDJhNWMwZTM2ZWExMDI4MGEzYTE3OTZhM2FlOTlhMmYzMTk3NzhhYzYwNjhlMTkwMjIzZTc0NSIsImV4Y2x1c2lvbl9hdXRob3JpemF0aW9uX3NoYTI1NiI6bnVsbCwicmVnaW9ucyI6W10sInN0YXR1cyI6ImFic2VudCJ9LCJ0cmFuc2NyaXB0X3NoYTI1NiI6bnVsbH0=',
  plan_json_b64:
    'eyJlZGl0X3BvbGljeV9zaGEyNTYiOiJjOWUxZDZiYTI2MTY0N2I0ZjA1NjhiMjZlNTk5M2ExYmFlNjE1NDAzYTA0NTRiMDdkZTUyMmI2MDkxMjNhMWFlIiwibWFzdGVyaW5nIjp7InRhcmdldF9sb3VkbmVzc19taWxsaWx1ZnMiOi0xNDAwMCwidHJ1ZV9wZWFrX2NlaWxpbmdfbWlsbGlkYnRwIjotMTAwMH0sIm11c2ljX2Fzc2V0X21hbmlmZXN0X3NoYTI1NiI6Ijg3NzIwMDRhZTc5OTQ2NjQ5ZDA4OWVmN2FhM2E0OWY2YmQ4N2M5MmYyZDBmYzA3NjI3ZDQ5Zjc4ODNhYTEzMjQiLCJvdXRwdXRfZHVyYXRpb25fbXMiOjYwMDAsIm91dHB1dF90aW1lbGluZV9zaGEyNTYiOiIyZjY2OTU4YWEzNTE2ZmQ5ZWFkY2JjNjNmMTRhZTVjMGEyY2E4ZTU3OTQ1YjQ3MmMxNDQ4YjBhYmRkMjU5NDExIiwicG9saWN5Ijp7ImR1Y2tfdW5kZXJfZGlhbG9ndWUiOnRydWUsIm1heF9hZGRlZF9jb3ZlcmFnZV9tcyI6NjAwMCwibWF4X2FkZGVkX3RyYWNrX2NvdW50IjozLCJtYXhfZ2Fpbl9taWxsaWRiIjowLCJtYXhfcG9seXBob255IjoyLCJtYXhfcmVnaW9uX2NvdW50IjoxLCJwcm9maWxlIjoibW9udGFnZV9tZW1lIiwic3BlZWNoX2VmZmVjdGl2ZV9nYWluX2NlaWxpbmdfbWlsbGlkYiI6LTE1MDAwLCJ1c2FnZSI6InByaW1hcnkifSwicmVnaW9ucyI6W3siYXNzZXRfaWQiOiJtdXNpY2Fzc2V0LWM4ODEwZGY5NzQ0ZGIxOTAzNGEzY2QzYTk3YWNmNDI3NGRlYmNkYWUxYjdhN2NmM2E4OGNkNmY4YzY5NjMxZWEiLCJhc3NldF9zaGEyNTYiOiIxZTdjZDhhMjZhYzQxZWY0ODVkOGYxOTg0ZmQ5ODgxOTk2MjY3ZmU1M2NkODY4ZDIwMTE5NDIwMWE5YzAwYzg3IiwiYmVhdF9zeW5jIjp7ImFuYWx5c2lzX3JlY2VpcHRfc2hhMjU2IjoiM2JjYWZiNmQyNGM5NTA2OWI0OWU1NGQ3NjI5NGRjODg2YjY3YWFjYjM4YWEyODI2MmQxYTk4MzliY2MwMDBmNiIsImFzc2V0X2JlYXRfbXMiOjAsImJlYXRfZ3JpZF9pZCI6ImJlYXRncmlkLTU1NWU1MDdlMTZjZmU5ZjgzYzAyYmM1MmFiMjA4YzZhZDliNzQxN2E1ZjNkODhkNzZkNWFlNzk1N2YzZmZlZGIiLCJvdXRwdXRfYmVhdF9tcyI6MH0sImNyb3NzZmFkZV9pbl9tcyI6MCwiY3Jvc3NmYWRlX291dF9tcyI6MCwiZGlhbG9ndWVfZHVja2luZyI6bnVsbCwiZHVyYXRpb25fbXMiOjYwMDAsImZhZGVfaW5fbXMiOjUwMCwiZmFkZV9vdXRfbXMiOjUwMCwiZ2Fpbl9taWxsaWRiIjotNjAwMCwibG9vcF9jcm9zc2ZhZGVfbXMiOjAsImxvb3BfbGVuZ3RoX21zIjowLCJwbGF5YmFja19tb2RlIjoib25jZSIsInJlZ2lvbl9pZCI6Im11c2ljcmVnaW9uLWJjNzY5NzZhOGNlMTE1MmM0Mjg4M2Y0MzZlMzczY2ZkOGQ3MTZiYjUwZmMwZmM5NDZiYjkyZTQ2OTA3Y2E4MGMiLCJzdGFydF9tcyI6MCwidHJhY2tfaW5kZXgiOjAsInRyaW1fc3RhcnRfbXMiOjB9XSwic2NoZW1hX3ZlcnNpb24iOiJhdXRvZWRpdG9yLW11c2ljLXBsYW4vdjEiLCJzb3VyY2VfbXVzaWNfYWN0aW9uIjoibm9uZSJ9',
});

test('frozen Python IDs, hashes, canonical bytes, compile hashes, and schema match', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const compiled = compileMusicPlan(plan, manifest, policy);

  assert.equal(manifest.assets[0].asset_id, PYTHON_VECTOR.asset_id);
  assert.equal(manifest.beat_grids[0].beat_grid_id, PYTHON_VECTOR.beat_grid_id);
  assert.equal(plan.regions[0].region_id, PYTHON_VECTOR.region_id);
  assert.equal(musicAssetManifestSha256(manifest), PYTHON_VECTOR.manifest_sha256);
  assert.equal(editPolicySha256(policy), PYTHON_VECTOR.policy_sha256);
  assert.equal(musicPlanSha256(plan), PYTHON_VECTOR.plan_sha256);
  assert.equal(
    compiled.receipt.compiled_regions_sha256,
    PYTHON_VECTOR.compiled_regions_sha256,
  );
  assert.equal(compiled.receipt.mix_primitives_sha256, PYTHON_VECTOR.mix_primitives_sha256);
  assert.equal(compiled.receipt_sha256, PYTHON_VECTOR.receipt_sha256);
  assert.equal(compiled.receipt_sha256, musicCompileReceiptSha256(compiled.receipt));
  assert.equal(
    canonicalMusicAssetManifestJson(manifest),
    Buffer.from(PYTHON_VECTOR.manifest_json_b64, 'base64').toString('utf8'),
  );
  assert.equal(
    canonicalMusicPlanJson(plan),
    Buffer.from(PYTHON_VECTOR.plan_json_b64, 'base64').toString('utf8'),
  );
  assert.equal(
    hashCanonicalSchema(MUSIC_PLAN_JSON_SCHEMA),
    PYTHON_VECTOR.schema_sha256,
  );
});

function hashCanonicalSchema(schema) {
  return crypto.createHash('sha256').update(canonicalSchemaJson(schema), 'utf8').digest('hex');
}

test('valid compile is deterministic, detached, normalized, padded, and inert', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const first = compileMusicPlan(plan, manifest, policy);
  const second = compileMusicPlan(clone(plan), clone(manifest), clone(policy));
  assert.deepEqual(first, second);
  assert.equal(first.schema_version, MUSIC_COMPILE_RECEIPT_SCHEMA_VERSION);
  assert.equal(first.receipt.region_count, 1);
  assert.equal(first.receipt.max_observed_polyphony, 1);
  assert.equal(first.receipt.added_coverage_ms, 6_000);
  assert.deepEqual(validateMusicCompileResult(first, plan, manifest, policy), first);
  assert.deepEqual(first.track_crossfade_ffmpeg_primitive_tokens, []);
  assert.deepEqual(first.compiled_regions[0].loop_ffmpeg_primitive_tokens, []);
  assert.deepEqual(
    first.compiled_regions[0].dialogue_sidechain_ffmpeg_primitive_tokens,
    [],
  );
  assert.deepEqual(first.compiled_regions[0].source_ffmpeg_primitive_tokens, [
    'atrim=start=0.000:duration=6.000',
    'asetpts=PTS-STARTPTS',
    'aresample=48000',
    'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
  ]);
  assert.deepEqual(first.music_bus_ffmpeg_primitive_tokens, [
    'amix=inputs=1:duration=longest:dropout_transition=0:normalize=0',
    'apad=whole_dur=6.000',
    'atrim=start=0.000:duration=6.000',
    'asetpts=PTS-STARTPTS',
  ]);
  assert.deepEqual(first.output_ffmpeg_argument_tokens, [
    '-map', 'AUTOEDITOR_PROGRAM_AUDIO', '-ar', '48000', '-ac', '2',
  ]);
  const forbidden = /[;&|$()<>\\\n\r]/;
  const lists = [
    first.track_crossfade_ffmpeg_primitive_tokens,
    first.music_bus_ffmpeg_primitive_tokens,
    first.program_mix_ffmpeg_primitive_tokens,
    first.output_ffmpeg_argument_tokens,
  ];
  for (const item of first.compiled_regions) {
    for (const [key, value] of Object.entries(item)) {
      if (key.endsWith('_tokens')) lists.push(value);
    }
  }
  for (const tokens of lists) {
    for (const token of tokens) {
      assert.doesNotMatch(token, forbidden);
      assert.doesNotMatch(token, /:\/\//);
    }
  }
  const detached = validateMusicAssetManifest(manifest);
  manifest.assets[0].license.license_name = 'changed';
  assert.notEqual(detached.assets[0].license.license_name, 'changed');
});

test('canonical JSON is insertion-order independent and Python ensure_ascii compatible', () => {
  const manifest = makeManifest();
  const plan = makePlan(manifest);
  const reversedManifest = Object.fromEntries(Object.entries(manifest).reverse());
  reversedManifest.assets = manifest.assets.map((item) =>
    Object.fromEntries(Object.entries(item).reverse()));
  const reversedPlan = Object.fromEntries(Object.entries(plan).reverse());
  reversedPlan.regions = plan.regions.map((item) =>
    Object.fromEntries(Object.entries(item).reverse()));
  assert.equal(
    canonicalMusicAssetManifestJson(reversedManifest),
    canonicalMusicAssetManifestJson(manifest),
  );
  assert.equal(canonicalMusicPlanJson(reversedPlan), canonicalMusicPlanJson(plan));
  assert.match(canonicalMusicAssetManifestJson(manifest), /\\u00c9dition \\ud83c\\udf0d/);
  assert.doesNotMatch(canonicalMusicPlanJson(plan), /\s/);
});

test('complete JSON Schema recursively advertises the narrow executable v1', () => {
  const schema = MUSIC_PLAN_JSON_SCHEMA;
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(new Set(schema.required), new Set(Object.keys(makePlan())));
  for (const name of ['policy', 'mastering']) {
    const nested = schema.properties[name];
    assert.equal(nested.additionalProperties, false);
    assert.deepEqual(new Set(nested.required), new Set(Object.keys(nested.properties)));
  }
  const region = schema.properties.regions.items;
  assert.equal(region.additionalProperties, false);
  assert.deepEqual(new Set(region.required), new Set(Object.keys(region.properties)));
  assert.deepEqual(region.properties.playback_mode, { const: 'once' });
  assert.deepEqual(region.properties.loop_length_ms, { const: 0 });
  assert.deepEqual(region.properties.loop_crossfade_ms, { const: 0 });
  assert.deepEqual(region.properties.crossfade_in_ms, { const: 0 });
  assert.deepEqual(region.properties.crossfade_out_ms, { const: 0 });
  assert.deepEqual(region.properties.dialogue_ducking, { const: null });
  assert.deepEqual(schema.properties.source_music_action.enum, ['none', 'preserve']);
});

test('closed objects, symbols, sparse arrays, booleans, floats, and non-NFC fail closed', () => {
  const manifest = makeManifest();
  manifest[Symbol('hidden')] = true;
  assert.throws(() => validateMusicAssetManifest(manifest), MusicPlanError);

  const sparse = makeManifest();
  sparse.assets = new Array(1);
  assert.throws(() => validateMusicAssetManifest(sparse), MusicPlanError);

  const plan = makePlan();
  plan.extra = true;
  assert.throws(() => validateMusicPlan(plan, makeManifest(), makePolicy()), MusicPlanError);

  const booleanPlan = makePlan();
  booleanPlan.regions[0].start_ms = true;
  assert.throws(() => canonicalMusicPlanJson(booleanPlan), MusicPlanError);

  const floatPlan = makePlan();
  floatPlan.regions[0].start_ms = 1.5;
  assert.throws(() => canonicalMusicPlanJson(floatPlan), MusicPlanError);

  const nonNfc = makeAssetPayload();
  nonNfc.license.license_name = 'Édition'.normalize('NFD');
  assert.throws(() => deriveMusicAssetId(nonNfc), MusicPlanError);
});

test('rights and licenses reject case, whitespace, placeholders, and false provenance', () => {
  for (const [licenseId, licenseName, licensor] of [
    ['PROJECT-GENERATED', 'External license', 'Vendor'],
    ['external-1', ' unknown ', 'Vendor'],
    ['external-1', 'External license', ' PROJECT '],
    ['external-1', 'External license', 'User'],
    ['external-1', 'External license', 'uſer'],
    ['external-1', 'unlicenſed', 'Vendor'],
  ]) {
    const payload = makeAssetPayload({ unicodeLicense: false });
    Object.assign(payload.license, {
      license_id: licenseId, license_name: licenseName, licensor,
    });
    assert.throws(() => deriveMusicAssetId(payload), MusicPlanError);
  }

  for (const licensor of ['User', 'user ', 'project']) {
    const payload = makeAssetPayload({ unicodeLicense: false });
    payload.provenance = 'user_supplied';
    payload.source_ref = 'user-supplied://music/user.wav';
    payload.license.basis = 'user_authorized';
    payload.license.licensor = licensor;
    assert.throws(() => deriveMusicAssetId(payload), MusicPlanError);
  }

  const receipt = makeAssetPayload();
  receipt.rights_receipt.receipt_id = 'TBD';
  assert.throws(() => deriveMusicAssetId(receipt), MusicPlanError);
});

test('delivery output is exactly 48000 Hz stereo while assets are normalized', () => {
  for (const [rate, channels] of [[8_000, 2], [48_000, 1], [44_100, 6]]) {
    const manifest = makeManifest();
    manifest.output_sample_rate_hz = rate;
    manifest.output_channels = channels;
    assert.throws(() => validateMusicAssetManifest(manifest), MusicPlanError);
  }
  assert.equal(validateMusicAssetManifest(makeManifest()).assets[0].sample_rate_hz, 44_100);
  assert.equal(validateMusicAssetManifest(makeManifest()).assets[0].channels, 1);
});

test('arbitrary paths, shell metacharacters, unsafe segments, and duplicate facts fail', () => {
  for (const sourceRef of [
    'licensed-external://music/ok.wav;calc.exe',
    'C:\\music\\song.wav',
    'licensed-external://music/../secret.wav',
  ]) {
    const payload = makeAssetPayload();
    payload.source_ref = sourceRef;
    assert.throws(() => deriveMusicAssetId(payload), MusicPlanError);
  }
  const manifest = makeManifest();
  manifest.assets.push(clone(manifest.assets[0]));
  assert.throws(() => validateMusicAssetManifest(manifest), MusicPlanError);
});

test('exact asset, manifest, timeline, and edit-policy bindings reject tampering', () => {
  const manifest = makeManifest();
  manifest.assets[0].rights_receipt.receipt_sha256 = hash('tampered-rights');
  assert.throws(() => validateMusicAssetManifest(manifest), MusicPlanError);

  const trusted = makeManifest();
  const policy = makePolicy();
  for (const key of [
    'music_asset_manifest_sha256', 'edit_policy_sha256', 'output_timeline_sha256',
  ]) {
    const plan = makePlan(trusted, policy);
    plan[key] = hash(`tampered-${key}`);
    assert.throws(() => validateMusicPlan(plan, trusted, policy), MusicPlanError);
  }
  const plan = makePlan(trusted, policy);
  plan.regions[0].asset_sha256 = hash('substituted-bytes');
  refreshRegion(plan.regions[0]);
  assert.throws(() => validateMusicPlan(plan, trusted, policy), MusicPlanError);
});

test('loop, crossfade, and sidechain requests are rejected until executable topology exists', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const cases = [
    { playback_mode: 'loop', loop_length_ms: 2_000, loop_crossfade_ms: 100 },
    { crossfade_in_ms: 100 },
    { crossfade_out_ms: 100 },
    {
      dialogue_ducking: {
        dialogue_window_ids: [`dialogue-${'0'.repeat(64)}`],
        threshold_millidbfs: -30_000,
        attenuation_millidb: 12_000,
        attack_ms: 40,
        release_ms: 300,
      },
    },
  ];
  for (const overrides of cases) {
    const region = makeRegion(manifest, overrides);
    const plan = makePlan(manifest, policy, [region]);
    assert.throws(() => validateMusicPlan(plan, manifest, policy), MusicPlanError);
  }
});

test('trusted beats compile while fabricated beat evidence and mapping fail', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const valid = makePlan(manifest, policy);
  assert.equal(compileMusicPlan(valid, manifest, policy).receipt.beat_synced_region_count, 1);

  for (const mutation of [
    (beat) => { beat.asset_beat_ms = 1_234; },
    (beat) => { beat.analysis_receipt_sha256 = hash('fabricated-analysis'); },
    (beat) => { beat.output_beat_ms = 1_000; },
  ]) {
    const plan = makePlan(manifest, policy);
    mutation(plan.regions[0].beat_sync);
    refreshRegion(plan.regions[0]);
    assert.throws(() => validateMusicPlan(plan, manifest, policy), MusicPlanError);
  }
});

test('dialogue overlap rejects both missing and claimed unimplemented duck topology', () => {
  const manifest = makeManifest({ includeDialogue: true });
  const policy = makePolicy();
  const overlap = makeRegion(manifest, { beat_sync: null });
  assert.throws(
    () => validateMusicPlan(makePlan(manifest, policy, [overlap]), manifest, policy),
    MusicPlanError,
  );
  const claimed = makeRegion(manifest, {
    beat_sync: null,
    dialogue_ducking: {
      dialogue_window_ids: [manifest.dialogue_windows[0].dialogue_window_id],
      threshold_millidbfs: -30_000,
      attenuation_millidb: 12_000,
      attack_ms: 40,
      release_ms: 300,
    },
  });
  assert.throws(
    () => validateMusicPlan(makePlan(manifest, policy, [claimed]), manifest, policy),
    MusicPlanError,
  );
});

test('source music must be preserved; exclusion claims and added overlap fail', () => {
  for (const authorized of [false, true]) {
    const manifest = withSourceMusic(makeManifest(), { authorized });
    const policy = makePolicy();
    const excluded = makePlan(manifest, policy, [], {
      sourceMusicAction: 'exclude_authorized',
    });
    assert.throws(() => validateMusicPlan(excluded, manifest, policy), MusicPlanError);
    const overlap = makePlan(manifest, policy, [makeRegion(manifest)], {
      sourceMusicAction: 'preserve',
    });
    assert.throws(() => validateMusicPlan(overlap, manifest, policy), MusicPlanError);
  }
  const manifest = withSourceMusic(makeManifest());
  const policy = makePolicy({ profile: 'music_performance' });
  const preserved = makePlan(manifest, policy, [], { sourceMusicAction: 'preserve' });
  assert.deepEqual(validateMusicPlan(preserved, manifest, policy), preserved);
});

test('receipt omission, tamper, and replay against a changed plan fail', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const compiled = compileMusicPlan(plan, manifest, policy);

  const omitted = clone(compiled);
  delete omitted.program_mix_ffmpeg_primitive_tokens;
  assert.throws(
    () => validateMusicCompileResult(omitted, plan, manifest, policy),
    MusicPlanError,
  );

  const tampered = clone(compiled);
  tampered.receipt.compiled_regions_sha256 = hash('tampered-regions');
  tampered.receipt_sha256 = musicCompileReceiptSha256(tampered.receipt);
  assert.throws(
    () => validateMusicCompileResult(tampered, plan, manifest, policy),
    MusicPlanError,
  );

  const changed = clone(plan);
  changed.regions[0].gain_millidb = -9_000;
  refreshRegion(changed.regions[0]);
  assert.throws(
    () => validateMusicCompileResult(compiled, changed, manifest, policy),
    MusicPlanError,
  );
});

test('policy density, coverage, track, gain, and mastering snapshots are authoritative', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  for (const mutate of [
    (plan) => { plan.policy.max_region_count = 0; },
    (plan) => { plan.policy.max_added_coverage_ms = 1; },
    (plan) => { plan.policy.max_added_track_count = 0; },
    (plan) => { plan.policy.max_gain_millidb = -60_000; },
    (plan) => { plan.mastering.target_loudness_millilufs = -23_000; },
  ]) {
    const plan = makePlan(manifest, policy);
    mutate(plan);
    assert.throws(() => validateMusicPlan(plan, manifest, policy), MusicPlanError);
  }
  const broadcast = makePolicy({ platform: 'broadcast' });
  assert.deepEqual(deriveMusicMastering(broadcast), {
    target_loudness_millilufs: -23_000,
    true_peak_ceiling_millidbtp: -2_000,
  });
});
