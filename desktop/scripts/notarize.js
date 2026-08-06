/** Ad-hoc sign acceptance builds, or notarize Developer ID builds. */
exports.default = async function notarize(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const appName = context.packager.appInfo.productFilename;
  const appPath = `${context.appOutDir}/${appName}.app`;
  const { APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID } =
    process.env;
  if (!process.env.CSC_LINK) {
    // Electron's main executable arrives linker-signed. Once resources are
    // added, leaving that partial signature in place makes macOS call the app
    // damaged. Seal the complete acceptance build ad hoc instead.
    const { execFileSync } = require('child_process');
    execFileSync('/usr/bin/xattr', ['-cr', appPath]);
    execFileSync('/usr/bin/codesign', [
      '--force', '--deep', '--sign', '-',
      '--entitlements', `${__dirname}/../build/entitlements.mac.plist`,
      appPath,
    ], { stdio: 'inherit' });
    console.log('sign: ad-hoc acceptance build sealed');
    console.log('notarize: Developer ID certificate not set, skipping');
    return;
  }
  if (!APPLE_ID || !APPLE_APP_SPECIFIC_PASSWORD || !APPLE_TEAM_ID) {
    console.log('notarize: Apple credentials not set, skipping');
    return;
  }
  const { notarize } = require('@electron/notarize');
  await notarize({
    appPath,
    appleId: APPLE_ID,
    appleIdPassword: APPLE_APP_SPECIFIC_PASSWORD,
    teamId: APPLE_TEAM_ID,
  });
};
