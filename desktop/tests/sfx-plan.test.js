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
  ANCHOR_CATEGORIES,
  CUE_KINDS,
  DELIVERY_CHANNELS,
  DELIVERY_SAMPLE_RATE_HZ,
  DUCK_ATTENUATIONS_MILLIDB,
  DUCK_SIDECHAIN_THRESHOLD_TEXT,
  LICENSE_BASES,
  MAX_CUES,
  POLICY_DENSITIES,
  POLICY_USAGES,
  PROVENANCE_KINDS,
  SAMPLE_RATES_HZ,
  SFX_COMPILE_RECEIPT_JSON_SCHEMA,
  SFX_COMPILE_RECEIPT_SCHEMA_VERSION,
  SFX_CUE_MANIFEST_JSON_SCHEMA,
  SFX_CUE_MANIFEST_SCHEMA_VERSION,
  SFX_PLAN_JSON_SCHEMA,
  SFX_PLAN_SCHEMA_VERSION,
  SfxPlanError,
  canonicalSfxCompileReceiptJson,
  canonicalSfxCueManifestJson,
  canonicalSfxPlanJson,
  compileSfxPlan,
  densityCueLimit,
  deriveSfxAnchorId,
  deriveSfxAssetId,
  deriveSfxCueId,
  deriveSfxPolicyLimits,
  deriveSpeechWindowId,
  sfxCompileReceiptSha256,
  sfxCueManifestSha256,
  sfxPlanSha256,
  validateSfxCueManifest,
  validateSfxPlan,
} = require('../helper/lib/sfx-plan');

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

function makePolicy(profile = 'dialogue_talking_head', durationMs = 60_000) {
  return resolveEditPolicy({
    schema_version: EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    profile,
    duration_ms: durationMs,
    delivery: { platform: 'web', aspect: 'auto' },
    explicit_intent: autoValues(),
    consented_preferences: { consented: false, values: autoValues() },
    available_capabilities: [...CAPABILITIES].sort(),
  });
}

function makeAsset(
  name,
  provenance,
  { durationMs = 3_000, sampleRateHz = 48_000, channels = 2 } = {},
) {
  let scheme;
  let license;
  if (provenance === 'project_generated') {
    scheme = 'project-generated';
    license = {
      basis: 'project_owned',
      license_id: 'project-generated',
      licensor: 'project',
      evidence_sha256: hash(`${name}-generation-receipt`),
    };
  } else if (provenance === 'user_supplied') {
    scheme = 'user-supplied';
    license = {
      basis: 'user_authorized',
      license_id: `user-consent-${name}`,
      licensor: 'user',
      evidence_sha256: hash(`${name}-user-consent`),
    };
  } else {
    scheme = 'licensed-external';
    license = {
      basis: 'licensed_external',
      license_id: `stock-license-${name}`,
      licensor: 'Sound Vendor',
      evidence_sha256: hash(`${name}-license-document`),
    };
  }
  const payload = {
    sha256: hash(`${name}-audio-bytes`),
    byte_length: 10_000 + name.length,
    duration_ms: durationMs,
    sample_rate_hz: sampleRateHz,
    channels,
    source_ref: `${scheme}://cues/${name}.wav`,
    provenance,
    license,
  };
  return { asset_id: deriveSfxAssetId(payload), ...payload };
}

function makeAnchor(category, referenceId, timeMs) {
  const payload = {
    category,
    reference_id: referenceId,
    time_ms: timeMs,
    evidence_start_ms: timeMs - 100,
    evidence_end_ms: timeMs + 100,
    evidence_sha256: hash(`${referenceId}-evidence`),
  };
  return { anchor_id: deriveSfxAnchorId(payload, 60_000), ...payload };
}

function makeSpeech(startMs, endMs) {
  const payload = {
    start_ms: startMs,
    end_ms: endMs,
    evidence_sha256: hash(`speech-${startMs}-${endMs}`),
  };
  return { speech_id: deriveSpeechWindowId(payload, 60_000), ...payload };
}

