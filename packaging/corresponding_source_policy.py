#!/usr/bin/env python3
"""Validate the recorded policy required before third-party Helper delivery.

This validates that the release owner recorded every technical and delivery
decision needed by the release workflow. It does not decide license scope or
provide legal advice.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import socket
import stat
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit


SCHEMA = "autoeditor-corresponding-source-policy/v1"
PLATFORMS = ["mac-arm64", "mac-x64", "windows-x64"]
ROOT_FIELDS = {
    "approval", "distribution", "release_channel", "schema", "scope",
    "status",
}
DISTRIBUTION_FIELDS = {
    "availability_rule", "contact", "installer_access_mode",
    "installer_route_template", "method", "source_access_mode",
    "source_route_template",
}
SCOPE_FIELDS = {
    "autoeditor_repository", "build_scripts_complete",
    "license_texts_complete", "native_lineages_complete", "platforms",
}
APPROVAL_FIELDS = {
    "approved_on", "decision_record", "decision_record_sha256", "owner",
    "reviewer",
}
APPROVED_REPOSITORY_DECISIONS = {"include"}
APPROVED_ACCESS_MODES = {"public", "recipient-authenticated"}
AVAILABILITY_RULE = "while-corresponding-installer-is-offered"
PLACEHOLDER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:REPLACE(?:_WITH)?|TODO|TBD|CHOOSE)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
GITHUB_HANDLE_RE = re.compile(
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z"
)
SHA256_RE = re.compile(r"[a-f0-9]{64}\Z")
DNS_LABEL_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)
RESERVED_HOSTS = {
    "example", "example.com", "example.net", "example.org", "home.arpa",
    "internal", "invalid", "local", "localdomain", "localhost", "onion",
    "test",
}
RESERVED_SUFFIXES = (
    ".example", ".home.arpa", ".internal", ".invalid", ".local",
    ".localdomain", ".localhost", ".onion", ".test",
)
WINDOWS_RESERVED_NAMES = {
    "aux", "clock$", "con", "conin$", "conout$", "nul", "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
    *(f"com{number}" for number in ("¹", "²", "³")),
    *(f"lpt{number}" for number in ("¹", "²", "³")),
}
FORBIDDEN_PATH_CHARS = frozenset('<>:"\\|?*')


class CorrespondingSourcePolicyError(ValueError):
    """The recorded corresponding-source policy is incomplete or malformed."""


def _normalize_lf_bytes(raw: bytes, label: str) -> bytes:
    """Accept one consistent checkout line ending and return canonical LF bytes."""
    if b"\r" not in raw:
        return raw
    without_crlf = raw.replace(b"\r\n", b"")
    if b"\r" in without_crlf or b"\n" in without_crlf:
        raise CorrespondingSourcePolicyError(
            f"{label} has malformed or mixed line endings"
        )
    return raw.replace(b"\r\n", b"\n")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CorrespondingSourcePolicyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise CorrespondingSourcePolicyError(
                "policy path must be a regular file, not a symlink"
            )
        raw = _normalize_lf_bytes(path.read_bytes(), "policy JSON")
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except CorrespondingSourcePolicyError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorrespondingSourcePolicyError(f"cannot read policy {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CorrespondingSourcePolicyError("policy root must be an object")
    return value, raw


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise CorrespondingSourcePolicyError(
            f"{label} fields are invalid ({'; '.join(details)})"
        )


def _string(value: Any, label: str, *, approved: bool) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CorrespondingSourcePolicyError(f"{label} must be a trimmed string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise CorrespondingSourcePolicyError(f"{label} contains control characters")
    if approved and PLACEHOLDER_RE.search(value):
        raise CorrespondingSourcePolicyError(f"{label} still contains a placeholder")
    return value


def _require_public_host(
    hostname: str,
    label: str,
    *,
    approved: bool,
    bracketed: bool = False,
) -> None:
    if not hostname.isascii():
        raise CorrespondingSourcePolicyError(
            f"{label} host must be ASCII and may not rely on IDNA normalization"
        )
    host = hostname.lower()

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if bracketed:
        if (
            address is None
            or address.version != 6
            or not address.is_global
            or address.is_multicast
        ):
            raise CorrespondingSourcePolicyError(
                f"{label} bracketed host must be a global IPv6 address"
            )
        return

    if address is not None:
        if (
            address.version != 4
            or not address.is_global
            or address.is_multicast
        ):
            raise CorrespondingSourcePolicyError(
                f"{label} must not use a non-public IP address"
            )
        return

    try:
        socket.inet_aton(host)
    except (OSError, UnicodeError):
        pass
    else:
        raise CorrespondingSourcePolicyError(
            f"{label} may not use a noncanonical numeric IP address"
        )
    if re.fullmatch(r"[0-9.]+", host):
        raise CorrespondingSourcePolicyError(
            f"{label} may not use an invalid numeric IP address"
        )

    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 2
        or any(not DNS_LABEL_RE.fullmatch(part) for part in labels)
    ):
        raise CorrespondingSourcePolicyError(
            f"{label} host must be an ASCII LDH hostname or global IP address"
        )
    if approved and (
        host in RESERVED_HOSTS
        or any(host.endswith(suffix) for suffix in RESERVED_SUFFIXES)
        or any(host.endswith(f".{reserved}") for reserved in RESERVED_HOSTS)
    ):
        raise CorrespondingSourcePolicyError(
            f"{label} must not use a reserved or local hostname"
        )


def _strict_urlsplit(
    route: str, label: str
) -> tuple[SplitResult, str, bool]:
    try:
        parsed = urlsplit(route)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise CorrespondingSourcePolicyError(
            f"{label} is not a valid URL: {exc}"
        ) from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CorrespondingSourcePolicyError(
            f"{label} must be an HTTPS URL without credentials"
        )

    netloc = parsed.netloc
    bracketed = netloc.startswith("[")
    if bracketed:
        closing = netloc.find("]")
        suffix = netloc[closing + 1:] if closing >= 0 else ""
        if closing < 0 or suffix and not re.fullmatch(r":[0-9]+", suffix):
            raise CorrespondingSourcePolicyError(f"{label} has an invalid port")
    elif ":" in netloc:
        raw_host, separator, raw_port = netloc.rpartition(":")
        if (
            not separator
            or ":" in raw_host
            or not re.fullmatch(r"[0-9]+", raw_port)
        ):
            raise CorrespondingSourcePolicyError(f"{label} has an invalid port")
    if port == 0:
        raise CorrespondingSourcePolicyError(f"{label} has an invalid port")
    return parsed, hostname, bracketed


def _route_template(
    value: Any,
    label: str,
    required_tokens: set[str],
    *,
    approved: bool,
) -> str:
    route = _string(value, label, approved=approved)
    parsed, hostname, bracketed = _strict_urlsplit(route, label)
    if parsed.query or parsed.fragment:
        raise CorrespondingSourcePolicyError(
            f"{label} must be an HTTPS URL template without credentials, query, or fragment"
        )
    _require_public_host(
        hostname, label, approved=approved, bracketed=bracketed
    )
    if "%" in route or "\\" in route:
        raise CorrespondingSourcePolicyError(
            f"{label} may not contain percent escapes or backslashes"
        )
    raw_tokens = re.findall(r"\{[^{}]*\}", route)
    tokens = set(raw_tokens)
    if route.count("{") != len(raw_tokens) or route.count("}") != len(raw_tokens):
        raise CorrespondingSourcePolicyError(f"{label} has malformed placeholders")
    if tokens != required_tokens or any(route.count(token) != 1 for token in tokens):
        raise CorrespondingSourcePolicyError(
            f"{label} must contain exactly: {', '.join(sorted(required_tokens))}"
        )
    path_parts = parsed.path.split("/")
    if not parsed.path.startswith("/") or any(
        part in {"", ".", ".."} for part in path_parts[1:]
    ):
        raise CorrespondingSourcePolicyError(
            f"{label} must use nonempty normalized path segments"
        )
    token_parts = [part for part in path_parts if "{" in part or "}" in part]
    if set(token_parts) != required_tokens or len(token_parts) != len(required_tokens):
        raise CorrespondingSourcePolicyError(
            f"{label} placeholders must each occupy one complete path segment"
        )
    if re.search(r"(?:^|[/_.-])(latest|current)(?:$|[/_.-])", route, re.IGNORECASE):
        raise CorrespondingSourcePolicyError(f"{label} may not use a moving release path")
    return route


def _utf16_code_units(value: str, label: str) -> int:
    try:
        encoded = value.encode("utf-16-le")
    except UnicodeEncodeError as exc:
        raise CorrespondingSourcePolicyError(
            f"{label} contains invalid Unicode"
        ) from exc
    return len(encoded) // 2


def _decision_record(value: Any, *, approved: bool) -> str:
    record = _string(value, "approval.decision_record", approved=approved)
    parts = record.split("/")
    if (
        record.startswith("/")
        or "\\" in record
        or not record.startswith("docs/")
        or any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or any(ord(char) < 32 or char in FORBIDDEN_PATH_CHARS for char in part)
            or (
                part.split(".", 1)[0].rstrip(" .").casefold()
                in WINDOWS_RESERVED_NAMES
            )
            for part in parts
        )
    ):
        raise CorrespondingSourcePolicyError(
            "approval.decision_record must be a safe repository path under docs/"
        )
    if (
        _utf16_code_units(record, "approval.decision_record") > 180
        or any(
            _utf16_code_units(part, "approval.decision_record component") > 100
            for part in parts
        )
    ):
        raise CorrespondingSourcePolicyError(
            "approval.decision_record exceeds conservative Windows path bounds"
        )
    return record


def _approval_identity(value: Any, label: str, *, approved: bool) -> str:
    identity = _string(value, label, approved=approved)
    if not approved:
        return identity
    if GITHUB_HANDLE_RE.fullmatch(identity):
        return identity
    if EMAIL_RE.fullmatch(identity):
        _require_public_host(
            identity.rsplit("@", 1)[1], label, approved=True
        )
        return identity
    raise CorrespondingSourcePolicyError(
        f"{label} must be a GitHub handle or email address"
    )


def _contact(value: Any, *, approved: bool) -> str:
    contact = _string(value, "distribution.contact", approved=approved)
    if EMAIL_RE.fullmatch(contact):
        _require_public_host(
            contact.rsplit("@", 1)[1],
            "distribution.contact",
            approved=approved,
        )
        return contact
    parsed, hostname, bracketed = _strict_urlsplit(
        contact, "distribution.contact"
    )
    if parsed.fragment:
        raise CorrespondingSourcePolicyError(
            "distribution.contact must not contain a fragment"
        )
    _require_public_host(
        hostname,
        "distribution.contact",
        approved=approved,
        bracketed=bracketed,
    )
    return contact


def _decision_record_bytes(repo_root: Path, relative: str) -> bytes:
    try:
        root_stat = repo_root.lstat()
    except OSError as exc:
        raise CorrespondingSourcePolicyError(
            f"cannot inspect repository root {repo_root}: {exc}"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise CorrespondingSourcePolicyError(
            "repository root must be a real directory, not a symlink"
        )
    current = repo_root
    for index, part in enumerate(relative.split("/")):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CorrespondingSourcePolicyError(
                f"cannot inspect approval decision record {relative}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CorrespondingSourcePolicyError(
                "approval decision record path must not contain symlinks"
            )
        if index < len(relative.split("/")) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                raise CorrespondingSourcePolicyError(
                    "approval decision record parent is not a directory"
                )
        elif not stat.S_ISREG(metadata.st_mode):
            raise CorrespondingSourcePolicyError(
                "approval decision record must be a regular file"
            )
    try:
        return current.read_bytes()
    except OSError as exc:
        raise CorrespondingSourcePolicyError(
            f"cannot read approval decision record {relative}: {exc}"
        ) from exc


def _canonical_decision_record_bytes(policy: dict[str, Any]) -> bytes:
    approval = policy["approval"]
    distribution = policy["distribution"]
    scope = policy["scope"]
    lines = (
        "DECISION_STATUS: APPROVED",
        f"APPROVED_BY_OWNER: {approval['owner']}",
        f"APPROVED_ON: {approval['approved_on']}",
        f"AUTOEDITOR_REPOSITORY_DECISION: {scope['autoeditor_repository']}",
        f"AVAILABILITY_RULE: {distribution['availability_rule']}",
        f"DISTRIBUTION_METHOD: {distribution['method']}",
        f"INSTALLER_ACCESS_MODE: {distribution['installer_access_mode']}",
        f"REVIEWED_BY: {approval['reviewer']}",
        f"SOURCE_ACCESS_MODE: {distribution['source_access_mode']}",
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _validate_decision_record(
    repo_root: Path,
    policy: dict[str, Any],
) -> None:
    approval = policy["approval"]
    relative = approval["decision_record"]
    raw = _normalize_lf_bytes(
        _decision_record_bytes(repo_root, relative),
        "approval decision record",
    )
    expected_sha = approval["decision_record_sha256"]
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise CorrespondingSourcePolicyError(
            "approval decision record SHA256 does not match policy"
        )
    if raw != _canonical_decision_record_bytes(policy):
        raise CorrespondingSourcePolicyError(
            "approval decision record is not the exact canonical approved record"
        )
def _validate_policy_structure(
    value: dict[str, Any], *, require_approved: bool = True
) -> dict:
    """Validate policy structure without claiming external release approval."""
    _exact_fields(value, ROOT_FIELDS, "policy")
    if value["schema"] != SCHEMA:
        raise CorrespondingSourcePolicyError(f"policy schema must be {SCHEMA}")
    if value["release_channel"] != "helper":
        raise CorrespondingSourcePolicyError("release_channel must be helper")
    allowed_statuses = {"approved"} if require_approved else {"approved", "pending"}
    if value["status"] not in allowed_statuses:
        raise CorrespondingSourcePolicyError(
            "policy status must be approved" if require_approved
            else "example policy status must be pending or approved"
        )
    approved = value["status"] == "approved"

    distribution = value["distribution"]
    scope = value["scope"]
    approval = value["approval"]
    if not isinstance(distribution, dict) or not isinstance(scope, dict) \
            or not isinstance(approval, dict):
        raise CorrespondingSourcePolicyError(
            "distribution, scope, and approval must be objects"
        )
    _exact_fields(distribution, DISTRIBUTION_FIELDS, "distribution")
    _exact_fields(scope, SCOPE_FIELDS, "scope")
    _exact_fields(approval, APPROVAL_FIELDS, "approval")

    if distribution["method"] != "internet-download-equivalent-access":
        raise CorrespondingSourcePolicyError(
            "distribution.method must be internet-download-equivalent-access"
        )
    for field in ("installer_access_mode", "source_access_mode"):
        if distribution[field] not in APPROVED_ACCESS_MODES:
            raise CorrespondingSourcePolicyError(f"distribution.{field} is invalid")
    if distribution["source_access_mode"] != distribution["installer_access_mode"]:
        raise CorrespondingSourcePolicyError(
            "source access must be equivalent to installer access"
        )
    if distribution["availability_rule"] != AVAILABILITY_RULE:
        raise CorrespondingSourcePolicyError(
            f"distribution.availability_rule must be {AVAILABILITY_RULE}"
        )
    _contact(distribution["contact"], approved=approved)
    _route_template(
        distribution["installer_route_template"],
        "distribution.installer_route_template",
        {"{commit}", "{platform}", "{tag}"},
        approved=approved,
    )
    _route_template(
        distribution["source_route_template"],
        "distribution.source_route_template",
        {"{commit}", "{platform}", "{sha256}", "{tag}"},
        approved=approved,
    )

    platforms = scope["platforms"]
    if platforms != PLATFORMS:
        raise CorrespondingSourcePolicyError(
            "scope.platforms must list mac-arm64, mac-x64, windows-x64 exactly"
        )
    repository_decision = scope["autoeditor_repository"]
    if approved and repository_decision not in APPROVED_REPOSITORY_DECISIONS:
        raise CorrespondingSourcePolicyError(
            "scope.autoeditor_repository must be include for an approved v1 policy"
        )
    if not approved and repository_decision not in (
        APPROVED_REPOSITORY_DECISIONS | {"pending"}
    ):
        raise CorrespondingSourcePolicyError("scope.autoeditor_repository is invalid")
    for field in (
        "native_lineages_complete",
        "build_scripts_complete",
        "license_texts_complete",
    ):
        if type(scope[field]) is not bool or (approved and scope[field] is not True):
            raise CorrespondingSourcePolicyError(f"scope.{field} must be true")

    owner = _approval_identity(
        approval["owner"], "approval.owner", approved=approved
    )
    reviewer = _approval_identity(
        approval["reviewer"], "approval.reviewer", approved=approved
    )
    if approved and owner.casefold() == reviewer.casefold():
        raise CorrespondingSourcePolicyError(
            "approval.owner and approval.reviewer must be different identities"
        )
    _decision_record(approval["decision_record"], approved=approved)
    record_sha = approval["decision_record_sha256"]
    if approved and (
        not isinstance(record_sha, str) or not SHA256_RE.fullmatch(record_sha)
    ):
        raise CorrespondingSourcePolicyError(
            "approval.decision_record_sha256 must be a lowercase SHA256"
        )
    if not approved and not (
        record_sha == "pending"
        or isinstance(record_sha, str) and SHA256_RE.fullmatch(record_sha)
    ):
        raise CorrespondingSourcePolicyError(
            "pending approval.decision_record_sha256 must be pending or a SHA256"
        )
    approved_on = _string(
        approval["approved_on"], "approval.approved_on", approved=approved
    )
    if approved:
        try:
            parsed_date = date.fromisoformat(approved_on)
        except ValueError as exc:
            raise CorrespondingSourcePolicyError(
                "approval.approved_on must be an ISO date"
            ) from exc
        if parsed_date > date.today():
            raise CorrespondingSourcePolicyError(
                "approval.approved_on may not be in the future"
            )
    return value


def _canonical_policy_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _verify_external_policy_sha256(
    canonical: bytes, expected_policy_sha256: str | None
) -> None:
    if (
        not isinstance(expected_policy_sha256, str)
        or not SHA256_RE.fullmatch(expected_policy_sha256)
    ):
        raise CorrespondingSourcePolicyError(
            "approved policy requires an external expected_policy_sha256"
        )
    actual = hashlib.sha256(canonical).hexdigest()
    if actual != expected_policy_sha256:
        raise CorrespondingSourcePolicyError(
            "approved policy does not match external expected_policy_sha256"
        )


def validate_policy(
    value: dict[str, Any],
    *,
    require_approved: bool = True,
    expected_policy_sha256: str | None = None,
    repo_root: Path | None = None,
) -> dict:
    """Fully validate and externally bind any approved policy."""
    validated = _validate_policy_structure(
        value, require_approved=require_approved
    )
    if validated["status"] == "approved":
        _verify_external_policy_sha256(
            _canonical_policy_bytes(validated), expected_policy_sha256
        )
        if repo_root is None:
            raise CorrespondingSourcePolicyError(
                "approved policy validation requires repo_root"
            )
        _validate_decision_record(repo_root, validated)
    return validated


def load_policy(
    path: Path,
    *,
    require_approved: bool = True,
    repo_root: Path | None = None,
    expected_policy_sha256: str | None = None,
) -> dict:
    value, raw = _load_json(path)
    validated = _validate_policy_structure(
        value, require_approved=require_approved
    )
    canonical = _canonical_policy_bytes(validated)
    if raw != canonical:
        raise CorrespondingSourcePolicyError("policy JSON is not canonical")
    if validated["status"] == "approved":
        _verify_external_policy_sha256(canonical, expected_policy_sha256)
        _validate_decision_record(
            repo_root or Path(__file__).resolve().parents[1], validated
        )
    return validated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--expected-policy-sha256")
    parser.add_argument("--allow-pending-example", action="store_true")
    args = parser.parse_args()
    try:
        if args.allow_pending_example and not args.policy.name.endswith(".example.json"):
            raise CorrespondingSourcePolicyError(
                "pending policy validation is restricted to .example.json files"
            )
        policy = load_policy(
            args.policy,
            require_approved=not args.allow_pending_example,
            repo_root=args.repo_root,
            expected_policy_sha256=args.expected_policy_sha256,
        )
    except CorrespondingSourcePolicyError as exc:
        parser.error(str(exc))
    if policy["status"] == "pending":
        print(
            "corresponding-source example structurally verified: pending "
            "(not release-approved)"
        )
    else:
        print("corresponding-source policy verified: approved")


if __name__ == "__main__":
    main()
