"""The Review canary's actuator, driven through its real seams (#11543).

The spawn is injected, so every test below runs the actuator's own code — the
real canary gate, the real independence fence, the real tier resolution, the
real parse, the real receipt construction — against a double at the one place it
touches the world. Nothing here is an ``AsyncMock`` of a port.

The classes follow P5's acceptance criteria: a reviewer sees canonical evidence
and nothing else, cannot self-review, cannot approve, cannot hide a finding, and
cannot be dispatched at all by a repository nobody armed.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import TYPE_CHECKING, Any

import pytest

from config import HydraFlowConfig
from driver_contracts import (
    WORKER_CATALOG,
    DriverLease,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    ReceiptStatus,
    RejectionReason,
    WorkerDispatchRequest,
    WorkerRole,
)
from execution import SimpleResult
from models import ReviewVerdict
from review_broker import review_roles_for_review_phase
from review_evidence import build_review_evidence
from review_worker_runner import (
    MAX_ARTIFACT_CHARS,
    MAX_DIFF_CHARS,
    MAX_FINDING_SUMMARY_CHARS,
    MAX_FINDINGS,
    NO_SUMMARY_PLACEHOLDER,
    ReviewWorkerRunner,
    build_review_worker_prompt,
    parse_review_proposal,
)
from scheduling_model import ExecutionRuntime, SchedulingModel

if TYPE_CHECKING:
    from pathlib import Path

    from review_evidence import ReviewEvidence

REPO = "acme/widgets"
REVIEW_LABEL = "hydraflow-review"
ROUTE_REVISION = "route-v1"
BRANCH = "agent/issue-7"
BASE = "a" * 40
HEAD = "b" * 40
OPUS = "claude-opus-4-7"

#: A string that exists nowhere in the canonical evidence. Anything carrying it
#: reached the prompt from somewhere it should not have.
PRIVATE = "IMPLEMENTER-ONLY-SENTINEL-9f31"


class SpawnRecorder:
    """Stands in for ``run_lightweight_agent`` and records every call."""

    def __init__(
        self,
        *,
        stdout: str = "",
        served: str | None = None,
        returncode: int = 0,
        spawned: bool = True,
        timed_out: bool = False,
        refused: tuple[str, str] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._stdout = stdout or json.dumps(
            {"recommended": "comment", "summary": "reads fine", "findings": []}
        )
        self._served = served
        self._returncode = returncode
        self._spawned = spawned
        self._timed_out = timed_out
        self._refused = refused

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls.append(kwargs)
        spawn_out = kwargs.get("spawn_out")
        if spawn_out is not None:
            spawn_out.update(
                {
                    "model": kwargs["model"],
                    "provider": "gateway",
                    "usage": {"input_tokens": 800, "output_tokens": 120},
                }
            )
            if self._spawned:
                spawn_out["spawned"] = True
            if self._served is not None:
                spawn_out["served_model"] = self._served
            if self._timed_out:
                spawn_out["timed_out"] = True
            if self._refused is not None:
                spawn_out["refused"], spawn_out["refused_outcome"] = self._refused
        return SimpleResult(stdout=self._stdout, returncode=self._returncode)

    @property
    def prompt(self) -> str:
        return str(self.calls[0]["prompt"])


class ExplodingSpawn:
    """A spawn that raises the way a gateway outage does."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls += 1
        raise self.error


def _config(tmp_path: Path, **overrides: object) -> HydraFlowConfig:
    fields: dict[str, Any] = {
        "state_file": tmp_path / "state.json",
        "repo": REPO,
        "workspace_base": tmp_path / "worktrees",
        "scheduling_model": SchedulingModel.ISSUE_CONTROLLER,
        "execution_runtime": ExecutionRuntime.FABLE_DIRECTOR,
        "fable_review_canary_repo": REPO,
    }
    fields.update(overrides)
    return HydraFlowConfig(**fields)


