/** Product identity: one shared codebase, two release channels.
 *
 * PRODUCT=ryan  -> "Ryan Reels Editor"  (ryan_duffy, ryan_humes, shared_skit)
 * PRODUCT=pse   -> "PSE AutoEditor"     (pse)
 *
 * CI stamps the resolved identity and architecture-specific update channel
 * into product.json. The packaged app reads that file from resources.
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
