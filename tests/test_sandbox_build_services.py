"""`sandbox_scenario.build_services()` — the env override CI uses to skip a build.

CI pre-builds the `hydraflow` service's image (Dockerfile.agent, ~3 GB) with
buildx against a GHCR layer cache and loads it under the tag compose pins. The
runner daemon's own builder does NOT share buildx's cache, so if the harness
then rebuilt `hydraflow` the cached layers would be silently discarded and the
lane would pay the full ~10 min anyway — green, correct, and no faster (#11601).

The override is what prevents that. Its failure modes are both silent, so both
are pinned here: an unset/blank value must fall back to the FULL list (local
dev and every non-opted-in caller unchanged), and a typo must raise rather than
skip a build and resurface as a confusing "image not found" three steps later.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.sandbox_scenario import (  # noqa: E402
    BUILD_SERVICES_ENV,
    DEFAULT_BUILD_SERVICES,
    build_services,
)


class TestDefault:
    def test_unset_returns_the_full_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(BUILD_SERVICES_ENV, raising=False)
        assert build_services() == DEFAULT_BUILD_SERVICES

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_blank_falls_back_to_the_full_list(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        # A workflow that computes the value and produces "" must not
        # accidentally mean "build nothing" — that boots against a stale image.
        monkeypatch.setenv(BUILD_SERVICES_ENV, blank)
        assert build_services() == DEFAULT_BUILD_SERVICES

    def test_default_list_includes_the_agent_service(self) -> None:
        # Sanity: the whole point is that `hydraflow` is in the default list
        # and can be taken OUT of it.
        assert "hydraflow" in DEFAULT_BUILD_SERVICES


class TestOverride:
    def test_narrowing_drops_the_prebuilt_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BUILD_SERVICES_ENV, "fake-llm-http gateway ui playwright")
        services = build_services()
        assert "hydraflow" not in services
        assert services == ("fake-llm-http", "gateway", "ui", "playwright")

    def test_extra_whitespace_is_tolerated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BUILD_SERVICES_ENV, "  gateway   ui  ")
        assert build_services() == ("gateway", "ui")

    def test_unknown_service_raises_instead_of_silently_skipping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BUILD_SERVICES_ENV, "gateway hydrflow")
        with pytest.raises(ValueError) as excinfo:
            build_services()
        assert "hydrflow" in str(excinfo.value)

    def test_error_names_the_valid_services(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BUILD_SERVICES_ENV, "nope")
        with pytest.raises(ValueError) as excinfo:
            build_services()
        for service in DEFAULT_BUILD_SERVICES:
            assert service in str(excinfo.value)
