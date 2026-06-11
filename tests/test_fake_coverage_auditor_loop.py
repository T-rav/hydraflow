"""Tests for FakeCoverageAuditorLoop (spec §4.7)."""

from __future__ import annotations

import asyncio
import json  # noqa: F401 — used by appended tick-behavior tests below
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml  # noqa: F401 — used by appended tick-behavior tests below

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from fake_coverage_auditor_loop import (
    _FAKE_TO_CASSETTE_DIR,
    FakeCoverageAuditorLoop,
    _is_helper,
    catalog_cassette_methods,
    catalog_fake_methods,
)


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", repo_root=tmp_path
    )
    state = MagicMock()
    state.get_fake_coverage_last_known.return_value = {}
    state.get_fake_coverage_attempts.return_value = 0
    # Default: returns 1 (< _MAX_ATTEMPTS=3) so gap filing path is taken.
    # Escalation tests override this explicitly.
    state.inc_fake_coverage_attempts.return_value = 1
    # #8986 — rollup-issue tracking: default no tracked rollup.
    state.get_fake_coverage_rollup_issue.return_value = None
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.update_issue_body = AsyncMock(return_value=None)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "fake_coverage_auditor"
    assert loop._get_default_interval() == 604800


def test_catalog_fake_methods_splits_surface_vs_helper(tmp_path: Path) -> None:
    fake_dir = tmp_path / "fakes"
    fake_dir.mkdir()
    (fake_dir / "fake_github.py").write_text(
        "from dataclasses import dataclass\n\n"
        "class FakeGitHub:\n"
        "    async def create_issue(self, title, body, labels): ...\n"
        "    async def close_issue(self, num): ...\n"
        "    def script_ci(self, events): ...\n"
        "    def fail_service(self, reason): ...\n"
        "    def _private(self): ...\n"
    )

    cat = catalog_fake_methods(fake_dir)
    assert "FakeGitHub" in cat
    surface = set(cat["FakeGitHub"]["adapter-surface"])
    helpers = set(cat["FakeGitHub"]["test-helper"])
    assert surface == {"create_issue", "close_issue"}
    assert helpers == {"script_ci", "fail_service"}


def test_catalog_fake_methods_fake_git_script_api_helpers_are_test_helpers(
    tmp_path: Path,
) -> None:
    """reject_next_push / set_corrupted_config / active_worktrees must land in test-helper."""
    fake_dir = tmp_path / "fakes"
    fake_dir.mkdir()
    (fake_dir / "fake_git.py").write_text(
        "class FakeGit:\n"
        "    def reject_next_push(self): ...\n"
        "    def set_corrupted_config(self, cwd, *, key, value): ...\n"
        "    def active_worktrees(self): ...\n"
        "    async def push(self, cwd, remote, branch): ...\n"
        "    async def commit(self, cwd, message): ...\n"
    )

    cat = catalog_fake_methods(fake_dir)
    assert "FakeGit" in cat
    surface = set(cat["FakeGit"]["adapter-surface"])
    helpers = set(cat["FakeGit"]["test-helper"])

    for method in ("reject_next_push", "set_corrupted_config", "active_worktrees"):
        assert method not in surface, f"{method} must not be adapter-surface"
        assert method in helpers, f"{method} must be in test-helper"

    assert "push" in surface
    assert "commit" in surface


def test_catalog_cassette_methods_reads_input_command(tmp_path: Path) -> None:
    import yaml

    cassettes = tmp_path / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    (cassettes / "create_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
    )
    (cassettes / "close_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "close_issue"}, "output": {}})
    )
    methods = catalog_cassette_methods(cassettes)
    assert methods == {"create_issue", "close_issue"}


async def test_do_work_files_surface_gap(loop_env, monkeypatch, tmp_path) -> None:
    """Un-cassetted public method → one ``adapter-surface`` rollup issue."""
    cfg, state, pr, dedup = loop_env
    state.get_fake_coverage_rollup_issue.return_value = None
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self, title): ...\n"
        "    async def close_issue(self, n): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    # Note: plan draft used .json; real catalog_cassette_methods scans *.yaml
    # per §4.2 cassette schema. See plan deviation note (C4).
    (cassettes / "create_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
    )
    # close_issue uncassetted → expect one adapter-surface gap.

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-adapter-surface" in labels
    assert "hydraflow-fake-coverage-gap" in labels