function makeManifest() {
  const assets = [
    makeAsset('generated-whoosh', 'project_generated'),
    makeAsset('user-click', 'user_supplied'),
    makeAsset('licensed-impact', 'licensed_external'),
    makeAsset('licensed-whoosh', 'licensed_external'),
  ].sort((left, right) => left.asset_id.localeCompare(right.asset_id));
  const anchors = [
    makeAnchor('event', 'event-product-drop', 5_000),
    makeAnchor('boundary', `boundary-${hash('cut-a')}`, 25_000),
    makeAnchor('interface_feedback', 'interface-submit-button', 45_000),
  ].sort((left, right) => left.time_ms - right.time_ms ||
    left.anchor_id.localeCompare(right.anchor_id));
  return {
    schema_version: SFX_CUE_MANIFEST_SCHEMA_VERSION,
    output_timeline_sha256: hash('compiled-output-timeline'),
    output_duration_ms: 60_000,
    output_sample_rate_hz: 48_000,
    output_channels: 2,
    assets,
    anchors,
    speech_windows: [makeSpeech(5_000, 5_500)],
  };
}

function assetByName(manifest, fragment) {
  return manifest.assets.find((asset) => asset.source_ref.includes(fragment));
}

function anchorByCategory(manifest, category) {
  return manifest.anchors.find((anchor) => anchor.category === category);
}

function makeCue(asset, anchor, {
  kind,
  startMs,
  trimDurationMs = 1_000,
  gainMillidb = -6_000,
  attackFadeMs = 50,
  releaseFadeMs = 100,
  ducking = null,
}) {
  const payload = {
    asset_id: asset.asset_id,
    asset_sha256: asset.sha256,
    kind,
    motivation: {
      category: anchor.category,
      anchor_id: anchor.anchor_id,
      reference_id: anchor.reference_id,
      anchor_ms: anchor.time_ms,
      evidence_start_ms: anchor.evidence_start_ms,
      evidence_end_ms: anchor.evidence_end_ms,
      evidence_sha256: anchor.evidence_sha256,
    },
    placement: {
      start_ms: startMs,
      trim_start_ms: 0,
      trim_duration_ms: trimDurationMs,
      gain_millidb: gainMillidb,
      attack_fade_ms: attackFadeMs,
      release_fade_ms: releaseFadeMs,
    },
    ducking: clone(ducking),
  };
  return { cue_id: deriveSfxCueId(payload), ...payload };
}

function refreshCueId(cue) {
  const payload = Object.fromEntries(
    Object.entries(clone(cue)).filter(([key]) => key !== 'cue_id'),
  );
  cue.cue_id = deriveSfxCueId(payload);
}

function defaultCues(manifest) {
  return [
    makeCue(assetByName(manifest, 'licensed-impact'), anchorByCategory(manifest, 'event'), {
      kind: 'impact',
      startMs: 5_000,
      ducking: {
        start_ms: 5_000,
        end_ms: 5_500,
        attenuation_millidb: 12_000,
        attack_ms: 20,
        release_ms: 200,
      },
    }),
    makeCue(
      assetByName(manifest, 'generated-whoosh'),
      anchorByCategory(manifest, 'boundary'),
      { kind: 'whoosh', startMs: 24_500, trimDurationMs: 1_500, gainMillidb: -9_000 },
    ),
  ];
}

function makePlan(
  manifest = makeManifest(),
  policy = makePolicy(),
  cues = defaultCues(manifest),
) {
  const ordered = clone(cues).sort((left, right) =>
    left.placement.start_ms - right.placement.start_ms || left.cue_id.localeCompare(right.cue_id));
  return {
    schema_version: SFX_PLAN_SCHEMA_VERSION,
    cue_manifest_sha256: sfxCueManifestSha256(manifest),
    edit_policy_sha256: editPolicySha256(policy),
    output_timeline_sha256: manifest.output_timeline_sha256,
    output_duration_ms: manifest.output_duration_ms,
    policy: deriveSfxPolicyLimits(policy, manifest.output_duration_ms),
    cues: ordered,
  };
}

function reversedObject(value) {
  return Object.fromEntries(Object.entries(value).reverse());
}

function canonicalAscii(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalAscii).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${canonicalAscii(value[key])}`).join(',')}}`;
}

