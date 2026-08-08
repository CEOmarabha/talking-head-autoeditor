!macro customUnInstall
  # nsis-web retains package.7z for updater reuse. A real uninstall should
  # remove the multi-gigabyte runtime cache, while an in-place update must keep
  # it available for the replacement install.
  ${ifNot} ${isUpdated}
    Delete "$LOCALAPPDATA\${APP_PACKAGE_STORE_FILE}"
    RMDir "$LOCALAPPDATA\autoeditor-desktop-updater"
  ${endIf}
!macroend
