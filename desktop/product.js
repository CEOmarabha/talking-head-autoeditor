/** Product identity for the legacy PSE desktop channel.
 *
 * Friends use the generic AutoEditor Helper product. The old creator-specific
 * channel is retired so a local build cannot silently
 * ship somebody else's name or profiles. PSE remains separate from the same
 * codebase and CI stamps its identity into product.json.
 */
const fs = require('fs');
const path = require('path');

const PRODUCTS = {
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
  return PRODUCTS[process.env.PRODUCT || 'pse'];
}

module.exports = { PRODUCTS, resolveProduct };
