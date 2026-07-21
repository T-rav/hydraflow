"""Shared escalation reconciler: closed-escalation state clearing + open-
escalation re-verification against the current tick's detections.

Closing a stuck escalation is today the ONLY reset mechanism, and it is
human-gated — #9618 sat six days as a dead letter while later PRs may have
fixed the gap. `reconcile_open` parses subjects from OPEN escalation titles
(not from dedup keys — recovery paths like fake_coverage's
_clear_rollup_state erase the key on the very tick the gap disappears) and
closes any whose subject is absent from the currently-detected set.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from dedup_store import DedupStore
from escalation_reconcile import (
    BOT_CLOSE_MARKER_LABEL,
    EscalationReconciler,
    is_bot_close,
    stamp_and_close,
)
from mockworld.fakes.fake_github import FakeGitHub

_TITLE_RE = re.compile(r"fake coverage gap (\S+) unresolved")


def _subject_from_title(title: str) -> str | None:
    m = _TITLE_RE.search(title)
    return m.group(1) if m else None


@pytest.fixture
def env(tmp_path: Path):
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.list_closed_issues_by_label = AsyncMock(return_value=[])
    dedup = DedupStore("esc_test", tmp_path / "dedup" / "esc_test.json")
    cleared: list[str] = []
    rec = EscalationReconciler(
        prs=prs,
        dedup=dedup,
        key_prefix="fake_coverage_auditor",
        stuck_label="hydraflow-fake-coverage-stuck",
        clear_attempts=cleared.append,
        subject_from_title=_subject_from_title,
    )
    return rec, prs, dedup, cleared


def _issue(number: int, title: str, labels: list[str] | None = None) -> dict:
    issue: dict = {"number": number, "title": title, "body": "", "updated_at": ""}
    if labels is not None:
        issue["labels"] = [{"name": name} for name in labels]
    return issue


_STUCK_TITLE = "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3"


class TestReconcileClosed:
    @pytest.mark.asyncio
    async def test_clears_key_and_attempts_on_matching_closed_title(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [_issue(9618, _STUCK_TITLE)]
        await rec.reconcile_closed()
        assert dedup.get() == set()
        assert cleared == ["FakeGitHub:adapter-surface"]

    @pytest.mark.asyncio
    async def test_keeps_keys_without_matching_closed_title(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [
            _issue(
                1, "HITL: fake coverage gap FakeDocker:test-helper unresolved after 3"
            )
        ]
        await rec.reconcile_closed()
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []

    @pytest.mark.asyncio
    async def test_foreign_prefix_key_untouched(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"other_loop:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [_issue(1, _STUCK_TITLE)]
        await rec.reconcile_closed()
        assert dedup.get() == {"other_loop:FakeGitHub:adapter-surface"}
        assert cleared == []

    @pytest.mark.asyncio
    async def test_unparseable_titles_skipped(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [
            _issue(1, "some manually-created issue carrying the label")
        ]
        await rec.reconcile_closed()
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []

    # --- bot-vs-human close guard (#9437) -------------------------------------
    # A human/external close is the intentional reset signal → drop the dedup
    # key + counter (pre-#9437 contract). A bot/programmatic close (stamped with
    # BOT_CLOSE_MARKER_LABEL before closing) must NOT reset dedup, or a premature
    # close of a still-detected subject refiles a duplicate next tick. An
    # unknown/absent signal falls open to the human path — behaviour unchanged.

    @pytest.mark.asyncio
    async def test_human_close_drops_key(self, env) -> None:
        """No bot marker on the close → treat as human/external → drop key."""
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [
            _issue(9618, _STUCK_TITLE, labels=["hydraflow-fake-coverage-stuck"])
        ]
        await rec.reconcile_closed()
        assert dedup.get() == set()
        assert cleared == ["FakeGitHub:adapter-surface"]

    @pytest.mark.asyncio
    async def test_bot_close_retains_key(self, env) -> None:
        """Bot/programmatic marker present → retain key (no duplicate refile)."""
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [
            _issue(
                9618,
                _STUCK_TITLE,
                labels=["hydraflow-fake-coverage-stuck", BOT_CLOSE_MARKER_LABEL],
            )
        ]
        await rec.reconcile_closed()
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []

    @pytest.mark.asyncio
    async def test_unknown_signal_falls_open_to_drop(self, env) -> None:
        """Closed projection omits labels (#9943) → signal unavailable → the
        backward-compatible fallback drops the key, exactly as pre-#9437."""
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [_issue(9618, _STUCK_TITLE)]
        await rec.reconcile_closed()
        assert dedup.get() == set()
        assert cleared == ["FakeGitHub:adapter-surface"]


class TestIsBotClose:
    def test_marker_label_present_is_bot(self) -> None:
        issue = {"labels": [{"name": "x"}, {"name": BOT_CLOSE_MARKER_LABEL}]}
        assert is_bot_close(issue) is True

    def test_marker_label_absent_is_human(self) -> None:
        issue = {"labels": [{"name": "hydraflow-fake-coverage-stuck"}]}
        assert is_bot_close(issue) is False

    def test_missing_labels_key_is_human(self) -> None:
        assert is_bot_close({"number": 1, "title": "t"}) is False

    def test_none_or_malformed_labels_is_human(self) -> None:
        assert is_bot_close({"labels": None}) is False
        assert is_bot_close({"labels": ["not-a-dict"]}) is False


class TestReconcileOpen:
    @pytest.mark.asyncio
    async def test_closes_escalation_when_subject_no_longer_detected(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.return_value = [_issue(9618, _STUCK_TITLE)]
        closed = await rec.reconcile_open(active_subjects=set())
        assert closed == 1
        prs.post_comment.assert_awaited_once()
        assert "no longer detected" in prs.post_comment.await_args.args[1]
        prs.close_issue.assert_awaited_once_with(9618)
        assert dedup.get() == set()
        assert cleared == ["FakeGitHub:adapter-surface"]

    @pytest.mark.asyncio
    async def test_closes_even_when_dedup_key_already_cleared(self, env) -> None:
        """Recovery paths (e.g. _clear_rollup_state) erase the dedup key on
        the same tick the gap disappears — discovery must come from the open
        escalation's TITLE, or the escalation orphans forever."""
        rec, prs, dedup, cleared = env
        prs.list_issues_by_label.return_value = [_issue(9618, _STUCK_TITLE)]
        closed = await rec.reconcile_open(active_subjects=set())
        assert closed == 1
        prs.close_issue.assert_awaited_once_with(9618)
        assert cleared == ["FakeGitHub:adapter-surface"]

    @pytest.mark.asyncio
    async def test_keeps_escalation_while_subject_still_detected(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.return_value = [_issue(9618, _STUCK_TITLE)]
        closed = await rec.reconcile_open(
            active_subjects={"FakeGitHub:adapter-surface"}
        )
        assert closed == 0
        prs.close_issue.assert_not_awaited()
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}

    @pytest.mark.asyncio
    async def test_none_active_subjects_skips_entirely(self, env) -> None:
        """Detection failed/partial this tick — closing on incomplete data
        would kill real escalations and reset their attempt budgets."""
        rec, prs, dedup, cleared = env
        closed = await rec.reconcile_open(active_subjects=None)
        assert closed == 0
        prs.list_issues_by_label.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unparseable_open_title_left_alone(self, env) -> None:
        rec, prs, dedup, cleared = env
        prs.list_issues_by_label.return_value = [
            _issue(7, "manually created issue with the stuck label")
        ]
        closed = await rec.reconcile_open(active_subjects=set())
        assert closed == 0
        prs.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_close_propagates_but_retains_state(self, env) -> None:
        """Port errors propagate to the loop's cycle handler (which owns
        credit/auth classification per the reraise rule); dedup key and
        attempt budget stay intact so the next tick retries — and the
        closed-path parser self-heals any half-closed issue."""
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.return_value = [_issue(9618, _STUCK_TITLE)]
        prs.close_issue.side_effect = RuntimeError("gh down mid-close")
        with pytest.raises(RuntimeError):
            await rec.reconcile_open(active_subjects=set())
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []  # retry next tick with budget intact

    @pytest.mark.asyncio
    async def test_list_error_propagates_without_state_change(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.side_effect = RuntimeError("gh down")
        with pytest.raises(RuntimeError):
            await rec.reconcile_open(active_subjects=set())
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []


class TestStampAndClose:
    """The shared #10095 helper every programmatic escalation-closer routes
    through: stamp BOT_CLOSE_MARKER_LABEL, THEN close — so the next
    ``list_closed_issues_by_label`` read always sees both together."""

    @pytest.mark.asyncio
    async def test_stamps_marker_before_closing(self) -> None:
        prs = AsyncMock()
        calls: list[str] = []
        prs.add_labels.side_effect = lambda *a, **k: calls.append("add_labels")
        prs.close_issue.side_effect = lambda *a, **k: calls.append("close_issue")

        await stamp_and_close(prs, 9618)

        prs.add_labels.assert_awaited_once_with(9618, [BOT_CLOSE_MARKER_LABEL])
        prs.close_issue.assert_awaited_once_with(9618)
        assert calls == ["add_labels", "close_issue"]

    @pytest.mark.asyncio
    async def test_against_fake_github_issue_is_closed_and_labeled(self) -> None:
        """End-to-end against the real MockWorld fake (not a mock double):
        the closed-issue projection FakeGitHub returns afterward carries
        the marker, exactly like the real gh-wire shape (#8996)."""
        prs = FakeGitHub()
        prs.add_issue(
            9618, "HITL: flaky test t unresolved after 3", "", ["flaky-test-stuck"]
        )

        await stamp_and_close(prs, 9618)

        closed = await prs.list_closed_issues_by_label("flaky-test-stuck")
        assert len(closed) == 1
        assert is_bot_close(closed[0]) is True


class TestStampAndCloseActivatesReconcileClosedGuard:
    """Integration proof (#10095): a programmatic close that routes through
    :func:`stamp_and_close` is retained by
    :meth:`EscalationReconciler.reconcile_closed`, while a plain/human close
    of an otherwise-identical escalation still re-arms — against the same
    FakeGitHub + DedupStore + EscalationReconciler wiring a real trust loop
    uses, so Part 2 (#8996 labels-on-closed-projection) is exercised too."""

    @pytest.mark.asyncio
    async def test_programmatic_close_retains_dedup_key_no_duplicate_refile(
        self, tmp_path: Path
    ) -> None:
        prs = FakeGitHub()
        prs.add_issue(
            9618,
            _STUCK_TITLE,
            "",
            ["hydraflow-fake-coverage-stuck"],
        )
        dedup = DedupStore("esc_test", tmp_path / "dedup" / "esc_test.json")
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        cleared: list[str] = []
        rec = EscalationReconciler(
            prs=prs,
            dedup=dedup,
            key_prefix="fake_coverage_auditor",
            stuck_label="hydraflow-fake-coverage-stuck",
            clear_attempts=cleared.append,
            subject_from_title=_subject_from_title,
        )

        # Programmatic close (e.g. IssueDecomposer's superseded-by-decompose
        # path) — routes through the shared helper, so the marker lands
        # BEFORE the close.
        await stamp_and_close(prs, 9618)

        await rec.reconcile_closed()

        # Retained: a still-detected subject must not refile a duplicate.
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []

    @pytest.mark.asyncio
    async def test_human_close_without_marker_still_rearms(
        self, tmp_path: Path
    ) -> None:
        prs = FakeGitHub()
        prs.add_issue(
            9619,
            _STUCK_TITLE,
            "",
            ["hydraflow-fake-coverage-stuck"],
        )
        dedup = DedupStore("esc_test_human", tmp_path / "dedup" / "esc_test_human.json")
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        cleared: list[str] = []
        rec = EscalationReconciler(
            prs=prs,
            dedup=dedup,
            key_prefix="fake_coverage_auditor",
            stuck_label="hydraflow-fake-coverage-stuck",
            clear_attempts=cleared.append,
            subject_from_title=_subject_from_title,
        )

        # Human close via the GitHub UI — no stamp, unlike stamp_and_close.
        await prs.close_issue(9619)

        await rec.reconcile_closed()

        # Dropped: the pre-#9437 contract is unchanged for genuine human closes.
        assert dedup.get() == set()
        assert cleared == ["FakeGitHub:adapter-surface"]
