"""The subscription lane, end to end through the gateway (ADR-0148).

ADR-0147 routed every role through the gateway, and the gateway only knew how
to present a static `x-api-key` — so "everything through one ledger" required
buying a metered API key. This lane lets the same gateway present a Claude
subscription's OAuth bearer token instead, so both credential kinds funnel
through one proxy and land in one ledger.

The end-to-end tests here assert on the headers the UPSTREAM actually received,
not on the function that builds them. A unit test of `replace_request_headers`
cannot see the proxy forgetting to resolve a token, which is the wiring that
breaks.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import (
    MintKeyRequest,
    ProviderBinding,
    RepoClass,
)
from hydraflow_gateway.proxy import replace_request_headers
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from hydraflow_gateway.subscription_credential import (
    OAUTH_BETA_FLAG,
    SubscriptionCredentialSource,
    build_subscription_credential,
)

_CONTROL_TOKEN = "c" * 40
_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


class _ChunkStream(httpx.AsyncByteStream):
    """A response body the proxy can stream once, as a real upstream would."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


def _ok() -> httpx.Response:
    return httpx.Response(200, stream=_ChunkStream([b'{"ok":true}']))


def _fresh_blob(token: str = "sub-token") -> str:
    return json.dumps(
        {
            "accessToken": token,
            "expiresAt": (_NOW + timedelta(hours=2)).isoformat(),
        }
    )


def _credential(token: str = "sub-token") -> SubscriptionCredentialSource:
    return SubscriptionCredentialSource(
        read_command=("read",),
        run=lambda _command: _fresh_blob(token),
        now=lambda: _NOW,
    )


def _subscription_settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://upstream.test",
                api_key=None,
                auth_style=UpstreamAuthStyle.OAUTH_BEARER,
            ),
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )


def _anthropic_upstream(style: UpstreamAuthStyle) -> UpstreamSettings:
    return UpstreamSettings(
        base_url="https://upstream.test",
        api_key=None if style is UpstreamAuthStyle.OAUTH_BEARER else SecretStr("k"),
        auth_style=style,
    )


class TestSettingsRefuseAnAmbiguousCredential:
    """ADR-0148: two credentials configured and one in use is the worst state."""

    def test_an_oauth_upstream_needs_no_static_key(self) -> None:
        upstream = _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER)

        assert upstream.api_key is None

    def test_an_oauth_upstream_carrying_a_static_key_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="static api_key"):
            UpstreamSettings(
                base_url="https://upstream.test",
                api_key=SecretStr("sk-oops"),
                auth_style=UpstreamAuthStyle.OAUTH_BEARER,
            )

    @pytest.mark.parametrize(
        "style",
        [
            pytest.param(UpstreamAuthStyle.X_API_KEY, id="x-api-key"),
            pytest.param(UpstreamAuthStyle.BEARER, id="bearer"),
        ],
    )
    def test_a_static_lane_without_a_key_is_refused(
        self, style: UpstreamAuthStyle
    ) -> None:
        """Decoy: making `api_key` optional must not open a false-ready tap."""
        with pytest.raises(ValidationError, match="requires an api_key"):
            UpstreamSettings(
                base_url="https://upstream.test", api_key=None, auth_style=style
            )

    def test_the_env_contract_selects_the_lane(self) -> None:
        settings = GatewaySettings.from_env(
            {
                "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                "GATEWAY_ANTHROPIC_BASE_URL": "https://upstream.test",
                "GATEWAY_ANTHROPIC_AUTH_MODE": "subscription",
            }
        )
        upstream = settings.upstreams[ProviderBinding.ANTHROPIC]

        assert upstream.auth_style is UpstreamAuthStyle.OAUTH_BEARER
        assert upstream.api_key is None

    def test_the_default_lane_is_unchanged_by_this_feature(self) -> None:
        """Decoy: an existing deployment must not move onto the new lane."""
        settings = GatewaySettings.from_env(
            {
                "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                "GATEWAY_ANTHROPIC_BASE_URL": "https://upstream.test",
                "GATEWAY_ANTHROPIC_API_KEY": "sk-static",
            }
        )

        assert (
            settings.upstreams[ProviderBinding.ANTHROPIC].auth_style
            is UpstreamAuthStyle.X_API_KEY
        )

    def test_both_credentials_configured_at_once_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unset one"):
            GatewaySettings.from_env(
                {
                    "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                    "GATEWAY_ANTHROPIC_BASE_URL": "https://upstream.test",
                    "GATEWAY_ANTHROPIC_API_KEY": "sk-static",
                    "GATEWAY_ANTHROPIC_AUTH_MODE": "subscription",
                }
            )

    def test_an_unknown_mode_is_named_at_boot(self) -> None:
        with pytest.raises(ValueError, match="GATEWAY_ANTHROPIC_AUTH_MODE"):
            GatewaySettings.from_env(
                {
                    "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                    "GATEWAY_ANTHROPIC_BASE_URL": "https://upstream.test",
                    "GATEWAY_ANTHROPIC_AUTH_MODE": "subscribtion",
                }
            )

    def test_the_subscription_lane_still_needs_a_destination(self) -> None:
        with pytest.raises(ValueError, match="GATEWAY_ANTHROPIC_BASE_URL"):
            GatewaySettings.from_env(
                {
                    "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                    "GATEWAY_ANTHROPIC_AUTH_MODE": "subscription",
                }
            )


