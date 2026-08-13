from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import unittest

from autoeditor.sequence_plan import (
    COMPILE_RECEIPT_SCHEMA_VERSION,
    MAX_SEGMENTS,
    MIN_SEQUENCE_DURATION_MS,
    ROLES,
    SEQUENCE_PLAN_JSON_SCHEMA,
    SEQUENCE_PLAN_SCHEMA_VERSION,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    SequencePlanError,
    canonical_json,
    canonical_source_manifest_json,
    compile_receipt_sha256,
    compile_sequence_plan,
    sequence_plan_sha256,
    source_manifest_sha256,
    validate_sequence_plan,
)


def _source(source_id: str, digest_character: str, duration_ms: int) -> dict:
    return {
        "source_id": source_id,
        "sha256": digest_character * 64,
        "duration_ms": duration_ms,
    }


def _manifest() -> dict:
    return {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sources": [
            _source("cam-a", "a", 10_000),
            _source("screen-b", "b", 20_000),
            _source("reaction-c", "c", 5_000),
        ],
    }


def _segment(
    segment_id: str,
    source_id: str,
    source_sha256: str,
    start_ms: int,
    end_ms: int,
    role: str = "development",
    *,
    speech_anchor: dict | None = None,
) -> dict:
    return {
        "segment_id": segment_id,
        "source_id": source_id,
        "source_sha256": source_sha256,
        "source_start_ms": start_ms,
        "source_end_ms": end_ms,
        "role": role,
        "reason": f"Use {segment_id} because it advances the sequence.",
        "speech_anchor": speech_anchor,
        "transition": {"kind": "hard_cut"},
    }


def _plan() -> dict:
    manifest = _manifest()
    by_id = {item["source_id"]: item for item in manifest["sources"]}
    return {
        "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
        # Deliberately not source-id sorted. Source inventory is a set; sequence
        # order belongs exclusively to segments.
        "sources": [by_id["screen-b"], by_id["cam-a"], by_id["reaction-c"]],
        "target_duration": {"min_ms": 6_000, "max_ms": 6_000},
        "segments": [
            _segment(
                "seg-hook",
                "screen-b",
                "b" * 64,
                1_250,
                3_000,
                "hook",
                speech_anchor={
                    "start_word": 4,
                    "end_word": 7,
                    "text": "Here is the exact hook",
                },
            ),
            _segment("seg-demo", "cam-a", "a" * 64, 500, 2_500,
                     "demonstration"),
            _segment("seg-react", "reaction-c", "c" * 64, 0, 1_000,
                     "reaction"),
            # Deliberately overlaps seg-hook in the same source. Overlap and
            # repeated source selection are valid sequence-edit operations.
            _segment("seg-close", "screen-b", "b" * 64, 1_500, 2_750,
                     "closer"),
        ],
    }