def _lease(*, epoch: int = 3) -> DriverLease:
    from datetime import UTC, datetime, timedelta

    return DriverLease(
        driver_id="drv-7",
        epoch=epoch,
        repo_slug=REPO,
        issue_number=7,
        phase=DriverPhase.REVIEW,
        expected_stage_label=REVIEW_LABEL,
        phase_attempt=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


def _request(
    *,
    role: WorkerRole = WorkerRole.REVIEWER,
    request_id: str = "req-1",
    key: str = "key-1",
    value: str = "claude-opus",
    spawn_id: str | None = "spawn-fresh",
    requirement: ModelRequirement | None = None,
) -> WorkerDispatchRequest:
    return WorkerDispatchRequest(
        request_id=request_id,
        driver_id="drv-7",
        epoch=3,
        phase_attempt=1,
        worker_role=role,
        model_requirement=requirement
        or ModelRequirement(kind=ModelRequirementKind.LITERAL_FAMILY, value=value),
        # Deliberately carries the private sentinel. A task contract is written
        # by a director that has read the implementer's receipts, so if this
        # module ever renders one, implementer-private context has a path in.
        task_contract=f"review the change {PRIVATE}",
        reason=f"the implement boundary finished {PRIVATE}",
        expected_route_policy_revision=ROUTE_REVISION,
        idempotency_key=key,
        requesting_spawn_id=spawn_id,
    )


def _evidence(**overrides: object) -> ReviewEvidence:
    source: dict[str, Any] = {
        "issue_number": 7,
        "issue_title": "make the widget faster",
        "issue_goal": "the widget takes 4s to render",
        "acceptance_criteria": ("renders under 400ms",),
        "plan_summary": "memoize the layout pass",
        "branch": BRANCH,
        "base_sha": BASE,
        "head_sha": HEAD,
        "diff": "--- a/widget.py\n+++ b/widget.py\n+cache = {}\n",
        "changed_files": ("widget.py",),
        "test_command": "make quality",
        "test_summary": "412 passed",
        "test_failures": (),
        # Never copied: absent from CANONICAL_FIELDS.
        "implementer_transcript": PRIVATE,
        "implementer_reasoning": PRIVATE,
    }
    source.update(overrides)
    return build_review_evidence(source)


def _runner(
    tmp_path: Path, spawn: Any, **config_overrides: object
) -> ReviewWorkerRunner:
    class _NoRunner:
        async def run_simple(self, *args: Any, **kwargs: Any) -> SimpleResult:
            raise AssertionError("the review actuator ran a subprocess of its own")

    return ReviewWorkerRunner(
        config=_config(tmp_path, **config_overrides),
        route_policy_revision=ROUTE_REVISION,
        runner=_NoRunner(),  # type: ignore[arg-type]
        spawn=spawn,
    )


async def _dispatch(
    runner: ReviewWorkerRunner,
    requests: Any,
    *,
    evidence: ReviewEvidence | None = None,
    fence: Any = None,
    implementers: Any = (),
) -> Any:
    return await runner.dispatch(
        requests,
        evidence=evidence or _evidence(),
        issue_labels=(REVIEW_LABEL,),
        lease=_lease(),
        phase=DriverPhase.REVIEW,
        fence=fence or (lambda: None),
        implementer_spawn_ids=implementers,
    )


# ---------------------------------------------------------------------------
# What the runner has no authority to do
# ---------------------------------------------------------------------------


class TestAnUnarmedRepositoryDispatchesNothing:
    @pytest.mark.asyncio
    async def test_an_empty_dial_starts_no_child(self, tmp_path: Path) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn, fable_review_canary_repo="")

        receipts = await _dispatch(runner, [_request()])

        assert spawn.calls == []
        assert receipts[0].status is ReceiptStatus.REJECTED
        # An unarmed dial says nothing about the ROLE (#11543). This asserted
        # ROLE_PHASE_FORBIDDEN, which claims the catalogue forbids a reviewer
        # at REVIEW — it does not — and pinned that claim as correct.
        assert receipts[0].reason_code is RejectionReason.OUTSIDE_CANARY_BOUND

    @pytest.mark.asyncio
    async def test_another_repositorys_dial_arms_nothing_here(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn, fable_review_canary_repo="acme/other")

        receipts = await _dispatch(runner, [_request()])

        assert spawn.calls == []
        assert receipts[0].reason_code is RejectionReason.OUTSIDE_CANARY_BOUND

    @pytest.mark.asyncio
    async def test_a_non_review_boundary_dispatches_nothing(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        receipts = await runner.dispatch(
            [_request()],
            evidence=_evidence(),
            issue_labels=(REVIEW_LABEL,),
            lease=_lease(),
            phase=DriverPhase.IMPLEMENT,
            fence=lambda: None,
        )

        assert spawn.calls == []
        # The canary's phase clause, not the catalogue's. This read
        # ROLE_PHASE_FORBIDDEN, which is accurate here only by accident — the
        # runner never looks at the role, so the same code was minted for a
        # debugger at IMPLEMENT, which the catalogue plainly allows (#11543).
        assert receipts[0].reason_code is RejectionReason.OUTSIDE_CANARY_BOUND

    @pytest.mark.asyncio
    async def test_clearing_the_dial_mid_batch_stops_the_next_child(
        self, tmp_path: Path
    ) -> None:
        """The bound is read per request, which is what makes clearing it the
        whole rollback: a batch already running stops at its next child rather
        than finishing on the strength of a dial nobody has read since."""
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        def disarm() -> RejectionReason | None:
            object.__setattr__(runner._config, "fable_review_canary_repo", "")
            return None

        receipts = await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(request_id="req-2", key="key-2"),
            ],
            fence=disarm,
        )

        assert len(spawn.calls) == 1
        assert receipts[0].status is ReceiptStatus.ACCEPTED
        # Cleared mid-batch: the second child is outside the bound, which is
        # not a statement about its role (#11543).
        assert receipts[1].reason_code is RejectionReason.OUTSIDE_CANARY_BOUND


