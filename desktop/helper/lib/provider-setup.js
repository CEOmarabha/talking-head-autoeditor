'use strict';

const PROVIDER_LINKS = Object.freeze({
  pexelsSignup: 'https://www.pexels.com/join/',
  pexelsApi: 'https://www.pexels.com/api/',
  pixabaySignup: 'https://pixabay.com/accounts/register/',
  pixabayApi: 'https://pixabay.com/api/docs/',
  elevenSignup: 'https://elevenlabs.io/app/sign-up',
  elevenApiKeys: 'https://elevenlabs.io/app/settings/api-keys',
  elevenPricing: 'https://elevenlabs.io/pricing/api',
  remotionLicense: 'https://www.remotion.dev/docs/license/pricing',
  remotionDashboard: 'https://remotion.pro/dashboard',
});

function requiredText(value, label) {
  const text = String(value || '').trim();
  if (!text) throw new Error(`${label} is required`);
  if (text.length > 500) throw new Error(`${label} is too long`);
  return text;
}

function normalizeProviderSetup(input) {
  const value = input && typeof input === 'object' ? input : {};
  const setupCode = requiredText(value.setupCode, 'Setup code');
  const pexelsMode = value.pexelsMode === 'connect' ? 'connect' :
    (value.pexelsMode === 'skip' ? 'skip' : '');
  const pixabayMode = value.pixabayMode === 'connect' ? 'connect' :
    (value.pixabayMode === 'skip' ? 'skip' : '');
  const elevenMode = value.elevenMode === 'connect' ? 'connect' :
    (value.elevenMode === 'skip' ? 'skip' : '');
  if (!pexelsMode) throw new Error('Choose Connect or Skip for Pexels');
  if (!pixabayMode) throw new Error('Choose Connect or Skip for Pixabay');
  if (!elevenMode) throw new Error('Choose Connect or Skip for ElevenLabs');
  const pexelsKey = pexelsMode === 'connect'
    ? requiredText(value.pexelsKey, 'Pexels API key') : '';
  const pixabayKey = pixabayMode === 'connect'
    ? requiredText(value.pixabayKey, 'Pixabay API key') : '';
  const elevenKey = elevenMode === 'connect'
    ? requiredText(value.elevenKey, 'ElevenLabs API key') : '';
  const remotionMode = ['free', 'paid'].includes(value.remotionMode)
    ? value.remotionMode : '';
  if (!remotionMode) {
    throw new Error('Remotion is required. Choose the license that applies to you');
  }
  const remotionKey = remotionMode === 'free' ? 'free-license' :
    requiredText(value.remotionKey, 'Remotion license key');
  if (remotionMode === 'paid' && !/^rm_pub_[A-Za-z0-9]{48}$/.test(remotionKey)) {
    throw new Error('That Remotion public license key does not look valid');
  }
  return {
    setupCode, pexelsMode, pexelsKey, pixabayMode, pixabayKey,
    elevenMode, elevenKey,
    remotionMode, remotionKey,
  };
}

async function checkedJson(url, options, label, fetchImpl = globalThis.fetch) {
  if (typeof fetchImpl !== 'function') throw new Error('Secure web checks are unavailable');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  let response;
  try {
    response = await fetchImpl(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error(`${label} did not respond. Check your internet connection and try again`);
    }
    throw new Error(`${label} could not be reached. Check your internet connection and try again`);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    throw new Error(`${label} rejected that key. Copy the key again from your ${label} account`);
  }
  try { return await response.json(); } catch (_) {
    throw new Error(`${label} returned an unreadable response. Try again in a few minutes`);
  }
}

async function validateProviderKeys(setup, fetchImpl = globalThis.fetch) {
  if (setup.pexelsMode === 'connect') {
    const pexels = await checkedJson(
      'https://api.pexels.com/v1/videos/search?query=nature&per_page=1',
      { headers: { Authorization: setup.pexelsKey } }, 'Pexels', fetchImpl);
    if (!Array.isArray(pexels.videos)) {
      throw new Error('Pexels key check returned no video list');
    }
  }

  if (setup.pixabayMode === 'connect') {
    const pixabay = await checkedJson(
      `https://pixabay.com/api/videos/?key=${encodeURIComponent(setup.pixabayKey)}` +
        '&q=nature&per_page=3&safesearch=true',
      {}, 'Pixabay', fetchImpl);
    if (!Array.isArray(pixabay.hits)) {
      throw new Error('Pixabay key check returned no video list');
    }
  }
  if (setup.elevenMode === 'connect') {
    const eleven = await checkedJson(
      'https://api.elevenlabs.io/v1/user',
      { headers: { 'xi-api-key': setup.elevenKey } }, 'ElevenLabs', fetchImpl);
    if (!eleven || typeof eleven.user_id !== 'string' || !eleven.subscription) {
      throw new Error('ElevenLabs key check returned no user information');
    }
  }
  return {
    pexels: setup.pexelsMode === 'connect',
    pixabay: setup.pixabayMode === 'connect',
    elevenlabs: setup.elevenMode === 'connect',
  };
}

module.exports = { PROVIDER_LINKS, normalizeProviderSetup, validateProviderKeys };
