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
from subprocess_util import CreditExhaustedError
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
    # #11480 already-satisfied gate reads. Seeded with the real "no evidence"
    # shapes (an open issue, no PR detail, no base-branch history) rather than
    # bare AsyncMock returns, so a test that decomposes does so because the
    # gate found nothing — not because it choked on a MagicMock.
    prs.get_issue_state = AsyncMock(return_value="OPEN")
    prs.get_pr_title_and_body = AsyncMock(return_value=("", ""))
    prs.get_pr_checks = AsyncMock(return_value=[])
    prs.get_pr_reviews = AsyncMock(return_value=[])
    prs.get_pr_mergeable = AsyncMock(return_value=True)
    prs.list_branch_commits = AsyncMock(return_value=[])
    decomposer = AsyncMock()
    council = AsyncMock()
    return config, state, prs, decomposer, council


def _seed_open_pr(
    prs,
    *,
    branch: str,
    pr_number: int,
    title: str = "",
    body: str = "",
    draft: bool = False,
    checks: list[tuple[str, str]] | None = None,
    reviews: list[str] | None = None,
    mergeable: bool | None = True,
) -> None:
    """Seed *prs* so exactly *branch* carries an open PR with these details."""
    from models import PRInfo

    async def _find(b: str, *, issue_number: int = 0) -> PRInfo | None:
        if b != branch:
            return None
        return PRInfo(
            number=pr_number, issue_number=issue_number, branch=b, draft=draft
        )

    prs.find_open_pr_for_branch = AsyncMock(side_effect=_find)
    prs.get_pr_title_and_body = AsyncMock(return_value=(title, body))
    prs.get_pr_checks = AsyncMock(
        return_value=[
            {"name": name, "state": state}
            for name, state in (
                checks if checks is not None else [("quality", "SUCCESS")]
            )
        ]
    )
    prs.get_pr_reviews = AsyncMock(
        return_value=[{"author": "octocat", "state": s} for s in (reviews or [])]
    )
    prs.get_pr_mergeable = AsyncMock(return_value=mergeable)


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
# #11480: the already-satisfied gate — never re-slice work that already landed
# ---------------------------------------------------------------------------


