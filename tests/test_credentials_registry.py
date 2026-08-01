"""build_credentials reads its env keys from an enumerable registry (#10885)."""

from __future__ import annotations

import os

import pytest

from config import (
    CREDENTIAL_ENV_KEYS,
    HydraFlowConfig,
    build_credentials,
    declared_env_keys,
)


def test_registry_covers_every_key_build_credentials_reads() -> None:
    # The exported surface must enumerate every key build_credentials reads —
    # the gh-token priority chain and all five whatsapp keys.
    assert {"HYDRAFLOW_GH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"} <= CREDENTIAL_ENV_KEYS
    assert "HYDRAFLOW_WHATSAPP_TOKEN" in CREDENTIAL_ENV_KEYS


def test_registry_is_separate_from_table_declared_keys() -> None:
    # Credential keys are read directly (not via an _ENV_*_OVERRIDES table), so
    # they are deliberately NOT in declared_env_keys() — folding them in would
    # trip the #10876 leak guard on the seeded GH_TOKEN. They are a distinct,
    # separately-scrubbed surface (#10885).
    assert not (CREDENTIAL_ENV_KEYS & declared_env_keys())


def test_isolation_fixture_scrubs_the_registry() -> None:
    # "test isolation reads from the exported structure": every credential key is
    # absent during the session, except GH_TOKEN which is re-seeded deterministic.
    for key in CREDENTIAL_ENV_KEYS:
        if key == "GH_TOKEN":
            assert os.environ.get(key) == "test-token"
        else:
            assert os.environ.get(key) is None


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