// Frozen from CPython 3 against the settled autoeditor/sfx_plan.py contract.
const PYTHON_VECTOR = Object.freeze({
  manifest_schema_sha256: '9763086fd91953ed89224f68571ff435e7430320356fc4607482810180ecacb0',
  plan_schema_sha256: 'cca3fa113730b164ddc91c76b22e1fc2e800cb2e6a73a0c41013ec6af91aa651',
  receipt_schema_sha256: '254f49de61723c49829cb7371cd6117811abbe15615cd0b3bb23f086785609ff',
  manifest_sha256: 'cea60c0d69f04a8399fc6fbf323554bca2da9f1628ab011181f5d45e509cb65f',
  edit_policy_sha256: '3c3272a15a185d79245eddc9d1ca1559b55c7fb20aae8ba67347299820ecfa4c',
  asset_ids: Object.freeze([
    'sfxasset-140d25073d3dc4a56d72c169e38c822944b373245aa689a207a1dc55263746c5',
    'sfxasset-6e005cbb05a0ea9a75f7af18fcd01da573a718ada2d3695ffb53f60ec4b7b009',
    'sfxasset-9fee761876bddc94e762d2b25bacd4022e84fd1102cadcdac6ab29c6301e9978',
    'sfxasset-d8cc4ed5fd26b3fd18894aedc8bb49dbbebbe1c9bc8ba0993fb29bc8138ba68f',
  ]),
  anchor_ids: Object.freeze([
    'sfxanchor-953a7712859049096e953aca01b4b99f2a76b6b530bccc24c61054d51097a76c',
    'sfxanchor-d5605f7d6dbc45cb6e37f44c930c66dbd1d1c7cbd0d67c4a5f461a8cbe43ed16',
    'sfxanchor-1ee70d1cd502f975e479508164d6b70c1ef7b73b64a6da8c981015c6629013c8',
  ]),
  speech_ids: Object.freeze([
    'speech-c59019ff21879424c033a9c4121bf485850fcbd228d722a23a02e38c7d80b149',
  ]),
  cue_ids: Object.freeze([
    'sfxcue-1dd84a7d98076c62714adaf93de37a4564044f54ad0521d8fdde310c5dbea641',
    'sfxcue-b0f566e1f4afca12aa0e8f8240d5e98bdc3dbdd2fb6b9e09d8f1e4e3c721bc26',
  ]),
  plan_sha256: '0248b68e88f78eabd147fd101819f9ffc7b701612995fff8355ac7a3f61a1b2e',
  compiled_cues_sha256: 'a8c67b450ef0785653c086b3a52d0c4d5315f9ed77fea01aa8053a92669afe35',
  mix_primitives_sha256: 'e84479bf594d6fe5666814de1ee72e1b3d3359a88b83217bb965ee6349dd4b86',
  receipt_sha256: '690d89dba9919cab79a9d36dfc6d6ad6c1dcb3f7645a7b1539e732c63f33a196',
  result_canonical_sha256: '32e1fb75a33f9e790c0d4c53e8b3f47cefcc3477454010ffd849e793da2c3fd6',
});
test('frozen Python asset, anchor, speech, cue, plan, compile, mix, and receipt vectors match', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const result = compileSfxPlan(plan, manifest, policy);

  assert.equal(hash(canonicalAscii(SFX_CUE_MANIFEST_JSON_SCHEMA)),
    PYTHON_VECTOR.manifest_schema_sha256);
  assert.equal(hash(canonicalAscii(SFX_PLAN_JSON_SCHEMA)), PYTHON_VECTOR.plan_schema_sha256);
  assert.equal(hash(canonicalAscii(SFX_COMPILE_RECEIPT_JSON_SCHEMA)),
    PYTHON_VECTOR.receipt_schema_sha256);
  assert.equal(sfxCueManifestSha256(manifest), PYTHON_VECTOR.manifest_sha256);
  assert.equal(editPolicySha256(policy), PYTHON_VECTOR.edit_policy_sha256);
  assert.deepEqual(manifest.assets.map((asset) => asset.asset_id), PYTHON_VECTOR.asset_ids);
  assert.deepEqual(manifest.anchors.map((anchor) => anchor.anchor_id), PYTHON_VECTOR.anchor_ids);
  assert.deepEqual(
    manifest.speech_windows.map((speech) => speech.speech_id),
    PYTHON_VECTOR.speech_ids,
  );
  assert.deepEqual(plan.cues.map((cue) => cue.cue_id), PYTHON_VECTOR.cue_ids);
  assert.equal(sfxPlanSha256(plan), PYTHON_VECTOR.plan_sha256);
  assert.equal(result.receipt.compiled_cues_sha256, PYTHON_VECTOR.compiled_cues_sha256);
  assert.equal(result.receipt.mix_primitives_sha256, PYTHON_VECTOR.mix_primitives_sha256);
  assert.equal(result.receipt_sha256, PYTHON_VECTOR.receipt_sha256);
  assert.equal(result.receipt_sha256, sfxCompileReceiptSha256(result.receipt));

  // This canonical byte stream covers every compiled metadata field and every
  // inert FFmpeg token. Its digest and byte count were frozen from Python.
  const compiledBytes = Buffer.from(canonicalAscii(result), 'utf8');
  assert.equal(compiledBytes.length, 5_886);
  assert.equal(
    crypto.createHash('sha256').update(compiledBytes).digest('hex'),
    PYTHON_VECTOR.result_canonical_sha256,
  );
});

