'use strict';

const { canonicalText } = require('./story-plan');

const CREATIVE_CONSTRAINTS_SCHEMA = 'autoeditor-creative-constraints/v1';
const GRAPHIC_KINDS = Object.freeze(['bars', 'callout', 'keyword', 'stat']);
const GRAPHIC_KIND_SET = new Set(GRAPHIC_KINDS);
const ROOT_KEYS = Object.freeze([
  'schema_version', 'opener', 'visual_policy', 'required_graphic',
  'music_allowed',
]);
const OPENER_KEYS = Object.freeze(['exact_text', 'max_start_seconds']);
const VISUAL_POLICY_KEYS = Object.freeze([
  'graphics_exact', 'broll_exact', 'opening_punch_required',
  'opening_visual_required', 'max_visual_gap_seconds',
]);
const REQUIRED_GRAPHIC_KEYS = Object.freeze(['kind', 'text', 'anchor_text']);

function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

// Schema-shape illustration only. Deliberately contains no source-video or
// user-specific wording; the editing prompt requires replacing every value
// from the current request and kept transcript before execution.
const CREATIVE_CONSTRAINTS_SCHEMA_EXAMPLE = deepFreeze({
  schema_version: CREATIVE_CONSTRAINTS_SCHEMA,
  opener: {
    exact_text: 'REPLACE WITH EXACT OPENER',
    max_start_seconds: 3,
  },
  visual_policy: {
    graphics_exact: 1,
    broll_exact: 0,
    opening_punch_required: true,
    opening_visual_required: false,
    max_visual_gap_seconds: null,
  },
  required_graphic: {
    kind: 'callout',
    text: 'REPLACE DISPLAY COPY',
    anchor_text: 'REPLACE WITH EXACT KEPT ANCHOR',
  },
  music_allowed: false,
});

function isPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exactKeys(value, expected) {
  if (!isPlainObject(value)) return false;
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index]);
}

function canonicalString(value, label, maximum, requireCanonical) {
  if (typeof value !== 'string') {
    throw new TypeError(`${label} must be a string`);
  }
  const clean = canonicalText(value);
  if (!clean || clean.length > maximum || (requireCanonical && clean !== value)) {
    throw new Error(`${label} must be canonical text containing 1-${maximum} characters`);
  }
  return clean;
}

function boundedNumber(value, label, low, high) {
  if (typeof value !== 'number' || !Number.isFinite(value) ||
      value < low || value > high) {
    throw new Error(`${label} must be a finite number from ${low} to ${high}`);
  }
  return value;
}

function exactCount(value, label) {
  if (!Number.isSafeInteger(value) || value < 0 || value > 16) {
    throw new Error(`${label} must be an integer from 0 to 16`);
  }
  return value;
}

