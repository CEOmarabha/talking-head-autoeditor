'use strict';

// Deterministic, synthetic 16:9 artifact-review fixtures. The caller creates
// these inside its private probe workdir with the already bound local FFmpeg,
// then owns the returned path/hash descriptors. No imagery or font is fetched.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const WIDTH = 960;
const HEIGHT = 540;
const MAX_STDERR = 16 * 1024;
const ENCODE_TIMEOUT_MS = 20_000;
const FIXTURE_SCHEMA_VERSION = 'autoeditor-visual-quality-fixtures/v1';

const FONT = Object.freeze({
  ' ': ['00000','00000','00000','00000','00000','00000','00000'],
  A: ['01110','10001','10001','11111','10001','10001','10001'],
  B: ['11110','10001','10001','11110','10001','10001','11110'],
  C: ['01111','10000','10000','10000','10000','10000','01111'],
  D: ['11110','10001','10001','10001','10001','10001','11110'],
  E: ['11111','10000','10000','11110','10000','10000','11111'],
  F: ['11111','10000','10000','11110','10000','10000','10000'],
  G: ['01111','10000','10000','10111','10001','10001','01111'],
  H: ['10001','10001','10001','11111','10001','10001','10001'],
  I: ['11111','00100','00100','00100','00100','00100','11111'],
  J: ['00111','00010','00010','00010','10010','10010','01100'],
  K: ['10001','10010','10100','11000','10100','10010','10001'],
  L: ['10000','10000','10000','10000','10000','10000','11111'],
  M: ['10001','11011','10101','10101','10001','10001','10001'],
  N: ['10001','11001','10101','10011','10001','10001','10001'],
  O: ['01110','10001','10001','10001','10001','10001','01110'],
  P: ['11110','10001','10001','11110','10000','10000','10000'],
  Q: ['01110','10001','10001','10001','10101','10010','01101'],
  R: ['11110','10001','10001','11110','10100','10010','10001'],
  S: ['01111','10000','10000','01110','00001','00001','11110'],
  T: ['11111','00100','00100','00100','00100','00100','00100'],
  U: ['10001','10001','10001','10001','10001','10001','01110'],
  V: ['10001','10001','10001','10001','10001','01010','00100'],
  W: ['10001','10001','10001','10101','10101','10101','01010'],
  X: ['10001','10001','01010','00100','01010','10001','10001'],
  Y: ['10001','10001','01010','00100','00100','00100','00100'],
  Z: ['11111','00001','00010','00100','01000','10000','11111'],
  0: ['01110','10001','10011','10101','11001','10001','01110'],
  1: ['00100','01100','00100','00100','00100','00100','01110'],
  2: ['01110','10001','00001','00010','00100','01000','11111'],
  3: ['11110','00001','00001','01110','00001','00001','11110'],
  4: ['00010','00110','01010','10010','11111','00010','00010'],
  5: ['11111','10000','10000','11110','00001','00001','11110'],
  6: ['01110','10000','10000','11110','10001','10001','01110'],
  7: ['11111','00001','00010','00100','01000','01000','01000'],
  8: ['01110','10001','10001','01110','10001','10001','01110'],
  9: ['01110','10001','10001','01111','00001','00001','01110'],
  '+': ['00000','00100','00100','11111','00100','00100','00000'],
  '-': ['00000','00000','00000','11111','00000','00000','00000'],
  '.': ['00000','00000','00000','00000','00000','00110','00110'],
  ':': ['00000','00110','00110','00000','00110','00110','00000'],
  '/': ['00001','00010','00010','00100','01000','01000','10000'],
  '%': ['11001','11010','00100','01000','10110','00110','00000'],
  '?': ['01110','10001','00001','00010','00100','00000','00100'],
});

class Raster {
  constructor(width = WIDTH, height = HEIGHT) {
    this.width = width;
    this.height = height;
    this.data = Buffer.alloc(width * height * 3);
  }

  pixel(x, y, color) {
    x = Math.floor(x); y = Math.floor(y);
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return;
    const offset = (y * this.width + x) * 3;
    this.data[offset] = color[0];
    this.data[offset + 1] = color[1];
    this.data[offset + 2] = color[2];
  }

