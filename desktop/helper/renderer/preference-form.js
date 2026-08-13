(function exposePreferenceForm(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AutoEditorPreferenceForm = api;
})(typeof globalThis === 'object' ? globalThis : this, function preferenceFormFactory() {
  'use strict';

  const DEFECTS = new Set([
    'captions', 'audio', 'sound-design', 'transitions', 'pacing', 'cuts',
    'continuity', 'framing', 'color', 'graphics', 'b-roll', 'accessibility',
    'export', 'other',
  ]);

  function parseTimestamp(value) {
    const text = String(value || '').trim();
    if (/^\d+(?:\.\d{1,3})?$/.test(text)) {
      const milliseconds = Math.round(Number(text) * 1000);
      if (milliseconds <= 24 * 60 * 60 * 1000) return milliseconds;
    }
    const match = text.match(/^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?$/);
    if (!match) throw new Error(`Invalid timecode: ${text}`);
    const hours = Number(match[1] || 0);
    const minutes = Number(match[2]);
    const seconds = Number(match[3]);
    if (hours > 24 || minutes > 59 || seconds > 59) {
      throw new Error(`Invalid timecode: ${text}`);
    }
    const fraction = String(match[4] || '').padEnd(3, '0');
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + Number(fraction || 0);
  }

  function parseTimecodes(value) {
    const lines = String(value || '').split(/\r?\n/)
      .map((line) => line.trim()).filter(Boolean);
    if (!lines.length) throw new Error('Add at least one timecoded example.');
    if (lines.length > 32) throw new Error('Use at most 32 timecoded examples.');
    return lines.map((line, index) => {
      const parts = line.split('|').map((part) => part.trim());
      if (parts.length !== 5) {
        throw new Error(`Timecode line ${index + 1} must have five | separated fields.`);
      }
      const [artifact, start, end, category, note] = parts;
      if (artifact !== 'before' && artifact !== 'after') {
        throw new Error(`Timecode line ${index + 1} version must be before or after.`);
      }
      if (!DEFECTS.has(category)) {
        throw new Error(`Timecode line ${index + 1} has an unsupported category.`);
      }
      if (!note || note.length > 400) {
        throw new Error(`Timecode line ${index + 1} needs a note up to 400 characters.`);
      }
      const startMs = parseTimestamp(start);
      const endMs = parseTimestamp(end);
      if (endMs < startMs) {
        throw new Error(`Timecode line ${index + 1} ends before it starts.`);
      }
      return { artifact, startMs, endMs, category, note };
    });
  }

  function resultTarget(attachments, currentResultPath) {
    return Array.isArray(attachments) && attachments.length
      ? '' : String(currentResultPath || '');
  }

  function comparisonPair(renderPayload, output) {
    const beforeResultPath = typeof renderPayload?.resultPath === 'string'
      ? renderPayload.resultPath : '';
    const afterResultPath = typeof output === 'string' ? output : '';
    if (!beforeResultPath || !afterResultPath || beforeResultPath === afterResultPath) {
      return null;
    }
    return Object.freeze({ beforeResultPath, afterResultPath });
  }

  return Object.freeze({ parseTimestamp, parseTimecodes, resultTarget, comparisonPair });
});
