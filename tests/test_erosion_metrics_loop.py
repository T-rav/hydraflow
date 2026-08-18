"""Unit tests for ErosionMetricsLoop (#10107, epic #10104).

Covers: sensor composition + threshold gate (spread/scatter candidates),
dedup by SHA (cursor) and by finding-fingerprint (DedupStore), the
per-tick issue-filing cap, the kill-switch, and reraise_on_credit_or_bug
in the per-item except.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from arch._models import ModuleGraph, ModuleNode
from erosion_metrics_loop import (
    ErosionMetricsLoop,
    _current_head_sha,
    scatter_finding_fingerprint,
    spread_finding_fingerprint,
)
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps


def _graph(*names: str) -> ModuleGraph:
    return ModuleGraph(nodes=[ModuleNode(name=n) for n in names])


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    """Create a fresh git repo with an initial commit under ``src/``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_state(initial_sha: str = "") -> MagicMock:
    state = MagicMock()
    cursor: dict[str, str] = {"sha": initial_sha}
    state.get_erosion_last_processed_sha.side_effect = lambda: cursor["sha"]

    def _set(sha: str) -> None:
        cursor["sha"] = sha

    state.set_erosion_last_processed_sha.side_effect = _set
    state._cursor = cursor
    return state


def _make_dedup(seen: set[str] | None = None) -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set(seen or set())
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    dedup._store = store
    return dedup


def _make_loop(
    tmp_path: Path,
    repo: Path,
    *,
    state: MagicMock | None = None,
    dedup: MagicMock | None = None,
    pr_manager: Any = None,
    **config_overrides: Any,
) -> ErosionMetricsLoop:
    max_issues = config_overrides.pop("erosion_metrics_max_issues_per_tick", None)
    bg = make_bg_loop_deps(tmp_path, **config_overrides)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)
    if max_issues is not None:
        object.__setattr__(bg.config, "erosion_metrics_max_issues_per_tick", max_issues)
    prs = pr_manager if pr_manager is not None else MagicMock()
    if not isinstance(prs.create_issue, AsyncMock):
        prs.create_issue = AsyncMock(return_value=1)
    return ErosionMetricsLoop(
        config=bg.config,
        pr_manager=prs,
        state=state if state is not None else _make_state(),
        dedup=dedup if dedup is not None else _make_dedup(),
        deps=bg.loop_deps,
    )


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def test_spread_fingerprint_is_stable_per_range() -> None:
    assert spread_finding_fingerprint("aaa..bbb") == "spread:aaa..bbb"


def test_scatter_fingerprint_folds_in_range_and_symbol() -> None:
    fp = scatter_finding_fingerprint("aaa..bbb", "helper")
    assert fp == "scatter:aaa..bbb:helper"
    # A distinct range for the SAME symbol produces a distinct fingerprint
    # (each range is a distinct incident, not deduped forever).
    assert fp != scatter_finding_fingerprint("ccc..ddd", "helper")


# ---------------------------------------------------------------------------
# _current_head_sha
# ---------------------------------------------------------------------------


def test_current_head_sha_reads_real_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    sha = _current_head_sha(repo)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert sha == result.stdout.strip()


def test_current_head_sha_none_outside_a_repo(tmp_path: Path) -> None:
    assert _current_head_sha(tmp_path) is None


# ---------------------------------------------------------------------------
# _compute_candidates — threshold gate (pure, synthetic graph, no git)
# ---------------------------------------------------------------------------


