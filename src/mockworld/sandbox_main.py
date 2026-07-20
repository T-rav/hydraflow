"""Sandbox entrypoint — boots HydraFlow with Fake adapters injected.

Used by docker-compose.sandbox.yml and by anyone wanting to run HydraFlow
against simulated GitHub/LLM state. Reads a seed JSON path from argv[1]
or from $HYDRAFLOW_MOCKWORLD_SEED.

Production runs the `hydraflow` console script (server:main) which never
imports this module — Fakes are unreachable from the production code path.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from dashboard import HydraFlowDashboard
from events import EventBus
from mockworld.fakes import (
    FakeGitHub,
    FakeIssueFetcher,
    FakeIssueStore,
    FakeLLM,
    FakeWorkspace,
)
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner
from mockworld.seed import MockWorldSeed
from orchestrator import HydraFlowOrchestrator
from ports import IssueFetcherPort, IssueStorePort, PRPort, WorkspacePort
from runtime_config import load_runtime_config
from service_registry import (
    WorkerRegistryCallbacks,
    build_services,
    build_state_tracker,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig


def _apply_sandbox_config_overrides(config: HydraFlowConfig) -> None:
    """Turn off production code paths that reach services unreachable on the
    air-gapped sandbox network (``internal: true`` in docker-compose.sandbox.yml).

    The four primary LLM-backed runners (triage/plan/agent/review) are already
    replaced with FakeLLM; these flags turn off the remaining external reachers,
    which otherwise either hang for the full subprocess timeout or hard-fail:

    - ``transcript_summarization``/``research``: secondary ``claude`` callers
      (TranscriptSummarizer after each agent phase; ResearchRunner before each
      plan phase) that hang ~30s on api_retry backoff before failing.
    - ``contract_refresh_external``: ContractRefreshLoop's github/claude/docker
      recorders reach the contracts-sandbox repo / api.anthropic.com / alpine
      pull, each blocking up to the 120s subprocess timeout (s30).
    - ``merge_policy`` (#9754): CH-3 ``enforce_merge_policy`` fetches PR labels
      via a RAW ``gh pr view --json labels`` subprocess
      (``merge_policy._fetch_pr_labels`` — deliberately not routed through
      PRPort, so FakeGitHub never sees it). On the air-gapped network that gh
      call runs against an empty ``config.repo``, falls back to git, and fails
      with "not a git repository", so EVERY approved PR's merge raises and no
      issue reaches the "merged" outcome (s01's happy path). The compliance
      gate has its own unit tests; the sandbox exercises the pipeline.
    """
    config.transcript_summarization_enabled = False  # type: ignore[misc]
    config.research_enabled = False  # type: ignore[misc]
    config.contract_refresh_external_enabled = False  # type: ignore[misc]
    config.merge_policy_enabled = False  # type: ignore[misc]


def _load_seed() -> MockWorldSeed:
    """Read the seed file path from argv or env, return the seed."""
    path: str | None = sys.argv[1] if len(sys.argv) > 1 else None
    if path is None:
        path = os.environ.get("HYDRAFLOW_MOCKWORLD_SEED")
    if not path:
        return MockWorldSeed()
    return MockWorldSeed.from_json(Path(path).read_text())


class _SeededRefineLLM:
    """Air-gapped stand-in for ``SkillPromptEvalLoop``'s one-shot refine client.

    Returns a scenario-scripted raw response (a ```diff fence) so refine
    synthesis never shells out to a real ``claude`` under the sandbox's
    air-gapped network — the same escape class that wedged discover/shape in
    #9796. Structurally satisfies the loop's private ``_RefineLLM`` protocol
    (a single ``async complete(prompt) -> str``); ``_refine_llm_complete``
    uses it verbatim once ``sandbox_main`` injects it onto the loop.
    """

    def __init__(self, response: str) -> None:
        self._response = response

    async def complete(self, prompt: str) -> str:
        # ``prompt`` is ignored by design — the response is scenario-scripted.
        _ = prompt
        return self._response


def _load_phase_script(
    fake_llm: FakeLLM, phase_name: str, issue_number: int, payload: object
) -> None:
    """Translate one seed.phase_scripts entry into FakeLLM.script_* calls.

    Each phase has a different inner shape (see ``MockWorldSeed.phase_scripts``
    docstring). This loader is the single point where the JSON shapes are
    decoded; the FakeLLM ``script_*`` methods themselves take typed kwargs.

    Unknown phase names log a warning and are skipped — sandbox scenarios
    cannot regress the seed loader by misnaming a phase, but they also can't
    silently land an unwired phase that looks correct.
    """
    if phase_name == "discover":
        assert isinstance(payload, list)
        for entry in payload:
            fake_llm.script_discover(
                issue_number,
                coherent=bool(entry.get("coherent", True)),
                queries_required=list(entry.get("queries_required", []) or []),
                summary=str(entry.get("summary", "") or ""),
                findings=list(entry.get("findings", []) or []),
            )
    elif phase_name == "plan_review":
        assert isinstance(payload, list)
        for entry in payload:
            fake_llm.script_plan_review(
                issue_number,
                verdict=entry["verdict"],
                gaps=list(entry.get("gaps", []) or []),
            )
    elif phase_name == "shape_council":
        assert isinstance(payload, dict)
        # Inner keys are round numbers; from_json coerces them to int.
        fake_llm.script_shape_council(issue_number, payload)
    elif phase_name == "implement_spec_review":
        assert isinstance(payload, list)
        for entry in payload:
            fake_llm.script_implement_spec_review(
                issue_number,
                compliant=bool(entry.get("compliant", True)),
                gaps=list(entry.get("gaps", []) or []),
                reasoning=str(entry.get("reasoning", "") or ""),
            )
    else:
        # Unknown phase name — log and skip so a typo can't silently break.
        import logging  # noqa: PLC0415

        logging.getLogger("hydraflow.sandbox_main").warning(
            "Unknown phase_scripts phase %r for issue #%d — ignored",
            phase_name,
            issue_number,
        )


def _build_caretaker_enabled_cb(
    loops_enabled: list[str] | None,
) -> Callable[[str], bool]:
    """Build the kill-switch gate for caretaker loops (ADR-0049).

    Semantics of ``MockWorldSeed.loops_enabled``:

    - ``None`` — all caretaker loops enabled (production default; scenario
      didn't opt into a subset).
    - ``[]`` — no caretaker loops enabled (universal kill-switch — proves
      ADR-0049 wiring; phase orchestrators are unaffected because they
      consult ``BGWorkerManager.is_enabled`` via the orchestrator's own
      ``is_bg_worker_enabled``, not this callback).
    - ``["name1", "name2", ...]`` — only those caretakers are enabled.
      Names match the keys in ``HydraFlowOrchestrator._bg_loop_registry``
      (e.g. ``"workspace_gc"``, ``"dependabot_merge"``, ``"ci_monitor"``).

    This callback is fed into ``WorkerRegistryCallbacks.is_enabled`` and
    becomes each caretaker's ``LoopDeps.enabled_cb`` — the in-body
    ``self._enabled_cb(self._worker_name)`` gate every
    ``BaseBackgroundLoop`` subclass checks per ADR-0049. Phase
    orchestrators (``_triage_loop``, ``_discover_loop``, ``_shape_loop``,
    ``_plan_loop``, ``_implement_loop``, ``_review_loop``, ``_hitl_loop``)
    use a different gate (``orchestrator.is_bg_worker_enabled`` →
    ``BGWorkerManager``) and so are not affected here. That's the
    per-triage-comment-on-#8483 contract: the kill-switch suppresses
    cadence-driven loops, not work-driven phase orchestrators.
    """
    if loops_enabled is None:
        return lambda *_a, **_kw: True
    allowed = frozenset(loops_enabled)
    return lambda name, *_a, **_kw: name in allowed


async def main() -> None:
    import logging as _diaglog  # noqa: PLC0415  # DIAG-9925 temporary

    _diaglog.basicConfig(level=_diaglog.INFO, force=True)  # DIAG-9925 temporary
    config = load_runtime_config()
    # Disable production code paths that reach services unreachable on the
    # air-gapped sandbox network (see the helper for the per-flag rationale).
    _apply_sandbox_config_overrides(config)
    seed = _load_seed()
    event_bus = EventBus()
    state = build_state_tracker(config)
    stop_event = asyncio.Event()

    # Build the Fake adapter set from the seed.
    # NOTE: Casts here intentionally bypass strict Port conformance — the
    # current FakeIssueStore / FakeIssueFetcher have a narrower surface
    # than the production Ports require (no get_triageable / mark_active /
    # fetch_issues_by_labels yet). PR B widens the Fakes to satisfy the
    # full IssueStorePort / IssueFetcherPort contract; until then the
    # cast lets sandbox_main type-check while signaling the gap. At
    # runtime the FakeLLM / FakeWorkspace / FakeGitHub adapters carry
    # the entire required surface for the loops PR A actually exercises.
    workspaces = cast(WorkspacePort, FakeWorkspace(config.workspace_base))
    # Single FakeGitHub instance — shared by all three Fake adapters.
    # Using ``from_seed`` independently would create three isolated copies,
    # so a PR created via ``prs.create_pr`` wouldn't be visible to the
    # fetcher's ``fetch_reviewable_prs`` and the review loop would loop
    # forever requeuing the issue. The fetcher / store wrap the same
    # ``FakeGitHub`` so any state mutation is visible to all readers.
    shared_github = FakeGitHub.from_seed(seed)
    fetcher = cast(IssueFetcherPort, FakeIssueFetcher(github=shared_github))
    store = cast(
        IssueStorePort, FakeIssueStore(github=shared_github, event_bus=event_bus)
    )
    prs = cast(PRPort, shared_github)

    # FakeLLM provides triage_runner / planners / agents / reviewers from
    # the seed.scripts payload. Without this, the sandbox would attempt
    # real LLM calls and fail under the air-gapped network.
    fake_llm = FakeLLM()
    # Defaults to 0.0 (no-op) — see MockWorldSeed.plan_hold_seconds docstring
    # for why a scenario (e.g. s52_human_steering_directive) might set this.
    fake_llm.plan_hold_seconds = seed.plan_hold_seconds
    for phase, by_issue in seed.scripts.items():
        for issue_number, results in by_issue.items():
            getattr(fake_llm, f"script_{phase}")(issue_number, results)

    # Advisor scripts use a 3-arg shape: (issue_number, role, results) — the
    # 2-arg ``script_<phase>`` loop above can't carry the role axis, so they
    # live in their own seed field. Empty for non-advisor scenarios, which
    # keeps every existing seed payload unchanged.
    for issue_number, by_role in seed.advisor_scripts.items():
        for role, results in by_role.items():
            fake_llm.script_advisor(issue_number, role, results)

    # ADR-0063 phase-level scripts (W3a/W3b/W4/W5). Each phase entry maps
    # to a distinct FakeLLM.script_* call. Empty for pre-W3a/W3b/W4/W5
    # scenarios so existing seeds carry no payload here.
    for phase_name, by_issue in seed.phase_scripts.items():
        for issue_number, payload in by_issue.items():
            _load_phase_script(fake_llm, phase_name, int(issue_number), payload)

    # Pre-seed the auto-agent attempt counter (decompose-to-converge, ADR-0105).
    # Lets s54 start an issue already at `auto_agent_max_attempts` so the
    # decompose-or-escalate terminal fires on the first tick, instead of burning
    # real auto-agent attempts to reach the cap. Empty for other scenarios.
    for issue_number, count in seed.auto_agent_attempts.items():
        for _ in range(count):
            state.bump_auto_agent_attempts(int(issue_number))

    # Every async-touched ``subprocess.run`` site in production code now
    # specifies ``timeout=`` (PRs #8454, #8456, #8468 — enforced by
    # ``tests/regressions/test_async_subprocess_timeouts.py``), so caretaker
    # loops that try to call out under air-gap fail fast instead of hanging
    # the dashboard's uvicorn bind. No sandbox-specific carve-out is needed.
    # ADR-0049 universal kill-switch wiring (#8483). ``seed.loops_enabled``
    # gates caretaker-loop ``enabled_cb`` only; phase orchestrators consult
    # ``BGWorkerManager.is_enabled`` and are unaffected. See
    # ``_build_caretaker_enabled_cb`` docstring for full semantics.
    # Caretaker-loop tick interval — default 60s (historical cadence); a long
    # multi-hop scenario (s55) lowers it via the seed so its many pipeline stages
    # advance fast enough for CI's slower runners. Bind the value now (loop late
    # binding would otherwise capture the name, not the value).
    _loop_interval = seed.sandbox_loop_interval
    callbacks = WorkerRegistryCallbacks(
        update_status=lambda *_a, **_kw: None,
        is_enabled=_build_caretaker_enabled_cb(seed.loops_enabled),
        get_interval=lambda *_a, _iv=_loop_interval, **_kw: _iv,
    )

    # FakeSubprocessRunner short-circuits every remaining shell-out to
    # ``claude -p`` that isn't covered by ``runners=fake_llm`` — most
    # critically ``TranscriptSummarizer``, ``HITLRunner``, and the
    # pre-quality-review skill subprocesses inside ``AgentRunner``.
    # Without this override they hit the air-gapped network, retry for
    # ~90s each, and overrun the scenario timeout.  The default
    # FakeDocker response is a single ``{success: True}`` event that
    # returns instantly.
    fake_docker = FakeDocker()
    fake_subprocess_runner = FakeSubprocessRunner(fake_docker)

    svc = build_services(
        config,
        event_bus,
        state,
        stop_event,
        callbacks,
        prs=prs,
        workspaces=workspaces,
        store=store,
        fetcher=fetcher,
        runners=fake_llm,
        subprocess_runner=fake_subprocess_runner,
    )

    # Attach the advisor-routing sentinel — mirrors
    # tests/scenarios/fakes/mock_world.py::_wire_targets so
    # ReviewPhase._build_post_verify_runner's ``_PostVerifyRunner.run``
    # adapter routes advisor consults into FakeLLM (via
    # ``pop_advisor_result``) instead of falling through to
    # ``ReviewRunner._execute``, which would spawn a real Claude
    # subprocess and fail under the sandbox's air-gapped network.
    #
    # The sentinel must land on the SAME object the production runner
    # adapter probes (``parent._reviewers.__dict__``). With
    # ``runners=fake_llm`` above, ``svc.reviewers`` IS the
    # ``_FakeReviewRunner`` — a plain Python instance whose ``__dict__``
    # carries the assignment cleanly.
    svc.reviewers._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]

    # ADR-0063 sentinel wiring (W3a/W3b/W4/W5). Each runner consults the
    # sentinel via ``getattr(self, "_mockworld_fake_llm", None)`` in its
    # subprocess-dispatch method; setting the attribute here lets sandbox
    # scenarios drive failure-path recovery without producing synthetic
    # subprocess transcripts.
    discover_runner = getattr(svc.discover_phase, "_runner", None)
    if discover_runner is not None:
        discover_runner._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    plan_reviewer = getattr(svc.planner_phase, "_plan_reviewer", None)
    if plan_reviewer is not None:
        plan_reviewer._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    expert_council = getattr(svc.shape_phase, "_council", None)
    if expert_council is not None:
        expert_council._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    # ShapeRunner post-dates the ``runners=fake_llm`` rebinding seam (which
    # covers only triage/plan/implement/review), so build_services constructs
    # a REAL one whose ``run_turn`` subprocess wedges the air-gapped sandbox
    # exactly like the DiscoverRunner spawn (#9796 — froze the shape loop
    # heartbeat once discover was unblocked). Drop it to None: ShapePhase's
    # no-runner path posts stub Direction A/B options and the scripted
    # ExpertCouncil (sentinel attached above) selects the direction —
    # mirroring the Tier-1 in-process harness, which wires no shape runner
    # either (tests/scenarios/fakes/mock_world.py).
    svc.shape_phase._runner = None
    spec_reviewer = getattr(svc.implementer, "_spec_reviewer", None)
    if spec_reviewer is not None:
        spec_reviewer._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    # DiagnosticRunner.diagnose spawns a real ``claude`` subprocess that hangs
    # in the air-gapped sandbox; the sentinel routes it to a not-fixable
    # diagnosis so review-fix-cap escalations reach HITL (s05).
    diagnostic_runner = getattr(svc.diagnostic_loop, "_runner", None)
    if diagnostic_runner is not None:
        diagnostic_runner._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    # DecompositionCouncil (decompose-to-converge, ADR-0105): route its two
    # seam calls (direction + validation) to scripted transcripts so a scenario
    # (s54) can drive the decompose terminal deterministically. The council
    # lives on the auto-agent loop when epic_manager/runner were wired.
    decompose_council = getattr(svc.auto_agent_preflight_loop, "_council", None)
    if decompose_council is not None:
        decompose_council._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]

    # Prompt self-refinement (#9724) air-gap seam. SkillPromptEvalLoop's refine
    # path has two pre-PR escape points that ``runners=fake_llm`` does NOT cover:
    # ``_run_corpus`` spawns ``make trust-adversarial`` and ``_refine_llm_complete``
    # spawns a real ``claude`` via run_lightweight_agent (the #9796 real-claude
    # wedge class). When a scenario (s56) scripts a corpus regression, replace
    # both with air-gapped stand-ins so refine runs on FakeLLM/FakeGitHub state:
    # ``_run_corpus`` returns the seeded PASS→FAIL case and ``_refine_llm`` returns
    # the seeded patch. The seeded patch is crafted to trip ``check_tripwires`` so
    # the loop exercises the full synth→parse→tripwire chain and returns BEFORE
    # ``_open_refine_pr`` — whose live-validation ``corpus_runner`` subprocess and
    # raw git/gh PR-open have no Fake seam and cannot be air-gapped. Empty seed
    # fields (every other scenario, incl. s17) leave production ``_run_corpus`` /
    # ``_refine_llm`` untouched.
    if seed.skill_prompt_corpus_cases:
        _refine_loop = svc.skill_prompt_eval_loop
        _seeded_cases: list[dict[str, Any]] = [
            dict(c) for c in seed.skill_prompt_corpus_cases
        ]

        async def _seeded_run_corpus(
            _cases: list[dict[str, Any]] = _seeded_cases,
        ) -> list[dict[str, Any]]:
            return [dict(c) for c in _cases]

        # vars() assignment: instance-level seam without tripping the
        # method-assign checker or ruff's B010 setattr rewrite.
        vars(_refine_loop)["_run_corpus"] = _seeded_run_corpus
        _refine_loop._refine_llm = _SeededRefineLLM(seed.skill_prompt_refine_patch)

    orch = HydraFlowOrchestrator(
        config,
        event_bus=event_bus,
        state=state,
        services=svc,
    )

    dashboard = HydraFlowDashboard(
        config=config,
        event_bus=event_bus,
        state=state,
        orchestrator=orch,
    )
    await dashboard.start()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # Drive the pipeline. Without this, the dashboard would serve /healthz
    # but no loops would tick, no issues would advance, and Tier-2
    # scenarios would always time out at the API-poll step.
    orch_task = asyncio.create_task(orch.run(), name="hydraflow-orchestrator")

    try:
        await stop_event.wait()
    finally:
        if orch.running:
            await orch.stop()
        # Allow orch_task to clean up (it observes stop_event via orch.stop()).
        if not orch_task.done():
            orch_task.cancel()
        await asyncio.gather(orch_task, return_exceptions=True)
        await dashboard.stop()


if __name__ == "__main__":
    asyncio.run(main())
