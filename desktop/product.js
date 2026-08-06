/** Product identity: one shared codebase, two release channels.
 *
 * PRODUCT=ryan  -> "Ryan Reels Editor"  (ryan_duffy, ryan_humes, shared_skit)
 * PRODUCT=pse   -> "PSE AutoEditor"     (pse)
 *
 * At build time electron-builder reads this via electron-builder.yml env
 * interpolation; at runtime the packaged app reads product.json placed in
 * resources by the build.
 */
const fs = require('fs');
const path = require('path');

const PRODUCTS = {
  ryan: {
    id: 'ryan',
    name: 'Ryan Reels Editor',
    appId: 'com.marabha.ryanreels',
    profiles: ['ryan_duffy', 'ryan_humes', 'shared_skit'],
    channel: 'ryan',
    tagline: 'Drop clips. Get a finished reel.'
  },
  pse: {
    id: 'pse',
    name: 'PSE AutoEditor',
    appId: 'com.marabha.pseautoeditor',
    profiles: ['pse'],
    channel: 'pse',
    tagline: 'Verified talking-head edits.'
  }
};

function resolveProduct(resourcesPath) {
  // packaged: product.json is stamped into resources at build time
  try {
    const p = path.join(resourcesPath, 'product.json');
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (_) { /* fall through */ }
  return PRODUCTS[process.env.PRODUCT || 'ryan'];
}

module.exports = { PRODUCTS, resolveProduct };
