"""Sandbox entrypoint — boots HydraFlow with Fake adapters injected.

Used by docker-compose.sandbox.yml and by anyone wanting to run HydraFlow
against simulated GitHub/LLM state. Reads a seed JSON path from argv[1]
or from $HYDRAFLOW_MOCKWORLD_SEED.

Production runs the `hydraflow` console script (server:main) which never
imports this module — Fakes are unreachable from the production code path.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from bg_worker_manager import BGWorkerManager
from branch_protection_audit import AuditReport, audit_repo
from dashboard import HydraFlowDashboard
from events import EventBus, EventLog, EventType, HydraFlowEvent
from file_util import append_jsonl, atomic_write
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
from models import BackgroundWorkerStatusPayload, EpicState
from orchestrator import HydraFlowOrchestrator
from ports import IssueFetcherPort, IssueStorePort, PRPort, WorkspacePort
from repo_wiki import RepoWikiStore, WikiEntry
from runtime_config import load_runtime_config
from service_registry import (
    WorkerRegistryCallbacks,
    build_services,
    build_state_tracker,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig

# --- Air-gap seam registry (#10012) ----------------------------------------
#
# Every loop/runner module that can lexically spawn an LLM or a subprocess
# (run_lightweight_agent / get_default_runner / stream_claude_process /
# create_subprocess_exec / run_subprocess / run_subprocess_result call sites
# in src/*_loop.py, src/*_runner.py, and src/runners/**) must either declare
# here HOW the sandbox air-gaps it, or sit in the shrink-only grandfathered
# baseline of tests/architecture/test_sandbox_seam_completeness.py. That
# guard AST-enumerates the call sites and reddens when a NEW spawn path
# appears without a declaration — turning the next s51/s56/s57 wedged-sandbox
# incident (#9919, #9925, #10006) into a red unit test at PR time.
#
# Keys are module stems (the loop/worker's module name); values are one of
# SEAM_KINDS:
#
# - "fake_llm_runner": the runner instance is rebound wholesale via
#   ``runners=fake_llm`` in ``build_services`` (triage/plan/implement/review);
#   remaining BaseRunner constructions thread ``runner=subprocess_runner``,
#   which main() below injects as FakeSubprocessRunner.
# - "fake_subprocess_runner": the spawn only happens through the injected
#   SubprocessRunner; main() passes FakeSubprocessRunner so the real docker/
#   host dispatch is never constructed.
# - "mockworld_sentinel": subclasses consult ``_mockworld_fake_llm``
#   (attached by main() below) in their dispatch method and route to FakeLLM
#   before reaching the real spawn; ShapeRunner is dropped to None outright.
# - "seed_seam": main() below injects seed-scripted stand-ins onto the loop
#   instance when the scenario seeds them (and the scenario is crafted to
#   stay within the seam's coverage — see the per-loop comments in main()).
# - "config_disable": ``_apply_sandbox_config_overrides`` turns the spawning
#   code path off wholesale.
SEAM_KINDS: frozenset[str] = frozenset(
    {
        "fake_llm_runner",
        "fake_subprocess_runner",
        "mockworld_sentinel",
        "seed_seam",
        "config_disable",
    }
)

SANDBOX_SEAMS: dict[str, str] = {
    # The four phase runners (triage/plan/implement/review) are replaced by
    # ``runners=fake_llm``; every other build_services BaseRunner gets the
    # injected FakeSubprocessRunner via ``runner=subprocess_runner``.
    "base_runner": "fake_llm_runner",
    # ADR-0063 runners (discover/plan-review/council/spec-review/diagnostic/
    # decompose) consult the ``_mockworld_fake_llm`` sentinel before their
    # BaseSubprocessRunner.run spawn; sentinels are attached in main().
    "base_subprocess_runner": "mockworld_sentinel",
    # ``get_docker_runner`` is the default only when no ``subprocess_runner``
    # is injected; main() always injects FakeSubprocessRunner.
    "docker_runner": "fake_subprocess_runner",
    # External recorders + replay gate path off via
    # ``contract_refresh_external_enabled=False`` (s30).
    "contract_refresh_loop": "config_disable",
    # s56: ``skill_prompt_corpus_cases`` / ``skill_prompt_refine_patch`` seed
    # seams replace ``_run_corpus`` and ``_refine_llm``; the seeded patch trips
    # the tripwire so the loop returns before ``_open_refine_pr``'s raw spawns.
    "skill_prompt_eval_loop": "seed_seam",
    # s57: ``issue_refinement_backlog`` / ``issue_refinement_verdicts`` seed
    # seams replace ``_refinement_llm`` so dup/priority judgments never shell
    # out to a real ``claude``.
    "issue_refinement_loop": "seed_seam",
}


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
    - ``auto_pr_preflight_gate`` (#10013): the pre-flight gate runs
      ``uv run pytest/ruff/arch.runner`` inside bot-PR worktrees; on the
      air-gapped network ``uv``'s environment sync cannot reach PyPI, so
      every full-set stage would hang-then-red and block every bot PR a
      scenario asserts on. The gate has its own unit + regression tests;
      the sandbox exercises the PR pipeline.
    """
    config.transcript_summarization_enabled = False  # type: ignore[misc]
    config.research_enabled = False  # type: ignore[misc]
    config.contract_refresh_external_enabled = False  # type: ignore[misc]
    config.merge_policy_enabled = False  # type: ignore[misc]
    # Frozen-model bypass (the same write the runtime PATCH route uses) —
    # avoids adding another suppression to the disturbance ratchet.
    object.__setattr__(config, "auto_pr_preflight_gate_enabled", False)
    # ``approval_records`` (#9543): MergeStateWatcherLoop's CH-2 reconciler
    # tick reads merged PRs at the raw ``gh`` subprocess boundary
    # (approval_records._list_recently_merged — deliberately not on PRPort, so
    # FakeGitHub never sees it). Under the air-gapped network that read raises
    # every cycle, so ``_do_work`` never returns its conflict-handling stats
    # and the watcher's active outcome is unobservable. The reconciler has its
    # own unit tests; the sandbox exercises the conflict watcher.
    object.__setattr__(config, "approval_records_enabled", False)


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


