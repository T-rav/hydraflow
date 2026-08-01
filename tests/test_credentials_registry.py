"""build_credentials reads its env keys from an enumerable registry (#10885)."""

from __future__ import annotations

import pytest

from config import (
    CREDENTIAL_ENV_KEYS,
    HydraFlowConfig,
    build_credentials,
    declared_env_keys,
)


def test_credential_env_keys_are_all_declared() -> None:
    # The whole credential surface must be reachable via declared_env_keys() so
    # test isolation and .env/doc generators enumerate it instead of hardcoding.
    assert declared_env_keys() >= CREDENTIAL_ENV_KEYS


def test_unprefixed_github_keys_are_declared() -> None:
    # These used to be hand-listed in conftest's scrub set; the registry now
    # carries them (#10885).
    assert {"GH_TOKEN", "GITHUB_TOKEN"} <= declared_env_keys()


def test_gh_token_priority_order_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    # The refactored loop must keep the old or-chain priority.
    monkeypatch.setenv("GITHUB_TOKEN", "lowest")
    monkeypatch.setenv("GH_TOKEN", "middle")
    monkeypatch.setenv("HYDRAFLOW_GH_TOKEN", "highest")
    assert build_credentials(HydraFlowConfig()).gh_token == "highest"


def test_gh_token_falls_through_to_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "middle")
    monkeypatch.setenv("GITHUB_TOKEN", "lowest")
    assert build_credentials(HydraFlowConfig()).gh_token == "middle"


def test_whatsapp_fields_read_from_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_WHATSAPP_TOKEN", "wa-token")
    monkeypatch.setenv("HYDRAFLOW_WHATSAPP_PHONE_ID", "wa-phone")
    creds = build_credentials(HydraFlowConfig())
    assert creds.whatsapp_token == "wa-token"
    assert creds.whatsapp_phone_id == "wa-phone"
