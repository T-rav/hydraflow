"""MockWorld scenario for decompose-to-converge (ADR-0105) — Task 8.

Proves the auto-agent's decompose-before-HITL terminal
(``preflight.decompose_terminal.decompose_or_escalate``, wired into
``AutoAgentPreflightLoop`` at the attempt-cap pre-check per Task 7) end to
end against MockWorld fakes: FakeGitHub, a real ``StateTracker`` (via
``MockWorld.harness.state``), and a real ``EpicManager``/``IssueDecomposer``
pair. Only the council's LLM seam
(``DecompositionCouncil`` -> ``runner_utils.run_lightweight_agent``) is
scripted — no real model is ever invoked, mirroring
``tests/test_decomposition_council.py``'s own seam-patching convention.

Four cases (per ``.superpowers/sdd/task-8-brief.md``):

(a) An exhausted stuck issue + council APPROVE -> an epic + children are
    created, the parent epic is registered ``auto_decomposed``, children are
    scoped narrower than the parent, and NO ``human-required`` is added.
    Then the children close/merge and ``epic_sweeper`` auto-closes the
    parent for free (rollup).
(b) An undecomposable stuck issue + council DECLINE at high confidence ->
    the issue DOES reach ``human-required`` (the genuine dead end still
    escalates to a human).
(c) Nested: a child from (a) itself later stalls and decomposes a SECOND
    time (depth 1, exercised here via an explicit
    ``HYDRAFLOW_MAX_DECOMPOSITION_DEPTH=2`` override -- P1 ships with a
    default of 1, i.e. this nested path is OFF by default; a stalled child
    goes to HITL instead of re-decomposing, see ADR-0105's Consequences) ->
    the grandchild epic closes once its own children close, and the ROOT
    epic closes only once its own children (the superseded-but-tracked
    stalled child + its still-open sibling) are all closed. Proven at three
    sweep checkpoints so the root is never observed to close early. The
    premature-root-close gap this test documents (no epic-to-epic lineage
    in ``EpicState``) is why nesting is capped off by default; a follow-up
    tracked in ADR-0105 adds the lineage link so the default can safely
    rise back to 2.
(d) The Task-5 intake-vector skip guard: an issue already labelled
    ``auto-decomposed-child`` does NOT get re-split via the *intake* triage
    path, even when triage's complexity gate and the decomposition seam are
    both scripted to approve a split — proven by asserting no new epic is
    created despite the green light, so the assertion is non-vacuous
    (removing the guard would make this test start failing).
(e) The landed-fix guard (#11480): a stalled issue whose fix already landed
    (a ``Fixes #N`` commit on the base branch) does NOT get re-sliced —
    proven with the council's LLM seam scripted to explode if ever called,
    so a regression that removes the guard fails loudly instead of
    silently creating an unwanted epic. Paired with a same-shape contrast
    case (no landed-fix commit seeded) that DOES decompose normally, so the
    guard is proven to discriminate on the commit evidence rather than
    always (or never) firing.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _direction_reply(**fields: object) -> str:
    """A council direction-pass reply proposing 2 narrower, independent children."""
    fields.setdefault("epic_title", "Epic: split the stalled issue")
    fields.setdefault(
        "epic_body",
        "## Sub-issues\n\n- [ ] Narrower slice A\n- [ ] Narrower slice B",
    )
    fields.setdefault(
        "children",
        [
            {
                "title": "Narrower slice A",
                "body": "A small, independently shippable slice of the stalled issue.",
            },
            {
                "title": "Narrower slice B",
                "body": "A second small, independently shippable slice.",
            },
        ],
    )
    fields.setdefault(
        "rationale",
        "Two independently shippable slices, each narrower than the parent.",
    )
    return json.dumps(fields)


def _validation_reply(**fields: object) -> str:
    fields.setdefault("decision", "approve")
    fields.setdefault("confidence", "high")
    fields.setdefault("reasoning", "Sound, non-overlapping split.")
    return json.dumps(fields)


def _script_council(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> None:
    """Monkeypatch the council's LLM seam to return *replies* in call order.

    Mirrors ``tests/test_decomposition_council.py``'s ``_council`` helper:
    ``DecompositionCouncil._execute_council`` does a deferred
    ``from runner_utils import run_lightweight_agent`` every call, so
    patching the module attribute intercepts every direction/validation
    pass. No real model is ever invoked. Supply exactly as many replies as
    the test expects seam calls (2 per council decision: direction +
    validation) — once exhausted, the last reply repeats rather than
    raising, so an unexpected extra call fails on an assertion instead of
    an opaque IndexError.
    """
    from execution import SimpleResult  # noqa: PLC0415

    remaining = list(replies)

    async def _fake_seam(**_kwargs: object) -> SimpleResult:
        stdout = remaining.pop(0) if remaining else replies[-1]
        return SimpleResult(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _fake_seam)


def _make_epic_manager(world: MockWorld):
    """A real EpicManager wired against this world's real state + FakeGitHub.

    ``register_epic``/``get_progress`` (the only methods the stall-path
    ``IssueDecomposer`` exercises) never touch ``fetcher`` — a bare
    MagicMock is sufficient there. ``state``/``prs`` are the world's real
    ones so the registered ``EpicState`` is visible to ``epic_sweeper``.
    """
    from epic import EpicManager  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415

    return EpicManager(
        config=world.harness.config,
        state=world.harness.state,
        prs=world.github,
        fetcher=MagicMock(),
        event_bus=EventBus(),
    )


def _make_issue_fetcher(world: MockWorld):
    """An ``IssueFetcherPort`` adapter reading live from ``world.github``.

    ``epic_sweeper_loop`` needs ``fetch_issues_by_labels``/
    ``fetch_issue_by_number`` (the real ``IssueFetcher`` shells out to
    ``gh``, so it can't run inside a scenario). Unlike the static-return
    mocks ``tests/scenarios/test_caretaker_loops.py``'s L12 tests use, this
    reads ``world.github._issues`` live at call time — required here
    because the same epic gets swept multiple times across a changing
    child-closed state (case c sweeps at 3 checkpoints).
    """
    from models import GitHubIssue, GitHubIssueState  # noqa: PLC0415

    def _to_gh_issue(fake_issue: object) -> GitHubIssue:
        return GitHubIssue(
            number=fake_issue.number,  # type: ignore[attr-defined]
            title=fake_issue.title,  # type: ignore[attr-defined]
            body=fake_issue.body,  # type: ignore[attr-defined]
            labels=list(fake_issue.labels),  # type: ignore[attr-defined]
            state=GitHubIssueState(fake_issue.state),  # type: ignore[attr-defined]
        )

    async def _fetch_issues_by_labels(
        labels: object,
        limit: int = 50,
        exclude_labels: object = None,
        require_complete: bool = False,
    ) -> list[GitHubIssue]:
        wanted = set(labels) if isinstance(labels, list | tuple | set) else {labels}
        matches = [
            _to_gh_issue(fi)
            for fi in world.github._issues.values()
            if fi.state == "open" and wanted & set(fi.labels)
        ]
        return matches[:limit]

    async def _fetch_issue_by_number(issue_number: int) -> GitHubIssue | None:
        fi = world.github._issues.get(issue_number)
        return _to_gh_issue(fi) if fi is not None else None

    fetcher = MagicMock()
    fetcher.fetch_issues_by_labels = AsyncMock(side_effect=_fetch_issues_by_labels)
    fetcher.fetch_issue_by_number = AsyncMock(side_effect=_fetch_issue_by_number)
    return fetcher


def _wire_decompose(world: MockWorld, epic_manager: object) -> None:
    """Seed the ``auto_agent_preflight`` catalog builder's decompose ports.

    ``auto_agent_state`` is the world's real ``StateTracker`` (so attempts/
    escalation-context/epic-state reads are all backed by real persistence).
    ``auto_agent_decompose_runner`` is a placeholder — the council's LLM
    seam is scripted via :func:`_script_council`, so the runner object
    itself is never actually invoked (see ``_build_auto_agent_preflight``'s
    updated docstring in ``tests/scenarios/catalog/loop_registrations.py``).
    """
    _seed_ports(
        world,
        auto_agent_state=world.harness.state,
        auto_agent_epic_manager=epic_manager,
        auto_agent_decompose_runner=AsyncMock(),
    )


def _wire_epic_sweeper(world: MockWorld) -> None:
    _seed_ports(
        world,
        issue_fetcher=_make_issue_fetcher(world),
        epic_sweeper_state=world.harness.state,
    )


def _find_epic_numbers(world: MockWorld, epic_label: str) -> list[int]:
    return sorted(
        num for num, issue in world.github._issues.items() if epic_label in issue.labels
    )


def _exhaust_attempts(world: MockWorld, issue_number: int) -> None:
    """Bump auto_agent_attempts to the default cap (3) for *issue_number*."""
    for _ in range(world.harness.config.auto_agent_max_attempts):
        world.harness.state.bump_auto_agent_attempts(issue_number)


# ---------------------------------------------------------------------------
# (a) Exhausted stuck issue decomposes instead of human-required; parent
#     converges for free once children close.
# ---------------------------------------------------------------------------


class TestExhaustedIssueDecomposesThenParentConverges:
    async def test_council_approve_creates_epic_no_human_required_then_sweeps_closed(
        self, tmp_path, monkeypatch
    ) -> None:
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 501
        parent_title = "Root issue: the frobnicator never converges"
        parent_body = (
            "The frobnicator keeps failing CI no matter what the auto-agent tries."
        )
        world.add_issue(
            issue_number,
            parent_title,
            parent_body,
            labels=["hitl-escalation", "flaky-test-stuck"],
        )
        _exhaust_attempts(world, issue_number)

        epic_manager = _make_epic_manager(world)
        _wire_decompose(world, epic_manager)
        _script_council(
            monkeypatch,
            [
                _direction_reply(),
                _validation_reply(decision="approve", confidence="high"),
            ],
        )

        results = await world.run_with_loops(["auto_agent_preflight"], cycles=1)

        assert results["auto_agent_preflight"] == {
            "status": "ok",
            "issues_processed": 1,
            "result_status": "skipped_decomposed",
            "suppressed": 0,
        }

        # The stuck issue was superseded, closed, and marked decomposed --
        # NOT sent to human-required (the genuine ADR-0105 behavior change).
        assert world.github.issue(issue_number).state == "closed"
        assert "human-required" not in world.github.issue(issue_number).labels
        assert world.harness.state.get_issue_status(issue_number) == "decomposed"

        epic_numbers = _find_epic_numbers(world, cfg.epic_label[0])
        assert len(epic_numbers) == 1, (
            f"expected exactly 1 new epic, got {epic_numbers}"
        )
        epic_number = epic_numbers[0]

        epic_state = world.harness.state.get_epic_state(epic_number)
        assert epic_state is not None
        assert epic_state.auto_decomposed is True
        assert len(epic_state.child_issues) == 2

        # Children are scoped narrower than the parent: distinct, smaller
        # titles/bodies -- never a clone of the stalled parent issue.
        children = [world.github.issue(n) for n in epic_state.child_issues]
        for child in children:
            assert child.title != parent_title
            assert child.body != parent_body
            assert cfg.epic_child_label[0] in child.labels
            assert cfg.find_label[0] in child.labels
            assert cfg.auto_decomposed_child_label[0] in child.labels

        # --- Parent convergence is free: sweep before/after children close. ---
        _wire_epic_sweeper(world)

        pre_sweep = await world.run_with_loops(["epic_sweeper"], cycles=1)
        assert pre_sweep["epic_sweeper"]["swept"] == 0
        assert world.github.issue(epic_number).state == "open"

        for child_number in epic_state.child_issues:
            await world.github.close_issue(child_number)

        post_sweep = await world.run_with_loops(["epic_sweeper"], cycles=1)
        assert post_sweep["epic_sweeper"]["swept"] == 1
        assert world.github.issue(epic_number).state == "closed"


# ---------------------------------------------------------------------------
# (b) Undecomposable stuck issue still reaches human-required.
# ---------------------------------------------------------------------------


class TestUndecomposableIssueStillEscalatesToHuman:
    async def test_high_confidence_decline_reaches_human_required(
        self, tmp_path, monkeypatch
    ) -> None:
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 601
        world.add_issue(
            issue_number,
            "Fix off-by-one in the retry counter",
            "Single-line arithmetic bug -- there is nothing here to split.",
            labels=["hitl-escalation", "flaky-test-stuck"],
        )
        _exhaust_attempts(world, issue_number)

        epic_manager = _make_epic_manager(world)
        _wire_decompose(world, epic_manager)
        _script_council(
            monkeypatch,
            [
                _direction_reply(),
                _validation_reply(
                    decision="reject",
                    confidence="high",
                    reasoning="Atomic single-line fix -- children would be near-duplicates.",
                ),
            ],
        )

        results = await world.run_with_loops(["auto_agent_preflight"], cycles=1)

        assert results["auto_agent_preflight"] == {
            "status": "ok",
            "issues_processed": 1,
            "result_status": "skipped_exhausted",
            "suppressed": 0,
        }

        labels = world.github.issue(issue_number).labels
        assert "human-required" in labels
        assert "auto-agent-exhausted" in labels
        assert world.github.issue(issue_number).state == "open"
        assert world.harness.state.get_issue_status(issue_number) != "decomposed"
        assert _find_epic_numbers(world, cfg.epic_label[0]) == []


# ---------------------------------------------------------------------------
# (c) Nested decomposition cascades: a child of (a) itself stalls and
#     decomposes a second time; the root epic converges only once its own
#     children (incl. the superseded-but-tracked stalled child) are done.
# ---------------------------------------------------------------------------


class TestNestedDecompositionCascadesToRoot:
    async def test_second_hop_decompose_then_cascading_closure(
        self, tmp_path, monkeypatch
    ) -> None:
        # Default max_decomposition_depth is 2 (#9757), so a stalled depth-1
        # child re-decomposes rather than going to HITL — no env override
        # needed. This is also the default-depth-2 regression: the second hop
        # below only happens because the default now permits depth 2.
        world = MockWorld(tmp_path)
        assert world.harness.config.max_decomposition_depth == 2
        cfg = world.harness.config
        root_number = 701
        world.add_issue(
            root_number,
            "Root issue: sprawling migration",
            "Touches three subsystems at once; the auto-agent cannot converge.",
            labels=["hitl-escalation", "flaky-test-stuck"],
        )
        _exhaust_attempts(world, root_number)

        epic_manager = _make_epic_manager(world)
        _wire_decompose(world, epic_manager)
        _wire_epic_sweeper(world)

        # 4 scripted replies: [direction1, validation1(approve)] for the
        # root's split, [direction2, validation2(approve)] for the second
        # hop (the stalled child's own split).
        _script_council(
            monkeypatch,
            [
                _direction_reply(),
                _validation_reply(decision="approve", confidence="high"),
                _direction_reply(
                    epic_title="Epic: split the grandchild work",
                    epic_body=(
                        "## Sub-issues\n\n- [ ] Grandchild slice A\n- [ ] Grandchild slice B"
                    ),
                    children=[
                        {
                            "title": "Grandchild slice A",
                            "body": "Even narrower slice A.",
                        },
                        {
                            "title": "Grandchild slice B",
                            "body": "Even narrower slice B.",
                        },
                    ],
                    rationale="The stalled child itself needed one more split.",
                ),
                _validation_reply(decision="approve", confidence="high"),
            ],
        )

        # --- Hop 1: the root decomposes into epic E1 with children [C1, C2]. ---
        first = await world.run_with_loops(["auto_agent_preflight"], cycles=1)
        assert first["auto_agent_preflight"]["result_status"] == "skipped_decomposed"

        e1_numbers = _find_epic_numbers(world, cfg.epic_label[0])
        assert len(e1_numbers) == 1
        e1 = e1_numbers[0]
        e1_state = world.harness.state.get_epic_state(e1)
        assert e1_state is not None
        assert len(e1_state.child_issues) == 2
        c1, c2 = e1_state.child_issues

        # --- C1 itself later stalls and gets escalated to HITL. ---
        await world.github.add_labels(c1, ["hitl-escalation"])
        _exhaust_attempts(world, c1)

        second = await world.run_with_loops(["auto_agent_preflight"], cycles=1)
        assert second["auto_agent_preflight"]["result_status"] == "skipped_decomposed"

        # C1 is now superseded + closed; a SECOND epic (E2) exists, one
        # depth level deeper (1 < max_decomposition_depth=2 via this test's
        # env override -- the cap did not block this second hop; at the P1
        # default of 1 it would have).
        epic_numbers_after_hop2 = _find_epic_numbers(world, cfg.epic_label[0])
        assert len(epic_numbers_after_hop2) == 2
        e2 = next(n for n in epic_numbers_after_hop2 if n != e1)
        e2_state = world.harness.state.get_epic_state(e2)
        assert e2_state is not None
        assert e2_state.decomposition_depth == 1
        assert len(e2_state.child_issues) == 2
        g1, g2 = e2_state.child_issues

        assert world.github.issue(c1).state == "closed"
        assert world.harness.state.get_issue_status(c1) == "decomposed"

        # --- Checkpoint 1: nothing has merged yet -- neither epic sweeps. ---
        cp1 = await world.run_with_loops(["epic_sweeper"], cycles=1)
        assert cp1["epic_sweeper"]["swept"] == 0
        assert world.github.issue(e1).state == "open"
        assert world.github.issue(e2).state == "open"

        # --- Checkpoint 2: the grandchildren merge -- E2 (the second-hop
        # epic) closes, but the ROOT epic does NOT, because its own sibling
        # child C2 (the real remaining work) is still open. ---
        await world.github.close_issue(g1)
        await world.github.close_issue(g2)
        cp2 = await world.run_with_loops(["epic_sweeper"], cycles=1)
        assert cp2["epic_sweeper"]["swept"] == 1
        assert world.github.issue(e2).state == "closed"
        assert world.github.issue(e1).state == "open", (
            "root epic must not close before its own remaining child (C2) "
            "is done, even though the grandchildren already merged"
        )

        # --- Checkpoint 3: C2 (the real remaining work) also completes --
        # only now does the root epic cascade-close. ---
        await world.github.close_issue(c2)
        cp3 = await world.run_with_loops(["epic_sweeper"], cycles=1)
        assert cp3["epic_sweeper"]["swept"] == 1
        assert world.github.issue(e1).state == "closed"

    async def test_root_held_open_when_sibling_closes_before_grandchildren(
        self, tmp_path, monkeypatch
    ) -> None:
        """The premature-close bug (#9757): if the root's OTHER child closes
        before the re-decomposed child's grandchildren, the root must stay open
        until the grandchildren's replacement epic closes. Without the sweeper
        gate the root would see both its children closed and auto-close while
        grandchild work is still live under E2. This is the adverse ordering the
        original cascade test deliberately avoided.
        """
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        root_number = 801
        world.add_issue(
            root_number,
            "Root issue: sprawling migration",
            "Touches three subsystems at once; the auto-agent cannot converge.",
            labels=["hitl-escalation", "flaky-test-stuck"],
        )
        _exhaust_attempts(world, root_number)
        epic_manager = _make_epic_manager(world)
        _wire_decompose(world, epic_manager)
        _wire_epic_sweeper(world)
        _script_council(
            monkeypatch,
            [
                _direction_reply(),
                _validation_reply(decision="approve", confidence="high"),
                _direction_reply(
                    epic_title="Epic: split the grandchild work",
                    epic_body=(
                        "## Sub-issues\n\n- [ ] Grandchild slice A\n- [ ] Grandchild slice B"
                    ),
                    children=[
                        {"title": "Grandchild slice A", "body": "Narrower slice A."},
                        {"title": "Grandchild slice B", "body": "Narrower slice B."},
                    ],
                    rationale="The stalled child itself needed one more split.",
                ),
                _validation_reply(decision="approve", confidence="high"),
            ],
        )

        # Hop 1: root -> E1 [C1, C2].
        await world.run_with_loops(["auto_agent_preflight"], cycles=1)
        e1 = _find_epic_numbers(world, cfg.epic_label[0])[0]
        c1, c2 = world.harness.state.get_epic_state(e1).child_issues

        # C1 stalls -> E2 [G1, G2].
        await world.github.add_labels(c1, ["hitl-escalation"])
        _exhaust_attempts(world, c1)
        await world.run_with_loops(["auto_agent_preflight"], cycles=1)
        e2 = next(n for n in _find_epic_numbers(world, cfg.epic_label[0]) if n != e1)
        g1, g2 = world.harness.state.get_epic_state(e2).child_issues

        # ADVERSE ORDERING: the sibling C2 finishes FIRST, while the
        # grandchildren are still open. The root must NOT close.
        await world.github.close_issue(c2)
        await world.run_with_loops(["epic_sweeper"], cycles=1)
        assert world.github.issue(e1).state == "open", (
            "root epic closed prematurely — C1's replacement epic E2 is still "
            "open (grandchildren live), so C1 is not resolved yet"
        )

        # Grandchildren finish -> E2 closes -> the root now converges.
        await world.github.close_issue(g1)
        await world.github.close_issue(g2)
        await world.run_with_loops(["epic_sweeper"], cycles=2)
        assert world.github.issue(e2).state == "closed"
        assert world.github.issue(e1).state == "closed"


# ---------------------------------------------------------------------------
# (d) Intake triage does not re-split an already auto-decomposed child
#     (Task 5's skip guard).
# ---------------------------------------------------------------------------


class TestIntakeSkipsReSplittingAutoDecomposedChild:
    async def test_auto_child_label_skips_intake_decomposition(self, tmp_path) -> None:
        from epic import EpicManager  # noqa: PLC0415
        from events import EventBus  # noqa: PLC0415
        from mockworld.fakes._factories import TriageResultFactory  # noqa: PLC0415
        from models import EpicDecompResult, NewIssueSpec  # noqa: PLC0415

        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 900

        # PipelineHarness's TriagePhase is built with epic_manager=None
        # (MockWorld._wire_targets doesn't wire an epic_manager -- there is
        # no intake decomposition to test by default). Wire a real one here
        # (mirrors tests/scenarios/test_agent_realistic.py's
        # test_A13_epic_decomposition_creates_child_issues injection
        # pattern) so the Task-5 guard actually has something to bypass.
        world.harness.triage_phase._epic_manager = EpicManager(
            config=cfg,
            state=world.harness.state,
            prs=world.github,
            fetcher=MagicMock(),
            event_bus=EventBus(),
        )
        # world.harness.prs is a bare AsyncMock; MockWorld._wire_targets
        # doesn't wire create_issue onto it (only pre-existing PR/label
        # methods). Wire it to FakeGitHub so a (guard-failure) decompose
        # would actually create observable issues rather than erroring on
        # a MagicMock return value.
        world.harness.prs.create_issue = world.github.create_issue

        auto_child_label = cfg.auto_decomposed_child_label[0]
        labels = [cfg.find_label[0], cfg.epic_child_label[0], auto_child_label]
        world.add_issue(
            issue_number,
            "Auto-decomposed child: narrower slice A",
            "Created by a prior decomposition.",
            labels=labels,
        )

        # Triage would decompose this (ready, clear, complexity above the
        # gate) IF the guard didn't intercept it first.
        world.set_phase_result(
            "triage",
            issue_number,
            TriageResultFactory.create(
                issue_number=issue_number,
                ready=True,
                complexity_score=cfg.epic_decompose_complexity_threshold + 1,
                clarity_score=10,
                needs_discovery=False,
            ),
        )
        # And the decomposition seam is scripted to APPROVE a split -- if
        # the guard is ever removed, this exact test starts creating a
        # nested epic, proving the assertion below is non-vacuous.
        world._llm.triage_runner.script_decomposition(
            issue_number,
            EpicDecompResult(
                should_decompose=True,
                epic_title="Epic: re-split the auto-child",
                epic_body="## Sub-issues\n\n- [ ] X\n- [ ] Y",
                children=[
                    NewIssueSpec(title="X", body="..."),
                    NewIssueSpec(title="Y", body="..."),
                ],
                reasoning="Still complex.",
            ),
        )

        pre_issue_count = len(world.github._issues)

        await world.run_pipeline()

        # No new epic (or any new issue at all) was created by decompose --
        # the guard skipped intake decomposition outright, never reaching
        # run_decomposition's approval.
        assert _find_epic_numbers(world, cfg.epic_label[0]) == []
        assert len(world.github._issues) == pre_issue_count
        assert world.harness.state.get_issue_status(issue_number) != "decomposed"


# ---------------------------------------------------------------------------
# (e) The landed-fix guard (#11480): a stalled issue whose fix already
#     landed does not get re-sliced. Paired with a same-shape contrast case
#     that DOES decompose, proving the guard discriminates on the evidence.
# ---------------------------------------------------------------------------


def _explode_council_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the council's LLM seam raise if it is ever invoked -- proves the
    landed-fix guard short-circuits BEFORE the council runs, not merely that
    the end-to-end outcome happens to look the same."""

    async def _explode(**_kwargs: object) -> None:
        raise AssertionError(
            "the council must never run once a landed-fix commit is found"
        )

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _explode)