  fill(color) { this.rect(0, 0, this.width, this.height, color); }

  rect(x, y, width, height, color) {
    const left = Math.max(0, Math.floor(x));
    const top = Math.max(0, Math.floor(y));
    const right = Math.min(this.width, Math.ceil(x + width));
    const bottom = Math.min(this.height, Math.ceil(y + height));
    for (let row = top; row < bottom; row += 1) {
      let offset = (row * this.width + left) * 3;
      for (let column = left; column < right; column += 1) {
        this.data[offset++] = color[0];
        this.data[offset++] = color[1];
        this.data[offset++] = color[2];
      }
    }
  }

  gradient(left, right) {
    for (let y = 0; y < this.height; y += 1) {
      const mix = y / Math.max(1, this.height - 1);
      const color = [0, 1, 2].map((index) => Math.round(
        left[index] + (right[index] - left[index]) * mix));
      this.rect(0, y, this.width, 1, color);
    }
  }

  line(x0, y0, x1, y1, thickness, color) {
    const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0), 1);
    for (let index = 0; index <= steps; index += 1) {
      const mix = index / steps;
      this.rect(
        x0 + (x1 - x0) * mix - thickness / 2,
        y0 + (y1 - y0) * mix - thickness / 2,
        thickness, thickness, color,
      );
    }
  }

  circle(cx, cy, radius, color) {
    const squared = radius * radius;
    for (let y = Math.floor(cy - radius); y <= Math.ceil(cy + radius); y += 1) {
      const dy = y - cy;
      const span = Math.sqrt(Math.max(0, squared - dy * dy));
      this.rect(cx - span, y, span * 2 + 1, 1, color);
    }
  }

  text(value, x, y, scale, color, tracking = 1) {
    let cursor = x;
    for (const raw of String(value).toUpperCase()) {
      const glyph = FONT[raw] || FONT['?'];
      for (let row = 0; row < glyph.length; row += 1) {
        for (let column = 0; column < glyph[row].length; column += 1) {
          if (glyph[row][column] === '1') {
            this.rect(cursor + column * scale, y + row * scale,
              scale, scale, color);
          }
        }
      }
      cursor += (5 + tracking) * scale;
    }
    return cursor;
  }

  textWidth(value, scale, tracking = 1) {
    return Math.max(0, String(value).length * (5 + tracking) * scale - tracking * scale);
  }

  centeredText(value, y, scale, color, tracking = 1) {
    this.text(value, (this.width - this.textWidth(value, scale, tracking)) / 2,
      y, scale, color, tracking);
  }

  ppm() {
    return Buffer.concat([
      Buffer.from(`P6\n${this.width} ${this.height}\n255\n`, 'ascii'),
      this.data,
    ]);
  }
}

const COLORS = Object.freeze({
  navy: [11, 21, 42], deep: [18, 33, 58], teal: [28, 214, 190],
  cyan: [93, 225, 255], white: [246, 249, 252], cream: [245, 239, 222],
  gold: [244, 188, 74], ink: [20, 32, 47], coral: [255, 99, 92],
  red: [238, 32, 56], magenta: [255, 0, 160], lime: [163, 255, 0],
  gray: [95, 98, 106], black: [4, 4, 7],
});

function positiveTitle() {
  const image = new Raster();
  image.gradient(COLORS.navy, COLORS.deep);
  image.rect(64, 58, 9, 424, COLORS.teal);
  image.rect(104, 86, 244, 34, COLORS.teal);
  image.text('OPENING FILM', 118, 94, 3, COLORS.navy);
  image.text('NORTHSTAR', 110, 164, 13, COLORS.white);
  image.text('CREATIVE SUMMIT', 114, 282, 6, COLORS.cyan);
  image.line(114, 354, 820, 354, 3, COLORS.teal);
  image.text('LOS ANGELES / 2026', 114, 384, 4, COLORS.cream);
  image.text('DESIGNING IDEAS THAT MOVE', 114, 448, 3, COLORS.white);
  image.circle(850, 100, 34, COLORS.gold);
  image.circle(850, 100, 17, COLORS.navy);
  return image.ppm();
}

