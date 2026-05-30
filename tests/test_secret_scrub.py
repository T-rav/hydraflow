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
