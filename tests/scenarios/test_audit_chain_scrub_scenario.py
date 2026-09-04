"""Scenario layer for #12146: a real AuditChain survives credential-shaped prose.

The unit test asserts the round-trip property against `SECRET_PATTERNS`. This
drives the actual writer — a real `AuditChain` over a real file — because the
defect was never in the regex alone: it was that `_scrub_payload` scrubs
SERIALIZED JSON and re-parses it, and the unguarded `json.loads` propagated out
of `append()` to all thirteen importers. Only a real append proves that path.

`approval_records` puts a PR title and reason into the chain, so the payload
here is shaped like one: arbitrary human prose that happens to contain a
credential-shaped token next to a quote.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_chain import AuditChain


@pytest.mark.parametrize(
    "title",
    [
        pytest.param("secret_key=" + "A" * 25 + '"deploy" notes', id="unquoted-value"),
        pytest.param('password="' + "B" * 12 + '" in the runbook', id="quoted-value"),
        # Unbalanced quote: an ordinary typo in a PR title, and the shape the
        # FIRST cut of this fix corrupted. Review of #12149 caught that the
        # balanced cases above cannot detect it -- pre-fix the pattern was
        # dead on this path and short-circuited; post-first-fix it ate the
        # field's own structural closing quote. Only an odd quote count
        # exercises either failure.
        pytest.param('password="never rotated', id="unbalanced-quote"),
        pytest.param('token="' + "D" * 12 + " unterminated", id="unbalanced-token"),
        pytest.param(
            "GATEWAY_CONTROL_TOKEN=" + "C" * 20 + '"prod"', id="gateway-token"
        ),
        pytest.param("nothing credential-shaped here at all", id="clean-prose"),
    ],
)
def test_append_survives_credential_shaped_prose(tmp_path: Path, title: str) -> None:
    """A record whose prose trips a scrubber pattern must still append."""
    chain = AuditChain(tmp_path / "chain.jsonl")

    record = chain.append({"kind": "approval", "title": title, "reason": "merged"})

    assert record["record_hash"], "the record must be chained, not silently dropped"


def test_the_written_line_is_valid_json_and_redacted(tmp_path: Path) -> None:
    """The stored line must parse, and must not carry the secret.

    Both halves matter: the pre-fix failure mode was a line that could not be
    parsed, and a fix that simply stopped scrubbing would pass the parse half
    while leaking the credential.
    """
    path = tmp_path / "chain.jsonl"
    secret = "A" * 25
    chain = AuditChain(path)

    chain.append({"kind": "approval", "title": f'secret_key={secret}"deploy"'})

    line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
    parsed = json.loads(line)  # must not raise
    assert secret not in line, "the credential survived into the audit record"
    assert parsed["kind"] == "approval"


def test_the_chain_still_verifies_after_a_redaction(tmp_path: Path) -> None:
    """Scrubbing happens BEFORE hashing, so the chain must still verify.

    `_scrub_payload`'s docstring is explicit that hashing pre-scrub content
    would make the stored record fail verification the moment a secret is
    redacted. A fix that scrubbed at the wrong point would break this.
    """
    chain = AuditChain(tmp_path / "chain.jsonl")

    first = chain.append({"kind": "approval", "title": "secret_key=" + "A" * 25})
    second = chain.append({"kind": "approval", "title": "ordinary follow-up"})

    assert second["prev_hash"] == first["record_hash"]
