"""Regression test for issue #6494.

Bug: ``WhatsAppBridge.parse_webhook()`` wraps the entire payload parse in
``try/except (IndexError, KeyError, TypeError): pass``.  When a malformed
webhook arrives (missing keys, unexpected nesting), ``text`` stays ``""``
and the method returns ``("", None)``.

Problems:

1. Callers cannot distinguish "valid message with empty body" from
   "malformed payload" -- both produce ``("", None)``.

2. The ``except`` block discards the actual parse error with no logging,
   so webhook schema changes (e.g. Meta updating the WhatsApp Cloud API
   payload format) are invisible.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from whatsapp_bridge import WhatsAppBridge

# ---------------------------------------------------------------------------
# Valid payload fixture (baseline)
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "entry": [
        {
            "changes": [
                {"value": {"messages": [{"text": {"body": "looks good, ship it #42"}}]}}
            ]
        }
    ],
}


# ---------------------------------------------------------------------------
# Malformed payloads that trigger the silent except branch
# ---------------------------------------------------------------------------

# These payloads trigger IndexError or TypeError — the exceptions that ARE
# caught by the except block, causing the silent swallow described in #6494.
MALFORMED_PAYLOADS: list[tuple[str, dict]] = [
    # IndexError: empty entry list → [][0]
    ("empty_entry_list", {"entry": []}),
    # IndexError: empty changes list → [][0]
    ("empty_changes_list", {"entry": [{"changes": []}]}),
    # TypeError: changes is int → 99[0]
    ("changes_is_int", {"entry": [{"changes": 99}]}),
    # TypeError: changes is None → None[0]
    ("changes_is_none", {"entry": [{"changes": None}]}),
]


class TestParseWebhookBaseline:
    """Sanity check: valid payloads still parse correctly."""

    def test_valid_payload_returns_text_and_issue(self) -> None:
        text, issue = WhatsAppBridge.parse_webhook(VALID_PAYLOAD)
        assert text == "looks good, ship it #42"
        assert issue == 42


# ---------------------------------------------------------------------------
# 1. Malformed payloads must produce observable log output
# ---------------------------------------------------------------------------


class TestMalformedWebhookLogsError:
    """BUG (current): malformed payloads silently return ("", None) with no
    logging.  After fix: parse failures must emit at least a debug-level log
    entry so that webhook schema changes are observable.
    """

    @pytest.mark.parametrize("label,payload", MALFORMED_PAYLOADS)
    @pytest.mark.xfail(reason="Regression for issue #6494 — fix not yet landed", strict=False)
    def test_malformed_payload_logs_parse_failure(
        self, label: str, payload: dict, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed payload that triggers the except branch must produce
        a log record (at any level) containing diagnostic information.

        Currently FAILS because the except block is ``pass`` with no logging.
        """
        with caplog.at_level(logging.DEBUG, logger="hydraflow.whatsapp"):
            WhatsAppBridge.parse_webhook(payload)

        parse_failure_logs = [
            r
            for r in caplog.records
            if "parse" in r.message.lower() or "webhook" in r.message.lower()
        ]
        assert parse_failure_logs, (
            f"Malformed payload ({label}) produced no log output -- "
            f"parse failure is completely silent"
        )


# ---------------------------------------------------------------------------
# 2. Malformed payloads must be distinguishable from valid empty messages
# ---------------------------------------------------------------------------


class TestMalformedDistinguishableFromEmpty:
    """BUG (current): a valid webhook with empty body and a malformed webhook
    both return ("", None).  The caller cannot tell them apart.

    After fix: malformed payloads should either raise ``WebhookParseError``
    or return a tri-state that signals parse failure.
    """

    def test_valid_empty_body_returns_empty_string(self) -> None:
        """A valid webhook whose message body is intentionally empty."""
        payload = {
            "entry": [{"changes": [{"value": {"messages": [{"text": {"body": ""}}]}}]}],
        }
        text, issue = WhatsAppBridge.parse_webhook(payload)
        assert text == ""
        assert issue is None

    @pytest.mark.xfail(reason="Regression for issue #6494 — fix not yet landed", strict=False)
    def test_malformed_payload_is_not_identical_to_valid_empty(self) -> None:
        """A malformed payload (changes is int, not a list) must produce
        a distinguishably different result from a valid empty-body message.

        This can be satisfied by either:
        - Raising an exception (e.g. WebhookParseError), OR
        - Returning a different value (e.g. a third element in the tuple)

        Currently FAILS because both cases return ("", None).
        """
        malformed = {"entry": [{"changes": 99}]}
        raised = False
        result = None
        try:
            result = WhatsAppBridge.parse_webhook(malformed)
        except Exception:
            raised = True

        if not raised:
            # If no exception was raised, the result must differ from ("", None)
            assert result != ("", None), (
                "Malformed payload returned ('', None) -- identical to a valid "
                "empty-body message.  Caller cannot distinguish parse failure "
                "from intentionally empty message."
            )
