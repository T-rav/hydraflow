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
    UNKNOWN_EXPIRY_TTL_SECONDS,
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

    def test_a_blob_with_no_expiry_is_trusted_for_a_bounded_window(self) -> None:
        """Not forever, and not never.

        "Never fresh" was the original rule and it made a bare token unusable:
        never fresh -> refresh -> re-read -> still no expiry -> fail, because
        the re-read was judged by the same predicate that had nothing to judge.
        `.env.sample` offered exactly such a read command.
        """
        token = parse_credential_blob(_blob(), read_at=_NOW)

        assert token.expires_at is None
        assert token.is_fresh(now=_NOW, skew_seconds=0) is True

    def test_a_blob_with_no_expiry_goes_stale_once_the_window_passes(self) -> None:
        """The other half: an unknown expiry must not read as "valid forever".

        A store whose schema moved would otherwise look healthy right up until
        every spawn failed at the upstream.
        """
        token = parse_credential_blob(_blob(), read_at=_NOW)
        later = _NOW + timedelta(seconds=UNKNOWN_EXPIRY_TTL_SECONDS + 1)

        assert token.is_fresh(now=later, skew_seconds=0) is False

    def test_a_stated_expiry_still_wins_over_the_window(self) -> None:
        """Decoy: the window is a fallback, not an override.

        Without this, trusting every token for the window would mask an expiry
        the store actually gave us.
        """
        token = parse_credential_blob(
            _blob(expires_at=(_NOW - timedelta(hours=1)).isoformat()), read_at=_NOW
        )

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


class TestConcurrentSpawnsShareOneResolution:
    """ADR-0148: the gateway resolves this per request, from many threads.

    `access_token` runs under `asyncio.to_thread` on every proxied request, so
    a factory with N concurrent spawns calls it N times at once. Before the
    lock, a cold cache produced N credential-store forks and — far worse — a
    stale credential produced N concurrent refreshes.
    """

    def _hammer(
        self,
        source: SubscriptionCredentialSource,
        workers: int,
    ) -> list[str]:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(lambda _: source.access_token(), range(workers)))

    def test_a_cold_cache_reads_the_store_once(self) -> None:
        import threading
        import time

        reads: list[object] = []
        guard = threading.Lock()

        def _slow_read(command: tuple[str, ...]) -> str:
            with guard:
                reads.append(command)
            time.sleep(0.02)  # a real keychain fork is not instantaneous
            return _blob(
                token="tok", expires_at=(_NOW + timedelta(hours=2)).isoformat()
            )

        source = SubscriptionCredentialSource(
            read_command=("read",), run=_slow_read, now=lambda: _NOW
        )

        tokens = self._hammer(source, 16)

        assert len(reads) == 1, f"{len(reads)} concurrent store reads"
        assert set(tokens) == {"tok"}

    def test_a_stale_credential_refreshes_once(self) -> None:
        """The dangerous one: an OAuth refresh token is normally single-use.

        Replaying one concurrently means the later exchanges are rejected, and
        a provider may read the replay as a compromised grant and revoke it —
        signing the operator out of the tool the credential came from.
        """
        import threading
        import time

        refreshes: list[object] = []
        guard = threading.Lock()
        done = threading.Event()

        stale = _blob(token="old", expires_at=(_NOW - timedelta(hours=1)).isoformat())
        fresh = _blob(token="new", expires_at=(_NOW + timedelta(hours=2)).isoformat())

        def _run(command: tuple[str, ...]) -> str:
            if command == ("refresh",):
                with guard:
                    refreshes.append(command)
                time.sleep(0.02)  # a real OAuth round-trip
                done.set()
                return ""
            return fresh if done.is_set() else stale

        source = SubscriptionCredentialSource(
            read_command=("read",),
            refresh_command=("refresh",),
            run=_run,
            now=lambda: _NOW,
        )

        tokens = self._hammer(source, 16)

        assert len(refreshes) == 1, f"{len(refreshes)} concurrent refreshes"
        assert set(tokens) == {"new"}

    def test_a_warm_cache_does_not_serialise_readers(self) -> None:
        """Decoy: the lock must not put every request behind one mutex.

        A lock taken on the fast path would make the credential a global
        bottleneck for a proxy whose whole job is concurrent streaming.
        """
        source = SubscriptionCredentialSource(
            read_command=("read",),
            run=lambda _c: _blob(
                token="tok", expires_at=(_NOW + timedelta(hours=2)).isoformat()
            ),
            now=lambda: _NOW,
        )
        source.access_token()  # warm it

        assert source._lock.acquire(blocking=False), "fast path held the lock"
        source._lock.release()
        assert source.access_token() == "tok"


class TestTheRealSubprocessPath:
    """`run_credential_command` is the only code that touches a real store.

    Every other test injects `run=`, so the default path — argv, exit codes,
    decoding — had no coverage at all, and `test_it_does_not_print_the_secret
    _to_a_shell` pinned a constant rather than the behaviour: swapping the
    implementation to `shell=True` left the suite green.
    """

    def test_it_returns_the_commands_stdout(self) -> None:
        import sys

        from hydraflow_gateway.subscription_credential import run_credential_command

        out = run_credential_command((sys.executable, "-c", "print('tok-from-argv')"))

        assert out.strip() == "tok-from-argv"

    def test_shell_metacharacters_arrive_literally(self) -> None:
        """The property, not the constant: argv is never handed to a shell.

        Under `shell=True` this argument would be split on the `;` and the
        second half executed — which for a command whose OUTPUT is a live
        credential is how the credential reaches somewhere it should not.
        """
        import sys

        from hydraflow_gateway.subscription_credential import run_credential_command

        out = run_credential_command(
            (sys.executable, "-c", "import sys; print(sys.argv[1])", "a; echo pwned")
        )

        assert out.strip() == "a; echo pwned"

    def test_a_non_zero_exit_becomes_a_credential_error(self) -> None:
        import sys

        from hydraflow_gateway.subscription_credential import run_credential_command

        with pytest.raises(SubscriptionCredentialError, match="exited"):
            run_credential_command((sys.executable, "-c", "raise SystemExit(3)"))

    def test_a_missing_command_becomes_a_credential_error(self) -> None:
        """Not an OSError out of the proxy's credential arm."""
        from hydraflow_gateway.subscription_credential import run_credential_command

        with pytest.raises(SubscriptionCredentialError, match="could not run"):
            run_credential_command(("hydraflow-no-such-binary-exists",))

    def test_undecodable_output_becomes_a_credential_error(self) -> None:
        """A store emitting non-UTF-8 raised UnicodeDecodeError — a ValueError
        the proxy's `except (OSError, SubprocessError)` did not catch."""
        import sys

        from hydraflow_gateway.subscription_credential import run_credential_command

        with pytest.raises(SubscriptionCredentialError):
            run_credential_command(
                (
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'\\xff\\xfe\\x00bad')",
                )
            )