class TestTheCredentialSourceIsBuiltOnlyWhenNeeded:
    def test_an_api_key_deployment_builds_none(self, tmp_path: Path) -> None:
        """It must not touch a credential store it does not use."""
        upstreams = [_anthropic_upstream(UpstreamAuthStyle.X_API_KEY)]

        assert build_subscription_credential(upstreams, {}) is None

    def test_a_subscription_upstream_builds_one(self, tmp_path: Path) -> None:
        upstreams = [_anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER)]

        assert isinstance(
            build_subscription_credential(upstreams, {}), SubscriptionCredentialSource
        )

    def test_an_oauth_account_alone_builds_one(self, tmp_path: Path) -> None:
        """The helper's half of the accounts-file shape."""
        env_level = _anthropic_upstream(UpstreamAuthStyle.X_API_KEY)
        from_accounts_file = _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER)

        assert isinstance(
            build_subscription_credential([env_level, from_accounts_file], {}),
            SubscriptionCredentialSource,
        )

    def test_create_app_wires_a_source_for_an_accounts_file_subscription(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The WIRING, which is where this actually broke.

        `create_app` asked `build_subscription_credential` about the env-level
        settings only. Declaring the subscription as an account — the shape the
        README recommends for running it beside a metered key — produced no
        source, the mint succeeded, and every proxied request on that account
        then failed with a message that did not name the cause.

        Asserting through `app.state.gateway_proxy` rather than by calling the
        helper: a test of the helper stays green when the call site stops
        passing it the pool, which is exactly the mutation that reintroduces
        this bug.
        """
        monkeypatch.setenv("GATEWAY_ACCOUNT_METERED_KEY", "sk-metered")
        accounts = tmp_path / "accounts.yml"
        accounts.write_text(
            """
schema_version: 1
accounts:
  - id: claude-subscription
    provider_binding: anthropic
    base_url: https://upstream.test
    auth_style: oauth-bearer
    billing_kind: flat_rate
""",
            encoding="utf-8",
        )
        # Env level is a plain API key: only the ACCOUNT wants a subscription.
        settings = GatewaySettings(
            control_token=SecretStr(_CONTROL_TOKEN),
            upstreams={
                ProviderBinding.ANTHROPIC: _anthropic_upstream(
                    UpstreamAuthStyle.X_API_KEY
                )
            },
            ledger_path=tmp_path / "l.jsonl",
            body_dir=tmp_path / "b",
            accounts_file=accounts,
        )

        app = create_app(
            settings,
            key_store=VirtualKeyStore(max_ttl_seconds=600),
            client=httpx.AsyncClient(),
            ledger=GatewayLedger(tmp_path / "l.jsonl"),
            body_store=GatewayBodyStore(tmp_path / "b"),
        )

        assert app.state.gateway_proxy._subscription_credential is not None


class TestABootWithNoCredentialSourceIsRefused:
    """A gateway that starts, mints, then fails every request is a false-ready tap."""

    def test_an_oauth_upstream_with_no_source_refuses_to_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hydraflow_gateway.app as gateway_app

        # Simulate the builder failing to produce one for an oauth upstream.
        monkeypatch.setattr(
            gateway_app, "build_subscription_credential", lambda *a, **k: None
        )

        with pytest.raises(ValueError, match="no credential source"):
            create_app(
                _subscription_settings(tmp_path),
                key_store=VirtualKeyStore(max_ttl_seconds=600),
                client=httpx.AsyncClient(),
                ledger=GatewayLedger(tmp_path / "l.jsonl"),
                body_store=GatewayBodyStore(tmp_path / "b"),
            )

    def test_an_api_key_deployment_still_boots(self, tmp_path: Path) -> None:
        """Decoy: the guard must not fire on the ordinary deployment."""
        settings = GatewaySettings(
            control_token=SecretStr(_CONTROL_TOKEN),
            upstreams={
                ProviderBinding.ANTHROPIC: _anthropic_upstream(
                    UpstreamAuthStyle.X_API_KEY
                )
            },
            ledger_path=tmp_path / "l.jsonl",
            body_dir=tmp_path / "b",
        )

        assert (
            create_app(
                settings,
                key_store=VirtualKeyStore(max_ttl_seconds=600),
                client=httpx.AsyncClient(),
                ledger=GatewayLedger(tmp_path / "l.jsonl"),
                body_store=GatewayBodyStore(tmp_path / "b"),
            )
            is not None
        )


class TestTheOAuthHeadersAreBuilt:
    """ADR-0148: bearer plus the beta flag, never at the cost of the client's betas."""

    def test_the_token_rides_on_authorization(self) -> None:
        headers = replace_request_headers(
            [(b"content-type", b"application/json")],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="sub-token",
        )

        assert (b"authorization", b"Bearer sub-token") in headers

    def test_the_oauth_beta_flag_is_added(self) -> None:
        headers = replace_request_headers(
            [], _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER), access_token="t"
        )

        assert (b"anthropic-beta", OAUTH_BETA_FLAG.encode()) in headers

    def test_a_clients_own_betas_survive(self) -> None:
        """The Claude CLI sends its own betas; replacing them disables features."""
        headers = replace_request_headers(
            [(b"anthropic-beta", b"compact-2026-01-12, fast-mode-2026-02-01")],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="t",
        )
        betas = [value for name, value in headers if name == b"anthropic-beta"]

        assert len(betas) == 1, "one merged header, not two competing ones"
        assert b"compact-2026-01-12" in betas[0]
        assert b"fast-mode-2026-02-01" in betas[0]
        assert OAUTH_BETA_FLAG.encode() in betas[0]

    def test_the_flag_is_not_duplicated_when_the_client_sent_it(self) -> None:
        headers = replace_request_headers(
            [(b"anthropic-beta", OAUTH_BETA_FLAG.encode())],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="t",
        )
        betas = [value for name, value in headers if name == b"anthropic-beta"]

        assert betas == [OAUTH_BETA_FLAG.encode()]

    def test_the_clients_own_credential_is_still_stripped(self) -> None:
        """The worker's virtual key must never reach the real upstream."""
        headers = replace_request_headers(
            [(b"authorization", b"Bearer virtual-secret"), (b"x-api-key", b"virtual")],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="sub-token",
        )

        assert (b"x-api-key", b"virtual") not in headers
        assert (b"authorization", b"Bearer virtual-secret") not in headers

    def test_a_static_lane_gains_no_beta_flag(self) -> None:
        """Decoy: an API key does not carry the OAuth beta."""
        headers = replace_request_headers(
            [], _anthropic_upstream(UpstreamAuthStyle.X_API_KEY)
        )

        assert not any(name == b"anthropic-beta" for name, _ in headers)

    def test_reaching_the_oauth_lane_with_no_token_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="no resolved"):
            replace_request_headers(
                [], _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER)
            )


