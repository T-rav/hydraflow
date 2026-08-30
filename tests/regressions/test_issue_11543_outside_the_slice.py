"""Outside the Review canary's bound, nothing moved — and inside it, a reviewer ran (#11543).

The same **differential** proof #11541 and #11542 wrote for their bounds, over
the third one. The same director, over the same boundary, with the review
actuator fully wired and the bound not covering it, must record byte-identical
evidence to the same director with no review actuator at all — and must spawn
nothing and read no git.

Five ways out of the bound, one per clause of the thing that could regress:

* the review dial is empty (an untouched deployment);
* the review dial names another repository;
* the review dial names this repository but the boundary is not ``REVIEW``;
* **only the older canaries are armed** — the case that says "widen one role
  boundary at a time" is a property rather than a sentence, and the case an
  operator running Plan and Implement today actually occupies;
* the dial was cleared while the process was running (the one-action rollback,
  taking effect on the next boundary rather than the next restart).

The class that matters most for this phase is
:class:`TestInsideTheBoundAReviewerActuallyRuns`. Until this issue, arming
``fable_review_canary_repo`` dispatched **nothing** — the dial's own docstring
said so — because nothing constructed a ``ReviewWorkerRunner``. Every "outside
the bound nothing happened" assertion above would have passed against that
inert build, unchanged, which is precisely why they cannot be the proof. What
proves the dial is a capability is a spawn that happens when it is armed.

And two classes that are this boundary's own, not inherited: the reviewer sees
**only** canonical evidence, and it cannot review its own work. Both are
asserted on the REASON rather than on an absence — a self-review test passes
just as well when the reviewer never ran at all, and a "no private context
reached the child" test passes just as well when no child was started.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from director_broker import ShadowDispatchBroker
from director_sandbox import ProbeEvidence
from director_shadow_log import ShadowObservationLog
from director_turn_runner import CAPSULE_CLOSE, CAPSULE_OPEN, DirectorTurnResult
from driver_contracts import DriverPhase, ReceiptStatus, RejectionReason
from execution import SimpleResult
from fable_director import FableDirector
from issue_driver import AdvanceOutcome, DriverAdvance, IssueDriver
from models import Task
from review_broker import review_canary_covers
from review_evidence import PRIVATE_MARKERS
from review_worker_runner import ReviewWorkerRunner
from scheduling_model import ExecutionRuntime, SchedulingModel

if TYPE_CHECKING:
    from pathlib import Path

CANARY_REPO = "acme/widgets"
REVIEW_LABEL = "hydraflow-review"
ROUTE_REVISION = "route-v1"
BRANCH = "agent/issue-7"
BASE = "1" * 40
HEAD = "2" * 40
IMPLEMENTER_SPAWN = "spawn-implementer"
FRESH_SPAWN = "spawn-fresh"

#: The string that must never reach a child. Carried on every field of the
#: director's own command — the task contract and the reason — because those
#: are the two the runner would render if anybody widened ``dispatch``'s
#: signature to take the request.
PRIVATE = "IMPLEMENTER-PRIVATE-CONTEXT"

STAGE_LABELS = {
    "PLAN": "hydraflow-plan",
    "READY": "hydraflow-ready",
    "REVIEW": REVIEW_LABEL,
    "DIAGNOSE": REVIEW_LABEL,
    "HITL_WAIT": "hydraflow-hitl",
}
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

ISSUE_BODY = f"""Some preamble that is not the ask. {PRIVATE}

## Goal

Make the widget cache correctly.

## Acceptance criteria

