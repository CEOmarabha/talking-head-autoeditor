#!/usr/bin/env python3
"""Materialize AutoEditor's pinned local vision model from Chromium CacheStorage.

This tool is deliberately network-free.  It accepts only the nine cache
objects whose embedded request URLs name the exact reviewed Hugging Face
revision, verifies their immutable byte identities and response evidence, and
writes a closed model-pack lock beside the extracted files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path


MODEL_ID = "HuggingFaceTB/SmolVLM2-256M-Video-Instruct"
MODEL_REVISION = "067788b187b95ebe7b2e040b3e4299e342e5b8fd"
MODEL_DTYPE = "q4"
MODEL_LICENSE = "Apache-2.0"
MODEL_PACK_SCHEMA_VERSION = "autoeditor-local-vision-model-pack/v1"
# Keep the on-disk directory short enough for conservative Windows path limits;
# the lock binds the complete model id and 40-character revision.
MODEL_PACK_DIRECTORY = "smolvlm2-067788b187b95ebe"
MODEL_PACK_LOCK_FILE = "model-pack.lock.json"
SIMPLE_CACHE_INITIAL_MAGIC = 0xFCFB6D1BA7725C30
SIMPLE_CACHE_FINAL_MAGIC = 0xF4FA6F45970D41D8
SIMPLE_CACHE_VERSION = 5
SIMPLE_CACHE_HEADER_BYTES = 24


class CachedVisionModelError(RuntimeError):
    """The local cache cannot prove the exact pinned model pack."""


@dataclass(frozen=True)
class ExpectedFile:
    path: str
    bytes: int
    sha256: str
    etag: str

    @property
    def url(self) -> str:
        return (
            f"https://huggingface.co/{MODEL_ID}/resolve/"
            f"{MODEL_REVISION}/{self.path}"
        )


EXPECTED_FILES = (
    ExpectedFile(
        "config.json", 3812,
        "756cb7d37d7659c9d5a71c563f9d2530f9dd674ab7e909d8d0dd5b1a2d3e8317",
        'W/"182b1b0f71941ed48c1a8c983b88ad877bcc3f4c"',
    ),
    ExpectedFile(
        "generation_config.json", 136,
        "34835060c9f0f74d1acb456cc72ca32746d3843d9eb5f578f9cbffac1d2eb840",
        '"eace9aa6d392fd94dbe0c90825074c53fd7ecd4a"',
    ),
    ExpectedFile(
        "onnx/decoder_model_merged_q4.onnx", 86894835,
        "ce4021b8e2242cbd4caac06b259e1b15e085c6a4b900af40f1e0abec7a6c6df2",
        '"37951674e07b2dd9a5645b376acaffaa43ab89601f780eb5b3fd390bc514b393"',
    ),
    ExpectedFile(
        "onnx/embed_tokens_q4.onnx", 113541438,
        "64f62db97ca38a44b5ed8a225b75dbede2d069c9afc76696d63b89300d5edcd2",
        '"141288d2fbdf706d95f628b9633e0b755bf91c781d3dd080f8e971351924f910"',
    ),
    ExpectedFile(
        "onnx/vision_encoder_q4.onnx", 63784944,
        "253d225bf96b6203118d16e57bb2890c2dc542dd989d484cb9541dc4d4ae719b",
        '"0484d85223cbb45c742ad93c3cd7213c583cc36b9afde743a81f874dce3e6aee"',
    ),
    ExpectedFile(
        "preprocessor_config.json", 599,
        "149e315d9410368e5491455bb06e0f763426e9e56cca731c13b24404a29b6374",
        '"bf7669a38692ad141d333db3be18bd55cb6e2c59"',
    ),
    ExpectedFile(
        "processor_config.json", 67,
        "f3ad45028447b3562b4752be0d5916d6806c1ef589091a469608dcf0faa1737c",
        '"83df8c48da1f41e1a9129a4bc2aba000eb2b529f"',
    ),
    ExpectedFile(
        "tokenizer.json", 3548256,
        "5ece781dc8d2b2f3e2f289ca0ae50b17cfc27dd27bfe7971bb8241e0b964331a",
        'W/"a4005d1cf3170a31600a5c96f95768166cbc2b28"',
    ),
    ExpectedFile(
        "tokenizer_config.json", 28626,
        "dd9ce2ab89a3dd881bd9378f1a79b943a064b9275a7e1706d5b7b47b68977913",
        'W/"e4042a1126290fdb96ece2a4ad8dd7108c5de484"',
    ),
)
EXPECTED_BY_URL = {item.url: item for item in EXPECTED_FILES}


def _fail(message: str) -> None:
    raise CachedVisionModelError(message)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _sha256_file(path: Path, *, offset: int = 0, length: int | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        handle.seek(offset)
        remaining = length
        while remaining is None or remaining > 0:
            size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
        if remaining not in (None, 0):
            _fail("cached model body ended before its locked length")
    return digest.hexdigest()


def _read_cache_header(path: Path) -> tuple[str, int]:
    with path.open("rb") as handle:
        header = handle.read(SIMPLE_CACHE_HEADER_BYTES)
        if len(header) != SIMPLE_CACHE_HEADER_BYTES:
            _fail("cached model object has a truncated simple-cache header")
        magic, version, key_length, _key_hash, reserved = struct.unpack(
            "<QIIII", header,
        )
        if (magic != SIMPLE_CACHE_INITIAL_MAGIC or version != SIMPLE_CACHE_VERSION
                or reserved != 0 or key_length < 1 or key_length > 1024):
            _fail("cached model object has an unsupported simple-cache header")
        key = handle.read(key_length)
    try:
        url = key.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CachedVisionModelError("cached model URL is not UTF-8") from error
    return url, SIMPLE_CACHE_HEADER_BYTES + key_length


def _validate_cached_object(path: Path, expected: ExpectedFile) -> int:
    before = path.stat()
    if (not stat.S_ISREG(before.st_mode) or path.is_symlink()
            or before.st_size <= SIMPLE_CACHE_HEADER_BYTES + expected.bytes):
        _fail(f"cached object for {expected.path} is unavailable")
    url, body_offset = _read_cache_header(path)
    if url != expected.url:
        _fail(f"cached object URL drifted for {expected.path}")
    body_end = body_offset + expected.bytes
    if body_end + 8 > before.st_size:
        _fail(f"cached object body is truncated for {expected.path}")
    if _sha256_file(path, offset=body_offset, length=expected.bytes) != expected.sha256:
        _fail(f"cached object bytes drifted for {expected.path}")
    with path.open("rb") as handle:
        handle.seek(body_offset)
        prefix = handle.read(2)
        handle.seek(body_end)
        trailer = handle.read()
    if (len(trailer) < 64
            or struct.unpack_from("<Q", trailer, 0)[0] != SIMPLE_CACHE_FINAL_MAGIC
            or b"content-length" not in trailer
            or str(expected.bytes).encode("ascii") not in trailer
            or expected.etag.encode("ascii") not in trailer):
        _fail(f"cached response evidence drifted for {expected.path}")
    if expected.path.endswith(".json"):
        with path.open("rb") as handle:
            handle.seek(body_offset)
            payload = handle.read(expected.bytes)
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CachedVisionModelError(
                f"cached JSON is invalid for {expected.path}",
            ) from error
        if not isinstance(value, dict):
            _fail(f"cached JSON root is invalid for {expected.path}")
        if MODEL_REVISION.encode("ascii") not in trailer:
            _fail(f"cached response revision is absent for {expected.path}")
    elif prefix != b"\x08\x07":
        _fail(f"cached ONNX payload is invalid for {expected.path}")
    after = path.stat()
    if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
            or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)):
        _fail(f"cached object changed while reading {expected.path}")
    return body_offset


def _cache_objects(cache_storage: Path) -> dict[str, tuple[Path, int]]:
    if (not cache_storage.is_absolute() or not cache_storage.is_dir()
            or cache_storage.is_symlink()):
        _fail("CacheStorage root must be an existing absolute directory")
    found: dict[str, tuple[Path, int]] = {}
    for candidate in sorted(cache_storage.rglob("*_0")):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            url, _ = _read_cache_header(candidate)
        except CachedVisionModelError:
            continue
        expected = EXPECTED_BY_URL.get(url)
        if expected is None:
            continue
        if expected.path in found:
            _fail(f"cached model URL is duplicated for {expected.path}")
        found[expected.path] = (
            candidate, _validate_cached_object(candidate, expected),
        )
    missing = [item.path for item in EXPECTED_FILES if item.path not in found]
    if missing:
        _fail("pinned cached model objects are missing: " + ", ".join(missing))
    return found


def _lock() -> dict[str, object]:
    files = [{
        "bytes": item.bytes,
        "path": item.path,
        "sha256": item.sha256,
        "source_etag": item.etag,
        "source_url": item.url,
    } for item in EXPECTED_FILES]
    tree_contract = {
        "dtype": MODEL_DTYPE,
        "files": files,
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
    }
    return {
        "schema_version": MODEL_PACK_SCHEMA_VERSION,
        "model": {
            "dtype": MODEL_DTYPE,
            "id": MODEL_ID,
            "license": MODEL_LICENSE,
            "revision": MODEL_REVISION,
        },
        "files": files,
        "total_bytes": sum(item.bytes for item in EXPECTED_FILES),
        "tree_sha256": hashlib.sha256(_canonical_bytes(tree_contract)).hexdigest(),
    }


def _copy_body(source: Path, offset: int, expected: ExpectedFile, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(target, flags, 0o644)
    try:
        with source.open("rb") as handle:
            handle.seek(offset)
            remaining = expected.bytes
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    _fail(f"cached body ended while extracting {expected.path}")
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written < 1:
                        _fail(f"cached body write failed for {expected.path}")
                    view = view[written:]
                remaining -= len(chunk)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if target.stat().st_size != expected.bytes or _sha256_file(target) != expected.sha256:
        target.unlink(missing_ok=True)
        _fail(f"extracted model identity drifted for {expected.path}")


def extract_cached_model(cache_storage: Path, output: Path) -> dict[str, object]:
    cache_storage = cache_storage.resolve()
    if not output.is_absolute() or output.exists() or output.is_symlink():
        _fail("model-pack output must be a new absolute path")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    objects = _cache_objects(cache_storage)
    temporary = Path(tempfile.mkdtemp(
        prefix=f".{output.name}.", dir=output.parent,
    ))
    try:
        repository = temporary / MODEL_ID
        for expected in EXPECTED_FILES:
            source, offset = objects[expected.path]
            _copy_body(source, offset, expected, repository / expected.path)
        lock = _lock()
        lock_path = temporary / MODEL_PACK_LOCK_FILE
        lock_path.write_bytes(_canonical_bytes(lock) + b"\n")
        os.chmod(lock_path, 0o644)
        os.replace(temporary, output)
        return {
            "lock": lock,
            "lock_sha256": _sha256_file(output / MODEL_PACK_LOCK_FILE),
            "output": str(output),
        }
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_model_pack(output: Path) -> dict[str, object]:
    if (not output.is_absolute() or not output.is_dir()
            or output.is_symlink()):
        _fail("model-pack root must be an existing absolute directory")
    output = output.resolve()
    lock_path = output / MODEL_PACK_LOCK_FILE
    try:
        actual_lock_bytes = lock_path.read_bytes()
        actual_lock = json.loads(actual_lock_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CachedVisionModelError("model-pack lock is unavailable") from error
    expected_lock = _lock()
    if (actual_lock != expected_lock
            or actual_lock_bytes != _canonical_bytes(expected_lock) + b"\n"):
        _fail("model-pack lock drifted")
    repository = output / MODEL_ID
    actual_inventory: list[str] = []
    for item in output.rglob("*"):
        if item.is_symlink():
            _fail("model-pack inventory contains a symbolic link")
        if item.is_file():
            actual_inventory.append(item.relative_to(output).as_posix())
        elif not item.is_dir():
            _fail("model-pack inventory contains an unsupported entry")
    expected_inventory = sorted([
        MODEL_PACK_LOCK_FILE,
        *(f"{MODEL_ID}/{item.path}" for item in EXPECTED_FILES),
    ])
    if sorted(actual_inventory) != expected_inventory:
        _fail("model-pack file inventory drifted")
    for expected in EXPECTED_FILES:
        target = repository / expected.path
        if (target.is_symlink() or target.stat().st_size != expected.bytes
                or _sha256_file(target) != expected.sha256):
            _fail(f"model-pack file drifted for {expected.path}")
    return {
        "lock": expected_lock,
        "lock_sha256": hashlib.sha256(actual_lock_bytes).hexdigest(),
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract or verify the pinned offline vision model pack",
    )
    parser.add_argument("--cache-storage", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.verify_only:
        if arguments.cache_storage is not None:
            parser.error("--cache-storage is not accepted with --verify-only")
        result = verify_model_pack(arguments.output)
    else:
        if arguments.cache_storage is None:
            parser.error("--cache-storage is required when extracting")
        result = extract_cached_model(arguments.cache_storage, arguments.output)
    public = {
        "event": "autoeditor-local-vision-model-pack",
        "schema_version": MODEL_PACK_SCHEMA_VERSION,
        "files": len(EXPECTED_FILES),
        "total_bytes": result["lock"]["total_bytes"],
        "tree_sha256": result["lock"]["tree_sha256"],
        "lock_sha256": result["lock_sha256"],
    }
    print(json.dumps(public, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
