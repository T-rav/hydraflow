"""decompose_or_escalate — the auto-agent's decompose-before-HITL terminal
(ADR-0105 task 7).

Covers the terminal's own decision logic directly (council + decomposer
mocked, per the task brief) plus the redirect wiring at both
``human-required`` sites: ``AutoAgentPreflightLoop``'s attempt-cap pre-check
(``auto_agent_preflight_loop.py``) and ``preflight/decision.py``'s
``apply_decision``. ``tests/test_auto_agent_preflight_loop.py`` and
``tests/test_preflight_decision.py`` are left unmodified and must stay green
unchanged — they exercise the no-decomposer-wired fallback that this feature
must not disturb (ADR-0084's existing HITL path).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from models import EpicDecompResult, EpicState, NewIssueSpec
from preflight.context import PreflightContext
from preflight.decision import PreflightResult, apply_decision
from preflight.decompose_terminal import decompose_or_escalate
from tests.helpers import ConfigFactory, make_bg_loop_deps, make_tracker

# ---------------------------------------------------------------------------
# Shared factories
# ---------------------------------------------------------------------------


def _ctx(**overrides: object) -> PreflightContext:
    defaults: dict[str, object] = {
        "issue_number": 1,
        "issue_body": "stuck issue body",
        "issue_comments": [],
        "sub_label": "flaky-test-stuck",
        "escalation_context": None,
        "wiki_excerpts": "",
        "sentry_events": [],
        "recent_commits": [],
    }
    defaults.update(overrides)
    return PreflightContext(**defaults)  # type: ignore[arg-type]


def _decomp_result(**overrides: object) -> EpicDecompResult:
    defaults: dict[str, object] = {
        "should_decompose": True,
        "epic_title": "Epic: Split the stalled issue",
        "epic_body": "## Sub-issues",
        "children": [
            NewIssueSpec(title="Child 1", body="Do 1"),
            NewIssueSpec(title="Child 2", body="Do 2"),
        ],
        "reasoning": "Too broad for one autonomous pass",
        "confidence": "high",
    }
    defaults.update(overrides)
    return EpicDecompResult(**defaults)  # type: ignore[arg-type]


def _decline_result(**overrides: object) -> EpicDecompResult:
    defaults: dict[str, object] = {
        "should_decompose": False,
        "reasoning": "Atomic change, not splittable",
        "confidence": "high",
    }
    defaults.update(overrides)
    return EpicDecompResult(**defaults)  # type: ignore[arg-type]


def _make_deps(tmp_path: Path):
    """Terminal-level deps: config real, state/prs mocked, council/decomposer mocked."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    state = MagicMock()
    state.get_issue_status = MagicMock(return_value="")
    state.get_all_epic_states = MagicMock(return_value={})
    state.clear_auto_agent_attempts = MagicMock()
    state.reset_issue_attempts = MagicMock()
    state.reset_review_attempts = MagicMock()
    prs = AsyncMock()
    prs.find_open_pr_for_branch = AsyncMock(return_value=None)
    prs.get_pr_diff_names = AsyncMock(return_value=[])
    prs.close_pr = AsyncMock()
    decomposer = AsyncMock()
    council = AsyncMock()
    return config, state, prs, decomposer, council


# ---------------------------------------------------------------------------
# decompose_or_escalate — direct unit tests
# ---------------------------------------------------------------------------


