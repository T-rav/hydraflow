"""Issue #10658: per-repo config overrides are written to ``repos.json`` but
never read back at boot.

An operator edits a per-repo setting via ``PATCH /api/control/config?repo=X``,
which persists the edit into ``RepoRecord.overrides`` in
``data_root/repos.json`` (``repo_store.update_overrides``). But the boot
repo-restore path in ``server.py`` rebuilt each repo's ``HydraFlowConfig`` via
``load_runtime_config`` *without* the stored overrides — so the operator's edit
survived only in memory until the next restart, then silently vanished.

Fix: on restore (and when re-adding a known repo) merge the stored, validated
overrides into the ``load_runtime_config`` overrides, layered **under** the
structural keys (``repo_root`` / ``repo`` / ``repo_data_class``) so a stale or
hand-edited stored value can never hijack repo identity or the CH-6 data-class
governance merge.

Precedence follows the sibling #10657 model: an explicitly supplied value (here
the persisted operator edit) beats a matching ``HYDRAFLOW_*`` env var, while the
env var still wins when no stored edit exists. This test must never invert that.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import server
from config import HydraFlowConfig
from repo_store import RepoRecord, RepoRegistryStore
from runtime_config import valid_stored_overrides


class _RecordingRegistry:
    """Minimal ``RepoRuntimeRegistry`` stand-in that records the configs handed
    to ``register`` without building a heavyweight ``RepoRuntime``."""

    def __init__(self) -> None:
        self.registered: list[HydraFlowConfig] = []

    def __contains__(self, slug: str) -> bool:  # nothing pre-registered
        return False

    async def register(self, config: HydraFlowConfig) -> HydraFlowConfig:
        self.registered.append(config)
        return config


@pytest.fixture(autouse=True)
def _hermetic_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point ``load_runtime_config`` at a non-existent config file so no ambient
    ``.hydraflow/config.json`` bleeds into these assertions."""
    monkeypatch.setattr(
        "runtime_config.DEFAULT_CONFIG_PATH", tmp_path / "no-such-config.json"
    )


def _store_with_repo(
    tmp_path: Path, overrides: dict[str, object], *, slug: str = "acme/widgets"
) -> tuple[RepoRegistryStore, Path]:
    repo_path = tmp_path / "widgets"
    repo_path.mkdir(exist_ok=True)
    data_root = tmp_path / "data"
    data_root.mkdir(exist_ok=True)
    store = RepoRegistryStore(data_root)
    store.upsert(
        RepoRecord(slug=slug, repo=slug, path=str(repo_path), overrides=overrides)
    )
    return store, repo_path


# --- valid_stored_overrides helper -----------------------------------------


def test_valid_stored_overrides_keeps_known_valid_field() -> None:
    assert valid_stored_overrides({"max_workers": 7}, "acme/widgets") == {
        "max_workers": 7
    }


def test_valid_stored_overrides_drops_unknown_key() -> None:
    assert valid_stored_overrides({"not_a_real_field": 1}, "acme/widgets") == {}


def test_valid_stored_overrides_drops_out_of_range_value() -> None:
    # ``max_workers`` is constrained ``ge=1``; a stored 0 is unusable and must
    # be dropped so the field falls back to its default rather than raising.
    assert valid_stored_overrides({"max_workers": 0}, "acme/widgets") == {}


def test_valid_stored_overrides_excludes_structural_keys() -> None:
    result = valid_stored_overrides(
        {
            "repo_root": "/tmp/evil",
            "repo": "evil/x",
            "repo_data_class": "public-code",
            "max_workers": 5,
        },
        "acme/widgets",
    )
    assert result == {"max_workers": 5}


# --- restore path: the boot read gap ---------------------------------------


@pytest.mark.asyncio
async def test_restore_reproduces_stored_override(tmp_path: Path) -> None:
    store, _ = _store_with_repo(tmp_path, {"max_workers": 7})
    registry = _RecordingRegistry()

    await server._restore_registered_repos(store, registry)

    assert len(registry.registered) == 1
    assert registry.registered[0].max_workers == 7


@pytest.mark.asyncio
async def test_restore_structural_key_wins_over_stored(tmp_path: Path) -> None:
    # A hand-edited stored ``repo_root`` must never hijack the record's real path.
    store, repo_path = _store_with_repo(tmp_path, {"repo_root": "/nonexistent/evil"})
    registry = _RecordingRegistry()

    await server._restore_registered_repos(store, registry)

    assert len(registry.registered) == 1
    assert Path(registry.registered[0].repo_root) == repo_path.resolve()


