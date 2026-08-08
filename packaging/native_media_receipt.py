#!/usr/bin/env python3
"""Inventory native media binaries in a final installed application tree.

The allowlist defines explicit app-relative directories to scan. Every real PE
or Mach-O file found recursively below those roots must appear in the allowlist,
and every allowlisted file must be found. The receipt binds source-lineage
metadata to the final installed bytes. This module records technical provenance
only; it makes no licensing or legal-compliance determination. A caller-supplied
allowlist digest proves equality to that allowlist only. The release workflow
must independently authenticate every referenced source manifest and signed
attestation before trusting the resulting receipt. POSIX scans use held
directory descriptors and openat-style calls. Windows scans hold no-delete
Win32 handles, reject reparse points, and hash through the same file handles
used for classification. No path-based traversal fallback is allowed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
import unicodedata
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, Iterator


ALLOWLIST_SCHEMA = "autoeditor-native-media-allowlist/v1"
RECEIPT_SCHEMA = "autoeditor-native-media-receipt/v1"
CPU_TYPE_X86_64 = 0x01000007
CPU_TYPE_ARM64 = 0x0100000C
CPU_ARCH_ABI64 = 0x01000000
PE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_EXECUTABLE_IMAGE = 0x0002
IMAGE_FILE_DLL = 0x2000
IMAGE_SCN_CNT_CODE = 0x00000020
IMAGE_SCN_MEM_EXECUTE = 0x20000000
MH_EXECUTE = 0x2
MH_DYLIB = 0x6
MH_BUNDLE = 0x8
LC_SEGMENT = 0x1
LC_SEGMENT_64 = 0x19
VM_PROT_EXECUTE = 0x4
MAX_PE_HEADER_OFFSET = 16 * 1024 * 1024
MAX_MACH_LOAD_COMMANDS = 65_535
SHA256_RE = re.compile(r"[a-f0-9]{64}")
LINEAGE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+,-]{0,255}")
FORBIDDEN_PATH_CHARS = frozenset('<>:"\\|?*')
WINDOWS_RESERVED_NAMES = {
    "aux", "con", "nul", "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
POSIX_HANDLE_APIS_AVAILABLE = (
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.listdir in os.supports_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)
REQUIRED_COMPONENTS = frozenset({
    "main-ffmpeg",
    "remotion",
    "onnxruntime-node",
    "electron",
    "browser",
    "frozen-engine",
    "frozen-helper",
})
OPTIONAL_COMPONENTS = frozenset({"supporting-native"})
COMPONENTS = REQUIRED_COMPONENTS | OPTIONAL_COMPONENTS

PYAV_NATIVE_NAME = re.compile(
    r"^(?:lib)?(?:avcodec|avdevice|avfilter|avformat|avutil|postproc|"
    r"swresample|swscale)(?:[.\-]|$)",
    re.IGNORECASE,
)
PYAV_METADATA_NAME = re.compile(r"^av-[^/]+\.dist-info$", re.IGNORECASE)

PLATFORM_RULES = {
    "windows-x64": {
        "core": (
            "resources/bin/ffmpeg.exe",
            "resources/bin/ffprobe.exe",
        ),
        "format": "pe",
        "machine": PE_MACHINE_AMD64,
    },
    "mac-arm64": {
        "core": (
            "Contents/Resources/bin/ffmpeg",
            "Contents/Resources/bin/ffprobe",
        ),
        "format": "macho",
        "machine": CPU_TYPE_ARM64,
    },
    "mac-x64": {
        "core": (
            "Contents/Resources/bin/ffmpeg",
            "Contents/Resources/bin/ffprobe",
        ),
        "format": "macho",
        "machine": CPU_TYPE_X86_64,
    },
}

REMOTION_VERSION = "4.0.507"
HYPERFRAMES_VERSION = "0.7.99"
CHROME_HEADLESS_SHELL_VERSION = "152.0.7928.2"

WINDOWS_REMOTION_NATIVE_NAMES = (
    "avcodec-61.dll",
    "avdevice-61.dll",
    "avfilter-10.dll",
    "avformat-61.dll",
    "avutil-59.dll",
    "ffmpeg.exe",
    "ffprobe.exe",
    "libgcc_s_seh-1.dll",
    "libssp-0.dll",
    "libstdc++-6.dll",
    "libvpx-1.dll",
    "libwinpthread-1.dll",
    "msvcr100.dll",
    "remotion.exe",
    "swresample-5.dll",
    "swscale-8.dll",
    "zlib1.dll",
)

WINDOWS_REMOTION_STALE_NATIVE_SHA256 = {
    "avcodec-60.dll": (
        "b65d252925037d170803a16cdab1391acb3a9179cd5f93e47f31eefbce535f5d"
    ),
    "avdevice-60.dll": (
        "bb17bd3d39856f6c8940e86bc7336ab09151f17cac4a52eb0c5679ea3c171d46"
    ),
    "avfilter-9.dll": (
        "ddeb084f55d2f5c9d3d33d0b5b238d3d66ab83744a853daada3bd6b1d0f765ba"
    ),
    "avformat-60.dll": (
        "0694f8549b8d56125150dfacc70d0f27ab199a1179055b43b7c386a381106a52"
    ),
    "avutil-58.dll": (
        "71d5c71fab96ab66f0826a310418e010f796dc1c88d5c48d233cad080c5f0c40"
    ),
    "swresample-4.dll": (
        "31f08bd1b0996ec52a96b9dac6786289559f6b29902cc2ec455fdb7bd35f4ec0"
    ),
    "swscale-7.dll": (
        "1f96a24e81da9fe32d35d3db9780fcdd4048d5c62b0cb2795cf7c95975f40326"
    ),
}
REMOTION_PRUNE_RECEIPT_PATH = (
    "resources/licenses/REMOTION_WINDOWS_RUNTIME_PRUNE.json"
)
REMOTION_PRUNE_RECEIPT_SCHEMA = (
    "autoeditor-remotion-windows-runtime-prune/v1"
)
REMOTION_PACKAGE_NAME = "@remotion/compositor-win32-x64-msvc"
REMOTION_PACKAGE_RESOLVED = (
    "https://registry.npmjs.org/@remotion/compositor-win32-x64-msvc/-/"
    "compositor-win32-x64-msvc-4.0.507.tgz"
)
REMOTION_PACKAGE_INTEGRITY = (
    "sha512-FCkZDLcPBCO2WO/MyrtMB5tpsIuqqkc7E1nY2lfY6WmRX2quGfykcsz4S9inYx/"
    "G+XybKVTgplqnyLtt9wyFnw=="
)
REMOTION_PACKAGE_TARBALL_SHA256 = (
    "f0e006a1b84d7ac3caf6970ea6cfa4c0419371db230a2bd593996e86db197749"
)
REMOTION_INVENTORY_SHA256_BEFORE = (
    "e5b4f09e8d99068895da30a4d74f4c24ce82ece9869bfdd7bf62fe48aae3f47f"
)
REMOTION_INVENTORY_SHA256_AFTER = (
    "77976da929c0744b4503720c070f441702522f30a9ba3c6dacf6abcf70d123f1"
)
REMOTION_ACTIVE_PE_IMPORTS = {
    "ffmpeg.exe": (
        "avcodec-61.dll", "avdevice-61.dll", "avfilter-10.dll",
        "avformat-61.dll", "avutil-59.dll", "kernel32.dll",
        "libgcc_s_seh-1.dll", "libwinpthread-1.dll", "msvcrt.dll",
        "psapi.dll", "shell32.dll", "swresample-5.dll", "swscale-8.dll",
    ),
    "ffprobe.exe": (
        "avcodec-61.dll", "avdevice-61.dll", "avfilter-10.dll",
        "avformat-61.dll", "avutil-59.dll", "kernel32.dll",
        "libwinpthread-1.dll", "msvcrt.dll", "shell32.dll",
        "swresample-5.dll", "swscale-8.dll",
    ),
    "remotion.exe": (
        "api-ms-win-core-synch-l1-2-0.dll",
        "api-ms-win-crt-environment-l1-1-0.dll",
        "api-ms-win-crt-heap-l1-1-0.dll",
        "api-ms-win-crt-math-l1-1-0.dll",
        "api-ms-win-crt-private-l1-1-0.dll",
        "api-ms-win-crt-runtime-l1-1-0.dll",
        "api-ms-win-crt-stdio-l1-1-0.dll",
        "api-ms-win-crt-string-l1-1-0.dll",
        "api-ms-win-crt-time-l1-1-0.dll",
        "avcodec-61.dll", "avdevice-61.dll", "avfilter-10.dll",
        "avformat-61.dll", "avutil-59.dll", "bcryptprimitives.dll",
        "kernel32.dll", "msvcrt.dll", "ntdll.dll", "pdh.dll",
        "swscale-8.dll",
    ),
}

# Frozen verifier seam copied from packaging/prune_onnxruntime_node.py at
# exact commit 68719fe31df8454a9fecaaa967c8687f2e5df200. That pruner is not on the
# current main branch yet. Keep the comparison regression in
# tests/test_native_media_receipt.py so this mirror cannot silently drift once
# the producer lands.
ONNX_CONTRACT_SOURCE_COMMIT = "68719fe31df8454a9fecaaa967c8687f2e5df200"
ONNX_PRUNE_RECEIPT_SCHEMA = "autoeditor-onnxruntime-node-target-prune/v2"
ONNX_PACKAGE_NAME = "onnxruntime-node"
ONNX_PACKAGE_VERSION = "1.21.1"
ONNX_PACKAGE_INTEGRITY = (
    "sha512-YThL/YYeGAeytecOvRcTKUORTIE2f8/iSo/JZgHFawWrV4zOY7fWLEaNuscg"
    "jmY5C5/VE/Wr7tm+ucSsc/AysQ=="
)
ONNX_PRUNE_RECEIPT_FILENAME = "ONNXRUNTIME_NODE_TARGET_PRUNE.json"
ONNX_TARGET_DIRECTORIES = {
    "mac-arm64": "darwin/arm64",
    "mac-x64": "darwin/x64",
    "windows-x64": "win32/x64",
}
ONNX_RECEIPT_TARGETS = {
    "mac-arm64": {"os": "mac", "arch": "arm64"},
    "mac-x64": {"os": "mac", "arch": "x64"},
    "windows-x64": {"os": "windows", "arch": "x64"},
}
ONNX_NATIVE_INVENTORY = {
    "darwin/arm64/libonnxruntime.1.21.1.dylib": (
        "2ea5e7f4202bfa9e0cfe4822576d8a7bb71e430a57c84decb7c4830dea4337ef"
    ),
    "darwin/arm64/onnxruntime_binding.node": (
        "d748eb499784a400e4c4ee5932e61a79d5cbb6fde26382fe3fb62aeeda3a9dd4"
    ),
    "darwin/x64/libonnxruntime.1.21.1.dylib": (
        "f5044fa26473f312af7222b9c85410a72488848b3667b1cfaf8f92d271a81990"
    ),
    "darwin/x64/onnxruntime_binding.node": (
        "f1263de9f95174584f0f035adbe530790d7914f81a06e50f3494e70c344c34b4"
    ),
    "linux/arm64/libonnxruntime.so.1": (
        "2dba27b484f8171f9fd39182230b4ace5f85401114d65a53c767ee924284806b"
    ),
    "linux/arm64/libonnxruntime.so.1.21.1": (
        "2dba27b484f8171f9fd39182230b4ace5f85401114d65a53c767ee924284806b"
    ),
    "linux/arm64/onnxruntime_binding.node": (
        "c1af123e973aa95b71df207e79a0ce63def9b2b8a0e6f384a8c4455c64d5b1a8"
    ),
    "linux/x64/libonnxruntime.so.1": (
        "3d03e6de8f828ae7432e67764ab4c02d4c9d4804db1b46ad60484c46188bb144"
    ),
    "linux/x64/libonnxruntime.so.1.21.1": (
        "3d03e6de8f828ae7432e67764ab4c02d4c9d4804db1b46ad60484c46188bb144"
    ),
    "linux/x64/libonnxruntime_providers_shared.so": (
        "950dbbe7c7a6f73b7f574c0e2308417e1e90e1f73b6472d799e25b47c6fdee82"
    ),
    "linux/x64/onnxruntime_binding.node": (
        "61278544b4668a50a481b8a451cbd8f7627e2006b2b54cd9a96438dff24b67da"
    ),
    "win32/arm64/DirectML.dll": (
        "77b0db83ff903f2323f5caf538499d75af6038bbea23b7959f7d232d9a4ab9d4"
    ),
    "win32/arm64/onnxruntime.dll": (
        "705d445a93d59db8f3ac540e9c94d9498a7399bca90047fc9ca18cc87f6c0af2"
    ),
    "win32/arm64/onnxruntime_binding.node": (
        "401a1a66a9f01237c7b60340554ed3e65a8cd88402f72260fa0c14d348491de9"
    ),
    "win32/x64/DirectML.dll": (
        "9c9e6d822561c6c41b90e6994b3e8857cf1d66dbfb1e0c4c799c7c89b4e92da1"
    ),
    "win32/x64/onnxruntime.dll": (
        "253cdf35f87692394205b01d8b6430f7926479bde557200f98d08193e8160a82"
    ),
    "win32/x64/onnxruntime_binding.node": (
        "9f3026a462fb77d9f5866680209dd683ee51f6fbf8967da7770e154c395f73ef"
    ),
}

PYAV_COMPONENT_ROOTS = {
    "windows-x64": (
        "resources/engine/_internal/av",
        "resources/engine/_internal/av.libs",
        "resources/helper/_internal/av",
        "resources/helper/_internal/av.libs",
    ),
    "mac-arm64": (
        "Contents/Resources/engine/_internal/av",
        "Contents/Resources/engine/_internal/av.libs",
        "Contents/Resources/helper/_internal/av",
        "Contents/Resources/helper/_internal/av.libs",
    ),
    "mac-x64": (
        "Contents/Resources/engine/_internal/av",
        "Contents/Resources/engine/_internal/av.libs",
        "Contents/Resources/helper/_internal/av",
        "Contents/Resources/helper/_internal/av.libs",
    ),
}

MANDATORY_SCAN_PATHS = {
    "windows-x64": ("resources/engine", "resources/helper"),
    "mac-arm64": (
        "Contents/Resources/engine",
        "Contents/Resources/helper",
    ),
    "mac-x64": (
        "Contents/Resources/engine",
        "Contents/Resources/helper",
    ),
}
FROZEN_RUNTIME_PATHS = {
    "windows-x64": {
        "frozen-engine": "resources/engine/autoeditor-engine.exe",
        "frozen-helper": "resources/helper/autoeditor-helper-daemon.exe",
    },
    "mac-arm64": {
        "frozen-engine": "Contents/Resources/engine/autoeditor-engine",
        "frozen-helper": (
            "Contents/Resources/helper/autoeditor-helper-daemon"
        ),
    },
    "mac-x64": {
        "frozen-engine": "Contents/Resources/engine/autoeditor-engine",
        "frozen-helper": (
            "Contents/Resources/helper/autoeditor-helper-daemon"
        ),
    },
}
MAC_REMOTION_NATIVE_NAMES = (
    "ffmpeg",
    "ffprobe",
    "libavcodec.dylib",
    "libavdevice.dylib",
    "libavfilter.dylib",
    "libavformat.dylib",
    "libavutil.dylib",
    "libswresample.dylib",
    "libswscale.dylib",
    "remotion",
)
MAC_MAIN_FFMPEG_LIBRARY_NAMES = (
    "libavcodec.62.28.102.dylib",
    "libavdevice.62.3.102.dylib",
    "libavfilter.11.14.102.dylib",
    "libavformat.62.12.102.dylib",
    "libavutil.60.26.102.dylib",
    "libswresample.6.3.102.dylib",
    "libswscale.9.5.102.dylib",
)


def _under(relative: str, root: str) -> bool:
    return relative.startswith(root + "/")


def _component_rules() -> dict[str, dict[str, dict[str, Any]]]:
    windows_remotion_root = (
        "resources/creative-runtime/node_modules/@remotion/"
        "compositor-win32-x64-msvc"
    )
    mac_arm_remotion_root = (
        "Contents/Resources/creative-runtime/node_modules/@remotion/"
        "compositor-darwin-arm64"
    )
    mac_x64_remotion_root = (
        "Contents/Resources/creative-runtime/node_modules/@remotion/"
        "compositor-darwin-x64"
    )
    windows_browser_root = (
        "resources/browser/chrome-headless-shell-win64"
    )
    mac_browser_root = (
        "Contents/Resources/browser/chrome-headless-shell-mac"
    )
    windows_onnx_root = (
        "resources/creative-runtime/node_modules/onnxruntime-node"
    )
    mac_onnx_root = (
        "Contents/Resources/creative-runtime/node_modules/onnxruntime-node"
    )

    def prefixed(root: str, names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(f"{root}/{name}" for name in names)

    def onnx_paths(platform: str, root: str) -> tuple[str, ...]:
        target = ONNX_TARGET_DIRECTORIES[platform]
        return tuple(
            f"{root}/bin/napi-v3/{relative}"
            for relative in sorted(ONNX_NATIVE_INVENTORY)
            if relative.startswith(target + "/")
        )

    return {
        "windows-x64": {
            "main-ffmpeg": {
                "required_all": PLATFORM_RULES["windows-x64"]["core"],
                "lineage_id": (
                    "autoeditor:ffmpeg-source-build-v1:windows-x64"
                ),
            },
            "remotion": {
                "roots": (windows_remotion_root,),
                "required_all": prefixed(
                    windows_remotion_root, WINDOWS_REMOTION_NATIVE_NAMES
                ),
                "allowed_all": prefixed(
                    windows_remotion_root, WINDOWS_REMOTION_NATIVE_NAMES
                ),
                "lineage_id": (
                    "npm:@remotion/compositor-win32-x64-msvc@4.0.507"
                ),
            },
            "onnxruntime-node": {
                "roots": (windows_onnx_root,),
                "scan_entire_roots": True,
                "required_all": onnx_paths(
                    "windows-x64", windows_onnx_root
                ),
                "allowed_all": onnx_paths(
                    "windows-x64", windows_onnx_root
                ),
                "lineage_id": "npm:onnxruntime-node@1.21.1:win32-x64",
            },
            "electron": {
                "required_all": ("ffmpeg.dll",),
                "allowed_all": ("ffmpeg.dll",),
                "lineage_id": "npm:electron@43.3.0:windows-x64",
            },
            "browser": {
                "roots": (windows_browser_root,),
                "required_all": (
                    f"{windows_browser_root}/chrome-headless-shell.exe",
                ),
                "lineage_id": (
                    "hyperframes@0.7.99:chrome-headless-shell@"
                    "152.0.7928.2:windows-x64"
                ),
            },
            "frozen-engine": {
                "required_all": (
                    FROZEN_RUNTIME_PATHS["windows-x64"]["frozen-engine"],
                ),
                "lineage_id": "autoeditor:pyinstaller-engine:v1:windows-x64",
            },
            "frozen-helper": {
                "required_all": (
                    FROZEN_RUNTIME_PATHS["windows-x64"]["frozen-helper"],
                ),
                "lineage_id": "autoeditor:pyinstaller-helper:v1:windows-x64",
            },
        },
        "mac-arm64": {
            "main-ffmpeg": {
                "required_all": (
                    *PLATFORM_RULES["mac-arm64"]["core"],
                    *prefixed(
                        "Contents/Resources/lib",
                        MAC_MAIN_FFMPEG_LIBRARY_NAMES,
                    ),
                ),
                "lineage_id": "homebrew:ffmpeg@8.1.2_1:mac-arm64",
            },
            "remotion": {
                "roots": (mac_arm_remotion_root,),
                "required_all": prefixed(
                    mac_arm_remotion_root, MAC_REMOTION_NATIVE_NAMES
                ),
                "allowed_all": prefixed(
                    mac_arm_remotion_root, MAC_REMOTION_NATIVE_NAMES
                ),
                "lineage_id": (
                    "npm:@remotion/compositor-darwin-arm64@4.0.507"
                ),
            },
            "onnxruntime-node": {
                "roots": (mac_onnx_root,),
                "scan_entire_roots": True,
                "required_all": onnx_paths("mac-arm64", mac_onnx_root),
                "allowed_all": onnx_paths("mac-arm64", mac_onnx_root),
                "lineage_id": "npm:onnxruntime-node@1.21.1:darwin-arm64",
            },
            "electron": {
                "required_all": (
                    "Contents/Frameworks/Electron Framework.framework/Versions/"
                    "A/Libraries/libffmpeg.dylib",
                ),
                "lineage_id": "npm:electron@43.3.0:mac-arm64",
            },
            "browser": {
                "roots": (mac_browser_root,),
                "required_all": (
                    f"{mac_browser_root}/chrome-headless-shell",
                ),
                "lineage_id": (
                    "hyperframes@0.7.99:chrome-headless-shell@"
                    "152.0.7928.2:mac-arm64"
                ),
            },
            "frozen-engine": {
                "required_all": (
                    FROZEN_RUNTIME_PATHS["mac-arm64"]["frozen-engine"],
                ),
                "lineage_id": "autoeditor:pyinstaller-engine:v1:mac-arm64",
            },
            "frozen-helper": {
                "required_all": (
                    FROZEN_RUNTIME_PATHS["mac-arm64"]["frozen-helper"],
                ),
                "lineage_id": "autoeditor:pyinstaller-helper:v1:mac-arm64",
            },
        },
        "mac-x64": {
            "main-ffmpeg": {
                "required_all": (
                    *PLATFORM_RULES["mac-x64"]["core"],
                    *prefixed(
                        "Contents/Resources/lib",
                        MAC_MAIN_FFMPEG_LIBRARY_NAMES,
                    ),
                ),
                "lineage_id": "homebrew:ffmpeg@8.1.2_1:mac-x64",
            },
            "remotion": {
                "roots": (mac_x64_remotion_root,),
                "required_all": prefixed(
                    mac_x64_remotion_root, MAC_REMOTION_NATIVE_NAMES
                ),
                "allowed_all": prefixed(
                    mac_x64_remotion_root, MAC_REMOTION_NATIVE_NAMES
                ),
                "lineage_id": (
                    "npm:@remotion/compositor-darwin-x64@4.0.507"
                ),
            },
            "onnxruntime-node": {
                "roots": (mac_onnx_root,),
                "scan_entire_roots": True,
                "required_all": onnx_paths("mac-x64", mac_onnx_root),
                "allowed_all": onnx_paths("mac-x64", mac_onnx_root),
                "lineage_id": "npm:onnxruntime-node@1.21.1:darwin-x64",
            },
            "electron": {
                "required_all": (
                    "Contents/Frameworks/Electron Framework.framework/Versions/"
                    "A/Libraries/libffmpeg.dylib",
                ),
                "lineage_id": "npm:electron@43.3.0:mac-x64",
            },
            "browser": {
                "roots": (mac_browser_root,),
                "required_all": (
                    f"{mac_browser_root}/chrome-headless-shell",
                ),
                "lineage_id": (
                    "hyperframes@0.7.99:chrome-headless-shell@"
                    "152.0.7928.2:mac-x64"
                ),
            },
            "frozen-engine": {
                "required_all": (
                    FROZEN_RUNTIME_PATHS["mac-x64"]["frozen-engine"],
                ),
                "lineage_id": "autoeditor:pyinstaller-engine:v1:mac-x64",
            },
            "frozen-helper": {
                "required_all": (
                    FROZEN_RUNTIME_PATHS["mac-x64"]["frozen-helper"],
                ),
                "lineage_id": "autoeditor:pyinstaller-helper:v1:mac-x64",
            },
        },
    }


PLATFORM_COMPONENT_RULES = _component_rules()


class NativeMediaReceiptError(ValueError):
    """The allowlist, app tree, or receipt violated the v1 contract."""


def _define_validated_allowlist_type():
    """Keep allowlist construction behind the validating loader factory."""
    factory_token = object()

    @dataclass(frozen=True, init=False)
    class _ValidatedAllowlist:
        platform: str
        scan_roots: tuple[str, ...]
        files: Mapping[str, Mapping[str, str]]
        sha256: str

        def __init__(
            self,
            platform: str,
            scan_roots: tuple[str, ...],
            files: Mapping[str, Mapping[str, str]],
            sha256: str,
            *,
            _factory_token: object | None = None,
        ) -> None:
            if _factory_token is not factory_token:
                raise TypeError(
                    "validated native allowlists must come from load_allowlist"
                )
            object.__setattr__(self, "platform", platform)
            object.__setattr__(self, "scan_roots", scan_roots)
            object.__setattr__(self, "files", files)
            object.__setattr__(self, "sha256", sha256)

    def construct(
        platform: str,
        scan_roots: tuple[str, ...],
        files: Mapping[str, Mapping[str, str]],
        sha256: str,
    ) -> _ValidatedAllowlist:
        return _ValidatedAllowlist(
            platform,
            scan_roots,
            files,
            sha256,
            _factory_token=factory_token,
        )

    return _ValidatedAllowlist, construct


_ValidatedAllowlist, _new_validated_allowlist = (
    _define_validated_allowlist_type()
)
del _define_validated_allowlist_type


@dataclass(frozen=True)
class _NativeObservation:
    """Bytes and stable file identity observed through one held handle."""

    byte_count: int
    sha256: str
    file_id: tuple[int, int]
    link_count: int


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize the schema's integer/string-only data deterministically."""
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeMediaReceiptError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[Any, bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except NativeMediaReceiptError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeMediaReceiptError(f"cannot read JSON {path}: {exc}") from exc
    return payload, raw


def _expected_remotion_prune_receipt() -> dict[str, Any]:
    """Return the sole accepted Remotion 4.0.507 Windows prune receipt."""
    return {
        "schema": REMOTION_PRUNE_RECEIPT_SCHEMA,
        "status": "pruned",
        "target": {"os": "windows", "arch": "x64"},
        "package": {
            "name": REMOTION_PACKAGE_NAME,
            "version": REMOTION_VERSION,
            "resolved": REMOTION_PACKAGE_RESOLVED,
            "integrity": REMOTION_PACKAGE_INTEGRITY,
            "tarballSha256": REMOTION_PACKAGE_TARBALL_SHA256,
            "inventorySha256Before": REMOTION_INVENTORY_SHA256_BEFORE,
            "inventorySha256After": REMOTION_INVENTORY_SHA256_AFTER,
        },
        "activeFfmpegGeneration": "7.1",
        "staleFfmpegGeneration": "6.1",
        "activePeImports": {
            executable: list(imports)
            for executable, imports in REMOTION_ACTIVE_PE_IMPORTS.items()
        },
        "removed": [
            {"path": relative, "sha256": digest}
            for relative, digest in WINDOWS_REMOTION_STALE_NATIVE_SHA256.items()
        ],
    }


def _validate_remotion_prune_receipt(
    raw: bytes, expected_sha256: str
) -> None:
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise NativeMediaReceiptError(
            "Windows Remotion pruning receipt SHA256 does not match the "
            "allowlist source manifest"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except NativeMediaReceiptError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeMediaReceiptError(
            f"cannot read canonical Windows Remotion pruning receipt: {exc}"
        ) from exc
    expected = _expected_remotion_prune_receipt()
    if payload != expected:
        raise NativeMediaReceiptError(
            "Windows Remotion pruning receipt does not match the canonical "
            "4.0.507 post-prune contract"
        )
    canonical = (
        json.dumps(expected, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if raw != canonical:
        raise NativeMediaReceiptError(
            "Windows Remotion pruning receipt is not canonical"
        )


def _inventory_map_digest(inventory: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_sha256 in sorted(inventory.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_sha256))
    return digest.hexdigest()


def _onnx_package_root(platform: str) -> str:
    return PLATFORM_COMPONENT_RULES[platform]["onnxruntime-node"]["roots"][0]


def _onnx_prune_receipt_path(platform: str) -> str:
    return f"{_onnx_package_root(platform)}/{ONNX_PRUNE_RECEIPT_FILENAME}"


def _expected_onnx_target_inventory(platform: str) -> dict[str, str]:
    target = ONNX_TARGET_DIRECTORIES[platform] + "/"
    return {
        relative: digest
        for relative, digest in ONNX_NATIVE_INVENTORY.items()
        if relative.startswith(target)
    }


def _expected_onnx_prune_receipt(platform: str) -> dict[str, Any]:
    """Return the exact v2 producer receipt for one supported target."""
    _platform_rule(platform)
    kept = _expected_onnx_target_inventory(platform)
    removed = {
        relative: digest
        for relative, digest in ONNX_NATIVE_INVENTORY.items()
        if relative not in kept
    }
    return {
        "schema": ONNX_PRUNE_RECEIPT_SCHEMA,
        "target": dict(ONNX_RECEIPT_TARGETS[platform]),
        "package": {
            "name": ONNX_PACKAGE_NAME,
            "version": ONNX_PACKAGE_VERSION,
            "integrity": ONNX_PACKAGE_INTEGRITY,
            "inventorySha256Before": _inventory_map_digest(
                ONNX_NATIVE_INVENTORY
            ),
            "inventorySha256After": _inventory_map_digest(kept),
        },
        "kept": [
            {"path": relative, "sha256": digest}
            for relative, digest in sorted(kept.items())
        ],
        "removed": [
            {"path": relative, "sha256": digest}
            for relative, digest in sorted(removed.items())
        ],
    }


def _validate_onnx_prune_receipt(
    raw: bytes,
    expected_sha256: str,
    platform: str,
) -> None:
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise NativeMediaReceiptError(
            "ONNX Runtime pruning receipt SHA256 does not match the "
            "allowlist source manifest"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except NativeMediaReceiptError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeMediaReceiptError(
            f"cannot read canonical ONNX Runtime pruning receipt: {exc}"
        ) from exc
    expected = _expected_onnx_prune_receipt(platform)
    if payload != expected:
        raise NativeMediaReceiptError(
            "ONNX Runtime pruning receipt does not match the canonical "
            f"1.21.1 {platform} target-only contract"
        )
    canonical = (
        json.dumps(expected, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if raw != canonical:
        raise NativeMediaReceiptError(
            "ONNX Runtime pruning receipt is not canonical"
        )


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("extra " + ", ".join(extra))
    raise NativeMediaReceiptError(
        f"{label} has wrong fields ({'; '.join(details)})"
    )


def _platform_rule(platform: str) -> dict[str, Any]:
    rule = PLATFORM_RULES.get(platform)
    if rule is None:
        raise NativeMediaReceiptError(f"unsupported platform: {platform}")
    return rule


def _safe_relative_path(
    value: Any,
    *,
    allow_dot: bool = False,
    label: str = "path",
) -> str:
    if allow_dot and value == ".":
        return "."
    if not isinstance(value, str) or not value:
        raise NativeMediaReceiptError(f"unsafe {label}: {value!r}")
    if value.startswith("/") or value.endswith("/") or "\\" in value:
        raise NativeMediaReceiptError(f"unsafe {label}: {value!r}")
    if len(value) > 4096 or unicodedata.normalize("NFC", value) != value:
        raise NativeMediaReceiptError(f"unsafe {label}: {value!r}")

    parts = value.split("/")
    for part in parts:
        if part in {"", ".", ".."} or len(part) > 255:
            raise NativeMediaReceiptError(f"unsafe {label}: {value!r}")
        if part.endswith((".", " ")):
            raise NativeMediaReceiptError(f"unsafe {label}: {value!r}")
        if any(
            ord(char) < 32
            or ord(char) == 127
            or char in FORBIDDEN_PATH_CHARS
            for char in part
        ):
            raise NativeMediaReceiptError(f"unsafe {label}: {value!r}")
        windows_stem = part.split(".", 1)[0].rstrip(" ").casefold()
        if windows_stem in WINDOWS_RESERVED_NAMES:
            raise NativeMediaReceiptError(f"unsafe {label}: {value!r}")
    return "/".join(parts)


def _assert_no_path_collisions(paths: list[str], label: str) -> None:
    exact: set[str] = set()
    folded: dict[str, str] = {}
    for path in paths:
        if path in exact:
            raise NativeMediaReceiptError(f"duplicate {label} path: {path}")
        exact.add(path)
        key = unicodedata.normalize("NFC", path).casefold()
        previous = folded.get(key)
        if previous is not None and previous != path:
            raise NativeMediaReceiptError(
                f"{label} casefold collision: {previous} and {path}"
            )
        folded[key] = path


def _root_covers_path(scan_root: str, relative: str) -> bool:
    if scan_root == ".":
        return True
    root_key = scan_root.casefold()
    path_key = relative.casefold()
    return path_key == root_key or path_key.startswith(root_key + "/")


def _normalize_scan_roots(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise NativeMediaReceiptError(
            "allowlist scan_roots must be a nonempty JSON array"
        )
    if len(value) > 256:
        raise NativeMediaReceiptError("allowlist has too many scan_roots")
    roots = [
        _safe_relative_path(item, allow_dot=True, label="scan root")
        for item in value
    ]
    _assert_no_path_collisions(roots, "scan root")

    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            if _root_covers_path(left, right) or _root_covers_path(right, left):
                raise NativeMediaReceiptError(
                    f"overlapping scan roots: {left} and {right}"
                )
    return tuple(sorted(roots))


def _validate_scan_coverage(
    scan_roots: tuple[str, ...], platform: str
) -> None:
    mandatory = set(MANDATORY_SCAN_PATHS[platform])
    for contract in PLATFORM_COMPONENT_RULES[platform].values():
        if contract.get("scan_entire_roots"):
            mandatory.update(contract.get("roots", ()))
    missing = sorted(
        path
        for path in mandatory
        if not any(_root_covers_path(root, path) for root in scan_roots)
    )
    if missing:
        raise NativeMediaReceiptError(
            "scan_roots do not cover mandatory component subtrees: "
            + ", ".join(missing)
        )


def _validate_core_paths(paths: set[str], platform: str, label: str) -> None:
    missing = sorted(set(_platform_rule(platform)["core"]) - paths)
    if missing:
        raise NativeMediaReceiptError(
            f"{label} is missing required native media paths: "
            + ", ".join(missing)
        )


def _validate_paths_covered(
    paths: set[str], scan_roots: tuple[str, ...]
) -> None:
    outside = sorted(
        path
        for path in paths
        if not any(_root_covers_path(root, path) for root in scan_roots)
    )
    if outside:
        raise NativeMediaReceiptError(
            "allowlist native media paths outside scan_roots: "
            + ", ".join(outside)
        )


def _resource_prefix(platform: str) -> str:
    return "resources/" if platform == "windows-x64" else "Contents/Resources/"


def _component_for_path(relative: str, platform: str) -> str:
    """Return the only component label valid for an app-relative path."""
    rule = _platform_rule(platform)
    contracts = PLATFORM_COMPONENT_RULES[platform]
    core = set(rule["core"])
    resource_prefix = _resource_prefix(platform)

    if platform == "windows-x64":
        electron_paths = {"ffmpeg.dll", "libffmpeg.dll"}
    else:
        electron_paths = {
            "Contents/Frameworks/Electron Framework.framework/Versions/A/"
            "Libraries/libffmpeg.dylib"
        }
    if relative in electron_paths:
        return "electron"

    for component, runtime_path in FROZEN_RUNTIME_PATHS[platform].items():
        runtime_root = runtime_path.rsplit("/", 1)[0]
        if relative == runtime_path or _under(relative, runtime_root):
            return component

    if relative in core or _under(relative, resource_prefix + "lib"):
        return "main-ffmpeg"

    for component in ("remotion", "onnxruntime-node", "browser"):
        for root in contracts[component]["roots"]:
            if _under(relative, root):
                return component

    return "supporting-native"


def _is_forbidden_pyav_path(relative: str, platform: str) -> bool:
    runtime_path = any(
        relative == root or _under(relative, root)
        for root in MANDATORY_SCAN_PATHS[platform]
    )
    if not runtime_path:
        return False
    parts = relative.split("/")
    return bool(
        any(part.casefold() in {"av", "av.libs"} for part in parts)
        or any(PYAV_METADATA_NAME.fullmatch(part) for part in parts)
        or PYAV_NATIVE_NAME.match(parts[-1])
    )


def _validate_component_path(
    component: Any,
    relative: str,
    platform: str,
    label: str,
) -> str:
    if _is_forbidden_pyav_path(relative, platform):
        raise NativeMediaReceiptError(
            f"PyAV payload in frozen runtime: {relative}"
        )
    if not isinstance(component, str) or component not in COMPONENTS:
        raise NativeMediaReceiptError(
            f"invalid {label} component for native media path {relative}: "
            f"{component!r}"
        )
    expected = _component_for_path(relative, platform)
    if component != expected:
        raise NativeMediaReceiptError(
            f"{label} component {component} is invalid for {relative}; "
            f"expected {expected}"
        )
    return component


def _validate_required_components(
    files: Mapping[str, Mapping[str, Any]], label: str
) -> None:
    present = {
        metadata.get("component")
        for metadata in files.values()
        if isinstance(metadata, Mapping)
    }
    missing = sorted(REQUIRED_COMPONENTS - present)
    if missing:
        raise NativeMediaReceiptError(
            f"{label} is missing required native media components: "
            + ", ".join(missing)
        )


def _validate_component_contracts(
    files: Mapping[str, Mapping[str, Any]], platform: str, label: str
) -> None:
    """Require pinned component roots, core files, versions, and platforms."""
    contracts = PLATFORM_COMPONENT_RULES[platform]
    paths = set(files)
    for component in sorted(REQUIRED_COMPONENTS):
        contract = contracts[component]
        required_all = set(contract.get("required_all", ()))
        missing = sorted(required_all - paths)
        if missing:
            raise NativeMediaReceiptError(
                f"{label} is missing required {component} paths: "
                + ", ".join(missing)
            )
        for alternatives in contract.get("required_any", ()):
            if paths.isdisjoint(alternatives):
                raise NativeMediaReceiptError(
                    f"{label} is missing a required {component} path; "
                    "expected one of: " + ", ".join(alternatives)
                )

        allowed_all = contract.get("allowed_all")
        if allowed_all is not None:
            allowed = set(allowed_all)
            disallowed = sorted(
                relative
                for relative, metadata in files.items()
                if metadata.get("component") == component
                and relative not in allowed
            )
            if disallowed:
                raise NativeMediaReceiptError(
                    f"{label} has disallowed pinned {component} paths: "
                    + ", ".join(disallowed)
                )

        expected_lineage = contract.get("lineage_id")
        if expected_lineage is None:
            continue
        drift = sorted(
            relative
            for relative, metadata in files.items()
            if metadata.get("component") == component
            and metadata.get("lineage_id") != expected_lineage
        )
        if drift:
            raise NativeMediaReceiptError(
                f"{label} has wrong pinned {component} lineage for: "
                + ", ".join(drift)
            )

    if platform == "windows-x64":
        remotion_source_manifests = {
            metadata.get("source_manifest_sha256")
            for metadata in files.values()
            if metadata.get("component") == "remotion"
        }
        if len(remotion_source_manifests) != 1:
            raise NativeMediaReceiptError(
                f"{label} must bind every Windows Remotion native path to "
                "one canonical pruning receipt"
            )
    onnx_source_manifests = {
        metadata.get("source_manifest_sha256")
        for metadata in files.values()
        if metadata.get("component") == "onnxruntime-node"
    }
    if len(onnx_source_manifests) != 1:
        raise NativeMediaReceiptError(
            f"{label} must bind every ONNX Runtime native path to one "
            "canonical target-pruning receipt"
        )


def _validate_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise NativeMediaReceiptError(f"invalid {label} SHA256")
    return value


def _read_validate_allowlist(
    path: Path,
    platform: str,
    expected_allowlist_sha256: str,
) -> tuple[str, tuple[str, ...], Mapping[str, Mapping[str, str]], str]:
    """Read and validate an allowlist without constructing its sealed type."""
    _platform_rule(platform)
    expected_digest = _validate_sha256(
        expected_allowlist_sha256, "expected allowlist"
    )
    payload, raw = _read_json(path)
    actual_digest = hashlib.sha256(raw).hexdigest()
    if actual_digest != expected_digest:
        raise NativeMediaReceiptError(
            "allowlist SHA256 does not match --expected-allowlist-sha256"
        )
    if not isinstance(payload, dict):
        raise NativeMediaReceiptError("allowlist root must be a JSON object")
    _exact_keys(
        payload,
        {"schema", "platform", "scan_roots", "files"},
        "allowlist",
    )
    if payload["schema"] != ALLOWLIST_SCHEMA:
        raise NativeMediaReceiptError("allowlist has wrong schema")
    if payload["platform"] != platform:
        raise NativeMediaReceiptError(
            f"allowlist has wrong platform: expected {platform}, "
            f"found {payload['platform']}"
        )
    scan_roots = _normalize_scan_roots(payload["scan_roots"])
    _validate_scan_coverage(scan_roots, platform)
    files = payload["files"]
    if not isinstance(files, dict):
        raise NativeMediaReceiptError("allowlist files must be a path mapping")

    normalized: dict[str, dict[str, str]] = {}
    paths: list[str] = []
    for raw_path, metadata in files.items():
        relative = _safe_relative_path(raw_path)
        if not isinstance(metadata, dict):
            raise NativeMediaReceiptError(
                f"allowlist metadata must be an object: {relative}"
            )
        _exact_keys(
            metadata,
            {"component", "lineage_id", "source_manifest_sha256"},
            f"allowlist entry {relative}",
        )
        component = _validate_component_path(
            metadata["component"], relative, platform, "allowlist"
        )
        lineage_id = metadata["lineage_id"]
        source_sha = metadata["source_manifest_sha256"]
        if not isinstance(lineage_id, str) or not LINEAGE_ID_RE.fullmatch(
                lineage_id):
            raise NativeMediaReceiptError(
                f"invalid lineage ID for native media path: {relative}"
            )
        if not isinstance(source_sha, str) or not SHA256_RE.fullmatch(source_sha):
            raise NativeMediaReceiptError(
                f"invalid source-manifest SHA256 for native media path: {relative}"
            )
        paths.append(relative)
        normalized[relative] = {
            "component": component,
            "lineage_id": lineage_id,
            "source_manifest_sha256": source_sha,
        }

    _assert_no_path_collisions(paths, "allowlist")
    expected = set(paths)
    _validate_core_paths(expected, platform, "allowlist")
    _validate_paths_covered(expected, scan_roots)
    _validate_required_components(normalized, "allowlist")
    _validate_component_contracts(normalized, platform, "allowlist")
    immutable_files = MappingProxyType({
        relative: MappingProxyType(dict(metadata))
        for relative, metadata in normalized.items()
    })
    return platform, scan_roots, immutable_files, actual_digest


def _bind_allowlist_loader(construct):
    """Close the only valid constructor into the public validating loader."""
    def load_allowlist(
        path: Path,
        platform: str,
        expected_allowlist_sha256: str,
    ) -> _ValidatedAllowlist:
        """Load and strictly validate an explicit final-app native allowlist."""
        validated = _read_validate_allowlist(
            path, platform, expected_allowlist_sha256
        )
        return construct(*validated)

    return load_allowlist


load_allowlist = _bind_allowlist_loader(_new_validated_allowlist)
del _bind_allowlist_loader
del _new_validated_allowlist


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_exact_at(
    handle: BinaryIO,
    offset: int,
    size: int,
    relative: str,
    binary_format: str,
) -> bytes:
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise NativeMediaReceiptError(
            f"truncated {binary_format} native media path: {relative}"
        )
    return data


def _parse_pe(
    handle: BinaryIO, file_size: int, relative: str
) -> tuple[set[int], set[str]]:
    if file_size < 64:
        raise NativeMediaReceiptError(
            f"truncated PE native media path: {relative}"
        )
    dos_header = _read_exact_at(handle, 0, 64, relative, "PE")
    pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
    if (
        pe_offset < 64
        or pe_offset > MAX_PE_HEADER_OFFSET
        or pe_offset + 24 > file_size
    ):
        raise NativeMediaReceiptError(
            f"invalid PE header offset for native media path: {relative}"
        )

    header = _read_exact_at(handle, pe_offset, 24, relative, "PE")
    if header[:4] != b"PE\0\0":
        raise NativeMediaReceiptError(
            f"invalid PE signature for native media path: {relative}"
        )
    machine, sections = struct.unpack_from("<HH", header, 4)
    optional_size = struct.unpack_from("<H", header, 20)[0]
    characteristics = struct.unpack_from("<H", header, 22)[0]
    if not 1 <= sections <= 96:
        raise NativeMediaReceiptError(
            f"invalid PE section count for native media path: {relative}"
        )
    if optional_size < 112 or optional_size > 4096:
        raise NativeMediaReceiptError(
            f"invalid PE optional header for native media path: {relative}"
        )
    if not characteristics & IMAGE_FILE_EXECUTABLE_IMAGE:
        raise NativeMediaReceiptError(
            f"PE native media path is not executable image data: {relative}"
        )

    optional_offset = pe_offset + 24
    section_offset = optional_offset + optional_size
    section_end = section_offset + sections * 40
    if section_end > file_size:
        raise NativeMediaReceiptError(
            f"truncated PE section table for native media path: {relative}"
        )
    optional = _read_exact_at(
        handle, optional_offset, optional_size, relative, "PE"
    )
    if struct.unpack_from("<H", optional, 0)[0] != 0x20B:
        raise NativeMediaReceiptError(
            f"PE native media path is not PE32+: {relative}"
        )
    entry_point = struct.unpack_from("<I", optional, 16)[0]
    section_alignment = struct.unpack_from("<I", optional, 32)[0]
    file_alignment = struct.unpack_from("<I", optional, 36)[0]
    size_of_image = struct.unpack_from("<I", optional, 56)[0]
    size_of_headers = struct.unpack_from("<I", optional, 60)[0]
    if (
        file_alignment < 512
        or file_alignment > 65_536
        or file_alignment & (file_alignment - 1)
        or section_alignment < file_alignment
        or section_alignment & (section_alignment - 1)
        or size_of_headers < section_end
        or size_of_headers > file_size
        or size_of_headers % file_alignment
        or size_of_image <= size_of_headers
        or size_of_image % section_alignment
    ):
        raise NativeMediaReceiptError(
            f"invalid PE header bounds for native media path: {relative}"
        )

    table = _read_exact_at(
        handle, section_offset, sections * 40, relative, "PE"
    )
    nonempty_sections = 0
    executable_ranges: list[tuple[int, int]] = []
    raw_ranges: list[tuple[int, int]] = []
    for index in range(sections):
        entry_offset = index * 40
        virtual_size, virtual_address = struct.unpack_from(
            "<II", table, entry_offset + 8
        )
        raw_size, raw_offset = struct.unpack_from(
            "<II", table, entry_offset + 16
        )
        section_characteristics = struct.unpack_from(
            "<I", table, entry_offset + 36
        )[0]
        mapped_size = max(virtual_size, raw_size)
        if (
            mapped_size == 0
            or virtual_address % section_alignment
            or virtual_address >= size_of_image
            or mapped_size > size_of_image - virtual_address
        ):
            raise NativeMediaReceiptError(
                f"invalid PE section mapping for native media path: {relative}"
            )
        if raw_size == 0:
            continue
        if (
            raw_offset < size_of_headers
            or raw_offset % file_alignment
            or raw_size % file_alignment
            or raw_offset > file_size
            or raw_size > file_size - raw_offset
        ):
            raise NativeMediaReceiptError(
                f"invalid PE section bounds for native media path: {relative}"
            )
        nonempty_sections += 1
        raw_ranges.append((raw_offset, raw_offset + raw_size))
        if (
            section_characteristics & IMAGE_SCN_CNT_CODE
            and section_characteristics & IMAGE_SCN_MEM_EXECUTE
        ):
            executable_ranges.append(
                (virtual_address, virtual_address + mapped_size)
            )
    for left, right in zip(sorted(raw_ranges), sorted(raw_ranges)[1:]):
        if left[1] > right[0]:
            raise NativeMediaReceiptError(
                f"overlapping PE sections for native media path: {relative}"
            )
    if nonempty_sections == 0 or not executable_ranges:
        raise NativeMediaReceiptError(
            f"PE native media path has no executable section data: {relative}"
        )
    role = "library" if characteristics & IMAGE_FILE_DLL else "executable"
    if role == "executable" and (
        entry_point == 0
        or not any(start <= entry_point < end for start, end in executable_ranges)
    ):
        raise NativeMediaReceiptError(
            f"PE executable has no valid entry point: {relative}"
        )
    return {machine}, {role}


MACH_THIN_MAGICS = {
    b"\xce\xfa\xed\xfe": ("<", 28),
    b"\xfe\xed\xfa\xce": (">", 28),
    b"\xcf\xfa\xed\xfe": ("<", 32),
    b"\xfe\xed\xfa\xcf": (">", 32),
}
MACH_FAT_MAGICS = {
    b"\xca\xfe\xba\xbe": (">", 20),
    b"\xbe\xba\xfe\xca": ("<", 20),
    b"\xca\xfe\xba\xbf": (">", 32),
    b"\xbf\xba\xfe\xca": ("<", 32),
}


def _parse_macho_thin(
    handle: BinaryIO,
    offset: int,
    size: int,
    relative: str,
) -> tuple[int, str]:
    if size < 4:
        raise NativeMediaReceiptError(
            f"truncated Mach-O native media path: {relative}"
        )
    magic = _read_exact_at(handle, offset, 4, relative, "Mach-O")
    thin = MACH_THIN_MAGICS.get(magic)
    if thin is None:
        raise NativeMediaReceiptError(
            f"invalid Mach-O slice for native media path: {relative}"
        )
    endian, header_size = thin
    if size < header_size:
        raise NativeMediaReceiptError(
            f"truncated Mach-O header for native media path: {relative}"
        )
    header = _read_exact_at(
        handle, offset, header_size, relative, "Mach-O"
    )
    cpu_type = struct.unpack_from(f"{endian}I", header, 4)[0]
    is_64_bit_header = header_size == 32
    if is_64_bit_header != bool(cpu_type & CPU_ARCH_ABI64):
        raise NativeMediaReceiptError(
            f"Mach-O header width does not match CPU type: {relative}"
        )
    if not is_64_bit_header:
        raise NativeMediaReceiptError(
            f"Mach-O native media path is not 64-bit: {relative}"
        )
    file_type = struct.unpack_from(f"{endian}I", header, 12)[0]
    role_by_type = {
        MH_EXECUTE: "executable",
        MH_DYLIB: "library",
        MH_BUNDLE: "bundle",
    }
    role = role_by_type.get(file_type)
    if role is None:
        raise NativeMediaReceiptError(
            f"unsupported Mach-O file type for native media path: {relative}"
        )
    command_count, command_bytes = struct.unpack_from(
        f"{endian}II", header, 16
    )
    if (
        command_count == 0
        or command_count > MAX_MACH_LOAD_COMMANDS
        or command_bytes < command_count * 8
        or command_bytes > size - header_size
    ):
        raise NativeMediaReceiptError(
            f"invalid Mach-O load-command bounds for native media path: "
            f"{relative}"
        )

    cursor = offset + header_size
    command_end = cursor + command_bytes
    saw_file_segment = False
    saw_executable_code = False
    for _ in range(command_count):
        command = _read_exact_at(
            handle, cursor, 8, relative, "Mach-O load command"
        )
        command_type = struct.unpack_from(f"{endian}I", command, 0)[0]
        command_size = struct.unpack_from(f"{endian}I", command, 4)[0]
        if command_size < 8 or command_size > command_end - cursor:
            raise NativeMediaReceiptError(
                f"invalid Mach-O load command for native media path: {relative}"
            )
        full_command = _read_exact_at(
            handle, cursor, command_size, relative, "Mach-O load command"
        )
        if command_type == LC_SEGMENT:
            raise NativeMediaReceiptError(
                f"32-bit segment command in 64-bit Mach-O path: {relative}"
            )
        if command_type == LC_SEGMENT_64:
            if command_size < 72:
                raise NativeMediaReceiptError(
                    f"truncated Mach-O segment command: {relative}"
                )
            vm_size, file_offset, file_bytes = struct.unpack_from(
                f"{endian}QQQ", full_command, 32
            )
            init_protection, section_count = struct.unpack_from(
                f"{endian}II", full_command, 60
            )
            required_command_size = 72 + section_count * 80
            if required_command_size > command_size:
                raise NativeMediaReceiptError(
                    f"truncated Mach-O section table: {relative}"
                )
            if file_bytes:
                if (
                    vm_size < file_bytes
                    or file_offset > size
                    or file_bytes > size - file_offset
                ):
                    raise NativeMediaReceiptError(
                        f"invalid Mach-O segment bounds: {relative}"
                    )
                saw_file_segment = True
            for section_index in range(section_count):
                section_offset = 72 + section_index * 80
                section_size = struct.unpack_from(
                    f"{endian}Q", full_command, section_offset + 40
                )[0]
                section_file_offset = struct.unpack_from(
                    f"{endian}I", full_command, section_offset + 48
                )[0]
                section_flags = struct.unpack_from(
                    f"{endian}I", full_command, section_offset + 64
                )[0]
                has_instructions = bool(
                    section_flags & (0x80000000 | 0x00000400)
                )
                if has_instructions:
                    if (
                        section_size == 0
                        or section_file_offset > size
                        or section_size > size - section_file_offset
                    ):
                        raise NativeMediaReceiptError(
                            f"invalid Mach-O executable section: {relative}"
                        )
                    if not init_protection & VM_PROT_EXECUTE:
                        raise NativeMediaReceiptError(
                            f"non-executable Mach-O code segment: {relative}"
                        )
                    saw_executable_code = True
        cursor += command_size
    if cursor != command_end:
        raise NativeMediaReceiptError(
            f"invalid Mach-O load-command size for native media path: {relative}"
        )
    if not saw_file_segment or not saw_executable_code:
        raise NativeMediaReceiptError(
            f"Mach-O native media path has no executable section data: {relative}"
        )
    return cpu_type, role


def _parse_macho_fat(
    handle: BinaryIO,
    file_size: int,
    relative: str,
    endian: str,
    entry_size: int,
) -> tuple[set[int], set[str]]:
    header = _read_exact_at(handle, 0, 8, relative, "Mach-O fat header")
    count = struct.unpack_from(f"{endian}I", header, 4)[0]
    if count == 0 or count > 64:
        raise NativeMediaReceiptError(
            f"invalid Mach-O fat slice count for native media path: {relative}"
        )
    table_size = 8 + count * entry_size
    if table_size > file_size:
        raise NativeMediaReceiptError(
            f"truncated Mach-O fat table for native media path: {relative}"
        )
    table = _read_exact_at(handle, 8, count * entry_size, relative, "Mach-O")
    slices: list[tuple[int, int, int]] = []
    for index in range(count):
        entry_offset = index * entry_size
        if entry_size == 20:
            cpu_type, _, slice_offset, slice_size, _ = struct.unpack_from(
                f"{endian}IIIII", table, entry_offset
            )
        else:
            cpu_type, _, slice_offset, slice_size, _, _ = struct.unpack_from(
                f"{endian}IIQQII", table, entry_offset
            )
        if (
            slice_offset < table_size
            or slice_size < 28
            or slice_offset > file_size
            or slice_size > file_size - slice_offset
        ):
            raise NativeMediaReceiptError(
                f"invalid Mach-O fat slice bounds for native media path: "
                f"{relative}"
            )
        slices.append((slice_offset, slice_size, cpu_type))

    ordered = sorted(slices)
    for left, right in zip(ordered, ordered[1:]):
        if left[0] + left[1] > right[0]:
            raise NativeMediaReceiptError(
                f"overlapping Mach-O fat slices for native media path: "
                f"{relative}"
            )
    machines: set[int] = set()
    roles: set[str] = set()
    for slice_offset, slice_size, declared_cpu in slices:
        actual_cpu, role = _parse_macho_thin(
            handle, slice_offset, slice_size, relative
        )
        if actual_cpu != declared_cpu:
            raise NativeMediaReceiptError(
                f"Mach-O fat CPU mismatch for native media path: {relative}"
            )
        machines.add(actual_cpu)
        roles.add(role)
    if len(roles) != 1:
        raise NativeMediaReceiptError(
            f"mixed Mach-O roles for native media path: {relative}"
        )
    return machines, roles


def _native_identity(
    handle: BinaryIO, relative: str
) -> tuple[str, set[int], set[str]] | None:
    handle.seek(0, os.SEEK_END)
    file_size = handle.tell()
    handle.seek(0)
    prefix = handle.read(4)
    if len(prefix) < 2:
        return None
    if prefix[:2] == b"MZ":
        machines, roles = _parse_pe(handle, file_size, relative)
        return "pe", machines, roles
    if len(prefix) < 4:
        return None
    if prefix in MACH_THIN_MAGICS:
        machine, role = _parse_macho_thin(
            handle, 0, file_size, relative
        )
        return "macho", {machine}, {role}
    fat = MACH_FAT_MAGICS.get(prefix)
    if fat is not None:
        endian, entry_size = fat
        machines, roles = _parse_macho_fat(
            handle, file_size, relative, endian, entry_size
        )
        return "macho", machines, roles
    return None


def _validate_file_platform(
    identity: tuple[str, set[int], set[str]] | None,
    platform: str,
    relative: str,
) -> None:
    rule = _platform_rule(platform)
    if identity is None:
        raise NativeMediaReceiptError(
            f"allowlisted native media path is not PE or Mach-O: {relative}"
        )
    binary_format, machines, roles = identity
    if binary_format != rule["format"] or rule["machine"] not in machines:
        raise NativeMediaReceiptError(
            f"wrong platform for native media path {relative}: expected {platform}"
        )
    expected_roles = _expected_binary_roles(relative, platform)
    if not roles <= expected_roles:
        raise NativeMediaReceiptError(
            f"wrong binary role for native media path {relative}: expected "
            f"{', '.join(sorted(expected_roles))}, found "
            f"{', '.join(sorted(roles))}"
        )


def _expected_binary_roles(relative: str, platform: str) -> set[str]:
    """Return fail-closed executable/library roles for a final app path."""
    _platform_rule(platform)
    name = relative.rsplit("/", 1)[-1].casefold()
    if platform == "windows-x64":
        return {"executable"} if name.endswith(".exe") else {"library"}
    if name.endswith((".dylib", ".a")):
        return {"library"}
    if name.endswith((".so", ".node")) or ".so." in name:
        return {"bundle", "library"}
    return {"executable"}


def _observe_open_handle(
    handle: BinaryIO,
    expected_size: int,
    file_id: tuple[int, int],
    link_count: int,
    platform: str,
    relative: str,
    *,
    hash_nonnative: bool = False,
) -> tuple[_NativeObservation | None, str | None]:
    """Classify and hash a native file without reopening its pathname."""
    identity = _native_identity(handle, relative)
    if identity is None and not hash_nonnative:
        return None, None
    if identity is not None:
        _validate_file_platform(identity, platform, relative)
    handle.seek(0)
    digest = hashlib.sha256()
    byte_count = 0
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        byte_count += len(chunk)
    if byte_count != expected_size or byte_count <= 0:
        raise NativeMediaReceiptError(
            f"native media path changed while scanning: {relative}"
        )
    content_sha256 = digest.hexdigest()
    if identity is None:
        return None, content_sha256
    return (
        _NativeObservation(byte_count, content_sha256, file_id, link_count),
        content_sha256,
    )


def _inspect_app_root(app_root: Path) -> None:
    try:
        root_stat = app_root.lstat()
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"cannot inspect final app root {app_root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise NativeMediaReceiptError("final app root must not be a symlink")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise NativeMediaReceiptError("final app root is not a directory")


def _validate_bound_component_receipts(
    app_root: Path,
    platform: str,
    allowlist: _ValidatedAllowlist,
) -> None:
    if platform == "windows-x64":
        source_manifests = {
            metadata["source_manifest_sha256"]
            for metadata in allowlist.files.values()
            if metadata["component"] == "remotion"
        }
        if len(source_manifests) != 1:
            raise NativeMediaReceiptError(
                "allowlist must bind every Windows Remotion native path to "
                "one canonical pruning receipt"
            )
        expected_sha256 = next(iter(source_manifests))
        raw = _secure_read_relative_file(
            app_root, REMOTION_PRUNE_RECEIPT_PATH
        )
        _validate_remotion_prune_receipt(raw, expected_sha256)

    onnx_source_manifests = {
        metadata["source_manifest_sha256"]
        for metadata in allowlist.files.values()
        if metadata["component"] == "onnxruntime-node"
    }
    if len(onnx_source_manifests) != 1:
        raise NativeMediaReceiptError(
            "allowlist must bind every ONNX Runtime native path to one "
            "canonical target-pruning receipt"
        )
    onnx_sha256 = next(iter(onnx_source_manifests))
    onnx_raw = _secure_read_relative_file(
        app_root, _onnx_prune_receipt_path(platform)
    )
    _validate_onnx_prune_receipt(onnx_raw, onnx_sha256, platform)


def _validate_onnx_observed(
    observed: Mapping[str, _NativeObservation], platform: str
) -> None:
    package_root = _onnx_package_root(platform)
    expected = {
        f"{package_root}/bin/napi-v3/{relative}": digest
        for relative, digest in _expected_onnx_target_inventory(platform).items()
    }
    changed = sorted(
        relative
        for relative, expected_sha256 in expected.items()
        if relative in observed
        and observed[relative].sha256 != expected_sha256
    )
    if changed:
        raise NativeMediaReceiptError(
            "ONNX Runtime native bytes do not match the authenticated "
            "target-pruning receipt: " + ", ".join(changed)
        )


class _NativeCollector:
    """Collect one race-bounded native inventory from held file handles."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.seen_paths: dict[str, str] = {}
        self.file_ids: dict[tuple[int, int], str] = {}
        self.observations: dict[str, _NativeObservation] = {}
        self.full_inventory_root = (
            PLATFORM_COMPONENT_RULES[platform]["remotion"]["roots"][0]
            if platform == "windows-x64"
            else None
        )
        self.full_inventory: dict[str, str] = {}

    def record_path(self, relative: str) -> None:
        key = unicodedata.normalize("NFC", relative).casefold()
        previous = self.seen_paths.get(key)
        if previous is not None and previous != relative:
            raise NativeMediaReceiptError(
                f"discovered casefold collision: {previous} and {relative}"
            )
        if previous == relative:
            raise NativeMediaReceiptError(
                f"duplicate discovered path: {relative}"
            )
        self.seen_paths[key] = relative
        if _is_forbidden_pyav_path(relative, self.platform):
            raise NativeMediaReceiptError(
                f"PyAV payload in frozen runtime: {relative}"
            )

    def record_native(
        self, relative: str, observation: _NativeObservation
    ) -> None:
        self._record_identity(
            relative, observation.file_id, observation.link_count
        )
        self.observations[relative] = observation

    def _record_identity(
        self,
        relative: str,
        file_id: tuple[int, int],
        link_count: int,
    ) -> None:
        if link_count != 1:
            raise NativeMediaReceiptError(
                "native or supporting file must have exactly one filesystem "
                "link: "
                f"{relative}"
            )
        if file_id[1] == 0:
            raise NativeMediaReceiptError(
                "filesystem did not provide a stable native or supporting "
                "file identity: "
                f"{relative}"
            )
        previous = self.file_ids.get(file_id)
        if previous is not None and previous != relative:
            raise NativeMediaReceiptError(
                "duplicate native or supporting file identity: "
                f"{previous} and {relative}"
            )
        self.file_ids[file_id] = relative

    def captures_full_file(self, relative: str) -> bool:
        root = self.full_inventory_root
        return root is not None and _under(relative, root)

    def record_full_file(
        self,
        relative: str,
        digest: str,
        file_id: tuple[int, int],
        link_count: int,
    ) -> None:
        root = self.full_inventory_root
        if root is None or not _under(relative, root):
            raise NativeMediaReceiptError(
                f"internal full-inventory path error: {relative}"
            )
        self._record_identity(relative, file_id, link_count)
        self.full_inventory[relative[len(root) + 1:]] = digest

    def validate_full_inventory(self) -> None:
        if self.platform != "windows-x64":
            return
        digest = hashlib.sha256()
        for relative, file_sha256 in sorted(self.full_inventory.items()):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(file_sha256))
        if digest.hexdigest() != REMOTION_INVENTORY_SHA256_AFTER:
            raise NativeMediaReceiptError(
                "Windows Remotion final inventory does not match the canonical "
                "4.0.507 post-prune receipt"
            )


def _require_posix_handle_apis() -> None:
    if not POSIX_HANDLE_APIS_AVAILABLE:
        raise NativeMediaReceiptError(
            "secure held-directory traversal is unavailable on this host; "
            "the native receipt refuses path-based fallback"
        )


def _posix_directory_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _posix_file_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_BINARY", 0)
    )


def _posix_open_directory_at(
    parent_fd: int, name: str, display: str
) -> tuple[int, os.stat_result]:
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"cannot inspect scan root {display}: {exc}"
        ) from exc
    if stat.S_ISLNK(before.st_mode):
        raise NativeMediaReceiptError(f"symlink scan root path: {display}")
    if not stat.S_ISDIR(before.st_mode):
        raise NativeMediaReceiptError(
            f"scan root is not a directory: {display}"
        )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name, _posix_directory_flags(), dir_fd=parent_fd
        )
        opened = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise NativeMediaReceiptError(
            f"cannot open held scan directory {display}: {exc}"
        ) from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or before.st_dev != opened.st_dev
        or before.st_ino != opened.st_ino
    ):
        os.close(descriptor)
        raise NativeMediaReceiptError(
            f"scan directory changed while opening: {display}"
        )
    return descriptor, opened


def _posix_verify_directory_path(
    parent_fd: int,
    name: str,
    opened: os.stat_result,
    display: str,
) -> None:
    try:
        after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"scan directory changed while scanning {display}: {exc}"
        ) from exc
    if (
        stat.S_ISLNK(after.st_mode)
        or not stat.S_ISDIR(after.st_mode)
        or after.st_dev != opened.st_dev
        or after.st_ino != opened.st_ino
    ):
        raise NativeMediaReceiptError(
            f"scan directory changed while scanning: {display}"
        )


@contextmanager
def _posix_relative_directory(
    root_fd: int, relative: str
) -> Iterator[int]:
    if relative == ".":
        yield root_fd
        return
    held: list[tuple[int, str, int, os.stat_result, str]] = []
    parent_fd = root_fd
    traversed: list[str] = []
    try:
        for component in relative.split("/"):
            traversed.append(component)
            display = "/".join(traversed)
            descriptor, opened = _posix_open_directory_at(
                parent_fd, component, display
            )
            held.append((parent_fd, component, descriptor, opened, display))
            parent_fd = descriptor
        yield parent_fd
    finally:
        verification_error: BaseException | None = None
        for parent, name, _, opened, display in reversed(held):
            try:
                _posix_verify_directory_path(parent, name, opened, display)
            except BaseException as exc:
                if verification_error is None:
                    verification_error = exc
        for _, _, descriptor, _, _ in reversed(held):
            os.close(descriptor)
        if verification_error is not None and sys.exc_info()[0] is None:
            raise verification_error


def _posix_walk_directory(
    directory_fd: int,
    prefix: str,
    collector: _NativeCollector,
) -> None:
    directory_before = os.fstat(directory_fd)
    try:
        names = sorted(
            os.listdir(directory_fd), key=lambda name: (name.casefold(), name)
        )
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"cannot scan held native media directory {prefix or '.'}: {exc}"
        ) from exc
    for name in names:
        relative = _safe_relative_path(
            f"{prefix}/{name}" if prefix else name
        )
        collector.record_path(relative)
        try:
            before = os.stat(
                name, dir_fd=directory_fd, follow_symlinks=False
            )
        except OSError as exc:
            raise NativeMediaReceiptError(
                f"cannot inspect native media path {relative}: {exc}"
            ) from exc
        if stat.S_ISLNK(before.st_mode):
            raise NativeMediaReceiptError(
                f"symlink in native media scan root: {relative}"
            )
        if stat.S_ISDIR(before.st_mode):
            child_fd, opened = _posix_open_directory_at(
                directory_fd, name, relative
            )
            try:
                _posix_walk_directory(child_fd, relative, collector)
                _posix_verify_directory_path(
                    directory_fd, name, opened, relative
                )
            finally:
                os.close(child_fd)
            continue
        if not stat.S_ISREG(before.st_mode):
            raise NativeMediaReceiptError(
                f"non-file in native media scan root: {relative}"
            )

        descriptor: int | None = None
        try:
            descriptor = os.open(
                name, _posix_file_flags(), dir_fd=directory_fd
            )
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or before.st_dev != opened.st_dev
                or before.st_ino != opened.st_ino
            ):
                raise NativeMediaReceiptError(
                    f"native media path changed while opening: {relative}"
                )
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = None
                observation, full_digest = _observe_open_handle(
                    handle,
                    opened.st_size,
                    (opened.st_dev, opened.st_ino),
                    opened.st_nlink,
                    collector.platform,
                    relative,
                    hash_nonnative=collector.captures_full_file(relative),
                )
                after_open = os.fstat(handle.fileno())
            after_path = os.stat(
                name, dir_fd=directory_fd, follow_symlinks=False
            )
            if (
                _stat_identity(opened) != _stat_identity(after_open)
                or _stat_identity(opened) != _stat_identity(after_path)
            ):
                raise NativeMediaReceiptError(
                    f"native media path changed while scanning: {relative}"
                )
            if observation is not None:
                collector.record_native(relative, observation)
            if full_digest is not None and collector.captures_full_file(relative):
                collector.record_full_file(
                    relative,
                    full_digest,
                    (opened.st_dev, opened.st_ino),
                    opened.st_nlink,
                )
        except NativeMediaReceiptError:
            raise
        except OSError as exc:
            raise NativeMediaReceiptError(
                f"cannot read native media path {relative}: {exc}"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
    directory_after = os.fstat(directory_fd)
    if _stat_identity(directory_before) != _stat_identity(directory_after):
        raise NativeMediaReceiptError(
            f"native media directory changed while scanning: {prefix or '.'}"
        )


def _inventory_native_tree_posix(
    app_root: Path,
    scan_roots: tuple[str, ...],
    platform: str,
) -> dict[str, _NativeObservation]:
    _require_posix_handle_apis()
    _inspect_app_root(app_root)
    before = app_root.lstat()
    descriptor: int | None = None
    try:
        descriptor = os.open(app_root, _posix_directory_flags())
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or before.st_dev != opened.st_dev
            or before.st_ino != opened.st_ino
        ):
            raise NativeMediaReceiptError(
                "final app root changed while opening"
            )
        for mandatory in MANDATORY_SCAN_PATHS[platform]:
            with _posix_relative_directory(descriptor, mandatory):
                pass
        collector = _NativeCollector(platform)
        for scan_root in scan_roots:
            with _posix_relative_directory(descriptor, scan_root) as root_fd:
                _posix_walk_directory(
                    root_fd,
                    "" if scan_root == "." else scan_root,
                    collector,
                )
        collector.validate_full_inventory()
        after = app_root.lstat()
        if _stat_identity(before) != _stat_identity(after):
            raise NativeMediaReceiptError(
                "final app root changed while scanning"
            )
        return dict(sorted(collector.observations.items()))
    except NativeMediaReceiptError:
        raise
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"cannot securely scan final app root {app_root}: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


@dataclass(frozen=True)
class _WindowsFileInfo:
    attributes: int
    byte_count: int
    file_id: tuple[int, int]
    link_count: int
    write_time: int


class _WindowsHandleApi:
    """Minimal Win32 held-handle API, loaded only on Windows."""

    FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_READ_ATTRIBUTES = 0x00000080
    FILE_SHARE_READ = 0x00000001
    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    FILE_TYPE_DISK = 0x0001

    def __init__(self) -> None:
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes
        except ImportError as exc:  # pragma: no cover - Windows runtime only
            raise NativeMediaReceiptError(
                "Win32 held-handle traversal APIs are unavailable"
            ) from exc

        class FileTime(ctypes.Structure):
            _fields_ = [
                ("low", wintypes.DWORD),
                ("high", wintypes.DWORD),
            ]

        class ByHandleFileInformation(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD),
                ("creation_time", FileTime),
                ("access_time", FileTime),
                ("write_time", FileTime),
                ("volume_serial", wintypes.DWORD),
                ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD),
                ("link_count", wintypes.DWORD),
                ("file_index_high", wintypes.DWORD),
                ("file_index_low", wintypes.DWORD),
            ]

        self.ctypes = ctypes
        self.msvcrt = msvcrt
        self.wintypes = wintypes
        self.info_type = ByHandleFileInformation
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel32.CreateFileW.restype = wintypes.HANDLE
        self.kernel32.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ByHandleFileInformation),
        ]
        self.kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
        self.kernel32.GetFileType.argtypes = [wintypes.HANDLE]
        self.kernel32.GetFileType.restype = wintypes.DWORD
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.invalid_handle = ctypes.c_void_p(-1).value

    @staticmethod
    def _extended_path(path: Path) -> str:
        absolute = os.path.abspath(os.fspath(path))
        if absolute.startswith("\\\\?\\"):
            return absolute
        if absolute.startswith("\\\\"):
            return "\\\\?\\UNC\\" + absolute[2:]
        return "\\\\?\\" + absolute

    def close(self, handle: int) -> None:
        if not self.kernel32.CloseHandle(handle):
            error = self.ctypes.get_last_error()
            raise NativeMediaReceiptError(
                f"cannot close held Windows filesystem handle: "
                f"{self.ctypes.FormatError(error)}"
            )

    def info(self, handle: int, display: str) -> _WindowsFileInfo:
        raw = self.info_type()
        if not self.kernel32.GetFileInformationByHandle(
            handle, self.ctypes.byref(raw)
        ):
            error = self.ctypes.get_last_error()
            raise NativeMediaReceiptError(
                f"cannot inspect held Windows path {display}: "
                f"{self.ctypes.FormatError(error)}"
            )
        if self.kernel32.GetFileType(handle) != self.FILE_TYPE_DISK:
            raise NativeMediaReceiptError(
                f"non-file in native media scan root: {display}"
            )
        return _WindowsFileInfo(
            attributes=int(raw.attributes),
            byte_count=(int(raw.size_high) << 32) | int(raw.size_low),
            file_id=(
                int(raw.volume_serial),
                (int(raw.file_index_high) << 32) | int(raw.file_index_low),
            ),
            link_count=int(raw.link_count),
            write_time=(int(raw.write_time.high) << 32)
            | int(raw.write_time.low),
        )

    def open(
        self, path: Path, display: str, *, read_data: bool
    ) -> tuple[int, _WindowsFileInfo]:
        desired_access = self.FILE_READ_ATTRIBUTES
        if read_data:
            desired_access |= self.GENERIC_READ
        handle = self.kernel32.CreateFileW(
            self._extended_path(path),
            desired_access,
            self.FILE_SHARE_READ,
            None,
            self.OPEN_EXISTING,
            self.FILE_FLAG_BACKUP_SEMANTICS
            | self.FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle in (None, self.invalid_handle):
            error = self.ctypes.get_last_error()
            raise NativeMediaReceiptError(
                f"cannot open held Windows path {display}: "
                f"{self.ctypes.FormatError(error)}"
            )
        try:
            information = self.info(handle, display)
            if information.attributes & self.FILE_ATTRIBUTE_REPARSE_POINT:
                raise NativeMediaReceiptError(
                    f"symlink or reparse point in native media scan root: "
                    f"{display}"
                )
            return handle, information
        except BaseException:
            self.close(handle)
            raise

    def adopt_file_handle(self, handle: int, display: str) -> int:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        try:
            return self.msvcrt.open_osfhandle(handle, flags)
        except OSError as exc:
            raise NativeMediaReceiptError(
                f"cannot adopt held Windows file handle {display}: {exc}"
            ) from exc

    def file_handle(self, descriptor: int) -> int:
        return int(self.msvcrt.get_osfhandle(descriptor))


@contextmanager
def _windows_relative_directory(
    api: _WindowsHandleApi,
    root_path: Path,
    relative: str,
) -> Iterator[tuple[Path, int, _WindowsFileInfo]]:
    if relative == ".":
        raise NativeMediaReceiptError(
            "internal Windows traversal error: root handle was not supplied"
        )
    held: list[tuple[int, _WindowsFileInfo, str]] = []
    current = root_path
    traversed: list[str] = []
    try:
        for component in relative.split("/"):
            traversed.append(component)
            display = "/".join(traversed)
            current = current / component
            handle, information = api.open(
                current, display, read_data=False
            )
            if not information.attributes & api.FILE_ATTRIBUTE_DIRECTORY:
                api.close(handle)
                raise NativeMediaReceiptError(
                    f"scan root is not a directory: {display}"
                )
            held.append((handle, information, display))
        yield current, held[-1][0], held[-1][1]
    finally:
        verification_error: BaseException | None = None
        for handle, opened, display in reversed(held):
            try:
                if api.info(handle, display) != opened:
                    raise NativeMediaReceiptError(
                        f"scan directory changed while scanning: {display}"
                    )
            except BaseException as exc:
                if verification_error is None:
                    verification_error = exc
        for handle, _, _ in reversed(held):
            try:
                api.close(handle)
            except BaseException as exc:
                if verification_error is None:
                    verification_error = exc
        if verification_error is not None and sys.exc_info()[0] is None:
            raise verification_error


def _windows_walk_directory(
    api: _WindowsHandleApi,
    directory: Path,
    directory_handle: int,
    directory_info: _WindowsFileInfo,
    prefix: str,
    collector: _NativeCollector,
) -> None:
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(
                iterator,
                key=lambda entry: (entry.name.casefold(), entry.name),
            )
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"cannot scan held native media directory {prefix or '.'}: {exc}"
        ) from exc
    for entry in entries:
        relative = _safe_relative_path(
            f"{prefix}/{entry.name}" if prefix else entry.name
        )
        collector.record_path(relative)
        child_path = directory / entry.name
        handle: int | None = None
        try:
            handle, information = api.open(
                child_path, relative, read_data=True
            )
            is_directory = bool(
                information.attributes & api.FILE_ATTRIBUTE_DIRECTORY
            )
            if is_directory:
                _windows_walk_directory(
                    api,
                    child_path,
                    handle,
                    information,
                    relative,
                    collector,
                )
                if api.info(handle, relative) != information:
                    raise NativeMediaReceiptError(
                        f"scan directory changed while scanning: {relative}"
                    )
                continue
            descriptor = api.adopt_file_handle(handle, relative)
            handle = None
            with os.fdopen(descriptor, "rb") as file_handle:
                observation, full_digest = _observe_open_handle(
                    file_handle,
                    information.byte_count,
                    information.file_id,
                    information.link_count,
                    collector.platform,
                    relative,
                    hash_nonnative=collector.captures_full_file(relative),
                )
                after = api.info(api.file_handle(file_handle.fileno()), relative)
            if after != information:
                raise NativeMediaReceiptError(
                    f"native media path changed while scanning: {relative}"
                )
            if observation is not None:
                collector.record_native(relative, observation)
            if full_digest is not None and collector.captures_full_file(relative):
                collector.record_full_file(
                    relative,
                    full_digest,
                    information.file_id,
                    information.link_count,
                )
        finally:
            if handle is not None:
                api.close(handle)
    if api.info(directory_handle, prefix or ".") != directory_info:
        raise NativeMediaReceiptError(
            f"native media directory changed while scanning: {prefix or '.'}"
        )


def _inventory_native_tree_windows(
    app_root: Path,
    scan_roots: tuple[str, ...],
    platform: str,
) -> dict[str, _NativeObservation]:
    api = _WindowsHandleApi()
    root_handle: int | None = None
    try:
        root_handle, root_info = api.open(
            app_root, ".", read_data=False
        )
        if not root_info.attributes & api.FILE_ATTRIBUTE_DIRECTORY:
            raise NativeMediaReceiptError("final app root is not a directory")
        for mandatory in MANDATORY_SCAN_PATHS[platform]:
            with _windows_relative_directory(api, app_root, mandatory):
                pass
        collector = _NativeCollector(platform)
        for scan_root in scan_roots:
            if scan_root == ".":
                _windows_walk_directory(
                    api,
                    app_root,
                    root_handle,
                    root_info,
                    "",
                    collector,
                )
            else:
                with _windows_relative_directory(
                    api, app_root, scan_root
                ) as (directory, handle, information):
                    _windows_walk_directory(
                        api,
                        directory,
                        handle,
                        information,
                        scan_root,
                        collector,
                    )
        collector.validate_full_inventory()
        if api.info(root_handle, ".") != root_info:
            raise NativeMediaReceiptError(
                "final app root changed while scanning"
            )
        return dict(sorted(collector.observations.items()))
    finally:
        if root_handle is not None:
            api.close(root_handle)


def _inventory_native_tree(
    app_root: Path,
    scan_roots: tuple[str, ...],
    platform: str,
) -> dict[str, _NativeObservation]:
    if os.name == "nt":
        return _inventory_native_tree_windows(app_root, scan_roots, platform)
    return _inventory_native_tree_posix(app_root, scan_roots, platform)


def _secure_read_relative_file_posix(
    app_root: Path, relative: str
) -> bytes:
    _require_posix_handle_apis()
    _inspect_app_root(app_root)
    root_before = app_root.lstat()
    root_fd: int | None = None
    try:
        root_fd = os.open(app_root, _posix_directory_flags())
        root_opened = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_opened.st_mode)
            or root_before.st_dev != root_opened.st_dev
            or root_before.st_ino != root_opened.st_ino
        ):
            raise NativeMediaReceiptError(
                "final app root changed while opening"
            )
        parent_relative, name = relative.rsplit("/", 1)
        with _posix_relative_directory(root_fd, parent_relative) as parent_fd:
            before = os.stat(
                name, dir_fd=parent_fd, follow_symlinks=False
            )
            if stat.S_ISLNK(before.st_mode):
                raise NativeMediaReceiptError(
                    f"symlink native media receipt path: {relative}"
                )
            if not stat.S_ISREG(before.st_mode):
                raise NativeMediaReceiptError(
                    f"non-file native media receipt path: {relative}"
                )
            if before.st_nlink != 1:
                raise NativeMediaReceiptError(
                    "native media receipt must have exactly one filesystem "
                    f"link: {relative}"
                )
            descriptor = os.open(
                name, _posix_file_flags(), dir_fd=parent_fd
            )
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or before.st_dev != opened.st_dev
                    or before.st_ino != opened.st_ino
                ):
                    raise NativeMediaReceiptError(
                        f"native media receipt changed while opening: {relative}"
                    )
                with os.fdopen(descriptor, "rb") as handle:
                    descriptor = -1
                    raw = handle.read()
                    after_open = os.fstat(handle.fileno())
                after_path = os.stat(
                    name, dir_fd=parent_fd, follow_symlinks=False
                )
                if (
                    _stat_identity(opened) != _stat_identity(after_open)
                    or _stat_identity(opened) != _stat_identity(after_path)
                ):
                    raise NativeMediaReceiptError(
                        f"native media receipt changed while reading: {relative}"
                    )
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        root_after = app_root.lstat()
        if _stat_identity(root_before) != _stat_identity(root_after):
            raise NativeMediaReceiptError(
                "final app root changed while reading component receipt"
            )
        return raw
    except NativeMediaReceiptError:
        raise
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"cannot securely read native media receipt {relative}: {exc}"
        ) from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _secure_read_relative_file_windows(
    app_root: Path, relative: str
) -> bytes:
    api = _WindowsHandleApi()
    root_handle: int | None = None
    file_handle: int | None = None
    try:
        root_handle, root_info = api.open(
            app_root, ".", read_data=False
        )
        if not root_info.attributes & api.FILE_ATTRIBUTE_DIRECTORY:
            raise NativeMediaReceiptError("final app root is not a directory")
        parent_relative, name = relative.rsplit("/", 1)
        with _windows_relative_directory(
            api, app_root, parent_relative
        ) as (parent, _, _):
            file_handle, opened = api.open(
                parent / name, relative, read_data=True
            )
            if opened.attributes & api.FILE_ATTRIBUTE_DIRECTORY:
                raise NativeMediaReceiptError(
                    f"non-file native media receipt path: {relative}"
                )
            if opened.link_count != 1:
                raise NativeMediaReceiptError(
                    "native media receipt must have exactly one filesystem "
                    f"link: {relative}"
                )
            descriptor = api.adopt_file_handle(file_handle, relative)
            file_handle = None
            with os.fdopen(descriptor, "rb") as handle:
                raw = handle.read()
                after = api.info(api.file_handle(handle.fileno()), relative)
            if after != opened:
                raise NativeMediaReceiptError(
                    f"native media receipt changed while reading: {relative}"
                )
        if api.info(root_handle, ".") != root_info:
            raise NativeMediaReceiptError(
                "final app root changed while reading component receipt"
            )
        return raw
    finally:
        if file_handle is not None:
            api.close(file_handle)
        if root_handle is not None:
            api.close(root_handle)


def _secure_read_relative_file(app_root: Path, relative: str) -> bytes:
    _safe_relative_path(relative)
    if os.name == "nt":
        return _secure_read_relative_file_windows(app_root, relative)
    return _secure_read_relative_file_posix(app_root, relative)


def _validate_allowlist_platform(
    allowlist: _ValidatedAllowlist, platform: str
) -> None:
    if not isinstance(allowlist, _ValidatedAllowlist):
        raise NativeMediaReceiptError("allowlist object was not validated")
    if allowlist.platform != platform:
        raise NativeMediaReceiptError(
            f"validated allowlist platform mismatch: expected {platform}, "
            f"found {allowlist.platform}"
        )


def _validate_allowlist_digest(
    allowlist: _ValidatedAllowlist,
    expected_allowlist_sha256: str,
) -> None:
    expected = _validate_sha256(
        expected_allowlist_sha256, "expected allowlist"
    )
    if allowlist.sha256 != expected:
        raise NativeMediaReceiptError(
            "validated allowlist SHA256 does not match "
            "--expected-allowlist-sha256"
        )


def scan_app(
    app_root: Path,
    platform: str,
    allowlist: _ValidatedAllowlist,
    expected_allowlist_sha256: str,
) -> dict[str, Any]:
    """Create a deterministic receipt from a final app or install root."""
    _platform_rule(platform)
    _validate_allowlist_platform(allowlist, platform)
    _validate_allowlist_digest(allowlist, expected_allowlist_sha256)
    expected = set(allowlist.files)
    _validate_core_paths(expected, platform, "allowlist")
    _validate_required_components(allowlist.files, "allowlist")
    _validate_component_contracts(allowlist.files, platform, "allowlist")
    _validate_bound_component_receipts(app_root, platform, allowlist)
    observed = _inventory_native_tree(
        app_root, allowlist.scan_roots, platform
    )
    discovered = set(observed)
    missing = sorted(expected - discovered)
    extra = sorted(discovered - expected)
    if missing:
        raise NativeMediaReceiptError(
            "missing native media paths: " + ", ".join(missing)
        )
    if extra:
        raise NativeMediaReceiptError(
            "extra native media paths: " + ", ".join(extra)
        )
    _validate_onnx_observed(observed, platform)

    files = []
    for relative in sorted(expected):
        observation = observed[relative]
        metadata = allowlist.files[relative]
        files.append({
            "bytes": observation.byte_count,
            "component": metadata["component"],
            "lineage_id": metadata["lineage_id"],
            "path": relative,
            "sha256": observation.sha256,
            "source_manifest_sha256": metadata["source_manifest_sha256"],
        })

    final_observed = _inventory_native_tree(
        app_root, allowlist.scan_roots, platform
    )
    if final_observed != observed:
        raise NativeMediaReceiptError(
            "native media tree changed while scanning"
        )
    _validate_bound_component_receipts(app_root, platform, allowlist)
    return {
        "allowlist_sha256": allowlist.sha256,
        "files": files,
        "platform": platform,
        "scan_roots": list(allowlist.scan_roots),
        "schema": RECEIPT_SCHEMA,
    }


def _load_receipt(
    path: Path,
    platform: str,
    allowlist: _ValidatedAllowlist,
    expected_allowlist_sha256: str,
) -> dict[str, Any]:
    _validate_allowlist_platform(allowlist, platform)
    _validate_allowlist_digest(allowlist, expected_allowlist_sha256)
    payload, raw = _read_json(path)
    if not isinstance(payload, dict):
        raise NativeMediaReceiptError("receipt root must be a JSON object")
    _exact_keys(
        payload,
        {
            "allowlist_sha256", "schema", "platform", "scan_roots", "files"
        },
        "receipt",
    )
    if payload["schema"] != RECEIPT_SCHEMA:
        raise NativeMediaReceiptError("receipt has wrong schema")
    if payload["platform"] != platform:
        raise NativeMediaReceiptError(
            f"receipt has wrong platform: expected {platform}, "
            f"found {payload['platform']}"
        )
    receipt_allowlist_sha = _validate_sha256(
        payload["allowlist_sha256"], "receipt allowlist"
    )
    if receipt_allowlist_sha != allowlist.sha256:
        raise NativeMediaReceiptError(
            "receipt allowlist SHA256 does not match validated allowlist"
        )
    receipt_roots = _normalize_scan_roots(payload["scan_roots"])
    if receipt_roots != allowlist.scan_roots or \
            payload["scan_roots"] != list(receipt_roots):
        raise NativeMediaReceiptError("receipt scan_roots do not match allowlist")
    entries = payload["files"]
    if not isinstance(entries, list):
        raise NativeMediaReceiptError("receipt files must be a JSON array")

    paths: list[str] = []
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise NativeMediaReceiptError("receipt file entry must be an object")
        _exact_keys(
            entry,
            {
                "bytes", "component", "lineage_id", "path", "sha256",
                "source_manifest_sha256",
            },
            "receipt file entry",
        )
        relative = _safe_relative_path(entry["path"])
        component = entry["component"]
        if not isinstance(component, str) or component not in COMPONENTS:
            raise NativeMediaReceiptError(
                f"invalid receipt component for native media path {relative}: "
                f"{component!r}"
            )
        size = entry["bytes"]
        if type(size) is not int or size <= 0:
            raise NativeMediaReceiptError(
                f"invalid receipt byte count for native media path: {relative}"
            )
        digest = entry["sha256"]
        source_sha = entry["source_manifest_sha256"]
        lineage_id = entry["lineage_id"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise NativeMediaReceiptError(
                f"invalid final SHA256 for native media path: {relative}"
            )
        if not isinstance(source_sha, str) or not SHA256_RE.fullmatch(source_sha):
            raise NativeMediaReceiptError(
                f"invalid source-manifest SHA256 for native media path: {relative}"
            )
        if not isinstance(lineage_id, str) or not LINEAGE_ID_RE.fullmatch(
                lineage_id):
            raise NativeMediaReceiptError(
                f"invalid lineage ID for native media path: {relative}"
            )
        paths.append(relative)
        by_path[relative] = entry

    _assert_no_path_collisions(paths, "receipt")
    if paths != sorted(paths):
        raise NativeMediaReceiptError("receipt native media paths are not sorted")
    _validate_core_paths(set(paths), platform, "receipt")
    _validate_required_components(by_path, "receipt")
    _validate_component_contracts(by_path, platform, "receipt")
    expected_paths = set(allowlist.files)
    actual_paths = set(paths)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("extra " + ", ".join(extra))
        raise NativeMediaReceiptError(
            "receipt paths do not match allowlist (" + "; ".join(details) + ")"
        )
    for relative, metadata in allowlist.files.items():
        entry = by_path[relative]
        if entry["component"] != metadata["component"]:
            raise NativeMediaReceiptError(
                f"receipt component drift: {relative}"
            )
        _validate_component_path(
            entry["component"], relative, platform, "receipt"
        )
        if (
            entry["lineage_id"] != metadata["lineage_id"]
            or entry["source_manifest_sha256"]
            != metadata["source_manifest_sha256"]
        ):
            raise NativeMediaReceiptError(
                f"receipt lineage metadata drift: {relative}"
            )
    if raw != canonical_json_bytes(payload):
        raise NativeMediaReceiptError("receipt JSON is not canonical")
    return payload


def verify_app(
    app_root: Path,
    platform: str,
    allowlist: _ValidatedAllowlist,
    receipt_path: Path,
    expected_allowlist_sha256: str,
) -> dict[str, Any]:
    """Verify a final app or install root against a canonical receipt."""
    expected = _load_receipt(
        receipt_path,
        platform,
        allowlist,
        expected_allowlist_sha256,
    )
    actual = scan_app(
        app_root,
        platform,
        allowlist,
        expected_allowlist_sha256,
    )
    expected_by_path = {entry["path"]: entry for entry in expected["files"]}
    drift = []
    for entry in actual["files"]:
        prior = expected_by_path[entry["path"]]
        if entry["bytes"] != prior["bytes"] or \
                entry["sha256"] != prior["sha256"]:
            drift.append(entry["path"])
    if drift:
        raise NativeMediaReceiptError(
            "native media hash/size drift: " + ", ".join(drift)
        )
    return actual


def _write_canonical(path: Path, payload: dict[str, Any]) -> None:
    data = canonical_json_bytes(payload)
    if str(path) == "-":
        sys.stdout.buffer.write(data)
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        raise NativeMediaReceiptError(
            f"cannot write native media receipt {path}: {exc}"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan or verify final installed native media bytes",
        epilog=(
            "Security boundary: the required allowlist digest proves equality "
            "to a caller-selected allowlist only. The release workflow must "
            "separately verify every referenced source manifest and signed "
            "attestation. Mac staging must replace validated in-tree PyInstaller "
            "library symlinks with regular byte copies before this fail-closed "
            "scanner runs; the scanner never follows links."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--app-root", type=Path, required=True)
        sub.add_argument(
            "--platform", choices=sorted(PLATFORM_RULES), required=True
        )
        sub.add_argument("--allowlist", type=Path, required=True)
        sub.add_argument(
            "--expected-allowlist-sha256",
            required=True,
            help=(
                "trusted SHA256 of the exact allowlist bytes; source manifests "
                "and signed attestations still require separate verification"
            ),
        )
        if command == "scan":
            sub.add_argument("--output", type=Path, required=True)
        else:
            sub.add_argument("--receipt", type=Path, required=True)
            sub.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        allowlist = load_allowlist(
            args.allowlist,
            args.platform,
            args.expected_allowlist_sha256,
        )
        if args.command == "scan":
            payload = scan_app(
                args.app_root,
                args.platform,
                allowlist,
                args.expected_allowlist_sha256,
            )
            _write_canonical(args.output, payload)
        else:
            payload = verify_app(
                args.app_root,
                args.platform,
                allowlist,
                args.receipt,
                args.expected_allowlist_sha256,
            )
            if args.output is not None:
                _write_canonical(args.output, payload)
    except NativeMediaReceiptError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
