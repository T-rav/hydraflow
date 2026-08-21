"""ErosionMetricsLoop — mass + suite-hygiene class-issue wiring.

Covers the repo-wide candidates (one class issue per kind), the three-way
dedup (open+same roster → nothing; open+changed roster → body refresh;
closed → re-file), the per-tick cap, and the rendered body's class marker.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from erosion_metrics_loop import (
    _current_head_sha,
    class_issue_fingerprint,
    find_class_issue_entry,
)
from find_class_key import extract_class_key, extract_folded_sites
from subprocess_util import CreditExhaustedError
from tests.test_erosion_metrics_loop import (
    _commit_all,
    _init_repo,
    _make_dedup,
    _make_loop,
    _make_state,
)


def _god_class_source(methods: int = 40) -> str:
    lines = ["class Hub:"]
    for i in range(methods):
        lines.append(f"    def m{i}(self):")
        lines.append("        return 1")
    return "\n".join(lines) + "\n"


def _parametrize_group_source(n: int = 3) -> str:
    return "".join(
        f"def test_case_{i}():\n    assert f('{i}') == {i}\n\n" for i in range(n)
    )


def _seed(repo: Path, *, god_class: bool = True, dup_tests: bool = True) -> str:
    """Commit a repo that trips the mass and/or suite-hygiene sensors; return HEAD sha."""
    (repo / "src").mkdir(exist_ok=True)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "src" / "hub.py").write_text(
        _god_class_source() if god_class else "x = 1\n"
    )
    (repo / "tests" / "test_dup.py").write_text(
        _parametrize_group_source() if dup_tests else "def test_one():\n    pass\n"
    )
    return _commit_all(repo, "seed")


def _prs(state: str = "OPEN") -> MagicMock:
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=7)
    prs.get_issue_state = AsyncMock(return_value=state)
    prs.update_issue_body = AsyncMock()
    return prs


# --- fingerprints ------------------------------------------------------------


def test_class_issue_fingerprint_and_lookup_round_trip() -> None:
    seen = {
        "spread:a..b",
        class_issue_fingerprint("mass", 12, "abc123"),
        class_issue_fingerprint("suite_hygiene", 13, "def456"),
    }
    assert find_class_issue_entry(seen, "mass") == (12, "abc123")
    assert find_class_issue_entry(seen, "suite_hygiene") == (13, "def456")
    assert find_class_issue_entry(seen, "other") is None


# --- repo-wide candidates ----------------------------------------------------


class TestRepoWideCandidates:
    def test_god_class_and_parametrize_group_each_yield_one_candidate(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _seed(repo)
        loop = _make_loop(tmp_path, repo)

        candidates = loop._repo_wide_candidates(repo)

        assert [c["kind"] for c in candidates] == ["mass", "suite_hygiene"]
        assert all(c["class_issue"] for c in candidates)
        assert candidates[0]["finding"].god_classes[0].key == "src/hub.py:Hub"
        assert candidates[1]["finding"].parametrize_copies == 2

    def test_clean_repo_yields_no_candidates(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _seed(repo, god_class=False, dup_tests=False)
        loop = _make_loop(tmp_path, repo)
        assert loop._repo_wide_candidates(repo) == []

    def test_digest_is_stable_for_the_same_roster(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _seed(repo)
        loop = _make_loop(tmp_path, repo)
        first = loop._repo_wide_candidates(repo)[0]["digest"]
        second = loop._repo_wide_candidates(repo)[0]["digest"]
        assert first == second and len(first) >= 8


# --- filing: three-way dedup -------------------------------------------------


class TestClassIssueFiling:
    async def test_first_tick_files_one_class_issue_per_kind(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo)
        prs = _prs()
        dedup = _make_dedup()
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["filed"] == 2
        assert prs.create_issue.await_count == 2
        assert find_class_issue_entry(dedup._store, "mass") == (
            7,
            result["mass"]["digest"],
        )
        assert find_class_issue_entry(dedup._store, "suite_hygiene") is not None

    async def test_open_issue_with_same_roster_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo)
        prs = _prs(state="OPEN")
        loop = _make_loop(tmp_path, repo, state=_make_state(base), pr_manager=prs)
        digest = loop._repo_wide_candidates(repo)[0]["digest"]
        hygiene_digest = loop._repo_wide_candidates(repo)[1]["digest"]
        dedup = _make_dedup(
            {
                class_issue_fingerprint("mass", 7, digest),
                class_issue_fingerprint("suite_hygiene", 8, hygiene_digest),
            }
        )
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        result = await loop._do_work()

        assert result["filed"] == 0
        prs.create_issue.assert_not_awaited()
        prs.update_issue_body.assert_not_awaited()

    async def test_open_issue_with_changed_roster_gets_body_refresh(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo)
        prs = _prs(state="OPEN")
        dedup = _make_dedup(
            {
                class_issue_fingerprint("mass", 7, "stale-digest"),
                class_issue_fingerprint("suite_hygiene", 8, "stale-digest"),
            }
        )
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        result = await loop._do_work()

        assert result["filed"] == 0
        assert result["refreshed"] == 2
        prs.create_issue.assert_not_awaited()
        assert prs.update_issue_body.await_count == 2
        refreshed_number, body = prs.update_issue_body.await_args_list[0].args
        assert refreshed_number == 7
        assert "src/hub.py:Hub" in body
        assert find_class_issue_entry(dedup._store, "mass") == (
            7,
            result["mass"]["digest"],
        )
        assert class_issue_fingerprint("mass", 7, "stale-digest") not in dedup._store

    async def test_refresh_failure_is_swallowed_and_old_entry_kept(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo, dup_tests=False)
        prs = _prs(state="OPEN")
        prs.update_issue_body = AsyncMock(side_effect=RuntimeError("gh: 502"))
        dedup = _make_dedup({class_issue_fingerprint("mass", 7, "stale-digest")})
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        result = await loop._do_work()

        assert result["refreshed"] == 0 and result["filed"] == 0
        prs.create_issue.assert_not_awaited()
        # The stale entry stays so the next tick retries the refresh.
        assert find_class_issue_entry(dedup._store, "mass") == (7, "stale-digest")

    async def test_refresh_failure_reraises_credit_exhausted(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo, dup_tests=False)
        prs = _prs(state="OPEN")
        prs.update_issue_body = AsyncMock(side_effect=CreditExhaustedError("credits"))
        dedup = _make_dedup({class_issue_fingerprint("mass", 7, "stale-digest")})
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()

    async def test_closed_issue_is_refiled_while_reading_is_non_empty(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo, dup_tests=False)
        prs = _prs(state="COMPLETED")
        prs.create_issue = AsyncMock(return_value=9)
        dedup = _make_dedup({class_issue_fingerprint("mass", 7, "any")})
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        result = await loop._do_work()

        assert result["filed"] == 1
        prs.create_issue.assert_awaited_once()
        assert find_class_issue_entry(dedup._store, "mass")[0] == 9

    async def test_create_issue_returning_zero_stores_nothing(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo, dup_tests=False)
        prs = _prs()
        prs.create_issue = AsyncMock(
            return_value=0
        )  # PRManager's no-raise failure sentinel
        dedup = _make_dedup()
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        result = await loop._do_work()

        assert result["filed"] == 0
        assert find_class_issue_entry(dedup._store, "mass") is None
        # Next tick (new commit) tries again instead of believing "#0" exists.
        (repo / "src" / "more.py").write_text("x = 1\n")
        _commit_all(repo, "more")
        prs.create_issue = AsyncMock(return_value=11)
        again = await loop._do_work()
        assert again["filed"] == 1
        assert find_class_issue_entry(dedup._store, "mass") == (
            11,
            again["mass"]["digest"],
        )

    async def test_unknown_issue_state_is_a_no_op_this_tick(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo, dup_tests=False)
        prs = _prs(state="")  # PRManager returns '' on a gh error
        dedup = _make_dedup({class_issue_fingerprint("mass", 7, "any")})
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )

        result = await loop._do_work()

        assert result["filed"] == 0
        prs.create_issue.assert_not_awaited()
        prs.update_issue_body.assert_not_awaited()
        assert class_issue_fingerprint("mass", 7, "any") in dedup._store

    async def test_class_issues_count_against_the_per_tick_cap(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo)
        prs = _prs()
        loop = _make_loop(
            tmp_path,
            repo,
            state=_make_state(base),
            pr_manager=prs,
            erosion_metrics_max_issues_per_tick=1,
        )

        result = await loop._do_work()

        assert result["filed"] == 1
        assert result["capped"] is True
        prs.create_issue.assert_awaited_once()


# --- rendering ---------------------------------------------------------------


class TestRendering:
    async def test_mass_body_carries_class_marker_roster_and_brief(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo, dup_tests=False)
        prs = _prs()
        loop = _make_loop(tmp_path, repo, state=_make_state(base), pr_manager=prs)

        await loop._do_work()

        title, body = prs.create_issue.await_args.args[:2]
        assert title.startswith("Erosion: 1 god class")
        assert "Hub" in title
        assert extract_class_key(body).startswith("findclass:erosion_metrics:")
        assert extract_folded_sites(body) == ["src/hub.py:Hub"]
        assert "40 methods" in body
        assert "re-export" in body  # the safe decomposition brief
        assert "hydraflow-find" in prs.create_issue.await_args.kwargs["labels"]

    async def test_suite_hygiene_body_lists_groups_and_totals(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        _seed(repo, god_class=False)
        prs = _prs()
        loop = _make_loop(tmp_path, repo, state=_make_state(base), pr_manager=prs)

        await loop._do_work()

        title, body = prs.create_issue.await_args.args[:2]
        assert "2 parametrize copies" in title
        assert extract_class_key(body).startswith("findclass:erosion_metrics:")
        assert extract_folded_sites(body) == ["tests/test_dup.py::test_case_0"]
        assert "test_case_0, test_case_1, test_case_2" in body
        assert "pytest.mark.parametrize" in body
        assert "| tests | 3 |" in body