class _SeededRefinementLLM:
    """Air-gapped stand-in for ``IssueRefinementLoop``'s one-shot judgment client.

    The refinement loop makes two kinds of structured LLM call per tick — a
    duplicate judgment (``build_dup_judgment_prompt``) and a priority score
    (``build_priority_prompt``) — and BOTH shell out to a real ``claude`` via
    ``run_lightweight_agent`` in production (the #9796 real-claude-wedge class
    that wedged discover/shape on the air-gapped sandbox). This stand-in answers
    both from scenario data so nothing escapes the air-gapped network:

    * Dup-judgment prompts — identified by the fixed ``Canonical-selection
      rubric`` header the loop's prompt template always emits (never issue
      content, so a crafted body can't spoof the dispatch) — return the next
      scripted verdict from ``seed.issue_refinement_verdicts``, consumed FIFO
      and reusing the last once exhausted.
    * Priority prompts get a benign ``{"priority": "none"}`` — a deliberate
      no-op: the loop skips a ``none`` verdict on an unlabelled issue, so the
      scenario's only observable action is the dup proposal, not a relabel.

    Structurally satisfies the loop's private ``_RefinementLLM`` protocol (a
    single ``async complete(prompt) -> str``); ``_refinement_complete`` uses it
    verbatim once ``sandbox_main`` injects it onto ``svc.issue_refinement_loop``.
    """

    # Unique to the dup-judgment rubric (issue_refinement._DUP_JUDGMENT_RUBRIC);
    # absent from the priority rubric and from any issue title/body.
    _DUP_MARKER = "Canonical-selection rubric"
    _PRIORITY_NOOP = '{"priority": "none", "reason": "sandbox no-op"}'

    def __init__(self, verdicts: list[str]) -> None:
        self._verdicts = list(verdicts)
        self._next = 0

    async def complete(self, prompt: str) -> str:
        if self._DUP_MARKER not in prompt:
            # A priority-scoring prompt — answer with the deliberate no-op.
            return self._PRIORITY_NOOP
        if not self._verdicts:
            # Defensive: no dup verdict scripted (a scenario always provides at
            # least one). Degrade to the no-op rather than IndexError; the loop
            # treats an unparseable dup verdict as a low-confidence proposal.
            return self._PRIORITY_NOOP
        idx = min(self._next, len(self._verdicts) - 1)
        self._next += 1
        return self._verdicts[idx]


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