test('canonical JSON is Python-compatible, ASCII-only, detached, and key-order independent', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const reversedManifest = reversedObject(manifest);
  reversedManifest.assets = manifest.assets.map(reversedObject);
  reversedManifest.anchors = manifest.anchors.map(reversedObject);
  reversedManifest.speech_windows = manifest.speech_windows.map(reversedObject);
  const reversedPlan = reversedObject(plan);
  reversedPlan.cues = plan.cues.map((cue) => {
    const changed = reversedObject(cue);
    changed.motivation = reversedObject(cue.motivation);
    changed.placement = reversedObject(cue.placement);
    if (cue.ducking) changed.ducking = reversedObject(cue.ducking);
    return changed;
  });

  assert.equal(
    canonicalSfxCueManifestJson(manifest),
    canonicalSfxCueManifestJson(reversedManifest),
  );
  assert.equal(canonicalSfxPlanJson(plan), canonicalSfxPlanJson(reversedPlan));
  assert.equal(sfxPlanSha256(plan), sfxPlanSha256(reversedPlan));
  assert.match(canonicalSfxCueManifestJson(manifest), /^[\x00-\x7f]+$/);
  assert.match(canonicalSfxPlanJson(plan), /^[\x00-\x7f]+$/);

  const clean = validateSfxCueManifest(manifest);
  clean.assets[0].license.license_id = 'mutated';
  assert.notEqual(clean.assets[0].license.license_id, manifest.assets[0].license.license_id);
});

test('manifest binds exact byte, media, source, provenance, and rights facts', () => {
  const manifest = makeManifest();
  const clean = validateSfxCueManifest(manifest);
  assert.deepEqual(clean, manifest);
  assert.deepEqual(
    Object.fromEntries(clean.assets.map((asset) => [asset.provenance, asset.license.basis])),
    {
      licensed_external: 'licensed_external',
      project_generated: 'project_owned',
      user_supplied: 'user_authorized',
    },
  );
  clean.assets.forEach((asset) => {
    const payload = Object.fromEntries(
      Object.entries(asset).filter(([key]) => key !== 'asset_id'),
    );
    assert.equal(asset.asset_id, deriveSfxAssetId(payload));
  });
});

test('rights checks reject forged classes, placeholders, case variants, and whitespace bypasses', () => {
  for (const provenance of ['user_supplied', 'licensed_external']) {
    for (const [field, invalid] of [
      ['license_id', 'PROJECT-GENERATED'],
      ['licensor', 'Project'],
      ['licensor', 'User'],
      ['licensor', 'unknown '],
      ['licensor', 'project '],
    ]) {
      const asset = makeAsset('rights-bypass', provenance);
      asset.license[field] = invalid;
      const payload = Object.fromEntries(
        Object.entries(asset).filter(([key]) => key !== 'asset_id'),
      );
      assert.throws(() => deriveSfxAssetId(payload), SfxPlanError);
    }
  }

  const manifest = makeManifest();
  const external = manifest.assets.find((asset) => asset.provenance === 'licensed_external');
  external.license.basis = 'project_owned';
  assert.throws(() => validateSfxCueManifest(manifest), SfxPlanError);
});

test('closed manifest rejects loose numbers, unknown or symbol keys, sparse arrays, Unicode, and injection', () => {
  const invalid = [];
  let changed = makeManifest();
  changed.output_duration_ms = 60_000.5;
  invalid.push(changed);
  changed = makeManifest();
  changed.assets[0].channels = true;
  invalid.push(changed);
  changed = makeManifest();
  changed.assets[0].extra = 'x';
  invalid.push(changed);
  changed = makeManifest();
  Object.defineProperty(changed.assets[0], Symbol('hidden'), { value: true, enumerable: true });
  invalid.push(changed);
  changed = makeManifest();
  delete changed.assets[1];
  invalid.push(changed);
  changed = makeManifest();
  changed.anchors.reverse();
  invalid.push(changed);
  changed = makeManifest();
  changed.assets[0].source_ref = 'project-generated://cues/../escape.wav';
  invalid.push(changed);
  changed = makeManifest();
  changed.assets[0].source_ref = 'project-generated://cues/x.wav;anull';
  invalid.push(changed);
  changed = makeManifest();
  changed.assets[0].license.licensor = 'Véndor';
  invalid.push(changed);
  changed = makeManifest();
  changed.output_sample_rate_hz = 44_100;
  invalid.push(changed);
  changed = makeManifest();
  changed.output_channels = 1;
  invalid.push(changed);
  changed = makeManifest();
  changed.schema_version = 'autoeditor-sfx-cue-manifest/v2';
  invalid.push(changed);

  invalid.forEach((value) => {
    assert.throws(() => validateSfxCueManifest(value), SfxPlanError);
  });
});