class TestDecomposeOrEscalate:
    @pytest.mark.asyncio
    async def test_council_approves_creates_epic_no_human_required(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        prs.find_open_pr_for_branch = AsyncMock(return_value=MagicMock(number=42))

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "decomposed"
        decomposer.create_epic_from_result.assert_awaited_once()
        _, kwargs = decomposer.create_epic_from_result.call_args
        assert kwargs["source_task"].id == 7
        assert kwargs["depth"] == 0
        assert kwargs["result"].should_decompose is True
        # Superseded PR closed + attempt counters cleared -- but the caller
        # (not this function) is responsible for NOT adding human-required.
        prs.close_pr.assert_awaited_once_with(42)
        state.clear_auto_agent_attempts.assert_called_once_with(7)
        state.reset_issue_attempts.assert_called_once_with(7)
        state.reset_review_attempts.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_council_declines_returns_human_required(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decline_result())
        decomposer.create_epic_from_result = AsyncMock()

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "human-required"
        decomposer.create_epic_from_result.assert_not_awaited()
        state.clear_auto_agent_attempts.assert_not_called()
        prs.close_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_epic_creation_capped_by_decomposer_falls_through(
        self, tmp_path: Path
    ) -> None:
        """Council approves but IssueDecomposer's own depth/fanout cap
        declines (returns None) -- same floor as an outright decline."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=None)

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "human-required"
        prs.close_pr.assert_not_awaited()
        state.clear_auto_agent_attempts.assert_not_called()

    @pytest.mark.asyncio
    async def test_depth_capped_skips_council_entirely(self, tmp_path: Path) -> None:
        """Issue #7 is itself an auto-decomposed child one split below the
        cap -- resolved depth == max_decomposition_depth. Must escalate
        WITHOUT spending an LLM call to find that out."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        epic = EpicState(
            epic_number=900,
            title="Parent epic",
            child_issues=[7],
            decomposition_depth=config.max_decomposition_depth - 1,
        )
        state.get_all_epic_states = MagicMock(return_value={"900": epic})
        council.decide = AsyncMock(
            side_effect=AssertionError("council must not be called at depth cap")
        )

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "human-required"
        council.decide.assert_not_called()
        decomposer.create_epic_from_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_skips_when_already_decomposed(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        state.get_issue_status = MagicMock(return_value="decomposed")
        council.decide = AsyncMock(
            side_effect=AssertionError("council must not be called when idempotent")
        )

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "decomposed"
        council.decide.assert_not_called()
        decomposer.create_epic_from_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_second_tick_no_duplicate_create_issue(
        self, tmp_path: Path
    ) -> None:
        """Integration-flavored: a REAL IssueDecomposer + FakeGitHub, proving
        a second decompose_or_escalate call for the same issue -- as would
        happen if the auto-agent tick that closed the issue crashed before
        the caller re-polled -- creates zero additional GitHub issues."""
        from issue_decomposer import IssueDecomposer
        from mockworld.fakes.fake_github import FakeGitHub

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        prs = FakeGitHub()
        prs.add_issue(7, "Stuck issue", "body")
        epic_manager = MagicMock()
        epic_manager.register_epic = AsyncMock()
        state = make_tracker(tmp_path)
        decomposer = IssueDecomposer(prs, epic_manager, state, config)
        council = AsyncMock()
        council.decide = AsyncMock(return_value=_decomp_result())

        outcome1 = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )
        assert outcome1 == "decomposed"
        issue_count_after_first = len(prs._issues)
        assert issue_count_after_first > 1  # epic + >=2 children were created

        outcome2 = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome2 == "decomposed"
        # No new epic/children were created on the second, idempotent call.
        assert len(prs._issues) == issue_count_after_first
        council.decide.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_decomposer_falls_back_to_human_required(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=None,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "human-required"
        council.decide.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_council_falls_back_to_human_required(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=None,
            state=state,
            prs=prs,
        )

        assert outcome == "human-required"
        decomposer.create_epic_from_result.assert_not_called()


# ---------------------------------------------------------------------------
# Wiring: AutoAgentPreflightLoop constructor threads epic_manager/runner
# ---------------------------------------------------------------------------


class TestConstructorWiring:
    def test_epic_manager_and_runner_build_decomposer_and_council(
        self, tmp_path: Path
    ) -> None:
        from decomposition_council import DecompositionCouncil
        from issue_decomposer import IssueDecomposer

        deps = make_bg_loop_deps(tmp_path)
        state = MagicMock()
        audit = MagicMock()
        loop = AutoAgentPreflightLoop(
            config=deps.config,
            state=state,
            pr_manager=AsyncMock(),
            wiki_store=None,
            audit_store=audit,
            deps=deps.loop_deps,
            epic_manager=MagicMock(),
            runner=MagicMock(),
        )
        assert isinstance(loop._decomposer, IssueDecomposer)
        assert isinstance(loop._council, DecompositionCouncil)

    def test_without_epic_manager_or_runner_stays_none(self, tmp_path: Path) -> None:
        """Matches every existing fixture in test_auto_agent_preflight_loop.py
        -- no epic_manager/runner passed, so decompose is never attempted."""
        deps = make_bg_loop_deps(tmp_path)
        state = MagicMock()
        audit = MagicMock()
        loop = AutoAgentPreflightLoop(
            config=deps.config,
            state=state,
            pr_manager=AsyncMock(),
            wiki_store=None,
            audit_store=audit,
            deps=deps.loop_deps,
        )
        assert loop._decomposer is None
        assert loop._council is None


# ---------------------------------------------------------------------------
# Wiring: the attempt-cap pre-check site in auto_agent_preflight_loop.py
# ---------------------------------------------------------------------------


def _make_wired_loop(tmp_path: Path, *, decomposer, council):
    deps = make_bg_loop_deps(tmp_path)
    state = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.get_auto_agent_attempts = MagicMock(return_value=3)
    state.get_escalation_context = MagicMock(return_value=None)
    state.get_issue_status = MagicMock(return_value="")
    state.get_all_epic_states = MagicMock(return_value={})
    state.clear_auto_agent_attempts = MagicMock()
    state.reset_issue_attempts = MagicMock()
    state.reset_review_attempts = MagicMock()
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.find_open_pr_for_branch = AsyncMock(return_value=None)
    pr.get_pr_diff_names = AsyncMock(return_value=[])
    audit = MagicMock()
    audit.daily_spend = MagicMock(return_value=0.0)
    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    # Direct injection (same technique other tests in
    # test_auto_agent_preflight_loop.py use for loop._prs): the loop-level
    # contract under test is "the terminal is consulted and its outcome
    # gates the label", not the terminal's own internals or the
    # constructor's epic_manager/runner build path (covered above).
    loop._decomposer = decomposer
    loop._council = council
    return loop, state, pr


def _hitl_issue() -> dict:
    return {
        "number": 1,
        "title": "Stuck issue",
        "body": "x",
        "labels": [{"name": "hitl-escalation"}, {"name": "flaky-test-stuck"}],
    }


class TestAttemptCapPreCheckWiring:
    @pytest.mark.asyncio
    async def test_decompose_success_skips_human_required(self, tmp_path: Path) -> None:
        decomposer = AsyncMock()
        decomposer.create_epic_from_result = AsyncMock(return_value=777)
        council = AsyncMock()
        council.decide = AsyncMock(return_value=_decomp_result())
        loop, state, pr = _make_wired_loop(
            tmp_path, decomposer=decomposer, council=council
        )
        pr.list_issues_by_label = AsyncMock(return_value=[_hitl_issue()])

        result = await loop._do_work()

        pr.add_labels.assert_not_awaited()
        assert result["result_status"] == "skipped_decomposed"
        decomposer.create_epic_from_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_decompose_decline_still_marks_exhausted(
        self, tmp_path: Path
    ) -> None:
        """CRITICAL regression (ADR-0084): when the council declines, the
        pre-check site's existing human-required + auto-agent-exhausted
        behavior must fire exactly as it does with no decomposer wired at
        all (see test_auto_agent_preflight_loop.py::test_attempt_cap_marks_exhausted)."""
        decomposer = AsyncMock()
        council = AsyncMock()
        council.decide = AsyncMock(return_value=_decline_result())
        loop, state, pr = _make_wired_loop(
            tmp_path, decomposer=decomposer, council=council
        )
        pr.list_issues_by_label = AsyncMock(return_value=[_hitl_issue()])

        result = await loop._do_work()

        pr.add_labels.assert_awaited_with(1, ["human-required", "auto-agent-exhausted"])
        assert result["result_status"] == "skipped_exhausted"
        decomposer.create_epic_from_result.assert_not_awaited()


# ---------------------------------------------------------------------------
# Wiring: apply_decision's exhaustion + _LABEL_MAP needs_human/fatal path
# ---------------------------------------------------------------------------


def _preflight_result(status: str) -> PreflightResult:
    return PreflightResult(
        status=status,
        pr_url=None,
        diagnosis="diag",
        cost_usd=1.0,
        wall_clock_s=60.0,
        tokens=1000,
    )


class TestApplyDecisionDecomposeWiring:
    @pytest.mark.asyncio
    async def test_needs_human_decompose_success_skips_label(
        self, tmp_path: Path
    ) -> None:
        config, state, pr_port, decomposer, council = _make_deps(tmp_path)
        state.get_auto_agent_attempts = MagicMock(return_value=1)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=42)

        out = await apply_decision(
            issue_number=9,
            sub_label="x",
            result=_preflight_result("needs_human"),
            pr_port=pr_port,
            state=state,
            max_attempts=3,
            decomposer=decomposer,
            council=council,
            config=config,
            ctx=_ctx(issue_number=9),
        )

        assert out["decomposed"] is True
        pr_port.add_labels.assert_not_awaited()
        pr_port.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_needs_human_decompose_decline_still_adds_label(
        self, tmp_path: Path
    ) -> None:
        """CRITICAL regression: preserves ADR-0084's existing HITL path —
        matches test_preflight_decision.py::test_needs_human_adds_label's
        assertion exactly when the council declines."""
        config, state, pr_port, decomposer, council = _make_deps(tmp_path)
        state.get_auto_agent_attempts = MagicMock(return_value=1)
        council.decide = AsyncMock(return_value=_decline_result())

        out = await apply_decision(
            issue_number=9,
            sub_label="x",
            result=_preflight_result("needs_human"),
            pr_port=pr_port,
            state=state,
            max_attempts=3,
            decomposer=decomposer,
            council=council,
            config=config,
            ctx=_ctx(issue_number=9),
        )

        assert out["decomposed"] is False
        pr_port.add_labels.assert_awaited_with(9, ["human-required"])

    @pytest.mark.asyncio
    async def test_fatal_decompose_decline_still_adds_paired_label(
        self, tmp_path: Path
    ) -> None:
        config, state, pr_port, decomposer, council = _make_deps(tmp_path)
        state.get_auto_agent_attempts = MagicMock(return_value=1)
        council.decide = AsyncMock(return_value=_decline_result())

        out = await apply_decision(
            issue_number=9,
            sub_label="x",
            result=_preflight_result("fatal"),
            pr_port=pr_port,
            state=state,
            max_attempts=3,
            decomposer=decomposer,
            council=council,
            config=config,
            ctx=_ctx(issue_number=9),
        )

        assert out["decomposed"] is False
        pr_port.add_labels.assert_awaited_with(
            9, ["human-required", "auto-agent-fatal"]
        )

    @pytest.mark.asyncio
    async def test_resolved_never_attempts_decompose(self, tmp_path: Path) -> None:
        """`resolved` never carries human-required in its label set, so the
        council must not even be consulted."""
        config, state, pr_port, decomposer, council = _make_deps(tmp_path)
        state.get_auto_agent_attempts = MagicMock(return_value=1)
        council.decide = AsyncMock(
            side_effect=AssertionError("council must not be called on resolve")
        )

        out = await apply_decision(
            issue_number=9,
            sub_label="x",
            result=_preflight_result("resolved"),
            pr_port=pr_port,
            state=state,
            max_attempts=3,
            decomposer=decomposer,
            council=council,
            config=config,
            ctx=_ctx(issue_number=9),
        )

        assert out["decomposed"] is False
        council.decide.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_at_cap_decompose_success_skips_exhaustion_label(
        self, tmp_path: Path
    ) -> None:
        """The exhaustion top-up path (a `retry` that spends its budget)
        also redirects through decompose_or_escalate."""
        config, state, pr_port, decomposer, council = _make_deps(tmp_path)
        state.get_auto_agent_attempts = MagicMock(return_value=3)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=42)

        out = await apply_decision(
            issue_number=9,
            sub_label="x",
            result=_preflight_result("retry"),
            pr_port=pr_port,
            state=state,
            max_attempts=3,
            decomposer=decomposer,
            council=council,
            config=config,
            ctx=_ctx(issue_number=9),
        )

        assert out["decomposed"] is True
        assert out["exhausted"] is True
        pr_port.add_labels.assert_not_awaited()
