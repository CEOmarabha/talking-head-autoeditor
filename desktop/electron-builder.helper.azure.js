/** Tagged Windows releases use Microsoft Azure Artifact Signing. */
const required = [
  'WIN_AZURE_PUBLISHER_NAME',
  'WIN_AZURE_ENDPOINT',
  'WIN_AZURE_CERTIFICATE_PROFILE_NAME',
  'WIN_AZURE_CODE_SIGNING_ACCOUNT_NAME',
];

for (const name of required) {
  if (!process.env[name]) throw new Error(`${name} is required for Windows signing`);
}

module.exports = {
  extends: './electron-builder.helper.yml',
  forceCodeSigning: true,
  win: {
    azureSignOptions: {
      publisherName: process.env.WIN_AZURE_PUBLISHER_NAME,
      endpoint: process.env.WIN_AZURE_ENDPOINT,
      certificateProfileName: process.env.WIN_AZURE_CERTIFICATE_PROFILE_NAME,
      codeSigningAccountName: process.env.WIN_AZURE_CODE_SIGNING_ACCOUNT_NAME,
      fileDigest: 'SHA256',
      timestampDigest: 'SHA256',
      timestampRfc3161: 'http://timestamp.acs.microsoft.com',
    },
  },
};
