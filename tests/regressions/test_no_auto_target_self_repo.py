"""The factory must not adopt the checkout it boots from as its pipeline target.

`_resolve_repo_and_identity` used to fall back to the git remote of the repo
the process started in. In practice that fallback only ever fired for one repo
— HydraFlow itself — because no other repo is ever the checkout. So `make
factory` run from a HydraFlow clone silently began triaging HydraFlow's own
issues, which is exactly the wrong default while an operator is standing in
that clone trying to point the factory somewhere else.

Detection still runs, but only to explain the idle state. It no longer selects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from config import HydraFlowConfig, _resolve_repo_and_identity

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _no_inherited_target(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The ambient env must not decide these outcomes."""
    monkeypatch.delenv("HYDRAFLOW_GITHUB_REPO", raising=False)
    yield


def _config_in(repo_root: Path) -> HydraFlowConfig:
    cfg = HydraFlowConfig()
    cfg.repo = ""
    cfg.repo_root = repo_root
    return cfg


class TestTheCheckoutIsNotATarget:
    def test_a_detectable_remote_is_not_adopted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The whole point: detection succeeds, and is still not used."""
        monkeypatch.setattr("config._detect_repo_slug", lambda _root: "T-rav/hydraflow")

        cfg = _config_in(tmp_path)
        _resolve_repo_and_identity(cfg)

        assert cfg.repo == "", (
            "the checkout's own remote was adopted as the pipeline target — the "
            "factory will start working whatever repo it happens to live in"
        )

    def test_an_explicitly_named_repo_is_still_honoured(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Removing the fallback must not remove the feature."""
        monkeypatch.setenv("HYDRAFLOW_GITHUB_REPO", "T-rav/other-project")
        monkeypatch.setattr("config._detect_repo_slug", lambda _root: "T-rav/hydraflow")

        cfg = _config_in(tmp_path)
        _resolve_repo_and_identity(cfg)

        assert cfg.repo == "T-rav/other-project"

    def test_the_idle_state_says_what_it_detected_and_did_not_take(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An operator must not have to read source to learn why nothing runs.

        A silent empty target is indistinguishable from a broken factory.
        """
        monkeypatch.setattr("config._detect_repo_slug", lambda _root: "T-rav/hydraflow")

        with caplog.at_level(logging.WARNING, logger="hydraflow.config"):
            _resolve_repo_and_identity(_config_in(tmp_path))

        msg = caplog.text
        assert "HYDRAFLOW_GITHUB_REPO" in msg, "the fix is not named"
        assert "T-rav/hydraflow" in msg, "the detected-but-unused remote is not named"
        assert "NOT targeted automatically" in msg


class TestPipelineLoopsIdleWithoutATarget:
    """All five pipeline loops funnel through one wrapper; guard it once."""

    @staticmethod
    def _mixin() -> object:
        from orchestrator_loops import OrchestratorLoopsMixin

        return OrchestratorLoopsMixin

    def test_the_latch_defaults_falsy_so_the_warning_can_fire(self) -> None:
        """A TYPE_CHECKING seam stub here would be truthy and mute the warning.

        This repo has shipped that exact bug: a runtime ``...`` stub winning the
        MRO. The latch must be a real class-level default.
        """
        latch = self._mixin()._warned_no_pipeline_target  # type: ignore[attr-defined]

        assert latch is False, f"latch is {latch!r} — a truthy default mutes the warning"

    @pytest.mark.asyncio
    async def test_an_empty_slug_skips_without_calling_the_work_function(self) -> None:
        """The guard must short-circuit BEFORE the pipeline does any GitHub work."""
        from orchestrator_loops import OrchestratorLoopsMixin

        called = False

        async def _inner() -> bool:
            nonlocal called
            called = True
            return True

        holder = OrchestratorLoopsMixin()
        result = await holder._pipeline_work_wrapper("", _inner)

        assert called is False, (
            "the work function ran with an empty repo slug — the pipeline is "
            "polling GitHub for a repo nobody named"
        )
        assert result is False, "a falsy return is what makes _polling_loop sleep"

    @pytest.mark.asyncio
    async def test_a_named_slug_still_reaches_the_work_function(self) -> None:
        """Guard the guard: skipping everything would pass the test above."""
        from orchestrator_loops import OrchestratorLoopsMixin

        called = False

        async def _inner() -> bool:
            nonlocal called
            called = True
            return True

        holder = OrchestratorLoopsMixin()
        holder._is_slug_blocked = lambda _slug: False  # type: ignore[method-assign]
        result = await holder._pipeline_work_wrapper("T-rav/other", _inner)

        assert called is True, "a named repo did not reach the pipeline work function"
        assert result is True