def _mint(store: VirtualKeyStore) -> str:
    return store.mint(
        MintKeyRequest(
            principal_kind="loop",
            principal_id="implementer",
            spawn_id="spawn-1",
            session_id="session-1",
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=False,
            ttl_seconds=300,
        )
    ).token


def _client(
    tmp_path: Path,
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    *,
    credential: SubscriptionCredentialSource | None = None,
) -> tuple[httpx.AsyncClient, str, GatewayLedger]:
    settings = _subscription_settings(tmp_path)
    store = VirtualKeyStore(
        max_ttl_seconds=600,
        id_factory=lambda: "key-1",
        secret_factory=lambda: "virtual-secret",
    )
    token = _mint(store)
    ledger = GatewayLedger(settings.ledger_path)
    app = create_app(
        settings,
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ledger=ledger,
        body_store=GatewayBodyStore(settings.body_dir),
        subscription_credential=credential if credential is not None else _credential(),
    )
    return (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
        ),
        token,
        ledger,
    )


@pytest.mark.asyncio
class TestAProxiedRequestOnTheSubscriptionLane:
    """ADR-0148, from the outside: what the upstream actually received."""

    async def test_the_upstream_gets_the_subscription_token(
        self, tmp_path: Path
    ) -> None:
        seen: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            await request.aread()
            seen.update(dict(request.headers))
            return _ok()

        client, token, _ = _client(tmp_path, handler)
        async with client:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token, "anthropic-beta": "compact-2026-01-12"},
                json={"model": "claude-opus-5"},
            )

        assert response.status_code == 200
        assert seen["authorization"] == "Bearer sub-token"
        assert "x-api-key" not in seen, "the virtual key must not be forwarded"
        assert OAUTH_BETA_FLAG in seen["anthropic-beta"]
        assert "compact-2026-01-12" in seen["anthropic-beta"]

    async def test_the_ledger_row_names_the_subscription_lane(
        self, tmp_path: Path
    ) -> None:
        """Otherwise flat-rate traffic is summed as dollars owed.

        `AccountBillingKind` already existed with exactly this meaning and no
        consumer; this is its first reader (ADR-0053: use the term, do not
        coin a synonym).
        """

        async def handler(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return _ok()

        client, token, ledger = _client(tmp_path, handler)
        async with client:
            await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                json={"model": "claude-opus-5"},
            )

        rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
        assert [row["billing_kind"] for row in rows] == ["flat_rate"]

    async def test_a_stale_credential_refuses_the_request(self, tmp_path: Path) -> None:
        """Fail closed: never send a dead token upstream and bill the retry."""
        reached = False

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal reached
            await request.aread()
            reached = True
            return _ok()

        expired = SubscriptionCredentialSource(
            read_command=("read",),
            run=lambda _c: json.dumps(
                {
                    "accessToken": "dead",
                    "expiresAt": (_NOW - timedelta(hours=1)).isoformat(),
                }
            ),
            now=lambda: _NOW,
        )
        client, token, _ = _client(tmp_path, handler, credential=expired)
        async with client:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                json={"model": "claude-opus-5"},
            )

        assert response.status_code >= 500
        assert reached is False, "a dead token must not reach the upstream"