class TestComputeCandidates:
    def test_scatter_candidate_when_symbol_crosses_threshold_modules(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo)
        graph = _graph("src.moda", "src.modb", "src.modc")
        added_symbols = {
            "src/moda/a.py": ["shared_helper"],
            "src/modb/b.py": ["shared_helper"],
            "src/modc/c.py": ["shared_helper"],
        }

        candidates = loop._compute_candidates("aaa..bbb", [], added_symbols, graph)

        assert len(candidates) == 1
        assert candidates[0]["kind"] == "scatter"
        assert candidates[0]["symbol"].symbol == "shared_helper"
        assert candidates[0]["fingerprint"] == "scatter:aaa..bbb:shared_helper"

    def test_no_scatter_candidate_below_threshold(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo)
        graph = _graph("src.moda", "src.modb")
        added_symbols = {
            "src/moda/a.py": ["shared_helper"],
            "src/modb/b.py": ["shared_helper"],
        }

        candidates = loop._compute_candidates("aaa..bbb", [], added_symbols, graph)

        assert candidates == []

    def test_spread_candidate_when_ratio_exceeds_a_tightened_baseline(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        baseline_dir = repo / "erosion" / "baselines"
        baseline_dir.mkdir(parents=True)
        (baseline_dir / "spread.yaml").write_text(
            "comment: test\nentries:\n  max_spread_ratio: 0.1\n"
        )
        loop = _make_loop(tmp_path, repo)
        graph = _graph("src.moda", "src.modb")
        changed_files = ["src/moda/a.py", "src/modb/b.py"]

        candidates = loop._compute_candidates("aaa..bbb", changed_files, {}, graph)

        spread_candidates = [c for c in candidates if c["kind"] == "spread"]
        assert len(spread_candidates) == 1
        assert spread_candidates[0]["fingerprint"] == "spread:aaa..bbb"
        assert spread_candidates[0]["finding"].spread_ratio == pytest.approx(1.0)

    def test_no_spread_candidate_under_default_baseline(self, tmp_path: Path) -> None:
        """The default baseline (ratio ceiling 1.0, strict-greater gate) never fires."""
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo)
        graph = _graph("src.moda", "src.modb")
        changed_files = ["src/moda/a.py", "src/modb/b.py"]

        candidates = loop._compute_candidates("aaa..bbb", changed_files, {}, graph)

        assert candidates == []


# ---------------------------------------------------------------------------
# Kill-switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    async def test_disabled_via_enabled_cb(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        bg = make_bg_loop_deps(tmp_path, enabled=False)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)
        loop = ErosionMetricsLoop(
            config=bg.config,
            pr_manager=MagicMock(),
            state=_make_state(),
            dedup=_make_dedup(),
            deps=bg.loop_deps,
        )

        result = await loop._do_work()

        assert result == {"status": "disabled", "token_drift_filed": 0}

    async def test_disabled_via_config_flag(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "erosion_metrics_loop_enabled", False)
        loop = ErosionMetricsLoop(
            config=bg.config,
            pr_manager=MagicMock(),
            state=_make_state(),
            dedup=_make_dedup(),
            deps=bg.loop_deps,
        )

        result = await loop._do_work()

        assert result == {"status": "config_disabled", "token_drift_filed": 0}

    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo, dry_run=True)

        result = await loop._do_work()

        assert result is None

    async def test_dry_run_skips_token_drift_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo, dry_run=True)
        called = AsyncMock()
        monkeypatch.setattr("erosion_metrics_loop.run_token_drift_check", called)

        await loop._do_work()

        called.assert_not_awaited()


# ---------------------------------------------------------------------------
# Token-drift filing actuator wiring (#11442)
# ---------------------------------------------------------------------------


class TestTokenDriftWiring:
    async def test_host_calls_run_token_drift_check_and_folds_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        head = _current_head_sha(repo)
        assert head is not None
        state = _make_state(initial_sha=head)  # no_new_commits: simplest early-exit
        dedup = _make_dedup()
        pr_manager = MagicMock()
        loop = _make_loop(
            tmp_path, repo, state=state, dedup=dedup, pr_manager=pr_manager
        )
        stub = AsyncMock(return_value=7)
        monkeypatch.setattr("erosion_metrics_loop.run_token_drift_check", stub)

        result = await loop._do_work()

        stub.assert_awaited_once_with(
            loop._config,
            pr_manager=pr_manager,
            dedup=dedup,
            event_bus=loop._bus,
        )
        assert result == {
            "status": "no_new_commits",
            "sha": head,
            "token_drift_filed": 7,
        }

    async def test_disabled_via_enabled_cb_skips_token_drift_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        bg = make_bg_loop_deps(tmp_path, enabled=False)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)
        loop = ErosionMetricsLoop(
            config=bg.config,
            pr_manager=MagicMock(),
            state=_make_state(),
            dedup=_make_dedup(),
            deps=bg.loop_deps,
        )
        called = AsyncMock()
        monkeypatch.setattr("erosion_metrics_loop.run_token_drift_check", called)

        result = await loop._do_work()

        called.assert_not_awaited()
        assert result == {"status": "disabled", "token_drift_filed": 0}