def seed_stale_workspaces(
    state: Any, config: HydraFlowConfig, seed: MockWorldSeed
) -> None:
    """Register seeded stale worktrees in StateTracker (#9543).

    WorkspaceGCLoop's phase-1 sweep reads ``state.get_active_workspaces()``;
    seeding an entry here (path derived from config, mirroring the production
    WorkspaceManager layout) gives a GC cycle a tracked worktree to judge.
    Empty ``stale_workspaces`` (every other scenario) touches nothing.
    """
    for entry in seed.stale_workspaces:
        number = int(entry["number"])
        branch = str(entry.get("branch") or f"agent/issue-{number}")
        path = config.workspace_base / config.repo_slug / f"issue-{number}"
        state.set_workspace(number, str(path))
        state.set_branch(number, branch)


def materialize_expired_runs(config: HydraFlowConfig, seed: MockWorldSeed) -> None:
    """Create back-dated run-artifact dirs for RunsGCLoop to purge (#9543).

    RunRecorder derives a run's age from its ``%Y%m%dT%H%M%SZ`` directory
    name, so materializing ``<runs>/<issue>/<old-timestamp>/`` at boot is all
    an expired artifact takes. Empty ``expired_run_dirs`` creates nothing.
    """

    runs_dir = config.repo_data_path("runs")
    for entry in seed.expired_run_dirs:
        issue = int(entry["issue"])
        age_days = int(entry.get("age_days", 90))
        stamp = (datetime.now(UTC) - timedelta(days=age_days)).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        run_dir = runs_dir / str(issue) / stamp
        run_dir.mkdir(parents=True, exist_ok=True)
        # A marker file so the purged directory is a realistic non-empty run.
        (run_dir / "transcript.log").write_text("seeded expired run (#9543)\n")


def materialize_epic_states(state: Any, seed: MockWorldSeed) -> None:
    """Upsert seeded EpicState records into StateTracker (#9643).

    EpicMonitorLoop's stale sweep reads ``state.get_all_epic_states()``; the
    seed-only ``last_activity_age_days`` key is popped and converted to a
    tz-AWARE ``last_activity`` back-dated from boot, so seeds stay
    time-independent (mirroring ``expired_run_dirs.age_days``) and can never
    hit the naive-timestamp footgun (``EpicManager._is_stale`` swallows the
    naive/aware ``TypeError`` and reads the epic as fresh). Empty
    ``epic_states`` (every other scenario) touches nothing.
    """
    for entry in seed.epic_states:
        payload = dict(entry)
        age_days = payload.pop("last_activity_age_days", None)
        if age_days is not None:
            payload["last_activity"] = (
                datetime.now(UTC) - timedelta(days=float(age_days))
            ).isoformat()
        state.upsert_epic_state(EpicState.model_validate(payload))


# The fixed ``health_metrics`` artifact allowlist. Paths mirror
# ``HealthMonitorLoop._outcomes_path`` / ``_scores_path`` / ``_failures_path``
# exactly — a wrong root yields a silently-idle loop reading zero metrics.
_HEALTH_METRIC_KEYS: frozenset[str] = frozenset(
    {"outcomes", "item_scores", "harness_failures"}
)


