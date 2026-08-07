'use strict';

const ALLOWED_SITE_HOSTS = new Set([
  'autoeditor-web.mromarmarabha.workers.dev',
]);

function decodeSetupCode(value) {
  const raw = String(value || '').trim();
  if (!raw) throw new Error('Paste the Setup code from the AutoEditor website');
  let decoded;
  try {
    const pad = '='.repeat((4 - (raw.length % 4)) % 4);
    decoded = Buffer.from(raw.replace(/-/g, '+').replace(/_/g, '/') + pad,
      'base64').toString('utf8');
  } catch (_) { throw new Error('That Setup code is not valid'); }
  const split = decoded.indexOf('|');
  if (split < 1) throw new Error('That Setup code is not valid');
  const site = decoded.slice(0, split).replace(/\/$/, '');
  const token = decoded.slice(split + 1);
  let url;
  try { url = new URL(site); } catch (_) {
    throw new Error('That Setup code has an invalid site address');
  }
  if (url.protocol !== 'https:' && !site.startsWith('http://127.0.0.1')) {
    throw new Error('The AutoEditor site must use HTTPS');
  }
  if (site !== url.origin) {
    throw new Error('That Setup code has an invalid site address');
  }
  if (url.hostname !== '127.0.0.1' && !ALLOWED_SITE_HOSTS.has(url.hostname)) {
    throw new Error('That Setup code is not from the official AutoEditor website');
  }
  if (!/^[A-Za-z0-9_-]{16,200}$/.test(token)) {
    throw new Error('That Setup code has an invalid personal token');
  }
  return { site, token };
}

module.exports = { ALLOWED_SITE_HOSTS, decodeSetupCode };
