"""The server-owned account registry: what accounts exist, and in what order.

ADR-0138 compiled the two ``GATEWAY_<PROVIDER>_{BASE_URL,API_KEY}`` environment
pairs into stable identities and said multi-account pools were a later phase.
This is that phase's first half. A deployment may declare additional accounts in
a **server-owned file** (``GATEWAY_ACCOUNTS_FILE``), and the registry is the one
place that answers "which accounts could serve this model, in what order".

Three properties make a pool something a decision can be explained from:

* **No credential is ever in the file.** An account names the *variable* that
  configures it (``credential_env``), never a value, and that name must live in
  the ``GATEWAY_`` namespace so a worker's environment scrub reaches it. A
  document carrying an ``api_key`` is refused by ``extra="forbid"`` rather than
  quietly ignored.
* **The order is total and declared.** The reserved legacy accounts lead —
  the account already serving today's traffic keeps serving first, so adding a
  pool is additive rather than a silent re-route — and declared accounts follow
  in file order. Redeclaring a reserved id is refused, because two definitions
  of one account is exactly the ambiguity an ordered pool exists to remove.
* **Candidates are a pure function of the model.** ``candidates_for_model``
  filters the registry by the lane :func:`hydraflow_gateway.models.binding_for_model`
  assigns and by each account's own ``allowed_models`` patterns. It reads no
  live state, so the *set* is stable and only the live filters (credential,
  administrative state, circuit, capacity) can vary between two attempts.

Capacity is deliberately ``None`` by default. A legacy account has never had a
ceiling, and inventing one here would make an additive registry a throughput
change for every deployment that never asked for a pool.
"""

from __future__ import annotations

