const fs = require('fs');
const path = require('path');

function csvCell(value) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function writeClipCatalog(files, workDir) {
  const catalog = path.join(workDir, 'selected-footage.csv');
  const rows = ['path,scene_family,duration_sec,rating'];
  for (const file of files) {
    const family = path.parse(file).name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'selected_footage';
    rows.push([
      csvCell(file), csvCell(family), '', csvCell('KEEP'),
    ].join(','));
  }
  fs.writeFileSync(catalog, `${rows.join('\n')}\n`, { mode: 0o600 });
  return catalog;
}

module.exports = { csvCell, writeClipCatalog };
