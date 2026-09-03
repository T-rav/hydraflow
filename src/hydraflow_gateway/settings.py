"""Environment-backed settings for the LLM gateway deployable."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from hydraflow_gateway.models import ProviderBinding


class UpstreamAuthStyle(StrEnum):
    """Supported provider credential header styles."""

    X_API_KEY = "x-api-key"
    BEARER = "bearer"
    OAUTH_BEARER = "oauth-bearer"
    """A Claude subscription token: bearer PLUS the OAuth beta header.

    Separate from ``BEARER`` (z.ai's) for two reasons that both bite if they
    share a branch: an OAuth token to Anthropic is rejected without
    ``anthropic-beta: oauth-2025-04-20``, and it expires — so the credential
    is resolved per request from ``SubscriptionCredentialSource`` rather than
    read once from ``api_key``.
    """


class UpstreamSettings(BaseModel):
    """Fixed, server-owned upstream location and provider credential."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    api_key: SecretStr | None = None
    """The static provider credential, or ``None`` under ``OAUTH_BEARER``.

    Optional only for the subscription lane, where there is no static key to
    hold: the token expires, so it is resolved per request instead. Every other
    auth style still requires one — see :meth:`require_a_credential_or_a_lane`.
    """
    auth_style: UpstreamAuthStyle

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        """Provider credentials must be non-empty ASCII header values."""
        if value is None:
            return None
        _validate_header_secret(value.get_secret_value(), "provider API key")
        return value

    @model_validator(mode="after")
    def require_a_credential_or_a_lane(self) -> UpstreamSettings:
        """Exactly one of "static key" or "subscription lane", never neither.

        Making ``api_key`` optional opens a false-ready tap: an upstream with
        no key and no subscription lane would load fine and fail at the first
        spawn with an unauthenticated upstream request. And a static key
        sitting next to ``OAUTH_BEARER`` is a config mistake worth naming
        rather than silently ignoring — the operator believes one credential
        is in use while the request carries another.
        """
        if self.auth_style is UpstreamAuthStyle.OAUTH_BEARER:
            if self.api_key is not None:
                raise ValueError(
                    "an oauth-bearer upstream resolves its token per request, "
                    "so it must not also carry a static api_key"
                )
            return self
        if self.api_key is None:
            raise ValueError(
                f"an upstream using {self.auth_style.value!r} requires an api_key"
            )
        return self

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """Accept only fixed HTTP origins, without userinfo/query/fragment."""
        return normalise_upstream_base_url(value)


class GatewaySettings(BaseModel):
    """Validated runtime configuration with secrets excluded from repr output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    control_token: SecretStr
    upstreams: dict[ProviderBinding, UpstreamSettings]
    ledger_path: Path = Path(".hydraflow/gateway/requests.jsonl")
    body_dir: Path = Path(".hydraflow/gateway/bodies")
    body_capture_repo_slugs: frozenset[str] = frozenset()
    governed_repo_slugs: frozenset[str] = frozenset()
    """Repositories whose keys must be route-bound (ADR-0141 §D4).

    Empty by default, and deliberately server-owned: a caller cannot declare
    itself governed, and while this set names a repository, that repository's v1
    mints are refused and its unbound keys are turned away by the data plane.
    Arming it is a deployment act *after* the spawn side is already minting v2;
    disarming runs the other way. ADR-0141 states the ordering and why the
    operator-facing rollback is HydraFlow's own dial rather than this one.
    """
    accounts_file: Path | None = None
    """Server-owned multi-account registry document (ADR-0142), or ``None``.

    Absent by default, which is the whole of "a pool is opt-in": with no file
    this deployment has exactly ADR-0138's two compiled legacy accounts, every
    candidate list has one entry, and no fallback hop has anywhere to go. The
    file is restart-required on purpose — an account's credential and origin are
    deployment facts, and reloading them under live leases would let a key
    minted against one origin be served by another.
    """
    account_state_dir: Path = Path(".hydraflow/gateway/accounts")
    """Where the audited administrative overlay and its hash chain live."""
    max_fallback_hops: int = Field(default=1, ge=0)
    """The hard ceiling on bounded fallback. ``0`` refuses every hop.

    A ceiling rather than a target: the effective bound is always the smaller of
    this and the candidate list, so a pool can never be walked in a loop. One is
    the default because the shipped story is one primary and one backup, and a
    bound nobody chose should be the smallest one that still does something.
    """
    max_key_ttl_seconds: int = Field(default=86_400, gt=0)
    max_request_bytes: int = Field(default=33_554_432, gt=0)
    max_control_request_bytes: int = Field(default=16_384, gt=0)
    body_retention_seconds: int = Field(default=604_800, gt=0)
    reaper_interval_seconds: float = Field(default=30.0, gt=0)
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    write_timeout_seconds: float = Field(default=60.0, gt=0)
    pool_timeout_seconds: float = Field(default=10.0, gt=0)
    max_connections: int = Field(default=100, gt=0)
    max_keepalive_connections: int = Field(default=20, ge=0)

    def governs(self, repo_slug: str) -> bool:
        """Whether this deployment requires a route-bound key for *repo_slug*.

        Both sides are normalised at the moment of the decision rather than when
        the set is built, and that placement is the point. A field validator is
        skipped by ``model_copy`` and by any construction path that does not
        validate, so an authorization boundary resting on one would be as strong
        as however its settings object happened to be assembled. Normalising
        here also means neither the operator's spelling (``owner/repo``, the
        form ``.env.sample`` documents) nor the caller's (``MintKeyRequest``
        carries a free string) can open it. ADR-0141 §D4.
        """
        target = normalise_repo_slug(repo_slug)
        return any(
            normalise_repo_slug(declared) == target
            for declared in self.governed_repo_slugs
        )

    @field_validator("control_token")
    @classmethod
    def validate_control_token(cls, value: SecretStr) -> SecretStr:
        """Control credentials must compare safely and fit an HTTP header."""
        raw = value.get_secret_value()
        _validate_header_secret(raw, "control token")
        if len(raw.encode("ascii")) < 32:
            raise ValueError("control token must contain at least 32 ASCII bytes")
        return value

    @field_validator("upstreams")
    @classmethod
    def require_upstream(
        cls, value: dict[ProviderBinding, UpstreamSettings]
    ) -> dict[ProviderBinding, UpstreamSettings]:
        """Starting without any provider credential would create a false-ready tap."""
        if not value:
            raise ValueError("at least one gateway upstream must be configured")
        return value

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> GatewaySettings:
        """Load the deployable's explicit ``GATEWAY_*`` environment contract."""
        env = os.environ if environ is None else environ
        control_token = _required(env, "GATEWAY_CONTROL_TOKEN")
        upstreams: dict[ProviderBinding, UpstreamSettings] = {}
        if _anthropic_auth_mode(env) == "subscription":
            _add_subscription_upstream(upstreams, env)
        else:
            _add_upstream(
                upstreams,
                env,
                provider=ProviderBinding.ANTHROPIC,
                base_url_name="GATEWAY_ANTHROPIC_BASE_URL",
                api_key_name="GATEWAY_ANTHROPIC_API_KEY",
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        _add_upstream(
            upstreams,
            env,
            provider=ProviderBinding.ZAI_HARNESS,
            base_url_name="GATEWAY_ZAI_HARNESS_BASE_URL",
            api_key_name="GATEWAY_ZAI_HARNESS_API_KEY",
            auth_style=UpstreamAuthStyle.BEARER,
        )
        return cls(
            control_token=SecretStr(control_token),
            upstreams=upstreams,
            ledger_path=Path(
                env.get("GATEWAY_LEDGER_PATH", ".hydraflow/gateway/requests.jsonl")
            ),
            body_dir=Path(env.get("GATEWAY_BODY_DIR", ".hydraflow/gateway/bodies")),
            body_capture_repo_slugs=_repo_slug_allowlist(
                env.get("GATEWAY_BODY_CAPTURE_REPOS", "")
            ),
            governed_repo_slugs=_repo_slug_allowlist(
                env.get("GATEWAY_GOVERNED_REPOS", "")
            ),
            accounts_file=_optional_path(env, "GATEWAY_ACCOUNTS_FILE"),
            account_state_dir=Path(
                env.get("GATEWAY_ACCOUNT_STATE_DIR", ".hydraflow/gateway/accounts")
            ),
            max_fallback_hops=_non_negative_int(
                env, "GATEWAY_MAX_FALLBACK_HOPS", default=1
            ),
            max_key_ttl_seconds=_positive_int(
                env, "GATEWAY_MAX_KEY_TTL_SECONDS", default=86_400
            ),
            max_request_bytes=_positive_int(
                env, "GATEWAY_MAX_REQUEST_BYTES", default=33_554_432
            ),
            max_control_request_bytes=_positive_int(
                env, "GATEWAY_MAX_CONTROL_REQUEST_BYTES", default=16_384
            ),
            body_retention_seconds=_positive_int(
                env, "GATEWAY_BODY_RETENTION_SECONDS", default=604_800
            ),
        )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _positive_int(environ: Mapping[str, str], name: str, *, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _non_negative_int(environ: Mapping[str, str], name: str, *, default: int) -> int:
    """Parse a ceiling that may legitimately be zero.

    ``_positive_int`` refuses zero, which is right for a TTL or a byte ceiling
    and wrong for a fallback bound: ``0`` is the honest way to say "never hop",
    and forcing an operator to spell that as a kill-switch elsewhere would give
    the bound two places to look.
    """
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _optional_path(environ: Mapping[str, str], name: str) -> Path | None:
    """Return the configured path, or ``None`` when the variable is unset/blank."""
    raw = environ.get(name, "").strip()
    return Path(raw) if raw else None


def normalise_upstream_base_url(value: str) -> str:
    """Return one fixed http(s) origin, or raise. Shared by every upstream owner.

    Both a legacy environment pair and a file-declared account name an origin,
    and one predicate decides what an origin may be for both — a second copy is
    how a declared account eventually accepts a userinfo URL the legacy pair
    would have refused.
    """
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("upstream base_url must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("upstream base_url must not contain credentials or a query")
    return value.rstrip("/")


def _repo_slug_allowlist(raw: str) -> frozenset[str]:
    """Parse exact, case-insensitive repository slugs owned by the gateway.

    Exact, deliberately: ``body_capture_repo_slugs`` is matched against whatever
    ``MintKeyRequest.repo_slug`` carries, which is the caller's own runtime slug
    and is not guaranteed to be in any canonical form. Normalising here would
    silently stop authorising a repository whose slug does not round-trip.
    """
    return frozenset(slug.strip().lower() for slug in raw.split(",") if slug.strip())


def normalise_repo_slug(value: str) -> str:
    """Reduce a repository name to the one form the governed set is keyed on.

    ``owner/repo`` becomes ``owner-repo``; everything else is lower-cased and
    returned as it stands. Both the allow-list and every match against it go
    through here, because normalising only the operator's spelling would leave
    the boundary decided by the *caller's*: ``MintKeyRequest.repo_slug`` is a
    free string with no format constraint, so a caller sending the canonical
    form would miss a governed set holding the slug — and ADR-0141 §D4's whole
    claim is that the set is owned by the deployment and cannot be asserted by
    the caller.
    """
    # Deferred: ``routing_policy`` reaches back into ``accounts``, which reads
    # this module, so importing it at module scope closes a cycle.
    from hydraflow_gateway.routing_policy import canonicalize_repo, runtime_slug_for

    candidate = value.strip().lower()
    canonical = canonicalize_repo(candidate)
    return runtime_slug_for(canonical) if canonical is not None else candidate


#: The credential the Anthropic upstream authenticates with. ``api_key`` is the
#: default so an existing deployment is untouched by this option's existence.
_ANTHROPIC_AUTH_MODES: frozenset[str] = frozenset({"api_key", "subscription"})


def _anthropic_auth_mode(environ: Mapping[str, str]) -> str:
    """Which credential the Anthropic upstream uses, validated at boot."""
    mode = environ.get("GATEWAY_ANTHROPIC_AUTH_MODE", "api_key").strip() or "api_key"
    if mode not in _ANTHROPIC_AUTH_MODES:
        raise ValueError(
            "GATEWAY_ANTHROPIC_AUTH_MODE must be one of "
            f"{', '.join(sorted(_ANTHROPIC_AUTH_MODES))} (got {mode!r})"
        )
    return mode


def oauth_command(environ: Mapping[str, str], name: str) -> tuple[str, ...] | None:
    """A configured credential command as an argv tuple, or ``None``.

    Split with ``shlex`` and executed as an argument vector, never through a
    shell: the command's OUTPUT is a live credential, and a shell would put it
    one redirection away from a log.
    """
    raw = environ.get(name, "").strip()
    if not raw:
        return None
    parts = tuple(shlex.split(raw))
    if not parts:
        raise ValueError(f"{name} is set but parsed to an empty command")
    return parts


def _add_subscription_upstream(
    upstreams: dict[ProviderBinding, UpstreamSettings],
    environ: Mapping[str, str],
) -> None:
    """Register the Anthropic upstream on the subscription (OAuth) lane.

    ``GATEWAY_ANTHROPIC_API_KEY`` must be absent here. Accepting both would
    leave two credentials configured and only one in use, which is the state an
    operator is least able to debug from the outside.
    """
    base_url = environ.get("GATEWAY_ANTHROPIC_BASE_URL", "").strip()
    if not base_url:
        raise ValueError(
            "GATEWAY_ANTHROPIC_AUTH_MODE=subscription still needs "
            "GATEWAY_ANTHROPIC_BASE_URL — the lane changes the credential, "
            "not the destination"
        )
    if environ.get("GATEWAY_ANTHROPIC_API_KEY", "").strip():
        raise ValueError(
            "GATEWAY_ANTHROPIC_API_KEY is set while "
            "GATEWAY_ANTHROPIC_AUTH_MODE=subscription; unset one so it is "
            "unambiguous which credential this gateway presents"
        )
    upstreams[ProviderBinding.ANTHROPIC] = UpstreamSettings(
        base_url=base_url,
        api_key=None,
        auth_style=UpstreamAuthStyle.OAUTH_BEARER,
    )


def _add_upstream(
    upstreams: dict[ProviderBinding, UpstreamSettings],
    environ: Mapping[str, str],
    *,
    provider: ProviderBinding,
    base_url_name: str,
    api_key_name: str,
    auth_style: UpstreamAuthStyle,
) -> None:
    base_url = environ.get(base_url_name, "").strip()
    api_key = environ.get(api_key_name, "").strip()
    if bool(base_url) != bool(api_key):
        raise ValueError(f"{base_url_name} and {api_key_name} must be set together")
    if not base_url:
        return
    upstreams[provider] = UpstreamSettings(
        base_url=base_url,
        api_key=SecretStr(api_key),
        auth_style=auth_style,
    )


def _validate_header_secret(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} must not be empty")
    if "\r" in value or "\n" in value:
        raise ValueError(f"{label} must not contain newlines")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be ASCII") from exc
