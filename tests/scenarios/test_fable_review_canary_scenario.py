"""MockWorld scenario: a fresh brokered Opus reviewer, end to end (#11543).

The unit tests prove each piece against doubles. This proves the *integration* —
what neither the unit layer nor an architecture guard can see:

* the whole chain runs through the **real** seams. A real ``DriverManager``
  allocator, a real ``IssueDriver`` boundary, a real ``ReviewPhaseAdapter`` over
  the deterministic reviewer, a real ``ShadowDispatchBroker`` admission, a real
  ``ReviewWorkerRunner`` — including its real evidence gathering — and the real
  ``runner_utils.run_lightweight_agent`` spawn seam with its real per-spawn
  ``resolve_harness_env`` mint, env scrub and revoke. The only doubles are at
  the ports: ``FakeGitHub`` behind the real label adapter, a store-shaped queue,
  a recording gateway control plane, and one subprocess boundary that answers
  ``git`` reads from a table and the CLI with a result envelope. **No
  ``AsyncMock`` of a port anywhere**;
* the brokered review and a Classic review reach the **same canonical label
  outcome**, because the canary adds a judge beside the deterministic phase and
  takes no authority from it — P5's "one issue can complete the same canonical
  workflow under Classic and Fable presets", observed rather than asserted;
* the reviewer really is **fresh**: the prompt that reaches the real spawn seam
  carries the canonical evidence and none of the private context that was
  sitting one attribute away from it on the request the director wrote.

The director's *turn* is scripted rather than spawned: spawning a real CLI is
what the air-gap seam forbids, and ``director_turn_runner`` is ``config_disable``
for exactly that reason. Everything downstream of the turn is real.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from director_broker import ShadowDispatchBroker
from director_sandbox import ProbeEvidence
from director_shadow_log import ShadowObservationLog
from director_turn_runner import CAPSULE_CLOSE, CAPSULE_OPEN, DirectorTurnResult
from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from driver_manager import DriverManager, PipelineLabelAdapter
from driver_ownership import DriverOwnershipRegistry
from driver_phase_adapters import ReviewPhaseAdapter
from fable_director import FableDirector
from gateway_mint_client import GatewayMintCredential
from models import GitHubIssue, PRInfo, ReviewResult, ReviewVerdict, Task
from review_broker import review_canary_covers
from review_evidence import PRIVATE_MARKERS
from review_worker_runner import ReviewWorkerRunner
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario

CANARY_REPO = "acme/widgets"
ISSUE_CLASSIC = 8841
ISSUE_BROKERED = 8842
FIND_LABEL = "hydraflow-find"
PLAN_LABEL = "hydraflow-plan"
READY_LABEL = "hydraflow-ready"
REVIEW_LABEL = "hydraflow-review"
HITL_LABEL = "hydraflow-hitl"

ORDERED_LABELS = (FIND_LABEL, PLAN_LABEL, READY_LABEL, REVIEW_LABEL, HITL_LABEL)
STAGE_LABELS = {
    "TRIAGE": FIND_LABEL,
    "PLAN": PLAN_LABEL,
    "READY": READY_LABEL,
    "REVIEW": REVIEW_LABEL,
    "DIAGNOSE": REVIEW_LABEL,
    "HITL_WAIT": HITL_LABEL,
    "HITL_APPLY": HITL_LABEL,
}

ROUTE_REVISION = "route-scenario-review"
BRANCH = "agent/issue-8842"
BASE_SHA = "6" * 40
HEAD_SHA = "7" * 40

#: The string that must never reach a child. It rides on the director's own
#: task contract and rationale, on the issue body's preamble and on a
#: non-plan issue comment — four different paths into a prompt, all of which a
#: Classic reviewer legitimately reads and a fresh one must not.
PRIVATE = "IMPLEMENTER-PRIVATE-CONTEXT"

ISSUE_BODY = f"""Triage notes the implementer wrote to itself. {PRIVATE}

## Goal

Bound the upload session cache.

## Acceptance criteria