async def test_do_work_skips_surface_audit_for_unmapped_fake(
    loop_env, monkeypatch, tmp_path
) -> None:
    """A fake NOT registered in ``_FAKE_TO_CASSETTE_DIR`` must not file an
    adapter-surface gap.

    Internal-port fakes (a clock, in-memory stores, assertion helpers) have no
    recordable external I/O, so no cassette can ever cover them. The empty-string
    fallback (``_FAKE_TO_CASSETTE_DIR.get(fake, "")``) previously audited such a
    fake against the cassette *root* — flagging every public method as a false
    gap (the dominant fake-coverage false positive).
    """
    cfg, state, pr, dedup = loop_env
    state.get_fake_coverage_rollup_issue.return_value = None
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    # FakeClock is not in _FAKE_TO_CASSETTE_DIR; now/monotonic are surface methods.
    (fake_dir / "fake_clock.py").write_text(
        "class FakeClock:\n    def now(self): ...\n    def monotonic(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes").mkdir(parents=True)

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()

    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_do_work_files_helper_gap(loop_env, monkeypatch, tmp_path) -> None:
    """Un-exercised ``script_*`` helper → one ``test-helper`` rollup issue."""
    cfg, state, pr, dedup = loop_env
    state.get_fake_coverage_rollup_issue.return_value = None
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_docker.py").write_text(
        "class FakeDocker:\n    def script_run(self, events): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "docker"
    cassettes.mkdir(parents=True)

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_grep(helper):
        return False  # no scenario calls the helper

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_grep_scenario_for_helper", fake_grep)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-test-helper" in labels
    title = pr.create_issue.await_args.args[0]
    assert "FakeDocker" in title
    body = pr.create_issue.await_args.args[1]
    assert "script_run" in body


async def test_escalation_fires_after_three_attempts(
    loop_env, monkeypatch, tmp_path
) -> None:
    """3rd attempt at a stuck ``(fake, kind)`` rollup → ``hitl-escalation``."""
    cfg, state, pr, dedup = loop_env
    state.inc_fake_coverage_attempts.return_value = 3
    state.get_fake_coverage_rollup_issue.return_value = None
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n    async def missing(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(
        parents=True
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    # The escalation issue is the only one created (no rollup filed when
    # attempts >= _MAX_ATTEMPTS).
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-hitl-escalation" in labels
    assert "hydraflow-fake-coverage-stuck" in labels
    # Attempt counter keyed by ``{fake}:{kind}``, not ``{fake}.{method}:{kind}``.
    state.inc_fake_coverage_attempts.assert_called_with("FakeGitHub:adapter-surface")


async def test_close_reconcile_clears_dedup_on_closed_escalation(
    loop_env, monkeypatch, tmp_path
) -> None:
    """Closed ``fake-coverage-stuck`` issues clear their dedup key + attempts."""
    cfg, state, pr, dedup = loop_env
    # New rollup key shape: ``{fake}:{kind}``.
    stuck_key = "fake_coverage_auditor:FakeGitHub:adapter-surface"
    current = {stuck_key, "fake_coverage_auditor:FakeDocker:adapter-surface"}
    dedup.get.return_value = current

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    closed_payload = json.dumps(
        [{"title": "HITL: fake coverage gap FakeGitHub:adapter-surface ..."}]
    ).encode()

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return closed_payload, b""

    async def fake_exec(*_args, **_kwargs):
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await loop._reconcile_closed_escalations()

    # Only the closed key was cleared; the other key remains.
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert stuck_key not in remaining
    assert "fake_coverage_auditor:FakeDocker:adapter-surface" in remaining
    state.clear_fake_coverage_attempts.assert_called_once_with(
        "FakeGitHub:adapter-surface"
    )


async def test_all_emitted_labels_are_registered_hydraflow_labels(loop_env) -> None:
    """Every label the auditor passes to ``pr.create_issue`` must be a registered
    HydraFlow lifecycle label, so ``make ensure-labels`` provisions it on the repo.

    Regression for "could not add label: 'fake-coverage-gap' not found" — bare
    labels were silently failing every gap-issue creation. See PR for context.
    """
    from prep import HYDRAFLOW_LABELS

    cfg, state, pr, dedup = loop_env
    registered: set[str] = set()
    for cfg_field, *_ in HYDRAFLOW_LABELS:
        registered.update(getattr(cfg, cfg_field))

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    await loop._file_surface_gap("FakeGitHub", ["create_issue"])
    await loop._file_helper_gap("FakeDocker", ["script_run"])
    await loop._file_escalation("FakeGitHub:adapter-surface", 3)

    emitted: set[str] = set()
    for call in pr.create_issue.await_args_list:
        emitted.update(call.args[2])

    unregistered = emitted - registered
    assert not unregistered, (
        f"auditor emits unregistered labels: {sorted(unregistered)}"
    )


@pytest.mark.asyncio
async def test_kill_switch_short_circuits_do_work(loop_env) -> None:
    """Disabled kill-switch → _do_work returns `disabled` and skips reconcile (ADR-0049)."""
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "fake_coverage_auditor",
    )
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()


def test_is_helper_returns_true_for_class_overrides() -> None:
    """_FAKE_HELPER_OVERRIDES entries classify as test-helper regardless of prefix/name."""
    assert _is_helper("clear_rate_limit", "FakeGitHub") is True
    assert _is_helper("set_rate_limit_mode", "FakeGitHub") is True


def test_is_helper_override_does_not_affect_other_classes() -> None:
    """Override is class-scoped — same method name on another fake is adapter-surface."""
    assert _is_helper("clear_rate_limit", "FakeDocker") is False
    assert _is_helper("clear_rate_limit", "") is False


def test_catalog_fake_methods_applies_class_overrides(tmp_path: Path) -> None:
    """Methods in _FAKE_HELPER_OVERRIDES land in test-helper, not adapter-surface."""
    fake_dir = tmp_path / "fakes"
    fake_dir.mkdir()
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self, title): ...\n"
        "    def clear_rate_limit(self): ...\n"
        "    def set_rate_limit_mode(self, *, remaining=0): ...\n"
    )
    cat = catalog_fake_methods(fake_dir)
    assert "FakeGitHub" in cat
    surface = set(cat["FakeGitHub"]["adapter-surface"])
    helpers = set(cat["FakeGitHub"]["test-helper"])
    assert "clear_rate_limit" not in surface
    assert "clear_rate_limit" in helpers
    assert "set_rate_limit_mode" not in surface
    assert "set_rate_limit_mode" in helpers
    assert "create_issue" in surface