class TestAllThreeCredentialsCanShareOnePool:
    """Sub, metered key and z.ai as accounts, so fallback can hop between them.

    ADR-0148. The env-level `GATEWAY_ANTHROPIC_AUTH_MODE` picks ONE credential,
    because both would occupy the same `ProviderBinding.ANTHROPIC` slot. Bounded
    fallback (ADR-0142) needs them present at once, which means declaring them
    as accounts — and `load_account_pool` built every account with a static
    secret from `credential_env`, so a subscription account could not exist at
    all until the oauth-bearer branch was added.
    """

    def _pool(self, tmp_path: Path):
        from hydraflow_gateway.routing_accounts import load_account_pool

        accounts = tmp_path / "accounts.yml"
        accounts.write_text(
            """
schema_version: 1
accounts:
  - id: claude-subscription
    provider_binding: anthropic
    base_url: https://upstream.test
    auth_style: oauth-bearer
    credential_kind: oauth-subscription
    billing_kind: flat_rate
  - id: claude-metered
    provider_binding: anthropic
    base_url: https://upstream.test
    auth_style: x-api-key
    credential_env: GATEWAY_ACCOUNT_CLAUDE_METERED_KEY
  - id: zai-metered
    provider_binding: zai-harness
    base_url: https://zai.test
    auth_style: bearer
    credential_env: GATEWAY_ACCOUNT_ZAI_KEY
""",
            encoding="utf-8",
        )
        settings = _subscription_settings(tmp_path).model_copy(
            update={"accounts_file": accounts}
        )
        return load_account_pool(
            settings,
            environ={
                "GATEWAY_ACCOUNT_CLAUDE_METERED_KEY": "sk-metered",
                "GATEWAY_ACCOUNT_ZAI_KEY": "zai-key",
            },
        )

    def test_the_subscription_account_needs_no_environment_secret(
        self, tmp_path: Path
    ) -> None:
        """It resolves per request, so there is no secret to read at boot."""
        upstream = self._pool(tmp_path).upstream("claude-subscription")

        assert upstream is not None
        assert upstream.api_key is None
        assert upstream.auth_style is UpstreamAuthStyle.OAUTH_BEARER

    def test_the_metered_accounts_still_read_their_secrets(
        self, tmp_path: Path
    ) -> None:
        """Decoy: the oauth branch must not swallow the static-key path."""
        pool = self._pool(tmp_path)

        metered = pool.upstream("claude-metered")
        zai = pool.upstream("zai-metered")
        assert metered is not None and metered.api_key is not None
        assert zai is not None and zai.api_key is not None

    def test_all_three_are_reachable_at_once(self, tmp_path: Path) -> None:
        """The precondition for hopping off the subscription onto a key."""
        pool = self._pool(tmp_path)

        assert {
            account_id
            for account_id in ("claude-subscription", "claude-metered", "zai-metered")
            if pool.upstream(account_id) is not None
        } == {"claude-subscription", "claude-metered", "zai-metered"}

    def test_the_subscription_account_declares_flat_rate_billing(
        self, tmp_path: Path
    ) -> None:
        """`AccountBillingKind` is what keeps its rows out of a dollar total."""
        from hydraflow_gateway.models import AccountBillingKind

        account = self._pool(tmp_path).account("claude-subscription")

        assert account is not None
        assert account.billing_kind is AccountBillingKind.FLAT_RATE

    def test_a_metered_account_defaults_to_metered_billing(
        self, tmp_path: Path
    ) -> None:
        from hydraflow_gateway.models import AccountBillingKind

        account = self._pool(tmp_path).account("claude-metered")

        assert account is not None
        assert account.billing_kind is AccountBillingKind.METERED

    def test_both_anthropic_accounts_are_fallback_candidates(
        self, tmp_path: Path
    ) -> None:
        """Membership, which is the precondition for a hop.

        Not ordering — `candidates_for_model` also returns the compiled legacy
        account, so asserting a two-element sequence here would pin the wrong
        thing. What matters is that a subscription account and a metered one
        are BOTH eligible on the same lane; ADR-0142 owns the order.
        """
        candidates = self._pool(tmp_path).candidates_for_model("claude-opus-5")

        assert "claude-subscription" in candidates
        assert "claude-metered" in candidates

    def test_the_zai_account_is_not_a_candidate_for_a_claude_model(
        self, tmp_path: Path
    ) -> None:
        """Fallback never crosses providers, whatever the accounts file says.

        `candidates_for_model` filters by `binding_for_model`, so "sub, then a
        key, then z.ai" is not a thing the gateway can do — moving to z.ai is a
        spawn-side model change (ADR-0119). The ADR claimed otherwise until
        this test was written.
        """
        candidates = self._pool(tmp_path).candidates_for_model("claude-opus-5")

        assert "zai-metered" not in candidates


