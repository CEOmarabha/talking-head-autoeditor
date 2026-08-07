/** Notarize and staple final DMG artifacts after electron-builder creates them. */
exports.default = async function notarizeArtifacts(context) {
  if (process.platform !== 'darwin') return [];
  const { APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID, CSC_LINK } =
    process.env;
  if (!CSC_LINK || !APPLE_ID || !APPLE_APP_SPECIFIC_PASSWORD || !APPLE_TEAM_ID) {
    console.log('notarize artifacts: signing credentials not set, skipping');
    return [];
  }
  const { notarize } = require('@electron/notarize');
  for (const artifactPath of context.artifactPaths || []) {
    if (!artifactPath.endsWith('.dmg')) continue;
    await notarize({
      appPath: artifactPath,
      appleId: APPLE_ID,
      appleIdPassword: APPLE_APP_SPECIFIC_PASSWORD,
      teamId: APPLE_TEAM_ID,
    });
  }
  return [];
};