# ---------------------------------------------------------------------------
# Cursor: baseline priming, dedup by SHA, real-range end-to-end
# ---------------------------------------------------------------------------


class TestCursor:
    async def test_first_tick_primes_baseline_without_analysis(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        state = _make_state(initial_sha="")
        loop = _make_loop(tmp_path, repo, state=state)

        result = await loop._do_work()

        assert result["status"] == "baseline_established"
        assert state._cursor["sha"] == _current_head_sha(repo)

    async def test_no_new_commits_is_a_noop(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        head = _current_head_sha(repo)
        assert head is not None
        state = _make_state(initial_sha=head)
        loop = _make_loop(tmp_path, repo, state=state)

        result = await loop._do_work()

        assert result == {
            "status": "no_new_commits",
            "sha": head,
            "token_drift_filed": 0,
        }

    async def test_scattered_symbol_is_filed_then_not_refiled_on_no_new_commits(
        self, tmp_path: Path
    ) -> None:
        """End-to-end over a real git range: erosive commit -> issue filed;
        a second tick with no new commits does not refile (dedup by SHA)."""
        repo = _init_repo(tmp_path)
        for pkg in ("moda", "modb", "modc"):
            (repo / "src" / pkg).mkdir(parents=True)
            (repo / "src" / pkg / "m.py").write_text("x = 1\n")
        base_sha = _commit_all(repo, "base modules")

        for pkg in ("moda", "modb", "modc"):
            path = repo / "src" / pkg / "m.py"
            path.write_text(path.read_text() + "\n\ndef shared_helper():\n    pass\n")
        erosive_sha = _commit_all(repo, "scatter shared_helper")

        state = _make_state(initial_sha=base_sha)
        dedup = _make_dedup()
        pr_manager = MagicMock()
        pr_manager.create_issue = AsyncMock(return_value=42)
        loop = _make_loop(
            tmp_path, repo, state=state, dedup=dedup, pr_manager=pr_manager
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["filed"] == 1
        assert pr_manager.create_issue.await_count == 1
        title, body = pr_manager.create_issue.await_args.args[:2]
        assert "shared_helper" in title
        assert "hydraflow-find" in pr_manager.create_issue.await_args.kwargs["labels"]
        assert "erosion-metrics" in pr_manager.create_issue.await_args.kwargs["labels"]
        assert "#10106" in body
        assert state._cursor["sha"] == erosive_sha

        # Second tick: cursor already at HEAD -> dedup by SHA, no re-analysis.
        result_2 = await loop._do_work()

        assert result_2 == {
            "status": "no_new_commits",
            "sha": erosive_sha,
            "token_drift_filed": 0,
        }
        assert pr_manager.create_issue.await_count == 1

    async def test_diff_unavailable_leaves_cursor_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        (repo / "src" / "moda").mkdir(parents=True)
        (repo / "src" / "moda" / "m.py").write_text("x = 1\n")
        base_sha = _commit_all(repo, "base")
        (repo / "src" / "moda" / "m.py").write_text("x = 2\n")
        _commit_all(repo, "change")

        state = _make_state(initial_sha=base_sha)
        loop = _make_loop(tmp_path, repo, state=state)
        monkeypatch.setattr(
            "erosion_metrics_loop.changed_files_for_range", lambda *a, **k: None
        )

        result = await loop._do_work()

        assert result["status"] == "diff_unavailable"
        assert state._cursor["sha"] == base_sha  # unchanged — will retry


# ---------------------------------------------------------------------------
# Dedup by finding-fingerprint
# ---------------------------------------------------------------------------


class TestFileFindings:
    async def test_already_seen_fingerprint_is_not_refiled(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        fingerprint = "scatter:aaa..bbb:shared_helper"
        dedup = _make_dedup(seen={fingerprint})
        pr_manager = MagicMock()
        pr_manager.create_issue = AsyncMock(return_value=1)
        loop = _make_loop(tmp_path, repo, dedup=dedup, pr_manager=pr_manager)
        graph = _graph("src.moda", "src.modb", "src.modc")
        candidates = loop._compute_candidates(
            "aaa..bbb",
            [],
            {
                "src/moda/a.py": ["shared_helper"],
                "src/modb/b.py": ["shared_helper"],
                "src/modc/c.py": ["shared_helper"],
            },
            graph,
        )
        assert [c["fingerprint"] for c in candidates] == [fingerprint]

        filed, capped = await loop._file_findings(candidates)

        assert filed == 0
        assert capped is False
        pr_manager.create_issue.assert_not_awaited()

    async def test_per_tick_cap_bounds_filing_and_reports_capped(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        pr_manager = MagicMock()
        pr_manager.create_issue = AsyncMock(return_value=1)
        loop = _make_loop(
            tmp_path,
            repo,
            pr_manager=pr_manager,
            erosion_metrics_max_issues_per_tick=1,
        )
        candidates = [
            {
                "kind": "spread",
                "fingerprint": "spread:a..b",
                "commit_range": "a..b",
                "finding": MagicMock(
                    spread_ratio=2.0, files_touched=1, modules_crossed=2, modules=("x",)
                ),
                "baseline": MagicMock(max_spread_ratio=1.0),
            },
            {
                "kind": "scatter",
                "fingerprint": "scatter:a..b:foo",
                "commit_range": "a..b",
                "symbol": MagicMock(
                    symbol="foo", modules=("x", "y", "z"), files=("f",)
                ),
                "excess": 3,
                "threshold": 3,
            },
        ]

        filed, capped = await loop._file_findings(candidates)

        assert filed == 1
        assert capped is True
        assert pr_manager.create_issue.await_count == 1

    async def test_create_issue_failure_reraises_credit_exhausted(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        pr_manager = MagicMock()
        pr_manager.create_issue = AsyncMock(side_effect=CreditExhaustedError("out"))
        loop = _make_loop(tmp_path, repo, pr_manager=pr_manager)
        candidates = [
            {
                "kind": "spread",
                "fingerprint": "spread:a..b",
                "commit_range": "a..b",
                "finding": MagicMock(
                    spread_ratio=2.0, files_touched=1, modules_crossed=2, modules=("x",)
                ),
                "baseline": MagicMock(max_spread_ratio=1.0),
            }
        ]

        with pytest.raises(CreditExhaustedError):
            await loop._file_findings(candidates)

    async def test_create_issue_generic_failure_is_swallowed_and_logged(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        pr_manager = MagicMock()
        pr_manager.create_issue = AsyncMock(side_effect=RuntimeError("boom"))
        loop = _make_loop(tmp_path, repo, pr_manager=pr_manager)
        candidates = [
            {
                "kind": "spread",
                "fingerprint": "spread:a..b",
                "commit_range": "a..b",
                "finding": MagicMock(
                    spread_ratio=2.0, files_touched=1, modules_crossed=2, modules=("x",)
                ),
                "baseline": MagicMock(max_spread_ratio=1.0),
            }
        ]

        filed, capped = await loop._file_findings(candidates)

        assert filed == 0
        assert capped is False


# ---------------------------------------------------------------------------
# loop_fitness
# ---------------------------------------------------------------------------


def test_loop_fitness_is_housekeeping(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from loop_fitness import FitnessContext, FitnessKind

    repo = _init_repo(tmp_path)
    loop = _make_loop(tmp_path, repo)
    now = datetime.now(UTC)
    ctx = FitnessContext(window_start=now, window_end=now)

    fitness = loop.loop_fitness(ctx)

    assert fitness.kind == FitnessKind.HOUSEKEEPING
    assert fitness.worker_name == "erosion_metrics"