class TestHeaderMergingSurvivesRealClientShapes:
    """ADR-0148: what an HTTP client is actually allowed to send.

    The merge keys on a lowercase name and emits one joined header, so every
    shape a client may legitimately use has to land in the same place.
    """

    def test_a_capitalised_header_name_is_still_merged(self) -> None:
        """HTTP header names are case-insensitive; the CLI may send any casing."""
        headers = replace_request_headers(
            [(b"Anthropic-Beta", b"compact-2026-01-12")],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="t",
        )
        betas = [v for n, v in headers if n.lower() == b"anthropic-beta"]

        assert len(betas) == 1, "a capitalised header was left beside the merged one"
        assert b"compact-2026-01-12" in betas[0]
        assert OAUTH_BETA_FLAG.encode() in betas[0]

    def test_repeated_beta_headers_collapse_into_one(self) -> None:
        """HTTP permits a repeated field; both values must survive the merge."""
        headers = replace_request_headers(
            [
                (b"anthropic-beta", b"compact-2026-01-12"),
                (b"anthropic-beta", b"fast-mode-2026-02-01"),
            ],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="t",
        )
        betas = [v for n, v in headers if n.lower() == b"anthropic-beta"]

        assert len(betas) == 1
        assert b"compact-2026-01-12" in betas[0]
        assert b"fast-mode-2026-02-01" in betas[0]

    def test_an_empty_beta_header_does_not_produce_a_stray_comma(self) -> None:
        """A leading comma is a malformed field value, not a harmless one."""
        headers = replace_request_headers(
            [(b"anthropic-beta", b"")],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="t",
        )
        betas = [v for n, v in headers if n.lower() == b"anthropic-beta"]

        assert betas == [OAUTH_BETA_FLAG.encode()]

    def test_whitespace_around_client_betas_is_normalised(self) -> None:
        headers = replace_request_headers(
            [(b"anthropic-beta", b"  compact-2026-01-12 ,  ")],
            _anthropic_upstream(UpstreamAuthStyle.OAUTH_BEARER),
            access_token="t",
        )
        betas = [v for n, v in headers if n.lower() == b"anthropic-beta"]

        assert betas == [b"compact-2026-01-12, " + OAUTH_BETA_FLAG.encode()]