- A session is evicted at the cap.
- A cache miss is not counted as a hit.
"""
PLAN_COMMENT = (
    "## Implementation Plan\n\n- add the eviction at the cap\n- fix the miss counter"
)

EVIDENCE = ProbeEvidence(
    agent_cli_version="2.1.239",
    residual_agents=5,
    residual_skills=15,
    residual_slash_commands=42,
)
CLEAN_INIT = {
    "type": "system",
    "subtype": "init",
    "tools": [],
    "mcp_servers": [],
    "plugins": [],
    "agents": [],
    "skills": [],
    "slash_commands": [],
    "version": "2.1.239",
}


class PortBackedReviewer:
    """The deterministic review phase: it merges, as the real one does.

    The canary must not change what this does or what it decides. It is the
    component that holds verdict and merge authority, and the whole scenario is
    a comparison of its outcome with and without a brokered judge beside it.
    """

    def __init__(self, github: Any) -> None:
        self._github = github
        self.reviewed: list[int] = []

    async def review_prs(
        self, prs: list[Any], issues: list[Task]
    ) -> list[ReviewResult]:
        results = []
        for pr in prs:
            self.reviewed.append(pr.issue_number)
            await self._github.swap_pipeline_labels(pr.issue_number, None)
            results.append(
                ReviewResult(
                    pr_number=pr.number,
                    issue_number=pr.issue_number,
                    verdict=ReviewVerdict.APPROVE,
                    success=True,
                    merged=True,
                    summary="approved and merged",
                )
            )
        return results


class OnePullRequest:
    """A ``ReviewablePRSource`` answering with one open PR for the issue."""

    def __init__(self, issue: int) -> None:
        self._issue = issue

    async def fetch_reviewable_prs(
        self,
        active_issues: set[int],
        prefetched_issues: list[GitHubIssue] | None = None,
    ) -> tuple[list[Any], list[GitHubIssue]]:
        if self._issue not in active_issues:
            return [], []
        return (
            [
                PRInfo(
                    number=self._issue - 8000,
                    issue_number=self._issue,
                    branch=f"agent/issue-{self._issue}",
                )
            ],
            list(prefetched_issues or []),
        )


class SingleIssueStore:
    """A store that offers one reviewable issue, then nothing."""

    def __init__(self, task: Task) -> None:
        self._pending = [task]
        self.released: list[int] = []
        self.requeued: list[tuple[int, str]] = []

    def get_plannable(self, max_count: int) -> list[Task]:
        return []

    def get_implementable(self, max_count: int) -> list[Task]:
        return []

    def get_reviewable(self, max_count: int) -> list[Task]:
        taken, self._pending = self._pending[:max_count], self._pending[max_count:]
        return taken

    def release_in_flight(
        self, issue_numbers: set[int], *, expected_stage: str | None = None
    ) -> None:
        self.released.extend(sorted(issue_numbers))

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        self.requeued.append((task.id, next_stage))


class RecordingGatewayControlPlane:
    """The real control-plane contract, recording every mint and revoke."""

    def __init__(self) -> None:
        self.minted: list[Any] = []
        self.revoked: list[str] = []
        self._n = 0

    async def mint_key(
        self, *, base_url, control_token, request
    ) -> GatewayMintCredential:
        _ = (base_url, control_token)
        self._n += 1
        self.minted.append(request)
        return GatewayMintCredential(
            key_id=f"key-{self._n}",
            token=f"hfgw_virtual_{self._n}",
            expires_at="2099-08-29T12:05:00Z",
        )

    async def revoke_key(self, *, base_url, control_token, key_id) -> bool:
        _ = (base_url, control_token)
        self.revoked.append(key_id)
        return True


class WorktreeAndEnvelopeRunner:
    """The one process boundary this scenario has, answering both kinds of call.

    Not a mock of a port: it *is* the subprocess boundary. A ``git`` argv is
    answered from a table — which is how the reviewed snapshot is staged
    without reaching inside the actuator — and a CLI argv gets exactly the JSON
    envelope ``_unwrap_result_envelope`` parses, so the real seam's unwrapping,
    usage extraction and credit scan all run.
    """

    def __init__(self) -> None:
        self.git_reads: list[list[str]] = []
        self.spawns: list[dict[str, Any]] = []
        self.answers = {
            "status": f"# branch.oid {HEAD_SHA}\n# branch.head {BRANCH}\n",
            "merge-base": f"{BASE_SHA}\n",
            "diff": "--- a/upload/session.py\n+++ b/upload/session.py\n+    evict()\n",
            "names": "upload/session.py\nupload/cache.py\n",
        }

    async def run_simple(self, cmd, *, env=None, input=None, timeout=None, cwd=None):  # noqa: A002
        from execution import SimpleResult

        argv = list(cmd)
        if argv[0] == "git":
            self.git_reads.append(argv)
            # ``diff HEAD`` and ``diff --name-only HEAD`` share a subcommand
            # and are two different reads, so the key is the flag, not argv[3].
            token = "names" if "--name-only" in argv else argv[3]
            return SimpleResult(stdout=self.answers.get(token, ""), returncode=0)
        self.spawns.append({"cmd": argv, "env": dict(env or {})})
        envelope = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps(
                {
                    "recommended": "request-changes",
                    "summary": "the eviction is off by one at the cap",
                    "findings": [
                        {
                            "summary": "`evict()` runs at cap+1, so the cap is never held",
                            "file": "upload/session.py",
                            "blocking": True,
                        }
                    ],
                }
            ),
            "session_id": "sess-review-1",
            "usage": {"input_tokens": 3100, "output_tokens": 260},
        }
        return SimpleResult(stdout=json.dumps(envelope), returncode=0)


class ScriptedTurnRunner:
    """One scripted director turn asking for a fresh Opus reviewer."""

    def __init__(self, *, requesting_spawn_id: str = "spawn-fresh") -> None:
        self.cli_version = "2.1.239"
        self.turns = 0
        self._requesting_spawn_id = requesting_spawn_id

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        """Answer *from the capsule*, the way a real director has to.

        The fencing tokens are read back out of the capsule rather than
        hardcoded; a made-up driver id would be refused with
        ``DRIVER_IDENTITY_MISMATCH`` and this scenario would prove only that
        the fence works, never that an honest request survives it.
        """
        self.turns += 1
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        lease = json.loads(payload)["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": f"the implement boundary finished {PRIVATE}",
            "dispatches": [
                {
                    "request_id": "req-1",
                    "driver_id": lease["driver_id"],
                    "epoch": lease["epoch"],
                    "phase_attempt": lease["phase_attempt"],
                    "worker_role": "reviewer",
                    "model_requirement": {
                        "kind": "literal_family",
                        "value": "claude-opus",
                    },
                    "task_contract": f"judge the change {PRIVATE}",
                    "reason": f"the implementer says it is done {PRIVATE}",
                    "expected_route_policy_revision": ROUTE_REVISION,
                    "idempotency_key": "key-review-1",
                    "requesting_spawn_id": self._requesting_spawn_id,
                }
            ],
        }
        return DirectorTurnResult(
            frames=[
                CLEAN_INIT,
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": json.dumps(command)}]
                    },
                },
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "total_cost_usd": 0.04,
                },
            ],
            exit_code=0,
            usd_cost=0.04,
            latency_ms=1400,
        )


def _settings(tmp_path, *, canary: str):
    from config import HydraFlowConfig
    from scheduling_model import ExecutionRuntime, SchedulingModel

    built = HydraFlowConfig(
        state_file=tmp_path / "state.json",
        repo=CANARY_REPO,
        workspace_base=tmp_path / "worktrees",
        scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
        execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
        fable_review_canary_repo=canary,
        gateway_base_url="http://gateway.test:8080",
    )
    for issue in (ISSUE_CLASSIC, ISSUE_BROKERED):
        built.workspace_path_for_issue(issue).mkdir(parents=True, exist_ok=True)
    return built


def _task(issue: int) -> Task:
    return Task(
        id=issue,
        title="bound the upload session cache",
        body=ISSUE_BODY,
        comments=[f"a triage note {PRIVATE}", PLAN_COMMENT],
        tags=[REVIEW_LABEL],
    )


def _build(mock_world, tmp_path, *, name: str, issue: int, canary: str | None):
    """One allocator over the real ports, with or without an armed canary."""
    github = mock_world.github
    reviewer = PortBackedReviewer(github)
    store = SingleIssueStore(_task(issue))
    director = None
    shadow_log = None
    control = RecordingGatewayControlPlane()
    boundary = WorktreeAndEnvelopeRunner()
    actuator = None
    if canary is not None:
        settings = _settings(tmp_path, canary=canary)
        shadow_log = ShadowObservationLog(tmp_path / f"{name}-shadow.jsonl")
        actuator = ReviewWorkerRunner(
            config=settings,
            route_policy_revision=ROUTE_REVISION,
            runner=boundary,  # type: ignore[arg-type]
            base_ref="origin/staging",
            gateway_client=control,  # type: ignore[arg-type]
        )
        director = FableDirector(
            runner=ScriptedTurnRunner(),  # type: ignore[arg-type]
            broker=ShadowDispatchBroker(),
            shadow_log=shadow_log,
            evidence=EVIDENCE,
            repo_slug=CANARY_REPO,
            route_policy_revision=ROUTE_REVISION,
            stage_labels=STAGE_LABELS,
            usd_budget_per_boundary=5.0,
            review_dispatcher=actuator,
            review_is_covered=lambda phase: review_canary_covers(settings, phase=phase),
        )
    manager = DriverManager(
        store=store,
        labels=PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS),
        journal=DriverJournal(tmp_path / f"{name}-driver_journal.jsonl"),
        ownership=DriverOwnershipRegistry(enabled=True),
        adapters={
            DriverPhase.REVIEW: ReviewPhaseAdapter(reviewer, OnePullRequest(issue))
        },
        stage_labels=STAGE_LABELS,
        repo_slug=CANARY_REPO,
        max_in_flight=1,
        stage_caps={DriverPhase.REVIEW: 1},
        observer=director,
    )
    return {
        "manager": manager,
        "github": github,
        "reviewer": reviewer,
        "shadow_log": shadow_log,
        "control": control,
        "boundary": boundary,
        "actuator": actuator,
    }


async def _run(mock_world, tmp_path, *, name, issue, canary):
    built = _build(mock_world, tmp_path, name=name, issue=issue, canary=canary)
    await built["manager"].tick()
    built["outcome"] = {
        "labels": sorted(await built["github"].get_issue_labels(issue)),
        # Offset by the issue number so the two arms are comparable across two
        # different issues — the same normalisation the implement scenario uses.
        "reviewed": [n - issue for n in built["reviewer"].reviewed],
    }
    return built


def _dispatched(shadow_log: ShadowObservationLog) -> list[dict[str, Any]]:
    return list(shadow_log.recent()[-1].dispatched)


@pytest.fixture
def seeded_issues(mock_world, monkeypatch):
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
    for issue in (ISSUE_CLASSIC, ISSUE_BROKERED):
        IssueBuilder().numbered(issue).titled("bound the upload session cache").labeled(
            REVIEW_LABEL
        ).at(mock_world)
    return mock_world


# --------------------------------------------------------------------------
# The canary adds a judge, not authority
# --------------------------------------------------------------------------


class TestABrokeredReviewReachesTheClassicOutcome:
    async def test_the_label_outcome_is_identical(
        self, seeded_issues, tmp_path
    ) -> None:
        """P5's "one issue can complete the same canonical workflow under
        Classic and Fable presets", as an observation rather than a claim.

        The spawn count is asserted BESIDE the parity, and it is not decoration.
        "The two arms reach the same outcome" is satisfied perfectly by a
        brokered arm in which the canary dispatched nothing at all — which is
        precisely the state this issue found the dial in. Parity is only
        evidence that the judge takes no authority if a judge actually ran.
        """
        classic = await _run(
            seeded_issues, tmp_path, name="classic", issue=ISSUE_CLASSIC, canary=None
        )
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="brokered",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

        assert brokered["outcome"] == classic["outcome"]
        assert len(brokered["boundary"].spawns) == 1
        assert classic["boundary"].spawns == []

    async def test_the_deterministic_phase_still_decides_and_merges(
        self, seeded_issues, tmp_path
    ) -> None:
        # The whole scope line: the brokered judge produces a proposal and a
        # receipt *beside* the phase that owns the verdict and the merge, never
        # instead of it.
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="still-decides",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

        assert brokered["reviewer"].reviewed == [ISSUE_BROKERED]

    async def test_an_actuator_armed_elsewhere_starts_nothing_here(
        self, seeded_issues, tmp_path
    ) -> None:
        """The bound refusing, with the actuator fully wired behind it.

        Armed for *another* repository rather than compared against the
        ``canary=None`` arm: that arm never constructs an actuator at all, so
        empty lists there are guaranteed by this harness's own branching rather
        than by ``review_canary_covers``.
        """
        elsewhere = await _run(
            seeded_issues,
            tmp_path,
            name="elsewhere",
            issue=ISSUE_BROKERED,
            canary="acme/other",
        )

        assert elsewhere["boundary"].spawns == []
        assert elsewhere["boundary"].git_reads == []
        assert elsewhere["control"].minted == []


class TestTheBrokeredJudgeReallyRan:
    """Without this class, deleting the wiring would pass everything above."""

    async def test_one_child_starts_and_its_key_is_minted_and_revoked(
        self, seeded_issues, tmp_path
    ) -> None:
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="ran",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )

        assert len(brokered["boundary"].spawns) == 1
        assert len(brokered["control"].minted) == 1
        assert brokered["control"].revoked == ["key-1"]

    async def test_the_child_never_receives_the_control_token(
        self, seeded_issues, tmp_path
    ) -> None:
        # The credential boundary, through the real ``resolve_harness_env``
        # scrub rather than around it.
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="scrub",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        env = brokered["boundary"].spawns[0]["env"]

        assert "HYDRAFLOW_GATEWAY_CONTROL_TOKEN" not in env
        assert "control-secret" not in json.dumps(env)

    async def test_the_evidence_is_gathered_from_the_worktree(
        self, seeded_issues, tmp_path
    ) -> None:
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="gathered",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        reads = brokered["boundary"].git_reads

        assert [argv[3] for argv in reads] == ["status", "merge-base", "diff", "diff"]
        assert sum("--name-only" in argv for argv in reads) == 1

    async def test_the_receipt_is_accepted_and_names_its_served_model(
        self, seeded_issues, tmp_path
    ) -> None:
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="receipt",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        receipts = _dispatched(brokered["shadow_log"])

        assert [r["status"] for r in receipts] == ["accepted"]
        assert receipts[0]["served_model"]
        assert receipts[0]["child_spawn_id"]


class TestTheJudgeIsFreshAndProposesOnly:
    async def test_no_private_context_reaches_the_child(
        self, seeded_issues, tmp_path
    ) -> None:
        """The sentinel rides on four paths into the prompt. None may arrive.

        Asserted beside a positive: the prompt must ALSO carry the canonical
        facts. "The sentinel is absent" is satisfied perfectly by a prompt that
        was never built, which is what every earlier assertion in this file
        would look like if the wiring were deleted.
        """
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="fresh",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        argv = brokered["boundary"].spawns[0]["cmd"]
        prompt = "\n".join(str(part) for part in argv)

        assert PRIVATE not in prompt
        assert "Bound the upload session cache." in prompt
        assert "A session is evicted at the cap." in prompt
        assert "add the eviction at the cap" in prompt
        assert BRANCH in prompt and BASE_SHA in prompt and HEAD_SHA in prompt
        assert "+    evict()" in prompt

    async def test_no_private_marker_names_a_key_in_the_child_argv(
        self, seeded_issues, tmp_path
    ) -> None:
        # Derived from ``PRIVATE_MARKERS`` rather than spelled here, so a
        # marker added there is checked here without an edit.
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="markers",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        argv = "\n".join(str(p) for p in brokered["boundary"].spawns[0]["cmd"])

        assert [marker for marker in sorted(PRIVATE_MARKERS) if marker in argv] == []

    async def test_the_reply_becomes_a_proposal_and_never_a_verdict(
        self, seeded_issues, tmp_path
    ) -> None:
        """The judge filed a blocking finding and asked for changes; the
        deterministic phase approved and merged anyway.

        That divergence is the point, and it is what makes "Fable cannot
        self-approve, merge or mutate a verdict" observable rather than
        promised: the two disagree in the same tick, and the pipeline follows
        the deterministic one.
        """
        brokered = await _run(
            seeded_issues,
            tmp_path,
            name="proposal",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        proposal = brokered["actuator"].last_proposals["req-1"]

        assert proposal.recommended.value == "request-changes"
        assert len(proposal.findings) == 1
        # The pipeline's own outcome, unchanged by that recommendation.
        assert brokered["reviewer"].reviewed == [ISSUE_BROKERED]
        assert REVIEW_LABEL not in brokered["outcome"]["labels"]


class TestAJudgeCannotReviewItsOwnWork:
    async def test_a_reviewer_requested_by_the_implementer_never_starts(
        self, seeded_issues, tmp_path
    ) -> None:
        """The self-review fence through the whole allocator, by REASON.

        "No spawn happened" is true of a disarmed dial, a wrong phase and a
        deleted feature; only the reason distinguishes the fence.
        """
        implementer_spawn = "spawn-implementer"
        built = _build(
            seeded_issues,
            tmp_path,
            name="self",
            issue=ISSUE_BROKERED,
            canary=CANARY_REPO,
        )
        director = built["manager"]._observer  # noqa: SLF001
        director._runner = ScriptedTurnRunner(  # noqa: SLF001
            requesting_spawn_id=implementer_spawn
        )
        director._implementer_spawns[ISSUE_BROKERED] = frozenset({implementer_spawn})  # noqa: SLF001

        await built["manager"].tick()

        row = built["shadow_log"].recent()[-1]
        assert built["boundary"].spawns == []
        assert list(row.rejection_reasons) == ["self_review_forbidden"]
        # And the deterministic phase was untouched by the refusal: a fenced
        # judge must not cost the issue its review.
        assert built["reviewer"].reviewed == [ISSUE_BROKERED]
