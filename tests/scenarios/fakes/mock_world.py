"""MockWorld — composable test world for scenario testing.

Wraps PipelineHarness with stateful fakes so scenarios can seed a world,
run the pipeline, and assert on the world's final state.
"""

from __future__ import annotations

import asyncio
import contextlib
import faulthandler
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from events import EventBus, EventLog
from mockworld.fakes.fake_clock import FakeClock

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_fs import FakeFS
from mockworld.fakes.fake_git import FakeGit
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_http import FakeHTTP
from mockworld.fakes.fake_llm import FakeLLM
from mockworld.fakes.fake_observability import FakeObservability
from mockworld.fakes.fake_workspace import FakeWorkspace
from tests.conftest import TaskFactory
from tests.helpers import PipelineHarness, PipelineRunResult
from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog import (
    loop_registrations as _loop_registrations,  # noqa: F401
)
from tests.scenarios.fakes.scenario_result import IssueOutcome, ScenarioResult

#: Upper bound for ``orchestrator.stop()`` during teardown (#10073). Generous —
#: a healthy stop path finishes in well under a second; the bound exists only to
#: convert a wedged shutdown into a loud, attributed failure instead of a silent
#: 20-minute CI cancel at event-loop close.
_ORCHESTRATOR_STOP_TIMEOUT = 60.0


class _SafeProxy:
    """Recursive no-op proxy: any attribute access and any call returns another proxy.

    Used as a fallback for orchestrator attributes that the dashboard UI polls
    but the test shim doesn't implement (e.g. run_recorder, metrics_manager,
    _svc.epic_manager).  Every method call returns an empty list/dict/None at
    the leaf, so JSON serialisation and truth-value tests work safely.
    """

    def __getattr__(self, name: str) -> _SafeProxy:
        return _SafeProxy()

    def __call__(self, *args: Any, **kwargs: Any) -> _SafeProxy:
        return _SafeProxy()

    # Support async calls
    def __await__(self):  # type: ignore[override]
        yield
        return _SafeProxy()

    # Support iteration (e.g. list comprehensions over route results)
    def __iter__(self):  # type: ignore[override]
        return iter([])

    def __bool__(self) -> bool:
        return False

    def model_dump(self) -> dict:
        return {}

    def list_issues(self) -> list:
        return []

    def list_runs(self, *a: Any, **kw: Any) -> list:
        return []

    def get_storage_stats(self) -> dict:
        return {}

    def get_run_artifact(self, *a: Any, **kw: Any) -> None:
        return None


class _StubMetricsManager:
    """Stub MetricsManager that returns empty data for dashboard polling."""

    async def fetch_history_from_issue(self) -> list:
        return []

    @property
    def latest_snapshot(self) -> None:
        return None


class _StubRunRecorder:
    """Stub RunRecorder that returns empty data for dashboard polling."""

    def list_issues(self) -> list:
        return []

    def list_runs(self, issue_number: int) -> list:
        return []

    def get_run_artifact(
        self, issue_number: int, timestamp: str, filename: str
    ) -> None:
        return None

    def get_storage_stats(self) -> dict:
        return {"total_size_bytes": 0, "run_count": 0}


class _HarnessOrchestratorShim:
    """Minimal orchestrator-like object that exposes a PipelineHarness's store.

    Dashboard routes check ``orchestrator.running`` / ``orchestrator.pipeline_enabled``
    to decide whether to serve live data.  This shim answers ``True`` for both so
    the routes don't short-circuit to empty responses, and forwards
    ``issue_store`` / ``build_pipeline_stats`` to the underlying harness store.

    The UI polls many endpoints (metrics, workers, HITL, run_recorder, etc.).
    A ``__getattr__`` fallback returns empty-safe sentinel objects so all routes
    return 200 with empty payloads instead of 500 errors.  No ``github_cache``
    attribute is exposed intentionally — routes that require it perform an
    ``isinstance`` guard before accessing it.
    """

    def __init__(self, harness: Any) -> None:
        self._harness = harness

    # --- Core properties checked by route guards ---

    @property
    def running(self) -> bool:
        return True

    @property
    def pipeline_enabled(self) -> bool:
        return True

    @pipeline_enabled.setter
    def pipeline_enabled(self, value: bool) -> None:
        pass  # no-op in test mode

    # --- Pipeline data ---

    @property
    def issue_store(self) -> Any:
        return self._harness.store

    def build_pipeline_stats(self) -> Any:
        from datetime import UTC, datetime  # noqa: PLC0415

        from models import PipelineStats  # noqa: PLC0415

        queue_stats = self._harness.store.get_queue_stats()
        return PipelineStats(
            timestamp=datetime.now(UTC).isoformat(),
            queue=queue_stats,
        )

    # --- Attributes polled by the dashboard UI ---

    @property
    def current_session_id(self) -> str | None:
        return None

    @property
    def run_status(self) -> str:
        return "idle"

    @property
    def human_input_requests(self) -> dict:
        return {}

    @property
    def credits_paused_until(self) -> None:
        return None

    def get_bg_worker_states(self) -> dict:
        return {}

    def is_bg_worker_enabled(self, name: str) -> bool:
        return False

    def get_bg_worker_interval(self, name: str) -> int:
        return 60

    def get_hitl_status(self, issue_number: int) -> str:
        return "idle"

    @property
    def metrics_manager(self) -> Any:
        """Stub metrics manager — returns empty snapshots for dashboard polling."""
        return _StubMetricsManager()

    @property
    def run_recorder(self) -> Any:
        """Stub run recorder — returns empty lists for dashboard polling."""
        return _StubRunRecorder()

    def __getattr__(self, name: str) -> Any:
        """Return a safe proxy for any unrecognised attribute.

        This prevents ``AttributeError`` 500s from dashboard routes that poll
        optional orchestrator APIs (run_recorder, metrics_manager, _svc, etc.).
        The returned proxy accepts any attribute access or call chain.
        """
        return _SafeProxy()

    async def stop(self) -> None:
        """No-op stop — shim has no background tasks to cancel."""