@pytest.mark.asyncio
class TestTheCredentialFailurePath:
    """A refusal is still an observation, and still says which lane it was."""

    async def test_a_credential_failure_still_writes_a_ledger_row(
        self, tmp_path: Path
    ) -> None:
        """Otherwise a stopped factory leaves no trace of WHY it stopped."""

        async def handler(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return _ok()

        expired = SubscriptionCredentialSource(
            read_command=("read",),
            run=lambda _c: json.dumps(
                {
                    "accessToken": "dead",
                    "expiresAt": (_NOW - timedelta(hours=1)).isoformat(),
                }
            ),
            now=lambda: _NOW,
        )
        client, token, ledger = _client(tmp_path, handler, credential=expired)
        async with client:
            await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                json={"model": "claude-opus-5"},
            )

        rows = [
            json.loads(line)
            for line in ledger.path.read_text().splitlines()
            if line.strip()
        ]
        assert rows, "a refused request left no observation"
        assert rows[0]["billing_kind"] == "flat_rate"
        assert rows[0]["status_code"] == 503
        # The marker is load-bearing, not decoration: without it a credential
        # failure reads as UNAVAILABLE evidence against the ACCOUNT, tripping
        # its circuit and licensing a fallback hop that the gateway's own
        # credential store manufactured.
        assert rows[0]["refusal_reason"] == "gateway-upstream-credential-unavailable"

    async def test_an_unexpected_credential_error_is_still_contained(
        self, tmp_path: Path
    ) -> None:
        """Not every failure here is a SubscriptionCredentialError.

        The credential path forks a process and parses a third-party document,
        so it can also surface a decode error or a malformed expiry. Catching
        only the expected type returns a 500 with a traceback, writes NO ledger
        row, and leaks the request slot plus a phantom active route — strictly
        worse than the 503 this contract promises.
        """

        async def handler(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return _ok()

        class _Exploding:
            def access_token(self) -> str:
                raise RuntimeError("something the credential path did not expect")

        client, token, ledger = _client(
            tmp_path,
            handler,
            credential=_Exploding(),  # type: ignore[arg-type]
        )
        async with client:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                json={"model": "claude-opus-5"},
            )

        assert response.status_code == 503, "an unexpected error escaped as a 500"
        rows = [
            json.loads(line)
            for line in ledger.path.read_text().splitlines()
            if line.strip()
        ]
        assert rows, "the attempt was never finalized, so the slot leaked"
        assert rows[0]["refusal_reason"] == "gateway-upstream-credential-unavailable"
        # The raw message may name internals; it must not reach the client.
        assert "something the credential path did not expect" not in response.text

    async def test_the_refusal_never_carries_the_credential(
        self, tmp_path: Path
    ) -> None:
        """The 503 detail reaches a client and a log; a token must not ride it."""

        async def handler(request: httpx.Request) -> httpx.Response:
            await request.aread()
            return _ok()

        expired = SubscriptionCredentialSource(
            read_command=("read",),
            run=lambda _c: json.dumps(
                {
                    "accessToken": "sk-super-secret-value",
                    "expiresAt": (_NOW - timedelta(hours=1)).isoformat(),
                }
            ),
            now=lambda: _NOW,
        )
        client, token, ledger = _client(tmp_path, handler, credential=expired)
        async with client:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": token},
                json={"model": "claude-opus-5"},
            )

        assert "sk-super-secret-value" not in response.text
        assert "sk-super-secret-value" not in ledger.path.read_text()