def materialize_health_metrics(config: HydraFlowConfig, seed: MockWorldSeed) -> None:
    """Write seeded health trend artifacts to the paths the loop reads (#9643).

    ``outcomes.jsonl`` + ``item_scores.json`` are FLAT under
    ``config.memory_dir``; ``harness_failures.jsonl`` is repo-scoped under
    ``config.repo_memory_dir``. Unknown keys raise ``ValueError`` (fail-closed
    — a typo'd artifact name must not silently seed nothing). Empty
    ``health_metrics`` (every other scenario) creates no files.
    """
    metrics = seed.health_metrics
    if not metrics:
        return
    unknown = set(metrics) - _HEALTH_METRIC_KEYS
    if unknown:
        msg = (
            f"Unknown health_metrics keys: {sorted(unknown)}; "
            f"valid: {sorted(_HEALTH_METRIC_KEYS)}"
        )
        raise ValueError(msg)
    for rec in metrics.get("outcomes") or []:
        append_jsonl(config.memory_dir / "outcomes.jsonl", json.dumps(rec))
    item_scores = metrics.get("item_scores") or {}
    if item_scores:
        atomic_write(
            config.memory_dir / "item_scores.json", json.dumps(item_scores, indent=2)
        )
    for rec in metrics.get("harness_failures") or []:
        append_jsonl(config.repo_memory_dir / "harness_failures.jsonl", json.dumps(rec))


def materialize_worker_heartbeats(state: Any, seed: MockWorldSeed) -> None:
    """Persist seeded worker heartbeats into StateTracker (#9643/#9904).

    HealthMonitorLoop's dead-man-switch reads (``_check_worker_staleness`` /
    ``_check_sanity_loop_staleness``) consume ``state.get_worker_heartbeats()``;
    the relative ``age_seconds`` back-dates ``last_run`` from boot (tz-aware),
    so a seeded stall stays a stall regardless of clock. Empty
    ``worker_heartbeats`` (every other scenario) touches nothing.
    """
    for name, entry in seed.worker_heartbeats.items():
        age_seconds = float(entry.get("age_seconds", 0))
        last_run = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
        state.set_worker_heartbeat(
            name,
            {
                "status": str(entry.get("status", "running")),
                "last_run": last_run,
                "details": dict(entry.get("details") or {}),
            },
        )


def materialize_worker_status_history(
    config: HydraFlowConfig, seed: MockWorldSeed
) -> None:
    """Append seeded BACKGROUND_WORKER_STATUS rows to the on-disk event log (#10133).

    ``TrustFleetSanityLoop._collect_window_metrics`` computes its 24h
    ticks/repair/error window via ``EventBus.load_events_since`` — a DISK
    read (``EventLog.load``), not the in-memory ``EventBus._history`` list
    ``/api/events`` falls back to. Each row is appended in the exact
    ``HydraFlowEvent.model_dump_json()`` format ``EventLog.append`` writes
    (mirrors that method's own ``append_jsonl`` call, minus its lock file —
    nothing else writes to the log this early in boot). Each entry's relative
    ``age_seconds`` (mirrors ``worker_heartbeats``) back-dates the row's
    ``timestamp`` from boot, so the seed never rots. Writing the rows alone
    is not sufficient — the caller must ALSO attach a real
    ``EventLog(config.event_log_path)`` to the shared event bus (see
    ``main()`` / ``MockWorld._wire_seed_loop_seams``), since the loop's read
    goes through the bus, not this file directly. Empty
    ``worker_status_history`` (every other scenario) writes nothing.
    """
    now = datetime.now(UTC)
    for worker, entries in seed.worker_status_history.items():
        for entry in entries:
            age_seconds = float(entry.get("age_seconds", 0))
            ts = (now - timedelta(seconds=age_seconds)).isoformat()
            event = HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                timestamp=ts,
                data=BackgroundWorkerStatusPayload(
                    worker=worker,
                    status=str(entry.get("status", "ok")),
                    last_run=ts,
                    details=dict(entry.get("details") or {}),
                ),
            )
            append_jsonl(config.event_log_path, event.model_dump_json())