class TestLandedFixGuardSkipsReslice:
    async def test_landed_fix_on_base_branch_skips_decomposition(
        self, tmp_path, monkeypatch
    ) -> None:
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 1050
        world.add_issue(
            issue_number,
            "Root issue: the frobnicator never converges",
            "The frobnicator keeps failing CI no matter what the auto-agent tries.",
            labels=["hitl-escalation", "flaky-test-stuck"],
        )
        _exhaust_attempts(world, issue_number)
        world.github.add_gc_branch(
            cfg.base_branch(),
            [
                {
                    "date": "2026-08-18T07:08:00Z",
                    "message": f"Fixes #{issue_number}: retry-cap arithmetic",
                }
            ],
        )

        epic_manager = _make_epic_manager(world)
        _wire_decompose(world, epic_manager)
        _explode_council_seam(monkeypatch)

        results = await world.run_with_loops(["auto_agent_preflight"], cycles=1)

        assert results["auto_agent_preflight"] == {
            "status": "ok",
            "issues_processed": 1,
            "result_status": "skipped_decomposed",
            "suppressed": 0,
        }
        # No epic (or any child) was manufactured for already-finished work.
        assert _find_epic_numbers(world, cfg.epic_label[0]) == []
        assert "human-required" not in world.github.issue(issue_number).labels

    async def test_no_landed_fix_on_base_branch_still_decomposes_normally(
        self, tmp_path, monkeypatch
    ) -> None:
        """Same issue shape as the case directly above, minus the seeded
        base-branch commit -- the council DOES run and an epic + children
        ARE created, proving the guard above fired because of the commit
        evidence, not because decomposition is broken or skipped outright."""
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 1050
        world.add_issue(
            issue_number,
            "Root issue: the frobnicator never converges",
            "The frobnicator keeps failing CI no matter what the auto-agent tries.",
            labels=["hitl-escalation", "flaky-test-stuck"],
        )
        _exhaust_attempts(world, issue_number)
        # No world.github.add_gc_branch(...) seeding here -- the base branch
        # carries no closing-keyword commit for this issue.

        epic_manager = _make_epic_manager(world)
        _wire_decompose(world, epic_manager)
        _script_council(
            monkeypatch,
            [
                _direction_reply(),
                _validation_reply(decision="approve", confidence="high"),
            ],
        )

        results = await world.run_with_loops(["auto_agent_preflight"], cycles=1)

        assert results["auto_agent_preflight"] == {
            "status": "ok",
            "issues_processed": 1,
            "result_status": "skipped_decomposed",
            "suppressed": 0,
        }
        epic_numbers = _find_epic_numbers(world, cfg.epic_label[0])
        assert len(epic_numbers) == 1
        epic_state = world.harness.state.get_epic_state(epic_numbers[0])
        assert epic_state is not None
        assert len(epic_state.child_issues) == 2
