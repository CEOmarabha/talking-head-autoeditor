#!/usr/bin/env python3
"""Stage the immutable large-file NSIS web downloader and its notices."""
from __future__ import annotations

import argparse
import hashlib
import tempfile
import urllib.request
import zipfile
from pathlib import Path


INETC_VERSION = "1.0.5.7"
INETC_COMMIT = "447625a39809f1df19ddeba9cb1c30e26ca741be"
INETC_ARCHIVE_URL = (
    "https://github.com/DigitalMediaServer/NSIS-INetC-plugin/"
    "releases/download/v1.0.5.7/InetC.zip"
)
INETC_ARCHIVE_SHA256 = (
    "b01077e56ebb19c005b45d40f837958ca6a92f51a5a937dc1bb497c7c7f2aa93"
)
INETC_DLL_MEMBER = "x86-unicode/INetC.dll"
INETC_DLL_SHA256 = (
    "83005624a3c515e8e4454a416693ba0fbf384ff5ea0e1471f520dfae790d4ab7"
)
INETC_LICENSE_URL = (
    "https://raw.githubusercontent.com/DigitalMediaServer/"
    f"NSIS-INetC-plugin/{INETC_COMMIT}/LICENSE.md"
)
INETC_LICENSE_SHA256 = (
    "c5ee66863fcea719d3b4badeb81fcf0021796b693b4b8b3821d9ce53e447cdf3"
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_digest(data: bytes, expected: str, label: str) -> None:
    actual = digest(data)
    if actual != expected:
        raise SystemExit(
            f"{label} digest drifted: expected {expected}, found {actual}"
        )


def download(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "AutoEditor-Helper-release-build/1"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def stage(
    archive: bytes,
    license_text: bytes,
    build_resources: Path,
    licenses: Path,
) -> None:
    require_digest(archive, INETC_ARCHIVE_SHA256, "INetC release archive")
    require_digest(license_text, INETC_LICENSE_SHA256, "INetC license")
    with tempfile.TemporaryDirectory() as temporary:
        archive_path = Path(temporary) / "InetC.zip"
        archive_path.write_bytes(archive)
        try:
            with zipfile.ZipFile(archive_path) as bundle:
                names = bundle.namelist()
                if names.count(INETC_DLL_MEMBER) != 1:
                    raise SystemExit("INetC archive has no unique x86 Unicode plug-in")
                plugin = bundle.read(INETC_DLL_MEMBER)
        except zipfile.BadZipFile as exc:
            raise SystemExit(f"INetC release archive is invalid: {exc}") from exc
    require_digest(plugin, INETC_DLL_SHA256, "INetC x86 Unicode plug-in")
    plugin_dir = build_resources / "x86-unicode"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "AutoEditorINetC.dll").write_bytes(plugin)
    licenses.mkdir(parents=True, exist_ok=True)
    (licenses / "AutoEditor-INetC-Zlib-LICENSE.md").write_bytes(license_text)
    (licenses / "NSIS_WEB_DOWNLOADER.txt").write_text(
        "\n".join((
            f"name=INetC {INETC_VERSION}",
            f"source_commit={INETC_COMMIT}",
            f"archive_url={INETC_ARCHIVE_URL}",
            f"archive_sha256={INETC_ARCHIVE_SHA256}",
            f"plugin_member={INETC_DLL_MEMBER}",
            f"plugin_sha256={INETC_DLL_SHA256}",
            f"license_url={INETC_LICENSE_URL}",
            f"license_sha256={INETC_LICENSE_SHA256}",
            "purpose=NSIS web runtime download with corrected over-2-GiB progress",
        )) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-resources", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    args = parser.parse_args()
    stage(
        download(INETC_ARCHIVE_URL),
        download(INETC_LICENSE_URL),
        args.build_resources,
        args.licenses,
    )
    print("INetC 1.0.5.7 large-file downloader staged and verified")


if __name__ == "__main__":
    main()
