const assert = require('assert');
const fs = require('fs');
const path = require('path');

const desktop = path.resolve(__dirname, '..');
const main = fs.readFileSync(path.join(desktop, 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8');
const renderer = fs.readFileSync(
  path.join(desktop, 'renderer', 'app.js'), 'utf8');
const workflow = fs.readFileSync(
  path.join(desktop, '..', '.github', 'workflows', 'release.yml'), 'utf8');

assert.ok((main.match(/windowsHide: true/g) || []).length >= 3);
assert.ok(main.includes('stopProcessTree(active)'));
assert.ok(main.includes("AUTOEDITOR_SMOKE_TEST === '1'"));
assert.ok(main.includes('safeStorage.encryptString(secret)'));
assert.ok(preload.includes('webUtils.getPathForFile(file)'));
assert.ok(renderer.includes('window.api.filePath(f)'));
assert.ok(!renderer.includes('.map((f) => f.path)'));
assert.ok(workflow.includes('Smoke-test Windows installer'));
assert.ok(workflow.includes('Smoke-test macOS app and DMG'));
assert.ok(workflow.includes('Publish only after every platform passes'));