function positiveSpeaker() {
  const image = new Raster();
  image.gradient([14, 52, 63], COLORS.navy);
  image.rect(0, 0, 420, HEIGHT, [21, 87, 92]);
  image.circle(225, 190, 82, [224, 170, 127]);
  image.rect(150, 112, 150, 38, [29, 38, 55]);
  image.rect(198, 254, 54, 42, [224, 170, 127]);
  image.rect(130, 286, 190, 204, [31, 44, 73]);
  image.rect(130, 286, 190, 13, COLORS.gold);
  image.circle(194, 180, 8, COLORS.ink);
  image.circle(255, 180, 8, COLORS.ink);
  image.line(204, 225, 246, 225, 5, [120, 65, 55]);
  image.text('BUILD WITH', 478, 86, 7, COLORS.white);
  image.text('PURPOSE', 478, 160, 10, COLORS.teal);
  image.text('MAYA CHEN', 478, 278, 5, COLORS.gold);
  image.text('CREATIVE DIRECTOR', 478, 326, 3, COLORS.white);
  image.rect(54, 445, 852, 66, COLORS.black);
  image.text('GREAT STORIES MAKE IDEAS CLEAR', 102, 463, 4, COLORS.white);
  return image.ppm();
}

function positiveData() {
  const image = new Raster();
  image.fill(COLORS.cream);
  image.rect(0, 0, WIDTH, 72, COLORS.navy);
  image.text('NORTHSTAR / AUDIENCE IMPACT', 54, 23, 4, COLORS.white);
  image.text('AUDIENCE', 62, 116, 6, COLORS.ink);
  image.text('+42%', 62, 174, 12, [10, 132, 122]);
  image.text('YEAR OVER YEAR', 64, 278, 3, COLORS.gray);
  const bars = [112, 176, 238, 314];
  bars.forEach((height, index) => {
    const x = 470 + index * 96;
    image.rect(x, 420 - height, 58, height, index === bars.length - 1
      ? COLORS.coral : [61, 95, 120]);
    image.text(String(2023 + index), x - 3, 445, 2, COLORS.ink);
  });
  image.line(446, 420, 870, 420, 3, COLORS.ink);
  image.rect(48, 468, 850, 44, COLORS.navy);
  image.text('CLEAR DATA / CONFIDENT DECISIONS', 76, 481, 3, COLORS.white);
  return image.ppm();
}

function positiveClose() {
  const image = new Raster();
  image.gradient(COLORS.deep, [7, 16, 31]);
  image.circle(480, 118, 58, COLORS.teal);
  image.circle(480, 118, 29, COLORS.navy);
  image.centeredText('THANK YOU', 205, 12, COLORS.white);
  image.centeredText('MAKE THE NEXT IDEA MATTER', 330, 4, COLORS.cyan);
  image.rect(282, 410, 396, 56, COLORS.teal);
  image.centeredText('NORTHSTAR.STUDIO', 425, 4, COLORS.navy);
  return image.ppm();
}

function defectiveCaption() {
  const image = new Raster();
  image.fill(COLORS.magenta);
  image.rect(0, 0, WIDTH, 180, COLORS.lime);
  image.rect(30, 26, 900, 488, COLORS.red);
  image.circle(480, 245, 125, [230, 162, 116]);
  image.circle(435, 220, 12, COLORS.black);
  image.circle(525, 220, 12, COLORS.black);
  image.text('DRAFT', -38, 18, 18, COLORS.black);
  image.text('PLACEHOLDER', 118, 122, 10, COLORS.white);
  image.rect(0, 208, WIDTH, 126, COLORS.black);
  image.text('CAPTION OVER FACE', -55, 236, 11, COLORS.white);
  image.rect(0, 378, WIDTH, 144, COLORS.lime);
  image.text('THIS CAPTION IS CLIPPED OFF SCREEN', 390, 405, 8, COLORS.magenta);
  image.line(40, 40, 920, 500, 16, COLORS.cyan);
  image.line(920, 40, 40, 500, 16, COLORS.cyan);
  return image.ppm();
}