def resolve_self_wiki_root(config: HydraFlowConfig) -> Path:
    """Return the wiki_root a fresh ``RepoWikiStore`` should point at (#10133).

    MIRRORS ``service_registry.build_services``'s ``repo_wiki_store``
    construction EXACTLY (same fallback order): the self-repo's wiki lives
    at ``docs/wiki/`` when it exists (git-tracked alongside the code), else
    the runtime-cache ``config.data_path("repo_wiki")``. Dockerfile.agent
    does NOT ship ``docs/`` into the sandbox image (only ``src``/``tests``/
    ``templates``/``static`` are copied), so the docker tier always takes the
    fallback branch; the in-process ``MockWorld`` harness usually does too
    (its ``config.repo_root`` is a bare ``tmp_path``). A single source of
    truth here keeps ``materialize_wiki_fixtures`` (below) and any port a
    caller builds pointed at the exact same directory the real (read-only)
    ``repo_wiki_store`` reads from.
    """
    wiki_root = config.repo_root / "docs" / "wiki"
    if not wiki_root.exists():
        wiki_root = config.data_path("repo_wiki")
    return wiki_root


def materialize_wiki_fixtures(config: HydraFlowConfig, seed: MockWorldSeed) -> None:
    """Ingest seeded repo-wiki fixture entries via a REAL ``RepoWikiStore`` (#10133).

    ``WikiRotDetectorLoop`` reads wiki content through the same structured
    ``parse_topic_page`` parse ``RepoWikiStore`` uses to write itself (issue
    #9936): a hand-written markdown blob falls back to the legacy whole-file
    regex row and never carries ``source_type``/``source_issue``/
    ``fixed_in_pr``/``code_refs`` as modeled ``WikiEntry`` fields. Routing
    each fixture through ``RepoWikiStore.ingest`` — the same call the real
    ingest pipeline makes — is what GUARANTEES that structured shape rather
    than merely approximating it.

    A throwaway WRITABLE store is built here (the composition root's own
    ``repo_wiki_store`` is ``read_only=True`` — its roots live under the
    operator's main checkout, see ``service_registry.build_services``) —
    pointed at :func:`resolve_self_wiki_root` so it lands exactly where the
    loop's own store later reads from. See ``MockWorldSeed.repo_wiki_
    fixtures`` for the per-entry field shape and why each fixture names its
    own ``repo_slug`` rather than always targeting the (empty-in-sandbox)
    self-repo slug. Empty ``repo_wiki_fixtures`` (every other scenario)
    creates nothing.
    """
    if not seed.repo_wiki_fixtures:
        return
    store = RepoWikiStore(
        wiki_root=resolve_self_wiki_root(config),
        tracked_root=config.repo_root / config.repo_wiki_path,
        self_slug=config.repo,
        read_only=False,
    )
    by_repo: dict[str, list[WikiEntry]] = {}
    for fixture in seed.repo_wiki_fixtures:
        repo_slug = str(fixture["repo_slug"])
        source_issue = fixture.get("source_issue")
        entry = WikiEntry(
            title=str(fixture["title"]),
            content=str(fixture.get("content", "")),
            source_type=str(fixture.get("source_type", "manual")),
            source_issue=int(source_issue) if source_issue is not None else None,
            fixed_in_pr=fixture.get("fixed_in_pr"),
            code_refs=tuple(fixture.get("code_refs") or ()),
        )
        by_repo.setdefault(repo_slug, []).append(entry)
    for repo_slug, entries in by_repo.items():
        store.ingest(repo_slug, entries)