test('valid sparse plan binds policy, manifest, exact output, and conservative ceilings', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const clean = validateSfxPlan(makePlan(manifest, policy), manifest, policy);
  assert.deepEqual(clean.policy, {
    profile: 'dialogue_talking_head',
    density: 'sparse',
    usage: 'motivated_only',
    max_cue_count: 4,
    max_polyphony: 1,
    max_gain_millidb: 0,
    speech_effective_gain_ceiling_millidb: -15_000,
  });
  assert.deepEqual(
    ['none', 'sparse', 'medium', 'dense'].map((density) => densityCueLimit(density, 60_000)),
    [0, 4, 10, 20],
  );
  assert.equal(densityCueLimit('sparse', 1), 1);
  assert.equal(densityCueLimit('dense', Number.MAX_SAFE_INTEGER), MAX_CUES);
  assert.throws(() => densityCueLimit('high', 60_000), SfxPlanError);
});

test('forbidden, source-only, interface-only, and event-only policies enforce semantics', () => {
  const manifest = makeManifest();
  for (const [profile, usage] of [
    ['podcast_interview', 'forbidden'],
    ['music_performance', 'source_only'],
  ]) {
    const policy = makePolicy(profile);
    const empty = validateSfxPlan(makePlan(manifest, policy, []), manifest, policy);
    assert.equal(empty.policy.usage, usage);
    assert.equal(empty.policy.max_cue_count, 0);
    assert.throws(
      () => validateSfxPlan(makePlan(manifest, policy, defaultCues(manifest).slice(0, 1)),
        manifest, policy),
      SfxPlanError,
    );
  }

  const interfaceAnchor = anchorByCategory(manifest, 'interface_feedback');
  const interfaceCue = makeCue(assetByName(manifest, 'user-click'), interfaceAnchor, {
    kind: 'interface_feedback', startMs: 45_000,
  });
  const course = makePolicy('course_tutorial_screencast');
  assert.doesNotThrow(() => validateSfxPlan(
    makePlan(manifest, course, [interfaceCue]), manifest, course,
  ));
  assert.throws(() => validateSfxPlan(
    makePlan(manifest, course, defaultCues(manifest).slice(0, 1)), manifest, course,
  ), SfxPlanError);

  const gaming = makePolicy('gaming');
  assert.throws(() => validateSfxPlan(
    makePlan(manifest, gaming, defaultCues(manifest).slice(1)), manifest, gaming,
  ), SfxPlanError);
});

test('motivation, timeline, manifest, policy, asset, and cue-id tampering fails closed', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const invalid = [];
  for (const key of [
    'cue_manifest_sha256', 'edit_policy_sha256', 'output_timeline_sha256',
  ]) {
    const changed = makePlan(manifest, policy);
    changed[key] = '0'.repeat(64);
    invalid.push(changed);
  }
  let changed = makePlan(manifest, policy);
  changed.output_duration_ms -= 1;
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.policy.density = 'medium';
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[0].asset_sha256 = '0'.repeat(64);
  refreshCueId(changed.cues[0]);
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[0].motivation.evidence_sha256 = hash('forged');
  refreshCueId(changed.cues[0]);
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[1].motivation.reference_id = `boundary-${hash('other')}`;
  refreshCueId(changed.cues[1]);
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[0].cue_id = `sfxcue-${'0'.repeat(64)}`;
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues.reverse();
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues.push(clone(changed.cues[1]));
  invalid.push(changed);

  invalid.forEach((value) => {
    assert.throws(() => validateSfxPlan(value, manifest, policy), SfxPlanError);
  });
  const wrongDuration = makePolicy('dialogue_talking_head', 30_000);
  changed = makePlan(manifest, policy);
  changed.edit_policy_sha256 = editPolicySha256(wrongDuration);
  assert.throws(() => validateSfxPlan(changed, manifest, wrongDuration), SfxPlanError);
  assert.throws(() => deriveSfxPolicyLimits(wrongDuration, 60_000), SfxPlanError);
});

