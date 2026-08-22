"""Tests for blocker_gate.py — ``Blocked by: #N`` readiness gating (#11614).

The gate reads blocker state through ``PRPort`` only; every test drives it
through ``FakeGitHub`` (a real ``PRPort``) so the air-gap holds and no live
``gh`` can be reached. The load-bearing invariant is FAIL-OPEN: an unknown,
unreadable, or rate-limited blocker must never hold an issue back — an
unknown dependency is not evidence of a dependency.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from blocker_gate import BlockerGate, parse_blockers
from mockworld.fakes.fake_github import FakeGitHub

_SRC = Path(__file__).resolve().parent.parent / "src"


class _CountingGitHub(FakeGitHub):
    """FakeGitHub that records how many state/body reads the gate issues."""

    def __init__(self) -> None:
        super().__init__()
        self.state_reads: list[int] = []
        self.body_reads: list[int] = []

    async def get_issue_state(self, issue_number: int) -> str:
        self.state_reads.append(issue_number)
        return await super().get_issue_state(issue_number)

    async def get_issue_body(self, issue_number: int) -> str:
        self.body_reads.append(issue_number)
        return await super().get_issue_body(issue_number)


# ---------------------------------------------------------------------------
# Grammar — only the forms actually written on the board
# ---------------------------------------------------------------------------


class TestParseBlockers:
    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            pytest.param(
                "Parent: #11531\nBlocked by: #11533\n", [11533], id="single-ref"
            ),
            pytest.param(
                "Blocked by: #11537, #11539", [11537, 11539], id="comma-separated"
            ),
            pytest.param("Blocked by: #9\nBlocked by: #9", [9], id="repeats-collapse"),
            pytest.param("Parent: #1\r\nBlocked by: #2\r\n", [2], id="crlf-endings"),
            pytest.param("blocked by: #3", [3], id="lowercase-phrase"),
        ],
    )
    def test_declaration_parses(self, body: str, expected: list[int]) -> None:
        assert parse_blockers(body) == expected

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                "This regression was blocked by a flaky test in #42 last week.",
                id="prose-mid-sentence",
            ),
            pytest.param(
                "Blocked by: #42 which is only a red herring", id="trailing-prose"
            ),
            pytest.param("Blocked by: the upstream vendor", id="no-issue-ref"),
            pytest.param("", id="empty-body"),
        ],
    )
    def test_non_declaration_parses_to_nothing(self, body: str) -> None:
        assert parse_blockers(body) == []

    def test_self_reference_is_ignored(self) -> None:
        assert parse_blockers("Blocked by: #7", self_number=7) == []

    def test_self_reference_does_not_drop_its_siblings(self) -> None:
        assert parse_blockers("Blocked by: #7, #8", self_number=7) == [8]


# ---------------------------------------------------------------------------
# Resolution — blocker state read through the PRPort
# ---------------------------------------------------------------------------


class TestOpenBlockerBlocks:
    async def test_open_blocker_blocks_the_issue(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(11533, "Fable P0", "the prerequisite")
        verdict = await BlockerGate().evaluate(gh, 11534, "Blocked by: #11533")
        assert verdict.blocked is True

    async def test_reason_names_the_open_blocker(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(11533, "Fable P0", "the prerequisite")
        verdict = await BlockerGate().evaluate(gh, 11534, "Blocked by: #11533")
        assert "#11533" in verdict.reason

    async def test_open_blockers_are_reported_in_declaration_order(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(11537, "P1", "open")
        gh.add_issue(11539, "P2", "open")
        verdict = await BlockerGate().evaluate(gh, 11541, "Blocked by: #11537, #11539")
        assert verdict.open_blockers == (11537, 11539)


class TestClosedBlockerDoesNotBlock:
    async def test_closed_blocker_does_not_block(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(11533, "Fable P0", "shipped", state="closed")
        verdict = await BlockerGate().evaluate(gh, 11534, "Blocked by: #11533")
        assert verdict.blocked is False

    async def test_not_planned_blocker_does_not_block(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(500, "Abandoned", "wont fix")
        await gh.close_issue(500, reason="not planned")
        verdict = await BlockerGate().evaluate(gh, 501, "Blocked by: #500")
        assert verdict.blocked is False

    async def test_all_blockers_closed_does_not_block(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(11540, "P4", "done", state="closed")
        gh.add_issue(11543, "P5", "done", state="closed")
        verdict = await BlockerGate().evaluate(gh, 11544, "Blocked by: #11540, #11543")
        assert verdict.blocked is False

    async def test_one_open_among_several_still_blocks(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(11540, "P4", "done", state="closed")
        gh.add_issue(11543, "P5", "still open")
        verdict = await BlockerGate().evaluate(gh, 11544, "Blocked by: #11540, #11543")
        assert verdict.open_blockers == (11543,)


# ---------------------------------------------------------------------------
# Fail-open — the invariant a bug here would freeze the whole board
# ---------------------------------------------------------------------------


class TestFailOpen:
    async def test_unknown_blocker_does_not_block(self) -> None:
        gh = FakeGitHub()  # #999 was never seeded → UNKNOWN
        verdict = await BlockerGate().evaluate(gh, 1, "Blocked by: #999")
        assert verdict.blocked is False

    async def test_unknown_blocker_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        gh = FakeGitHub()
        with caplog.at_level(logging.WARNING, logger="hydraflow.blocker_gate"):
            await BlockerGate().evaluate(gh, 1, "Blocked by: #999")
        assert "#999" in caplog.text

    async def test_read_error_does_not_block(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(2, "Prerequisite", "open")
        gh.set_rate_limit_mode(remaining=0)
        verdict = await BlockerGate().evaluate(gh, 1, "Blocked by: #2")
        assert verdict.blocked is False

    async def test_read_error_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        gh = FakeGitHub()
        gh.add_issue(2, "Prerequisite", "open")
        gh.set_rate_limit_mode(remaining=0)
        with caplog.at_level(logging.WARNING, logger="hydraflow.blocker_gate"):
            await BlockerGate().evaluate(gh, 1, "Blocked by: #2")
        assert "failing open" in caplog.text

    async def test_read_error_still_reports_what_was_declared(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(2, "Prerequisite", "open")
        gh.set_rate_limit_mode(remaining=0)
        verdict = await BlockerGate().evaluate(gh, 1, "Blocked by: #2")
        assert verdict.declared == (2,)


class TestCycles:
    async def test_two_cycle_does_not_block_either_side(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(10, "A", "Blocked by: #11")
        gh.add_issue(11, "B", "Blocked by: #10")
        verdict = await BlockerGate().evaluate(gh, 10, "Blocked by: #11")
        assert verdict.blocked is False

    async def test_two_cycle_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        gh = FakeGitHub()
        gh.add_issue(10, "A", "Blocked by: #11")
        gh.add_issue(11, "B", "Blocked by: #10")
        with caplog.at_level(logging.WARNING, logger="hydraflow.blocker_gate"):
            await BlockerGate().evaluate(gh, 10, "Blocked by: #11")
        assert "cycle" in caplog.text.lower()

    async def test_longer_cycle_does_not_block(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(20, "A", "Blocked by: #21")
        gh.add_issue(21, "B", "Blocked by: #22")
        gh.add_issue(22, "C", "Blocked by: #20")
        verdict = await BlockerGate().evaluate(gh, 20, "Blocked by: #21")
        assert verdict.blocked is False

    async def test_acyclic_chain_still_blocks(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(30, "A", "Blocked by: #31")
        gh.add_issue(31, "B", "Blocked by: #32")
        gh.add_issue(32, "C", "no blockers")
        verdict = await BlockerGate().evaluate(gh, 30, "Blocked by: #31")
        assert verdict.blocked is True


# ---------------------------------------------------------------------------
# Cost — no N+1 gh call per tick
# ---------------------------------------------------------------------------


class TestLookupCost:
    async def test_body_without_a_declaration_reads_nothing(self) -> None:
        gh = _CountingGitHub()
        await BlockerGate().evaluate(gh, 1, "A perfectly ordinary issue body.")
        assert gh.state_reads == []

    async def test_repeated_blocker_is_read_once_across_children(self) -> None:
        gh = _CountingGitHub()
        gh.add_issue(100, "Shared prerequisite", "open")
        gate = BlockerGate()
        await gate.evaluate(gh, 1, "Blocked by: #100")
        await gate.evaluate(gh, 2, "Blocked by: #100")
        assert gh.state_reads == [100]

    async def test_expired_cache_entry_is_re_read(self) -> None:
        gh = _CountingGitHub()
        gh.add_issue(100, "Shared prerequisite", "open")
        gate = BlockerGate(ttl_seconds=0.0)
        await gate.evaluate(gh, 1, "Blocked by: #100")
        await gate.evaluate(gh, 2, "Blocked by: #100")
        assert gh.state_reads == [100, 100]

    async def test_closed_blocker_unblocks_once_the_cache_expires(self) -> None:
        gh = _CountingGitHub()
        gh.add_issue(100, "Shared prerequisite", "open")
        gate = BlockerGate(ttl_seconds=0.0)
        assert (await gate.evaluate(gh, 1, "Blocked by: #100")).blocked is True
        await gh.close_issue(100)
        assert (await gate.evaluate(gh, 1, "Blocked by: #100")).blocked is False

    async def test_memo_evicts_rather_than_growing_without_bound(self) -> None:
        """The gate outlives every tick; its memo must not leak issue by issue."""
        gh = _CountingGitHub()
        gate = BlockerGate()
        for n in range(1, 400):
            gh.add_issue(n, f"Prerequisite {n}", "done", state="closed")
            await gate.evaluate(gh, 900_000 + n, f"Blocked by: #{n}")

        gh.state_reads.clear()
        await gate.evaluate(gh, 900_001, "Blocked by: #1")

        assert gh.state_reads == [1]

    async def test_cycle_walk_does_not_re_read_the_same_body(self) -> None:
        gh = _CountingGitHub()
        gh.add_issue(40, "A", "Blocked by: #41, #42")
        gh.add_issue(41, "B", "Blocked by: #43")
        gh.add_issue(42, "C", "Blocked by: #43")
        gh.add_issue(43, "D", "terminal")
        await BlockerGate().evaluate(gh, 40, "Blocked by: #41, #42")
        assert sorted(gh.body_reads) == [41, 42, 43]


# ---------------------------------------------------------------------------
# Port fidelity — the gate never shells out to gh itself
# ---------------------------------------------------------------------------


class TestPortFidelity:
    def test_module_never_shells_out(self) -> None:
        source = (_SRC / "blocker_gate.py").read_text(encoding="utf-8")
        banned = ("subprocess", "run_simple", "create_subprocess")
        offenders = [token for token in banned if token in source]
        assert offenders == []
