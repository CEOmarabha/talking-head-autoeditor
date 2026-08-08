const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { decodeSetupCode } = require('../helper/lib/setup-code');
const {
  normalizeProviderSetup, validateProviderKeys,
} = require('../helper/lib/provider-setup');

const encoded = Buffer.from(
  'https://autoeditor-web.mromarmarabha.workers.dev|friend-token-1234567890', 'utf8')
  .toString('base64url');
assert.deepStrictEqual(decodeSetupCode(encoded), {
  site: 'https://autoeditor-web.mromarmarabha.workers.dev',
  token: 'friend-token-1234567890',
});
assert.throws(() => decodeSetupCode('not-valid'), /not valid/);
const forged = Buffer.from(
  'https://fake-autoeditor.example|friend-token-1234567890', 'utf8')
  .toString('base64url');
assert.throws(() => decodeSetupCode(forged), /official AutoEditor website/);
const pathInjected = Buffer.from(
  'https://autoeditor-web.mromarmarabha.workers.dev/other|friend-token-1234567890',
  'utf8').toString('base64url');
assert.throws(() => decodeSetupCode(pathInjected), /invalid site address/);

const skipped = normalizeProviderSetup({
  setupCode: encoded, pexelsMode: 'skip', pixabayMode: 'skip',
  elevenMode: 'skip', remotionMode: 'free',
});
assert.strictEqual(skipped.pexelsKey, '');
assert.strictEqual(skipped.pixabayKey, '');
assert.strictEqual(skipped.elevenKey, '');
assert.strictEqual(skipped.remotionKey, 'free-license');
assert.throws(() => normalizeProviderSetup({
  setupCode: encoded, pexelsMode: 'skip', pixabayMode: 'skip',
  elevenMode: 'skip', remotionMode: 'skip',
}), /Remotion is required/);

assert.throws(() => normalizeProviderSetup({
  setupCode: encoded,
  pexelsMode: 'connect', pixabayMode: 'skip', elevenMode: 'skip', remotionMode: 'free',
}), /Pexels API key is required/);

assert.throws(() => normalizeProviderSetup({
  setupCode: encoded,
  pexelsMode: 'skip', pixabayMode: 'skip', elevenMode: 'skip',
  remotionMode: 'paid', remotionKey: 'rm_wrong',
}), /Remotion public license key does not look valid/);
const paidRemotion = normalizeProviderSetup({
  setupCode: encoded,
  pexelsMode: 'skip', pixabayMode: 'skip', elevenMode: 'skip',
  remotionMode: 'paid', remotionKey: `rm_pub_${'A'.repeat(48)}`,
});
assert.strictEqual(paidRemotion.remotionKey, `rm_pub_${'A'.repeat(48)}`);

const helperMain = fs.readFileSync(
  path.join(__dirname, '..', 'helper', 'main.js'), 'utf8');
const helperHtml = fs.readFileSync(
  path.join(__dirname, '..', 'helper', 'renderer', 'index.html'), 'utf8');
const friendSiteHtml = fs.readFileSync(
  path.join(__dirname, '..', '..', 'webapp', 'site', 'index.html'), 'utf8');
assert.ok(helperMain.includes(
  "['pexels-mode', 'pixabay-mode', 'eleven-mode']"));
assert.ok(!helperMain.includes(
  "['pexels-mode', 'pixabay-mode', 'eleven-mode', 'remotion-mode']"));
assert.ok(helperHtml.includes(
  'HyperFrames and Remotion stay on for every edit'));
assert.ok(!helperHtml.includes('For every other account below, choose Skip'));
assert.ok(/HyperFrames and Remotion\r?\n      are required and already included/
  .test(friendSiteHtml));
assert.ok(friendSiteHtml.includes(
  'Remotion stays enabled and asks you to choose the free or paid license'));
assert.ok(!friendSiteHtml.includes(
  'paid Remotion account are only needed for the resources you choose'));
assert.ok(helperMain.includes(
  'preflight({ checkKeystore: !screenshotMode })'));
assert.ok(helperMain.includes(
  'const checks = preflight({ checkKeystore: false, checkDisk: false })'));
assert.ok(helperMain.includes(
  'function preflight({ checkKeystore = true, checkDisk = true } = {})'));
assert.ok(helperMain.includes('if (checkDisk)'));
assert.ok(helperMain.includes(
  'Number(stat.bavail) * Number(stat.bsize) >= MIN_FREE_BYTES'));
assert.ok(helperMain.includes('const ready = preflight()'));
assert.ok(helperMain.includes(
  'safeStorage.isEncryptionAvailable() : true'));
assert.ok(helperMain.includes(
  'if (!safeStorage.isEncryptionAvailable())'));

(async () => {
  let calls = 0;
  await validateProviderKeys(skipped, async () => { calls += 1; });
  assert.strictEqual(calls, 0);

  const connected = normalizeProviderSetup({
    setupCode: encoded,
    pexelsMode: 'connect', pexelsKey: 'pexels-secret',
    pixabayMode: 'connect', pixabayKey: 'pixabay-secret',
    elevenMode: 'connect', elevenKey: 'eleven-secret',
    remotionMode: 'free',
  });
  const urls = [];
  const fakeFetch = async (url) => {
    urls.push(String(url));
    return {
      ok: true,
      json: async () => urls.length === 1 ? { videos: [] } :
        (urls.length === 2 ? { hits: [] } : {
          user_id: 'friend', subscription: { tier: 'free' },
        }),
    };
  };
  const result = await validateProviderKeys(connected, fakeFetch);
  assert.deepStrictEqual(result, {
    pexels: true, pixabay: true, elevenlabs: true,
  });
  assert.ok(urls[0].startsWith('https://api.pexels.com/v1/videos/search'));
  assert.ok(urls[1].startsWith('https://pixabay.com/api/videos/'));
  assert.strictEqual(urls[2], 'https://api.elevenlabs.io/v1/user');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