test('density rejects local clustering, per-anchor stacking, and global overuse', () => {
  let manifest = makeManifest();
  const policy = makePolicy('commercial_product');
  const asset = assetByName(manifest, 'licensed-impact');
  const clustered = Array.from({ length: 6 }, (_, index) =>
    makeAnchor('event', `event-cluster-${index}`, 10_000 + index * 1_000));
  manifest.anchors = [...manifest.anchors, ...clustered].sort((left, right) =>
    left.time_ms - right.time_ms || left.anchor_id.localeCompare(right.anchor_id));
  const clusteredCues = clustered.map((anchor) => makeCue(asset, anchor, {
    kind: 'impact', startMs: anchor.time_ms, trimDurationMs: 500,
  }));
  assert.throws(() => validateSfxPlan(
    makePlan(manifest, policy, clusteredCues), manifest, policy,
  ), SfxPlanError);

  manifest = makeManifest();
  const event = anchorByCategory(manifest, 'event');
  const stacked = [
    makeCue(assetByName(manifest, 'licensed-impact'), event, {
      kind: 'impact', startMs: 5_000,
      ducking: {
        start_ms: 5_000, end_ms: 5_500, attenuation_millidb: 12_000,
        attack_ms: 20, release_ms: 200,
      },
    }),
    makeCue(assetByName(manifest, 'licensed-whoosh'), event, {
      kind: 'whoosh', startMs: 5_000,
      ducking: {
        start_ms: 5_000, end_ms: 5_500, attenuation_millidb: 12_000,
        attack_ms: 20, release_ms: 200,
      },
    }),
    makeCue(assetByName(manifest, 'generated-whoosh'), event, {
      kind: 'whoosh', startMs: 5_000,
      ducking: {
        start_ms: 5_000, end_ms: 5_500, attenuation_millidb: 12_000,
        attack_ms: 20, release_ms: 200,
      },
    }),
  ];
  assert.throws(() => validateSfxPlan(
    makePlan(manifest, policy, stacked), manifest, policy,
  ), SfxPlanError);

  manifest = makeManifest();
  const spaced = Array.from({ length: 11 }, (_, index) =>
    makeAnchor('event', `event-many-${index}`, 2_000 + index * 5_000));
  manifest.anchors = [...manifest.anchors, ...spaced].sort((left, right) =>
    left.time_ms - right.time_ms || left.anchor_id.localeCompare(right.anchor_id));
  const cues = spaced.map((anchor) => makeCue(assetByName(manifest, 'licensed-impact'), anchor, {
    kind: 'impact', startMs: anchor.time_ms, trimDurationMs: 250,
  }));
  assert.throws(() => validateSfxPlan(makePlan(manifest, policy, cues), manifest, policy),
    SfxPlanError);
});

test('profile and density polyphony ceilings reject overlapping cue stacks', () => {
  const manifest = makeManifest();
  const policy = makePolicy('commercial_product');
  const anchors = Array.from({ length: 3 }, (_, index) =>
    makeAnchor('event', `event-overlap-${index}`, 10_000 + index * 100));
  manifest.anchors = [...manifest.anchors, ...anchors].sort((left, right) =>
    left.time_ms - right.time_ms || left.anchor_id.localeCompare(right.anchor_id));
  const assets = [
    assetByName(manifest, 'licensed-impact'),
    assetByName(manifest, 'generated-whoosh'),
    assetByName(manifest, 'licensed-whoosh'),
  ];
  const cues = anchors.map((anchor, index) => makeCue(assets[index], anchor, {
    kind: index === 0 ? 'impact' : 'whoosh',
    startMs: anchor.time_ms,
    trimDurationMs: 2_000,
  }));
  assert.throws(() => validateSfxPlan(makePlan(manifest, policy, cues), manifest, policy),
    SfxPlanError);
});

test('trim, fade, gain, duration, output extent, and safe-integer ranges fail closed', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const invalid = [];
  for (const [key, value] of [
    ['trim_start_ms', 3_001],
    ['trim_duration_ms', 19],
    ['gain_millidb', 1],
    ['attack_fade_ms', 901],
    ['gain_millidb', true],
    ['start_ms', Number.MAX_SAFE_INTEGER + 1],
  ]) {
    const changed = makePlan(manifest, policy);
    changed.cues[0].placement[key] = value;
    if (key !== 'trim_duration_ms' && typeof value === 'number' && Number.isSafeInteger(value)) {
      refreshCueId(changed.cues[0]);
    }
    invalid.push(changed);
  }
  const changed = makePlan(manifest, policy);
  changed.cues[0].placement.start_ms = 59_500;
  refreshCueId(changed.cues[0]);
  changed.cues.sort((left, right) => left.placement.start_ms - right.placement.start_ms ||
    left.cue_id.localeCompare(right.cue_id));
  invalid.push(changed);
  invalid.forEach((value) => {
    assert.throws(() => validateSfxPlan(value, manifest, policy), SfxPlanError);
  });
});