- The cache is bounded.
- A miss is not recorded as a hit.
"""

PLAN_COMMENT = "## Implementation Plan\n\n- bound the cache\n- fix the miss counter"

#: Clock readings, normalised out of the comparison because they differ between
#: any two runs, armed or not — and pinned by name so the comparison cannot be
#: quietly widened into vacuity.
VOLATILE_FIELDS = ("recorded_at",)


class ScriptedTurn:
    """One director turn asking for one catalogued worker. Spawns nothing.

    The role and the requesting lineage are parameters for #11541's reason: a
    bound's phase clause can only be *killed* by a request the rest of the
    machinery would otherwise allow, so a test that wants to prove the clause
    must ask for a role the catalog permits at the phase under test — and at
    REVIEW it must also state a lineage, because a request that states none is
    refused by the independence fence before the bound is ever consulted.

    The fencing tokens are read back out of the capsule rather than hardcoded,
    because a hardcoded driver id makes every request for a second issue fail
    ``DRIVER_IDENTITY_MISMATCH`` and silently turns a bound test into a fence
    test.
    """

    def __init__(
        self,
        role: str = "reviewer",
        family: str = "claude-opus",
        requesting_spawn_id: str | None = FRESH_SPAWN,
    ) -> None:
        self.cli_version = "2.1.239"
        self.turns = 0
        self._role = role
        self._family = family
        self._requesting_spawn_id = requesting_spawn_id

    async def preflight(self) -> str:
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        self.turns += 1
        payload = prompt.split(CAPSULE_OPEN, 1)[1].split(CAPSULE_CLOSE, 1)[0]
        lease = json.loads(payload)["lease"]
        command = {
            "kind": "dispatch_workers",
            "rationale": "the implement boundary finished",
            "dispatches": [
                {
                    "request_id": "req-1",
                    "driver_id": lease["driver_id"],
                    "epoch": lease["epoch"],
                    "phase_attempt": lease["phase_attempt"],
                    "worker_role": self._role,
                    "model_requirement": {
                        "kind": "literal_family",
                        "value": self._family,
                    },
                    # Both carry the sentinel. A reviewer that can read the
                    # director's rationale for asking is reading the argument
                    # for the change, which is the thing this boundary exists
                    # to withhold.
                    "task_contract": f"review the change {PRIVATE}",
                    "reason": f"the implement boundary finished {PRIVATE}",
                    "expected_route_policy_revision": ROUTE_REVISION,
                    "idempotency_key": f"key-{lease['issue_number']}-{self.turns}",
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
                    "total_cost_usd": 0.0,
                },
            ],
            exit_code=0,
        )


class GitScript:
    """A ``SubprocessRunner`` answering scripted git reads and nothing else."""

    def __init__(self, *, answers: dict[str, str] | None = None) -> None:
        # ``answers if answers is not None`` and NOT ``answers or ...``: an
        # empty dict is falsy, so the ``or`` spelling silently handed the
        # BLIND arm the full default answers and its refusal test passed a
        # spawn through. Caught by the test failing; worth the comment because
        # the wrong spelling fails in the direction that looks like a pass.
        self.answers = (
            answers
            if answers is not None
            else {
                "status": f"# branch.oid {HEAD}\n# branch.head {BRANCH}\n",
                "merge-base": f"{BASE}\n",
                "diff": "--- a/widget.py\n+++ b/widget.py\n+cache = {}\n",
                "names": "widget.py\n",
            }
        )
        self.calls: list[list[str]] = []

    async def run_simple(self, cmd: Any, **kwargs: Any) -> SimpleResult:
        argv = list(cmd)
        self.calls.append(argv)
        if argv[0] != "git":
            raise AssertionError("the actuator ran a non-git command in a regression")
        # ``diff HEAD`` and ``diff --name-only HEAD`` share a subcommand and
        # are two different reads, so the key is the flag rather than argv[3].
        token = "names" if "--name-only" in argv else argv[3]
        return SimpleResult(stdout=self.answers.get(token, ""), returncode=0)


class SpawnCounter:
    """Stands in for ``run_lightweight_agent`` and records every call."""

    def __init__(self, *, stdout: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self._stdout = stdout or json.dumps(
            {"recommended": "comment", "summary": "reads fine", "findings": []}
        )

    async def __call__(self, **kwargs: Any) -> SimpleResult:
        self.calls.append(kwargs)
        spawn_out = kwargs.get("spawn_out")
        if spawn_out is not None:
            spawn_out.update(
                {
                    "model": kwargs["model"],
                    "provider": "gateway",
                    "usage": {"input_tokens": 800, "output_tokens": 120},
                    # The seam sets this on the last line before it starts the
                    # process. A double that filled ``model`` without it models
                    # a CAUGHT MINT FAILURE — a real thing the seam does, and a
                    # different one — which would silently turn every
                    # accepted-receipt assertion below into a refusal test.
                    "spawned": True,
                }
            )
        return SimpleResult(stdout=self._stdout, returncode=0)


def _settings(tmp_path: Path, canary: str, **overrides: object) -> Any:
    from config import HydraFlowConfig

    fields: dict[str, object] = {
        "state_file": tmp_path / "state.json",
        "repo": CANARY_REPO,
        "workspace_base": tmp_path / "worktrees",
        "scheduling_model": SchedulingModel.ISSUE_CONTROLLER,
        "execution_runtime": ExecutionRuntime.FABLE_DIRECTOR,
        "fable_review_canary_repo": canary,
    }
    fields.update(overrides)
    built = HydraFlowConfig(**fields)  # type: ignore[arg-type]
    # The evidence is read out of the issue's worktree, so it has to exist for
    # the probes to run at all — the same setup #11542's writer needs.
    built.workspace_path_for_issue(7).mkdir(parents=True, exist_ok=True)
    built.workspace_path_for_issue(9).mkdir(parents=True, exist_ok=True)
    return built


def _driver(state: str = "REVIEW", issue: int = 7) -> IssueDriver:
    return IssueDriver(
        issue_number=issue,
        driver_id=f"drv-{issue}",
        repo_slug=CANARY_REPO,
        adapters={},
        labels=object(),  # type: ignore[arg-type]
        journal=object(),  # type: ignore[arg-type]
        stage_labels=STAGE_LABELS,
        driver_state=state,
    )


def _advance(
    phase: DriverPhase = DriverPhase.REVIEW, state: str = "REVIEW", issue: int = 7
) -> DriverAdvance:
    return DriverAdvance(
        issue_number=issue,
        driver_id=f"drv-{issue}",
        epoch=0,
        phase=phase,
        outcome=AdvanceOutcome.COMMITTED,
        state=state,
    )


def _assemble(
    tmp_path: Path,
    *,
    name: str,
    canary: str | None,
    wired: bool,
    turn: ScriptedTurn | None = None,
    git: GitScript | None = None,
    spawn: SpawnCounter | None = None,
    settings: Any = None,
):
    """One director, with the review actuator wired or entirely absent."""
    log = ShadowObservationLog(tmp_path / f"{name}-shadow.jsonl")
    started = spawn or SpawnCounter()
    scripted_git = git or GitScript()
    actuator = None
    covered = None
    if wired:
        config = settings if settings is not None else _settings(tmp_path, canary or "")
        actuator = ReviewWorkerRunner(
            config=config,
            route_policy_revision=ROUTE_REVISION,
            runner=scripted_git,  # type: ignore[arg-type]
            base_ref="origin/staging",
            spawn=started,
        )
        covered = lambda phase: review_canary_covers(config, phase=phase)  # noqa: E731
    built = FableDirector(
        runner=turn or ScriptedTurn(),  # type: ignore[arg-type]
        broker=ShadowDispatchBroker(),
        shadow_log=log,
        evidence=EVIDENCE,
        repo_slug=CANARY_REPO,
        route_policy_revision=ROUTE_REVISION,
        stage_labels=STAGE_LABELS,
        usd_budget_per_boundary=5.0,
        review_dispatcher=actuator,
        review_is_covered=covered,
    )
    return built, log, started, scripted_git


async def _observe(
    built: FableDirector,
    *,
    phase: DriverPhase = DriverPhase.REVIEW,
    state: str = "REVIEW",
    issue: int = 7,
) -> None:
    await built.observe_boundary(
        task=Task(
            id=issue,
            title="make the widget cache correctly",
            body=ISSUE_BODY,
            comments=[f"a triage note {PRIVATE}", PLAN_COMMENT],
            tags=[STAGE_LABELS[state]],
        ),
        advance=_advance(phase, state, issue),
        driver=_driver(state, issue),
    )


def _rows(log: ShadowObservationLog) -> list[dict[str, Any]]:
    collected = []
    for observation in log.recent():
        row = observation.model_dump(mode="json")
        for field in VOLATILE_FIELDS:
            row.pop(field, None)
        collected.append(row)
    return collected


async def _run(
    tmp_path: Path,
    *,
    name: str,
    canary: str | None,
    wired: bool,
    phase: DriverPhase = DriverPhase.REVIEW,
    state: str = "REVIEW",
    turn: ScriptedTurn | None = None,
    settings: Any = None,
    spawn: SpawnCounter | None = None,
):
    built, log, started, git = _assemble(
        tmp_path,
        name=name,
        canary=canary,
        wired=wired,
        turn=turn,
        settings=settings,
        spawn=spawn,
    )
    await _observe(built, phase=phase, state=state)
    return _rows(log), started.calls, git.calls


@pytest.fixture
async def shadow_baseline(tmp_path: Path):
    """The arm with no review actuator and no coverage predicate at all."""
    return await _run(tmp_path, name="baseline", canary=None, wired=False)


class TestOutsideTheBoundNothingMoves:
    async def test_an_untouched_deployment_records_the_shadow_evidence(
        self, tmp_path: Path, shadow_baseline: Any
    ) -> None:
        rows, _spawns, _reads = shadow_baseline
        armed, _s, _r = await _run(tmp_path, name="empty", canary="", wired=True)

        assert armed == rows

    async def test_an_untouched_deployment_starts_no_reviewer(
        self, tmp_path: Path
    ) -> None:
        _rows_, spawns, _reads = await _run(
            tmp_path, name="empty", canary="", wired=True
        )

        assert spawns == []

    async def test_an_untouched_deployment_reads_no_git(self, tmp_path: Path) -> None:
        # Gathering evidence is itself an effect: four git reads against the
        # issue's worktree, on the allocator's tick. A disarmed repository must
        # not pay for them, and "nothing moved" has to include the probe.
        _rows_, _spawns, reads = await _run(
            tmp_path, name="empty", canary="", wired=True
        )

        assert reads == []

    async def test_another_repository_records_the_shadow_evidence(
        self, tmp_path: Path, shadow_baseline: Any
    ) -> None:
        rows, _spawns, _reads = shadow_baseline
        armed, spawns, reads = await _run(
            tmp_path, name="other", canary="acme/other", wired=True
        )

        assert (armed, spawns, reads) == (rows, [], [])

    @pytest.mark.parametrize(
        ("phase", "state", "role", "family"),
        [
            pytest.param(
                DriverPhase.PLAN, "PLAN", "explorer", "claude-sonnet", id="plan"
            ),
            pytest.param(
                DriverPhase.IMPLEMENT,
                "READY",
                "implementer",
                "claude-sonnet",
                id="implement",
            ),
        ],
    )
    async def test_another_phase_is_never_offered_to_the_review_canary(
        self, tmp_path: Path, phase: DriverPhase, state: str, role: str, family: str
    ) -> None:
        rows, spawns, reads = await _run(
            tmp_path,
            name=f"phase-{phase.value}",
            canary=CANARY_REPO,
            wired=True,
            phase=phase,
            state=state,
            turn=ScriptedTurn(role=role, family=family, requesting_spawn_id=None),
        )

        assert (spawns, reads) == ([], [])
        assert [row["dispatched"] for row in rows] == [[]]
        # The turn produced a real command that was judged and found outside
        # the bound — not one that never parsed. Without this the assertions
        # above hold for a malformed turn and the phase clause is never
        # consulted.
        assert [row["command_kind"] for row in rows] == ["dispatch_workers"]

    @pytest.mark.parametrize(
        "older",
        [
            pytest.param({"fable_plan_canary_repo": CANARY_REPO}, id="plan-only"),
            pytest.param(
                {"fable_implement_canary_repo": CANARY_REPO}, id="implement-only"
            ),
        ],
    )
    async def test_an_older_canary_alone_dispatches_no_reviewer(
        self, tmp_path: Path, older: dict[str, object]
    ) -> None:
        # "Widen one role boundary at a time" as a property. An operator who
        # armed a writer must not find judges running.
        settings = _settings(tmp_path, "", **older)
        _rows_, spawns, reads = await _run(
            tmp_path, name="older", canary=None, wired=True, settings=settings
        )

        assert (spawns, reads) == ([], [])

    async def test_clearing_the_dial_mid_run_stops_the_next_boundary(
        self, tmp_path: Path
    ) -> None:
        # The one-action rollback, with the actuator object still present. What
        # stops the second boundary is the predicate being re-read, not the
        # dispatcher going away.
        settings = _settings(tmp_path, CANARY_REPO)
        spawn = SpawnCounter()
        built, _log, started, _git = _assemble(
            tmp_path,
            name="rollback",
            canary=None,
            wired=True,
            settings=settings,
            spawn=spawn,
        )
        await _observe(built)
        started_while_armed = len(started.calls)

        object.__setattr__(settings, "fable_review_canary_repo", "")
        await _observe(built, issue=9)

        assert (started_while_armed, len(started.calls)) == (1, 1)


class TestInsideTheBoundAReviewerActuallyRuns:
    """Without this class, deleting the whole wiring would pass every test above.

    It is also the class that distinguishes this issue from the state before
    it. The dial, its bound, its refusals and its actuator all existed and were
    all tested; what did not exist was anything that constructed the actuator,
    so arming the dial was a no-op that every "nothing happened" assertion
    agreed with.
    """

    async def test_the_canary_repository_at_review_starts_one_reviewer(
        self, tmp_path: Path
    ) -> None:
        _rows_, spawns, _reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert len(spawns) == 1

    async def test_the_canary_repository_gathers_its_evidence(
        self, tmp_path: Path
    ) -> None:
        # Once per covered boundary, four reads, one pass. A base read taken a
        # second after a HEAD read describes a tree that never existed.
        _rows_, _spawns, reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert [argv[3] for argv in reads] == ["status", "merge-base", "diff", "diff"]
        assert sum("--name-only" in argv for argv in reads) == 1

    async def test_the_boundary_records_an_accepted_receipt(
        self, tmp_path: Path
    ) -> None:
        rows, _spawns, _reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert [row["status"] for row in rows[0]["dispatched"]] == [
            ReceiptStatus.ACCEPTED.value
        ]

    async def test_the_armed_evidence_differs_from_the_shadow_evidence(
        self, tmp_path: Path, shadow_baseline: Any
    ) -> None:
        # Makes every ``armed == rows`` comparison above non-vacuous: the two
        # evidence sets ARE distinguishable when something actually ran.
        rows, _spawns, _reads = shadow_baseline
        armed, _s, _r = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert armed != rows

    async def test_the_reviewer_is_routed_to_opus_through_the_gateway(
        self, tmp_path: Path
    ) -> None:
        _rows_, spawns, _reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )

        assert spawns[0]["provider"] == "gateway"
        assert spawns[0]["source"] == "reviewer"
        assert "opus" in str(spawns[0]["model"])


class TestTheReviewerSeesCanonicalEvidenceAndNothingElse:
    async def test_no_private_context_reaches_the_child(self, tmp_path: Path) -> None:
        """The sentinel is on the issue body, a comment, the task contract and
        the director's reason. None of them may appear in the prompt.

        Asserted beside a positive: the prompt must ALSO contain the canonical
        facts. A prompt that was empty, or a child that never started, would
        satisfy "the sentinel is absent" perfectly.
        """
        _rows_, spawns, _reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )
        prompt = str(spawns[0]["prompt"])

        assert PRIVATE not in prompt
        assert "Make the widget cache correctly." in prompt
        assert "The cache is bounded." in prompt
        assert "bound the cache" in prompt
        assert BRANCH in prompt and BASE in prompt and HEAD in prompt
        assert "+cache = {}" in prompt

    async def test_no_private_marker_names_a_key_in_the_prompt(
        self, tmp_path: Path
    ) -> None:
        # The belt over the allow-list, at the one place a leak would be
        # visible. Derived from ``PRIVATE_MARKERS`` rather than spelled here,
        # so a marker added there is checked here without an edit.
        _rows_, spawns, _reads = await _run(
            tmp_path, name="armed", canary=CANARY_REPO, wired=True
        )
        prompt = str(spawns[0]["prompt"])

        assert [marker for marker in sorted(PRIVATE_MARKERS) if marker in prompt] == []

    async def test_an_unreadable_snapshot_refuses_before_any_spawn(
        self, tmp_path: Path
    ) -> None:
        """ADR-0137 S4 at a third boundary: a boundary that cannot be proven is
        refused, never assumed.

        The refusal is asserted by its REASON, not by the absence of a spawn. A
        bare ``spawns == []`` is satisfied by every other refusal in the file
        and by the feature not existing at all.
        """
        settings = _settings(tmp_path, CANARY_REPO)
        blind = GitScript(answers={})
        built, log, spawn, _git = _assemble(
            tmp_path,
            name="blind",
            canary=None,
            wired=True,
            settings=settings,
            git=blind,
        )

        await _observe(built)

        rows = _rows(log)
        assert spawn.calls == []
        assert [row["status"] for row in rows[0]["dispatched"]] == [
            ReceiptStatus.REJECTED.value
        ]
        assert [row["reason"] for row in rows[0]["dispatched"]] == [
            RejectionReason.WORKTREE_UNMEASURED.value
        ]
        # And the probes really ran — the refusal is about what they answered,
        # not about the actuator declining to look.
        assert len(blind.calls) >= 1

    async def test_a_missing_worktree_refuses_without_reading_any_git(
        self, tmp_path: Path
    ) -> None:
        """The other way a snapshot goes unread: there is no worktree at all.

        A separate branch in ``gather`` from "the probes answered nothing", and
        it was reachable in principle and exercised by nothing — every other
        fixture in this file pre-creates the directory. An unexercised branch
        is where a later edit goes unnoticed, so it gets its own case: no git
        is run at all (there is nothing to run it against), and the boundary
        still refuses rather than dispatching a reviewer at a tree that does
        not exist.
        """
        settings = _settings(tmp_path, CANARY_REPO)
        # Remove the worktree the fixture created, leaving the dial armed.
        settings.workspace_path_for_issue(7).rmdir()
        git = GitScript()
        built, log, spawn, _git = _assemble(
            tmp_path,
            name="noworktree",
            canary=None,
            wired=True,
            settings=settings,
            git=git,
        )

        await _observe(built)

        rows = _rows(log)
        assert spawn.calls == []
        # No worktree means no probe: the actuator does not shell out to git
        # against a path it already knows is absent.
        assert git.calls == []
        assert [row["reason"] for row in rows[0]["dispatched"]] == [
            RejectionReason.WORKTREE_UNMEASURED.value
        ]


class TestAReviewerCannotReviewItsOwnWork:
    async def test_a_reviewer_requested_by_the_implementer_is_refused_by_reason(
        self, tmp_path: Path
    ) -> None:
        """The self-review fence, at the director seam.

        Asserted on ``SELF_REVIEW_FORBIDDEN`` specifically. "No spawn happened"
        is true of a disarmed dial, a wrong phase, an unreadable worktree and a
        deleted feature; only the reason distinguishes the fence from all of
        them.
        """
        settings = _settings(tmp_path, CANARY_REPO)
        built, log, spawn, _git = _assemble(
            tmp_path,
            name="self",
            canary=None,
            wired=True,
            settings=settings,
            # The whole point: this reviewer is requested BY the spawn that
            # implemented. Left at the default fresh id, the fence has nothing
            # to fire on and the test would have proved only that a reviewer
            # runs.
            turn=ScriptedTurn(requesting_spawn_id=IMPLEMENTER_SPAWN),
        )
        # The director learns the implementer's lineage the way it really does:
        # from an accepted IMPLEMENTER receipt it recorded at an earlier
        # boundary. Written directly here because reaching it through a full
        # implement boundary would make this a test of #11542.
        built._implementer_spawns[7] = frozenset({IMPLEMENTER_SPAWN})  # noqa: SLF001

        await built.observe_boundary(
            task=Task(
                id=7,
                title="t",
                body=ISSUE_BODY,
                comments=[PLAN_COMMENT],
                tags=[REVIEW_LABEL],
            ),
            advance=_advance(),
            driver=_driver(),
        )

        rows = _rows(log)
        assert spawn.calls == []
        # Refused at the BROKER, before the actuator is even asked — which is
        # why the reason is on the row rather than on a receipt. Stronger than
        # a refusal receipt would be: the request never became a dispatch at
        # all, so there was no moment at which a self-review was admissible.
        assert rows[0]["rejection_reasons"] == [
            RejectionReason.SELF_REVIEW_FORBIDDEN.value
        ]
        assert rows[0]["dispatched"] == []

    async def test_a_fresh_reviewer_at_the_same_boundary_is_admitted(
        self, tmp_path: Path
    ) -> None:
        """The negative control that makes the fence a fence rather than a wall.

        Same director, same recorded implementer lineage, same boundary — only
        the requesting spawn id differs. Without this, a fence that refused
        every reviewer unconditionally would pass the test above.
        """
        settings = _settings(tmp_path, CANARY_REPO)
        built, log, spawn, _git = _assemble(
            tmp_path, name="fresh", canary=None, wired=True, settings=settings
        )
        built._implementer_spawns[7] = frozenset({IMPLEMENTER_SPAWN})  # noqa: SLF001

        await _observe(built)

        rows = _rows(log)
        assert len(spawn.calls) == 1
        assert [row["status"] for row in rows[0]["dispatched"]] == [
            ReceiptStatus.ACCEPTED.value
        ]

    async def test_a_review_request_stating_no_lineage_never_constructs(
        self, tmp_path: Path
    ) -> None:
        """A REVIEW request with no lineage is refused by the CONTRACT, one
        layer above the fence — it does not become a request at all.

        Worth pinning as its own fact because it is the vacuity trap this
        boundary sets for its own tests. A test that asks for a REVIEW role
        without stating a lineage gets "no spawn happened" for free, with the
        canary's bound, the fence and the actuator all never consulted; #11542
        hit exactly this and had to carry the mutation receipt inline. Naming
        the real mechanism here is what stops the next test being written
        against the wrong one.
        """
        settings = _settings(tmp_path, CANARY_REPO)
        built, log, spawn, _git = _assemble(
            tmp_path,
            name="nolineage",
            canary=None,
            wired=True,
            settings=settings,
            turn=ScriptedTurn(requesting_spawn_id=None),
        )

        await _observe(built)

        rows = _rows(log)
        assert spawn.calls == []
        # Asserted POSITIVELY on the mechanism. The command never parsed, so
        # there is no rejection reason to read — and claiming one here would
        # describe a refusal that did not happen.
        assert (rows[0]["command_kind"], rows[0]["turn_failure"]) == (
            None,
            "malformed_output",
        )
        assert rows[0]["rejection_reasons"] == []
        # The contrast that makes the line above about LINEAGE rather than
        # about this turn being malformed generally: the identical turn with a
        # lineage stated parses and dispatches.
        _rows_, spawns, _reads = await _run(
            tmp_path, name="withlineage", canary=CANARY_REPO, wired=True
        )
        assert len(spawns) == 1


class TestTheReviewerProposesAndNeverDecides:
    async def test_the_receipt_carries_a_proposal_and_no_verdict(
        self, tmp_path: Path
    ) -> None:
        """P5's authority criterion at the seam that could break it.

        A reviewer's reply becomes a ``ReviewProposal``; nothing on this path
        turns it into a ``ReviewVerdict``, moves a label or merges anything.
        Asserted on the actuator's own ``last_proposals`` so it is the reply
        that was parsed, not a value this test constructed.
        """
        settings = _settings(tmp_path, CANARY_REPO)
        spawn = SpawnCounter(
            stdout=json.dumps(
                {
                    "recommended": "approve",
                    "summary": "looks fine to me",
                    "findings": [
                        {"summary": "the bound is off by one", "blocking": True}
                    ],
                }
            )
        )
        built, _log, started, _git = _assemble(
            tmp_path,
            name="proposal",
            canary=None,
            wired=True,
            settings=settings,
            spawn=spawn,
        )
        actuator = built._review_dispatcher  # noqa: SLF001
        assert actuator is not None

        await _observe(built)

        proposal = actuator.last_proposals["req-1"]
        assert len(started.calls) == 1
        # It recommended approval while filing a blocking finding. The proposal
        # records both, unchanged — the resolution is the adjudicator's, and
        # this path has no field to pre-empt it with.
        assert proposal.recommended.value == "approve"
        assert len(proposal.findings) == 1
        assert not hasattr(proposal, "verdict")

    async def test_the_adjudicator_overrides_the_reviewers_own_recommendation(
        self, tmp_path: Path
    ) -> None:
        # The other half: the proposal above, adjudicated. A reviewer cannot
        # self-approve past its own evidence.
        from models import ReviewVerdict
        from review_authority import AdjudicationReason, adjudicate

        settings = _settings(tmp_path, CANARY_REPO)
        spawn = SpawnCounter(
            stdout=json.dumps(
                {
                    "recommended": "approve",
                    "summary": "looks fine to me",
                    "findings": [
                        {"summary": "the bound is off by one", "blocking": True}
                    ],
                }
            )
        )
        built, _log, _started, _git = _assemble(
            tmp_path,
            name="adjudicate",
            canary=None,
            wired=True,
            settings=settings,
            spawn=spawn,
        )
        actuator = built._review_dispatcher  # noqa: SLF001
        assert actuator is not None
        await _observe(built)

        verdict, reason = adjudicate(
            actuator.last_proposals["req-1"],
            ci_green=True,
            hitl_required=False,
            reviewer_independent=True,
            evidence_head_sha=HEAD,
            current_head_sha=HEAD,
        )

        assert verdict is ReviewVerdict.REQUEST_CHANGES
        # The REASON, not just the verdict. "Request changes" is also what a
        # red CI or a required HITL produces, so without this the assertion
        # would pass for a reviewer whose recommendation was never overridden.
        assert reason is AdjudicationReason.FINDINGS_PRESENT