class MockWorld:
    """Composable test world for scenario testing."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        config: Any = None,
        install_subprocess_clock: bool = False,
        use_real_agent_runner: bool = False,
        clock_start: float | str | None = None,
        wiki_store: Any = None,
        wiki_compiler: Any = None,
        beads_manager: Any = None,
    ) -> None:
        self._tmp_path = tmp_path
        self._use_real_agent = use_real_agent_runner
        self._wiki_store = wiki_store
        self._wiki_compiler = wiki_compiler
        self._beads_manager = beads_manager
        self._harness = PipelineHarness(
            tmp_path,
            config=config,
            wiki_store=wiki_store,
            wiki_compiler=wiki_compiler,
            beads_manager=beads_manager,
        )
        self._llm = FakeLLM()
        self._github = FakeGitHub()
        self._sentry = FakeObservability()
        self._workspace = FakeWorkspace(tmp_path / "worktrees")
        self._clock = FakeClock(start=time.time())
        if clock_start is not None:
            self._clock.freeze(clock_start)
        self._docker = FakeDocker(beads=beads_manager)
        self._git = FakeGit()
        self._fs = FakeFS()
        self._http = FakeHTTP()
        self._issues: dict[int, dict[str, Any]] = {}
        self._phase_hooks: list[tuple[str, Callable[[], None]]] = []
        self._ran = False
        # Last seed given to apply_seed — run_with_loops wires the seed-seam
        # loop overrides (stale worktrees, gate proposals, rulesets, expired
        # runs) from it, mirroring sandbox_main's composition root (#9543).
        self._applied_seed: MockWorldSeed | None = None
        self._dashboard: Any = None
        self._dashboard_url: str | None = None

        from repo_runtime import RepoRuntimeRegistry  # noqa: PLC0415

        self._registry: RepoRuntimeRegistry = RepoRuntimeRegistry()

        self._wire_targets(self._harness)

        if self._use_real_agent:
            from tests.scenarios.helpers.agent_runner_factory import (  # noqa: PLC0415
                build_real_agent_runner,
            )

            self._harness.set_agents(
                build_real_agent_runner(
                    docker=self._docker,
                    event_bus=self._harness.bus,
                    tmp_path=self._tmp_path,
                )
            )

        if install_subprocess_clock:
            self._clock.install_subprocess_clock()

    def _wire_targets(self, target: Any) -> None:
        """Patch runner/PR/workspace attributes on ``target`` to this world's fakes.

        ``target`` must expose ``.prs``, ``.triage_runner``, ``.planners``,
        ``.agents``, ``.reviewers``, and ``.workspaces`` objects whose methods
        are replaceable. Works for both ``PipelineHarness`` and a small
        duck-typed wrapper around the service registry on a real
        ``HydraFlowOrchestrator`` (used in Task 9).
        """
        # Runners
        target.triage_runner.evaluate = self._llm.triage_runner.evaluate
        target.triage_runner.run_decomposition = (
            self._llm.triage_runner.run_decomposition
        )
        target.planners.plan = self._llm.planners.plan
        target.planners.run_gap_review = self._llm.planners.run_gap_review
        target.agents.run = self._llm.agents.run
        target.reviewers.review = self._llm.reviewers.review
        target.reviewers.fix_ci = self._llm.reviewers.fix_ci
        target.reviewers.fix_review_findings = self._llm.reviewers.fix_review_findings
        # Sentinel for ReviewPhase._build_post_verify_runner to route advisor
        # calls into FakeLLM instead of the production ReviewRunner._execute
        # (which would hit a real Claude subprocess).
        target.reviewers._mockworld_fake_llm = self._llm

        # PRs
        prs = target.prs
        gh = self._github
        for method in (
            "transition",
            "swap_pipeline_labels",
            "add_labels",
            "remove_label",
            "post_comment",
            "post_pr_comment",
            "submit_review",
            "create_task",
            "close_task",
            "close_issue",
            "update_issue_body",
            "find_existing_issue",
            "push_branch",
            "create_pr",
            "find_open_pr_for_branch",
            "branch_has_diff_from_main",
            "add_pr_labels",
            "get_pr_diff",
            "get_pr_head_sha",
            "get_pr_diff_names",
            # close_verification (default ON) reads commit messages on every
            # merge; delegate to FakeGitHub so the reconciler sees a real string
            # instead of an unwired AsyncMock.
            "get_pr_commit_messages",
            "get_pr_approvers",
            "fetch_code_scanning_alerts",
            "wait_for_ci",
            "fetch_ci_failure_logs",
            "merge_pr",
        ):
            setattr(prs, method, getattr(gh, method))

        # Workspaces
        target.workspaces.create = self._workspace.create
        target.workspaces.destroy = self._workspace.destroy

    def _wire_runners(self) -> None:
        """Backward-compatible wrapper — delegates to _wire_targets."""
        self._wire_targets(self._harness)

    def _wire_prs(self) -> None:
        """Backward-compatible wrapper — delegates to _wire_targets."""
        self._wire_targets(self._harness)

    def _wire_workspaces(self) -> None:
        """Backward-compatible wrapper — delegates to _wire_targets."""
        self._wire_targets(self._harness)

    # --- Seed API (fluent, returns self) ---

    def add_issue(
        self,
        number: int,
        title: str,
        body: str,
        labels: list[str] | None = None,
        state: str = "open",
        updated_at: str | None = None,
    ) -> MockWorld:
        self._issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "labels": labels or ["hydraflow-find"],
        }
        self._github.add_issue(
            number, title, body, labels=labels, state=state, updated_at=updated_at
        )
        return self

    def add_repo(
        self,
        slug: str,
        path: str,
        *,
        with_pipeline: bool = False,
        repo_provider: Literal["claude", "zai"] = "claude",
        repo_model: str = "",
    ) -> MockWorld:
        """Seed a RepoRegistryStore entry AND a live runtime in the registry.

        Scenarios that exercise multi-repo controls (register / remove) start
        with this rather than driving the UI's 'Add repo' button. The runtime
        is a duck-typed namespace (the proven test pattern) with its own
        EventBus tagged via set_repo, so >=2 calls yield genuinely independent
        runtimes that resolve_runtimes can aggregate.

        When ``with_pipeline`` is True the runtime also gets a pipeline-surfacing
        orchestrator (the host ``_HarnessOrchestratorShim`` over a fresh per-repo
        ``IssueStore``) and ``running=True``, so ``/api/pipeline`` (and the other
        active-gated routes) serve this repo's seeded issues — used by the
        aggregate browser e2e to render two repos' pipeline cards. Seed via
        ``registry.get(slug).orchestrator.issue_store.mark_active(n, stage)``.
        Default ``False`` keeps the legacy orchestrator-less runtime so existing
        callers are unaffected.

        ``repo_provider``/``repo_model`` (#11211) seed this repo's per-repo
        harness/backend dial — lets a multi-repo scenario put two repos on
        different backends and assert both configs resolve independently.
        Defaults keep every existing caller on native Claude.
        """
        from types import SimpleNamespace  # noqa: PLC0415

        from events import EventBus  # noqa: PLC0415
        from repo_store import RepoRecord, RepoRegistryStore  # noqa: PLC0415
        from state import StateTracker  # noqa: PLC0415
        from tests.helpers import ConfigFactory  # noqa: PLC0415

        store = RepoRegistryStore(self._tmp_path)
        store.upsert(RepoRecord(slug=slug, repo=slug, path=path))

        dash = slug.replace("/", "-")
        # The seed `path` may be a container path (e.g. /workspace/...) that is
        # not writable in-process; give the runtime a tmp-based repo_root so
        # building it never touches the seed's filesystem location.
        repo_root = self._tmp_path / "repo_runtimes" / dash
        repo_root.mkdir(parents=True, exist_ok=True)
        cfg = ConfigFactory.create(
            repo=slug,
            repo_root=repo_root,
            repo_provider=repo_provider,
            repo_model=repo_model,
        )
        bus = EventBus()
        bus.set_repo(dash)
        st = StateTracker(repo_root / "state.json")

        orchestrator: Any = None
        running = False
        if with_pipeline:
            from unittest.mock import AsyncMock  # noqa: PLC0415

            from issue_store import IssueStore  # noqa: PLC0415

            issue_store = IssueStore(cfg, AsyncMock(), bus)
            # This harness seeds pipeline state directly (mark_active, etc.)
            # rather than driving a real start()/refresh() boot sequence, so
            # mark it ready immediately — consistent with running=True below
            # and matching production's post-boot steady state (#11279).
            issue_store._has_completed_initial_refresh = True  # noqa: SLF001
            orchestrator = _HarnessOrchestratorShim(SimpleNamespace(store=issue_store))
            running = True

        self._registry._runtimes[dash] = SimpleNamespace(
            slug=dash,
            config=cfg,
            state=st,
            event_bus=bus,
            orchestrator=orchestrator,
            running=running,
            last_error=None,
        )
        return self

    def set_phase_result(self, phase: str, issue: int, result: Any) -> MockWorld:
        return self.set_phase_results(phase, issue, [result])

    def set_phase_results(
        self, phase: str, issue: int, results: list[Any]
    ) -> MockWorld:
        phase_map = {
            "triage": self._llm.script_triage,
            "plan": self._llm.script_plan,
            "implement": self._llm.script_implement,
            "review": self._llm.script_review,
            # "decomposition" isn't a pipeline-phase runner: it queues the raw
            # council transcripts the DecompositionCouncil seam returns (ADR-0105).
            # Included here so a sandbox scenario's seed.scripts["decomposition"]
            # loads in-process too — matching how sandbox_main dispatches
            # seed.scripts generically via getattr(fake_llm, f"script_{phase}").
            "decomposition": self._llm.script_decomposition,
        }
        # fix_ci uses a single-result scripting API (the latest call wins);
        # convert per-call here so scenarios can describe it uniformly.
        if phase == "fix_ci":
            for result in results:
                self._llm.script_fix_ci(issue, result)
            return self
        script_fn = phase_map.get(phase)
        if script_fn is None:
            msg = f"Unknown phase: {phase}; valid: {list(phase_map) + ['fix_ci']}"
            raise ValueError(msg)
        script_fn(issue, results)
        return self

    def apply_seed(self, seed: MockWorldSeed) -> MockWorld:
        """Populate wired Fakes from a serialized MockWorldSeed.

        Convenience wrapper over add_issue / add_pr / set_phase_result for
        test code that wants to consume a sandbox scenario's seed() output
        without rewriting it as a fluent chain. Returns self for chaining.
        """
        self._applied_seed = seed
        for repo_slug, repo_path in seed.repos:
            self.add_repo(repo_slug, repo_path)
        for issue_dict in seed.issues:
            self.add_issue(
                number=issue_dict["number"],
                title=issue_dict["title"],
                body=issue_dict["body"],
                labels=list(issue_dict.get("labels", [])),
                state=issue_dict.get("state", "open"),
                updated_at=issue_dict.get("updated_at"),
            )
        for pr_dict in seed.prs:
            self._github.add_pr(
                number=pr_dict["number"],
                issue_number=pr_dict["issue_number"],
                branch=pr_dict["branch"],
                ci_status=pr_dict.get("ci_status", "pass"),
                merged=pr_dict.get("merged", False),
                mergeable=pr_dict.get("mergeable", True),
            )
            for label in pr_dict.get("labels", []):
                self._github.add_pr_label(pr_dict["number"], label)
        for name, cfg in seed.rulesets.items():
            self._github.add_ruleset(name, cfg)
        for phase, by_issue in seed.scripts.items():
            for issue_number, results in by_issue.items():
                for result in results:
                    self.set_phase_result(phase, issue_number, result)
        return self

    def on_phase(self, phase: str, callback: Callable[[], None]) -> MockWorld:
        self._phase_hooks.append((phase, callback))
        return self

    def fail_service(
        self, name: str, _error: type[Exception] = ConnectionError
    ) -> MockWorld:
        if name == "docker":
            self._docker.fail_next(kind="exit_nonzero")
        elif name == "github":
            self._github.set_rate_limit_mode(remaining=0)
        else:
            msg = f"unknown service: {name}"
            raise ValueError(msg)
        return self

    def heal_service(self, name: str) -> MockWorld:
        if name == "github":
            self._github.clear_rate_limit()
        elif name == "docker":
            self._docker.clear_fault()
        else:
            msg = f"unknown service: {name}"
            raise ValueError(msg)
        return self

    # --- Inspect world state ---

    @property
    def registry(self):
        """The multi-repo runtime registry seeded by add_repo/apply_seed."""
        return self._registry

    @property
    def github(self) -> FakeGitHub:
        return self._github

    @property
    def sentry(self) -> FakeObservability:
        return self._sentry

    @property
    def clock(self) -> FakeClock:
        return self._clock

    @property
    def harness(self) -> PipelineHarness:
        return self._harness

    @property
    def docker(self) -> FakeDocker:
        return self._docker

    @property
    def git(self) -> FakeGit:
        return self._git

    @property
    def fs(self) -> FakeFS:
        return self._fs

    @property
    def http(self) -> FakeHTTP:
        return self._http

    # --- Run ---

    def _fire_hooks(self, phase: str) -> None:
        for hook_phase, callback in self._phase_hooks:
            if hook_phase == phase:
                callback()

    async def run_pipeline(self) -> ScenarioResult:
        """Run all seeded issues through the full pipeline."""
        if self._ran:
            msg = (
                "MockWorld.run_pipeline is single-shot; create a new MockWorld "
                "to run again. Re-use would re-seed issues against stale fake state."
            )
            raise RuntimeError(msg)
        self._ran = True
        h = self._harness
        start = time.monotonic()

        for info in self._issues.values():
            tags = info.get("labels", ["hydraflow-find"])
            task = TaskFactory.create(
                id=info["number"],
                title=info["title"],
                body=info["body"],
                tags=tags,
            )
            h.seed_issue(task, stage="find")

        snapshots: dict[str, Any] = {}

        def _capture(label: str) -> None:
            snapshots[label] = h.store.get_queue_stats().model_copy(deep=True)

        # Triage
        self._fire_hooks("triage")
        triaged = await h.triage_phase.triage_issues()
        _capture("after_triage")

        # Plan
        self._fire_hooks("plan")
        plan_results = await h.plan_phase.plan_issues()
        _capture("after_plan")

        # Implement
        self._fire_hooks("implement")
        worker_results, _ = await h.implement_phase.run_batch()
        _capture("after_implement")

        # Review
        self._fire_hooks("review")
        review_results: list[Any] = []
        if worker_results:
            prs_to_review = [wr.pr_info for wr in worker_results if wr.pr_info]
            if prs_to_review:
                candidates = h.store.get_reviewable(h.config.batch_size)
                review_results = await h.review_phase.review_prs(
                    prs_to_review, candidates
                )
        _capture("after_review")

        await asyncio.sleep(0)
        events = h.bus.get_history()

        # Build per-issue outcomes
        outcomes: dict[int, IssueOutcome] = {}
        for info in self._issues.values():
            num = info["number"]
            pr_record = self._github.pr_for_issue(num)
            merged = pr_record.merged if pr_record else False

            wr = next((w for w in worker_results if w.issue_number == num), None)
            rr = next((r for r in review_results if r.issue_number == num), None)
            pr_result = next((p for p in plan_results if p.issue_number == num), None)

            if rr and getattr(rr, "merged", False):
                final_stage = "done"
            elif rr:
                final_stage = "review"
            elif wr:
                final_stage = "implement"
            elif pr_result:
                final_stage = "plan"
            else:
                final_stage = "triage"

            labels = (
                self._github.issue(num).labels if num in self._github._issues else []
            )
            outcomes[num] = IssueOutcome(
                number=num,
                final_stage=final_stage,
                plan_result=pr_result,
                worker_result=wr,
                review_result=rr,
                labels=labels,
                merged=merged,
            )

        pipeline_result = PipelineRunResult(
            task=TaskFactory.create(id=0),
            triaged_count=triaged,
            plan_results=plan_results,
            worker_results=worker_results,
            review_results=review_results,
            snapshots=snapshots,
            events=events,
        )

        duration = time.monotonic() - start
        result = ScenarioResult(
            pipeline_results=[pipeline_result],
            duration_seconds=duration,
        )
        result._outcomes = outcomes
        return result

    # --- Loop execution ---

    @property
    def _dependabot_cache(self) -> Any:
        """Expose the dependabot cache mock created by loop_registrations."""
        return self._loop_ports.get("dependabot_cache")

    @property
    def _workspace_gc_state(self) -> Any:
        """Expose the workspace GC state mock created by loop_registrations."""
        return self._loop_ports.get("workspace_gc_state")

    async def run_with_loops(
        self,
        loops: list[str],
        *,
        cycles: int = 1,
    ) -> dict[str, dict[str, Any] | None]:
        """Instantiate and run real BaseBackgroundLoop subclasses via LoopCatalog.

        Invokes ``loop._do_work()`` directly, ``cycles`` times per loop, so
        each call returns the ``WorkCycleResult`` stats. This skips
        ``loop.run()`` (no sleep/stop_event lifecycle) AND skips
        ``loop._execute_cycle()`` (no status callback, no event-bus publish).
        Scenarios that need either of those must call ``loop._execute_cycle()``
        directly. FakeGitHub is wired as the PRPort so loops interact with
        seeded world state.

        Returns a dict mapping loop name → last ``_do_work()`` stats.
        """
        from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

        bg = make_bg_loop_deps(self._tmp_path)
        call_count = 0
        stop_event = bg.stop_event

        async def _counting_sleep(_seconds: int | float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= cycles:
                stop_event.set()
            await asyncio.sleep(0)

        from base_background_loop import LoopDeps  # noqa: PLC0415

        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=_counting_sleep,
        )
        config = bg.config
        # The caller explicitly asked to run these loops, so enable any
        # deploy-time kill-switch they gate on (e.g. diagnostic_loop_enabled
        # defaults OFF, #9895). Otherwise _do_work short-circuits to
        # config_disabled and the scenario can't exercise the loop.
        for _name in loops:
            _flag = f"{_name}_loop_enabled"
            if hasattr(config, _flag):
                object.__setattr__(config, _flag, True)

        # Persistent ports dict so catalog-allocated mocks survive across calls
        if not hasattr(self, "_loop_ports"):
            self._loop_ports: dict[str, Any] = {
                "github": self._github,
                "workspace": self._workspace,
                "sentry": self._sentry,
                "clock": self._clock,
                "state": self._harness.state,
            }
            # The ctor's wiki_compiler kwarg only threads through
            # PipelineHarness (Plan-phase wiring, #10306-era) — it never
            # reached _loop_ports, so RepoWikiLoop's catalog builder saw
            # None regardless of what the scenario passed in (#11416).
            if self._wiki_compiler is not None:
                self._loop_ports.setdefault("wiki_compiler", self._wiki_compiler)
        else:
            # Keep fakes up-to-date (cheap; they're the same objects)
            self._loop_ports["github"] = self._github
            self._loop_ports["workspace"] = self._workspace
            self._loop_ports["state"] = self._harness.state

        # Mirror sandbox_main's seed-seam composition wiring (#9543) so the
        # in-process tier exercises the same active-trigger paths the docker
        # tier does (dual-loader parity).
        self._wire_seed_loop_seams(config)

        loop_instances = []
        for name in loops:
            if name == "pipeline_poller":
                # pipeline_poller is the orchestrator-level
                # `_pipeline_stats_loop` (src/orchestrator.py ~965), NOT a
                # BaseBackgroundLoop subclass, so LoopCatalog has no builder
                # for it and instantiate() would raise "Unknown loop" (#9441).
                # Handled as a special case in the execution loop below.
                loop_instances.append((name, None))
                continue
            instance = LoopCatalog.instantiate(
                name, ports=self._loop_ports, config=config, deps=loop_deps
            )
            loop_instances.append((name, instance))

        results: dict[str, dict[str, Any] | None] = {}
        for name, loop in loop_instances:
            if name == "pipeline_poller":
                orchestrator = await self._pipeline_poller_orchestrator()
                stats: dict[str, Any] | None = None
                for _ in range(cycles):
                    await orchestrator.emit_pipeline_stats()
                    stats = orchestrator.build_pipeline_stats().model_dump()
                results[name] = stats
                continue
            for _ in range(cycles):
                stats = await loop._do_work()
                results[name] = stats

        return results

    async def _pipeline_poller_orchestrator(self) -> Any:
        """Lazily build (and cache) a real orchestrator to drive pipeline_poller.

        ``pipeline_poller`` is the orchestrator-level ``_pipeline_stats_loop``
        (src/orchestrator.py ~965), not a ``BaseBackgroundLoop`` subclass, so
        it has no ``_do_work()`` and ``LoopCatalog`` has no builder for it
        (#9441). Rather than faking the emission, reuse the same
        ``_build_wired_orchestrator`` helper the dashboard's
        ``with_orchestrator=True`` path uses to construct a real
        ``HydraFlowOrchestrator`` wired to this world's fakes, so
        ``run_with_loops`` drives the genuine ``emit_pipeline_stats()`` and
        publishes a real ``PIPELINE_STATS`` event on the harness bus — exactly
        what happens in the docker sandbox stack. Cached on the world so
        repeated calls (e.g. multiple scenarios in one test session) reuse the
        same instance instead of re-wiring on every cycle.
        """
        if not hasattr(self, "_pipeline_orchestrator"):
            self._pipeline_orchestrator = await self._build_wired_orchestrator(
                self._harness.config, self._harness.bus, self._harness.state
            )
        return self._pipeline_orchestrator

    def _wire_seed_loop_seams(self, config: Any) -> None:
        """Wire seed-seam loop overrides from the last applied seed (#9543).

        The dual-loader parity contract: any composition-root seam
        ``sandbox_main`` wires from a ``MockWorldSeed`` field must be wired
        here too, so ``test_sandbox_parity`` runs every scenario's active
        path in-process as well. Reuses sandbox_main's public builders — one
        implementation, no drift. Empty seed fields (or no ``apply_seed``
        call at all) leave every port default untouched.
        """
        seed = self._applied_seed
        if seed is None:
            return
        from mockworld.sandbox_main import (  # noqa: PLC0415
            build_seeded_branch_protection_auditor,
            build_seeded_gate_detector,
            materialize_epic_states,
            materialize_expired_runs,
            materialize_health_metrics,
            materialize_registered_workers,
            materialize_wiki_fixtures,
            materialize_worker_heartbeats,
            materialize_worker_status_history,
            resolve_self_wiki_root,
            seed_stale_workspaces,
        )

        if seed.registered_workers:
            # Mirrors sandbox_main's post-``build_services`` wiring: a
            # BGWorkerManager backed by the seeded name set is handed to the
            # catalog's health_monitor builder via the ``bg_workers`` port
            # (``_build_health_monitor`` calls ``loop.set_bg_workers(...)``
            # when the port is present), so
            # ``HealthMonitorLoop._check_worker_staleness`` can traverse a
            # seeded stall exactly as the docker tier does (#10086).
            bg_workers = materialize_registered_workers(
                self._harness.state, config, seed
            )
            if bg_workers is not None:
                self._loop_ports.setdefault("bg_workers", bg_workers)

        if seed.epic_states:
            # Materialize into the REAL harness StateTracker and hand the loop
            # builder a real EpicManager over the shared FakeGitHub (its
            # default is a MagicMock whose check_stale_epics can never flag
            # anything) — same dual-loader parity as sandbox_main, which gets
            # a real EpicManager from build_services over the same state.
            from epic import EpicManager  # noqa: PLC0415
            from mockworld.fakes.fake_issue_fetcher import (  # noqa: PLC0415
                FakeIssueFetcher,
            )

            materialize_epic_states(self._harness.state, seed)
            self._loop_ports.setdefault(
                "epic_manager",
                EpicManager(
                    config,
                    self._harness.state,
                    self._github,
                    FakeIssueFetcher(github=self._github),
                    self._harness.bus,
                ),
            )
        if seed.health_metrics:
            # Written via the run config: its memory_dir/repo_memory_dir are
            # the paths the catalog-built HealthMonitorLoop reads (both derive
            # from the same tmp repo_root as harness.config).
            materialize_health_metrics(config, seed)
        if seed.worker_heartbeats:
            materialize_worker_heartbeats(self._harness.state, seed)
        if seed.worker_status_history:
            # Mirrors sandbox_main's ``main()`` wiring (#10133): the seeded
            # rows only become readable once the loop's ``event_bus`` port
            # has a REAL ``EventLog`` attached (``TrustFleetSanityLoop._
            # collect_window_metrics`` reads via ``EventBus.load_events_
            # since``, a disk read — the harness's default ``event_bus``
            # port, when unseeded, falls back to a bare ``MagicMock`` whose
            # ``load_events_since`` isn't awaitable at all, see
            # ``_build_trust_fleet_sanity``).
            materialize_worker_status_history(config, seed)
            self._loop_ports.setdefault(
                "event_bus", EventBus(event_log=EventLog(config.event_log_path))
            )
        if seed.stale_workspaces:
            # Register the worktrees in the REAL harness StateTracker and hand
            # that tracker to the loop builder (its default is an empty-world
            # MagicMock, which can never surface a tracked workspace).
            seed_stale_workspaces(self._harness.state, config, seed)
            self._loop_ports.setdefault("workspace_gc_state", self._harness.state)
        if seed.gate_activations:
            self._loop_ports.setdefault(
                "gate_activation_detect",
                build_seeded_gate_detector(seed.gate_activations),
            )
        if seed.rulesets:
            # Default canonical_dir: the same fixed baseline sandbox_main
            # materializes under the (tmp-rooted) data root — both tiers
            # audit seeded live rulesets against one deterministic contract.
            self._loop_ports.setdefault(
                "branch_protection_audit",
                build_seeded_branch_protection_auditor(config, self._github),
            )
        if seed.expired_run_dirs:
            from run_recorder import RunRecorder  # noqa: PLC0415

            materialize_expired_runs(config, seed)
            self._loop_ports.setdefault("run_recorder", RunRecorder(config))
        if seed.repo_wiki_fixtures:
            # Mirrors sandbox_main's ``main()`` wiring (#10133 PIECE 2): the
            # catalog's ``wiki_store`` port defaults to a MagicMock whose
            # ``list_repos`` returns ``[]`` (see ``_build_wiki_rot_detector``),
            # so a seeded fixture is invisible to WikiRotDetectorLoop unless a
            # REAL ``RepoWikiStore`` pointed at the exact same wiki_root the
            # materializer wrote to replaces it — ``resolve_self_wiki_root``
            # is the single source of truth both loaders share, so this
            # never drifts from sandbox_main's own construction.
            from repo_wiki import RepoWikiStore  # noqa: PLC0415

            materialize_wiki_fixtures(config, seed)
            self._loop_ports.setdefault(
                "wiki_store",
                RepoWikiStore(
                    wiki_root=resolve_self_wiki_root(config),
                    tracked_root=config.repo_root / config.repo_wiki_path,
                    self_slug=config.repo,
                ),
            )
        epic_labels = set(getattr(config, "epic_label", None) or ["hydraflow-epic"])
        if any(epic_labels & set(i.get("labels", [])) for i in seed.issues):
            # Give epic_sweeper a real fetcher over the shared FakeGitHub so a
            # seeded epic (and its closed children) is actually swept; the
            # builder default is an empty-world MagicMock.
            from mockworld.fakes.fake_issue_fetcher import (  # noqa: PLC0415
                FakeIssueFetcher,
            )

            self._loop_ports.setdefault(
                "issue_fetcher", FakeIssueFetcher(github=self._github)
            )
            self._loop_ports.setdefault("epic_sweeper_state", self._harness.state)

    # --- Dashboard lifecycle ---

    @property
    def dashboard_url(self) -> str | None:
        return self._dashboard_url

    async def start_dashboard(self, *, with_orchestrator: bool = False) -> str:
        """Boot HydraFlowDashboard in-process against this world's fakes.

        Returns the base URL (e.g. 'http://127.0.0.1:54321'). Idempotent —
        subsequent calls return the existing URL.

        When ``with_orchestrator`` is True, MockWorld constructs a real
        HydraFlowOrchestrator wired against the fakes (Task 9). Otherwise
        the dashboard is wired to a lightweight shim that exposes the
        harness's IssueStore so seeded issues are visible in the UI.
        """
        if self._dashboard_url is not None:
            return self._dashboard_url

        from dashboard import HydraFlowDashboard  # noqa: PLC0415

        config = self._harness.config
        # Force ephemeral port; override static defaults from HydraFlowConfig.
        config.dashboard_host = "127.0.0.1"
        config.dashboard_port = 0

        # Reuse the harness's bus and state tracker so seeded state reaches the UI.
        bus = self._harness.bus
        state = self._harness.state

        if with_orchestrator:
            orchestrator = await self._build_wired_orchestrator(config, bus, state)
        else:
            # Lightweight shim so /api/pipeline and /api/queue serve harness data
            # without spinning up a full HydraFlowOrchestrator.
            orchestrator = _HarnessOrchestratorShim(self._harness)

        # Surface registered repos through /api/repos (the supervised-repo list
        # reads a repo_store, not the registry). Only when a repo was actually
        # added — single-repo scenarios keep the host-only legacy path (#9359).
        repo_store = None
        if len(self._registry) > 0:
            from repo_store import RepoRegistryStore  # noqa: PLC0415

            repo_store = RepoRegistryStore(self._tmp_path)

        dashboard = HydraFlowDashboard(
            config=config,
            event_bus=bus,
            state=state,
            orchestrator=orchestrator,
            repo_store=repo_store,
            # #9347 began ALWAYS passing this registry to the dashboard, even
            # empty. A non-None-but-empty registry flips the dashboard onto its
            # multi-repo branches for single-repo browser scenarios: POST
            # /api/control/start runs registry.start_all() over zero runtimes
            # (orchestrator stuck "idle"), and resolve_runtime / is_pipeline_active
            # resolve an empty set (cards "0 merged", flow-dots missing, routes
            # fall back to real gh -> 401). Only hand the dashboard the registry
            # once a repo is actually registered; otherwise use the host/legacy
            # path (the pre-#9347 behaviour these scenarios were written against).
            # See issue #9359. This invariant is now also guarded at PR time by
            # the `scenario-browser-fast` CI job (ci.yml), so dashboard
            # regressions no longer wait for the rc/*->main promotion gate.
            registry=self._registry if len(self._registry) > 0 else None,
            default_repo_slug=config.repo.replace("/", "-") if config.repo else None,
        )
        await dashboard.start()

        port = await self._await_dashboard_port(dashboard)
        self._dashboard = dashboard
        self._dashboard_url = f"http://127.0.0.1:{port}"
        return self._dashboard_url

    async def stop_dashboard(
        self, *, orchestrator_stop_timeout: float = _ORCHESTRATOR_STOP_TIMEOUT
    ) -> None:
        """Shut down uvicorn task, stop orchestrator if present.

        ``orchestrator.stop()`` is bounded (#10073): a stop path that blocks —
        or any task surviving shutdown — used to wedge the in-process harness
        at event-loop close, hanging pytest until the CI job's 20-minute
        timeout with zero output. On timeout we dump live asyncio task names
        and faulthandler stacks to stderr, then raise a TimeoutError naming
        the survivors, so the failure is loud and attributed.
        """
        if self._dashboard is None:
            return
        try:
            if self._dashboard._orchestrator and self._dashboard._orchestrator.running:
                try:
                    await asyncio.wait_for(
                        self._dashboard._orchestrator.stop(),
                        timeout=orchestrator_stop_timeout,
                    )
                except TimeoutError:
                    live = self._dump_stuck_teardown_diagnostics(
                        orchestrator_stop_timeout
                    )
                    raise TimeoutError(
                        "MockWorld.stop_dashboard: orchestrator.stop() did not "
                        f"complete within {orchestrator_stop_timeout}s (#10073); "
                        f"live tasks: {live}"
                    ) from None

            uv_server = getattr(self._dashboard, "_uvicorn_server", None)
            if uv_server is not None:
                uv_server.should_exit = True
                # Close bound listener sockets synchronously so the port is
                # released before we return. Uvicorn's graceful shutdown can
                # take seconds; explicit close avoids flake.
                for s in uv_server.servers:
                    s.close()
                    await s.wait_closed()

            await asyncio.wait_for(self._dashboard.stop(), timeout=5)
        finally:
            self._dashboard = None
            self._dashboard_url = None

    @staticmethod
    def _dump_stuck_teardown_diagnostics(timeout: float) -> list[str]:
        """Dump live task names + faulthandler stacks to stderr; return the names.

        Called when ``orchestrator.stop()`` exceeds its bound (#10073). The
        task-name dump attributes the wedge (the #10071 orphan-probe
        technique); the faulthandler dump adds thread stacks. Both are
        best-effort diagnostics — the load-bearing signal is the TimeoutError
        the caller raises with the returned names.
        """
        current = asyncio.current_task()
        live = sorted(
            task.get_name()
            for task in asyncio.all_tasks()
            if task is not current and not task.done()
        )
        print(
            f"MockWorld.stop_dashboard: orchestrator.stop() timed out after {timeout}s; "
            f"live tasks: {live}",
            file=sys.stderr,
            flush=True,
        )
        # capsys-style captures replace sys.stderr with a fileno-less buffer,
        # which faulthandler rejects — never let diagnostics mask the timeout.
        with contextlib.suppress(Exception):
            faulthandler.dump_traceback(file=sys.stderr)
        return live

    async def _await_dashboard_port(self, dashboard: Any, timeout: float = 5.0) -> int:
        """Poll ``dashboard._uvicorn_server`` for the bound port up to ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            uv_server = getattr(dashboard, "_uvicorn_server", None)
            if uv_server and uv_server.started and uv_server.servers:
                sock = uv_server.servers[0].sockets[0]
                return int(sock.getsockname()[1])
            await asyncio.sleep(0.05)
        raise TimeoutError("dashboard did not bind a port within 5s")

    async def _build_wired_orchestrator(self, config: Any, bus: Any, state: Any) -> Any:
        """Construct a HydraFlowOrchestrator whose services are air-gapped Fakes.

        Threads this world's Fakes through ``build_services`` exactly as
        ``mockworld.sandbox_main.main`` does — ``subprocess_runner=Fake…`` plus
        the Fake ports/runners and the claude/git-spawn sentinels
        (``air_gap_runner_sentinels``) — so the ~60 BACKGROUND caretaker loops
        the orchestrator supervises can never spawn real Docker/gh/claude on the
        shared event loop.

        Before #10253 this built a REAL ``ServiceRegistry`` (real Docker
        ``SubprocessRunner``, real ``gh``) and monkeypatched only the four
        PIPELINE runners after the fact via ``_wire_targets``; every background
        loop kept its real adapter. Clicking the dashboard Start button then ran
        those real loops in-process and a single blocking caretaker call wedged
        the loop shared by the test, the dashboard, and Playwright — the 2715s
        RC hang (#10215). Air-gapping the whole registry here is what makes the
        started orchestrator's background loops non-blocking.
        """
        from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher
        from mockworld.fakes.fake_issue_store import FakeIssueStore
        from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner
        from mockworld.sandbox_main import (
            _apply_sandbox_config_overrides,
            air_gap_runner_sentinels,
        )
        from orchestrator import HydraFlowOrchestrator
        from ports import (
            IssueFetcherPort,
            IssueStorePort,
            PRPort,
            WorkspacePort,
        )
        from service_registry import WorkerRegistryCallbacks, build_services

        # The same air-gap config overrides the docker sandbox applies: turn off
        # the production code paths that reach the network via a RAW gh/git
        # subprocess (merge_policy, approval_records, flake_tracker,
        # evidence_pack, …) rather than through a Faked Port. Without this a
        # background caretaker's raw ``gh`` call can still block the shared loop.
        _apply_sandbox_config_overrides(config)

        shared_github = self._github
        callbacks = WorkerRegistryCallbacks(
            update_status=lambda *_a, **_kw: None,
            # Enable every caretaker loop (mirrors sandbox_main's
            # ``loops_enabled=None``) so the started orch genuinely exercises the
            # background fleet the Start button spins up — the fleet that wedged.
            is_enabled=lambda *_a, **_kw: True,
            get_interval=lambda *_a, **_kw: 60,
            get_watchdog_timeout=(
                lambda *_a, **_kw: config.loop_watchdog_default_seconds
            ),
        )
        svc = build_services(
            config,
            bus,
            state,
            asyncio.Event(),
            callbacks,
            prs=cast(PRPort, shared_github),
            workspaces=cast(WorkspacePort, self._workspace),
            store=cast(
                IssueStorePort,
                FakeIssueStore(github=shared_github, event_bus=bus),
            ),
            fetcher=cast(IssueFetcherPort, FakeIssueFetcher(github=shared_github)),
            runners=self._llm,
            subprocess_runner=FakeSubprocessRunner(self._docker),
        )
        # Attach the fake-LLM sentinels + fake repo-prober (the paths
        # build_services' two seams don't cover); shared with sandbox_main.
        air_gap_runner_sentinels(svc, self._llm)

        return HydraFlowOrchestrator(
            config=config,
            event_bus=bus,
            state=state,
            pipeline_enabled=False,
            services=svc,
        )