function wordTokens(value) {
  return (canonicalText(value)
    .replace(/[\u2018\u2019\u02bc\uff07]/g, "'")
    .toLowerCase().match(/[a-z0-9']+/g) || []);
}

function assertStoryLink(constraints, storyPlan) {
  if (!isPlainObject(storyPlan) || !Array.isArray(storyPlan.keep_ranges) ||
      storyPlan.keep_ranges.length < 2) {
    throw new Error('creative constraints require a valid story plan');
  }
  const firstAnchor = canonicalText(storyPlan.keep_ranges[0]?.anchor_text);
  const opener = constraints.opener.exact_text;
  if (firstAnchor !== opener && !firstAnchor.startsWith(`${opener} `)) {
    throw new Error('creative constraints opener must exactly prefix the first kept story anchor');
  }
  if (constraints.required_graphic !== null) {
    const keptTranscript = canonicalText(storyPlan.keep_ranges
      .map((range) => range?.anchor_text).join(' '));
    if (!keptTranscript.includes(constraints.required_graphic.anchor_text)) {
      throw new Error('creative constraints required graphic anchor is absent from the kept story transcript');
    }
  }
}

function validateCreativeConstraints(raw, storyPlan = null, {
  requireCanonical = false,
} = {}) {
  if (!exactKeys(raw, ROOT_KEYS)) {
    throw new Error('creative constraints do not match the executable contract');
  }
  if (raw.schema_version !== CREATIVE_CONSTRAINTS_SCHEMA) {
    throw new Error('creative constraints schema is unsupported');
  }
  if (!exactKeys(raw.opener, OPENER_KEYS)) {
    throw new Error('creative constraints opener does not match the executable contract');
  }
  const openerText = canonicalString(
    raw.opener.exact_text, 'opener.exact_text', 160, requireCanonical);
  const openerStart = boundedNumber(
    raw.opener.max_start_seconds, 'opener.max_start_seconds', 0, 10);

  if (!exactKeys(raw.visual_policy, VISUAL_POLICY_KEYS)) {
    throw new Error('creative constraints visual policy does not match the executable contract');
  }
  const policy = raw.visual_policy;
  const graphicsExact = exactCount(
    policy.graphics_exact, 'visual_policy.graphics_exact');
  const brollExact = exactCount(policy.broll_exact, 'visual_policy.broll_exact');
  if (typeof policy.opening_punch_required !== 'boolean' ||
      typeof policy.opening_visual_required !== 'boolean') {
    throw new Error('creative constraints opening requirements must be boolean');
  }
  const maxVisualGap = policy.max_visual_gap_seconds === null ? null
    : boundedNumber(policy.max_visual_gap_seconds,
      'visual_policy.max_visual_gap_seconds', 1, 300);

  let requiredGraphic = null;
  if (raw.required_graphic !== null) {
    if (!exactKeys(raw.required_graphic, REQUIRED_GRAPHIC_KEYS)) {
      throw new Error('creative constraints required graphic does not match the executable contract');
    }
    if (graphicsExact !== 1) {
      throw new Error('creative constraints required graphic requires graphics_exact=1');
    }
    const rawKind = canonicalString(
      raw.required_graphic.kind, 'required_graphic.kind', 16, requireCanonical);
    const kind = rawKind.toLowerCase();
    if (requireCanonical && kind !== rawKind) {
      throw new Error('required_graphic.kind must be canonical lowercase text');
    }
    if (!GRAPHIC_KIND_SET.has(kind)) {
      throw new Error('creative constraints required graphic kind is unsupported');
    }
    const text = canonicalString(
      raw.required_graphic.text, 'required_graphic.text', 44, requireCanonical);
    const words = text.match(/[A-Za-z0-9']+/g) || [];
    if (text !== text.toUpperCase() || words.length > 4) {
      throw new Error('required_graphic.text must be uppercase and at most four words');
    }
    const anchorText = canonicalString(
      raw.required_graphic.anchor_text, 'required_graphic.anchor_text', 200,
      requireCanonical);
    const anchorWords = wordTokens(anchorText);
    if (anchorWords.length < 5 || anchorWords.length > 20) {
      throw new Error('required_graphic.anchor_text must contain 5-20 exact words');
    }
    requiredGraphic = Object.freeze({ kind, text, anchor_text: anchorText });
  } else if (graphicsExact === 1) {
    throw new Error('creative constraints with one exact graphic require its specification');
  }

  if (typeof raw.music_allowed !== 'boolean') {
    throw new Error('creative constraints music_allowed must be boolean');
  }

  const constraints = Object.freeze({
    schema_version: CREATIVE_CONSTRAINTS_SCHEMA,
    opener: Object.freeze({
      exact_text: openerText,
      max_start_seconds: openerStart,
    }),
    visual_policy: Object.freeze({
      graphics_exact: graphicsExact,
      broll_exact: brollExact,
      opening_punch_required: policy.opening_punch_required,
      opening_visual_required: policy.opening_visual_required,
      max_visual_gap_seconds: maxVisualGap,
    }),
    required_graphic: requiredGraphic,
    music_allowed: raw.music_allowed,
  });
  if (storyPlan !== null) assertStoryLink(constraints, storyPlan);
  return constraints;
}

function normalizeCreativeConstraints(raw, storyPlan) {
  try {
    return validateCreativeConstraints(raw, storyPlan);
  } catch (_) {
    return null;
  }
}

function structuralCreativeConstraints(raw, storyPlan) {
  validateCreativeConstraints(raw, storyPlan, { requireCanonical: true });
  return raw;
}

module.exports = Object.freeze({
  CREATIVE_CONSTRAINTS_SCHEMA,
  GRAPHIC_KINDS,
  CREATIVE_CONSTRAINTS_SCHEMA_EXAMPLE,
  validateCreativeConstraints,
  normalizeCreativeConstraints,
  structuralCreativeConstraints,
});
