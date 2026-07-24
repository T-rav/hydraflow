"""Unit tests for EscapeLedgerLoop (#10367).

Covers the kill-switch, the cursor (baseline priming + dedup by SHA), an
end-to-end escape recording over a real git revert range (populated
time-to-detection), the erosion trend datapoint + generated reports, the
finding-rate budget (pure cap), and reraise_on_credit_or_bug in the
issue-surfacing except.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from escape.models import EscapeRecord
from escape_ledger_loop import (
    EscapeLedgerLoop,
    _current_head_sha,
    select_findings_to_surface,
    surfacing_fingerprint,
)
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    # Per-repo identity — CI carries no global git config (see
    # feedback-ci-no-global-git-config).
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_revert_range(repo: Path) -> tuple[str, str]:
    """Base commit + a bad commit + a `git revert` of it. Returns (base, head)."""
    base_sha = _head(repo)
    (repo / "src" / "mod.py").write_text("def risky():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: risky change")
    bad_sha = _head(repo)
    _git(repo, "revert", "--no-edit", bad_sha)
    return base_sha, _head(repo)


def _make_state(initial_sha: str = "") -> MagicMock:
    state = MagicMock()
    cursor: dict[str, str] = {"sha": initial_sha}
    state.get_escape_ledger_last_processed_sha.side_effect = lambda: cursor["sha"]

    def _set(sha: str) -> None:
        cursor["sha"] = sha

    state.set_escape_ledger_last_processed_sha.side_effect = _set
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
) -> EscapeLedgerLoop:
    max_issues = config_overrides.pop("escape_ledger_max_issues_per_tick", None)
    bg = make_bg_loop_deps(tmp_path, **config_overrides)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    if max_issues is not None:
        object.__setattr__(bg.config, "escape_ledger_max_issues_per_tick", max_issues)
    prs = pr_manager if pr_manager is not None else MagicMock()
    if not isinstance(prs.create_issue, AsyncMock):
        prs.create_issue = AsyncMock(return_value=1)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=prs,
        state=state if state is not None else _make_state(),
        dedup=dedup if dedup is not None else _make_dedup(),
        deps=bg.loop_deps,
    )


def _record(
    rid: str, *, confidence: str = "low", encoded_as: str = "none-yet"
) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence=confidence,
        encoded_as=encoded_as,
        notes="",
    )


# ---------------------------------------------------------------------------
# _current_head_sha
# ---------------------------------------------------------------------------


def test_current_head_sha_reads_real_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert _current_head_sha(repo) == _head(repo)


def test_current_head_sha_none_outside_repo(tmp_path: Path) -> None:
    assert _current_head_sha(tmp_path) is None


# ---------------------------------------------------------------------------
# Kill-switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    async def test_disabled_via_enabled_cb(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        bg = make_bg_loop_deps(tmp_path, enabled=False)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        loop = EscapeLedgerLoop(
            config=bg.config,
            pr_manager=MagicMock(),
            state=_make_state(),
            dedup=_make_dedup(),
            deps=bg.loop_deps,
        )
        assert await loop._do_work() == {"status": "disabled"}

    async def test_disabled_via_config_flag(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        object.__setattr__(bg.config, "escape_ledger_loop_enabled", False)
        loop = EscapeLedgerLoop(
            config=bg.config,
            pr_manager=MagicMock(),
            state=_make_state(),
            dedup=_make_dedup(),
            deps=bg.loop_deps,
        )
        assert await loop._do_work() == {"status": "config_disabled"}

    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo, dry_run=True)
        assert await loop._do_work() is None


# ---------------------------------------------------------------------------
# Cursor
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
        assert state._cursor["sha"] == _head(repo)

    async def test_no_new_commits_is_noop(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        head = _head(repo)
        state = _make_state(initial_sha=head)
        loop = _make_loop(tmp_path, repo, state=state)
        assert await loop._do_work() == {"status": "no_new_commits", "sha": head}


# ---------------------------------------------------------------------------
# End-to-end escape recording over a real revert range
# ---------------------------------------------------------------------------


class TestRecordEscapes:
    async def test_revert_range_records_one_row_with_populated_ttd(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base_sha, head_sha = _seed_revert_range(repo)
        state = _make_state(initial_sha=base_sha)
        loop = _make_loop(tmp_path, repo, state=state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["escapes_recorded"] == 1
        assert result["escapes_detected"] == 1
        assert state._cursor["sha"] == head_sha

        from escape.ledger import EscapeLedger

        records = EscapeLedger(loop._ledger_path).read_all()
        assert len(records) == 1
        row = records[0]
        assert row.detection_source == "revert"
        assert row.attribution_method == "revert-parse"
        assert row.attribution_confidence == "high"
        assert row.time_to_detection_hours is not None  # merged_at resolved from sha

        # Generated reports written into the repo root (gitignored at runtime).
        assert (repo / "docs/arch/generated/escape-ledger.md").exists()
        assert (repo / "docs/arch/generated/erosion-trends.md").exists()

    async def test_second_tick_no_new_commits_does_not_refile(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base_sha, head_sha = _seed_revert_range(repo)
        state = _make_state(initial_sha=base_sha)
        dedup = _make_dedup()
        loop = _make_loop(tmp_path, repo, state=state, dedup=dedup)

        first = await loop._do_work()
        assert first["escapes_recorded"] == 1

        second = await loop._do_work()
        assert second == {"status": "no_new_commits", "sha": head_sha}

        from escape.ledger import EscapeLedger

        assert len(EscapeLedger(loop._ledger_path).read_all()) == 1  # not doubled

    async def test_trend_datapoint_appended(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base_sha, _head_sha = _seed_revert_range(repo)
        state = _make_state(initial_sha=base_sha)
        loop = _make_loop(tmp_path, repo, state=state)

        result = await loop._do_work()

        assert result["trend_datapoint"] is True
        from erosion.trends import TrendStore

        assert len(TrendStore(loop._trends_path).read_all()) == 1


# ---------------------------------------------------------------------------
# Finding-rate budget (pure) + surfacing
# ---------------------------------------------------------------------------


class TestFindingRateBudget:
    def test_flood_is_capped_at_max_per_tick(self) -> None:
        from datetime import UTC, datetime

        now = datetime(2026, 6, 1, tzinfo=UTC)
        flood = [_record(f"bug-issue:{i}", confidence="low") for i in range(20)]
        to_file, capped = select_findings_to_surface(
            flood,
            now=now,
            aging_threshold_hours=24 * 14,
            already_surfaced=set(),
            max_per_tick=3,
        )
        assert len(to_file) == 3
        assert capped is True

    def test_already_surfaced_are_skipped(self) -> None:
        from datetime import UTC, datetime

        now = datetime(2026, 6, 1, tzinfo=UTC)
        recs = [_record("bug-issue:a"), _record("bug-issue:b")]
        to_file, capped = select_findings_to_surface(
            recs,
            now=now,
            aging_threshold_hours=24 * 14,
            already_surfaced={surfacing_fingerprint("bug-issue:a")},
            max_per_tick=5,
        )
        assert {r.id for r in to_file} == {"bug-issue:b"}
        assert capped is False

    async def test_surface_reraises_credit_exhausted(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        pr = MagicMock()
        pr.create_issue = AsyncMock(side_effect=CreditExhaustedError("out"))
        loop = _make_loop(tmp_path, repo, pr_manager=pr)
        from escape.ledger import EscapeLedger

        EscapeLedger(loop._ledger_path).append(_record("bug-issue:x", confidence="low"))

        with pytest.raises(CreditExhaustedError):
            await loop._surface_findings()


# ---------------------------------------------------------------------------
# loop_fitness
# ---------------------------------------------------------------------------


def test_loop_fitness_is_housekeeping(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from loop_fitness import FitnessContext, FitnessKind

    repo = _init_repo(tmp_path)
    loop = _make_loop(tmp_path, repo)
    now = datetime.now(UTC)
    fitness = loop.loop_fitness(FitnessContext(window_start=now, window_end=now))
    assert fitness.kind == FitnessKind.HOUSEKEEPING
    assert fitness.worker_name == "escape_ledger"
