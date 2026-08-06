const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { writeClipCatalog } = require('../lib/clip-catalog');

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'clip-catalog-test-'));
try {
  const windowsPath = 'C:\\Ryan Clips\\POV, part 1.mp4';
  const quotedPath = '/tmp/Ryan "reaction".mov';
  const catalog = writeClipCatalog([windowsPath, quotedPath], work);
  const text = fs.readFileSync(catalog, 'utf8');
  assert.ok(text.startsWith('path,scene_family,duration_sec,rating\n'));
  assert.ok(text.includes('"C:\\Ryan Clips\\POV, part 1.mp4"'));
  assert.ok(text.includes('"/tmp/Ryan ""reaction"".mov"'));
  assert.strictEqual(text.trimEnd().split('\n').length, 3);
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
