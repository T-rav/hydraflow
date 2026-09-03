"""The Claude subscription OAuth credential for the gateway's Anthropic upstream.

ADR-0147 made the gateway the path every LLM spawn takes, and the gateway held
one static ``x-api-key`` per upstream — so routing everything through it meant
buying a metered API key. A Claude subscription authenticates with an OAuth
bearer token instead (``Authorization: Bearer`` plus the
``anthropic-beta: oauth-2025-04-20`` header). That token expires, which is why
it cannot be an ``UpstreamSettings`` field: a setting is read once at boot, and
this credential has to be re-read and refreshed while the factory runs.

**The refresh command is operator-supplied, deliberately.** Anthropic's OAuth
token endpoint and client id are vendor internals this repo has not verified.
ADR-0146 already shipped one asserted-but-unchecked vendor capability
("Bugsink files GitHub issues itself" — it does not), and the correction cost a
follow-up ADR. So the mechanism lives here and is tested; the one value that
would have to be guessed is configuration.

**The token never reaches a log.** It is spliced into a request header, so it
is validated for newlines and non-ASCII on the way in — a store that returned
``tok\\r\\nx-evil: 1`` would otherwise be a header-injection primitive — and
every error message here is written to be safe to print.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

#: Where Claude Code keeps its subscription credential on macOS. An argument
#: vector rather than a shell string: no interpolation, and the secret never
#: lands in a shell history or a `ps` line.
DEFAULT_KEYCHAIN_READ_COMMAND: tuple[str, ...] = (
    "security",
    "find-generic-password",
    "-s",
    "Claude Code-credentials",
    "-w",
)

#: The beta header an OAuth bearer token requires. An API key does not carry it,
#: which is why `UpstreamAuthStyle.OAUTH_BEARER` is a separate style rather than
#: a flag on the existing bearer path (z.ai's).
OAUTH_BETA_FLAG = "oauth-2025-04-20"

#: Key spellings seen for the token and its expiry. A list rather than one name
#: because this store's schema belongs to Claude Code, not to this repo, and a
#: rename there should degrade to "not found" rather than to a wrong field.
_ACCESS_TOKEN_KEYS: tuple[str, ...] = ("accessToken", "access_token", "token")
_EXPIRY_KEYS: tuple[str, ...] = (
    "expiresAt",
    "expires_at",
    "expiresAtMs",
    "expiry",
    "expires",
)

#: How long a token with no stated expiry is trusted after it is read. Short,
#: because it is a guess: long enough that a burst of spawns shares one read,
#: short enough that a revoked or rotated token is re-read within minutes.
UNKNOWN_EXPIRY_TTL_SECONDS = 300

#: Epoch values at or above this are milliseconds, not seconds. 1e11 seconds is
#: the year 5138, so no real second-denominated expiry reaches it.
_MILLIS_THRESHOLD = 1e11


class SubscriptionCredentialError(RuntimeError):
    """The subscription credential is missing, malformed, or stale.

    Raised rather than returning a sentinel because gateway selection is
    fail-closed: a spawn that cannot authenticate must stop, not silently
    reach an upstream with no credential.
    """


@dataclass(frozen=True)
class OAuthToken:
    """A bearer token and, when the store said so, when it stops working."""

    access_token: str
    expires_at: datetime | None

    read_at: datetime | None = None
    """When this token came out of the store. Only used when it has no expiry."""

    def is_fresh(self, *, now: datetime, skew_seconds: int) -> bool:
        """Whether this token is usable for a spawn starting *now*.

        A token whose expiry the store did not state is trusted for
        ``UNKNOWN_EXPIRY_TTL_SECONDS`` after it was read, and no longer. Not
        forever: a store whose schema moved would otherwise look healthy right
        up until every spawn failed at the upstream. But not *never* either —
        that was the original rule, and it made a bare token
        (``ant auth print-credentials --access-token``, which this repo's own
        docs offered) impossible to use: never fresh, so refresh, so re-read,
        still no expiry, so fail. The refresh could not help, because the
        re-read was judged by the same predicate that had nothing to judge.
        """
        if self.expires_at is not None:
            return (self.expires_at - now).total_seconds() > skew_seconds
        if self.read_at is None:
            return False
        return (now - self.read_at).total_seconds() < UNKNOWN_EXPIRY_TTL_SECONDS


def _walk(node: object) -> Iterator[Mapping[str, object]]:
    """Every mapping in a decoded blob, outermost first."""
    if isinstance(node, Mapping):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _first(blob: object, keys: tuple[str, ...]) -> object | None:
    for mapping in _walk(blob):
        for key in keys:
            if key in mapping and mapping[key] not in (None, ""):
                return mapping[key]
    return None


def _validate_token(raw: str) -> str:
    """Reject anything that could not safely become a header value."""
    token = raw.strip()
    if not token:
        raise SubscriptionCredentialError(
            "the subscription credential store returned nothing — sign in to "
            "Claude Code, or point the affected *_provider dials back at `claude`"
        )
    if any(char in token for char in "\r\n"):
        raise SubscriptionCredentialError(
            "the subscription credential contains a newline and was refused; a "
            "token is spliced into an Authorization header, so this would be a "
            "header-injection vector"
        )
    if not token.isascii():
        raise SubscriptionCredentialError(
            "the subscription credential contains non-ASCII bytes and was "
            "refused; HTTP header values cannot carry it"
        )
    return token


def _epoch_to_datetime(value: float) -> datetime | None:
    """An epoch in seconds or milliseconds, or ``None`` if it is not a time.

    `expiresAt: 1e20`, a NaN, or an infinity all reach here — `json.loads`
    accepts the latter two by default. Raising would escape the proxy's
    credential arm, so an unusable number is simply an unknown expiry.
    """
    seconds = value / 1000.0 if value >= _MILLIS_THRESHOLD else value
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_expiry(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_datetime(float(value))
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return _parse_expiry(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_credential_blob(raw: str, *, read_at: datetime | None = None) -> OAuthToken:
    """Read a token out of whatever the credential store printed.

    Accepts a JSON document (Claude Code's keychain item, at any nesting) or a
    bare token (``ant auth print-credentials --access-token``). A bare token
    has no expiry, so it is never *fresh* — a source configured that way needs
    a refresh command, which is the honest outcome: nothing told us when it
    dies.
    """
    read_at = datetime.now(UTC) if read_at is None else read_at
    text = raw.strip()
    if not text:
        raise SubscriptionCredentialError(
            "the subscription credential store returned nothing — sign in to "
            "Claude Code, or point the affected *_provider dials back at `claude`"
        )
    try:
        decoded = json.loads(text)
    except ValueError:
        return OAuthToken(
            access_token=_validate_token(text), expires_at=None, read_at=read_at
        )

    if isinstance(decoded, str):
        return OAuthToken(
            access_token=_validate_token(decoded), expires_at=None, read_at=read_at
        )

    found = _first(decoded, _ACCESS_TOKEN_KEYS)
    if not isinstance(found, str):
        raise SubscriptionCredentialError(
            "the subscription credential store held JSON with no recognisable "
            f"access token (looked for {', '.join(_ACCESS_TOKEN_KEYS)})"
        )
    return OAuthToken(
        access_token=_validate_token(found),
        expires_at=_parse_expiry(_first(decoded, _EXPIRY_KEYS)),
        read_at=read_at,
    )


def run_credential_command(command: tuple[str, ...]) -> str:
    """Run *command* as an argument vector and return its stdout.

    Never through a shell, and never string-interpolated: the command comes
    from settings and its OUTPUT is a live credential, so a shell would put
    that credential one redirection away from a log.

    ``check=False``: a missing credential store is a configuration state this
    module reports with a useful message, not a traceback out of subprocess.
    Output is never logged — it is the credential.
    """
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise SubscriptionCredentialError(
            f"could not run the credential command {command[0]!r}: {type(exc).__name__}"
        ) from exc
    if completed.returncode != 0:
        raise SubscriptionCredentialError(
            f"the credential command {command[0]!r} exited {completed.returncode}"
        )
    return completed.stdout


def needs_subscription_credential(upstreams: Iterable[object]) -> bool:
    """Whether any of *upstreams* authenticates with a subscription token."""
    from hydraflow_gateway.settings import UpstreamAuthStyle

    return any(
        getattr(upstream, "auth_style", None) is UpstreamAuthStyle.OAUTH_BEARER
        for upstream in upstreams
    )


def build_subscription_credential(
    upstreams: Iterable[object], environ: Mapping[str, str] | None = None
) -> SubscriptionCredentialSource | None:
    """A credential source when some upstream is on the subscription lane.

    ``None`` otherwise, so an ``api_key`` deployment never reads — or even
    names — a credential store it does not use.

    Takes the upstreams rather than the settings object because an oauth
    upstream can arrive two ways: the env-level pair, or an account declared in
    ``GATEWAY_ACCOUNTS_FILE``. Reading only the first meant the accounts-file
    configuration — the one documented for running a subscription alongside a
    metered key — built no source at all, and every request on that account
    failed at the proxy with a message that did not name the cause.

    Typed loosely to keep this module free of a settings import: ``settings.py``
    already imports ``OAUTH_BETA_FLAG`` from here, and a mutual import cycles.
    """
    from hydraflow_gateway.settings import oauth_command

    if not needs_subscription_credential(upstreams):
        return None
    env = os.environ if environ is None else environ
    return SubscriptionCredentialSource(
        read_command=oauth_command(env, "GATEWAY_ANTHROPIC_OAUTH_READ_COMMAND")
        or DEFAULT_KEYCHAIN_READ_COMMAND,
        refresh_command=oauth_command(env, "GATEWAY_ANTHROPIC_OAUTH_REFRESH_COMMAND"),
    )


class SubscriptionCredentialSource:
    """Serves a fresh subscription bearer token, refreshing when it goes stale.

    Cached between reads: the store is a subprocess, and shelling out once per
    proxied request would put a fork on the hot path of every spawn. The cache
    is keyed on nothing but freshness — there is one credential.
    """

    def __init__(
        self,
        *,
        read_command: tuple[str, ...] = DEFAULT_KEYCHAIN_READ_COMMAND,
        refresh_command: tuple[str, ...] | None = None,
        run: Callable[[tuple[str, ...]], str] = run_credential_command,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        skew_seconds: int = 120,
    ) -> None:
        self._read_command = read_command
        self._refresh_command = refresh_command
        self._run = run
        self._now = now
        self._skew_seconds = skew_seconds
        self._cached: OAuthToken | None = None
        self._lock = threading.Lock()
        """Serialises the slow path. See :meth:`access_token`."""

    def _read(self) -> OAuthToken:
        return parse_credential_blob(self._run(self._read_command), read_at=self._now())

    def access_token(self) -> str:
        """A token good for a spawn starting now, or an error naming the fix.

        Blocking (it may fork), so callers on the async path must hand this to
        a thread rather than await it inline.

        Double-checked: the fresh-cache path is lock-free, and everything that
        forks a process is serialised. Without the lock, N concurrent spawns on
        a cold or expired cache each ran the read AND the refresh — measured at
        32 store reads for 32 spawns, and 24 refresh commands for 24. The reads
        are merely wasteful; the refreshes are not. An OAuth refresh token is
        normally single-use and rotates, so replaying one 24 times concurrently
        means 23 rejected exchanges at best, and a provider treating the replay
        as a compromised grant at worst — which would sign the operator out of
        the very tool the credential came from.

        The unlocked read of ``self._cached`` is safe because the attribute is
        rebound, never mutated, and ``OAuthToken`` is frozen: a racing reader
        sees either the old token or the new one, never a half-built one.
        """
        now = self._now()
        cached = self._cached
        if cached is not None and cached.is_fresh(
            now=now, skew_seconds=self._skew_seconds
        ):
            return cached.access_token

        with self._lock:
            return self._resolve_locked()

    def _resolve_locked(self) -> str:
        """Read, refresh once, or fail closed. Callers hold ``self._lock``."""
        now = self._now()
        # Re-check under the lock: while this thread waited, the holder may
        # already have refreshed, and refreshing again would be the replay
        # the lock exists to prevent.
        cached = self._cached
        if cached is not None and cached.is_fresh(
            now=now, skew_seconds=self._skew_seconds
        ):
            return cached.access_token

        token = self._read()
        if token.is_fresh(now=now, skew_seconds=self._skew_seconds):
            self._cached = token
            return token.access_token

        if self._refresh_command is None:
            self._cached = None
            raise SubscriptionCredentialError(
                "the Claude subscription credential is expired or has no known "
                "expiry, and no refresh command is configured. Set "
                "GATEWAY_ANTHROPIC_OAUTH_REFRESH_COMMAND to something that "
                "renews it, or point the affected *_provider dials back at "
                "`claude`"
            )

        # One attempt, never a loop: if the command ran and the store is still
        # stale, retrying only forks again against the same answer.
        self._run(self._refresh_command)
        refreshed = self._read()
        if refreshed.is_fresh(now=self._now(), skew_seconds=self._skew_seconds):
            self._cached = refreshed
            return refreshed.access_token

        self._cached = None
        raise SubscriptionCredentialError(
            "the refresh command ran and the Claude subscription credential is "
            "still expired or has no known expiry; the gateway is failing "
            "closed rather than sending a dead token upstream"
        )
