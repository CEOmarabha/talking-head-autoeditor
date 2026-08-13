'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  FIXTURE_SCHEMA_VERSION,
  FRAME_DEFINITIONS,
  PROBE_FRAME_DEFINITIONS,
  HEIGHT,
  WIDTH,
  createVisualQualityFixtures,
} = require('../helper/lib/visual-quality-fixtures');

async function main() {
  assert.equal(FIXTURE_SCHEMA_VERSION, 'autoeditor-visual-quality-fixtures/v1');
  assert.equal(FRAME_DEFINITIONS.length, 6);
  assert.deepEqual(FRAME_DEFINITIONS.map(({ kind }) => kind), [
    'positive', 'positive', 'positive', 'positive', 'defective', 'defective',
  ]);
  assert.equal(new Set(FRAME_DEFINITIONS.map(({ id }) => id)).size, 6);
  assert.equal(new Set(FRAME_DEFINITIONS.map(({ target }) => target.id)).size, 6);
  assert.deepEqual(PROBE_FRAME_DEFINITIONS.map(({ id }) => id), [
    'positive-title-frame', 'defective-caption-frame',
  ]);
  for (const definition of FRAME_DEFINITIONS) {
    const ppm = definition.render();
    const separator = ppm.indexOf(Buffer.from('\n255\n'));
    assert.ok(separator > 0);
    assert.equal(ppm.subarray(0, separator + 5).toString('ascii'),
      `P6\n${WIDTH} ${HEIGHT}\n255\n`);
    assert.equal(ppm.length - separator - 5, WIDTH * HEIGHT * 3);
  }

  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'visual-fixtures-test-'));
  try {
    const calls = [];
    const created = await createVisualQualityFixtures({
      workDir: root,
      ffmpegPath: path.join(root, 'fixed-ffmpeg'),
      signal: new AbortController().signal,
      encodeFrame: async (request) => {
        calls.push(request);
        assert.ok(fs.readFileSync(request.ppmPath, 'ascii').startsWith('P6\n'));
        fs.writeFileSync(request.jpegPath,
          Buffer.from([0xff, 0xd8, request.ppmPath.length % 255, 0xff, 0xd9]),
          { flag: 'wx' });
      },
    });
    assert.equal(calls.length, 2);
    assert.equal(created.schema_version, FIXTURE_SCHEMA_VERSION);
    assert.equal(created.positiveFrames.length, 1);
    assert.equal(created.defectiveFrames.length, 1);
    assert.ok(created.approvedBrief.includes('retro pixel-art design system'));
    const all = [...created.positiveFrames, ...created.defectiveFrames];
    assert.ok(all.every((frame) => path.isAbsolute(frame.path) &&
      /^[0-9a-f]{64}$/.test(frame.sha256) && frame.size_bytes === 5 &&
      frame.targets.length === 1));
    assert.equal(new Set(all.flatMap((frame) =>
      frame.targets.map((target) => target.id))).size, 2);
    assert.equal(fs.readdirSync(path.dirname(all[0].path))
      .filter((name) => name.endsWith('.ppm')).length, 0);

    const canceled = new AbortController();
    canceled.abort();
    await assert.rejects(createVisualQualityFixtures({
      workDir: root,
      ffmpegPath: path.join(root, 'fixed-ffmpeg'),
      signal: canceled.signal,
      encodeFrame: async () => assert.fail(),
    }), /canceled/);

    const ffmpeg = process.env.AUTOEDITOR_FFMPEG || '';
    if (path.isAbsolute(ffmpeg) && fs.existsSync(ffmpeg)) {
      const real = await createVisualQualityFixtures({
        workDir: root, ffmpegPath: ffmpeg,
        signal: new AbortController().signal,
      });
      assert.ok([...real.positiveFrames, ...real.defectiveFrames]
        .every((frame) => frame.size_bytes > 10_000));
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
  console.log('visual-quality fixture tests passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
