"""Environment-backed settings for the LLM gateway deployable."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from hydraflow_gateway.models import ProviderBinding


class UpstreamAuthStyle(StrEnum):
    """Supported provider credential header styles."""

    X_API_KEY = "x-api-key"
    BEARER = "bearer"


class UpstreamSettings(BaseModel):
    """Fixed, server-owned upstream location and provider credential."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    api_key: SecretStr
    auth_style: UpstreamAuthStyle

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        """Provider credentials must be non-empty ASCII header values."""
        _validate_header_secret(value.get_secret_value(), "provider API key")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """Accept only fixed HTTP origins, without userinfo/query/fragment."""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("upstream base_url must be an http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "upstream base_url must not contain credentials or a query"
            )
        return value.rstrip("/")


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


def _repo_slug_allowlist(raw: str) -> frozenset[str]:
    """Parse exact, case-insensitive repository slugs owned by the gateway."""
    return frozenset(slug.strip().lower() for slug in raw.split(",") if slug.strip())


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
