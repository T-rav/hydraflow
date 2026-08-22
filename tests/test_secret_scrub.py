"""secret_scrub: canonical secret patterns + scrubber, and the append_jsonl
audit-write chokepoint that uses it (ADR-0085 / SEC-AUDIT-001)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_util import append_jsonl
from secret_scrub import scan_for_secrets, scrub_secrets


def test_scrubs_anthropic_key() -> None:
    out = scrub_secrets("key=sk-ant-api03-" + "A" * 24 + " done")
    assert "sk-ant-" not in out
    assert "[REDACTED:Anthropic API key]" in out
    assert "done" in out  # surrounding text preserved


def test_scrubs_github_and_aws() -> None:
    out = scrub_secrets("ghp_" + "a" * 36 + " and AKIA" + "A" * 16)
    assert "ghp_" not in out
    assert "AKIA" + "A" * 16 not in out
    assert "[REDACTED:GitHub PAT (classic)]" in out
    assert "[REDACTED:AWS access key]" in out


def test_leaves_legitimate_text_unredacted() -> None:
    # Normal audit prose / a short commit sha must NOT be redacted.
    text = "Fixed in commit a1b2c3d4 — the function returns early on empty input."
    assert scrub_secrets(text) == text


def test_scrub_is_idempotent() -> None:
    once = scrub_secrets("token sk-ant-api03-" + "x" * 24)
    assert scrub_secrets(once) == once  # the [REDACTED:...] markers do not re-match


def test_scan_for_secrets_returns_labels() -> None:
    assert "AWS access key" in scan_for_secrets("AKIA" + "B" * 16)
    assert scan_for_secrets("nothing secret here") == []


def test_append_jsonl_scrubs_secrets_and_stays_valid_json(tmp_path: Path) -> None:
    # A leaked credential in an audit record must not persist, and the scrubbed
    # line must still parse as JSON.
    path = tmp_path / "audit.jsonl"
    secret = "sk-ant-api03-" + "z" * 24
    append_jsonl(path, json.dumps({"transcript": f"command failed: {secret}"}))
    content = path.read_text(encoding="utf-8")
    assert secret not in content
    assert "[REDACTED:Anthropic API key]" in content
    record = json.loads(content.strip())
    assert "REDACTED" in record["transcript"]


@pytest.mark.parametrize(
    "secret",
    [
        "aws_secret_access_key=" + "A" * 24,
        "secret_key=" + "B" * 24,
        "AWS_SECRET_ACCESS_KEY=" + "C" * 24,  # uppercase env-var form (IGNORECASE)
        "ghp_" + "d" * 36,
        "sk-ant-api03-" + "e" * 40,
        "AKIA" + "F" * 16,
        "hfgw_01M0MK5V9ZK5T2KZRPEZYF0D8B." + "g" * 43,
        "hfgwctl_" + "h" * 43,
        "GATEWAY_CONTROL_TOKEN=" + "i" * 34,
    ],
)
def test_append_jsonl_stays_valid_json_with_secret_at_value_end(
    tmp_path: Path, secret: str
) -> None:
    # A matching secret at the END of a JSON string value (immediately before the
    # closing quote + trailing fields) must not let the redaction eat the quote
    # and corrupt the serialized line — which events.py would then silently DROP.
    # This is the case the original sk-ant-only test could never hit.
    path = tmp_path / "audit.jsonl"
    append_jsonl(
        path,
        json.dumps({"transcript": f"leaked {secret}", "user": "alice", "amount": 42}),
    )
    line = path.read_text(encoding="utf-8").strip()
    record = json.loads(line)  # must NOT raise (ADR-0085: stays valid JSON)
    assert secret not in line  # the secret was redacted
    assert record["user"] == "alice"  # trailing fields survive
    assert record["amount"] == 42


def test_openai_pattern_does_not_over_redact_legitimate_ids() -> None:
    # The anchored, length-tightened sk- pattern must leave legitimate
    # hyphenated identifiers untouched on the irreversible audit-write path.
    for benign in (
        "disk-1a2b3c4d5e6f7g8h9i0j",
        "risk-assessmentABCDEF12345678",
        "task-sk-12345678abcdefghij90",
    ):
        assert scrub_secrets(benign) == benign


# --- Gateway credentials (issue #11635, ADR-0138) --------------------------
#
# Shapes taken from the minting code, not from prose:
#   hydraflow_gateway/keys.py::VirtualKeyStore.mint -> f"hfgw_{key_id}.{secret}"
#   with key_id = str(ULID()) and secret = secrets.token_urlsafe(32).
#   gateway/README.md -> control token = "hfgwctl_" + secrets.token_urlsafe(32).
_VIRTUAL_KEY = "hfgw_01M0MK5V9ZK5T2KZRPEZYF0D8B.3xQB9Af63yC_BaWCFGhTZKhRYVrYoUizPVb"
_KEY_ID = "01M0MK5V9ZK5T2KZRPEZYF0D8B"
_CONTROL_TOKEN = "hfgwctl_Zq3-tN7wR1cP0sV8yB2xL5mK9jH4dF6g_A"


def test_scan_detects_gateway_virtual_key() -> None:
    assert "HydraFlow gateway virtual key" in scan_for_secrets(_VIRTUAL_KEY)


def test_scan_detects_gateway_control_token() -> None:
    assert "HydraFlow gateway control token" in scan_for_secrets(_CONTROL_TOKEN)


def test_scan_detects_unquoted_control_token_env_assignment() -> None:
    # The quoted-only "Generic secret assignment" pattern cannot see this shape,
    # which is exactly how an echoed child env prints a legacy control token.
    leak = "HYDRAFLOW_GATEWAY_CONTROL_TOKEN=operator-chosen-token-0123456789"

    assert "HydraFlow gateway control token (assignment)" in scan_for_secrets(leak)


def test_append_jsonl_redacts_gateway_virtual_key(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    append_jsonl(path, json.dumps({"transcript": f"env: {_VIRTUAL_KEY}"}))

    assert _VIRTUAL_KEY not in path.read_text(encoding="utf-8")


def test_append_jsonl_labels_the_redacted_virtual_key(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    append_jsonl(path, json.dumps({"transcript": f"env: {_VIRTUAL_KEY}"}))

    assert "[REDACTED:HydraFlow gateway virtual key]" in path.read_text(
        encoding="utf-8"
    )


def test_append_jsonl_redacts_gateway_control_token(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    append_jsonl(path, json.dumps({"transcript": f"env: {_CONTROL_TOKEN}"}))

    assert _CONTROL_TOKEN not in path.read_text(encoding="utf-8")


def test_append_jsonl_keeps_a_bare_published_key_id(tmp_path: Path) -> None:
    # ADR-0138's read plane publishes key_id (a random ULID, not derived from the
    # token secret) on purpose. append_jsonl is append-only — redacting it here
    # would destroy legitimate published content with no way back.
    path = tmp_path / "audit.jsonl"
    append_jsonl(path, json.dumps({"key_id": _KEY_ID}))

    assert json.loads(path.read_text(encoding="utf-8").strip())["key_id"] == _KEY_ID


@pytest.mark.parametrize(
    "benign",
    [
        pytest.param(_KEY_ID, id="bare-key-id-ulid"),
        pytest.param(f'{{"key_id": "{_KEY_ID}"}}', id="published-key-id-json"),
        pytest.param("01M0MK5V9ZK5T2KZRPEZYF0D8B.json", id="ulid-named-artifact"),
        pytest.param(f"hfgw_{_KEY_ID}.md", id="prefixed-filename"),
        pytest.param("docs/wiki/hfgw_gateway_notes.md", id="file-path"),
        pytest.param("The hfgw prefix namespaces gateway tokens.", id="prose-prefix"),
        pytest.param("format is hfgw_{key_id}.{secret}", id="format-in-prose"),
        pytest.param("53b49052e8f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5", id="git-sha"),
        pytest.param("hydraflow_gateway/keys.py mints it", id="module-path-prose"),
        pytest.param("GATEWAY_CONTROL_TOKEN is required", id="env-name-in-prose"),
        pytest.param("GATEWAY_CONTROL_TOKEN: at least 32 bytes", id="env-name-doc"),
        pytest.param("hfgwctl_v1", id="short-prefixed-identifier"),
    ],
)
def test_gateway_patterns_leave_legitimate_content_intact(benign: str) -> None:
    # Over-matching is the other real failure direction: append_jsonl cannot
    # un-redact, so a pattern that ate any of these would corrupt retained records.
    assert scrub_secrets(benign) == benign


def test_gateway_redaction_markers_do_not_re_match() -> None:
    # Idempotence must hold across BOTH control-token patterns, whatever order
    # they run in: the assignment pattern excludes bracket chars precisely so it
    # can never chew on a [REDACTED:...] marker an earlier pattern emitted.
    once = scrub_secrets(f"{_VIRTUAL_KEY} GATEWAY_CONTROL_TOKEN={_CONTROL_TOKEN} tail")

    assert scrub_secrets(once) == once
