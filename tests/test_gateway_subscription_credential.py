"""The Claude subscription OAuth credential for the gateway (ADR-0148).

ADR-0147 routes every role through the gateway, and the gateway swapped in one
static `x-api-key` — which meant routing everything through it required a
metered API key. A subscription credential is an OAuth bearer token that
expires, so it cannot be a static setting: it is read from a credential store
on demand, refreshed when stale, and never logged.

The refresh MECHANISM is here and tested. The refresh COMMAND is operator
supplied on purpose: Anthropic's OAuth token endpoint and client id are vendor
internals this repo has not verified, and inventing them is the failure mode
ADR-0146 already shipped once (a capability asserted, not checked).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from hydraflow_gateway.subscription_credential import (
    DEFAULT_KEYCHAIN_READ_COMMAND,
    SubscriptionCredentialError,
    SubscriptionCredentialSource,
    parse_credential_blob,
)

_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _blob(*, token: str = "tok-abc", expires_at: object = None, **extra: object) -> str:
    payload: dict[str, object] = {"accessToken": token}
    if expires_at is not None:
        payload["expiresAt"] = expires_at
    payload.update(extra)
    return json.dumps(payload)


class TestReadingTheCredentialBlob:
    """The store's exact schema is not this repo's to pin, so parse defensively."""

    def test_a_json_blob_yields_its_access_token(self) -> None:
        token = parse_credential_blob(_blob(token="tok-1"))

        assert token.access_token == "tok-1"

    def test_a_nested_blob_is_searched(self) -> None:
        """Claude Code has stored the token under a wrapper key before now."""
        raw = json.dumps({"claudeAiOauth": {"accessToken": "tok-nested"}})

        assert parse_credential_blob(raw).access_token == "tok-nested"

    @pytest.mark.parametrize(
        "key",
        [
            pytest.param("accessToken", id="camel"),
            pytest.param("access_token", id="snake"),
        ],
    )
    def test_either_spelling_of_the_token_key_is_accepted(self, key: str) -> None:
        assert parse_credential_blob(json.dumps({key: "tok-x"})).access_token == "tok-x"

    def test_a_bare_token_is_accepted(self) -> None:
        """`ant auth print-credentials --access-token` prints a bare token."""
        assert parse_credential_blob("  tok-bare\n").access_token == "tok-bare"

    def test_epoch_millis_expiry_is_understood(self) -> None:
        expiry = _NOW + timedelta(hours=1)
        raw = _blob(expires_at=int(expiry.timestamp() * 1000))

        assert parse_credential_blob(raw).expires_at == expiry

    def test_epoch_seconds_expiry_is_understood(self) -> None:
        expiry = _NOW + timedelta(hours=1)
        raw = _blob(expires_at=int(expiry.timestamp()))

        assert parse_credential_blob(raw).expires_at == expiry

    def test_an_iso_expiry_is_understood(self) -> None:
        expiry = _NOW + timedelta(hours=1)

        assert (
            parse_credential_blob(_blob(expires_at=expiry.isoformat())).expires_at
            == expiry
        )

    def test_a_blob_with_no_expiry_is_treated_as_unknown_not_fresh(self) -> None:
        """Unknown expiry must not read as "valid forever"."""
        token = parse_credential_blob(_blob())

        assert token.expires_at is None
        assert token.is_fresh(now=_NOW, skew_seconds=0) is False

    def test_an_empty_store_is_an_error_not_an_empty_token(self) -> None:
        with pytest.raises(SubscriptionCredentialError):
            parse_credential_blob("   ")


class TestTheTokenIsNeverAHeaderInjection:
    """The token is spliced into an `Authorization` header on every request."""

    @pytest.mark.parametrize(
        "hostile",
        [
            pytest.param("tok\r\nx-evil: 1", id="crlf"),
            pytest.param("tok\nx-evil: 1", id="lf"),
            pytest.param("tok\rx", id="cr"),
        ],
    )
    def test_a_token_carrying_a_newline_is_refused(self, hostile: str) -> None:
        with pytest.raises(SubscriptionCredentialError):
            parse_credential_blob(json.dumps({"accessToken": hostile}))

    def test_a_non_ascii_token_is_refused(self) -> None:
        """Header values are latin-1 at best; a smuggled unicode token is a bug."""
        with pytest.raises(SubscriptionCredentialError):
            parse_credential_blob(json.dumps({"accessToken": "tok-é"}))


class TestFreshness:
    def test_a_token_expiring_beyond_the_skew_is_fresh(self) -> None:
        token = parse_credential_blob(
            _blob(expires_at=(_NOW + timedelta(minutes=10)).isoformat())
        )

        assert token.is_fresh(now=_NOW, skew_seconds=120) is True

    def test_a_token_inside_the_skew_is_not_fresh(self) -> None:
        """Renew before expiry, not after: a spawn can outlive the token."""
        token = parse_credential_blob(
            _blob(expires_at=(_NOW + timedelta(seconds=30)).isoformat())
        )

        assert token.is_fresh(now=_NOW, skew_seconds=120) is False

    def test_an_expired_token_is_not_fresh(self) -> None:
        token = parse_credential_blob(
            _blob(expires_at=(_NOW - timedelta(minutes=1)).isoformat())
        )

        assert token.is_fresh(now=_NOW, skew_seconds=0) is False


class TestTheSource:
    """ADR-0148: read, cache, refresh, fail closed."""

    def _source(
        self,
        reads: list[str],
        *,
        refresh_command: tuple[str, ...] | None = None,
        now: datetime = _NOW,
    ) -> tuple[SubscriptionCredentialSource, list[tuple[str, ...]]]:
        calls: list[tuple[str, ...]] = []
        pending = list(reads)

        def _run(command: tuple[str, ...]) -> str:
            calls.append(command)
            if command == refresh_command:
                return ""
            return pending.pop(0) if pending else ""

        source = SubscriptionCredentialSource(
            read_command=("read-me",),
            refresh_command=refresh_command,
            run=_run,
            now=lambda: now,
            skew_seconds=120,
        )
        return source, calls

    def test_a_fresh_token_is_returned(self) -> None:
        fresh = _blob(
            token="tok-fresh", expires_at=(_NOW + timedelta(hours=1)).isoformat()
        )
        source, _ = self._source([fresh])

        assert source.access_token() == "tok-fresh"

    def test_a_fresh_token_is_cached_rather_than_re_read(self) -> None:
        """One subprocess per token lifetime, not one per proxied request."""
        fresh = _blob(
            token="tok-fresh", expires_at=(_NOW + timedelta(hours=1)).isoformat()
        )
        source, calls = self._source([fresh])

        for _ in range(5):
            source.access_token()

        assert calls == [("read-me",)]

    def test_a_stale_token_triggers_the_refresh_command_then_re_reads(self) -> None:
        stale = _blob(
            token="tok-old", expires_at=(_NOW - timedelta(minutes=5)).isoformat()
        )
        fresh = _blob(
            token="tok-new", expires_at=(_NOW + timedelta(hours=1)).isoformat()
        )
        source, calls = self._source([stale, fresh], refresh_command=("refresh-me",))

        assert source.access_token() == "tok-new"
        assert calls == [("read-me",), ("refresh-me",), ("read-me",)]

    def test_a_stale_token_with_no_refresh_command_fails_closed(self) -> None:
        """Fail closed with a named remedy, never serve an expired token."""
        stale = _blob(
            token="tok-old", expires_at=(_NOW - timedelta(minutes=5)).isoformat()
        )
        source, _ = self._source([stale])

        with pytest.raises(SubscriptionCredentialError) as caught:
            source.access_token()

        assert "GATEWAY_ANTHROPIC_OAUTH_REFRESH_COMMAND" in str(caught.value)

    def test_a_refresh_that_does_not_refresh_fails_closed(self) -> None:
        """The command ran and the store is still stale — say so, don't loop."""
        stale = _blob(
            token="tok-old", expires_at=(_NOW - timedelta(minutes=5)).isoformat()
        )
        source, calls = self._source([stale, stale], refresh_command=("refresh-me",))

        with pytest.raises(SubscriptionCredentialError):
            source.access_token()

        assert calls.count(("refresh-me",)) == 1, "must not retry the refresh in a loop"

    def test_the_error_never_carries_the_token(self) -> None:
        """An error string reaches logs; the credential must not ride along."""
        stale = _blob(
            token="sk-secret-value", expires_at=(_NOW - timedelta(days=1)).isoformat()
        )
        source, _ = self._source([stale])

        with pytest.raises(SubscriptionCredentialError) as caught:
            source.access_token()

        assert "sk-secret-value" not in str(caught.value)


class TestTheDefaultReadCommand:
    def test_it_reads_the_claude_code_credential_store(self) -> None:
        """Named so a reader can see WHICH store without running anything."""
        assert DEFAULT_KEYCHAIN_READ_COMMAND[0] == "security"
        assert "Claude Code-credentials" in DEFAULT_KEYCHAIN_READ_COMMAND

    def test_it_does_not_print_the_secret_to_a_shell(self) -> None:
        """Argument vector, never a shell string: no interpolation, no history."""
        assert all(isinstance(part, str) for part in DEFAULT_KEYCHAIN_READ_COMMAND)
        assert not any(
            ";" in part or "|" in part for part in DEFAULT_KEYCHAIN_READ_COMMAND
        )