@pytest.mark.asyncio
async def test_restore_degrades_on_invalid_override(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store, _ = _store_with_repo(tmp_path, {"max_workers": 0})
    registry = _RecordingRegistry()

    with caplog.at_level("WARNING"):
        await server._restore_registered_repos(store, registry)

    # The repo is still restored (never skipped); the bad field uses its default.
    assert len(registry.registered) == 1
    assert registry.registered[0].max_workers == 1
    assert "acme/widgets" in caplog.text


@pytest.mark.asyncio
async def test_restore_stored_override_beats_env(tmp_path: Path) -> None:
    store, _ = _store_with_repo(tmp_path, {"max_review_fix_attempts": 1})
    registry = _RecordingRegistry()

    with patch.dict(
        os.environ, {"HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS": "4"}, clear=False
    ):
        await server._restore_registered_repos(store, registry)

    # Explicit stored edit wins over the env var (#10657 precedence, not inverted).
    assert registry.registered[0].max_review_fix_attempts == 1


@pytest.mark.asyncio
async def test_restore_env_still_applies_without_stored_override(
    tmp_path: Path,
) -> None:
    store, _ = _store_with_repo(tmp_path, {})
    registry = _RecordingRegistry()

    with patch.dict(
        os.environ, {"HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS": "4"}, clear=False
    ):
        await server._restore_registered_repos(store, registry)

    # No stored edit → the env var still wins, as it did before the fix.
    assert registry.registered[0].max_review_fix_attempts == 4


# --- write -> read round trip (PATCH edit, then restart) -------------------


@pytest.mark.asyncio
async def test_patch_edit_then_restore_round_trip(event_bus, tmp_path: Path) -> None:
    """The operator-facing guarantee: an edit made through
    ``PATCH /api/control/config?repo=X`` is reproduced on that repo's config
    after a simulated restart (fresh registry, same repo store)."""
    from state import StateTracker
    from tests.helpers import ConfigFactory, find_endpoint, make_dashboard_router

    repo_path = tmp_path / "widgets"
    repo_path.mkdir()
    repo_cfg = ConfigFactory.create(
        repo="acme/widgets",
        repo_root=repo_path,
        workspace_base=tmp_path / "widgets-wt",
        state_file=tmp_path / "widgets-state.json",
    )
    runtime_state = StateTracker(repo_cfg.state_file)

    class _StubRuntime:
        def __init__(self, cfg, bus, tracker) -> None:
            self.config = cfg
            self.event_bus = bus
            self.state = tracker
            self._orchestrator = None
            self.slug = cfg.repo_slug
            self._running = False

        @property
        def orchestrator(self):
            return self._orchestrator

    runtime = _StubRuntime(repo_cfg, event_bus, runtime_state)

    data_root = tmp_path / "data"
    data_root.mkdir()
    store = RepoRegistryStore(data_root)
    store.upsert(
        RepoRecord(slug=runtime.slug, repo=repo_cfg.repo, path=str(repo_cfg.repo_root))
    )

    class _StubRegistry:
        def __init__(self, rt) -> None:
            self._rt = rt

        def get(self, slug):
            return self._rt if slug == self._rt.slug else None

        def __contains__(self, slug: str) -> bool:
            return False

        @property
        def all(self):
            return [self._rt]

        def remove(self, slug):
            return None

    base_cfg = ConfigFactory.create(
        repo_root=tmp_path / "base-repo",
        workspace_base=tmp_path / "base-wt",
        state_file=tmp_path / "base-state.json",
    )
    router, _ = make_dashboard_router(
        base_cfg,
        event_bus,
        runtime_state,
        tmp_path,
        registry=_StubRegistry(runtime),
        default_repo_slug=runtime.slug,
        repo_store=store,
    )
    patch_config = find_endpoint(router, "/api/control/config")
    assert patch_config is not None

    response = await patch_config({"max_workers": 6}, repo=runtime.slug)
    assert json.loads(response.body)["status"] == "ok"
    assert store.load()[0].overrides["max_workers"] == 6

    # --- simulate restart: a fresh registry restores from the same store ---
    registry = _RecordingRegistry()
    await server._restore_registered_repos(store, registry)

    assert len(registry.registered) == 1
    assert registry.registered[0].max_workers == 6
