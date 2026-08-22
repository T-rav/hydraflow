"""Virtual-key lifecycle, policy, and environment contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from hydraflow_gateway.keys import (
    ExpiredVirtualKey,
    InvalidVirtualKey,
    KeyPolicyError,
    VirtualKeyStore,
)
from hydraflow_gateway.models import (
    MintKeyRequest,
    PrincipalKind,
    ProviderBinding,
    RepoClass,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
    _governed_repo_allowlist,
    _repo_slug_allowlist,
)
from mockworld.fakes.fake_clock import FakeClock

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"


def _request(**overrides: object) -> MintKeyRequest:
    values: dict[str, object] = {
        "principal_kind": "spawn",
        "principal_id": "implementer",
        "spawn_id": "spawn-17",
        "session_id": "session-4",
        "repo_slug": "acme/hydraflow",
        "repo_class": "hydraflow",
        "provider_binding": "anthropic",
        "capture_bodies": False,
        "ttl_seconds": 60,
    }
    values.update(overrides)
    return MintKeyRequest.model_validate(values)


class TestMintKeyRequest:
    def test_requires_spawn_id_for_spawn_principal(self) -> None:
        with pytest.raises(ValidationError, match="spawn_id is required"):
            _request(spawn_id=None)

    @pytest.mark.parametrize("repo_class", ["client", "personal"])
    def test_rejects_body_capture_for_sensitive_repo_classes(
        self, repo_class: str
    ) -> None:
        with pytest.raises(ValidationError, match="body capture is prohibited"):
            _request(repo_class=repo_class, capture_bodies=True)

    def test_accepts_future_person_principal_without_spawn(self) -> None:
        request = _request(
            principal_kind="person",
            principal_id="person-42",
            spawn_id=None,
            capture_bodies=False,
        )
        assert request.principal().kind is PrincipalKind.PERSON
        assert request.principal().spawn_id is None


class TestVirtualKeyStore:
    def test_mint_resolve_and_expire_at_exact_ttl_boundary(self) -> None:
        clock = FakeClock(start=1_700_000_000)
        store = VirtualKeyStore(
            max_ttl_seconds=120,
            wall_clock=clock.now,
            monotonic=clock.monotonic,
            id_factory=lambda: "key-1",
            secret_factory=lambda: "secret-material",
        )
        minted = store.mint(_request())

        assert minted.key_id == "key-1"
        assert minted.token == "hfgw_key-1.secret-material"
        assert store.resolve(minted.token).principal.spawn_id == "spawn-17"
        assert store.resolve(minted.token).provider_binding is ProviderBinding.ANTHROPIC

        clock.advance(60)
        with pytest.raises(ExpiredVirtualKey, match="expired virtual key"):
            store.resolve(minted.token)
        assert store.active_count == 0

    def test_rejects_unknown_malformed_and_modified_tokens(self) -> None:
        store = VirtualKeyStore(
            max_ttl_seconds=120,
            id_factory=lambda: "key-1",
            secret_factory=lambda: "secret-material",
        )
        minted = store.mint(_request())

        for token in ("not-a-key", "hfgw_unknown.value", minted.token + "x"):
            with pytest.raises(InvalidVirtualKey):
                store.resolve(token)

    def test_retains_only_digest_and_hides_token_from_repr(self) -> None:
        store = VirtualKeyStore(
            max_ttl_seconds=120,
            id_factory=lambda: "key-1",
            secret_factory=lambda: "secret-material",
        )
        minted = store.mint(_request())

        assert minted.token not in repr(minted)
        assert minted.token not in repr(store.__dict__)
        assert "secret-material" not in repr(store.__dict__)

    def test_revoke_invalidates_key_immediately(self) -> None:
        store = VirtualKeyStore(max_ttl_seconds=120)
        minted = store.mint(_request())

        assert store.revoke(minted.key_id) is True
        assert store.revoke(minted.key_id) is False
        with pytest.raises(InvalidVirtualKey):
            store.resolve(minted.token)

    def test_reap_removes_only_expired_keys(self) -> None:
        clock = FakeClock()
        ids = iter(["short", "long"])
        secrets = iter(["secret-one", "secret-two"])
        store = VirtualKeyStore(
            max_ttl_seconds=120,
            wall_clock=clock.now,
            monotonic=clock.monotonic,
            id_factory=lambda: next(ids),
            secret_factory=lambda: next(secrets),
        )
        short = store.mint(_request(ttl_seconds=10))
        long = store.mint(_request(ttl_seconds=20))

        clock.advance(10)
        assert store.reap_expired() == 1
        assert store.resolve(long.token).key_id == long.key_id
        with pytest.raises(InvalidVirtualKey):
            store.resolve(short.token)

    def test_enforces_maximum_ttl(self) -> None:
        store = VirtualKeyStore(max_ttl_seconds=30)
        with pytest.raises(KeyPolicyError, match="TTL exceeds"):
            store.mint(_request(ttl_seconds=31))

    def test_full_capture_requires_server_owned_repository_allowlist(self) -> None:
        denied = VirtualKeyStore(max_ttl_seconds=30)
        allowed = VirtualKeyStore(
            max_ttl_seconds=30,
            body_capture_repo_slugs=frozenset({"ACME/HydraFlow"}),
        )
        request = _request(capture_bodies=True, ttl_seconds=30)

        with pytest.raises(KeyPolicyError, match="not authorized"):
            denied.mint(request)

        identity = allowed.resolve(allowed.mint(request).token)
        assert identity.repo_slug == "acme/hydraflow"

    def test_expiry_uses_monotonic_time_when_wall_clock_moves_back(self) -> None:
        wall = [1_700_000_000.0]
        monotonic = [100.0]
        store = VirtualKeyStore(
            max_ttl_seconds=30,
            wall_clock=lambda: wall[0],
            monotonic=lambda: monotonic[0],
        )
        minted = store.mint(_request(ttl_seconds=10))

        wall[0] -= 3_600
        monotonic[0] += 10

        with pytest.raises(ExpiredVirtualKey):
            store.resolve(minted.token)

    def test_defends_capture_policy_when_model_validation_is_bypassed(self) -> None:
        request = MintKeyRequest.model_construct(
            principal_kind=PrincipalKind.PERSON,
            principal_id="person-1",
            spawn_id=None,
            session_id=None,
            repo_slug="client/private",
            repo_class=RepoClass.CLIENT,
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=True,
            ttl_seconds=10,
        )
        store = VirtualKeyStore(max_ttl_seconds=30)

        with pytest.raises(KeyPolicyError, match="body capture is prohibited"):
            store.mint(request)


class TestGatewaySettings:
    def test_from_env_loads_exact_public_contract(self, tmp_path: Path) -> None:
        settings = GatewaySettings.from_env(
            {
                "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                "GATEWAY_ANTHROPIC_BASE_URL": "https://api.example.test/root/",
                "GATEWAY_ANTHROPIC_API_KEY": "provider-secret",
                "GATEWAY_LEDGER_PATH": str(tmp_path / "ledger.jsonl"),
                "GATEWAY_BODY_DIR": str(tmp_path / "bodies"),
                "GATEWAY_MAX_KEY_TTL_SECONDS": "900",
                "GATEWAY_MAX_REQUEST_BYTES": "2048",
                "GATEWAY_MAX_CONTROL_REQUEST_BYTES": "4096",
                "GATEWAY_BODY_CAPTURE_REPOS": " acme/hydraflow,Other/Repo ",
                "GATEWAY_BODY_RETENTION_SECONDS": "12345",
            }
        )

        upstream = settings.upstreams[ProviderBinding.ANTHROPIC]
        assert settings.control_token == SecretStr(_CONTROL_TOKEN)
        assert upstream.base_url == "https://api.example.test/root"
        assert upstream.api_key == SecretStr("provider-secret")
        assert upstream.auth_style == UpstreamAuthStyle.X_API_KEY
        assert settings.max_key_ttl_seconds == 900
        assert settings.max_request_bytes == 2048
        assert settings.max_control_request_bytes == 4096
        assert settings.body_capture_repo_slugs == frozenset(
            {"acme/hydraflow", "other/repo"}
        )
        assert settings.body_retention_seconds == 12345

    @pytest.mark.parametrize(
        "environment, message",
        [
            ({}, "GATEWAY_CONTROL_TOKEN is required"),
            (
                {
                    "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                    "GATEWAY_ANTHROPIC_BASE_URL": "https://api.example.test",
                },
                "must be set together",
            ),
            (
                {
                    "GATEWAY_CONTROL_TOKEN": _CONTROL_TOKEN,
                    "GATEWAY_MAX_KEY_TTL_SECONDS": "never",
                },
                "must be an integer",
            ),
        ],
    )
    def test_from_env_fails_closed_on_incomplete_configuration(
        self, environment: dict[str, str], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            GatewaySettings.from_env(environment)

    def test_rejects_low_entropy_control_token(self) -> None:
        with pytest.raises(ValidationError, match="at least 32 ASCII bytes"):
            GatewaySettings(
                control_token=SecretStr("short"),
                upstreams={
                    ProviderBinding.ANTHROPIC: UpstreamSettings(
                        base_url="https://api.example.test",
                        api_key=SecretStr("provider-secret"),
                        auth_style=UpstreamAuthStyle.X_API_KEY,
                    )
                },
            )

    def test_rejects_base_url_with_userinfo_or_query(self) -> None:
        with pytest.raises(ValidationError, match="must not contain"):
            UpstreamSettings(
                base_url="https://user@example.test/path?next=evil",
                api_key=SecretStr("secret"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )

    def test_rejects_non_ascii_header_secrets(self) -> None:
        with pytest.raises(ValidationError, match="must be ASCII"):
            GatewaySettings(
                control_token=SecretStr("contröl"),
                upstreams={
                    ProviderBinding.ANTHROPIC: UpstreamSettings(
                        base_url="https://api.example.test",
                        api_key=SecretStr("provider-secret"),
                        auth_style=UpstreamAuthStyle.X_API_KEY,
                    )
                },
            )


class TestAttribution:
    """Optional issue/PR attribution rides the principal onto every ledger row."""

    def test_mint_carries_issue_and_pr_numbers_into_identity(self) -> None:
        store = VirtualKeyStore(max_ttl_seconds=600)

        minted = store.mint(_request(issue_number=11464, pr_number=11500))
        principal = store.resolve(minted.token).principal

        assert (principal.issue_number, principal.pr_number) == (11464, 11500)

    def test_attribution_defaults_to_none(self) -> None:
        principal = _request().principal()

        assert principal.issue_number is None
        assert principal.pr_number is None

    @pytest.mark.parametrize("field", ["issue_number", "pr_number"])
    def test_attribution_rejects_non_positive_numbers(self, field: str) -> None:
        with pytest.raises(ValidationError):
            _request(**{field: 0})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(
            "acme/project-x",
            frozenset({"acme-project-x"}),
            id="a-canonical-entry-is-translated-to-the-runtime-slug",
        ),
        pytest.param(
            "acme-project-x",
            frozenset({"acme-project-x"}),
            id="a-runtime-slug-is-kept-verbatim",
        ),
        pytest.param(
            "ACME/Project-X , other-repo",
            frozenset({"acme-project-x", "other-repo"}),
            id="both-forms-mix-and-case-does-not-matter",
        ),
        pytest.param("", frozenset(), id="the-empty-default-governs-nothing"),
    ],
)
def test_the_governed_set_accepts_either_identity_space(
    raw: str, expected: frozenset[str]
) -> None:
    """ADR-0141 §D4: a security control must not fail open on a format difference.

    HydraFlow's canary dial is the canonical ``owner/repo``; a mint request
    carries the path-safe ``owner-repo``. An operator copying the value across
    would otherwise arm nothing, silently.
    """
    assert _governed_repo_allowlist(raw) == expected


def test_the_body_capture_allowlist_is_still_matched_exactly() -> None:
    """It shares a shape with the governed set but not its semantics.

    ``body_capture_repo_slugs`` is compared against whatever
    ``MintKeyRequest.repo_slug`` carries — a caller-supplied string with no
    guaranteed form — so normalising it would silently de-authorise a repository
    whose slug does not round-trip.
    """
    assert _repo_slug_allowlist("acme/hydraflow") == frozenset({"acme/hydraflow"})
