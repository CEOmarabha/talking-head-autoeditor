const assert = require('assert');
const fs = require('fs');
const path = require('path');

const helperRoot = path.join(__dirname, '..', 'helper');
const helperMain = fs.readFileSync(path.join(helperRoot, 'main.js'), 'utf8');
const helperPreload = fs.readFileSync(path.join(helperRoot, 'preload.js'), 'utf8');
const helperHtml = fs.readFileSync(
  path.join(helperRoot, 'renderer', 'index.html'), 'utf8');
const helperRenderer = fs.readFileSync(
  path.join(helperRoot, 'renderer', 'app.js'), 'utf8');
const daemonEntry = fs.readFileSync(
  path.join(__dirname, '..', '..', 'packaging', 'helper_daemon_entry.py'), 'utf8');

assert.ok(!helperMain.includes("require('./lib/setup-code')"));
assert.ok(!helperMain.includes('AUTOEDITOR_WEB_API:'));
assert.ok(!helperMain.includes('WORKER_TOKEN:'));
assert.ok(!helperMain.includes('startDaemon'));
assert.ok(helperMain.includes("DEEPSEEK_API_KEY: settings.deepseekApiKey || ''"));
assert.ok(helperMain.includes("PEXELS_API_KEY: settings.pexelsApiKey || ''"));
assert.ok(helperMain.includes("PIXABAY_API_KEY: settings.pixabayApiKey || ''"));
assert.ok(helperMain.includes(
  "ELEVENLABS_API_KEY: settings.elevenLabsApiKey || ''"));
assert.ok(helperMain.includes("REMOTION_LICENSE_KEY: settings.remotionKey || ''"));
assert.ok(helperMain.includes("return path.join(app.getPath('userData'), 'local-settings.enc')"));
assert.ok(helperMain.includes('safeStorage.encryptString(JSON.stringify(normalized))'));
assert.ok(helperMain.includes('safeStorage.decryptString'));
assert.ok(helperMain.includes('spawn(p.daemon, [mode]'));
assert.ok(helperMain.includes("localProcess('--local-render'"));
assert.ok(helperMain.includes("localProcess('--local-chat'"));
assert.ok(helperMain.includes("child.stdin.end(`${JSON.stringify(payload)}\\n`)"));
assert.ok(helperMain.includes('returnedProposals'));
assert.ok(helperMain.includes('returnedOutputs'));
assert.ok(helperMain.includes('stopProcessTree(action.proc)'));
assert.ok(helperMain.includes('preflight({ checkKeystore: !screenshotMode })'));

for (const api of [
  'pickVideos', 'pickOutput', 'saveSettings', 'renderLocal', 'cancelLocal',
  'chatLocal', 'applyLocal', 'openResult', 'onRender',
]) {
  assert.ok(helperPreload.includes(`${api}:`), api);
}

assert.ok(helperHtml.includes('Rendering and file saving stay on this computer.'));
assert.ok(helperHtml.includes('What do you want done to this video?'));
assert.ok(helperHtml.includes('Your edit with DeepSeek'));
assert.ok(helperHtml.includes('DeepSeek API key'));
assert.ok(helperHtml.indexOf('id="edit-request"') < helperHtml.indexOf('id="script"'));
assert.ok(!/setup code/i.test(helperHtml));
assert.ok(!/AutoEditor website/i.test(helperHtml));
assert.ok(!/Start Helper/i.test(helperHtml));
assert.ok(helperRenderer.includes('window.helper.chatLocal'));
assert.ok(helperRenderer.includes('window.helper.applyLocal'));
assert.ok(helperRenderer.includes('app.initialPlanning = true'));
assert.ok(helperRenderer.includes('DeepSeek planned the edit. Rendering it on this computer...'));
assert.ok(helperRenderer.includes('history: app.chat.slice(0, -1).slice(-12)'));

assert.ok(daemonEntry.includes('def local_render()'));
assert.ok(daemonEntry.includes('def local_chat()'));
assert.ok(daemonEntry.includes('revision_engine_args'));
assert.ok(daemonEntry.includes('provider="deepseek"'));
assert.ok(daemonEntry.includes('"--local-render", "--local-chat"'));

console.log('helper local-only setup contract passed');