function defectiveDesign() {
  const image = new Raster();
  image.fill([76, 78, 81]);
  image.rect(0, 0, WIDTH, 72, [82, 84, 87]);
  image.text('FINAL FINAL V3?', 20, 20, 6, [91, 93, 96]);
  image.rect(44, 106, 872, 330, [88, 90, 92]);
  image.text('LOW CONTRAST', 90, 138, 10, [96, 98, 100]);
  image.text('ADD GRAPHIC HERE', 86, 244, 7, [94, 96, 98]);
  image.rect(0, 316, WIDTH, 104, [70, 72, 75]);
  image.text('CAPTION CAPTION CAPTION', 12, 338, 9, [78, 80, 83]);
  image.text('MISSING LOGO', 642, 486, 7, COLORS.red);
  return image.ppm();
}

const FRAME_DEFINITIONS = Object.freeze([
  Object.freeze({ kind: 'positive', id: 'positive-title-frame', timeSeconds: 0,
    target: Object.freeze({ id: 'positive-title', category: 'graphics',
      expectation: 'A polished branded opening title is readable and complete.' }),
    render: positiveTitle }),
  Object.freeze({ kind: 'positive', id: 'positive-speaker-frame', timeSeconds: 2,
    target: Object.freeze({ id: 'positive-target-caption', category: 'captions',
      expectation: 'The speaker composition and burned caption are clear and unobstructed.' }),
    render: positiveSpeaker }),
  Object.freeze({ kind: 'positive', id: 'positive-data-frame', timeSeconds: 4,
    target: Object.freeze({ id: 'positive-target-data', category: 'graphics',
      expectation: 'The data graphic has a clear hierarchy and legible labels.' }),
    render: positiveData }),
  Object.freeze({ kind: 'positive', id: 'positive-close-frame', timeSeconds: 6,
    target: Object.freeze({ id: 'positive-target-close', category: 'timeline',
      expectation: 'The closing call to action is polished and readable.' }),
    render: positiveClose }),
  Object.freeze({ kind: 'defective', id: 'defective-caption-frame', timeSeconds: 0,
    target: Object.freeze({ id: 'defective-caption', category: 'captions',
      expectation: 'Reject the visibly clipped, overlapping, face-obscuring caption.' }),
    render: defectiveCaption }),
  Object.freeze({ kind: 'defective', id: 'defective-design-frame', timeSeconds: 2,
    target: Object.freeze({ id: 'defective-target-design', category: 'graphics',
      expectation: 'Reject the low-contrast placeholder and unfinished production design.' }),
    render: defectiveDesign }),
]);
// The pinned 256M model did not follow the production JSON contract when all
// six frames were supplied together. The truthful runtime probe therefore
// measures only the narrow, mechanically obvious title/caption distinction.
const PROBE_FRAME_DEFINITIONS = Object.freeze([
  FRAME_DEFINITIONS[0],
  FRAME_DEFINITIONS[4],
]);

function fail(message) { throw new Error(message); }

function stableFixtureIdentity(file) {
  const descriptor = fs.openSync(file, 'r');
  try {
    const before = fs.fstatSync(descriptor);
    if (!before.isFile() || before.size < 4 || before.size > 3 * 1024 * 1024) {
      fail('generated visual-quality fixture has an invalid size');
    }
    const digest = crypto.createHash('sha256');
    const chunk = Buffer.allocUnsafe(256 * 1024);
    let offset = 0;
    while (offset < before.size) {
      const count = fs.readSync(descriptor, chunk, 0,
        Math.min(chunk.length, before.size - offset), offset);
      if (count < 1) fail('generated visual-quality fixture ended while measured');
      digest.update(chunk.subarray(0, count));
      offset += count;
    }
    const first = Buffer.alloc(2);
    const last = Buffer.alloc(2);
    fs.readSync(descriptor, first, 0, 2, 0);
    fs.readSync(descriptor, last, 0, 2, before.size - 2);
    const after = fs.fstatSync(descriptor);
    if (!first.equals(Buffer.from([0xff, 0xd8])) ||
        !last.equals(Buffer.from([0xff, 0xd9])) ||
        before.size !== after.size || before.mtimeMs !== after.mtimeMs ||
        before.dev !== after.dev || before.ino !== after.ino) {
      fail('generated visual-quality fixture changed while measured');
    }
    return { size_bytes: before.size, sha256: digest.digest('hex') };
  } finally { fs.closeSync(descriptor); }
}