class TestAPooledAccountsDeclarationWinsOverTheAuthStyle:
    """ADR-0148: a metered key and a flat-rate plan can share a lane.

    That is the whole reason accounts exist here, so the ledger must read the
    ACCOUNT's declared `billing_kind` rather than infer one from the auth
    style. Nothing else exercises `_billing_kind`'s account branch: the
    end-to-end tests above run without a pool, where it correctly falls
    through to the upstream.
    """

    def _proxy_with_pool(self, tmp_path: Path, pool: object):
        from hydraflow_gateway.ledger import GatewayLedger
        from hydraflow_gateway.proxy import GatewayProxy
        from model_pricing import ModelPricingTable

        return GatewayProxy(
            settings=_subscription_settings(tmp_path),
            client=httpx.AsyncClient(),
            ledger=GatewayLedger(tmp_path / "l.jsonl"),
            body_store=GatewayBodyStore(tmp_path / "b"),
            pricing=ModelPricingTable(),
            account_pool=pool,  # type: ignore[arg-type]
        )

    def _identity(self, account_id: str | None):
        from hydraflow_gateway.models import (
            BodyCapturePolicy,
            GatewayIdentity,
            Principal,
            RouteBinding,
        )

        return GatewayIdentity(
            key_id="key-1",
            principal=Principal(kind="loop", id="implementer"),
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            body_capture_policy=BodyCapturePolicy.METADATA_ONLY,
            issued_at=_NOW,
            expires_at=_NOW + timedelta(minutes=5),
            route_binding=(
                None
                if account_id is None
                else RouteBinding(
                    mint_decision_id="mint-1",
                    route_decision_id="route-1",
                    dispatch_id="dispatch-1",
                    account_id=account_id,
                    effective_model="claude-opus-5",
                )
            ),
        )

    def test_a_flat_rate_account_is_reported_flat_rate(self, tmp_path: Path) -> None:
        from hydraflow_gateway.models import AccountBillingKind

        class _Pool:
            def account(self, account_id: str):
                from hydraflow_gateway.routing_accounts import GatewayAccount

                return GatewayAccount.model_validate(
                    {
                        "id": account_id,
                        "provider_binding": "anthropic",
                        "base_url": "https://upstream.test",
                        "auth_style": "oauth-bearer",
                        "billing_kind": "flat_rate",
                    }
                )

        proxy = self._proxy_with_pool(tmp_path, _Pool())

        assert (
            proxy._billing_kind(self._identity("claude-subscription"))
            is AccountBillingKind.FLAT_RATE
        )

    def test_a_metered_account_on_the_same_lane_is_reported_metered(
        self, tmp_path: Path
    ) -> None:
        """The decoy that matters: same provider binding, opposite billing.

        The settings' own Anthropic upstream is oauth-bearer here, so inferring
        from the auth style would call this flat_rate and quietly stop counting
        real dollars.
        """
        from hydraflow_gateway.models import AccountBillingKind

        class _Pool:
            def account(self, account_id: str):
                from hydraflow_gateway.routing_accounts import GatewayAccount

                return GatewayAccount.model_validate(
                    {
                        "id": account_id,
                        "provider_binding": "anthropic",
                        "base_url": "https://upstream.test",
                        "auth_style": "x-api-key",
                        "credential_env": "GATEWAY_ACCOUNT_METERED_KEY",
                        "billing_kind": "metered",
                    }
                )

        proxy = self._proxy_with_pool(tmp_path, _Pool())

        assert (
            proxy._billing_kind(self._identity("claude-metered"))
            is AccountBillingKind.METERED
        )


