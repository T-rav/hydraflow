"""The server-owned account registry and its deterministic candidate order.

A pool only means something if "which account serves this?" has one answer that
can be stated before the request. These tests hold that from both ends: the
registry refuses anything that would make the order ambiguous (duplicate ids,
a redeclared legacy id, a credential named in the file rather than the
environment), and :meth:`AccountRegistry.candidates_for_model` returns the same
ordered tuple every time for the same inputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from hydraflow_gateway.models import ProviderBinding, legacy_account_id
from hydraflow_gateway.routing_accounts import (
    RESERVED_ACCOUNT_IDS,
    AccountBillingKind,
    AccountPool,
    AccountRegistryError,
    GatewayAccount,
    build_account_registry,
    compile_legacy_accounts,
    load_account_pool,
    parse_account_definitions,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)

_CONTROL_TOKEN = "registry-control-token-0123456789abcdef"


def _upstream(base_url: str = "https://zai.test") -> UpstreamSettings:
    return UpstreamSettings(
        base_url=base_url,
        api_key=SecretStr("registry-upstream-key"),
        auth_style=UpstreamAuthStyle.BEARER,
    )


def _definition(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "zai-secondary",
        "display_name": "z.ai secondary",
        "provider_binding": "zai-harness",
        "base_url": "https://api2.z.ai/api/anthropic",
        "auth_style": "bearer",
        "credential_env": "GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY",
        "lease_capacity": 4,
        "request_capacity": 8,
        "allowed_models": ["glm-*"],
    }
    payload.update(overrides)
    return payload


def _account(**overrides: object) -> GatewayAccount:
    return GatewayAccount.model_validate(_definition(**overrides))


def _settings(**overrides: object) -> GatewaySettings:
    payload: dict[str, object] = {
        "control_token": SecretStr(_CONTROL_TOKEN),
        "upstreams": {
            ProviderBinding.ANTHROPIC: _upstream("https://anthropic.test"),
            ProviderBinding.ZAI_HARNESS: _upstream(),
        },
    }
    payload.update(overrides)
    return GatewaySettings(**payload)  # type: ignore[arg-type]


# -- the shape of one declared account ---------------------------------------


@pytest.mark.parametrize(
    ("overrides", "marker"),
    [
        pytest.param({"id": "Zai Secondary"}, "id", id="id-is-not-url-safe"),
        pytest.param(
            {"credential_env": "ZAI_SECONDARY_KEY"},
            "GATEWAY_",
            id="credential-env-is-outside-the-scrubbed-namespace",
        ),
        pytest.param(
            {"credential_env": "GATEWAY_lower_case"},
            "GATEWAY_",
            id="credential-env-is-not-an-environment-variable-name",
        ),
        pytest.param(
            {"base_url": "https://user:pw@zai.test"},
            "base_url",
            id="base-url-carries-credentials",
        ),
        pytest.param(
            {"base_url": "ftp://zai.test"}, "base_url", id="base-url-is-not-http"
        ),
        pytest.param({"lease_capacity": 0}, "lease_capacity", id="lease-capacity-zero"),
        pytest.param(
            {"request_capacity": -1}, "request_capacity", id="request-capacity-negative"
        ),
        pytest.param(
            {"api_key": "sk-secret"}, "api_key", id="credential-value-in-the-file"
        ),
    ],
)
def test_an_inadmissible_account_definition_is_refused(
    overrides: dict[str, object], marker: str
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _account(**overrides)
    assert marker in str(excinfo.value)


def test_an_account_without_capacity_declares_no_ceiling() -> None:
    account = _account(lease_capacity=None, request_capacity=None)
    assert (account.lease_capacity, account.request_capacity) == (None, None)


def test_a_declared_account_keeps_its_base_url_without_a_trailing_slash() -> None:
    assert _account(base_url="https://api2.z.ai/v1/").base_url == "https://api2.z.ai/v1"


def test_an_account_defaults_to_metered_billing() -> None:
    assert _account().billing_kind is AccountBillingKind.METERED


# -- compiling the legacy environment pairs ----------------------------------


def test_the_legacy_pairs_compile_into_their_reserved_identities() -> None:
    compiled = compile_legacy_accounts(_settings().upstreams)
    assert [account.account_id for account in compiled] == sorted(RESERVED_ACCOUNT_IDS)


def test_a_legacy_account_declares_no_capacity_ceiling() -> None:
    compiled = compile_legacy_accounts(_settings().upstreams)
    assert all(account.lease_capacity is None for account in compiled)


def test_an_unconfigured_legacy_pair_still_has_a_named_account() -> None:
    upstreams = {ProviderBinding.ANTHROPIC: _upstream("https://anthropic.test")}
    compiled = compile_legacy_accounts(upstreams)
    assert [account.account_id for account in compiled] == sorted(RESERVED_ACCOUNT_IDS)


# -- the file, parsed --------------------------------------------------------


def test_a_registry_file_is_parsed_into_declared_accounts() -> None:
    parsed = parse_account_definitions(
        "schema_version: 1\naccounts:\n"
        "  - id: zai-secondary\n"
        "    provider_binding: zai-harness\n"
        "    base_url: https://api2.z.ai\n"
        "    auth_style: bearer\n"
        "    credential_env: GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY\n"
    )
    assert [account.account_id for account in parsed] == ["zai-secondary"]


@pytest.mark.parametrize(
    ("document", "marker"),
    [
        pytest.param("accounts: []\n", "schema_version", id="schema-version-missing"),
        pytest.param(
            "schema_version: 99\naccounts: []\n", "schema_version", id="unknown-version"
        ),
        pytest.param("schema_version: 1\n", "accounts", id="accounts-key-missing"),
        pytest.param(
            "schema_version: 1\naccounts: {}\n", "accounts", id="accounts-not-a-list"
        ),
        pytest.param("[", "could not be parsed", id="not-parseable-at-all"),
        pytest.param(
            "schema_version: 1\nextra: 1\naccounts: []\n", "extra", id="unknown-key"
        ),
    ],
)
def test_an_inadmissible_registry_document_is_refused(
    document: str, marker: str
) -> None:
    with pytest.raises(AccountRegistryError) as excinfo:
        parse_account_definitions(document)
    assert marker in str(excinfo.value)


def test_a_document_may_not_redeclare_a_reserved_legacy_identity() -> None:
    reserved = legacy_account_id(ProviderBinding.ZAI_HARNESS)
    document = (
        f"schema_version: 1\naccounts:\n"
        f"  - {{id: {reserved}, provider_binding: zai-harness, "
        f"base_url: 'https://elsewhere.test', auth_style: bearer, "
        f"credential_env: GATEWAY_ELSEWHERE_KEY}}\n"
    )
    with pytest.raises(AccountRegistryError, match="reserved"):
        parse_account_definitions(document)


def test_two_accounts_may_not_share_one_id() -> None:
    document = (
        "schema_version: 1\naccounts:\n"
        "  - {id: a, provider_binding: zai-harness, base_url: 'https://one.test', "
        "auth_style: bearer, credential_env: GATEWAY_A}\n"
        "  - {id: a, provider_binding: zai-harness, base_url: 'https://two.test', "
        "auth_style: bearer, credential_env: GATEWAY_B}\n"
    )
    with pytest.raises(AccountRegistryError, match="duplicate"):
        parse_account_definitions(document)


# -- the assembled registry --------------------------------------------------


def test_the_legacy_accounts_lead_the_registry_order() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams, declared=(_account(),)
    )
    assert registry.account_ids[: len(RESERVED_ACCOUNT_IDS)] == tuple(
        sorted(RESERVED_ACCOUNT_IDS)
    )


def test_a_declared_account_follows_the_legacy_ones() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams, declared=(_account(),)
    )
    assert registry.account_ids[-1] == "zai-secondary"


def test_declared_accounts_keep_their_declaration_order() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams,
        declared=(_account(id="zai-b"), _account(id="zai-a")),
    )
    assert registry.account_ids[-2:] == ("zai-b", "zai-a")


def test_an_unknown_account_id_resolves_to_nothing() -> None:
    registry = build_account_registry(upstreams=_settings().upstreams, declared=())
    assert registry.get("no-such-account") is None


# -- candidate derivation: the deterministic half of "pool" ------------------


def test_the_candidates_for_a_model_are_the_accounts_on_its_lane() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams, declared=(_account(),)
    )
    assert registry.candidates_for_model("glm-5.3") == (
        legacy_account_id(ProviderBinding.ZAI_HARNESS),
        "zai-secondary",
    )


def test_an_anthropic_model_never_reaches_a_zai_account() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams, declared=(_account(),)
    )
    assert registry.candidates_for_model("claude-sonnet-4-6") == (
        legacy_account_id(ProviderBinding.ANTHROPIC),
    )


def test_an_account_whose_allowed_models_exclude_the_model_is_not_a_candidate() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams,
        declared=(_account(allowed_models=["glm-4*"]),),
    )
    assert "zai-secondary" not in registry.candidates_for_model("glm-5.3")


def test_an_account_declaring_no_allowed_models_serves_its_whole_lane() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams, declared=(_account(allowed_models=[]),)
    )
    assert "zai-secondary" in registry.candidates_for_model("glm-5.3")


def test_the_candidate_order_is_the_same_on_every_call() -> None:
    registry = build_account_registry(
        upstreams=_settings().upstreams,
        declared=(_account(id="zai-b"), _account(id="zai-a")),
    )
    answers = {registry.candidates_for_model("glm-5.3") for _ in range(16)}
    assert len(answers) == 1


# -- the pool a deployment's environment describes ---------------------------

_DECLARED_DOCUMENT = (
    "schema_version: 1\naccounts:\n"
    "  - id: zai-secondary\n"
    "    provider_binding: zai-harness\n"
    "    base_url: https://api2.z.ai/api/anthropic\n"
    "    auth_style: bearer\n"
    "    credential_env: GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY\n"
    "    lease_capacity: 4\n"
)


def _pool_with_file(
    tmp_path: Path, *, environ: dict[str, str] | None = None
) -> AccountPool:
    path = tmp_path / "accounts.yaml"
    path.write_text(_DECLARED_DOCUMENT, encoding="utf-8")
    return load_account_pool(_settings(accounts_file=path), environ or {})


def test_a_deployment_with_no_registry_file_has_exactly_the_legacy_accounts() -> None:
    pool = load_account_pool(_settings(), {})
    assert pool.registry.account_ids == tuple(sorted(RESERVED_ACCOUNT_IDS))


def test_a_declared_account_joins_the_pool_from_its_file(tmp_path: Path) -> None:
    assert "zai-secondary" in _pool_with_file(tmp_path).registry.account_ids


def test_a_declared_account_is_configured_when_its_credential_is_present(
    tmp_path: Path,
) -> None:
    pool = _pool_with_file(
        tmp_path, environ={"GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY": "declared-key"}
    )
    assert pool.configured("zai-secondary") is True


def test_a_declared_account_without_its_credential_is_not_configured(
    tmp_path: Path,
) -> None:
    assert _pool_with_file(tmp_path).configured("zai-secondary") is False


def test_a_declared_account_without_its_credential_still_loads_the_pool(
    tmp_path: Path,
) -> None:
    assert "zai-secondary" in _pool_with_file(tmp_path).registry.account_ids


def test_the_upstream_for_a_declared_account_is_its_own_origin(
    tmp_path: Path,
) -> None:
    pool = _pool_with_file(
        tmp_path, environ={"GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY": "declared-key"}
    )
    upstream = pool.upstream("zai-secondary")
    assert upstream is not None
    assert upstream.base_url == "https://api2.z.ai/api/anthropic"


def test_the_upstream_for_a_legacy_account_is_its_environment_pair() -> None:
    pool = load_account_pool(_settings(), {})
    upstream = pool.upstream(legacy_account_id(ProviderBinding.ZAI_HARNESS))
    assert upstream is not None and upstream.base_url == "https://zai.test"


def test_an_unconfigured_legacy_account_has_no_upstream() -> None:
    pool = load_account_pool(
        _settings(upstreams={ProviderBinding.ZAI_HARNESS: _upstream()}), {}
    )
    assert pool.upstream(legacy_account_id(ProviderBinding.ANTHROPIC)) is None


def test_a_lane_served_only_by_a_declared_account_still_counts_as_configured(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(_DECLARED_DOCUMENT, encoding="utf-8")
    settings = _settings(
        accounts_file=path,
        upstreams={ProviderBinding.ANTHROPIC: _upstream("https://anthropic.test")},
    )
    pool = load_account_pool(
        settings, {"GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY": "declared-key"}
    )
    assert ProviderBinding.ZAI_HARNESS in pool.configured_bindings()


def test_a_registry_file_that_cannot_be_read_fails_closed(tmp_path: Path) -> None:
    settings = _settings(accounts_file=tmp_path / "absent.yaml")
    with pytest.raises(AccountRegistryError, match="could not be read"):
        load_account_pool(settings, {})


def test_an_unknown_key_refusal_reports_a_count_rather_than_the_key() -> None:
    """The one path that could quote document content back into a startup log.

    A mistyped credential pasted as a YAML key is exactly the content that must
    not travel, and the module's rule is that it never quotes a value.
    """
    document = (
        "schema_version: 1\naccounts: []\n"
        "sk-ant-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa: 1\n"
    )
    with pytest.raises(AccountRegistryError) as excinfo:
        parse_account_definitions(document)

    assert "sk-ant-" not in str(excinfo.value)


def test_an_unknown_key_refusal_still_says_how_many_there_were() -> None:
    with pytest.raises(AccountRegistryError, match="2 extra"):
        parse_account_definitions("schema_version: 1\naccounts: []\na: 1\nb: 2\n")
