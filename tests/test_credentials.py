"""Tests for the Credentials model and build_credentials() factory."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from config import Credentials, build_credentials
from tests.helpers import ConfigFactory, CredentialsFactory


class TestCredentialsModel:
    """Credentials model field defaults and immutability."""

    def test_defaults_are_empty_strings(self) -> None:
        creds = Credentials()
        assert creds.gh_token == ""

    def test_frozen_rejects_mutation(self) -> None:
        creds = Credentials(gh_token="tok")
        with pytest.raises(ValidationError):
            creds.gh_token = "other"  # type: ignore[misc]

    def test_explicit_values_stored(self) -> None:
        creds = Credentials(
            gh_token="gh-tok",
        )
        assert creds.gh_token == "gh-tok"


class TestCredentialsFactory:
    """CredentialsFactory test helper produces valid instances."""

    def test_factory_defaults(self) -> None:
        creds = CredentialsFactory.create()
        assert isinstance(creds, Credentials)
        assert creds.gh_token == ""

    def test_factory_overrides(self) -> None:
        creds = CredentialsFactory.create(gh_token="tok")
        assert creds.gh_token == "tok"


class TestBuildCredentials:
    """build_credentials() resolves tokens from env vars."""

    _CLEARED_ENV = {
        "HYDRAFLOW_GH_TOKEN": "",
        "GH_TOKEN": "",
        "GITHUB_TOKEN": "",
        "HYDRAFLOW_HINDSIGHT_URL": "",
        "HYDRAFLOW_HINDSIGHT_API_KEY": "",
    }

    def test_gh_token_priority_hydraflow(self, tmp_path: Path) -> None:
        """HYDRAFLOW_GH_TOKEN wins over GH_TOKEN and GITHUB_TOKEN."""
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {**self._CLEARED_ENV, "HYDRAFLOW_GH_TOKEN": "hf", "GH_TOKEN": "gh"}
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == "hf"

    def test_gh_token_priority_gh_token(self, tmp_path: Path) -> None:
        """GH_TOKEN is used when HYDRAFLOW_GH_TOKEN is empty."""
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {**self._CLEARED_ENV, "GH_TOKEN": "gh"}
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == "gh"

    def test_gh_token_priority_github_token(self, tmp_path: Path) -> None:
        """GITHUB_TOKEN is used when higher-priority vars are empty."""
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {**self._CLEARED_ENV, "GITHUB_TOKEN": "gha"}
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == "gha"

    def test_gh_token_empty_when_no_env(self, tmp_path: Path) -> None:
        """gh_token is empty when no env vars set and no .env file."""
        config = ConfigFactory.create(repo_root=tmp_path)
        with patch.dict(os.environ, self._CLEARED_ENV, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == ""

    # test_reads_hindsight_fields removed in Phase 3 cutover — Hindsight
    # credentials deleted from the Credentials model.
    # test_reads_whatsapp_fields removed with the WhatsApp bridge — the
    # Credentials model no longer carries those fields.


class TestHydraFlowConfigExcludesCredentials:
    """HydraFlowConfig no longer carries credential fields."""

    def test_model_dump_has_no_credential_keys(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        dumped = config.model_dump()
        # Derived, not spelled. The hardcoded list this replaces still named
        # four WhatsApp fields after that bridge was deleted — so it was
        # asserting that config does not carry fields which no longer exist
        # anywhere, while a NEWLY added credential would have gone unchecked.
        credential_keys = set(Credentials.model_fields)
        leaked = credential_keys & set(dumped.keys())
        assert not leaked, f"Credential fields still on HydraFlowConfig: {leaked}"