@dataclass
class SeededRegisteredLoop:
    """Duck-typed ``BaseBackgroundLoop`` stand-in for a seeded registered worker.

    ``BGWorkerManager.get_interval`` / ``cycle_timeout`` / ``run_started_at``
    read through ``loop._get_default_interval()`` / ``loop._cycle_timeout_
    seconds()`` / ``loop._run_started_at`` on whatever object is registered
    under a name in its ``_bg_loop_registry`` dict. Production populates that
    dict from the orchestrator's REAL loop instances (a chicken-and-egg with
    ``BGWorkerManager`` itself — see ``orchestrator.py``); a seeded scenario
    doesn't need a fully-wired ``BaseBackgroundLoop`` (LoopDeps, ports, ...),
    only these three duck-typed members traversed by
    ``HealthMonitorLoop._check_worker_staleness`` (#10086). Mirrors the
    ``stalled_loop = MagicMock()`` shape used by
    ``tests/scenarios/test_loop_stall_restart_scenario.py``, but as a plain
    class (no ``unittest.mock`` import in production composition-root code).
    """

    _interval_seconds: int
    _timeout_seconds: int
    _run_started_at: datetime | None = None

    def _get_default_interval(self) -> int:
        return self._interval_seconds

    def _cycle_timeout_seconds(self) -> int:
        return self._timeout_seconds


def materialize_registered_workers(
    state: Any, config: HydraFlowConfig, seed: MockWorldSeed
) -> BGWorkerManager | None:
    """Build a ``BGWorkerManager`` whose registered-loop set matches the seed (#10086).

    ``HealthMonitorLoop._check_worker_staleness`` filters every heartbeat
    through ``bg_workers.registered_loop_names()`` (backed by
    ``BGWorkerManager``'s ``_bg_loop_registry`` dict) — a heartbeat for a name
    absent from that set never reaches the restart/escalate logic at all, so
    seeding ``worker_heartbeats`` (#9643/#9904) alone can only exercise the
    dead-man-switch's *read* path, never a genuine stall escalation. Each
    seed entry optionally carries ``interval_seconds`` / ``cycle_timeout_
    seconds`` (both default 60) consumed by a lightweight
    ``SeededRegisteredLoop`` stand-in — no real loop boot required. Returns
    ``None`` (no-op) when ``registered_workers`` is empty; the caller must
    then leave ``HealthMonitorLoop._bg_workers`` unset, exactly as before
    #10086 — every existing scenario is unaffected.
    """
    if not seed.registered_workers:
        return None
    registry: dict[str, Any] = {
        name: SeededRegisteredLoop(
            _interval_seconds=int(entry.get("interval_seconds", 60)),
            _timeout_seconds=int(entry.get("cycle_timeout_seconds", 60)),
        )
        for name, entry in seed.registered_workers.items()
    }
    return BGWorkerManager(config, state, registry)


@dataclass(frozen=True)
class SeededActivationProposal:
    """Duck-typed stand-in for ``scripts.gates.activation.ActivationProposal``.

    GateActivatorLoop touches only these attributes (``_proposal_key`` /
    ``_issue_body``); its own ``ActivationProposal`` import is
    TYPE_CHECKING-only. A local mirror keeps the composition root off the
    ``scripts`` package, which Dockerfile.agent does NOT ship into the
    sandbox image (only ``src``/``tests``/``templates``/``static`` are
    copied) — a real import would crash the entrypoint at boot.
    """

    name: str
    dimension: str
    required_on: tuple[str, ...]
    workflow: str
    job: str
    make_target: str


def build_seeded_gate_detector(
    gate_activations: list[dict[str, Any]],
) -> Callable[[], Any]:
    """Detector stand-in returning seed-scripted activation proposals (#9543).

    The production detector reads the repo's real gates.toml / workflows /
    Makefile — all steady-state (no planned gates) in the baked sandbox image,
    so the file-a-proposal path could never fire. Swapping the loop's existing
    ``detector=`` injection point for this closure at the composition root is
    the same DI pattern as the ``_mockworld_fake_llm`` sentinel wiring.
    """
    proposals = [
        SeededActivationProposal(
            name=str(entry["name"]),
            dimension=str(entry.get("dimension", "tests")),
            required_on=tuple(entry.get("required_on", ("main",))),
            workflow=str(entry.get("workflow", "test.yml")),
            job=str(entry.get("job", "tests")),
            make_target=str(entry.get("make_target", "")),
        )
        for entry in gate_activations
    ]

    async def _detect() -> list[SeededActivationProposal]:
        return list(proposals)

    return _detect


