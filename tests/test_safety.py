from __future__ import annotations

import ast
import argparse
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autoeditor import calibrate, creative_contract, pipeline, premium, providers


class SafetyContracts(unittest.TestCase):
    def test_json_extractor_requires_every_requested_key(self):
        partial = '{"punch_ins":[]}'
        self.assertIsNone(providers.extract_json(
            partial, require=("punch_ins", "broll", "graphics")
        ))
        complete = '{"punch_ins":[],"broll":[],"graphics":[]}'
        self.assertEqual(
            providers.extract_json(
                complete, require=("punch_ins", "broll", "graphics")
            ),
            {"punch_ins": [], "broll": [], "graphics": []},
        )

    def test_deepseek_v4_payload_enables_json_thinking_and_max_reasoning(self):
        captured = {}
        old_post = providers._post
        old_key = os.environ.get("DEEPSEEK_API_KEY")
        old_model = os.environ.get("DEEPSEEK_MODEL")
        old_llm_model = os.environ.get("LLM_MODEL")

        def fake_post(url, payload, headers, timeout):
            captured.update({
                "url": url, "payload": payload,
                "headers": headers, "timeout": timeout,
            })
            return {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"ok":true}'},
                }],
                "system_fingerprint": "test-fingerprint",
            }

        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        os.environ.pop("DEEPSEEK_MODEL", None)
        os.environ.pop("LLM_MODEL", None)
        providers._post = fake_post
        receipt = {}
        try:
            result = providers.llm_json(
                'Return json with an "ok" key.',
                require=("ok",), provider="deepseek", attempts=1,
                receipt=receipt,
            )
        finally:
            providers._post = old_post
            if old_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old_key
            if old_model is None:
                os.environ.pop("DEEPSEEK_MODEL", None)
            else:
                os.environ["DEEPSEEK_MODEL"] = old_model
            if old_llm_model is None:
                os.environ.pop("LLM_MODEL", None)
            else:
                os.environ["LLM_MODEL"] = old_llm_model
        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            captured["payload"]["model"], providers.DEFAULT_DEEPSEEK_MODEL
        )
        self.assertEqual(
            captured["payload"]["response_format"], {"type": "json_object"}
        )
        self.assertEqual(
            captured["payload"]["thinking"], {"type": "enabled"}
        )
        self.assertEqual(captured["payload"]["reasoning_effort"], "max")
        self.assertGreaterEqual(captured["payload"]["max_tokens"], 16000)
        self.assertTrue(receipt["ok"])

    def test_retired_deepseek_alias_is_rejected(self):
        old_key = os.environ.get("DEEPSEEK_API_KEY")
        old_model = os.environ.get("DEEPSEEK_MODEL")
        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
        try:
            with self.assertRaises(providers.ProviderConfigurationError):
                providers.llm_available("deepseek")
        finally:
            if old_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old_key
            if old_model is None:
                os.environ.pop("DEEPSEEK_MODEL", None)
            else:
                os.environ["DEEPSEEK_MODEL"] = old_model

    def test_generic_llm_model_cannot_override_deepseek_v4(self):
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "LLM_MODEL": "gpt-4o-mini",
        }, clear=True):
            self.assertEqual(
                providers._deepseek_model(),
                providers.DEFAULT_DEEPSEEK_MODEL,
            )

    def test_empty_deepseek_content_retries_before_accepting_json(self):
        replies = [
            {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": ""},
                }]
            },
            {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"ok":true}'},
                }]
            },
        ]
        receipt = {}
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_MODEL": providers.DEFAULT_DEEPSEEK_MODEL,
        }), mock.patch.object(
            providers, "_post", side_effect=replies
        ), mock.patch.object(providers.time, "sleep", return_value=None):
            result = providers.llm_json(
                "Return json.", require=("ok",), provider="deepseek",
                attempts=2, receipt=receipt,
            )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            [attempt["result"] for attempt in receipt["attempts"]],
            ["empty_content", "json_ok"],
        )

    def test_truncated_finish_reason_is_never_accepted(self):
        reply = {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": '{"ok":true}'},
            }]
        }
        receipt = {}
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_MODEL": providers.DEFAULT_DEEPSEEK_MODEL,
        }), mock.patch.object(providers, "_post", return_value=reply):
            result = providers.llm_json(
                "Return json.", require=("ok",), provider="deepseek",
                attempts=1, receipt=receipt,
            )
        self.assertIsNone(result)
        self.assertEqual(
            receipt["attempts"][0]["result"], "finish_length"
        )

    def test_incomplete_http_body_becomes_a_retryable_transport_error(self):
        with mock.patch.object(
                providers.urllib.request, "urlopen",
                side_effect=http.client.IncompleteRead(b"{", 20)):
            result = providers._post(
                "https://example.invalid", {"x": 1}, {}, 1
            )
        self.assertEqual(result, {"_transport_error": "incomplete_read"})

    def test_trickled_http_body_cannot_bypass_wall_clock_timeout(self):
        import http.server
        import threading
        import time

        body = b'{"ok":true}'

        class TrickleHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.04)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, _format, *args):
                pass

        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), TrickleHandler
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            result = providers._post(
                f"http://127.0.0.1:{server.server_port}/",
                {"x": 1}, {}, 0.12,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        elapsed = time.monotonic() - started
        self.assertEqual(result, {"_transport_error": "timeout"})
        self.assertLess(elapsed, 1.0)

    def test_permanent_http_4xx_is_not_retried(self):
        receipt = {}
        with mock.patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_MODEL": providers.DEFAULT_DEEPSEEK_MODEL,
        }), mock.patch.object(
            providers, "_post", return_value={"_transport_error": "http_401"}
        ) as post, mock.patch.object(
            providers.time, "sleep", return_value=None
        ) as sleep:
            result = providers.llm_json(
                "Return json.", require=("ok",), provider="deepseek",
                attempts=3, receipt=receipt,
            )
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_telegram_home_channel_is_an_explicit_chat_id_fallback(self):
        with mock.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_HOME_CHANNEL": "12345",
        }, clear=True):
            self.assertEqual(providers._tg(), ("token", "12345"))

    def test_creative_contract_keeps_the_complete_transcript(self):
        words = [
            {"w": f"word{i}", "s": i * 0.2, "e": i * 0.2 + 0.1}
            for i in range(1600)
        ]
        words[-1]["w"] = "LATE_MARKER"
        payload = creative_contract.transcript_payload(words)
        self.assertIn("LATE_MARKER", payload)
        self.assertEqual(json.loads(payload)[-1]["i"], 1599)
        self.assertNotIn("[:6000]", Path(premium.__file__).read_text())

    def test_creative_contract_anchors_times_to_spoken_words(self):
        spoken = (
            "Your brain decides what matters today before any choice is made "
            "A city story now shows the concrete lesson clearly"
        ).split()
        words = [
            {"w": word, "s": index * 0.5, "e": index * 0.5 + 0.35}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.1, "e": 2.6, "scale": 1.1,
                "anchor_quote": "Your brain decides what matters today",
                "reason": "opening verdict",
            }],
            "broll": [{
                "s": 5.0, "e": 7.0,
                "query": "city skyline aerial night", "family": "",
                "anchor_quote": "A city story now shows the concrete lesson",
                "reason": "literal city story",
            }],
            "graphics": [],
        }
        edl, report = creative_contract.validate_edl(
            raw, words, [], 10.0, "long"
        )
        self.assertEqual(report["score"], 100)
        self.assertAlmostEqual(edl["punch_ins"][0]["s"], 0.0, places=3)
        city_start = next(
            word["s"] for word in words if word["w"] == "A"
        )
        self.assertAlmostEqual(
            edl["broll"][0]["s"], city_start - 0.1, places=3
        )

    def test_creative_contract_rejects_ungrounded_model_event(self):
        words = [
            {"w": word, "s": index * 0.4, "e": index * 0.4 + 0.25}
            for index, word in enumerate(
                "This opening sentence has enough real spoken words today".split()
            )
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote": "words that were never spoken here",
                "reason": "invented anchor",
            }],
            "broll": [],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "not grounded"):
            creative_contract.validate_edl(raw, words, [], 8.0, "long")

    def test_creative_contract_rejects_overlapping_model_events(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        punch = {
            "s": 0.0, "e": 2.0, "scale": 1.1,
            "anchor_quote":
                "This opening sentence contains enough real spoken words",
            "reason": "opening emphasis",
        }
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [punch, {**punch, "reason": "stacked emphasis"}],
            "broll": [{
                "s": 4.0, "e": 6.0,
                "query": "abstract light particles macro", "family": "",
                "anchor_quote": "A visual example follows with enough concrete words",
                "reason": "visual example",
            }],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "overlapping"):
            creative_contract.validate_edl(raw, words, [], 9.0, "long")

    def test_creative_contract_rejects_markup_and_unknown_commands(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote":
                    "This opening sentence contains enough real spoken words",
                "reason": "opening emphasis",
            }],
            "broll": [],
            "graphics": [{
                "s": 4.0, "e": 6.0, "kind": "callout",
                "text": "<SCRIPT>ALERT",
                "anchor_quote": "A visual example follows with enough concrete words",
                "reason": "visual example",
            }],
            "cuts": [{"s": 0.0, "e": 8.0}],
        }
        with self.assertRaises(
                creative_contract.CreativeContractError) as caught:
            creative_contract.validate_edl(raw, words, [], 9.0, "long")
        message = str(caught.exception)
        self.assertIn("unsupported top-level keys: cuts", message)
        self.assertIn("markup or control characters", message)

    def test_creative_contract_requires_exact_five_word_anchor(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote": "This opening sentence has enough words",
                "reason": "opening emphasis",
            }],
            "broll": [],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "not grounded"):
            creative_contract.validate_edl(raw, words, [], 8.0, "long")

    def test_fabricated_visual_copy_cannot_hide_behind_a_real_anchor(self):
        spoken = (
            "This city story explains architecture with a concrete lesson "
            "for everyone watching the example today"
        ).split()
        words = [
            {"w": word, "s": index * 0.4, "e": index * 0.4 + 0.25}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [],
            "broll": [{
                "s": 0.0, "e": 3.0,
                "query": "city architecture aerial", "family": "",
                "anchor_quote":
                    "This city story explains architecture with a concrete",
                "reason": "city example",
                "viz": {
                    "template": "steps",
                    "title": "THREE SIGNALS",
                    "items": ["SUPERIORITY", "AUTONOMY", "CERTAINTY"],
                },
            }],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "on-screen copy is not grounded"):
            creative_contract.validate_edl(raw, words, [], 6.0, "long")

    def test_fabricated_stat_number_cannot_reach_the_renderer(self):
        spoken = (
            "This city story explains architecture with a concrete lesson "
            "for everyone watching the example today"
        ).split()
        words = [
            {"w": word, "s": index * 0.4, "e": index * 0.4 + 0.25}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [],
            "broll": [],
            "graphics": [{
                "s": 0.0, "e": 2.0, "kind": "stat",
                "text": "REVENUE GROWTH", "value": "487%",
                "anchor_quote":
                    "This city story explains architecture with a concrete",
                "reason": "claimed result",
            }],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "on-screen copy is not grounded"):
            creative_contract.validate_edl(raw, words, [], 6.0, "long")

    def test_punch_anchor_itself_cannot_exceed_the_duration_limit(self):
        spoken = [f"word{index}" for index in range(20)]
        words = [
            {"w": word, "s": index * 0.5, "e": index * 0.5 + 0.35}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 8.0, "scale": 1.1,
                "anchor_quote": " ".join(spoken),
                "reason": "slow opening",
            }],
            "broll": [],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "spans more than 8.0 seconds"):
            creative_contract.validate_edl(raw, words, [], 11.0, "long")

    def test_legal_decimal_boundary_duration_is_not_rejected(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual example follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 1.8, "e": 2.4, "scale": 1.1,
                "anchor_quote":
                    "This opening sentence contains enough real spoken words",
                "reason": "opening emphasis",
            }],
            "broll": [{
                "s": 4.0, "e": 5.5,
                "query": "abstract visual example", "family": "",
                "anchor_quote":
                    "A visual example follows with enough concrete words",
                "reason": "opening visual",
            }],
            "graphics": [],
        }
        edl, report = creative_contract.validate_edl(
            raw, words, [], 9.0, "long"
        )
        self.assertEqual(report["score"], 100)
        self.assertGreaterEqual(
            edl["punch_ins"][0]["e"] - edl["punch_ins"][0]["s"], 0.6
        )

    def test_clustered_punch_budget_is_rejected(self):
        spoken = [f"word{index}" for index in range(100)]
        words = [
            {"w": word, "s": index * 0.3, "e": index * 0.3 + 0.2}
            for index, word in enumerate(spoken)
        ]
        punches = []
        for start_word in (0, 6, 12):
            punches.append({
                "s": start_word * 0.3,
                "e": start_word * 0.3 + 0.7,
                "scale": 1.1,
                "anchor_quote": " ".join(
                    spoken[start_word:start_word + 5]
                ),
                "reason": "clustered emphasis",
            })
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": punches,
            "broll": [{
                "s": 5.0, "e": 7.0,
                "query": "abstract opening visual", "family": "",
                "anchor_quote": " ".join(spoken[17:22]),
                "reason": "opening visual",
            }],
            "graphics": [],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError,
                "pacing requires at least 10.0s"):
            creative_contract.validate_edl(raw, words, [], 30.0, "long")

    def test_stat_parser_preserves_human_numeric_display(self):
        cases = {
            "$1,200": ("$1,200", 1200.0, 0, ""),
            "1,200": ("1,200", 1200.0, 0, ""),
            "12.5%": ("12.5%", 12.5, 1, "%"),
            "10.5": ("10.5", 10.5, 1, ""),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                parts = premium._stat_parts(value)
                self.assertIsNotNone(parts)
                self.assertEqual(
                    (parts["display"], parts["number"],
                     parts["decimals"], parts["suffix"]),
                    expected,
                )
        self.assertIsNone(premium._stat_parts("HALF"))
        self.assertTrue(creative_contract._number_is_spoken(
            "12.5%", "the result was twelve point five percent"
        ))

    def test_bar_values_cannot_be_negative(self):
        spoken = (
            "This opening sentence contains enough real spoken words today "
            "A visual comparison follows with enough concrete words now"
        ).split()
        words = [
            {"w": word, "s": index * 0.45, "e": index * 0.45 + 0.3}
            for index, word in enumerate(spoken)
        ]
        raw = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [{
                "s": 0.0, "e": 2.0, "scale": 1.1,
                "anchor_quote":
                    "This opening sentence contains enough real spoken words",
                "reason": "opening emphasis",
            }],
            "broll": [],
            "graphics": [{
                "s": 4.0, "e": 6.0, "kind": "bars",
                "text": "CLEAR COMPARISON",
                "items": [
                    {"label": "FIRST", "value": -1},
                    {"label": "SECOND", "value": 2},
                ],
                "anchor_quote":
                    "A visual comparison follows with enough concrete words",
                "reason": "spoken comparison",
            }],
        }
        with self.assertRaisesRegex(
                creative_contract.CreativeContractError, "nonnegative"):
            creative_contract.validate_edl(raw, words, [], 9.0, "long")

    def test_validated_plan_hash_changes_when_an_event_changes(self):
        edl = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [],
            "broll": [{
                "s": 1.0, "e": 3.0, "query": "city skyline",
                "family": "", "anchor_quote": "city skyline",
                "reason": "literal visual",
            }],
            "graphics": [],
        }
        original = creative_contract.edl_sha256(edl)
        edl["broll"][0]["query"] = "unrelated ocean"
        self.assertNotEqual(original, creative_contract.edl_sha256(edl))

    def test_requested_deepseek_mode_cannot_silently_fall_back(self):
        old_available = premium.providers.llm_available
        old_deepseek = premium.deepseek_edl
        premium.providers.llm_available = lambda provider=None: True
        premium.deepseek_edl = lambda *args, **kwargs: None
        try:
            with self.assertRaisesRegex(RuntimeError, "render is blocked"):
                premium.make_edl(
                    [{"w": "hello", "s": 0.0, "e": 0.4}],
                    [], 2.0, use_llm=True,
                )
        finally:
            premium.providers.llm_available = old_available
            premium.deepseek_edl = old_deepseek

    def test_deepseek_mode_with_empty_transcript_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "nonempty"):
            premium.make_edl([], [], 10.0, use_llm=True)

    def test_critic_repairs_again_with_fresh_validator_errors(self):
        words = [
            {"w": "opening", "s": 0.0, "e": 0.2},
            {"w": "words", "s": 0.3, "e": 0.5},
            {"w": "for", "s": 0.6, "e": 0.8},
            {"w": "a", "s": 0.9, "e": 1.1},
            {"w": "test", "s": 1.2, "e": 1.4},
        ]
        candidate = {
            "protocol_version": creative_contract.PROTOCOL_VERSION,
            "timeline_space": creative_contract.TIMELINE_SPACE,
            "punch_ins": [], "broll": [], "graphics": [],
        }
        valid_edl = {
            **candidate,
            "contract": {"score": 100},
        }
        receipts = []

        def fake_llm(*args, **kwargs):
            kwargs["receipt"].update({
                "ok": True,
                "attempts": [{"result": "json_ok"}],
                "model": providers.DEFAULT_DEEPSEEK_MODEL,
            })
            receipts.append(kwargs["purpose"])
            return dict(candidate)

        with mock.patch.object(
            providers, "llm_json", side_effect=fake_llm
        ), mock.patch.object(
            creative_contract, "validate_edl",
            side_effect=[
                creative_contract.CreativeContractError(["director bad"]),
                creative_contract.CreativeContractError(["critic still bad"]),
                (valid_edl, {"score": 100}),
            ],
        ):
            result = premium.deepseek_edl(words, [], 5.0, style="long")
        self.assertIsNotNone(result)
        production = result["production_receipt"]
        self.assertEqual(production["critic_rounds_used"], 2)
        self.assertEqual(len(production["critic_contract_error_rounds"]), 1)
        self.assertEqual(
            receipts,
            [
                "creative_edl_director",
                "creative_edl_critic_round_1",
                "creative_edl_critic_round_2",
            ],
        )

    def test_script_requirement_runs_before_media_preflight(self):
        source = Path(pipeline.__file__).read_text()
        requirement = source.index(
            "brand.yaml requires the script-integrity gate"
        )
        preflight = source.index("info = preflight(src)")
        self.assertLess(requirement, preflight)

    def test_supplied_control_files_cannot_silently_change_modes(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            existing = work / "script.txt"
            existing.write_text("known script")
            self.assertEqual(
                pipeline._required_input_file(existing, "--script"),
                existing.resolve(),
            )
            for option in ("--script", "--edl", "--music", "--background"):
                with self.subTest(option=option), self.assertRaisesRegex(
                        ValueError, "input path does not exist"):
                    pipeline._required_input_file(
                        work / f"missing-{option[2:]}", option
                    )

    def test_short_internal_sync_audio_is_a_failed_unusable_probe(self):
        def fake_run(command, check=False):
            if "rawvideo" in command:
                return mock.Mock(stdout=bytes(160 * 45))
            return mock.Mock(stdout=bytes(1000))

        with mock.patch.object(pipeline, "run", side_effect=fake_run):
            result = pipeline.verify_sync(
                Path("master.mp4"), Path("reference.mp4"), {}, 12.0
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["probes_used"], 0)
        self.assertTrue(result["probes"])
        self.assertTrue(all(
            probe.get("error") == "audio_probe_shorter_than_one_second"
            for probe in result["probes"]
        ))

    def test_live_command_imports_the_canonical_pipeline(self):
        root = Path(__file__).resolve().parent.parent
        tracked = (
            root / "integrations" / "hermes" / "hermes_pse_edit.py"
        )
        candidates = [tracked]
        live = (
            Path.home() / "cinematic-autopilot" / "tools"
            / "hermes_pse_edit.py"
        )
        if live.exists():
            candidates.append(live)
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                source = candidate.read_text()
                self.assertIn(
                    "from autoeditor.pipeline import main", source
                )
                self.assertNotIn("deepseek-v4-flash", source)
        installer = (root / "install.sh").read_text()
        self.assertIn(
            "integrations/hermes/hermes_pse_edit.py", installer
        )
        self.assertIn(".talking-head-autoeditor-root", installer)

    def test_canonical_runtime_does_not_require_an_uninstalled_legacy_venv(self):
        self.assertEqual(pipeline.VENV_PY, Path(pipeline.sys.executable).resolve())
        source = Path(pipeline.__file__).read_text()
        self.assertNotIn(
            'VENV_PY = EDIT_VENV / "bin" / "python"', source
        )

    def test_default_catalogs_exist_without_live_bridge_side_effects(self):
        self.assertTrue(premium.CLIP_CATALOGS)
        self.assertTrue(any(
            "marabha_kling_clip_library" in str(path)
            for path in premium.CLIP_CATALOGS
        ))

    def test_live_hermes_skill_requires_script_and_v4_pro(self):
        root = Path(__file__).resolve().parent.parent
        tracked = (
            root / "integrations" / "hermes"
            / "pse-talking-head-autoedit" / "SKILL.md"
        )
        candidates = [tracked]
        live = (
            Path.home() / ".hermes" / "skills" / "media"
            / "pse-talking-head-autoedit" / "SKILL.md"
        )
        if live.exists():
            candidates.append(live)
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                source = candidate.read_text()
                self.assertIn("--script", source)
                self.assertIn("DeepSeek V4 Pro", source)
                self.assertNotIn("deepseek-v4-flash", source.lower())
                self.assertIn(".UNVERIFIED", source)
        self.assertIn(
            "integrations/hermes/pse-talking-head-autoedit/SKILL.md",
            (root / "install.sh").read_text(),
        )

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg and ffprobe are required")
    def test_visual_artifact_gate_detects_present_and_missing_overlay(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            reference = work / "reference.mp4"
            present = work / "present.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(reference),
            ], check=True)
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(reference), "-vf",
                "drawbox=x=40:y=20:w=240:h=70:color=yellow:t=fill:"
                "enable='between(t,1,2)'",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(present),
            ], check=True)
            edl = {
                "broll": [],
                "graphics": [{"s": 1.0, "e": 2.0}],
            }
            found = pipeline.verify_visual_events(
                present, reference, edl
            )
            missing = pipeline.verify_visual_events(
                reference, reference, edl
            )
        self.assertTrue(found["ok"])
        self.assertFalse(missing["ok"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg and ffprobe are required")
    def test_aspect_derivatives_bind_both_geometry_paths_and_audio(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            landscape = work / "landscape.mp4"
            cropped = work / "cropped.mp4"
            portrait = work / "portrait.mp4"
            pillared = work / "pillared.mp4"
            bad_audio = work / "bad_audio.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-f", "lavfi", "-i",
                "sine=frequency=733:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(landscape),
            ], check=True)
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(landscape), "-vf",
                "crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9),"
                "scale=1080:1920",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", str(cropped),
            ], check=True)
            crop_result = pipeline.verify_aspect_derivative(
                cropped, landscape, "center_crop_9x16", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=180x320:rate=30:duration=3",
                "-f", "lavfi", "-i",
                "sine=frequency=811:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(portrait),
            ], check=True)
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(portrait), "-filter_complex",
                "[0:v]split=2[a][b];"
                "[a]scale=64:36,scale=1920:1080:flags=bicubic,"
                "crop=1920:1080[bg];"
                "[b]scale=-2:1080[fg];"
                "[bg][fg]overlay=(W-w)/2:0",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "copy", str(pillared),
            ], check=True)
            pillar_result = pipeline.verify_aspect_derivative(
                pillared, portrait, "portrait_pillarbox_16x9", {}, 3.0
            )
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-i", str(cropped),
                "-f", "lavfi", "-i",
                "sine=frequency=1200:sample_rate=48000:duration=3",
                "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                "-c:a", "aac", "-shortest", str(bad_audio),
            ], check=True)
            rejected = pipeline.verify_aspect_derivative(
                bad_audio, landscape, "center_crop_9x16", {}, 3.0
            )
        self.assertTrue(crop_result["ok"])
        self.assertTrue(pillar_result["ok"])
        self.assertFalse(rejected["ok"])
        self.assertFalse(rejected["audio_hash_match"])

    def test_planned_diagram_cannot_degrade_into_stock_footage(self):
        edl = {
            "broll": [{
                "s": 1.0, "e": 4.0,
                "query": "generic business office",
                "family": "",
                "viz": {
                    "template": "flow",
                    "title": "THREE STEPS",
                    "items": ["ONE", "TWO", "THREE"],
                },
            }],
            "graphics": [],
        }
        with mock.patch.object(
            premium, "_remotion_viz", return_value=None
        ), mock.patch.object(
            premium, "_pexels_fetch"
        ) as stock:
            layers = premium.broll_layers(edl, [])
        self.assertEqual(layers, [])
        stock.assert_not_called()
        self.assertFalse(edl["resolution"]["ok"])
        self.assertEqual(edl["resolution"]["unresolved_broll"], [0])
        self.assertEqual(
            edl["resolution"]["broll_events"][0]["reason"],
            "planned diagram did not render",
        )

    def test_empty_family_cannot_resolve_to_arbitrary_local_footage(self):
        edl = {
            "broll": [{
                "s": 1.0, "e": 3.0,
                "query": "unavailable concrete topic", "family": "",
            }],
            "graphics": [],
        }
        clips = [{
            "family": "", "path": "/tmp/unrelated.mp4", "dur": 10.0,
        }]
        with mock.patch.object(
            premium, "_pexels_fetch", return_value=None
        ), mock.patch.object(
            premium, "_pixabay_fetch", return_value=None
        ), mock.patch.object(
            premium, "_video_duration", return_value=10.0
        ):
            layers = premium.broll_layers(edl, clips)
        self.assertEqual(layers, [])
        self.assertFalse(edl["resolution"]["ok"])

    def test_rejected_or_unclassified_catalog_rows_never_reenter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip = root / "clip.mp4"
            clip.write_bytes(b"fixture")
            rejected = root / "curated.csv"
            rejected.write_text(
                "path,rating,scene_family,duration_sec\n"
                f"{clip},REJECT,office,5\n"
            )
            unclassified = root / "manifest.csv"
            unclassified.write_text(
                "path,duration_sec\n"
                f"{clip},5\n"
            )
            with mock.patch.object(
                    premium, "CLIP_CATALOGS",
                    [unclassified, rejected]):
                clips = premium.load_kling()
        self.assertEqual(clips, [])

    def test_one_bad_catalog_duration_does_not_hide_later_clips(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "first.mp4"
            second = root / "second.mp4"
            first.write_bytes(b"fixture")
            second.write_bytes(b"fixture")
            catalog = root / "catalog.csv"
            catalog.write_text(
                "path,rating,scene_family,duration_sec\n"
                f"{first},GOOD,office,N/A\n"
                f"{second},GOOD,city,8.5\n"
            )
            with mock.patch.object(premium, "CLIP_CATALOGS", [catalog]):
                clips = premium.load_kling()
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0]["dur"], 5.0)
        self.assertEqual(clips[1]["dur"], 8.5)

    def test_short_broll_asset_cannot_freeze_through_planned_window(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "short.mp4"
            clip.write_bytes(b"short fixture")
            edl = {
                "broll": [{
                    "s": 1.0, "e": 5.0,
                    "query": "", "family": "office",
                }],
                "graphics": [],
            }
            catalog = [{
                "family": "office", "path": str(clip), "dur": 99.0,
            }]
            with mock.patch.object(
                    premium, "_video_duration", return_value=0.5):
                layers = premium.broll_layers(edl, catalog)
        self.assertEqual(layers, [])
        self.assertFalse(edl["resolution"]["ok"])
        self.assertEqual(
            edl["resolution"]["broll_events"][0]["reason"],
            "resolved asset is shorter than the planned window",
        )

    def test_invalid_cached_visual_is_removed_before_network_retry(self):
        with tempfile.TemporaryDirectory() as td:
            cached = Path(td) / "poison.mp4"
            cached.write_bytes(b"partial transfer")
            with mock.patch.object(
                    premium, "_video_info", return_value=(0.2, 1920, 1080)):
                hit = premium._validated_cached(
                    [cached], min_dur=3.0, portrait=False
                )
        self.assertIsNone(hit)
        self.assertFalse(cached.exists())

    def test_valid_metadata_cannot_hide_a_truncated_cached_visual(self):
        with tempfile.TemporaryDirectory() as td:
            cached = Path(td) / "header_only.mp4"
            cached.write_bytes(b"valid-looking partial transfer")
            with mock.patch.object(
                premium, "_video_info", return_value=(8.0, 1920, 1080)
            ), mock.patch.object(
                premium, "_video_decodes", return_value=False
            ):
                hit = premium._validated_cached(
                    [cached], min_dur=3.0, portrait=False
                )
        self.assertIsNone(hit)
        self.assertFalse(cached.exists())

    def test_calibration_is_bound_to_raw_hash(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "take.mov"
            raw.write_bytes(b"original raw bytes")
            sidecar = calibrate.write_certification(raw, -100)
            payload = json.loads(sidecar.read_text())
            self.assertEqual(payload["offset_ms"], -100)
            self.assertEqual(
                payload["source_sha256"],
                hashlib.sha256(raw.read_bytes()).hexdigest(),
            )
            self.assertEqual(pipeline.certified_av_offset(raw)[0], -100)
            raw.write_bytes(b"replacement under the same filename")
            offset, note = pipeline.certified_av_offset(raw)
            self.assertEqual(offset, 0)
            self.assertIn("does not match", note)

    def test_gate_rejects_applied_value_that_is_not_certified(self):
        with tempfile.TemporaryDirectory() as td:
            result = pipeline.verify_sync_source(
                Path(td) / "master.mp4",
                Path(td) / "raw.mov",
                {},
                applied_ms=-200,
                certified_ms=0,
                final_words=[],
                workdir=Path(td),
            )
        self.assertFalse(result["ok"])
        self.assertIn("not the certified", result["note"])

    def test_uncertified_offset_is_rejected_before_render(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "recording.mov"
            raw.write_bytes(b"original source")
            with self.assertRaisesRegex(ValueError, r"requested \+100ms"):
                pipeline.resolve_av_offset(raw, 100)
            applied, certified, note = pipeline.resolve_av_offset(raw, 0)
        self.assertEqual((applied, certified), (0, 0))
        self.assertIn("certified default is 0ms", note)

    def test_outputs_are_quarantined_until_explicit_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            final = Path(td) / "PSE_MASTER_16x9.mp4"
            final.write_bytes(b"completed but ungated")
            quarantined, final_paths = pipeline.quarantine_outputs(
                {"16x9": final}
            )
            held = quarantined["16x9"]
            self.assertFalse(final.exists())
            self.assertTrue(held.exists())
            self.assertIn(".UNVERIFIED", held.name)
            promoted = pipeline.promote_outputs(quarantined, final_paths)
            self.assertEqual(promoted["16x9"], final)
            self.assertTrue(final.exists())
            self.assertFalse(held.exists())

    def test_backward_raw_mapping_is_a_hard_failure(self):
        matches = [
            (5.0, 10.0),
            (10.0, 15.0),
            (15.0, 14.5),
            (20.0, 25.0),
        ]
        failures = pipeline._nonmonotonic_matches(matches)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["from_raw_t"], 15.0)
        self.assertEqual(failures[0]["to_raw_t"], 14.5)

    def test_duplicate_probe_is_not_a_backward_mapping(self):
        matches = [
            (199.3796, 255.31),
            (199.3800, 255.31),
        ]
        self.assertEqual(pipeline._nonmonotonic_matches(matches), [])

    def test_start_probe_searches_past_an_overlay_but_stays_bounded(self):
        words = [6.2, 6.6, 8.0, 8.4, 20.1, 20.5, 28.0, 28.4]
        groups = pipeline._probe_candidate_groups(
            words, [(-1.0, 6.0)], 30.0, 0.2, 29.0
        )
        self.assertTrue(groups[0])
        self.assertLessEqual(groups[0][0], 10.2)
        blocked = pipeline._probe_candidate_groups(
            words, [(-1.0, 12.0)], 30.0, 0.2, 29.0
        )
        self.assertEqual(blocked[0], [])

    def test_short_source_gate_still_gets_four_probe_groups(self):
        word_mids = [0.2 + index * 0.4 for index in range(36)]
        groups = pipeline._probe_candidate_groups(
            word_mids, [], 15.0, 0.2, 14.2
        )
        self.assertGreaterEqual(len(groups), 4)
        self.assertTrue(all(groups[index] for index in range(4)))
        self.assertEqual(pipeline.SOURCE_SYNC_MAX_GAP_SECONDS, 30.0)

    def test_ignored_option_combinations_fail_instead_of_changing_modes(self):
        base = {
            "no_premium": False,
            "edl": None,
            "background": None,
            "no_llm": False,
        }
        cases = [
            {**base, "no_premium": True, "edl": Path("plan.json")},
            {**base, "no_premium": True, "background": Path("bg.png")},
            {**base, "no_premium": True, "no_llm": True},
            {**base, "edl": Path("plan.json"), "no_llm": True},
        ]
        for values in cases:
            with self.subTest(values=values):
                self.assertTrue(
                    pipeline._option_conflicts(argparse.Namespace(**values))
                )

    def test_renderer_honors_the_contracts_full_punch_scale(self):
        source = Path(premium.__file__).read_text()
        self.assertIn("min(1.15, max(1.05", source)

    def test_caption_gate_checks_the_selected_delivery_mode(self):
        words = [{"w": "hello", "s": 0.0, "e": 0.3}]
        with tempfile.TemporaryDirectory() as td:
            sidecar = Path(td) / "captions.srt"
            sidecar.write_text("caption")
            burned = pipeline._caption_delivery_check(
                words, True, True, sidecar
            )
            missing_burn = pipeline._caption_delivery_check(
                words, True, False, sidecar
            )
            sidecar_mode = pipeline._caption_delivery_check(
                words, False, False, sidecar
            )
        self.assertTrue(burned["ok"])
        self.assertFalse(missing_burn["ok"])
        self.assertTrue(sidecar_mode["ok"])

    def test_source_gate_reconstructs_spatial_normalization(self):
        module_text = Path(pipeline.__file__).read_text()
        function = next(
            node for node in ast.parse(module_text).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "verify_sync_source"
        )
        source = ast.get_source_segment(module_text, function)
        self.assertIn("_deletterbox_spec(raw_src)", source)
        names = {
            node.id for node in ast.walk(function)
            if isinstance(node, ast.Name)
        }
        self.assertNotIn("DELETTERBOX_VF", names)

    def test_independent_asr_can_clear_a_primary_homophone(self):
        script = (
            "There are three signals your Lizard Brain broadcasts and reads "
            "in every single human interaction: Superiority, Autonomy, and "
            "Certainty."
        )
        primary = (
            "Here's three signals your lizard brain broadcasts and reads in "
            "every single human interaction. The priority, autonomy, and "
            "certainty."
        )
        secondary = (
            "There's three signals your lizard brain broadcasts and reads in "
            "every single human interaction superiority autonomy and certainty."
        )
        result = pipeline._independent_asr_recovery(
            script, primary, secondary
        )
        self.assertTrue(result["clears"])
        self.assertEqual(result["recovered_content"], ["superiority"])

    def test_independent_asr_does_not_clear_confirmed_loss(self):
        result = pipeline._independent_asr_recovery(
            "The result is five hundred million years.",
            "The result is around Philly.",
            "The result is around Philly.",
        )
        self.assertFalse(result["clears"])

    def test_independent_asr_cannot_ignore_a_missing_negation(self):
        result = pipeline._independent_asr_recovery(
            "The system is not cryptographically secure.",
            "The system is secure.",
            "The system is cryptographically secure.",
        )
        self.assertIn("not", result["missing_content"])
        self.assertFalse(result["clears"])

    def test_multi_aspect_release_is_not_supported(self):
        self.assertNotIn("all", pipeline.SUPPORTED_ASPECTS)

    def test_container_stream_start_delta_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            media = Path(td) / "offset.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=160x90:rate=30:duration=3",
                "-itsoffset", "0.125", "-f", "lavfi", "-i",
                "sine=frequency=733:sample_rate=48000:duration=2.8",
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(media),
            ], check=True)
            delta = pipeline._stream_start_delta(media)
        self.assertGreater(delta, 0.08)
        self.assertLess(delta, 0.14)

    def test_failed_qa_cannot_reach_video_send(self):
        source = Path(pipeline.__file__).read_text()
        qa_guard = source.index('if not qa["pass"]:')
        send = source.index("providers.send_video(")
        self.assertLess(qa_guard, send)

    def test_main_builds_final_transcript_before_artifact_gates(self):
        source = Path(pipeline.__file__).read_text()
        assignment = source.index("final_words = transcribe(main_out_v, work)")
        retake_gate = source.index("residue = verify_no_retakes(final_words")
        source_gate = source.index("ssync = verify_sync_source(master")
        self.assertLess(assignment, retake_gate)
        self.assertLess(assignment, source_gate)

    def test_retranscription_reapplies_script_caption_correction(self):
        raw_words = [{"w": "misheard", "s": 0.0, "e": 0.2}]
        corrected = [{"w": "scripted", "s": 0.0, "e": 0.2}]
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            pipeline, "transcribe", return_value=raw_words
        ) as transcribe_call, mock.patch.object(
            pipeline, "script_correct", return_value=corrected
        ) as correct_call:
            script = Path(td) / "script.txt"
            script.write_text("scripted")
            result = pipeline._retranscribe_post_cut(
                Path("cut.mp4"), Path(td), script
            )
        self.assertEqual(result, corrected)
        transcribe_call.assert_called_once()
        correct_call.assert_called_once_with(raw_words, script)

    def test_whole_sentence_removed_by_large_splice_cannot_be_judged_fine(self):
        script_text = (
            "Alpha opening sentence has six clear words. "
            "Critical missing sentence contains the actual promise. "
            "Omega closing sentence has six clear words."
        )
        delivered = (
            "Alpha opening sentence has six clear words "
            "Omega closing sentence has six clear words"
        ).split()
        final_words = [
            {"w": word, "s": index * 0.3, "e": index * 0.3 + 0.2, "p": 0.99}
            for index, word in enumerate(delivered)
        ]
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            script = work / "script.txt"
            script.write_text(script_text)
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = [(1.8, 2.4)]
            try:
                with mock.patch.object(
                    providers, "llm_json",
                    return_value={
                        "verdicts": [{"i": 0, "verdict": "FINE", "why": ""}]
                    },
                ):
                    result = pipeline.script_integrity(
                        final_words, script, work
                    )
            finally:
                pipeline.CUT_BOUNDARIES = old_boundaries
        self.assertFalse(result["ok"])
        self.assertTrue(result["damaged"][0]["mechanically_missing"])
        self.assertIn("whole scripted sentence", result["damaged"][0]["why"])

    def test_srt_preserves_commas_in_spoken_copy(self):
        words = [
            {"w": "Hello,", "s": 0.0, "e": 0.2},
            {"w": "world.", "s": 0.2, "e": 0.5},
        ]
        with tempfile.TemporaryDirectory() as td:
            srt = Path(td) / "captions.srt"
            pipeline.build_srt(words, srt)
            text = srt.read_text()
        self.assertIn("Hello, world.", text)
        self.assertNotIn("Hello-world", text)

    def test_cleanup_loop_cuts_and_retranscribes_inside_each_pass(self):
        tree = ast.parse(Path(pipeline.__file__).read_text())
        main = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        loops = [
            node for node in ast.walk(main)
            if isinstance(node, ast.For)
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and any(
                isinstance(arg, ast.Constant) and arg.value == 6
                for arg in node.iter.args
            )
        ]
        self.assertEqual(len(loops), 1)
        calls = {
            node.func.id
            for statement in loops[0].body
            for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("apply_cuts", calls)
        self.assertIn("transcribe", calls)

    def test_incomplete_semantic_judgment_blocks_cut_implicated_sentence(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            script = work / "script.txt"
            tokens = "one two three four five six seven eight nine ten"
            script.write_text(tokens + ".")
            final_words = [
                {"w": word, "s": i * 0.4, "e": i * 0.4 + 0.25, "p": 0.99}
                for i, word in enumerate(tokens.split()[:8])
            ]
            old_llm_json = providers.llm_json
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = [(1.5, 0.5)]
            providers.llm_json = lambda *args, **kwargs: {"verdicts": []}
            try:
                result = pipeline.script_integrity(final_words, script, work)
            finally:
                providers.llm_json = old_llm_json
                pipeline.CUT_BOUNDARIES = old_boundaries
        self.assertFalse(result["ok"])
        self.assertEqual(result["judge"], "mechanical")
        self.assertEqual(len(result["damaged"]), 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg and ffprobe are required")
    def test_integer_cut_graph_keeps_stream_durations_aligned(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "input.mp4"
            subprocess.run([
                pipeline.FFMPEG, "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=30:duration=3",
                "-f", "lavfi", "-i",
                "anoisesrc=color=white:sample_rate=48000:duration=3:seed=7",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", str(src),
            ], check=True)
            old_boundaries = pipeline.CUT_BOUNDARIES
            pipeline.CUT_BOUNDARIES = []
            try:
                out = pipeline.apply_cuts(
                    src,
                    [{"s": 0.067, "e": 0.133},
                     {"s": 0.267, "e": 0.333}],
                    work,
                )
            finally:
                pipeline.CUT_BOUNDARIES = old_boundaries
            probe = subprocess.run([
                pipeline.FFPROBE, "-v", "error",
                "-show_entries", "stream=codec_type,duration",
                "-of", "json", str(out),
            ], check=True, capture_output=True, text=True)
            streams = json.loads(probe.stdout)["streams"]
            video = next(float(s["duration"]) for s in streams
                         if s["codec_type"] == "video")
            audio = next(float(s["duration"]) for s in streams
                         if s["codec_type"] == "audio")
            self.assertLessEqual(abs(video - audio), 0.002)


if __name__ == "__main__":
    unittest.main()