class TestAReviewerCannotReviewItsOwnWork:
    @pytest.mark.asyncio
    async def test_the_implementers_own_spawn_is_refused(self, tmp_path: Path) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        receipts = await _dispatch(
            runner,
            [_request(spawn_id="spawn-abc")],
            implementers={"spawn-abc"},
        )

        assert spawn.calls == []
        assert receipts[0].reason_code is RejectionReason.SELF_REVIEW_FORBIDDEN
        assert receipts[0].status is ReceiptStatus.REJECTED

    @pytest.mark.asyncio
    async def test_the_refusal_log_follows_the_reason_not_the_variable_name(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two reasons reach this arm now, and they say different things.

        The fence returns ``SELF_REVIEW_FORBIDDEN`` *or* ``LINEAGE_UNKNOWN``
        (#11543). One log line served both, so a request that merely failed to
        state its lineage was reported as "would review its own work (spawn
        None)" — asserting a fact nothing established and then rendering
        ``None`` as the evidence for it. Same dishonest-reason-code defect this
        phase already fixed in ``adjudicate``, arriving through a new enum
        member. Nothing pinned the message, so nothing reddened.
        """
        runner = _runner(tmp_path, SpawnRecorder())
        blank = _request().model_copy(update={"requesting_spawn_id": "   "})

        with caplog.at_level(logging.INFO):
            receipts = await _dispatch(runner, [blank], implementers={"spawn-abc"})

        assert receipts[0].reason_code is RejectionReason.LINEAGE_UNKNOWN
        assert "states no lineage" in caplog.text
        assert "would review its own work" not in caplog.text

    @pytest.mark.asyncio
    async def test_the_self_review_log_still_says_self_review(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-vacuity: the other branch must keep its own accurate wording."""
        runner = _runner(tmp_path, SpawnRecorder())

        with caplog.at_level(logging.INFO):
            await _dispatch(
                runner, [_request(spawn_id="spawn-abc")], implementers={"spawn-abc"}
            )

        assert "would review its own work" in caplog.text
        assert "states no lineage" not in caplog.text

    @pytest.mark.asyncio
    async def test_a_fresh_spawn_is_admitted(self, tmp_path: Path) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        receipts = await _dispatch(
            runner,
            [_request(spawn_id="spawn-fresh")],
            implementers={"spawn-abc"},
        )

        assert len(spawn.calls) == 1
        assert receipts[0].status is ReceiptStatus.ACCEPTED

    @pytest.mark.parametrize("role", sorted(review_roles_for_review_phase(), key=str))
    @pytest.mark.asyncio
    async def test_every_dispatchable_review_role_is_fenced(
        self, tmp_path: Path, role: WorkerRole
    ) -> None:
        """No role this runner can dispatch at REVIEW escapes the fence.

        The subject is READ from ``review_roles_for_review_phase()`` rather
        than named, and that is load-bearing rather than tidy. The first
        version of this test picked ``architect`` by hand as "a role the
        catalogue does not call independent", to prove the runner holds no
        second opinion about independence. #11699 then fenced ``architect``
        and filtered the REVIEW menu to ``WriteScope.NONE``, which dropped
        ``debugger`` out of it — and the hand-picked test kept passing for a
        completely different reason: its request was refused as *not catalogued
        for REVIEW* and never reached the fence at all. A test that names a
        role as a probe is one catalogue edit away from measuring nothing.

        So the property is stated over the menu itself: dispatch every role the
        runner can actually dispatch, with lineage that collides with a known
        implementer, and require the fence to stop each one. Widening the menu
        to a role the fence does not cover reddens this; so does un-fencing a
        role already on it.
        """
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        receipts = await _dispatch(
            runner,
            [
                _request(
                    role=role,
                    # The catalogue's own default, so a role whose requirement
                    # is a capability class rather than a literal family still
                    # builds a legal request.
                    requirement=WORKER_CATALOG[role].default_model,
                    spawn_id="spawn-abc",
                )
            ],
            implementers={"spawn-abc"},
        )

        assert spawn.calls == []
        assert receipts[0].reason_code is RejectionReason.SELF_REVIEW_FORBIDDEN

    def test_the_review_menu_is_not_empty(self) -> None:
        """Negative control for the parametrize above: an empty menu would make
        it collect zero cases and report green over nothing."""
        assert review_roles_for_review_phase()

    @pytest.mark.asyncio
    async def test_the_implementer_set_is_materialised_once(
        self, tmp_path: Path
    ) -> None:
        """A generator drained by the first request would leave every request
        after it comparing against nothing — a fence that stops one reviewer
        and waves the rest through, green in any one-request test."""
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        receipts = await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1", spawn_id="spawn-abc"),
                _request(request_id="req-2", key="key-2", spawn_id="spawn-abc"),
            ],
            implementers=(s for s in ["spawn-abc"]),
        )

        assert spawn.calls == []
        assert [r.reason_code for r in receipts] == [
            RejectionReason.SELF_REVIEW_FORBIDDEN,
            RejectionReason.SELF_REVIEW_FORBIDDEN,
        ]