def test_fake_to_cassette_dir_keys_match_real_classes() -> None:
    """Every key in _FAKE_TO_CASSETTE_DIR must be a real Fake* class in the fakes dir.

    Guards against case-mismatch regressions (e.g. 'FakeFs' vs actual 'FakeFS')
    and stale entries for removed classes.
    """
    import ast as _ast
    from pathlib import Path as _Path

    from fake_coverage_auditor_loop import _FAKE_TO_CASSETTE_DIR

    repo_root = _Path(__file__).parent.parent
    fake_dir = repo_root / "src" / "mockworld" / "fakes"
    actual: set[str] = set()
    for path in fake_dir.glob("*.py"):
        if path.name.startswith("test_") or path.name == "__init__.py":
            continue
        try:
            tree = _ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ClassDef) and node.name.startswith("Fake"):
                actual.add(node.name)

    stale = set(_FAKE_TO_CASSETTE_DIR) - actual
    assert not stale, (
        f"Stale _FAKE_TO_CASSETTE_DIR keys (class no longer exists): {stale}"
    )


# =============================================================================
# #8986 rollup behavior — one issue per (fake, gap_kind), not per method.
# =============================================================================


def _write_fake_with_methods(
    fake_dir: Path, class_name: str, methods: list[str]
) -> None:
    body_lines = "\n".join(
        f"    async def {m}(self): ..."  # public, non-helper → adapter-surface
        for m in methods
    )
    (fake_dir / f"{class_name.lower().replace('fake', 'fake_')}.py").write_text(
        f"class {class_name}:\n{body_lines}\n"
    )


