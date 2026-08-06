/** Notarize the mac build when Apple credentials are present; skip quietly
 * when they are not (unsigned local/dev builds stay possible). */
exports.default = async function notarize(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const { APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID } =
    process.env;
  if (!APPLE_ID || !APPLE_APP_SPECIFIC_PASSWORD || !APPLE_TEAM_ID) {
    console.log('notarize: Apple credentials not set, skipping');
    return;
  }
  const { notarize } = require('@electron/notarize');
  const appName = context.packager.appInfo.productFilename;
  await notarize({
    appPath: `${context.appOutDir}/${appName}.app`,
    appleId: APPLE_ID,
    appleIdPassword: APPLE_APP_SPECIFIC_PASSWORD,
    teamId: APPLE_TEAM_ID,
  });
};
