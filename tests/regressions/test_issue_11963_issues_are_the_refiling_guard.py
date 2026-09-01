"""#11963 — the re-filing guard must survive a re-clone.

ADR-0089 made the mirror frontmatter the loop's re-filing guard. That put the
guard in whichever checkout happened to be running: the loop filed #11947,
#11948 and #11949, wrote `status: issue-open`, and committed it into a factory
workspace nothing pushes — so `staging` still read `pending`, and re-cloning
that workspace (which #11923 asks for) would have re-filed all three as
duplicates of issues that were still open.

The board answers the question the frontmatter was standing in for, and it
survives a re-clone, a reset workspace and a lost DedupStore. The frontmatter
becomes a cache, healed on the tick that notices it is stale.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from config import HydraFlowConfig
from memory_backlog_loop import MemoryBacklogLoop
from memory_backlog_mirror import filed_slugs, slug_from_issue_body, render_issue_body


def _mirror_body(slug: str) -> str:
    rel = f"docs/wiki/memory-feedback/{slug}.md"
    return f"- Mirror: [`{rel}`]({rel})\n"


def _write_entry(dir_: Path, slug: str) -> Path:
    front = {
        "source": f"feedback_{slug.replace('-', '_')}.md",
        "name": f"Test rule {slug}",
        "description": f"desc for {slug}",
        "status": "pending",
        "issue": None,
        "promoted_in": None,
        "wontfix_reason": None,
        "created": "2026-05-07",
    }
    path = dir_ / f"{slug}.md"
    path.write_text(f"---\n{yaml.safe_dump(front)}---\n\nrule body\n", encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path: Path):
    mirror = tmp_path / "docs" / "wiki" / "memory-feedback"
    mirror.mkdir(parents=True)
    cfg = HydraFlowConfig(
        data_root=tmp_path / ".hydraflow", repo="hydra/hydraflow", repo_root=tmp_path
    )
    state = MagicMock()
    state.get_memory_backlog_attempts.return_value = 0
    state.inc_memory_backlog_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup, mirror


def _loop(env) -> MemoryBacklogLoop:
    from tests.test_memory_backlog_loop import _deps

    cfg, state, pr, dedup, _ = env
    loop = MemoryBacklogLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=_deps(asyncio.Event(), enabled=True),
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._commit_mirror_updates = AsyncMock(return_value=None)
    return loop


@pytest.mark.asyncio
class TestAFreshCheckoutDoesNotReFile:
    async def test_an_entry_with_an_open_issue_is_not_filed_again(self, env) -> None:
        # The exact #11963 state: frontmatter says `pending` because the
        # write-back never reached this checkout, while the issue is open.
        cfg, _s, pr, _d, mirror = env
        _write_entry(mirror, "feedback-alpha")
        pr.list_issues_by_label.return_value = [
            {
                "number": 11947,
                "title": "Memory backlog: alpha",
                "body": _mirror_body("feedback-alpha"),
                "updated_at": "",
            }
        ]

        result = await _loop(env)._do_work()

        assert result["filed"] == 0
        pr.create_issue.assert_not_awaited()

    async def test_the_stale_frontmatter_is_healed(self, env) -> None:
        # Skipping alone would make every future tick pay for the same query to
        # reach the same answer, and leave the row lying about its state.
        cfg, _s, pr, _d, mirror = env
        path = _write_entry(mirror, "feedback-alpha")
        pr.list_issues_by_label.return_value = [
            {
                "number": 11947,
                "title": "t",
                "body": _mirror_body("feedback-alpha"),
                "updated_at": "",
            }
        ]

        await _loop(env)._do_work()

        front = yaml.safe_load(path.read_text().split("---")[1])
        assert (front["status"], front["issue"]) == ("issue-open", 11947)

    async def test_a_healed_row_is_committed(self, env) -> None:
        # It changed the same files a filed row does; leaving it uncommitted is
        # the drift `_commit_mirror_updates` exists to prevent.
        cfg, _s, pr, _d, mirror = env
        _write_entry(mirror, "feedback-alpha")
        pr.list_issues_by_label.return_value = [
            {
                "number": 11947,
                "title": "t",
                "body": _mirror_body("feedback-alpha"),
                "updated_at": "",
            }
        ]
        loop = _loop(env)

        await loop._do_work()

        loop._commit_mirror_updates.assert_awaited_once()


@pytest.mark.asyncio
class TestAnUnfiledEntryStillFiles:
    async def test_an_empty_board_files_normally(self, env) -> None:
        # The decoy. A guard that skipped everything would pass every test
        # above while filing nothing, forever.
        cfg, _s, pr, _d, mirror = env
        _write_entry(mirror, "feedback-alpha")
        pr.list_issues_by_label.return_value = []

        result = await _loop(env)._do_work()

        assert result["filed"] == 1
        pr.create_issue.assert_awaited_once()

    async def test_an_issue_naming_no_mirror_is_not_evidence(self, env) -> None:
        # A human-written issue under the same label names no mirror, so it
        # says nothing about whether this entry was filed.
        cfg, _s, pr, _d, mirror = env
        _write_entry(mirror, "feedback-alpha")
        pr.list_issues_by_label.return_value = [
            {
                "number": 999,
                "title": "unrelated",
                "body": "no mirror here",
                "updated_at": "",
            }
        ]

        result = await _loop(env)._do_work()

        assert result["filed"] == 1

    async def test_a_different_entrys_issue_does_not_block_this_one(self, env) -> None:
        cfg, _s, pr, _d, mirror = env
        _write_entry(mirror, "feedback-alpha")
        pr.list_issues_by_label.return_value = [
            {
                "number": 11948,
                "title": "t",
                "body": _mirror_body("feedback-beta"),
                "updated_at": "",
            }
        ]

        result = await _loop(env)._do_work()

        assert result["filed"] == 1


@pytest.mark.asyncio
class TestTheGuardFailsClosed:
    async def test_an_unreadable_board_files_nothing(self, env) -> None:
        """A tick that files nothing costs a delay; one that files blind costs
        duplicates a human must close. The guard being unavailable means "not
        now", never "probably fine"."""
        cfg, _s, pr, _d, mirror = env
        _write_entry(mirror, "feedback-alpha")
        pr.list_issues_by_label.side_effect = RuntimeError("gh unavailable")

        result = await _loop(env)._do_work()

        assert result["status"] == "guard-unavailable"
        pr.create_issue.assert_not_awaited()


class TestTheParser:
    def test_the_slug_comes_from_the_body_the_loop_writes(self) -> None:
        """One format, two readers — not a convention held by agreement."""
        from memory_backlog_mirror import MirrorEntry

        entry = MirrorEntry(
            slug="feedback-alpha",
            path=Path("x"),
            source="s.md",
            name="n",
            description="d",
            status="pending",
            issue=None,
            promoted_in=None,
            wontfix_reason=None,
            body="b",
        )
        rendered = render_issue_body(
            entry, repo_relative_path="docs/wiki/memory-feedback/feedback-alpha.md"
        )

        assert slug_from_issue_body(rendered) == "feedback-alpha"

    def test_the_lowest_issue_number_wins_a_duplicate(self) -> None:
        # Deterministic healing, pointing at the original rather than whichever
        # row the API happened to return last.
        body = _mirror_body("feedback-alpha")
        issues = [{"number": 300, "body": body}, {"number": 100, "body": body}]

        assert filed_slugs(issues) == {"feedback-alpha": 100}

    def test_a_row_with_no_number_is_ignored(self) -> None:
        assert filed_slugs([{"body": _mirror_body("feedback-alpha")}]) == {}