async def test_rollup_files_one_issue_for_many_uncovered_methods(
    loop_env, monkeypatch, tmp_path
) -> None:
    """#8986: 12 uncovered FakeGitHub methods → 1 rollup issue, not 12."""
    cfg, state, pr, dedup = loop_env
    state.get_fake_coverage_rollup_issue.return_value = None
    state.get_fake_coverage_last_known.return_value = {}
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    methods = [f"op_{i:02d}" for i in range(12)]
    body_lines = "\n".join(f"    async def {m}(self): ..." for m in methods)
    (fake_dir / "fake_github.py").write_text(f"class FakeGitHub:\n{body_lines}\n")
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(
        parents=True
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()

    # Exactly ONE issue filed for all 12 uncovered methods.
    assert pr.create_issue.await_count == 1
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    body = pr.create_issue.await_args.args[1]
    assert "FakeGitHub" in title
    assert "12 methods" in title
    for method in methods:
        assert method in body
    # Rollup-issue number was stashed in state.
    state.set_fake_coverage_rollup_issue.assert_called_once_with(
        "FakeGitHub:adapter-surface", 42
    )


async def test_rollup_tick_2_updates_body_when_method_gains_coverage(
    loop_env, monkeypatch, tmp_path
) -> None:
    """Tick 2: previously-uncovered method now cassetted → update body, remove it."""
    cfg, state, pr, dedup = loop_env
    # State as if tick 1 already filed: rollup-issue tracked + prior uncovered set.
    # Per-kind tracking — only adapter-surface has a tracked issue; the
    # test-helper kind is untouched (no helpers in this fake).
    state.get_fake_coverage_rollup_issue.side_effect = lambda k: (
        4242 if k == "FakeGitHub:adapter-surface" else None
    )
    state.get_fake_coverage_last_known.return_value = {
        "__uncovered__:FakeGitHub:adapter-surface": ["create_issue", "close_issue"],
        "FakeGitHub": [],
    }
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self): ...\n"
        "    async def close_issue(self): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    # create_issue gained coverage between ticks.
    (cassettes / "create_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        # Pretend the rollup is still open.
        return {"Fake coverage gap: FakeGitHub adapter surface (2 methods)"}

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()

    # No new issue created; existing one updated.
    pr.create_issue.assert_not_awaited()
    pr.update_issue_body.assert_awaited_once()
    args = pr.update_issue_body.await_args.args
    assert args[0] == 4242
    body = args[1]
    # The remaining uncovered method is listed; the recovered one is struck.
    assert "close_issue" in body
    assert "~~`create_issue`~~" in body
    assert stats["updated"] == 1


async def test_rollup_tick_3_appends_newly_uncovered_method(
    loop_env, monkeypatch, tmp_path
) -> None:
    """Tick 3: a new method becomes uncovered → body updated, method appended."""
    cfg, state, pr, dedup = loop_env
    state.get_fake_coverage_rollup_issue.return_value = 4242
    # Tick 2 reported only [close_issue]; tick 3 sees close_issue + new_method.
    state.get_fake_coverage_last_known.return_value = {
        "__uncovered__:FakeGitHub:adapter-surface": ["close_issue"],
        "FakeGitHub": ["create_issue"],
    }
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self): ...\n"
        "    async def close_issue(self): ...\n"
        "    async def new_method(self): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    (cassettes / "create_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return {"Fake coverage gap: FakeGitHub adapter surface (1 methods)"}

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    await loop._do_work()

    pr.create_issue.assert_not_awaited()
    pr.update_issue_body.assert_awaited_once()
    body = pr.update_issue_body.await_args.args[1]
    assert "close_issue" in body
    assert "new_method" in body
    # create_issue is now covered, not listed (nor strikethrough — it
    # wasn't in last tick's uncovered set; it was already covered).
    assert "`create_issue`" not in body or "~~`create_issue`~~" not in body


async def test_rollup_escalation_keyed_on_fake_kind_not_method(
    loop_env, monkeypatch, tmp_path
) -> None:
    """3-strikes counter is per ``(fake, kind)``, never per method."""
    cfg, state, pr, dedup = loop_env
    state.inc_fake_coverage_attempts.return_value = 3
    state.get_fake_coverage_rollup_issue.return_value = None
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def a(self): ...\n"
        "    async def b(self): ...\n"
        "    async def c(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(
        parents=True
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()

    # Attempt counter incremented once for the whole (FakeGitHub, adapter-surface)
    # rollup — NOT once per uncovered method.
    state.inc_fake_coverage_attempts.assert_called_once_with(
        "FakeGitHub:adapter-surface"
    )
    assert stats["escalated"] == 1
    # And the escalation issue's title carries the rollup key.
    title = pr.create_issue.await_args.args[0]
    assert "FakeGitHub:adapter-surface" in title


