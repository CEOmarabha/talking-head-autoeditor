from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "corresponding_source_policy.py"
SPEC = importlib.util.spec_from_file_location("corresponding_source_policy", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load policy validator: {SCRIPT}")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class CorrespondingSourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.approved = {
            "schema": policy.SCHEMA,
            "status": "approved",
            "release_channel": "helper",
            "distribution": {
                "method": "internet-download-equivalent-access",
                "installer_access_mode": "public",
                "source_access_mode": "public",
                "availability_rule": policy.AVAILABILITY_RULE,
                "contact": "source@autoeditor.app",
                "installer_route_template": (
                    "https://downloads.autoeditor.app/helper/{tag}/{commit}/"
                    "{platform}"
                ),
                "source_route_template": (
                    "https://downloads.autoeditor.app/helper/{tag}/{commit}/"
                    "{platform}/"
                    "source/{sha256}"
                ),
            },
            "scope": {
                "platforms": list(policy.PLATFORMS),
                "autoeditor_repository": "include",
                "native_lineages_complete": True,
                "build_scripts_complete": True,
                "license_texts_complete": True,
            },
            "approval": {
                "owner": "@release-owner",
                "reviewer": "@policy-reviewer",
                "approved_on": "2026-08-08",
                "decision_record": "docs/CORRESPONDING_SOURCE.md",
                "decision_record_sha256": "0" * 64,
            },
        }

    def _write(self, root: Path, value: dict, name: str = "policy.json") -> Path:
        path = root / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path

    def _decision_text(self, value: dict) -> str:
        approval = value["approval"]
        distribution = value["distribution"]
        scope = value["scope"]
        lines = [
            "DECISION_STATUS: APPROVED",
            f"APPROVED_BY_OWNER: {approval['owner']}",
            f"APPROVED_ON: {approval['approved_on']}",
            f"AUTOEDITOR_REPOSITORY_DECISION: {scope['autoeditor_repository']}",
            f"AVAILABILITY_RULE: {distribution['availability_rule']}",
            f"DISTRIBUTION_METHOD: {distribution['method']}",
            f"INSTALLER_ACCESS_MODE: {distribution['installer_access_mode']}",
            f"REVIEWED_BY: {approval['reviewer']}",
            f"SOURCE_ACCESS_MODE: {distribution['source_access_mode']}",
        ]
        return "\n".join(lines) + "\n"

    def _prepare_approved(
        self, root: Path, value: dict | None = None
    ) -> dict:
        approved = copy.deepcopy(value or self.approved)
        decision = root / approved["approval"]["decision_record"]
        decision.parent.mkdir(parents=True, exist_ok=True)
        text = self._decision_text(approved)
        decision.write_text(text, encoding="utf-8")
        approved["approval"]["decision_record_sha256"] = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
        return approved

    def _write_approved(self, root: Path, value: dict | None = None) -> Path:
        approved = self._prepare_approved(root, value)
        return self._write(root, approved)

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _value_sha256(value: dict) -> str:
        canonical = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        return hashlib.sha256(canonical).hexdigest()

    def _assert_all_approved_entry_points_reject(
        self,
        root: Path,
        path: Path,
        expected_policy_sha256: str,
        pattern: str,
    ) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(
            policy.CorrespondingSourcePolicyError, pattern
        ):
            policy.validate_policy(
                value,
                repo_root=root,
                expected_policy_sha256=expected_policy_sha256,
            )
        with self.assertRaisesRegex(
            policy.CorrespondingSourcePolicyError, pattern
        ):
            policy.load_policy(
                path,
                repo_root=root,
                expected_policy_sha256=expected_policy_sha256,
            )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--policy",
                str(path),
                "--repo-root",
                str(root),
                "--expected-policy-sha256",
                expected_policy_sha256,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stderr, pattern)

    def test_approved_policy_is_canonical_and_cli_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write_approved(root)
            expected = json.loads(path.read_text(encoding="utf-8"))
            expected_sha = self._sha256(path)
            self.assertEqual(
                policy.load_policy(
                    path,
                    repo_root=root,
                    expected_policy_sha256=expected_sha,
                ),
                expected,
            )
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "--policy", str(path),
                    "--repo-root", str(root),
                    "--expected-policy-sha256", expected_sha,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("verified: approved", result.stdout)

    def test_approved_policy_requires_external_digest_and_rejects_coherent_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write_approved(root)
            expected_sha = self._sha256(path)

            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError,
                "external expected_policy_sha256",
            ):
                policy.validate_policy(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError, "requires repo_root"
            ):
                policy.validate_policy(
                    json.loads(path.read_text(encoding="utf-8")),
                    expected_policy_sha256=expected_sha,
                )
            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError,
                "external expected_policy_sha256",
            ):
                policy.load_policy(path, repo_root=root)
            missing_flag = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--policy",
                    str(path),
                    "--repo-root",
                    str(root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(missing_flag.returncode, 0)
            self.assertIn("expected_policy_sha256", missing_flag.stderr)
            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError,
                "does not match external",
            ):
                policy.load_policy(
                    path,
                    repo_root=root,
                    expected_policy_sha256="f" * 64,
                )

            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["approval"]["owner"] = "@different-release-owner"
            changed["approval"]["reviewer"] = "@different-policy-reviewer"
            decision_text = self._decision_text(changed)
            decision = root / changed["approval"]["decision_record"]
            decision.write_text(decision_text, encoding="utf-8")
            changed["approval"]["decision_record_sha256"] = hashlib.sha256(
                decision_text.encode("utf-8")
            ).hexdigest()
            self._write(root, changed)

            self._assert_all_approved_entry_points_reject(
                root, path, expected_sha, "does not match external"
            )

    def test_pending_example_is_explicitly_non_releasable(self):
        example = ROOT / "packaging" / "corresponding-source-policy.example.json"
        pending = policy.load_policy(example, require_approved=False)
        self.assertEqual(pending["status"], "pending")
        with self.assertRaisesRegex(
            policy.CorrespondingSourcePolicyError, "status must be approved"
        ):
            policy.load_policy(example)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--policy",
                str(example),
                "--allow-pending-example",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not release-approved", result.stdout)

    def test_crlf_checkout_uses_the_same_canonical_lf_digests(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write_approved(root)
            expected_policy_sha = self._sha256(path)
            value = json.loads(path.read_text(encoding="utf-8"))
            decision = root / value["approval"]["decision_record"]
            expected_record_sha = value["approval"]["decision_record_sha256"]

            decision.write_bytes(decision.read_bytes().replace(b"\n", b"\r\n"))
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

            self.assertNotEqual(self._sha256(path), expected_policy_sha)
            self.assertNotEqual(self._sha256(decision), expected_record_sha)
            self.assertEqual(
                policy.validate_policy(
                    value,
                    repo_root=root,
                    expected_policy_sha256=expected_policy_sha,
                ),
                value,
            )
            self.assertEqual(
                policy.load_policy(
                    path,
                    repo_root=root,
                    expected_policy_sha256=expected_policy_sha,
                ),
                value,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--policy",
                    str(path),
                    "--repo-root",
                    str(root),
                    "--expected-policy-sha256",
                    expected_policy_sha,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_lone_and_mixed_line_endings_fail_closed(self):
        for replacement in (b"\r", b"\r\n"):
            with self.subTest(policy_replacement=replacement):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    path = self._write_approved(root)
                    expected_sha = self._sha256(path)
                    raw = path.read_bytes()
                    path.write_bytes(raw.replace(b"\n", replacement, 1))
                    with self.assertRaisesRegex(
                        policy.CorrespondingSourcePolicyError, "line endings"
                    ):
                        policy.load_policy(
                            path,
                            repo_root=root,
                            expected_policy_sha256=expected_sha,
                        )

        for replacement in (b"\r", b"\r\n"):
            with self.subTest(record_replacement=replacement):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    path = self._write_approved(root)
                    expected_sha = self._sha256(path)
                    value = json.loads(path.read_text(encoding="utf-8"))
                    decision = root / value["approval"]["decision_record"]
                    raw = decision.read_bytes()
                    decision.write_bytes(raw.replace(b"\n", replacement, 1))
                    self._assert_all_approved_entry_points_reject(
                        root, path, expected_sha, "line endings"
                    )

    def test_unknown_duplicate_and_noncanonical_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            unknown = copy.deepcopy(self.approved)
            unknown["extra"] = True
            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError, "unknown extra"
            ):
                policy.load_policy(self._write(root, unknown))

            duplicate = root / "duplicate.json"
            duplicate.write_text(
                '{"schema":"x","schema":"y"}\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError, "duplicate JSON key"
            ):
                policy.load_policy(duplicate)

            noncanonical = root / "noncanonical.json"
            noncanonical.write_text(json.dumps(self.approved), encoding="utf-8")
            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError, "not canonical"
            ):
                policy.load_policy(noncanonical)

    def test_release_rejects_placeholders_and_incomplete_scope(self):
        cases = []
        value = copy.deepcopy(self.approved)
        value["approval"]["owner"] = "REPLACE_WITH_OWNER"
        cases.append(value)
        value = copy.deepcopy(self.approved)
        value["scope"]["native_lineages_complete"] = False
        cases.append(value)
        value = copy.deepcopy(self.approved)
        value["scope"]["platforms"] = ["windows-x64"]
        cases.append(value)
        value = copy.deepcopy(self.approved)
        value["scope"]["autoeditor_repository"] = "pending"
        cases.append(value)
        for invalid in cases:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                prepared = self._prepare_approved(root, invalid)
                with self.assertRaises(policy.CorrespondingSourcePolicyError):
                    policy.validate_policy(
                        prepared,
                        expected_policy_sha256=self._value_sha256(prepared),
                        repo_root=root,
                    )

    def test_release_routes_must_be_immutable_https_templates(self):
        routes = (
            "http://downloads.autoeditor.app/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://downloads.autoeditor.app/helper/latest/{commit}/{platform}/source/{sha256}",
            "https://user:secret@downloads.autoeditor.app/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://downloads.autoeditor.app/helper/{tag}/{commit}/{platform}/source",
            "https://downloads.autoeditor.app/helper/{tag}/{commit}/{platform}/source/{sha256}?token=x",
            "https://downloads.autoeditor.app/helper/{tag}/{commit}/../{platform}/source/{sha256}",
            "https://downloads.autoeditor.app/helper/{tag}/{commit}/{platform}/{UNBOUND_ROUTE_PART}/source/{sha256}",
            "https://2130706433/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://0x7f000001/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://999.999.999.999/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://１２７。０。０。１/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://not a host/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://downloads.autoeditor.app:notaport/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://downloads.autoeditor.app:70000/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://downloads.local/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://224.0.0.1/helper/{tag}/{commit}/{platform}/source/{sha256}",
            "https://[ff02::1]/helper/{tag}/{commit}/{platform}/source/{sha256}",
        )
        for route in routes:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                invalid = copy.deepcopy(self.approved)
                invalid["distribution"]["source_route_template"] = route
                prepared = self._prepare_approved(root, invalid)
                with self.assertRaises(policy.CorrespondingSourcePolicyError):
                    policy.validate_policy(
                        prepared,
                        expected_policy_sha256=self._value_sha256(prepared),
                        repo_root=root,
                    )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            global_ipv6 = copy.deepcopy(self.approved)
            global_ipv6["distribution"]["source_route_template"] = (
                "https://[2606:4700:4700::1111]:8443/helper/{tag}/{commit}/"
                "{platform}/source/{sha256}"
            )
            prepared = self._prepare_approved(root, global_ipv6)
            self.assertEqual(
                policy.validate_policy(
                    prepared,
                    expected_policy_sha256=self._value_sha256(prepared),
                    repo_root=root,
                ),
                prepared,
            )

    def test_approval_date_contact_and_decision_record_are_strict(self):
        for replacement in ("not-a-date", "2999-01-01"):
            with self.subTest(date=replacement), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                invalid = copy.deepcopy(self.approved)
                invalid["approval"]["approved_on"] = replacement
                prepared = self._prepare_approved(root, invalid)
                with self.assertRaises(policy.CorrespondingSourcePolicyError):
                    policy.validate_policy(
                        prepared,
                        expected_policy_sha256=self._value_sha256(prepared),
                        repo_root=root,
                    )

        unsafe_paths = (
            "../outside.md",
            "docs/CON.md",
            "docs/CLOCK$.md",
            "docs/CONIN$.md",
            "docs/conout$.txt",
            "docs/COM¹.txt",
            "docs/com².txt",
            "docs/COM³.txt",
            "docs/COM1 .txt",
            "docs/LPT¹.txt",
            "docs/lpt².txt",
            "docs/LPT³.txt",
            "docs/line\nbreak.md",
        )
        for replacement in unsafe_paths:
            invalid = copy.deepcopy(self.approved)
            invalid["approval"]["decision_record"] = replacement
            with self.subTest(path=replacement), self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError,
                "safe repository path|control characters|Windows path bounds",
            ):
                policy.validate_policy(
                    invalid,
                    expected_policy_sha256=self._value_sha256(invalid),
                    repo_root=Path("."),
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            invalid = copy.deepcopy(self.approved)
            invalid["distribution"]["contact"] = "not a contact"
            prepared = self._prepare_approved(root, invalid)
            with self.assertRaises(policy.CorrespondingSourcePolicyError):
                policy.validate_policy(
                    prepared,
                    expected_policy_sha256=self._value_sha256(prepared),
                    repo_root=root,
                )

    def test_source_access_and_public_hosts_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            invalid = copy.deepcopy(self.approved)
            invalid["distribution"]["source_access_mode"] = (
                "recipient-authenticated"
            )
            prepared = self._prepare_approved(root, invalid)
            with self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError, "equivalent"
            ):
                policy.validate_policy(
                    prepared,
                    expected_policy_sha256=self._value_sha256(prepared),
                    repo_root=root,
                )

        for hostname in (
            "localhost",
            "localhost.localdomain",
            "127.0.0.1",
            "downloads.example.com",
            "source.home.arpa",
        ):
            with self.subTest(hostname=hostname), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                invalid = copy.deepcopy(self.approved)
                invalid["distribution"]["source_route_template"] = (
                    f"https://{hostname}/helper/{{tag}}/{{commit}}/"
                    "{platform}/source/{sha256}"
                )
                prepared = self._prepare_approved(root, invalid)
                with self.assertRaises(policy.CorrespondingSourcePolicyError):
                    policy.validate_policy(
                        prepared,
                        expected_policy_sha256=self._value_sha256(prepared),
                        repo_root=root,
                    )

    def test_decision_record_uses_conservative_windows_utf16_bounds(self):
        too_long = (
            "docs/" + "a" * 101,
            "docs/" + "😀" * 51 + ".md",
            "docs/" + "a" * 100 + "/" + "b" * 75,
        )
        for relative in too_long:
            invalid = copy.deepcopy(self.approved)
            invalid["approval"]["decision_record"] = relative
            with self.subTest(path=relative), self.assertRaisesRegex(
                policy.CorrespondingSourcePolicyError, "Windows path bounds"
            ):
                policy.validate_policy(
                    invalid,
                    expected_policy_sha256=self._value_sha256(invalid),
                    repo_root=Path("."),
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            boundary = copy.deepcopy(self.approved)
            boundary["approval"]["decision_record"] = (
                "docs/" + "a" * 100 + "/" + "b" * 74
            )
            prepared = self._prepare_approved(root, boundary)
            self.assertEqual(
                policy.validate_policy(
                    prepared,
                    expected_policy_sha256=self._value_sha256(prepared),
                    repo_root=root,
                ),
                prepared,
            )

    def test_approved_policy_binds_real_decision_record_and_identities(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write_approved(root)
            expected_sha = self._sha256(path)
            value = json.loads(path.read_text(encoding="utf-8"))
            policy.validate_policy(
                value,
                repo_root=root,
                expected_policy_sha256=expected_sha,
            )
            policy.load_policy(
                path,
                repo_root=root,
                expected_policy_sha256=expected_sha,
            )
            decision = root / self.approved["approval"]["decision_record"]
            decision.unlink()
            self._assert_all_approved_entry_points_reject(
                root, path, expected_sha, "decision record"
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._write_approved(root)
            expected_sha = self._sha256(path)
            decision = root / self.approved["approval"]["decision_record"]
            decision.write_text("coherently changed\n", encoding="utf-8")
            self._assert_all_approved_entry_points_reject(
                root, path, expected_sha, "SHA256"
            )

        for field, replacement in (
            ("owner", "Pending Owner"),
            ("reviewer", "Unknown Reviewer"),
            ("reviewer", "@release-owner"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                invalid = copy.deepcopy(self.approved)
                invalid["approval"][field] = replacement
                prepared = self._prepare_approved(root, invalid)
                with self.assertRaises(policy.CorrespondingSourcePolicyError):
                    policy.validate_policy(
                        prepared,
                        expected_policy_sha256=self._value_sha256(prepared),
                        repo_root=root,
                    )

    def test_decision_record_is_exact_closed_and_ordered_for_every_api(self):
        mutations = (
            lambda text: text.replace(
                "DECISION_STATUS: APPROVED", "DECISION_STATUS: REJECTED", 1
            ),
            lambda text: text + "# approval comment\n",
            lambda text: text + "DECISION_STATUS: APPROVED\n",
            lambda text: text + "REJECTION_REASON: policy was rejected\n",
            lambda text: "\n".join(reversed(text.splitlines())) + "\n",
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                path = self._write_approved(root)
                value = json.loads(path.read_text(encoding="utf-8"))
                decision = root / value["approval"]["decision_record"]
                changed = mutate(decision.read_text(encoding="utf-8"))
                decision.write_text(changed, encoding="utf-8")
                value["approval"]["decision_record_sha256"] = hashlib.sha256(
                    changed.encode("utf-8")
                ).hexdigest()
                self._write(root, value)
                expected_sha = self._sha256(path)
                self._assert_all_approved_entry_points_reject(
                    root, path, expected_sha, "exact canonical approved record"
                )

    def test_v1_release_policy_rejects_repository_exclusion(self):
        excluded = copy.deepcopy(self.approved)
        excluded["scope"]["autoeditor_repository"] = (
            "exclude-with-recorded-basis"
        )
        with self.assertRaisesRegex(
            policy.CorrespondingSourcePolicyError,
            "must be include for an approved v1 policy",
        ):
            policy.validate_policy(
                excluded,
                expected_policy_sha256=self._value_sha256(excluded),
            )


if __name__ == "__main__":
    unittest.main()