test('speech masking requires full coverage, preset reduction, fast attack, and motivated ducking', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const invalid = [];
  let changed = makePlan(manifest, policy);
  changed.cues[0].ducking = null;
  refreshCueId(changed.cues[0]);
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[0].ducking.end_ms = 5_400;
  refreshCueId(changed.cues[0]);
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[0].ducking.attenuation_millidb = 6_000;
  changed.cues[0].placement.gain_millidb = -6_000;
  refreshCueId(changed.cues[0]);
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[0].ducking.attack_ms = 21;
  refreshCueId(changed.cues[0]);
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[0].ducking.attenuation_millidb = 7_000;
  invalid.push(changed);
  changed = makePlan(manifest, policy);
  changed.cues[1].ducking = {
    start_ms: 24_500,
    end_ms: 25_000,
    attenuation_millidb: 12_000,
    attack_ms: 20,
    release_ms: 200,
  };
  refreshCueId(changed.cues[1]);
  invalid.push(changed);
  invalid.forEach((value) => {
    assert.throws(() => validateSfxPlan(value, manifest, policy), SfxPlanError);
  });
});

test('every deterministic sidechain threshold independently yields its requested reduction', () => {
  for (const attenuation of DUCK_ATTENUATIONS_MILLIDB) {
    const threshold = Number(DUCK_SIDECHAIN_THRESHOLD_TEXT[attenuation]);
    const observed = Math.round((-20 * Math.log10(threshold)) * (1 - 1 / 2) * 1_000);
    assert.equal(observed, attenuation);
  }
});