async def test_rollup_closed_by_human_refiles_cleanly(
    loop_env, monkeypatch, tmp_path
) -> None:
    """Closed-by-human rollup: next tick re-files a fresh issue (zombie guard)."""
    cfg, state, pr, dedup = loop_env
    # State thinks rollup #4242 is open, but no matching open title is found.
    state.get_fake_coverage_rollup_issue.return_value = 4242
    state.get_fake_coverage_last_known.return_value = {}
    pr.create_issue = AsyncMock(return_value=5000)
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n    async def missing(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(
        parents=True
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return set()  # no open rollup → it was closed by a human

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()

    # The stale rollup number was dropped and a fresh issue was filed.
    state.clear_fake_coverage_rollup_issue.assert_any_call("FakeGitHub:adapter-surface")
    state.clear_fake_coverage_attempts.assert_any_call("FakeGitHub:adapter-surface")
    assert pr.create_issue.await_count == 1
    assert stats["filed"] == 1
    # New issue number recorded.
    state.set_fake_coverage_rollup_issue.assert_called_with(
        "FakeGitHub:adapter-surface", 5000
    )


async def test_escalation_does_not_storm_after_threshold(
    loop_env, monkeypatch, tmp_path
) -> None:
    """Regression: escalation fires exactly once when attempts crosses
    ``_MAX_ATTEMPTS`` (==3), not every tick at >=3.

    Without this guard, an open rollup that stays uncovered would file a
    fresh HITL escalation issue on every subsequent tick until a human
    closed it — the original bug review caught before merge.
    """
    cfg, state, pr, dedup = loop_env
    # Tracked rollup already open; counter has already crossed threshold.
    state.get_fake_coverage_rollup_issue.return_value = 4242
    state.get_fake_coverage_last_known.return_value = {}
    state.inc_fake_coverage_attempts.return_value = 4  # >MAX, post-threshold tick
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n    async def missing(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(
        parents=True
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return {"Fake coverage gap: FakeGitHub adapter surface (1 method)"}

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()

    # Body got updated (the rollup is still open and uncovered).
    assert pr.update_issue_body.await_count == 1
    # And NO new escalation issue was filed this tick — the
    # ``attempts == _MAX_ATTEMPTS`` guard only fires once at threshold.
    assert pr.create_issue.await_count == 0
    assert stats["escalated"] == 0


async def test_rollup_body_updated_when_gap_fully_closes(
    loop_env, monkeypatch, tmp_path
) -> None:
    """Regression: when all methods become covered, the rollup body is
    repainted to the "all covered" view BEFORE state is cleared.

    Without this update, the open rollup issue retains the stale list of
    uncovered methods — humans see "12 methods missing" on an issue where
    every method is now cassetted.
    """
    cfg, state, pr, dedup = loop_env
    # Tracked rollup #5050 is open ONLY for adapter-surface; prior tick had
    # ``missing`` uncovered. (Per-kind tracking — test-helper has no issue.)
    state.get_fake_coverage_rollup_issue.side_effect = lambda k: (
        5050 if k == "FakeGitHub:adapter-surface" else None
    )
    state.get_fake_coverage_last_known.return_value = {
        "FakeGitHub": ["missing"],
        "__uncovered__:FakeGitHub:adapter-surface": ["missing"],
    }
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n    async def missing(self): ...\n"
    )
    cassette_dir = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
    cassette_dir.mkdir(parents=True)
    # Cassette now exists for the previously-missing method → fully covered.
    (cassette_dir / "missing.yaml").write_text(
        yaml.safe_dump({"input": {"command": "missing"}, "output": {}})
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    await loop._do_work()

    # Body was updated with the "all covered" view before state cleared.
    assert pr.update_issue_body.await_count >= 1
    update_call = pr.update_issue_body.await_args_list[0]
    assert update_call.args[0] == 5050
    body = update_call.args[1]
    # The recovered method appears (struck through) and no live uncovered.
    assert "missing" in body
    # State was cleared after the body update.
    state.clear_fake_coverage_rollup_issue.assert_any_call("FakeGitHub:adapter-surface")


async def test_helper_rollup_same_shape(loop_env, monkeypatch, tmp_path) -> None:
    """#8986: test-helper gaps also roll up — 3 uncovered helpers → 1 issue."""
    cfg, state, pr, dedup = loop_env
    state.get_fake_coverage_rollup_issue.return_value = None
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_docker.py").write_text(
        "class FakeDocker:\n"
        "    def script_a(self): ...\n"
        "    def script_b(self): ...\n"
        "    def script_c(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "docker").mkdir(
        parents=True
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_grep(_helper):
        return False

    async def fake_list_titles():
        return set()

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_grep_scenario_for_helper", fake_grep)
    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    stats = await loop._do_work()

    assert pr.create_issue.await_count == 1
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    body = pr.create_issue.await_args.args[1]
    assert "FakeDocker" in title
    assert "3 methods" in title
    for helper in ("script_a", "script_b", "script_c"):
        assert helper in body


# --- Right-sizing (fix/rightsize-fake-coverage-auditor) ----------------------
# ADR-0047 scopes cassette contract testing to the adapters with a real
# recorder in src/contract_recording.py (github/git/docker/claude). The
# auditor must (1) only adapter-surface audit those cassette-capable fakes,
# and (2) treat in-memory fake scaffolding (methods with no real-adapter
# counterpart) as neither adapter-surface nor test-helper.


def test_registry_contains_only_cassette_capable_adapters() -> None:
    """Only adapters with a real recorder + YAML cassette dir are audited."""
    assert set(_FAKE_TO_CASSETTE_DIR) == {"FakeGitHub", "FakeGit", "FakeDocker"}


def test_catalog_drops_scaffolding_via_real_adapter(tmp_path: Path) -> None:
    """A FakeGitHub public method absent from the real PRManager/PRPort surface
    is scaffolding, not adapter-surface — it has no recordable gh counterpart."""
    src = tmp_path / "src"
    fake_dir = src / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (src / "pr_manager.py").write_text(
        "class PRManager:\n"
        "    async def create_issue(self, title, body, labels): ...\n"
        "    async def close_issue(self, n): ...\n"
        "    async def ensure_labels_exist(self, labels): ...\n"
    )
    (src / "ports.py").write_text(
        "class PRPort:\n    async def create_issue(self, title, body, labels): ...\n"
    )
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self, title, body, labels): ...\n"
        "    async def close_issue(self, n): ...\n"
        "    async def ensure_labels_exist(self, labels): ...\n"
        "    def add_issue(self, issue): ...\n"
        "    def from_seed(self, seed): ...\n"
        "    def script_ci(self, events): ...\n"
    )

    cat = catalog_fake_methods(fake_dir, repo_root=tmp_path)

    assert set(cat["FakeGitHub"]["adapter-surface"]) == {
        "create_issue",
        "close_issue",
        "ensure_labels_exist",
    }
    assert set(cat["FakeGitHub"]["scaffolding"]) == {"add_issue", "from_seed"}
    assert set(cat["FakeGitHub"]["test-helper"]) == {"script_ci"}


def test_catalog_real_adapter_filter_skips_when_adapter_missing(
    tmp_path: Path,
) -> None:
    """If the real adapter module can't be resolved, fall back to legacy
    classification rather than nuking the whole surface to scaffolding."""
    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self, title): ...\n"
        "    def add_issue(self, issue): ...\n"
    )
    # No src/pr_manager.py or src/ports.py under repo_root → no filtering.
    cat = catalog_fake_methods(fake_dir, repo_root=tmp_path)
    assert set(cat["FakeGitHub"]["adapter-surface"]) == {"create_issue", "add_issue"}
    assert cat["FakeGitHub"]["scaffolding"] == []


async def test_helper_coverage_counts_any_test_not_just_scenarios(
    loop_env, tmp_path
) -> None:
    """A helper exercised by a unit test (outside tests/scenarios/) is part of
    the working contract — the auditor must treat it as covered."""
    cfg, state, pr, dedup = loop_env
    # A non-scenario unit test calls the helper; no tests/scenarios/ at all.
    unit_tests = tmp_path / "tests"
    unit_tests.mkdir(parents=True)
    (unit_tests / "test_fake_llm_phase_scripts.py").write_text(
        "def test_x():\n    fake.script_discover(['a'])\n"
    )

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    assert await loop._grep_scenario_for_helper("script_discover") is True
