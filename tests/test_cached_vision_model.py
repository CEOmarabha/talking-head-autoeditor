from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "extract_cached_vision_model.py"
SPEC = importlib.util.spec_from_file_location(
    "autoeditor_cached_vision_model_test_module", SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
vision_pack = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = vision_pack
SPEC.loader.exec_module(vision_pack)

PACK_ROOT = (
    ROOT / "packaging" / "vision-model-packs" /
    vision_pack.MODEL_PACK_DIRECTORY
)
LOCK_SHA256 = (
    "adc37855602e89d80260fbb8768aa2b87fb4b928f34d9765a4e6c267f554a1fa"
)
TREE_SHA256 = (
    "5ab9f376a07e111ed08957c6db3847e4531b55589f6dbfe3fdb35619171bbc21"
)


def _cache_object(expected, payload: bytes) -> bytes:
    url = expected.url.encode("utf-8")
    header = struct.pack(
        "<QIIII",
        vision_pack.SIMPLE_CACHE_INITIAL_MAGIC,
        vision_pack.SIMPLE_CACHE_VERSION,
        len(url),
        0,
        0,
    )
    evidence = (
        struct.pack("<Q", vision_pack.SIMPLE_CACHE_FINAL_MAGIC)
        + b"\x00" * 24
        + b"content-length: " + str(len(payload)).encode("ascii")
        + b"\netag: " + expected.etag.encode("ascii")
        + b"\nx-repo-commit: " + vision_pack.MODEL_REVISION.encode("ascii")
        + b"\x00" * 32
    )
    return header + url + payload + evidence


class CachedVisionModelTests(unittest.TestCase):
    def test_checked_in_model_pack_is_exact_and_network_free(self) -> None:
        result = vision_pack.verify_model_pack(PACK_ROOT.resolve())
        self.assertEqual(result["lock_sha256"], LOCK_SHA256)
        self.assertEqual(result["lock"]["tree_sha256"], TREE_SHA256)
        self.assertEqual(result["lock"]["total_bytes"], 267_802_713)
        self.assertEqual(len(result["lock"]["files"]), 9)

        syntax = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(syntax)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (
                node.names if isinstance(node, ast.Import)
                else [ast.alias(name=node.module or "")]
            )
        }
        self.assertTrue({"urllib", "requests", "httpx", "huggingface_hub"}
                        .isdisjoint(imports))

    def test_synthetic_chromium_object_extracts_and_tamper_fails(self) -> None:
        payload = b'{"model_type":"smolvlm","fixture":true}'
        expected = vision_pack.ExpectedFile(
            path="config.json",
            bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            etag='"fixed-fixture-etag"',
        )
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root).resolve()
            cache = root / "CacheStorage"
            cache.mkdir()
            (cache / "fixture_0").write_bytes(_cache_object(expected, payload))
            output = root / "model-pack"
            with (
                mock.patch.object(vision_pack, "EXPECTED_FILES", (expected,)),
                mock.patch.object(
                    vision_pack, "EXPECTED_BY_URL", {expected.url: expected},
                ),
            ):
                produced = vision_pack.extract_cached_model(cache, output)
                self.assertEqual(produced["lock"]["files"][0]["source_url"],
                                 expected.url)
                self.assertEqual(
                    (output / vision_pack.MODEL_ID / expected.path).read_bytes(),
                    payload,
                )
                verified = vision_pack.verify_model_pack(output)
                self.assertEqual(verified["lock_sha256"],
                                 produced["lock_sha256"])

                extra = output / "unlocked.bin"
                extra.write_bytes(b"not allowed")
                with self.assertRaisesRegex(
                    vision_pack.CachedVisionModelError, "inventory drifted",
                ):
                    vision_pack.verify_model_pack(output)
                extra.unlink()

                lock_path = output / vision_pack.MODEL_PACK_LOCK_FILE
                canonical_lock = lock_path.read_bytes()
                parsed = json.loads(canonical_lock)
                lock_path.write_text(
                    json.dumps(parsed, indent=2), encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    vision_pack.CachedVisionModelError, "lock drifted",
                ):
                    vision_pack.verify_model_pack(output)
                lock_path.write_bytes(canonical_lock)

                model_file = output / vision_pack.MODEL_ID / expected.path
                model_file.write_bytes(payload[:-1] + b"X")
                with self.assertRaisesRegex(
                    vision_pack.CachedVisionModelError, "file drifted",
                ):
                    vision_pack.verify_model_pack(output)

    def test_wrong_revision_cache_object_is_not_admitted(self) -> None:
        payload = b'{"fixture":true}'
        expected = vision_pack.ExpectedFile(
            "config.json", len(payload), hashlib.sha256(payload).hexdigest(),
            '"fixture-etag"',
        )
        wrong_url = expected.url.replace(vision_pack.MODEL_REVISION, "0" * 40)
        raw = _cache_object(expected, payload).replace(
            expected.url.encode("utf-8"), wrong_url.encode("utf-8"), 1,
        )
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root).resolve()
            cache = root / "CacheStorage"
            cache.mkdir()
            (cache / "wrong_0").write_bytes(raw)
            with (
                mock.patch.object(vision_pack, "EXPECTED_FILES", (expected,)),
                mock.patch.object(
                    vision_pack, "EXPECTED_BY_URL", {expected.url: expected},
                ),
                self.assertRaisesRegex(
                    vision_pack.CachedVisionModelError,
                    "pinned cached model objects are missing",
                ),
            ):
                vision_pack.extract_cached_model(cache, root / "model-pack")


if __name__ == "__main__":
    unittest.main()
