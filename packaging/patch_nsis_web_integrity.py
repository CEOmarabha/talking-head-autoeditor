#!/usr/bin/env python3
"""Fail-closed hardening for electron-builder 26.15.3 NSIS web installs.

The locked upstream template hashes an adjacent package, but it neither hashes
an explicitly supplied package nor the package returned by INetC. We patch the
exact audited templates after ``npm ci`` so every path is checked against the
SHA-512 embedded by electron-builder before extraction. The downloader is also
renamed to a uniquely staged INetC 1.0.5.7 plug-in that fixes progress for
packages larger than 2 GiB.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ELECTRON_BUILDER_VERSION = "26.15.3"
INETC_SHA256 = "83005624a3c515e8e4454a416693ba0fbf384ff5ea0e1471f520dfae790d4ab7"
ORIGINAL_HASHES = {
    "installer.nsh": "0e319437dd01dcbf911f3f48f664fde0cefbaef704f1cdb1739f63d563f5d4a0",
    "webPackage.nsh": "2c0c0ab1ce525caf6ef908502d3ec007430986c3022c3987ccfaf021ddabe7b1",
}
PATCHED_HASHES = {
    "installer.nsh": "6a026f48f4634da65ef1b24921a3a450f6b2e206dc8da3d1d3b6ad06f5c07005",
    "webPackage.nsh": "69d65a4280e7a9440cc798f3208e7f93acdcc2516bbda2ee52dc1e15b4fc95e1",
}

INSTALLER_ORIGINAL = '''      fun_extract:
        !insertmacro extractUsing7za "$packageFile"
'''
INSTALLER_PATCHED = '''      fun_extract:
        # electron-builder 26.15.3 does not verify downloaded or explicit
        # web packages. AutoEditor requires the embedded x64 SHA-512 before
        # any package bytes are extracted.
        !ifndef APP_64_HASH
          !error "AutoEditor Helper web installer requires an x64 package hash"
        !endif
        StrCpy $1 "${APP_64_HASH}"
        ${StdUtils.HashFile} $3 "SHA2-512" "$packageFile"
        ${if} $3 != $1
          MessageBox MB_OK|MB_ICONSTOP "The AutoEditor runtime package failed its security check. Nothing was installed." /SD IDOK
          SetErrorLevel 3
          Quit
        ${endif}
        !insertmacro extractUsing7za "$packageFile"
'''


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{label} is missing: {path}")
    actual = sha256(path)
    if actual != expected:
        raise SystemExit(
            f"{label} digest drifted: expected {expected}, found {actual}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-modules", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    args = parser.parse_args()

    package = args.node_modules / "app-builder-lib" / "package.json"
    try:
        import json
        installed_version = json.loads(package.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot identify installed app-builder-lib: {exc}") from exc
    if installed_version != ELECTRON_BUILDER_VERSION:
        raise SystemExit(
            "app-builder-lib moved from the audited electron-builder version: "
            f"{installed_version} != {ELECTRON_BUILDER_VERSION}"
        )
    require_hash(args.plugin, INETC_SHA256, "AutoEditor INetC 1.0.5.7 plug-in")

    templates = args.node_modules / "app-builder-lib" / "templates" / "nsis" / "include"
    installer = templates / "installer.nsh"
    web_package = templates / "webPackage.nsh"
    require_hash(installer, ORIGINAL_HASHES[installer.name], "locked installer.nsh")
    require_hash(web_package, ORIGINAL_HASHES[web_package.name], "locked webPackage.nsh")

    installer_text = installer.read_text(encoding="utf-8")
    if installer_text.count(INSTALLER_ORIGINAL) != 1:
        raise SystemExit("electron-builder installer extraction hook drifted")
    installer.write_bytes(
        installer_text.replace(INSTALLER_ORIGINAL, INSTALLER_PATCHED).encode(
            "utf-8"
        )
    )
    web_text = web_package.read_text(encoding="utf-8")
    if web_text.count("inetc::get") != 2:
        raise SystemExit("electron-builder INetC call sites drifted")
    web_package.write_bytes(
        web_text.replace("inetc::get", "AutoEditorINetC::get").encode(
            "utf-8"
        )
    )
    require_hash(installer, PATCHED_HASHES[installer.name], "patched installer.nsh")
    require_hash(web_package, PATCHED_HASHES[web_package.name], "patched webPackage.nsh")
    print("electron-builder NSIS web integrity patch verified")


if __name__ == "__main__":
    main()