class SequencePlanContractTests(unittest.TestCase):
    def assert_rejected(self, plan: object, manifest: object | None = None):
        with self.assertRaises(SequencePlanError):
            validate_sequence_plan(
                plan, _manifest() if manifest is None else manifest
            )

    def test_arbitrary_selection_reordering_repeat_and_overlap_are_valid(self):
        raw = _plan()
        clean = validate_sequence_plan(raw, _manifest())

        self.assertEqual(
            [item["source_id"] for item in clean["sources"]],
            ["cam-a", "reaction-c", "screen-b"],
        )
        self.assertEqual(
            [item["source_id"] for item in clean["segments"]],
            ["screen-b", "cam-a", "reaction-c", "screen-b"],
        )
        self.assertEqual(clean["segments"][0]["source_end_ms"], 3_000)
        self.assertEqual(clean["segments"][3]["source_start_ms"], 1_500)
        self.assertIsNot(clean, raw)
        self.assertIsNot(clean["segments"], raw["segments"])

    def test_compile_derives_exact_ffmpeg_tokens_and_bound_receipt(self):
        result = compile_sequence_plan(_plan(), _manifest())
        segments = result["ffmpeg_segments"]
        receipt = result["receipt"]

        self.assertEqual(len(segments), 4)
        self.assertEqual(
            segments[0]["ffmpeg_trim_args"],
            ["-ss", "1.250", "-t", "1.750"],
        )
        self.assertEqual(segments[0]["duration_ms"], 1_750)
        self.assertEqual(segments[0]["transition"], {"kind": "hard_cut"})
        self.assertEqual(receipt["schema_version"], COMPILE_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["total_duration_ms"], 6_000)
        self.assertEqual(receipt["segment_count"], 4)
        self.assertEqual(
            receipt["ordered_segment_ids"],
            ["seg-hook", "seg-demo", "seg-react", "seg-close"],
        )
        self.assertEqual(receipt["time_base"], {"numerator": 1,
                                                 "denominator": 1_000})
        self.assertEqual(
            result["receipt_sha256"], compile_receipt_sha256(receipt)
        )

        expected_compiled_hash = hashlib.sha256(
            json.dumps(
                segments,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(receipt["compiled_segments_sha256"],
                         expected_compiled_hash)

    def test_compilation_is_deterministic_across_manifest_and_key_order(self):
        plan = _plan()
        reversed_keys = {
            key: plan[key] for key in reversed(list(plan))
        }
        manifest = _manifest()
        manifest["sources"].reverse()

        first = compile_sequence_plan(plan, _manifest())
        second = compile_sequence_plan(reversed_keys, manifest)
        self.assertEqual(first, second)

    def test_exact_keys_are_required_at_every_schema_level(self):
        mutations = []

        plan = _plan()
        plan["comment"] = "unsupported"
        mutations.append(plan)

        plan = _plan()
        del plan["target_duration"]["max_ms"]
        mutations.append(plan)

        plan = _plan()
        plan["sources"][0]["path"] = "untrusted.mp4"
        mutations.append(plan)

        plan = _plan()
        plan["segments"][0]["confidence"] = 0.9
        mutations.append(plan)

        plan = _plan()
        plan["segments"][0]["transition"]["duration_ms"] = 0
        mutations.append(plan)

        plan = _plan()
        plan["segments"][0]["speech_anchor"]["language"] = "en"
        mutations.append(plan)

        for index, invalid in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_rejected(invalid)

        manifest = _manifest()
        manifest["generated_at"] = "now"
        self.assert_rejected(_plan(), manifest)

    def test_schema_versions_and_transition_are_closed(self):
        plan = _plan()
        plan["schema_version"] = "autoeditor-sequence-plan/v2"
        self.assert_rejected(plan)

        manifest = _manifest()
        manifest["schema_version"] = "autoeditor-source-manifest/v2"
        self.assert_rejected(_plan(), manifest)

        for transition in ("hard_cut", {"kind": "crossfade"}, None):
            plan = _plan()
            plan["segments"][0]["transition"] = transition
            with self.subTest(transition=transition):
                self.assert_rejected(plan)

    def test_lists_have_closed_cardinality(self):
        plan = _plan()
        plan["sources"] = []
        self.assert_rejected(plan)

        sources = [
            _source(f"source-{index}", f"{index:064x}"[-1], 1_000)
            for index in range(20)
        ]
        # Ensure hashes are actually unique even where the final hex digit
        # would otherwise repeat.
        for index, source in enumerate(sources):
            source["sha256"] = f"{index + 1:064x}"
        plan = {
            "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
            "sources": sources,
            "target_duration": {"min_ms": 5_000, "max_ms": 5_000},
            "segments": [_segment("only", "source-0", sources[0]["sha256"],
                                  0, 1_000) for _ in range(5)],
        }
        for index, segment in enumerate(plan["segments"]):
            segment["segment_id"] = f"only-{index}"
        manifest = {
            "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
            "sources": copy.deepcopy(sources),
        }
        validate_sequence_plan(plan, manifest)

        for too_short in (34, 4_999):
            short_plan = _plan()
            short_plan["target_duration"] = {
                "min_ms": too_short, "max_ms": too_short,
            }
            self.assert_rejected(short_plan)

        extra = _source("source-20", "f", 1_000)
        plan["sources"].append(extra)
        manifest["sources"].append(copy.deepcopy(extra))
        self.assert_rejected(plan, manifest)

        plan = _plan()
        plan["segments"] = []
        self.assert_rejected(plan)

        plan = _plan()
        template = plan["segments"][0]
        plan["segments"] = []
        for index in range(MAX_SEGMENTS + 1):
            segment = copy.deepcopy(template)
            segment["segment_id"] = f"seg-{index}"
            plan["segments"].append(segment)
        plan["target_duration"] = {
            "min_ms": (MAX_SEGMENTS + 1) * 1_750,
            "max_ms": (MAX_SEGMENTS + 1) * 1_750,
        }
        self.assert_rejected(plan)

    def test_source_and_segment_ids_are_ascii_closed_and_unique(self):
        for invalid_id in ("", " has-space", "slash/id", "é", "x" * 65):
            plan = _plan()
            old = plan["sources"][0]["source_id"]
            plan["sources"][0]["source_id"] = invalid_id
            for segment in plan["segments"]:
                if segment["source_id"] == old:
                    segment["source_id"] = invalid_id
            manifest = _manifest()
            for source in manifest["sources"]:
                if source["source_id"] == old:
                    source["source_id"] = invalid_id
            with self.subTest(invalid_id=invalid_id):
                self.assert_rejected(plan, manifest)

        plan = _plan()
        plan["segments"][1]["segment_id"] = "seg-hook"
        self.assert_rejected(plan)

        plan = _plan()
        plan["sources"][1]["source_id"] = "screen-b"
        self.assert_rejected(plan)

        plan = _plan()
        plan["segments"][0]["segment_id"] = "x" * 97
        self.assert_rejected(plan)

    def test_hashes_must_be_full_lowercase_hex_and_unambiguous(self):
        for bad_hash in ("a" * 63, "A" * 64, "g" * 64, 123):
            plan = _plan()
            plan["sources"][0]["sha256"] = bad_hash
            with self.subTest(bad_hash=bad_hash):
                self.assert_rejected(plan)

        plan = _plan()
        plan["sources"][1]["sha256"] = plan["sources"][0]["sha256"]
        self.assert_rejected(plan)

        plan = _plan()
        plan["segments"][0]["source_sha256"] = "a" * 64
        self.assert_rejected(plan)

    def test_every_role_is_accepted_and_unknown_role_is_rejected(self):
        for role in sorted(ROLES):
            plan = _plan()
            plan["segments"][0]["role"] = role
            with self.subTest(role=role):
                validate_sequence_plan(plan, _manifest())

        plan = _plan()
        plan["segments"][0]["role"] = "viral_magic"
        self.assert_rejected(plan)

    def test_reason_is_nfkc_whitespace_normalized_and_bounded(self):
        plan = _plan()
        plan["segments"][0]["reason"] = "  Use\tthe  fullwidth Ａ proof.  "
        clean = validate_sequence_plan(plan, _manifest())
        self.assertEqual(clean["segments"][0]["reason"],
                         "Use the fullwidth A proof.")

        for reason in ("", "---", 7, "x" * 501):
            plan = _plan()
            plan["segments"][0]["reason"] = reason
            with self.subTest(reason=reason):
                self.assert_rejected(plan)

    def test_optional_speech_anchor_has_inclusive_exact_word_bounds(self):
        plan = _plan()
        plan["segments"][0]["speech_anchor"] = None
        validate_sequence_plan(plan, _manifest())

        plan = _plan()
        plan["segments"][0]["speech_anchor"]["text"] = (
            "  Here is\t the fullwidth Ｈook  "
        )
        clean = validate_sequence_plan(plan, _manifest())
        self.assertEqual(
            clean["segments"][0]["speech_anchor"],
            {"start_word": 4, "end_word": 7,
             "text": "Here is the fullwidth Hook"},
        )

        invalid_anchors = [
            {},
            {"start_word": 4, "end_word": 3, "text": "reversed"},
            {"start_word": True, "end_word": 3, "text": "boolean"},
            {"start_word": 0, "end_word": 0, "text": "---"},
            {"start_word": 0, "end_word": 0, "text": "x" * 1_001},
        ]
        for anchor in invalid_anchors:
            plan = _plan()
            plan["segments"][0]["speech_anchor"] = anchor
            with self.subTest(anchor=anchor):
                self.assert_rejected(plan)

    def test_source_bounds_are_positive_exact_integer_milliseconds(self):
        mutations = (
            ("source_start_ms", -1),
            ("source_start_ms", True),
            ("source_start_ms", 0.5),
            ("source_end_ms", 1_250),
            ("source_end_ms", 20_001),
        )
        for key, value in mutations:
            plan = _plan()
            plan["segments"][0][key] = value
            with self.subTest(key=key, value=value):
                self.assert_rejected(plan)

        plan = _plan()
        plan["sources"][0]["duration_ms"] = 20_000.0
        self.assert_rejected(plan)

        plan = _plan()
        plan["segments"][0]["source_end_ms"] = 20_000
        plan["target_duration"] = {"min_ms": 23_000, "max_ms": 23_000}
        validate_sequence_plan(plan, _manifest())

    def test_source_manifest_binding_is_exact_but_order_independent(self):
        manifest = _manifest()
        manifest["sources"].reverse()
        validate_sequence_plan(_plan(), manifest)

        for mutation in ("missing", "hash", "duration", "extra"):
            manifest = _manifest()
            if mutation == "missing":
                manifest["sources"].pop()
            elif mutation == "hash":
                manifest["sources"][0]["sha256"] = "d" * 64
            elif mutation == "duration":
                manifest["sources"][0]["duration_ms"] += 1
            else:
                manifest["sources"].append(_source("extra", "d", 1_000))
            with self.subTest(mutation=mutation):
                self.assert_rejected(_plan(), manifest)

    def test_target_range_is_inclusive_and_sum_is_exact(self):
        for target in (
            {"min_ms": 6_000, "max_ms": 6_000},
            {"min_ms": 5_999, "max_ms": 6_000},
            {"min_ms": 6_000, "max_ms": 6_001},
        ):
            plan = _plan()
            plan["target_duration"] = target
            validate_sequence_plan(plan, _manifest())

        for target in (
            {"min_ms": 6_001, "max_ms": 7_000},
            {"min_ms": 1, "max_ms": 5_999},
            {"min_ms": 7_000, "max_ms": 6_000},
            {"min_ms": True, "max_ms": 6_000},
            {"min_ms": 6_000.0, "max_ms": 6_000},
        ):
            plan = _plan()
            plan["target_duration"] = target
            with self.subTest(target=target):
                self.assert_rejected(plan)

    def test_canonical_plan_hash_normalizes_semantic_text_and_object_order(self):
        plan = _plan()
        reversed_plan = {key: plan[key] for key in reversed(list(plan))}
        reversed_plan["sources"] = list(reversed(reversed_plan["sources"]))
        reversed_plan["segments"][0]["reason"] = (
            "Use seg-hook because it advances the sequence."
        )
        self.assertEqual(sequence_plan_sha256(plan),
                         sequence_plan_sha256(reversed_plan))
        self.assertEqual(canonical_json(plan), canonical_json(reversed_plan))

        reordered_segments = copy.deepcopy(plan)
        reordered_segments["segments"][0], reordered_segments["segments"][1] = (
            reordered_segments["segments"][1],
            reordered_segments["segments"][0],
        )
        self.assertNotEqual(sequence_plan_sha256(plan),
                            sequence_plan_sha256(reordered_segments))

    def test_source_manifest_hash_is_inventory_order_independent(self):
        manifest = _manifest()
        reordered = copy.deepcopy(manifest)
        reordered["sources"].reverse()
        self.assertEqual(source_manifest_sha256(manifest),
                         source_manifest_sha256(reordered))
        self.assertEqual(canonical_source_manifest_json(manifest),
                         canonical_source_manifest_json(reordered))

    def test_receipt_hash_binds_plan_manifest_compilation_order_and_duration(self):
        result = compile_sequence_plan(_plan(), _manifest())
        receipt = result["receipt"]
        original_hash = compile_receipt_sha256(receipt)

        for key, replacement in (
            ("sequence_plan_sha256", "d" * 64),
            ("source_manifest_sha256", "e" * 64),
            ("compiled_segments_sha256", "f" * 64),
            ("total_duration_ms", 6_001),
        ):
            changed = copy.deepcopy(receipt)
            changed[key] = replacement
            with self.subTest(key=key):
                self.assertNotEqual(compile_receipt_sha256(changed), original_hash)

        changed = copy.deepcopy(receipt)
        changed["ordered_segment_ids"].reverse()
        self.assertNotEqual(compile_receipt_sha256(changed), original_hash)

        changed = copy.deepcopy(receipt)
        changed["extra"] = True
        with self.assertRaises(SequencePlanError):
            compile_receipt_sha256(changed)

    def test_ffmpeg_trim_tokens_are_plain_fixed_point_not_shell_fragments(self):
        segments = compile_sequence_plan(_plan(), _manifest())[
            "ffmpeg_segments"
        ]
        decimal = re.compile(r"^(0|[1-9][0-9]*)\.[0-9]{3}$")
        for segment in segments:
            args = segment["ffmpeg_trim_args"]
            self.assertEqual(args[0], "-ss")
            self.assertEqual(args[2], "-t")
            self.assertRegex(args[1], decimal)
            self.assertRegex(args[3], decimal)
            self.assertNotRegex("".join(args), r"[;&|`$(){}\[\]<>]")

    def test_property_style_generated_valid_plans_preserve_all_invariants(self):
        rng = random.Random(0xA17E)
        manifest = _manifest()
        sources = {item["source_id"]: item for item in manifest["sources"]}
        source_ids = sorted(sources)

        for trial in range(100):
            count = rng.randint(2, 30)
            segments = []
            expected_total = 0
            for index in range(count):
                source_id = rng.choice(source_ids)
                duration = sources[source_id]["duration_ms"]
                start = rng.randint(0, duration - 34)
                end = rng.randint(start + 34, duration)
                expected_total += end - start
                segments.append(_segment(
                    f"trial-{trial}-segment-{index}",
                    source_id,
                    sources[source_id]["sha256"],
                    start,
                    end,
                    rng.choice(sorted(ROLES)),
                ))

            if expected_total < 5_000:
                padding = 5_000 - expected_total
                source_id = source_ids[0]
                source = sources[source_id]
                segments.append(_segment(
                    f"trial-{trial}-minimum-padding",
                    source_id,
                    source["sha256"],
                    0,
                    padding,
                    "bridge",
                ))
                expected_total += padding

            plan = {
                "schema_version": SEQUENCE_PLAN_SCHEMA_VERSION,
                "sources": list(reversed(manifest["sources"])),
                "target_duration": {
                    "min_ms": expected_total,
                    "max_ms": expected_total,
                },
                "segments": segments,
            }
            result = compile_sequence_plan(plan, manifest)
            self.assertEqual(result["receipt"]["total_duration_ms"],
                             expected_total)
            self.assertEqual(
                sum(item["duration_ms"] for item in result["ffmpeg_segments"]),
                expected_total,
            )
            self.assertEqual(
                [item["segment_id"] for item in result["ffmpeg_segments"]],
                [item["segment_id"] for item in segments],
            )

    def test_property_style_single_mutations_fail_closed(self):
        rng = random.Random(9_001)
        mutators = (
            lambda plan: plan["segments"][0].update(source_start_ms=-1),
            lambda plan: plan["segments"][0].update(source_end_ms=99_999),
            lambda plan: plan["segments"][0].update(source_sha256="0" * 64),
            lambda plan: plan["segments"][0].update(role="unknown"),
            lambda plan: plan["segments"][0].update(transition={"kind": "fade"}),
            lambda plan: plan["target_duration"].update(min_ms=6_001),
        )
        for _ in range(60):
            plan = _plan()
            rng.choice(mutators)(plan)
            self.assert_rejected(plan)

    def test_json_schema_advertises_the_same_closed_surface(self):
        self.assertEqual(
            SEQUENCE_PLAN_JSON_SCHEMA["properties"]["schema_version"]["const"],
            SEQUENCE_PLAN_SCHEMA_VERSION,
        )
        self.assertFalse(SEQUENCE_PLAN_JSON_SCHEMA["additionalProperties"])
        self.assertEqual(
            SEQUENCE_PLAN_JSON_SCHEMA["properties"]["sources"]["maxItems"],
            20,
        )
        source_schema = SEQUENCE_PLAN_JSON_SCHEMA["properties"]["sources"][
            "items"
        ]
        self.assertEqual(
            source_schema["properties"]["duration_ms"]["minimum"], 1
        )
        target_schema = SEQUENCE_PLAN_JSON_SCHEMA["properties"][
            "target_duration"
        ]["properties"]
        self.assertEqual(
            target_schema["min_ms"]["minimum"], MIN_SEQUENCE_DURATION_MS
        )
        self.assertEqual(
            target_schema["max_ms"]["minimum"], MIN_SEQUENCE_DURATION_MS
        )
        segment_schema = SEQUENCE_PLAN_JSON_SCHEMA["properties"]["segments"]
        self.assertEqual(segment_schema["maxItems"], MAX_SEGMENTS)
        self.assertFalse(segment_schema["items"]["additionalProperties"])
        self.assertEqual(
            segment_schema["items"]["properties"]["role"]["enum"],
            sorted(ROLES),
        )
        self.assertEqual(
            segment_schema["items"]["properties"]["transition"][
                "properties"
            ]["kind"]["const"],
            "hard_cut",
        )


if __name__ == "__main__":
    unittest.main()