# Fixed canonical baseline served to the seeded auditor. Deliberately NOT the
# repo's real contract: Dockerfile.agent ships no ``docs/`` into the sandbox
# image, and a copy of the live contract in a seed would rot as gates.toml
# evolves. The seam tests audit MECHANICS (normalize/diff/missing-ruleset
# detection + issue filing) through the real ``audit_repo``; a scenario seeds
# live rulesets against this stable baseline to produce drift (or cleanness).
_CANONICAL_BASELINE: dict[str, dict[str, Any]] = {
    "main protect": {
        "name": "main protect",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
    },
    "staging protect": {
        "name": "staging protect",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/staging"], "exclude": []}},
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
    },
}


def materialize_canonical_rulesets(config: HydraFlowConfig) -> Path:
    """Write the fixed canonical ruleset baseline to disk; return its dir.

    ``branch_protection_audit.load_canonical`` reads
    ``main_ruleset.json``/``staging_ruleset.json`` from a directory; both
    loaders materialize this one under the writable data root so the REAL
    audit code runs unmodified with no dependency on repo ``docs/`` (absent
    from the sandbox image). Idempotent.
    """
    canonical_dir = config.repo_data_path("sandbox_canonical_rulesets")
    canonical_dir.mkdir(parents=True, exist_ok=True)
    (canonical_dir / "main_ruleset.json").write_text(
        json.dumps(_CANONICAL_BASELINE["main protect"], indent=2)
    )
    (canonical_dir / "staging_ruleset.json").write_text(
        json.dumps(_CANONICAL_BASELINE["staging protect"], indent=2)
    )
    return canonical_dir


def build_seeded_branch_protection_auditor(
    config: HydraFlowConfig,
    github: FakeGitHub,
    canonical_dir: Path | None = None,
) -> Callable[[], Any]:
    """Auditor stand-in serving live rulesets from FakeGitHub (#9543/#9644).

    Runs the REAL ``audit_repo`` diff — only its two inputs are swapped: the
    live-ruleset fetch moves from the raw-``gh`` ``gh_fetch_rulesets``
    (unreachable on the air-gapped network) to ``FakeGitHub.fetch_rulesets``
    serving ``seed.rulesets``, and ``canonical_dir`` defaults to the
    materialized fixed baseline (see ``materialize_canonical_rulesets``).
    """
    if canonical_dir is None:
        canonical_dir = materialize_canonical_rulesets(config)

    async def _audit() -> AuditReport:
        return await asyncio.to_thread(
            audit_repo,
            config.repo,
            canonical_dir,
            fetch_rulesets=github.fetch_rulesets,
        )

    return _audit