import os
import re
from enum import StrEnum
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from hydraflow_gateway.models import (
    LEGACY_ACCOUNT_IDS,
    ProviderBinding,
    binding_for_model,
    legacy_account_id,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
    normalise_upstream_base_url,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ACCOUNT_REGISTRY_SCHEMA_VERSION = 1
"""The only ``schema_version`` this build will load. An unknown one is refused."""

RESERVED_ACCOUNT_IDS: frozenset[str] = frozenset(LEGACY_ACCOUNT_IDS.values())
"""ADR-0138's compiled identities. A file may not redeclare one."""

_ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_CREDENTIAL_ENV_RE = re.compile(r"^GATEWAY_[A-Z0-9_]+$")

LEGACY_DISPLAY_NAMES: Mapping[ProviderBinding, str] = MappingProxyType(
    {
        ProviderBinding.ANTHROPIC: "Anthropic (legacy upstream)",
        ProviderBinding.ZAI_HARNESS: "z.ai harness (legacy upstream)",
    }
)

LEGACY_CREDENTIAL_ENV: Mapping[ProviderBinding, str] = MappingProxyType(
    {
        ProviderBinding.ANTHROPIC: "GATEWAY_ANTHROPIC_API_KEY",
        ProviderBinding.ZAI_HARNESS: "GATEWAY_ZAI_HARNESS_API_KEY",
    }
)

_LEGACY_AUTH_STYLE: Mapping[ProviderBinding, UpstreamAuthStyle] = MappingProxyType(
    {
        ProviderBinding.ANTHROPIC: UpstreamAuthStyle.X_API_KEY,
        ProviderBinding.ZAI_HARNESS: UpstreamAuthStyle.BEARER,
    }
)


class AccountRegistryError(ValueError):
    """A server-owned account document could not be loaded. Never quotes a value."""


class AccountBillingKind(StrEnum):
    """Whether spend on this account is metered actual or a flat-rate notional."""

    METERED = "metered"
    FLAT_RATE = "flat_rate"


class GatewayAccount(BaseModel):
    """One account's non-secret definition. Never carries credential material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(alias="id", min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    provider_binding: ProviderBinding
    base_url: str
    auth_style: UpstreamAuthStyle
    credential_env: str = Field(min_length=1, max_length=128)
    credential_kind: str = Field(default="api-key", max_length=64)
    billing_kind: AccountBillingKind = AccountBillingKind.METERED
    # ``None`` is "no declared ceiling", which is what every legacy account has
    # always had. A number is a real admission limit enforced at the mint (lease)
    # and at the proxy (request).
    lease_capacity: int | None = Field(default=None, gt=0)
    request_capacity: int | None = Field(default=None, gt=0)
    allowed_models: tuple[str, ...] = ()
    """fnmatch patterns. Empty means this account serves its whole lane."""
    capabilities: tuple[str, ...] = ()

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, value: str) -> str:
        """Ids reach ledgers and URLs, so they are lowercase and path-safe."""
        candidate = value.strip().lower()
        if _ACCOUNT_ID_RE.fullmatch(candidate) is None:
            raise ValueError(
                "id must be lowercase alphanumeric with '.', '-' or '_' separators"
            )
        # The reserved-id refusal deliberately lives in
        # :func:`parse_account_definitions` rather than here: it is a rule about
        # what a *document* may declare, not about what the type may hold, and
        # :func:`compile_legacy_accounts` builds those very ids.
        return candidate

    @field_validator("credential_env")
    @classmethod
    def validate_credential_env(cls, value: str) -> str:
        """The variable NAME, and only from the scrubbed ``GATEWAY_`` namespace.

        ``subprocess_util.scrub_gateway_spawn_env`` strips that whole namespace
        from a worker's environment. An account credential declared outside it
        would be inherited by every spawn — a pool that widens credential
        exposure is not a pool anyone should be able to declare in a file.
        """
        candidate = value.strip()
        if _CREDENTIAL_ENV_RE.fullmatch(candidate) is None:
            raise ValueError(
                "credential_env must be an upper-case GATEWAY_ environment "
                "variable name, and never a credential value"
            )
        return candidate

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """One fixed http(s) origin, exactly like a legacy upstream's."""
        return normalise_upstream_base_url(value)

    def serves_model(self, model: str) -> bool:
        """Whether this account's own allow-list admits *model*."""
        if not self.allowed_models:
            return True
        candidate = model.strip().lower()
        return any(
            fnmatchcase(candidate, pattern.strip().lower())
            for pattern in self.allowed_models
        )


class AccountRegistry(BaseModel):
    """The total, ordered set of accounts this deployment knows about."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = ACCOUNT_REGISTRY_SCHEMA_VERSION
    accounts: tuple[GatewayAccount, ...] = ()

    @property
    def account_ids(self) -> tuple[str, ...]:
        """Every account id in registry order. The order a pool is selected in."""
        return tuple(account.account_id for account in self.accounts)

    def get(self, account_id: str) -> GatewayAccount | None:
        """Return the account with this id, or ``None``."""
        target = account_id.strip().lower()
        for account in self.accounts:
            if account.account_id == target:
                return account
        return None

    def candidates_for_model(self, model: str) -> tuple[str, ...]:
        """The ordered account ids that *could* serve *model*. Pure and total.

        "Could" is the whole point of the split: this is the static half of
        eligibility — lane and declared model allow-list — and it does not read
        a credential, an administrative overlay, a circuit, or a capacity
        counter. A candidate set that varied with live state could not be
        replayed, and a fallback position computed against a set that has since
        changed shape would advance onto a different account than it named.
        """
        binding = binding_for_model(model)
        return tuple(
            account.account_id
            for account in self.accounts
            if account.provider_binding is binding and account.serves_model(model)
        )


def compile_legacy_accounts(
    upstreams: Mapping[ProviderBinding, UpstreamSettings],
) -> tuple[GatewayAccount, ...]:
    """Compile ADR-0138's environment pairs into their reserved identities.

    Every binding produces an account whether or not it is configured, exactly
    as ``build_accounts_view`` does: a missing credential is a named account an
    operator can fix, not an absence they have to infer. An unconfigured pair
    has no origin of its own, so it reports the provider's documented default —
    the account is never selectable while ``account_configured`` is false, so
    the origin is documentation rather than a route.
    """
    compiled = [
        GatewayAccount(
            id=legacy_account_id(binding),
            display_name=LEGACY_DISPLAY_NAMES[binding],
            provider_binding=binding,
            base_url=(
                upstreams[binding].base_url
                if binding in upstreams
                else _PLACEHOLDER_ORIGIN
            ),
            auth_style=(
                upstreams[binding].auth_style
                if binding in upstreams
                else _LEGACY_AUTH_STYLE[binding]
            ),
            credential_env=LEGACY_CREDENTIAL_ENV[binding],
        )
        for binding in ProviderBinding
    ]
    compiled.sort(key=lambda account: account.account_id)
    return tuple(compiled)


_PLACEHOLDER_ORIGIN = "https://unconfigured.invalid"
"""The origin of an account with no credential. Never reachable: an unconfigured
account is refused before selection, and ``.invalid`` is reserved by RFC 2606."""


def build_account_registry(
    *,
    upstreams: Mapping[ProviderBinding, UpstreamSettings],
    declared: Sequence[GatewayAccount] = (),
) -> AccountRegistry:
    """Assemble the ordered registry: reserved legacy accounts, then declared.

    Legacy first is the additive-by-construction choice. A deployment that adds
    a second z.ai account gets it as a *fallback target*, not as a silent
    promotion over the account that is already serving its traffic — so turning
    on a pool cannot move a single request on its own.
    """
    return AccountRegistry(
        accounts=compile_legacy_accounts(upstreams) + tuple(declared)
    )


def parse_account_definitions(document: str) -> tuple[GatewayAccount, ...]:
    """Parse a server-owned account document. Fails closed, never quotes a value.

    An unreadable or unknown-version document raises rather than degrading to an
    empty list: silently loading zero declared accounts would turn a typo into a
    pool that quietly stopped existing, and the fallback target an operator
    believes in would be missing with no signal at all.
    """
    try:
        loaded = yaml.safe_load(document)
    except yaml.YAMLError as exc:
        raise AccountRegistryError(
            "the account registry document could not be parsed"
        ) from exc
    if not isinstance(loaded, dict):
        raise AccountRegistryError(
            "the account registry document could not be parsed as a mapping"
        )
    unknown = set(loaded) - {"schema_version", "accounts"}
    if unknown:
        # The COUNT, never the names. This is the one place the module could
        # quote document content back into a startup log, and a mistyped
        # credential pasted as a YAML key is exactly the content that must not
        # travel — the module's rule is "never quotes a value", and a key is
        # close enough to one to be worth not testing the distinction.
        raise AccountRegistryError(
            f"the account registry document declares {len(unknown)} extra "
            "top-level key(s); only schema_version and accounts are permitted"
        )
    if loaded.get("schema_version") != ACCOUNT_REGISTRY_SCHEMA_VERSION:
        raise AccountRegistryError(
            f"the account registry document must declare schema_version "
            f"{ACCOUNT_REGISTRY_SCHEMA_VERSION}"
        )
    raw = loaded.get("accounts")
    if not isinstance(raw, list):
        raise AccountRegistryError(
            "the account registry document must declare an accounts list"
        )
    accounts = tuple(_account_from(entry, index) for index, entry in enumerate(raw))
    seen: set[str] = set()
    for account in accounts:
        if account.account_id in RESERVED_ACCOUNT_IDS:
            raise AccountRegistryError(
                f"the account registry redeclares the reserved legacy id "
                f"{account.account_id}"
            )
        if account.account_id in seen:
            raise AccountRegistryError(
                f"the account registry declares a duplicate id: {account.account_id}"
            )
        seen.add(account.account_id)
    return accounts


def _account_from(entry: Any, index: int) -> GatewayAccount:
    if not isinstance(entry, dict):
        raise AccountRegistryError(f"account #{index} is not a mapping")
    try:
        return GatewayAccount.model_validate(entry)
    except ValueError as exc:
        # The message names the field and the rule, never the offending value:
        # a malformed document can carry a credential someone pasted by mistake,
        # and this error reaches the gateway's startup log.
        raise AccountRegistryError(
            f"account #{index} is not admissible: "
            f"{'; '.join(sorted({str(error['loc'][0]) for error in _errors(exc)}))}"
        ) from exc


def _errors(exc: ValueError) -> Sequence[Mapping[str, Any]]:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        collected = errors()
        if isinstance(collected, list):
            return [error for error in collected if error.get("loc")]
    return [{"loc": ("account",)}]


class AccountPool:
    """The registry plus the credential each account is actually reachable with.

    Deliberately not a Pydantic model and deliberately not a field on
    :class:`~hydraflow_gateway.settings.GatewaySettings`: it holds
    :class:`~pydantic.SecretStr` upstreams, and every read model in this package
    is swept for credential-shaped fields. Keeping the secret-bearing half in a
    plain object that is never serialized means the sweep does not have to grow
    an exception for the one type that legitimately holds a key.

    ``configured`` is the single fact that separates "an account exists" from
    "an account can serve": an account with no credential in this process's
    environment is named, listed, and never selected.
    """

    __slots__ = ("_registry", "_upstreams")

    def __init__(
        self,
        registry: AccountRegistry,
        upstreams: Mapping[str, UpstreamSettings],
    ) -> None:
        self._registry = registry
        self._upstreams = dict(upstreams)

    @property
    def registry(self) -> AccountRegistry:
        """The ordered, non-secret account definitions."""
        return self._registry

    def account(self, account_id: str) -> GatewayAccount | None:
        """Return one account's definition, or ``None``."""
        return self._registry.get(account_id)

    def configured(self, account_id: str) -> bool:
        """Whether this process resolved a credential for *account_id*."""
        return account_id.strip().lower() in self._upstreams

    def upstream(self, account_id: str) -> UpstreamSettings | None:
        """Return the origin and credential one account is reached with."""
        return self._upstreams.get(account_id.strip().lower())

    def candidates_for_model(self, model: str) -> tuple[str, ...]:
        """The static, ordered candidate ids for *model*. See the registry."""
        return self._registry.candidates_for_model(model)


def load_account_pool(
    settings: GatewaySettings, environ: Mapping[str, str] | None = None
) -> AccountPool:
    """Build the pool this deployment's environment describes.

    The reserved legacy accounts take their credential from ``settings.upstreams``
    — the pairs ADR-0138 already compiled — and each declared account takes its
    own from the variable it *names*. A declared account whose variable is unset
    is loaded, listed, and never selected: refusing to start would turn a
    half-provisioned backup account into an outage of the primary, which is the
    opposite of what a fallback pool is for.
    """
    env = os.environ if environ is None else environ
    declared: tuple[GatewayAccount, ...] = ()
    if settings.accounts_file is not None:
        try:
            document = settings.accounts_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise AccountRegistryError(
                f"the account registry file at {settings.accounts_file} "
                "could not be read"
            ) from exc
        declared = parse_account_definitions(document)
    registry = build_account_registry(upstreams=settings.upstreams, declared=declared)
    upstreams: dict[str, UpstreamSettings] = {
        legacy_account_id(binding): upstream
        for binding, upstream in settings.upstreams.items()
    }
    for account in declared:
        secret = env.get(account.credential_env, "").strip()
        if not secret:
            continue
        upstreams[account.account_id] = UpstreamSettings(
            base_url=account.base_url,
            api_key=SecretStr(secret),
            auth_style=account.auth_style,
        )
    return AccountPool(registry, upstreams)