class TestItProducesAProposalAndNeverAVerdict:
    def test_the_module_does_not_reach_the_adjudicator(self) -> None:
        """``adjudicate`` is the only function that produces a verdict, and this
        module cannot call it: it imports no such name, binds no such name, and
        calls nothing by that name. Read from the AST rather than from the text
        so the prose that *explains* the rule cannot satisfy the test for it."""
        import ast

        import review_worker_runner

        tree = ast.parse(inspect.getsource(review_worker_runner))
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "adjudicate" not in imported
        assert "adjudicate" not in called
        assert "ReviewVerdict" not in imported
        assert not hasattr(review_worker_runner, "adjudicate")

    def test_a_proposal_has_no_field_that_could_carry_a_verdict(self) -> None:
        from review_authority import ReviewProposal

        assert set(ReviewProposal.model_fields) == {
            "recommended",
            "findings",
            "summary",
        }

    @pytest.mark.asyncio
    async def test_an_accepted_reviewer_leaves_a_proposal_not_a_decision(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder(
            stdout=json.dumps(
                {
                    "recommended": "approve",
                    "summary": "clean",
                    "findings": [{"summary": "leaks a handle", "file": "widget.py"}],
                }
            )
        )
        runner = _runner(tmp_path, spawn)

        receipts = await _dispatch(runner, [_request()])

        proposal = runner.last_proposals["req-1"]
        # The recommendation is recorded exactly as given — unchanged, and
        # unadjudicated. Resolving it against its own blocking finding is
        # ``adjudicate``'s job, and this module must not pre-empt it in either
        # direction.
        assert proposal.recommended is ReviewVerdict.APPROVE
        assert proposal.findings[0].blocking is True
        assert receipts[0].output_contract_ok is True

    @pytest.mark.asyncio
    async def test_the_proposal_is_what_the_adjudicator_then_resolves(
        self, tmp_path: Path
    ) -> None:
        """End to end: a reviewer recommending approval over a blocking finding
        does not get approval. The runner carries the opinion; the adjudicator
        decides."""
        from review_authority import adjudicate

        spawn = SpawnRecorder(
            stdout=json.dumps(
                {
                    "recommended": "approve",
                    "summary": "clean",
                    "findings": [{"summary": "off-by-one"}],
                }
            )
        )
        runner = _runner(tmp_path, spawn)
        await _dispatch(runner, [_request()])

        verdict, _reason = adjudicate(
            runner.last_proposals["req-1"],
            ci_green=True,
            hitl_required=False,
            reviewer_independent=True,
            evidence_head_sha=HEAD,
            current_head_sha=HEAD,
        )

        assert verdict is ReviewVerdict.REQUEST_CHANGES


# ---------------------------------------------------------------------------
# The prompt: canonical evidence and nothing else
# ---------------------------------------------------------------------------


class TestThePromptIsBuiltFromEvidenceAndNothingElse:
    def test_the_signature_admits_only_a_role_and_an_evidence(self) -> None:
        """The guarantee is structural. A parameter for a task contract, a
        rationale or a prior receipt is a path implementer-private context can
        take, so there is none."""
        params = inspect.signature(build_review_worker_prompt).parameters
        assert set(params) == {"role", "evidence"}

    @pytest.mark.asyncio
    async def test_no_private_context_reaches_the_child(self, tmp_path: Path) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        await _dispatch(runner, [_request()])

        assert PRIVATE not in spawn.prompt
        assert "task_contract" not in spawn.prompt

    def test_the_evidence_itself_never_carried_the_private_fields(self) -> None:
        from review_evidence import private_markers_in

        assert private_markers_in(_evidence().as_payload()) == ()

    def test_the_bounded_slice_is_stated_to_the_worker(self) -> None:
        """Not merely that the three tokens appear — that the worker is told
        they BOUND its review. A prompt that printed a branch, a base and a
        HEAD without saying the review is about that snapshot and no other
        would carry every token this test could check and none of its meaning.
        """
        prompt = build_review_worker_prompt(role="reviewer", evidence=_evidence())

        assert "one exact snapshot and nothing else" in prompt
        assert BRANCH in prompt
        assert BASE in prompt
        assert HEAD in prompt
        assert "has moved by the time you" in prompt
        assert "discarded" in prompt

    def test_the_worker_is_told_what_it_cannot_do(self) -> None:
        prompt = build_review_worker_prompt(role="reviewer", evidence=_evidence())

        for phrase in ("no shell", "no repository access", "merge", "approve"):
            assert phrase in prompt, phrase
        assert "move a label" in prompt

    def test_the_instruction_leads_and_the_payload_is_last(self) -> None:
        """ADR-0087's long-context placement rule, asserted rather than assumed."""
        prompt = build_review_worker_prompt(role="reviewer", evidence=_evidence())

        assert prompt.index("Review one bounded change") < prompt.index("<issue ")
        assert prompt.index("Respond with one JSON object") < prompt.index("<diff ")
        assert prompt.rstrip().endswith("</tests>")

    def test_a_truncated_diff_is_announced(self) -> None:
        prompt = build_review_worker_prompt(
            role="reviewer", evidence=_evidence(diff="+" * (MAX_DIFF_CHARS + 500))
        )

        assert "(TRUNCATED at" in prompt
        assert len(prompt) < MAX_DIFF_CHARS + 6000

    def test_an_untruncated_diff_is_not_announced(self) -> None:
        prompt = build_review_worker_prompt(role="reviewer", evidence=_evidence())

        assert "(TRUNCATED at" not in prompt

    def test_an_empty_diff_says_so_rather_than_showing_a_blank(self) -> None:
        prompt = build_review_worker_prompt(
            role="reviewer", evidence=_evidence(diff="")
        )

        assert "the diff supplied with this evidence is empty" in prompt

    def test_a_quoted_issue_title_cannot_break_the_payload_block(self) -> None:
        """A title carrying a delimiter would close the pseudo-tag early and
        leave the rest of it reading as markup — a reviewer parsing a broken
        block is being shown something other than the evidence it was handed."""
        prompt = build_review_worker_prompt(
            role="reviewer",
            evidence=_evidence(issue_title='the "fast" path\nis slow'),
        )

        opening = next(
            line for line in prompt.splitlines() if line.startswith("<issue ")
        )
        assert opening.endswith('">')
        assert opening.count('"') == 4

    def test_missing_criteria_read_as_missing_not_as_none_required(self) -> None:
        prompt = build_review_worker_prompt(
            role="reviewer", evidence=_evidence(acceptance_criteria=())
        )

        assert "(none supplied)" in prompt


# ---------------------------------------------------------------------------
# Parsing a reply into a proposal
# ---------------------------------------------------------------------------


class TestParsingAReplyIntoAProposal:
    def test_a_bare_json_object_parses(self) -> None:
        proposal = parse_review_proposal(
            json.dumps({"recommended": "comment", "summary": "ok", "findings": []})
        )

        assert proposal is not None
        assert proposal.recommended is ReviewVerdict.COMMENT

    def test_a_fenced_object_parses(self) -> None:
        proposal = parse_review_proposal(
            '```json\n{"recommended": "approve", "findings": []}\n```'
        )

        assert proposal is not None
        assert proposal.recommended is ReviewVerdict.APPROVE

    def test_an_object_wrapped_in_prose_parses(self) -> None:
        proposal = parse_review_proposal(
            'Here is my review.\n{"recommended": "request-changes", "findings": []}\n'
        )

        assert proposal is not None
        assert proposal.recommended is ReviewVerdict.REQUEST_CHANGES

    @pytest.mark.parametrize(
        "reply",
        [
            pytest.param("no json at all", id="prose"),
            pytest.param("", id="empty"),
            pytest.param('{"summary": "no recommendation"}', id="no-recommendation"),
            pytest.param('{"recommended": "lgtm"}', id="invented-verdict"),
            pytest.param('{"recommended": "approve", "findings": "none"}', id="scalar"),
            pytest.param("[1, 2, 3]", id="not-an-object"),
        ],
    )
    def test_an_unusable_reply_yields_no_proposal(self, reply: str) -> None:
        """``None``, never a stand-in. An empty APPROVE would invent a clean
        review nobody performed; an empty REQUEST_CHANGES would invent a
        blocking judgement with no finding behind it."""
        assert parse_review_proposal(reply) is None

    def test_a_smuggled_verdict_key_is_never_read(self) -> None:
        """The allow-list, applied to the reply as well as to the evidence."""
        proposal = parse_review_proposal(
            json.dumps(
                {
                    "recommended": "comment",
                    "verdict": "approve",
                    "merge": True,
                    "findings": [],
                }
            )
        )

        assert proposal is not None
        assert proposal.recommended is ReviewVerdict.COMMENT
        assert not hasattr(proposal, "verdict")

    def test_a_finding_blocks_unless_it_says_literal_false(self) -> None:
        proposal = parse_review_proposal(
            json.dumps(
                {
                    "recommended": "comment",
                    "findings": [
                        {"summary": "absent"},
                        {"summary": "string no", "blocking": "no"},
                        {"summary": "zero", "blocking": 0},
                        {"summary": "explicit", "blocking": False},
                    ],
                }
            )
        )

        assert proposal is not None
        assert [f.blocking for f in proposal.findings] == [True, True, True, False]

    def test_a_finding_with_no_prose_is_kept_rather_than_dropped(self) -> None:
        """Dropping it would be the parser hiding a finding, which is the first
        thing P5 says a Fable reviewer must not be able to do."""
        proposal = parse_review_proposal(
            json.dumps({"recommended": "comment", "findings": [{"summary": ""}]})
        )

        assert proposal is not None
        assert proposal.findings[0].summary == NO_SUMMARY_PLACEHOLDER
        assert proposal.findings[0].blocking is True

    def test_a_bare_string_finding_is_kept(self) -> None:
        proposal = parse_review_proposal(
            json.dumps(
                {"recommended": "comment", "findings": ["the retry double-counts"]}
            )
        )

        assert proposal is not None
        assert proposal.findings[0].summary == "the retry double-counts"
        assert proposal.findings[0].blocking is True

    def test_over_long_prose_is_trimmed_rather_than_losing_the_proposal(self) -> None:
        proposal = parse_review_proposal(
            json.dumps(
                {
                    "recommended": "request-changes",
                    "summary": "x" * 20000,
                    "findings": [{"summary": "y" * 5000, "blocking": True}],
                }
            )
        )

        assert proposal is not None
        assert proposal.findings[0].blocking is True
        assert proposal.summary.endswith("…")

    def test_an_unusable_line_number_does_not_lose_the_finding(self) -> None:
        proposal = parse_review_proposal(
            json.dumps(
                {
                    "recommended": "comment",
                    "findings": [{"summary": "here", "line": "somewhere"}],
                }
            )
        )

        assert proposal is not None
        assert proposal.findings[0].line is None

    def test_too_many_findings_is_refused_whole_not_trimmed(self) -> None:
        """Trimming would silently drop the findings past the bound. Refusing
        loses the proposal and says so on the receipt, which is honest."""
        reply = json.dumps(
            {
                "recommended": "request-changes",
                "findings": [{"summary": f"f{i}"} for i in range(MAX_FINDINGS + 1)],
            }
        )

        assert parse_review_proposal(reply) is None

    def test_exactly_the_bound_is_still_accepted(self) -> None:
        reply = json.dumps(
            {
                "recommended": "request-changes",
                "findings": [{"summary": f"f{i}"} for i in range(MAX_FINDINGS)],
            }
        )

        proposal = parse_review_proposal(reply)

        assert proposal is not None
        assert len(proposal.findings) == MAX_FINDINGS


# ---------------------------------------------------------------------------
# Receipts, lineage and budget
# ---------------------------------------------------------------------------


class TestTheReceiptIsTheEvidence:
    @pytest.mark.asyncio
    async def test_an_accepted_receipt_carries_lineage_model_and_cost(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder(served=OPUS)
        runner = _runner(tmp_path, spawn)

        receipts = await _dispatch(runner, [_request()])

        receipt = receipts[0]
        assert receipt.status is ReceiptStatus.ACCEPTED
        assert receipt.served_model == OPUS
        assert receipt.lineage is not None
        assert receipt.lineage.driver_id == "drv-7"
        assert receipt.lineage.epoch == 3
        assert receipt.lineage.depth == 1
        assert receipt.artifact_digest is not None
        assert receipt.usd_cost >= 0.0
        assert runner.last_decision_ids["req-1"]

    @pytest.mark.asyncio
    async def test_the_artifact_names_the_snapshot_it_reviewed(
        self, tmp_path: Path
    ) -> None:
        """Without the head sha the adjudicator's staleness check has nothing to
        compare: a review of a branch that has moved is not a review of what
        would merge."""
        runner = _runner(tmp_path, SpawnRecorder())

        await _dispatch(runner, [_request()])

        assert runner.artifacts[0].head_sha == HEAD

    @pytest.mark.asyncio
    async def test_an_unobserved_model_is_recorded_as_unobserved(
        self, tmp_path: Path
    ) -> None:
        runner = _runner(tmp_path, SpawnRecorder(served=None))

        await _dispatch(runner, [_request()])

        assert runner.artifacts[0].model_observed is False
        assert runner.artifacts[0].served_model == OPUS

    @pytest.mark.asyncio
    async def test_an_unparseable_reply_fails_the_output_contract(
        self, tmp_path: Path
    ) -> None:
        runner = _runner(tmp_path, SpawnRecorder(stdout="I think it looks fine!"))

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].status is ReceiptStatus.ACCEPTED
        assert receipts[0].output_contract_ok is False
        assert "req-1" not in runner.last_proposals
        assert runner.artifacts[0].proposal is None

    @pytest.mark.asyncio
    async def test_a_proposal_longer_than_the_retained_artifact_still_parses(
        self, tmp_path: Path
    ) -> None:
        """The reply is parsed whole and truncated only for storage.

        A maximally compliant proposal is larger than MAX_ARTIFACT_CHARS, so
        truncating before parsing would cut legal JSON mid-object and record an
        output-contract failure for a reviewer that filed fifty findings — this
        module hiding findings by accident, which is the one thing MAX_FINDINGS
        refuses to do on purpose.
        """
        reply = json.dumps(
            {
                "recommended": "request-changes",
                "summary": "s" * 3000,
                "findings": [
                    {"summary": f"{i:03d}" + "f" * (MAX_FINDING_SUMMARY_CHARS - 3)}
                    for i in range(MAX_FINDINGS)
                ],
            }
        )
        assert len(reply) > MAX_ARTIFACT_CHARS, "the fixture must exceed the cut"
        runner = _runner(tmp_path, SpawnRecorder(stdout=reply))

        receipts = await _dispatch(runner, [_request()])

        proposal = runner.last_proposals["req-1"]
        assert len(proposal.findings) == MAX_FINDINGS
        assert receipts[0].output_contract_ok is True
        # The stored artifact is still bounded — the two limits are separate.
        assert len(runner.artifacts[0].text) == MAX_ARTIFACT_CHARS

    @pytest.mark.asyncio
    async def test_a_timed_out_child_is_expired_and_keeps_its_spawn_id(
        self, tmp_path: Path
    ) -> None:
        runner = _runner(tmp_path, SpawnRecorder(timed_out=True, returncode=-1))

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].status is ReceiptStatus.EXPIRED
        assert receipts[0].reason_code is RejectionReason.WORKER_TIMEOUT
        assert receipts[0].lineage is not None

    @pytest.mark.asyncio
    async def test_a_deadline_outside_the_seam_before_a_child_exists(
        self, tmp_path: Path
    ) -> None:
        """``TimeoutError`` escaping the seam comes from the work *around* the
        spawn — the CH-6 gate, the enforcement threads, a Docker socket. No
        child existed, so the receipt must not carry a spawn id."""
        runner = _runner(tmp_path, ExplodingSpawn(TimeoutError("gate")))

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].status is ReceiptStatus.EXPIRED
        assert receipts[0].reason_code is RejectionReason.WORKER_TIMEOUT
        assert receipts[0].lineage is None

    @pytest.mark.asyncio
    async def test_a_deadline_after_a_child_started_keeps_its_spawn_id(
        self, tmp_path: Path
    ) -> None:
        """The other half: the seam's outer ``finally`` raising after a child
        ran. It existed and was billed, and a receipt that hid its spawn id
        would make it indistinguishable from work that never began."""

        class _LateTimeout:
            async def __call__(self, **kwargs: Any) -> SimpleResult:
                kwargs["spawn_out"]["spawned"] = True
                raise TimeoutError("cleanup")

        runner = _runner(tmp_path, _LateTimeout())

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].status is ReceiptStatus.EXPIRED
        assert receipts[0].lineage is not None

    @pytest.mark.asyncio
    async def test_a_child_that_never_started_carries_no_spawn_id(
        self, tmp_path: Path
    ) -> None:
        runner = _runner(tmp_path, SpawnRecorder(spawned=False, returncode=-1))

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].status is ReceiptStatus.REJECTED
        assert receipts[0].lineage is None

    @pytest.mark.asyncio
    async def test_an_inadmissible_route_is_not_reported_as_retryable(
        self, tmp_path: Path
    ) -> None:
        """The classification comes from ``plan_broker.refusal_for_spawn``, so
        the three actuators cannot disagree about what a routing refusal means
        — the divergence #11670 paid for."""
        runner = _runner(
            tmp_path,
            SpawnRecorder(
                spawned=False, returncode=-1, refused=("model-not-allowed", "rejected")
            ),
        )

        receipts = await _dispatch(runner, [_request()])

        assert (
            receipts[0].reason_code is RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )

    @pytest.mark.asyncio
    async def test_a_substituted_model_refuses_rather_than_recording_it(
        self, tmp_path: Path
    ) -> None:
        runner = _runner(tmp_path, SpawnRecorder(served="glm-4.6"))

        receipts = await _dispatch(runner, [_request()])

        assert (
            receipts[0].reason_code is RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
        )
        assert receipts[0].served_model is None

    @pytest.mark.asyncio
    async def test_credit_exhaustion_leaves_the_boundary(self, tmp_path: Path) -> None:
        """A burnt balance is factory-wide and must not be converted into a
        worker refusal that burns attempt budget against it (dark-factory 2.2)."""
        from subprocess_util import CreditExhaustedError

        spawn = ExplodingSpawn(CreditExhaustedError("out of credit"))
        runner = _runner(tmp_path, spawn)

        with pytest.raises(CreditExhaustedError):
            await _dispatch(runner, [_request()])

    @pytest.mark.asyncio
    async def test_an_ordinary_spawn_failure_becomes_a_receipt(
        self, tmp_path: Path
    ) -> None:
        spawn = ExplodingSpawn(ConnectionError("gateway down"))
        runner = _runner(tmp_path, spawn)

        receipts = await _dispatch(runner, [_request()])

        assert receipts[0].reason_code is RejectionReason.ROUTE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_a_replayed_idempotency_key_starts_no_second_child(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        await _dispatch(runner, [_request()])
        receipts = await _dispatch(runner, [_request()])

        assert len(spawn.calls) == 1
        assert receipts[0].reason_code is RejectionReason.DUPLICATE_IDEMPOTENCY_KEY

    @pytest.mark.asyncio
    async def test_the_fence_is_re_read_before_each_spawn(self, tmp_path: Path) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)
        answers = [None, RejectionReason.STOP_FENCE]

        receipts = await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(request_id="req-2", key="key-2"),
            ],
            fence=lambda: answers.pop(0),
        )

        assert len(spawn.calls) == 1
        assert receipts[1].reason_code is RejectionReason.STOP_FENCE

    @pytest.mark.asyncio
    async def test_a_spent_batch_budget_expires_the_rest_replayably(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refused *before* the key is claimed: a request that never ran must
        stay replayable.

        The clock is patched on the MODULE OBJECT rather than on ``time``
        itself, so nothing else running in this process — asyncio included —
        sees a monotonic clock that jumps a minute per read.
        """
        import review_worker_runner

        class _JumpingClock:
            def __init__(self) -> None:
                self._now = 0.0

            def monotonic(self) -> float:
                self._now += 60.0
                return self._now

        monkeypatch.setattr(review_worker_runner, "time", _JumpingClock())
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn, fable_review_worker_timeout_seconds=30)

        receipts = await _dispatch(
            runner,
            [
                _request(request_id="req-1", key="key-1"),
                _request(request_id="req-2", key="key-2"),
            ],
        )

        assert receipts[-1].status is ReceiptStatus.EXPIRED
        assert receipts[-1].reason_code is RejectionReason.WORKER_TIMEOUT
        assert receipts[-1].lineage is None
        # Never claimed, so the same key is still dispatchable once the fleet
        # has time for it again.
        assert "key-2" not in runner._dispatched_keys

    @pytest.mark.asyncio
    async def test_a_blank_decision_produces_a_blank_join(self, tmp_path: Path) -> None:
        """A refused receipt must not inherit the previous batch's decision id
        — the join #11657 found recording a false one."""
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)
        await _dispatch(runner, [_request()])

        receipts = runner.refuse([_request()], RejectionReason.STOP_FENCE)

        assert runner.last_decision_ids == {"req-1": ""}
        assert runner.last_proposals == {}
        assert receipts[0].served_model is None

    def test_the_default_spawn_is_the_real_seam(self, tmp_path: Path) -> None:
        """An injection point nobody checks is a seam in name only."""
        import review_worker_runner

        runner = ReviewWorkerRunner(
            config=_config(tmp_path),
            route_policy_revision=ROUTE_REVISION,
            runner=object(),  # type: ignore[arg-type]
        )

        assert runner.spawn is review_worker_runner._spawn_review_worker

    @pytest.mark.asyncio
    async def test_the_child_is_pinned_to_the_gateway_and_named_by_its_role(
        self, tmp_path: Path
    ) -> None:
        spawn = SpawnRecorder()
        runner = _runner(tmp_path, spawn)

        await _dispatch(runner, [_request()])

        call = spawn.calls[0]
        assert call["provider"] == "gateway"
        assert call["source"] == WorkerRole.REVIEWER.value
        assert call["model"] == OPUS
        assert call["issue_labels"] == (REVIEW_LABEL,)
        assert call["issue_number"] == 7