async def main() -> None:
    config = load_runtime_config()
    # Disable production code paths that reach services unreachable on the
    # air-gapped sandbox network (see the helper for the per-flag rationale).
    _apply_sandbox_config_overrides(config)
    seed = _load_seed()
    # A real EventLog is only attached when a scenario seeds worker-status
    # history (#10133) — every other scenario keeps the historical no-log
    # ``EventBus()`` so ``/api/events`` continues falling back to in-memory
    # history exactly as before. TrustFleetSanityLoop's window read
    # (``EventBus.load_events_since``) needs the disk-backed log to see
    # anything materialize_worker_status_history writes below.
    event_bus = EventBus(
        event_log=EventLog(config.event_log_path)
        if seed.worker_status_history
        else None
    )
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

    # Stale-worktree + expired-run seeding (#9543). Both act on state/disk
    # before the loops boot; empty seed fields are no-ops.
    seed_stale_workspaces(state, config, seed)
    materialize_expired_runs(config, seed)

    # EpicState / health-metrics / heartbeat seeding (#9643). All act on
    # state/disk before build_services wires the REAL EpicManager and
    # HealthMonitorLoop over them; empty seed fields are no-ops.
    materialize_epic_states(state, seed)
    materialize_health_metrics(config, seed)
    materialize_worker_heartbeats(state, seed)
    # Worker-status event HISTORY (#10133) — pairs with the event_bus/EventLog
    # wiring above; empty seed field writes nothing.
    materialize_worker_status_history(config, seed)
    # Repo-wiki fixture entries (#10133 PIECE 2) — ingested into the SAME
    # wiki_root the real (read-only) ``repo_wiki_store`` below reads from;
    # empty seed field writes nothing.
    materialize_wiki_fixtures(config, seed)

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
        # No sandbox scenario relies on watchdog firing early — real config
        # defaults keep the per-cycle bound generous (#9503).
        get_watchdog_timeout=lambda *_a, **_kw: config.loop_watchdog_default_seconds,
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

    # Registered-worker SET for the dead-man-switch stall/escalate sweep
    # (#10086). ``HealthMonitorLoop._check_worker_staleness`` only sweeps
    # names present in a wired BGWorkerManager's ``registered_loop_names()``
    # — without this, a seeded ``worker_heartbeats`` stale entry (#9643/#9904)
    # can never reach the restart/escalate path. None when
    # seed.registered_workers is empty — HealthMonitorLoop._bg_workers stays
    # unset, unchanged from pre-#10086 behavior.
    bg_workers = materialize_registered_workers(state, config, seed)
    if bg_workers is not None:
        svc.health_monitor_loop.set_bg_workers(bg_workers)

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

    # IssueRefinementLoop (#9957) air-gap seam. The loop reads the whole open
    # backlog via PRPort (Faked) and then spends one structured LLM call per dup
    # candidate / priority target — the judgment call shells out to a real
    # ``claude`` via run_lightweight_agent in production (the #9796
    # real-claude-wedge class). When a scenario (s57) seeds a backlog, populate
    # the shared FakeGitHub with it as open issues (label-free, so the pipeline's
    # ``hydraflow-*``-only store refresh never picks them up — only the
    # backlog-wide refinement sweep sees them) and inject a scripted refinement
    # LLM so judgment/priority never reach a real ``claude``. The scripted dup
    # verdict is a likely_dup/medium PROPOSE (not an auto-close), so the tick
    # renders an operator digest without any GitHub close write. Empty seed
    # (every other scenario, incl. s16/s56) leaves production ``_refinement_llm``
    # untouched.
    if seed.issue_refinement_backlog:
        for entry in seed.issue_refinement_backlog:
            number = int(entry["number"])
            shared_github.add_issue(
                number=number,
                title=str(entry.get("title", "")),
                body=str(entry.get("body", "")),
                labels=list(entry.get("labels", []) or []),
            )
            updated_at = entry.get("updated_at")
            if updated_at:
                shared_github.set_issue_updated_at(number, str(updated_at))
        # Instance-level data attribute (not a method) — a plain assignment is
        # the sanctioned seam here, mirroring ``_refine_loop._refine_llm`` above.
        svc.issue_refinement_loop._refinement_llm = _SeededRefinementLLM(
            list(seed.issue_refinement_verdicts)
        )

    # GateActivatorLoop (#9543) air-gap seam: when the scenario scripts
    # activation proposals, swap the loop's existing ``detector=`` injection
    # point for a closure returning them — the same composition-root DI as the
    # ``_mockworld_fake_llm`` sentinel wiring. ``create_issue`` already routes
    # through FakeGitHub. Empty seed: production detector untouched.
    if seed.gate_activations:
        svc.gate_activator_loop._detector = build_seeded_gate_detector(
            seed.gate_activations
        )

    # BranchProtectionAuditorLoop (#9543/#9644) air-gap seam: when the
    # scenario seeds live rulesets, rebind the auditor so the REAL
    # ``audit_repo`` diff runs against ``FakeGitHub.fetch_rulesets`` instead
    # of the raw-``gh`` ``gh_fetch_rulesets`` (which errors every cycle on the
    # air-gapped network, reducing s41's heartbeat to an ``{'error': True}``
    # tick). Empty seed: production auditor untouched.
    if seed.rulesets:
        svc.branch_protection_auditor_loop._auditor = (
            build_seeded_branch_protection_auditor(config, shared_github)
        )

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