class TestFlatRateTrafficIsNotSummedAsSpend:
    """ADR-0148's `billing_kind` has to change a number, or it is decoration.

    `.env.sample`, the wiki and this file's own docstrings all promise that a
    subscription's rows are "not summed as dollars owed". The only reader of
    gateway ledger cost is `_aggregate_gateway_rows`, so that promise is either
    true there or it is false everywhere.
    """

    def _rows(self, billing_kind: str) -> list[dict[str, object]]:
        return [
            {
                "timestamp": "2026-09-03T12:00:00+00:00",
                "repo_slug": "acme/hydraflow",
                "model_served": "claude-opus-5",
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "billing_kind": billing_kind,
            }
        ]

    def _spend(self, rows: list[dict[str, object]]) -> float:
        from datetime import datetime

        from gateway_coverage import _aggregate_gateway_rows
        from model_pricing import ModelPricingTable

        return _aggregate_gateway_rows(
            rows,
            since=datetime(2026, 9, 1, tzinfo=UTC),
            until=datetime(2026, 9, 30, tzinfo=UTC),
            repo_slug="acme/hydraflow",
            pricing=ModelPricingTable(),
        ).spend_usd

    def test_a_metered_row_is_spend(self) -> None:
        """Anti-vacuity floor: this model IS priced, so the decoy below means
        something. Without it, a pricing table that returned 0.0 for everything
        would make the flat-rate assertion pass for the wrong reason."""
        assert self._spend(self._rows("metered")) > 0.0

    def test_a_flat_rate_row_is_not_spend(self) -> None:
        assert self._spend(self._rows("flat_rate")) == 0.0

    def test_a_row_written_before_the_field_existed_is_still_spend(self) -> None:
        """Every historical row lacks `billing_kind` and was real money."""
        rows = self._rows("metered")
        del rows[0]["billing_kind"]

        assert self._spend(rows) > 0.0

    def test_a_flat_rate_row_is_still_counted_as_a_request(self) -> None:
        """It costs no dollars and it is still traffic — coverage must see it."""
        from datetime import datetime

        from gateway_coverage import _aggregate_gateway_rows
        from model_pricing import ModelPricingTable

        aggregate = _aggregate_gateway_rows(
            self._rows("flat_rate"),
            since=datetime(2026, 9, 1, tzinfo=UTC),
            until=datetime(2026, 9, 30, tzinfo=UTC),
            repo_slug="acme/hydraflow",
            pricing=ModelPricingTable(),
        )

        assert aggregate.requests == 1