class TestAlreadySatisfiedGate:
    """Each skip case pairs with a liveness counter-pin below it: the gate
    must recognise a landed fix WITHOUT quietly disabling the stall path."""

    @pytest.mark.asyncio
    async def test_closing_keyword_pr_on_auto_agent_branch_skips_decomposition(
        self, tmp_path: Path
    ) -> None:
        """#11427's exact shape: the fix lives on the auto-agent's own
        branch, which the old branch lookup never read."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(
            side_effect=AssertionError(
                "council must not be called — fix already landed"
            )
        )
        _seed_open_pr(
            prs,
            branch=config.auto_agent_branch_for_issue(11427),
            pr_number=11461,
            title="Fixes #11427: stop the frobnicator from stalling",
        )

        outcome = await decompose_or_escalate(
            issue_number=11427,
            ctx=_ctx(issue_number=11427),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "already-satisfied"
        council.decide.assert_not_called()
        decomposer.create_epic_from_result.assert_not_called()
        prs.close_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_closing_keyword_pr_on_manual_branch_skips_decomposition(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(side_effect=AssertionError("council must not run"))
        _seed_open_pr(
            prs,
            branch=config.branch_for_issue(7),
            pr_number=42,
            title="Some title",
            body="Resolves #7 — the whole thing.",
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

        assert outcome == "already-satisfied"
        decomposer.create_epic_from_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_landed_commit_on_base_branch_skips_decomposition(
        self, tmp_path: Path
    ) -> None:
        """The headline #11480 case: the fix merged hours ago and the issue
        just hasn't closed yet."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(side_effect=AssertionError("council must not run"))
        prs.list_branch_commits = AsyncMock(
            return_value=[
                {"date": "2026-08-18T09:00:00Z", "message": "chore: unrelated"},
                {
                    "date": "2026-08-18T07:08:00Z",
                    "message": "Fixes #11427: land the real fix (#11430)",
                },
            ]
        )

        outcome = await decompose_or_escalate(
            issue_number=11427,
            ctx=_ctx(issue_number=11427),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "already-satisfied"
        prs.list_branch_commits.assert_awaited_once_with(
            config.base_branch(), limit=100
        )
        decomposer.create_epic_from_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_closed_issue_skips_decomposition(self, tmp_path: Path) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(side_effect=AssertionError("council must not run"))
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "already-satisfied"
        decomposer.create_epic_from_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_posts_evidence_comment_once(self, tmp_path: Path) -> None:
        """The issue stays in the pipeline, so every later tick re-enters
        this path — the comment must not repeat."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")

        await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )
        prs.post_comment.assert_awaited_once()
        _, posted = prs.post_comment.call_args.args
        assert "already landed" in posted

        # Second tick: the marker is now in the gathered comments.
        from preflight.context import IssueComment

        prs.post_comment.reset_mock()
        await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(
                issue_number=7,
                issue_comments=[
                    IssueComment(author="hydraflow", body=posted, created_at="")
                ],
            ),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )
        prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skip_happens_before_the_depth_cap(self, tmp_path: Path) -> None:
        """A landed fix must not reach human-required either — the depth cap
        escalates, so the gate has to run ahead of it."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        state.get_all_epic_states = MagicMock(
            return_value={
                "900": EpicState(
                    epic_number=900,
                    title="Parent epic",
                    child_issues=[7],
                    decomposition_depth=config.max_decomposition_depth,
                )
            }
        )
        prs.get_issue_state = AsyncMock(return_value="COMPLETED")

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(issue_number=7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "already-satisfied"

    # --- Liveness counter-pins: a genuine stall must still decompose. ---

    @pytest.mark.asyncio
    async def test_genuinely_stalled_issue_with_no_landed_fix_still_decomposes(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        prs.list_branch_commits = AsyncMock(
            return_value=[{"date": "", "message": "Fixes #999: someone else's issue"}]
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
        decomposer.create_epic_from_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_red_ci_pr_still_decomposes(self, tmp_path: Path) -> None:
        """A PR that declares the fix but fails CI IS the stall — the gate
        must not read its title as success."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        _seed_open_pr(
            prs,
            branch=config.auto_agent_branch_for_issue(7),
            pr_number=42,
            title="Fixes #7: attempt three",
            checks=[("quality", "SUCCESS"), ("e2e", "FAILURE")],
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
        prs.close_pr.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_changes_requested_pr_still_decomposes(self, tmp_path: Path) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        _seed_open_pr(
            prs,
            branch=config.auto_agent_branch_for_issue(7),
            pr_number=42,
            title="Fixes #7: attempt three",
            reviews=["CHANGES_REQUESTED"],
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

    @pytest.mark.asyncio
    async def test_pr_with_no_ci_checks_still_decomposes(self, tmp_path: Path) -> None:
        """An empty check list is absence of evidence, not evidence of health."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        _seed_open_pr(
            prs,
            branch=config.auto_agent_branch_for_issue(7),
            pr_number=42,
            title="Fixes #7: attempt three",
            checks=[],
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

    @pytest.mark.asyncio
    async def test_unreadable_issue_state_still_decomposes(
        self, tmp_path: Path
    ) -> None:
        """`UNKNOWN` is how both adapters report an unreadable issue; it must
        never be mistaken for 'closed, so the work is done'."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        prs.get_issue_state = AsyncMock(return_value="UNKNOWN")

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

    @pytest.mark.asyncio
    async def test_draft_pr_is_not_evidence_of_a_landed_fix(
        self, tmp_path: Path
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        _seed_open_pr(
            prs,
            branch=config.auto_agent_branch_for_issue(7),
            pr_number=42,
            title="Fixes #7: work in progress",
            draft=True,
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


# ---------------------------------------------------------------------------
# #11480: every landed-fix read fails OPEN — and still lets a credit cap escape
# ---------------------------------------------------------------------------

# The six ``gh`` reads behind ``_find_landed_fix`` / ``_is_landing_fix_pr``,
# each wrapped in its own ``except Exception`` block. ``needs_landing_pr``
# says whether the read is only reached once an open PR declaring the fix
# exists (the four PR-detail reads) or only when no PR qualifies (the commit
# scan) — the issue-state read runs first regardless.
_LANDED_FIX_READS: list[tuple[str, bool]] = [
    ("get_issue_state", False),
    ("get_pr_title_and_body", True),
    ("get_pr_mergeable", True),
    ("get_pr_reviews", True),
    ("get_pr_checks", True),
    ("list_branch_commits", False),
]
_LANDED_FIX_READ_IDS = [seam for seam, _ in _LANDED_FIX_READS]


def _arm_landed_fix_read(
    prs, config, *, seam: str, needs_landing_pr: bool, exc: Exception
) -> None:
    """Make exactly *seam* raise *exc*, seeding a viable fix PR when the seam
    is only reachable through one."""
    if needs_landing_pr:
        _seed_open_pr(
            prs,
            branch=config.auto_agent_branch_for_issue(7),
            pr_number=42,
            title="Fixes #7: the landing fix",
        )
    setattr(prs, seam, AsyncMock(side_effect=exc))


class TestLandedFixReadsFailOpen:
    """An unreadable signal is "no evidence", not a verdict: the gate must
    fall through to today's decomposition path, or a flaky ``gh`` call would
    silently park a stalled issue forever."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("seam", "needs_landing_pr"), _LANDED_FIX_READS, ids=_LANDED_FIX_READ_IDS
    )
    async def test_read_failure_falls_through_to_decomposition(
        self, tmp_path: Path, seam: str, needs_landing_pr: bool
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        _arm_landed_fix_read(
            prs,
            config,
            seam=seam,
            needs_landing_pr=needs_landing_pr,
            exc=RuntimeError("gh api failed"),
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
        # The failing read was genuinely reached — the gate did not skip it.
        getattr(prs, seam).assert_awaited()
        decomposer.create_epic_from_result.assert_awaited_once()


class TestLandedFixReadsReraiseCredit:
    """``reraise_on_credit_or_bug`` is honoured at every seam: a credit cap
    raised by a read must reach the loop's pause handler, not be eaten as
    "no evidence" and then spent again on the council."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("seam", "needs_landing_pr"), _LANDED_FIX_READS, ids=_LANDED_FIX_READ_IDS
    )
    async def test_credit_exhaustion_propagates(
        self, tmp_path: Path, seam: str, needs_landing_pr: bool
    ) -> None:
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(
            side_effect=AssertionError("council must not run after a credit cap")
        )
        _arm_landed_fix_read(
            prs,
            config,
            seam=seam,
            needs_landing_pr=needs_landing_pr,
            exc=CreditExhaustedError("weekly limit reached"),
        )

        with pytest.raises(CreditExhaustedError):
            await decompose_or_escalate(
                issue_number=7,
                ctx=_ctx(issue_number=7),
                config=config,
                decomposer=decomposer,
                council=council,
                state=state,
                prs=prs,
            )

        council.decide.assert_not_called()
        decomposer.create_epic_from_result.assert_not_called()


# ---------------------------------------------------------------------------
# #11281 class: PR resolution must cover BOTH agent branch names
# ---------------------------------------------------------------------------


class TestPRResolutionCoversBothAgentBranches:
    @pytest.mark.asyncio
    async def test_supersede_closes_pr_on_the_auto_agent_branch(
        self, tmp_path: Path
    ) -> None:
        """Before #11480, `_find_pr_number` read only `agent/issue-{N}`, so
        the auto-agent's own PR was invisible: never superseded, and its diff
        never reached the council as salvage evidence."""
        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        _seed_open_pr(
            prs,
            branch=config.auto_agent_branch_for_issue(7),
            pr_number=4242,
            title="WIP: half a fix",
        )
        prs.get_pr_diff_names = AsyncMock(return_value=["src/frobnicator.py"])

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
        prs.close_pr.assert_awaited_once_with(4242)
        prs.get_pr_diff_names.assert_awaited_once_with(4242)

    @pytest.mark.asyncio
    async def test_manual_branch_wins_when_both_carry_a_pr(
        self, tmp_path: Path
    ) -> None:
        """`agent_branches_for_issue` documents manual-first precedence."""
        from models import PRInfo

        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        numbers = {
            config.branch_for_issue(7): 100,
            config.auto_agent_branch_for_issue(7): 200,
        }

        async def _find(branch: str, *, issue_number: int = 0) -> PRInfo:
            return PRInfo(
                number=numbers[branch], issue_number=issue_number, branch=branch
            )

        prs.find_open_pr_for_branch = AsyncMock(side_effect=_find)

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
        prs.close_pr.assert_awaited_once_with(100)

    @pytest.mark.asyncio
    async def test_supersede_never_closes_a_landing_fix_pr(
        self, tmp_path: Path
    ) -> None:
        """Defence in depth: `escalation_context.pr_number` bypasses branch
        resolution entirely, so the close path re-checks the PR itself."""
        from models import EscalationContext

        config, state, prs, decomposer, council = _make_deps(tmp_path)
        council.decide = AsyncMock(return_value=_decomp_result())
        decomposer.create_epic_from_result = AsyncMock(return_value=501)
        prs.get_pr_title_and_body = AsyncMock(
            return_value=("Fixes #7: the complete fix", "")
        )
        prs.get_pr_checks = AsyncMock(return_value=[{"name": "q", "state": "SUCCESS"}])

        outcome = await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(
                issue_number=7,
                escalation_context=EscalationContext(
                    cause="review-stuck", origin_phase="review", pr_number=888
                ),
            ),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

        assert outcome == "decomposed"
        prs.close_pr.assert_not_awaited()


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
    pr.get_issue_state = AsyncMock(return_value="OPEN")
    pr.get_pr_title_and_body = AsyncMock(return_value=("", ""))
    pr.get_pr_checks = AsyncMock(return_value=[])
    pr.get_pr_reviews = AsyncMock(return_value=[])
    pr.get_pr_mergeable = AsyncMock(return_value=True)
    pr.list_branch_commits = AsyncMock(return_value=[])
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

    @pytest.mark.asyncio
    async def test_already_satisfied_neither_decomposes_nor_pages_a_human(
        self, tmp_path: Path
    ) -> None:
        """#11480 at the loop seam: the attempt cap tripped on count, but a
        fix for the issue already landed — no epic, no human-required, and
        no TTL re-drive armed (that would page a human on a delay)."""
        decomposer = AsyncMock()
        council = AsyncMock()
        council.decide = AsyncMock(side_effect=AssertionError("council must not run"))
        loop, state, pr = _make_wired_loop(
            tmp_path, decomposer=decomposer, council=council
        )
        pr.list_issues_by_label = AsyncMock(return_value=[_hitl_issue()])
        pr.list_branch_commits = AsyncMock(
            return_value=[{"date": "", "message": "Fixes #1: already landed"}]
        )

        result = await loop._do_work()

        assert result["result_status"] == "skipped_already_satisfied"
        pr.add_labels.assert_not_awaited()
        decomposer.create_epic_from_result.assert_not_awaited()
        state.arm_auto_agent_redrive.assert_not_called()


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
    async def test_needs_human_already_satisfied_adds_no_label_or_comment(
        self, tmp_path: Path
    ) -> None:
        """#11480: the third outcome must not fall into the human-required
        path — `decomposed == False` alone used to guarantee exactly that."""
        config, state, pr_port, decomposer, council = _make_deps(tmp_path)
        state.get_auto_agent_attempts = MagicMock(return_value=1)
        council.decide = AsyncMock(side_effect=AssertionError("council must not run"))
        pr_port.get_issue_state = AsyncMock(return_value="COMPLETED")

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

        assert out["already_satisfied"] is True
        assert out["decomposed"] is False
        pr_port.add_labels.assert_not_awaited()
        # The evidence comment is the terminal's; apply_decision's own
        # attempt comment must not fire on top of it.
        pr_port.post_comment.assert_awaited_once()
        _, posted = pr_port.post_comment.call_args.args
        assert "already landed" in posted

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
