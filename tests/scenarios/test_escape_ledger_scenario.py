"""MockWorld scenario for EscapeLedgerLoop (#10367).

End-to-end over FakeGitHub + a real (tiny) git repo fixture on disk — the
escape detector's git adapter (``commits_for_range``) shells out to real git
against ``config.repo_root``, so this scenario builds an actual repo (a
``git revert`` range) rather than seeding FakeGitHub state (mirrors
``tests/scenarios/test_erosion_metrics_scenario.py``). Proves the loop +
FakeGitHub port integrate: a seeded post-merge escape is sensed and recorded
to the append-only ledger, and a re-tick with no new commits records nothing
further (dedup by SHA cursor).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "escape_repo"
    repo.mkdir()
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
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


def _seed_revert(repo: Path) -> tuple[str, str]:
    base_sha = _head(repo)
    (repo / "src" / "mod.py").write_text("def risky():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: risky change")
    bad_sha = _head(repo)
    _git(repo, "revert", "--no-edit", bad_sha)
    return base_sha, _head(repo)


def _seed_skip_regression_docs_commit(repo: Path) -> tuple[str, str]:
    base_sha = _head(repo)
    (repo / "docs.likec4").write_text("diagram v2\n")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "fix(erosion): refresh diagram\n\n"
        "No source or behavior change.\n\n"
        "Skip-Regression: no code change\n\nCloses #10449.",
    )
    return base_sha, _head(repo)


def _seed_regression_pin(repo: Path) -> tuple[str, str]:
    base_sha = _head(repo)
    (repo / "src" / "mod2.py").write_text("def risky2():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: another risky change")
    bad_sha = _head(repo)
    (repo / "tests" / "regressions").mkdir(parents=True)
    (repo / "tests" / "regressions" / "test_mod2.py").write_text(
        "def test_mod2(): pass\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"fix: pin regression from {bad_sha}")
    return base_sha, _head(repo)


def _make_state(initial_sha: str) -> Any:
    from unittest.mock import MagicMock

    state = MagicMock()
    cursor = {"sha": initial_sha}
    state.get_escape_ledger_last_processed_sha.side_effect = lambda: cursor["sha"]

    def _set(sha: str) -> None:
        cursor["sha"] = sha

    state.set_escape_ledger_last_processed_sha.side_effect = _set
    state._cursor = cursor
    return state


def _make_dedup() -> Any:
    from unittest.mock import MagicMock

    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    return dedup


def _build_loop(tmp_path: Path, repo: Path, github: Any, state: Any) -> Any:
    from escape_ledger_loop import EscapeLedgerLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


class TestEscapeLedgerScenario:
    async def test_seeded_revert_range_records_one_escape(self, tmp_path: Path) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, head_sha = _seed_revert(repo)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["escapes_recorded"] == 1

        from escape.ledger import EscapeLedger

        records = EscapeLedger(loop._ledger_path).read_all()
        assert len(records) == 1
        assert records[0].detection_source == "revert"
        assert state._cursor["sha"] == head_sha

    async def test_seeded_regression_pin_range_records_one_escape(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, head_sha = _seed_regression_pin(repo)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["escapes_recorded"] == 1

        from escape.ledger import EscapeLedger

        records = EscapeLedger(loop._ledger_path).read_all()
        assert len(records) == 1
        assert records[0].detection_source == "regression-pin"
        assert records[0].attribution_confidence == "medium"
        assert state._cursor["sha"] == head_sha
        # medium confidence must not trip the low-confidence HITL surface --
        # confirms the fix suppresses the spurious bug-issue filing, not just
        # that the ledger row's label changed.
        assert result["filed"] == 0

    async def test_re_tick_does_not_rerecord(self, tmp_path: Path) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, _head_sha = _seed_revert(repo)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state)

        first = await loop._do_work()
        assert first["escapes_recorded"] == 1

        second = await loop._do_work()
        assert second["status"] == "no_new_commits"

        from escape.ledger import EscapeLedger

        assert len(EscapeLedger(loop._ledger_path).read_all()) == 1

    async def test_skip_regression_docs_commit_files_no_hitl_finding(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, _head_sha = _seed_skip_regression_docs_commit(repo)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["escapes_recorded"] == 0
        assert result["filed"] == 0

    async def test_resolved_row_renders_as_encoded_in_report(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, _head_sha = _seed_revert(repo)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state)

        first = await loop._do_work()
        assert first["escapes_recorded"] == 1

        from escape.ledger import EscapeLedger

        ledger = EscapeLedger(loop._ledger_path)
        (record,) = ledger.read_all()
        resolved = ledger.append_resolution(
            record.id, encoded_as="detector", notes="resolved"
        )
        assert resolved is not None

        loop._render_reports(repo)

        report_path = repo / "docs/arch/generated/escape-ledger.md"
        text = report_path.read_text(encoding="utf-8")
        # the collapse must be applied: exactly one recorded escape, encoded
        # as `detector` — not double-counted as both none-yet and detector
        assert "| total recorded escapes | 1 |" in text
        assert "| encoded / unencoded | 1 / 0 |" in text

    async def test_surface_findings_reads_through_the_collapse(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        state = _make_state(_head(repo))
        loop = _build_loop(tmp_path, repo, github, state)

        from escape.ledger import EscapeLedger
        from escape.models import EscapeRecord

        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            EscapeRecord(
                id="bug-issue:abc123",
                detected_at="2026-01-01T00:00:00+00:00",
                detection_source="bug-issue",
                detection_ref="abc123",
                originating_pr=None,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method="fixes-chain",
                attribution_confidence="low",
                encoded_as="none-yet",
                notes="",
            )
        )
        # resolved BEFORE any tick ever surfaced it — the dedup store's
        # `already_surfaced` set is empty, so only the collapse (not the
        # one-shot surfacing fingerprint) can exclude it here.
        ledger.append_resolution(
            "bug-issue:abc123",
            encoded_as="detector",
            attribution_confidence="high",
            notes="confirmed not an escape",
        )

        filed, capped = await loop._surface_findings()

        assert filed == 0
        assert capped is False