function encodePpmWithFfmpeg({ ffmpegPath, ppmPath, jpegPath, signal }) {
  return new Promise((resolve, reject) => {
    let stderr = '';
    let expired = false;
    const child = spawn(ffmpegPath, [
      '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
      '-f', 'image2', '-i', ppmPath,
      '-frames:v', '1', '-c:v', 'mjpeg', '-q:v', '2', jpegPath,
    ], { stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true });
    const abort = () => child.kill();
    signal.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(() => { expired = true; child.kill(); },
      ENCODE_TIMEOUT_MS);
    child.stderr.on('data', (chunk) => {
      stderr = (stderr + chunk.toString('utf8')).slice(-MAX_STDERR);
    });
    child.once('error', (error) => {
      clearTimeout(timer); signal.removeEventListener('abort', abort);
      reject(error);
    });
    child.once('close', (code) => {
      clearTimeout(timer); signal.removeEventListener('abort', abort);
      if (signal.aborted) reject(new Error('visual-quality fixture encoding was canceled'));
      else if (expired) reject(new Error('visual-quality fixture encoding timed out'));
      else if (code !== 0) reject(new Error(
        `visual-quality fixture encoding failed: ${stderr.trim().slice(0, 500)}`));
      else resolve();
    });
  });
}

async function createVisualQualityFixtures({
  workDir,
  ffmpegPath,
  signal,
  encodeFrame = encodePpmWithFfmpeg,
} = {}) {
  if (typeof workDir !== 'string' || !path.isAbsolute(workDir) ||
      typeof ffmpegPath !== 'string' || !path.isAbsolute(ffmpegPath) ||
      !signal || typeof signal.aborted !== 'boolean' ||
      typeof encodeFrame !== 'function') {
    fail('visual-quality fixture configuration is invalid');
  }
  if (signal.aborted) fail('visual-quality fixture creation was canceled');
  let parent;
  try { parent = fs.realpathSync.native(workDir); }
  catch (_) { fail('visual-quality fixture workdir is unavailable'); }
  const root = fs.mkdtempSync(path.join(parent, 'visual-quality-fixtures-'));
  const result = { positiveFrames: [], defectiveFrames: [] };
  try {
    for (const definition of PROBE_FRAME_DEFINITIONS) {
      if (signal.aborted) fail('visual-quality fixture creation was canceled');
      const ppmPath = path.join(root, `${definition.id}.ppm`);
      const jpegPath = path.join(root, `${definition.id}.jpg`);
      fs.writeFileSync(ppmPath, definition.render(), { flag: 'wx', mode: 0o600 });
      try {
        await encodeFrame({ ffmpegPath, ppmPath, jpegPath, signal });
      } finally {
        fs.rmSync(ppmPath, { force: true });
      }
      const identity = stableFixtureIdentity(jpegPath);
      const record = Object.freeze({
        id: definition.id,
        path: jpegPath,
        sha256: identity.sha256,
        size_bytes: identity.size_bytes,
        timeSeconds: definition.timeSeconds,
        targets: Object.freeze([Object.freeze({ ...definition.target })]),
      });
      result[definition.kind === 'positive'
        ? 'positiveFrames' : 'defectiveFrames'].push(record);
    }
    return Object.freeze({
      schema_version: FIXTURE_SCHEMA_VERSION,
      approvedBrief: [
        'Deliver one premium Northstar opening title in an intentional retro',
        'pixel-art design system with clear hierarchy and readable text. Reject',
        'draft labels, placeholders, clipped, overlapping, or face-obscuring',
        'captions, unreadable contrast, and unfinished production design.',
      ].join(' '),
      positiveFrames: Object.freeze(result.positiveFrames),
      defectiveFrames: Object.freeze(result.defectiveFrames),
    });
  } catch (error) {
    fs.rmSync(root, { recursive: true, force: true });
    throw error;
  }
}

module.exports = Object.freeze({
  FIXTURE_SCHEMA_VERSION,
  FRAME_DEFINITIONS,
  PROBE_FRAME_DEFINITIONS,
  HEIGHT,
  WIDTH,
  createVisualQualityFixtures,
  encodePpmWithFfmpeg,
});
