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
    # Under docs/ — false_close.product_paths excludes this path, so the
    # paths-scoped Skip-Regression gate (#10498 review) actually fires. A
    # top-level docs.likec4 (no directory prefix) would NOT be excluded and
    # would defeat the point of this fixture.
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "diagram.likec4").write_text("diagram v2\n")
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


def _build_loop(
    tmp_path: Path,
    repo: Path,
    github: Any,
    state: Any,
    *,
    auto_diagnose: bool = False,
) -> Any:
    from escape_ledger_loop import EscapeLedgerLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    object.__setattr__(bg.config, "escape_ledger_auto_diagnose_enabled", auto_diagnose)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


def _seed_bug_fix_with_regression(repo: Path, issue: int) -> tuple[str, str]:
    """A regression pin lands first, THEN a `fix: … fixes #N` commit.

    The regression commit is BEFORE the analysed base, so the range holds only
    the low-confidence bug-issue fix — but the pin is in HEAD's tree for the
    auto-diagnose `git grep`. Returns (base_sha, head_sha).
    """
    reg = repo / "tests" / "regressions"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / f"test_bug_{issue}.py").write_text(
        f"# regression pin for #{issue}\ndef test_bug(): pass\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"test: pin regression for #{issue}")
    base = _head(repo)
    (repo / "src" / "crash.py").write_text("def crash():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"fix: resolve crash (fixes #{issue})")
    return base, _head(repo)


def _seed_bug_fix_no_regression(repo: Path, issue: int) -> tuple[str, str]:
    """A `fix: … fixes #N` commit with NO regression pin — inconclusive."""
    base = _head(repo)
    (repo / "src" / "widget.py").write_text("def widget():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"fix: repair widget (fixes #{issue})")
    return base, _head(repo)


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

    async def test_resolved_escape_closes_its_surfaced_issue_on_next_tick(
        self, tmp_path: Path
    ) -> None:
        # End-to-end over FakeGitHub: a surfaced HITL issue is closed once the
        # operator records an encoding, on a QUIET (no_new_commits) tick — the
        # reconcile pass runs before the early exit (#10577).
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        state = _make_state(_head(repo))
        loop = _build_loop(tmp_path, repo, github, state)

        from escape.ledger import EscapeLedger
        from escape.models import EscapeRecord
        from escape.surfaces import SurfacedIssueLedger

        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            EscapeRecord(
                id="bug-issue:esc9",
                detected_at="2026-01-01T00:00:00+00:00",  # aged past threshold
                detection_source="bug-issue",
                detection_ref="esc9",
                originating_pr=None,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method="fixes-chain",
                attribution_confidence="medium",  # not low => only the AGING surface
                encoded_as="none-yet",
                notes="",
            )
        )

        # A busy tick would file the aging HITL issue; drive that surface here.
        filed, _capped = await loop._surface_findings()
        assert filed == 1
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert await github.get_issue_state(link.issue_number) == "OPEN"

        # Operator records the encoding via EscapeLedger.append_resolution.
        ledger.append_resolution("bug-issue:esc9", encoded_as="detector", notes="done")

        # The next tick is quiet — reconcile must STILL close the stranded issue.
        result = await loop._do_work()
        assert result["status"] == "no_new_commits"
        assert result["closed"] == 1

        issue = github._issues[link.issue_number]
        assert issue.state == "closed"
        assert any("detector" in str(c) for c in issue.comments)

    async def test_folded_away_low_confidence_issue_closes_on_stronger_sibling(
        self, tmp_path: Path
    ) -> None:
        # End-to-end over FakeGitHub (#10731): a low-confidence bug-issue is
        # surfaced, then a stronger regression-pin sibling for the SAME commit
        # lands and folds the surfaced id out of read_latest. On the next quiet
        # tick the reconcile must STILL close the stranded HITL issue — it reads
        # through read_latest_index, not the id-projected read_latest view.
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        state = _make_state(_head(repo))
        loop = _build_loop(tmp_path, repo, github, state)

        from datetime import UTC, datetime

        from escape.ledger import EscapeLedger
        from escape.models import EscapeRecord
        from escape.surfaces import SurfacedIssueLedger

        sha = "d15c0acef00dd15c0acef00dd15c0acef00dd15c"
        fresh = datetime.now(UTC).isoformat()  # not aged => only the LOW surface

        def _row(source: str, confidence: str, method: str) -> EscapeRecord:
            return EscapeRecord(
                id=f"{source}:{sha}",
                detected_at=fresh,
                detection_source=source,
                detection_ref=sha,
                originating_pr=None,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method=method,
                attribution_confidence=confidence,
                encoded_as="none-yet",
                notes="",
            )

        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(_row("bug-issue", "low", "fixes-chain"))

        filed, _capped = await loop._surface_findings()
        assert filed == 1
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert link.escape_id == f"bug-issue:{sha}"
        assert await github.get_issue_state(link.issue_number) == "OPEN"

        # A stronger sibling for the same commit lands (folds bug-issue away).
        ledger.append(_row("regression-pin", "medium", "regression-pin"))

        result = await loop._do_work()
        assert result["status"] == "no_new_commits"
        assert result["closed"] == 1

        issue = github._issues[link.issue_number]
        assert issue.state == "closed"

    async def test_confidence_only_resolution_closes_low_confidence_surfaced_issue(
        self, tmp_path: Path
    ) -> None:
        # #10747: an operator confirming attribution confidence ALONE (via the
        # operator service, no --encoded-as) must answer the low-confidence
        # surface end-to-end — the exact HITL path this issue's finding named.
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        state = _make_state(_head(repo))
        loop = _build_loop(tmp_path, repo, github, state)

        from datetime import UTC, datetime

        from escape.ledger import EscapeLedger
        from escape.models import EscapeRecord
        from escape.resolve import resolve_escape
        from escape.surfaces import SurfacedIssueLedger

        fresh = datetime.now(UTC).isoformat()  # not aged => only the LOW surface
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(
            EscapeRecord(
                id="hotfix:4702cf9",
                detected_at=fresh,
                detection_source="hotfix",
                detection_ref="4702cf9",
                originating_pr=None,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method="blame-intersect",
                attribution_confidence="low",
                encoded_as="none-yet",
                notes="",
            )
        )

        filed, _capped = await loop._surface_findings()
        assert filed == 1
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        assert link.reason == "low-confidence"

        # Operator confirms confidence via the service, WITHOUT naming an
        # encoding — the encoding is still unknown.
        resolved = resolve_escape(
            "hotfix:4702cf9",
            ledger_path=loop._ledger_path,
            attribution_confidence="medium",
            notes="attribution confirmed via blame",
        )
        assert resolved.encoded_as == "none-yet"

        result = await loop._do_work()
        assert result["status"] == "no_new_commits"
        assert result["closed"] == 1

        issue = github._issues[link.issue_number]
        assert issue.state == "closed"


class TestEscapeAutoDiagnoseScenario:
    """ADR-0115: the machine auto-diagnose fires before the human surface."""

    async def test_real_and_encoded_escape_is_auto_resolved_not_filed(
        self, tmp_path: Path
    ) -> None:
        # End-to-end over FakeGitHub + a real repo: a low-confidence bug-issue
        # escape whose bug is already regression-encoded is auto-resolved (high
        # confidence, encoded-as regression-test) and NO HITL issue is filed.
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, head_sha = _seed_bug_fix_with_regression(repo, 123)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state, auto_diagnose=True)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["escapes_recorded"] == 1
        assert result["filed"] == 0, "machine-resolvable escape must not reach a human"
        assert state._cursor["sha"] == head_sha

        from escape.ledger import EscapeLedger

        resolved = EscapeLedger(loop._ledger_path).read_latest()[0]
        assert resolved.attribution_confidence == "high"
        assert resolved.encoded_as == "regression-test"

    async def test_inconclusive_escape_still_files_the_human_surface(
        self, tmp_path: Path
    ) -> None:
        # No regression encoding and an unknown referenced issue → the machine
        # cannot resolve or dismiss, so the human surface IS filed (the genuine
        # escalation path is preserved).
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha, _head_sha = _seed_bug_fix_no_regression(repo, 777)

        state = _make_state(base_sha)
        loop = _build_loop(tmp_path, repo, github, state, auto_diagnose=True)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["escapes_recorded"] == 1
        assert result["filed"] == 1, "inconclusive escape must still reach a human"

    async def test_aging_escape_already_encoded_is_auto_resolved_not_filed(
        self, tmp_path: Path
    ) -> None:
        # #11161: auto-diagnose used to run ONLY for SURFACE_REASON_LOW_CONFIDENCE
        # findings — an AGING finding (encoded_as="none-yet" past the encoding-age
        # threshold) skipped the diagnoser entirely and always filed a human
        # issue, even when its regression encoding was already on disk (the live
        # bug behind escape 9196f7403620 / issue #11161). A `medium`-confidence
        # row is AGING-eligible only (not low-confidence), isolating the surface
        # under test.
        from datetime import UTC, datetime, timedelta

        from escape.ledger import EscapeLedger
        from escape.models import EscapeRecord

        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        reg = repo / "tests" / "regressions"
        reg.mkdir(parents=True)
        (reg / "test_bug_321.py").write_text(
            "# regression pin for #321\ndef test_bug(): pass\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "test: pin regression for #321")
        (repo / "src" / "crash2.py").write_text("def crash2():\n    return 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix: resolve crash (fixes #321)")
        fix_sha = _head(repo)

        state = _make_state(fix_sha)
        loop = _build_loop(tmp_path, repo, github, state, auto_diagnose=True)
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        EscapeLedger(loop._ledger_path).append(
            EscapeRecord(
                id=f"bug-issue:{fix_sha}",
                detected_at=old,
                detection_source="bug-issue",
                detection_ref=fix_sha,
                originating_pr=321,
                originating_merge_sha="",
                merged_at="",
                time_to_detection_hours=None,
                attribution_method="fixes-chain",
                attribution_confidence="medium",
                encoded_as="none-yet",
                notes="Fix commit closing #321.",
            )
        )

        filed, capped = await loop._surface_findings()

        assert filed == 0, "aging escape already regression-encoded must self-answer"
        assert capped is False
        resolved = EscapeLedger(loop._ledger_path).read_latest()[0]
        assert resolved.attribution_confidence == "high"
        assert resolved.encoded_as == "regression-test"