test('compile emits exact inert shell-free FFmpeg primitives and 48000 Hz stereo receipt', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const result = compileSfxPlan(makePlan(manifest, policy), manifest, policy);
  const first = result.compiled_cues[0];
  assert.deepEqual(first.cue_ffmpeg_primitive_tokens, [
    'atrim=start=0.000:duration=1.000',
    'asetpts=PTS-STARTPTS',
    'aresample=48000:async=0:first_pts=0',
    'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
    'afade=t=in:st=0.000:d=0.050:curve=qsin',
    'afade=t=out:st=0.900:d=0.100:curve=qsin',
    'volume=-6.000dB:precision=double',
  ]);
  assert.deepEqual(first.duck_sidechain_gate_ffmpeg_primitive_tokens, [
    'aevalsrc=if(between(t\\,0.000\\,0.500)\\,1\\,0):d=1.000:s=48000:c=mono',
  ]);
  assert.deepEqual(first.sidechaincompress_ffmpeg_primitive_tokens, [
    'sidechaincompress=threshold=0.06309573445:ratio=2:attack=20:release=200:' +
      'makeup=1:knee=1:link=maximum:detection=peak:mix=1',
  ]);
  assert.deepEqual(first.timeline_ffmpeg_primitive_tokens, ['adelay=delays=5000:all=1']);
  assert.equal(result.sfx_bus_ffmpeg_primitive_tokens[0],
    'amix=inputs=2:duration=longest:dropout_transition=0:normalize=0');
  assert.equal(result.program_mix_ffmpeg_primitive_tokens[0],
    'amix=inputs=2:duration=first:dropout_transition=0:normalize=0');
  assert.equal(result.receipt.output_sample_rate_hz, DELIVERY_SAMPLE_RATE_HZ);
  assert.equal(result.receipt.output_channels, DELIVERY_CHANNELS);
  assert.equal(result.receipt.schema_version, SFX_COMPILE_RECEIPT_SCHEMA_VERSION);
  assert.equal(result.receipt.cue_count, 2);
  assert.equal(result.receipt.speech_overlap_cue_count, 1);
  assert.equal(result.receipt.max_observed_polyphony, 1);

  const primitiveTokens = result.compiled_cues.flatMap((cue) =>
    Object.entries(cue)
      .filter(([key]) => key.endsWith('_primitive_tokens'))
      .flatMap(([, value]) => value));
  assert.ok(primitiveTokens.every((token) => typeof token === 'string'));
  assert.ok(primitiveTokens.every((token) => !token.includes('://')));
  assert.ok(primitiveTokens.every((token) => !/[;&|`\r\n]/.test(token)));
  assert.match(JSON.stringify(result.compiled_cues), /licensed-external:\/\//);
});

test('empty forbidden plan compiles to no mix graph but a fully bound receipt', () => {
  const manifest = makeManifest();
  const policy = makePolicy('podcast_interview');
  const result = compileSfxPlan(makePlan(manifest, policy, []), manifest, policy);
  assert.deepEqual(result.compiled_cues, []);
  assert.deepEqual(result.program_input_ffmpeg_primitive_tokens, []);
  assert.deepEqual(result.sfx_bus_ffmpeg_primitive_tokens, []);
  assert.deepEqual(result.program_mix_ffmpeg_primitive_tokens, []);
  assert.equal(result.receipt.cue_count, 0);
  assert.equal(result.receipt.unique_asset_count, 0);
});

test('compile receipt is closed, canonical, and detects tampering and sparse ids', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const receipt = compileSfxPlan(makePlan(manifest, policy), manifest, policy).receipt;
  const original = sfxCompileReceiptSha256(receipt);
  let changed = clone(receipt);
  changed.output_duration_ms += 1;
  assert.notEqual(sfxCompileReceiptSha256(changed), original);
  changed = clone(receipt);
  changed.compiled_cues_sha256 = '0'.repeat(64);
  assert.notEqual(sfxCompileReceiptSha256(changed), original);
  changed = clone(receipt);
  changed.extra = true;
  assert.throws(() => sfxCompileReceiptSha256(changed), SfxPlanError);
  changed = clone(receipt);
  changed.cue_count += 1;
  assert.throws(() => sfxCompileReceiptSha256(changed), SfxPlanError);
  changed = clone(receipt);
  delete changed.ordered_cue_ids[0];
  assert.throws(() => canonicalSfxCompileReceiptJson(changed), SfxPlanError);
});

test('JSON schemas expose the complete closed v1 vocabulary and exact delivery format', () => {
  assert.equal(SFX_CUE_MANIFEST_JSON_SCHEMA.additionalProperties, false);
  assert.equal(SFX_PLAN_JSON_SCHEMA.additionalProperties, false);
  assert.equal(SFX_COMPILE_RECEIPT_JSON_SCHEMA.additionalProperties, false);
  assert.equal(
    SFX_CUE_MANIFEST_JSON_SCHEMA.properties.output_sample_rate_hz.const,
    DELIVERY_SAMPLE_RATE_HZ,
  );
  assert.equal(SFX_CUE_MANIFEST_JSON_SCHEMA.properties.output_channels.const, DELIVERY_CHANNELS);
  assert.deepEqual(
    SFX_CUE_MANIFEST_JSON_SCHEMA.properties.assets.items.properties.sample_rate_hz.enum,
    SAMPLE_RATES_HZ,
  );
  assert.deepEqual(
    SFX_CUE_MANIFEST_JSON_SCHEMA.properties.assets.items.properties.provenance.enum,
    PROVENANCE_KINDS,
  );
  assert.deepEqual(
    SFX_CUE_MANIFEST_JSON_SCHEMA.properties.assets.items.properties.license.properties.basis.enum,
    LICENSE_BASES,
  );
  assert.deepEqual(SFX_PLAN_JSON_SCHEMA.properties.cues.items.properties.kind.enum, CUE_KINDS);
  assert.deepEqual(
    SFX_PLAN_JSON_SCHEMA.properties.cues.items.properties.motivation.properties.category.enum,
    ANCHOR_CATEGORIES,
  );
  assert.deepEqual(SFX_PLAN_JSON_SCHEMA.properties.policy.properties.density.enum,
    POLICY_DENSITIES);
  assert.deepEqual(SFX_PLAN_JSON_SCHEMA.properties.policy.properties.usage.enum, POLICY_USAGES);
  assert.deepEqual(
    SFX_PLAN_JSON_SCHEMA.properties.cues.items.properties.ducking.oneOf[1]
      .properties.attenuation_millidb.enum,
    DUCK_ATTENUATIONS_MILLIDB,
  );
  for (const schema of [
    SFX_CUE_MANIFEST_JSON_SCHEMA,
    SFX_PLAN_JSON_SCHEMA,
    SFX_COMPILE_RECEIPT_JSON_SCHEMA,
  ]) {
    assert.deepEqual([...schema.required].sort(), Object.keys(schema.properties).sort());
  }
});
