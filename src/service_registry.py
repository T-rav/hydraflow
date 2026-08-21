"""Service registry and factory for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from acceptance_criteria import AcceptanceCriteriaGenerator
from adr_conformance_loop import AdrConformanceLoop
from adr_conformance_runner import SubprocessConformanceRunner
from adr_drift_resolver_loop import AdrDriftResolverLoop
from adr_drift_resolver_runtime import AdrDriftResolverLLMClient
from adr_drift_triage_llm import AdrDriftTriageLLM
from adr_index import ADRIndex
from adr_reviewer import ADRCouncilReviewer
from adr_reviewer_loop import ADRReviewerLoop
from adr_touchpoint_auditor_loop import AdrTouchpointAuditorLoop
from agent import AgentRunner
from auto_agent_preflight_loop import AutoAgentPreflightLoop
from auto_tighten.attribution import AttributionResolver
from auto_tighten.coverage_adapter import CoverageAdapter
from auto_tighten.coverage_ingestor import CoverageIngestor
from auto_tighten.observation_store import ObservationStore
from auto_tighten.pr_author import TighteningPrAuthor
from auto_tighten_loop import AutoTightenLoop
from base_background_loop import LoopDeps
from baseline_policy import BaselinePolicy
from beads_manager import BeadsManager
from branch_protection_audit import (
    AuditReport,
    audit_repo,
    gh_fetch_legacy_protection,
    gh_fetch_rulesets,
)
from branch_protection_auditor_loop import BranchProtectionAuditorLoop  # noqa: TCH001
from bug_reproducer import BugReproducer
from caching_issue_store import CachingIssueStore
from ci_monitor_loop import CIMonitorLoop  # noqa: TCH001
from config import Credentials, HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from convergence_oscillation_loop import ConvergenceOscillationLoop
from corpus_learning_loop import CorpusLearningLoop
from cost_budget_watcher_loop import CostBudgetWatcherLoop  # noqa: TCH001
from decomposition_council import DecompositionCouncil
from dependabot_merge_loop import DependabotMergeLoop
from detector_calibration_loop import DetectorCalibrationLoop
from diagnostic_loop import DiagnosticLoop  # noqa: TCH001
from diagnostic_runner import DiagnosticRunner
from diagram_loop import DiagramLoop  # noqa: TCH001
from discover_runner import DiscoverRunner
from disturbance_dampener_loop import DisturbanceDampenerLoop
from docker_runner import get_docker_runner
from edge_proposer_loop import EdgeProposerLoop
from entry_evidence_loop import EntryEvidenceLoop
from epic import EpicCompletionChecker, EpicManager
from epic_monitor_loop import EpicMonitorLoop
from epic_sweeper_loop import EpicSweeperLoop
from erosion_metrics_loop import ErosionMetricsLoop
from escape_ledger_loop import EscapeLedgerLoop
from events import EventBus
from execution import SubprocessRunner
from fail_open_monitor_loop import FailOpenMonitorLoop
from fake_coverage_auditor_loop import FakeCoverageAuditorLoop
from fitness_scorecard_loop import FitnessScorecardLoop
from flake_tracker_loop import FlakeTrackerLoop
from gate_activation_check import check_gate_activation
from gate_activator_loop import GateActivatorLoop  # noqa: TCH001
from gate_health_loop import GateHealthLoop
from gateway_coverage_loop import GatewayCoverageLoop
from github_cache_loop import GitHubCacheLoop, GitHubDataCache
from giveup_self_solve import PlanRetrySelfSolver
from giveup_window import GiveUpClass, GiveUpTracker, GiveUpWindow, resolve_window
from goal_supervisor_loop import GoalSupervisorLoop  # noqa: TCH001
from harness_insights import HarnessInsightStore
from health_monitor_loop import HealthMonitorLoop
from hitl_phase import HITLPhase
from hitl_runner import HITLRunner
from human_steering_loop import HumanSteeringLoop
from implement_phase import ImplementPhase
from intervention_tally_loop import InterventionTallyLoop
from issue_cache import IssueCache
from issue_decomposer import IssueDecomposer
from issue_fetcher import GitHubTaskFetcher, IssueFetcher
from issue_refinement_loop import IssueRefinementLoop
from issue_store import IssueStore
from label_drift_watcher_loop import LabelDriftWatcherLoop
from live_corpus_replay_loop import (
    LiveCorpusReplayLoop,  # noqa: TCH001 — dataclass annotation
)
from log_ingest_loop import LogIngestLoop  # noqa: TCH001 — used in dataclass field
from loop_fitness import IssueRecord as _IssueRecord
from memory_backlog_loop import MemoryBacklogLoop
from merge_conflict_resolver import MergeConflictResolver
from merge_state_watcher_loop import MergeStateWatcherLoop
from models import StatusCallback
from observability.noop_adapter import NoOpObservabilityAdapter
from plan_phase import PlanPhase
from plan_reviewer import PlanReviewer
from plan_touchpoint_expander import PlanTouchpointExpander
from planner import PlannerRunner
from ports import (
    IssueFetcherPort,
    IssueStorePort,
    ObservabilityPort,
    PRPort,
    WorkspacePort,
)
from post_merge_handler import PostMergeHandler
from pr_manager import PRManager
from pr_red_repair_loop import PrRedRepairLoop
from pr_unsticker import PRUnsticker
from pr_unsticker_loop import PRUnstickerLoop
from precondition_gate import PreconditionGate
from preflight.audit import PreflightAuditStore
from pricing_refresh_loop import PricingRefreshLoop  # noqa: TCH001
from principles_audit_loop import PrinciplesAuditLoop
from rails_drift_caretaker_loop import (  # noqa: TCH001
    RailsDriftCaretakerLoop,
    build_rails_auditor,
)
from rc_budget_loop import RCBudgetLoop
from repo_wiki import RepoWikiStore
from repo_wiki_loop import RepoWikiLoop  # noqa: TCH001
from report_issue_loop import ReportIssueLoop
from research_runner import ResearchRunner
from retrospective import RetrospectiveCollector
from retrospective_loop import RetrospectiveLoop  # noqa: TCH001
from retrospective_queue import RetrospectiveQueue  # noqa: TCH001
from review_insights import ReviewInsightStore
from review_phase import ReviewPhase
from reviewer import ReviewRunner
from route_back import RouteBackCoordinator
from run_recorder import RunRecorder
from runs_gc_loop import RunsGCLoop
from sampled_audit_loop import SampledAuditLoop
from sandbox_failure_fixer_loop import SandboxFailureFixerLoop
from second_order_vitals_loop import SecondOrderVitalsLoop
from security_patch_loop import SecurityPatchLoop  # noqa: TCH001
from shape_runner import ShapeRunner
from skill_prompt_eval_loop import SkillPromptEvalLoop
from staging_bisect_loop import StagingBisectLoop
from staging_promotion_loop import StagingPromotionLoop
from stale_issue_gc_loop import StaleIssueGCLoop  # noqa: TCH001
from stale_issue_loop import StaleIssueLoop
from state import StateTracker
from term_proposer_loop import TermProposerLoop
from term_pruner_loop import TermPrunerLoop
from transcript_summarizer import TranscriptSummarizer
from triage import TriageRunner
from triage_phase import TriagePhase
from triage_retry_loop import TriageRetryLoop
from troubleshooting_store import TroubleshootingPatternStore
from trust_fleet_sanity_loop import TrustFleetSanityLoop
from verification_judge import VerificationJudge
from wiki_rot_detector_loop import WikiRotDetectorLoop
from workspace import WorkspaceManager
from workspace_gc_loop import WorkspaceGCLoop

if TYPE_CHECKING:
    from scripts.gates.activation import ActivationProposal

    from auto_tighten.ratchet_adapter import RatchetAdapter
    from metrics_manager import MetricsManager

logger = logging.getLogger("hydraflow.service_registry")

_ISSUE_LIMIT = 1000
_PR_LIMIT = 1000


def _make_fitness_issue_fetcher(prs: PRManager):
    """Return an async closure that fetches issues + PRs and maps them to IssueRecord.

    Uses the ``list_all_issues``/``list_all_prs`` PRPort methods (#11418).
    If either call returns exactly the --limit count, a warning is logged
    so the caller knows results may be capped.
    """
    from datetime import datetime as _datetime

    def _parse_dt(s: str | None) -> _datetime | None:
        if not s:
            return None
        return _datetime.fromisoformat(s.replace("Z", "+00:00"))

    async def _fetcher() -> list[_IssueRecord]:
        records: list[_IssueRecord] = []

        # -- issues --
        issues = await prs.list_all_issues(state="all", limit=_ISSUE_LIMIT)
        if len(issues) == _ISSUE_LIMIT:
            logger.warning(
                "fitness_issue_fetcher: issue results capped at %d; "
                "some issues may be missing from the fitness window",
                _ISSUE_LIMIT,
            )
        for item in issues:
            records.append(
                _IssueRecord(
                    number=item["number"],
                    labels=[lbl["name"] for lbl in item.get("labels", [])],
                    is_pr=False,
                    state=item["state"].lower(),
                    merged=False,
                    created_at=_parse_dt(item.get("createdAt")),  # type: ignore[arg-type]
                    closed_at=_parse_dt(item.get("closedAt")),
                )
            )

        # -- pull requests --
        pull_requests = await prs.list_all_prs(state="all", limit=_PR_LIMIT)
        if len(pull_requests) == _PR_LIMIT:
            logger.warning(
                "fitness_issue_fetcher: PR results capped at %d; "
                "some PRs may be missing from the fitness window",
                _PR_LIMIT,
            )
        for item in pull_requests:
            records.append(
                _IssueRecord(
                    number=item["number"],
                    labels=[lbl["name"] for lbl in item.get("labels", [])],
                    is_pr=True,
                    state=item["state"].lower(),
                    merged=item.get("mergedAt") is not None,
                    created_at=_parse_dt(item.get("createdAt")),  # type: ignore[arg-type]
                    closed_at=_parse_dt(item.get("closedAt")),
                )
            )

        return records

    return _fetcher


@dataclass
class ServiceRegistry:
    """Holds all service instances for the orchestrator."""

    # Core infrastructure
    observability: ObservabilityPort
    workspaces: WorkspacePort
    subprocess_runner: SubprocessRunner
    agents: AgentRunner
    planners: PlannerRunner
    prs: PRPort
    reviewers: ReviewRunner
    hitl_runner: HITLRunner
    triage: TriageRunner
    summarizer: TranscriptSummarizer

    # Data layer
    fetcher: IssueFetcher
    store: IssueStorePort
    # Optional read-through cache decorator wrapping `store`. Phases
    # that want stale-bounded enrich_with_comments + fetch recording
    # consume this instead of `store` directly. Defaults to the same
    # object as `store` when caching_issue_store_enabled is False so
    # consumers can opt in without conditional wiring.
    phase_store: IssueStorePort
    issue_cache: IssueCache

    # Phase coordinators
    triager: TriagePhase
    # ADR-0107: Discover/Shape are no longer standalone phases. The
    # DiscoverRunner / ShapeRunner engines are held here (not phase wrappers)
    # so the planner can invoke them on demand behind its decision gate, and
    # so the sandbox harness can route them through the fake-LLM sentinel.
    discover_runner: DiscoverRunner
    shape_runner: ShapeRunner
    planner_phase: PlanPhase
    hitl_phase: HITLPhase
    implementer: ImplementPhase
    reviewer: ReviewPhase

    # Background workers and support
    run_recorder: RunRecorder
    metrics_manager: MetricsManager
    pr_unsticker: PRUnsticker
    retrospective: RetrospectiveCollector
    ac_generator: AcceptanceCriteriaGenerator
    verification_judge: VerificationJudge
    epic_checker: EpicCompletionChecker
    epic_manager: EpicManager

    # GitHub data cache
    github_cache: GitHubDataCache
    github_cache_loop: GitHubCacheLoop

    # Background loops
    pr_unsticker_loop: PRUnstickerLoop
    merge_state_watcher_loop: MergeStateWatcherLoop
    report_issue_loop: ReportIssueLoop
    epic_monitor_loop: EpicMonitorLoop
    epic_sweeper_loop: EpicSweeperLoop
    workspace_gc_loop: WorkspaceGCLoop
    runs_gc_loop: RunsGCLoop
    adr_reviewer_loop: ADRReviewerLoop
    health_monitor_loop: HealthMonitorLoop
    dependabot_merge_loop: DependabotMergeLoop
    staging_promotion_loop: StagingPromotionLoop
    staging_bisect_loop: StagingBisectLoop
    stale_issue_loop: StaleIssueLoop
    log_ingest_loop: LogIngestLoop
    stale_issue_gc_loop: StaleIssueGCLoop
    gate_health_loop: GateHealthLoop
    pr_red_repair_loop: PrRedRepairLoop
    erosion_metrics_loop: ErosionMetricsLoop
    fail_open_monitor_loop: FailOpenMonitorLoop
    escape_ledger_loop: EscapeLedgerLoop
    intervention_tally_loop: InterventionTallyLoop
    sampled_audit_loop: SampledAuditLoop
    second_order_vitals_loop: SecondOrderVitalsLoop
    issue_refinement_loop: IssueRefinementLoop
    ci_monitor_loop: CIMonitorLoop
    branch_protection_auditor_loop: BranchProtectionAuditorLoop
    goal_supervisor_loop: GoalSupervisorLoop
    rails_drift_caretaker_loop: RailsDriftCaretakerLoop
    gate_activator_loop: GateActivatorLoop
    security_patch_loop: SecurityPatchLoop
    repo_wiki_store: RepoWikiStore
    repo_wiki_loop: RepoWikiLoop
    diagnostic_loop: DiagnosticLoop
    retrospective_loop: RetrospectiveLoop
    retrospective_queue: RetrospectiveQueue
    principles_audit_loop: PrinciplesAuditLoop
    flake_tracker_loop: FlakeTrackerLoop
    skill_prompt_eval_loop: SkillPromptEvalLoop
    fake_coverage_auditor_loop: FakeCoverageAuditorLoop
    adr_touchpoint_auditor_loop: AdrTouchpointAuditorLoop
    adr_drift_resolver_loop: AdrDriftResolverLoop
    adr_conformance_loop: AdrConformanceLoop
    auto_tighten_loop: AutoTightenLoop
    memory_backlog_loop: MemoryBacklogLoop
    rc_budget_loop: RCBudgetLoop
    wiki_rot_detector_loop: WikiRotDetectorLoop
    trust_fleet_sanity_loop: TrustFleetSanityLoop
    label_drift_watcher_loop: LabelDriftWatcherLoop
    contract_refresh_loop: ContractRefreshLoop
    corpus_learning_loop: CorpusLearningLoop
    auto_agent_preflight_loop: AutoAgentPreflightLoop
    gateway_coverage_loop: GatewayCoverageLoop
    detector_calibration_loop: DetectorCalibrationLoop
    sandbox_failure_fixer_loop: SandboxFailureFixerLoop
    disturbance_dampener_loop: DisturbanceDampenerLoop
    human_steering_loop: HumanSteeringLoop
    diagram_loop: DiagramLoop
    cost_budget_watcher_loop: CostBudgetWatcherLoop
    pricing_refresh_loop: PricingRefreshLoop
    term_proposer_loop: TermProposerLoop
    term_pruner_loop: TermPrunerLoop
    edge_proposer_loop: EdgeProposerLoop
    entry_evidence_loop: EntryEvidenceLoop
    live_corpus_replay_loop: LiveCorpusReplayLoop
    triage_retry_loop: TriageRetryLoop
    convergence_oscillation_loop: ConvergenceOscillationLoop
    fitness_scorecard_loop: FitnessScorecardLoop

    # Optional integrations


@dataclass(frozen=True)
class WorkerRegistryCallbacks:
    """Focused interface for background-worker management callbacks.

    Replaces the former ``OrchestratorCallbacks`` god-object with only the
    focused callbacks that ``LoopDeps`` and status-reporting consumers need.
    """

    update_status: StatusCallback
    is_enabled: Callable[[str], bool]
    get_interval: Callable[[str], int]
    # Per-loop work-cycle watchdog bound override (#9503) — mirrors
    # get_interval. Wired to LoopDeps.timeout_cb below so every shared-deps
    # loop's watchdog reads the live operator override each cycle.
    get_watchdog_timeout: Callable[[str], int]


_GH_SUBPROCESS_TIMEOUT_S = 120

# Injectable `gh` runner type shared by the two auto-tighten closures below.
# Mirrors `auto_pr._run_gh`'s shape (a thin `subprocess.run` wrapper) so unit
# tests can pass a fake without monkeypatching `subprocess.run` globally.
GhRunner = Callable[..., "subprocess.CompletedProcess[str]"]


def run_gh_command(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Default `gh` subprocess runner for the auto-tighten closures.

    Kept as a free function (mirrors `auto_pr._run_gh`) so
    `make_gh_coverage_fetch` / `make_gh_merged_pr_lister` can be unit-tested
    by injecting a fake `runner` instead of monkeypatching `subprocess.run`.
    """
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        timeout=_GH_SUBPROCESS_TIMEOUT_S,
    )


def make_gh_coverage_fetch(
    config: HydraFlowConfig, *, runner: GhRunner = run_gh_command
) -> Callable[[], tuple[str, str, str] | None]:
    """Build the ``fetch_latest`` closure ``CoverageIngestor`` needs.

    Finds the most recent successful CI run on the base branch, downloads its
    ``coverage-json`` artifact, and returns ``(run_id, head_sha, coverage_json_text)``.
    Returns ``None`` on any failure (no successful runs yet, no artifact,
    unreadable JSON) — a safe "nothing new to ingest" signal, never a crash.
    """

    def _fetch_latest() -> tuple[str, str, str] | None:
        base = config.base_branch()
        list_proc = runner(
            [
                "gh",
                "run",
                "list",
                "--branch",
                base,
                "--workflow",
                "ci.yml",
                "--json",
                "databaseId,headSha,status,conclusion",
                "--limit",
                "20",
            ],
            cwd=config.repo_root,
        )
        if list_proc.returncode != 0:
            return None
        try:
            runs = json.loads(list_proc.stdout)
        except (json.JSONDecodeError, TypeError):
            return None

        latest = next(
            (
                run
                for run in runs
                if run.get("status") == "completed"
                and run.get("conclusion") == "success"
            ),
            None,
        )
        if latest is None:
            return None

        run_id = str(latest["databaseId"])
        head_sha = str(latest["headSha"])

        with tempfile.TemporaryDirectory() as tmpdir:
            download_proc = runner(
                [
                    "gh",
                    "run",
                    "download",
                    run_id,
                    "--name",
                    "coverage-json",
                    "--dir",
                    tmpdir,
                ],
                cwd=config.repo_root,
            )
            if download_proc.returncode != 0:
                return None
            cov_path = Path(tmpdir) / "coverage.json"
            if not cov_path.exists():
                return None
            cov_text = cov_path.read_text()

        return (run_id, head_sha, cov_text)

    return _fetch_latest


def make_gh_merged_pr_lister(
    config: HydraFlowConfig, *, runner: GhRunner = run_gh_command
) -> Callable[[str], list[dict]]:
    """Build the ``list_merged_prs`` closure ``AttributionResolver`` needs.

    Lists PRs merged to the base branch since ``since_iso``, normalizing
    ``gh``'s ``files: [{"path": ...}]`` objects to the flat
    ``files: [path, ...]`` list of strings ``AttributionResolver.attribute``
    expects, and ``mergedAt`` -> ``merged_at``. Returns ``[]`` on failure —
    attribution failure is a safe HOLD downstream, never a crash.
    """

    def _list_merged_prs(since_iso: str) -> list[dict]:
        base = config.base_branch()
        proc = runner(
            [
                "gh",
                "pr",
                "list",
                "--base",
                base,
                "--state",
                "merged",
                "--search",
                f"merged:>={since_iso}",
                "--json",
                "number,files,mergedAt",
                "--limit",
                "100",
            ],
            cwd=config.repo_root,
        )
        if proc.returncode != 0:
            return []
        try:
            prs = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            return []

        out: list[dict] = []
        for pr in prs:
            out.append(
                {
                    "number": pr["number"],
                    "files": [f["path"] for f in pr.get("files", [])],
                    "merged_at": pr.get("mergedAt"),
                }
            )
        return out

    return _list_merged_prs


def make_gh_open_pr_exists(
    config: HydraFlowConfig, *, runner: GhRunner = run_gh_command
) -> Callable[[str], bool]:
    """Build the open-PR probe ``TighteningPrAuthor`` uses for cross-tick dedup.

    Returns True when a PR is already open for ``branch`` (its head), so the
    loop skips re-opening a tightening PR whose prior tick's PR has not merged.
    Fails open (returns False on any ``gh`` error): a probe failure must not
    block a legitimate tightening, and a genuine duplicate-head open still
    resolves to a benign hold downstream via ``raise_on_failure=False``.
    """

    def _open_pr_exists(branch: str) -> bool:
        proc = runner(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number",
            ],
            cwd=config.repo_root,
        )
        if proc.returncode != 0:
            return False
        try:
            return bool(json.loads(proc.stdout))
        except (json.JSONDecodeError, TypeError):
            return False

    return _open_pr_exists


def build_state_tracker(config: HydraFlowConfig) -> StateTracker:
    """Construct a file-backed ``StateTracker``."""
    return StateTracker(config.state_file)


def build_services(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    stop_event: asyncio.Event,
    callbacks: WorkerRegistryCallbacks,
    active_issues_cb: Callable[[], None] | None = None,
    credentials: Credentials | None = None,
    *,
    # Sandbox overrides — None → construct the real adapter.
    # Production callers pass nothing and behavior is unchanged. The
    # sandbox entrypoint (mockworld.sandbox_main, Task 1.10) passes
    # Fakes here so a real ServiceRegistry can be wired around them
    # without any conditional in the production code path.
    prs: PRPort | None = None,
    workspaces: WorkspacePort | None = None,
    store: IssueStorePort | None = None,
    fetcher: IssueFetcherPort | None = None,
    observability: ObservabilityPort | None = None,
    # ``runners`` is duck-typed: any object exposing the four runner
    # attrs (triage_runner, planners, agents, reviewers) suffices.
    # FakeLLM does. See spec Component 1 RunnerSet pattern if a
    # stricter type is preferred.
    runners: object | None = None,
    # ``subprocess_runner`` is the LOWER-LEVEL docker dispatch — separate
    # from the four phase runners above.  ``runners=fake_llm`` rebinds
    # the phase runners but ``SubprocessRunner`` is still used by
    # ``TranscriptSummarizer``, ``HITLRunner``, ``AutoAgentRunner``,
    # and the pre-quality-review skill subprocesses inside
    # ``AgentRunner``.  All of those shell ``claude -p`` directly,
    # which hangs forever on the sandbox's air-gapped network.  Pass a
    # ``FakeSubprocessRunner`` here to short-circuit every remaining
    # claude path; production callers pass nothing and get the real
    # Docker runner.
    subprocess_runner: SubprocessRunner | None = None,
) -> ServiceRegistry:
    """Create all services wired together.

    Production callers pass no override kwargs and get real adapters
    constructed from config + credentials. The sandbox entrypoint
    (``mockworld.sandbox_main``) passes Fake adapters to short-circuit
    the construction.

    This replaces the 170-line orchestrator constructor body.
    """
    # Build credentials from env if not supplied by caller.
    if credentials is None:
        from config import build_credentials

        credentials = build_credentials(config)

    # Configure global GitHub API concurrency limiter (startup config
    # belongs in the composition root, not the orchestrator).
    from subprocess_util import configure_gh_circuit_breaker, configure_gh_concurrency

    configure_gh_concurrency(config.gh_api_concurrency)
    configure_gh_circuit_breaker(
        enabled=config.gh_circuit_breaker_enabled,
        max_failures=config.gh_circuit_breaker_max_failures,
        reset_timeout=config.gh_circuit_breaker_reset_timeout_s,
    )

    # Shadow corpus (#8786). Every gh/git/docker/claude subprocess call
    # feeds the bounded, normalized, PII-scrubbed corpus that
    # LiveCorpusReplayLoop consumes. ``shadow_corpus_max_per_adapter``
    # caps disk usage via LRU eviction.
    from contracts.shadow import ShadowCorpus
    from subprocess_util import set_shadow_sampler

    shadow_corpus = ShadowCorpus(
        config.data_root / "contract_shadow",
        max_per_adapter=config.shadow_corpus_max_per_adapter,
    )
    set_shadow_sampler(shadow_corpus.record)

    # Hindsight semantic memory and MemoryJudge — REMOVED in Phase 3 cutover.
    # The wiki + tribal + ADR-draft pipeline is the new primary. Any
    # historical Hindsight content that needs to be preserved should have
    # been extracted via scripts/extract_hindsight_to_wiki.py before merge.

    # Observability port — constructed once and injected throughout.
    # Production path: NoOpObservabilityAdapter (discards events until the SRE
    # agent wires a real backend, ADR-0118). Sandbox/test path: caller passes
    # FakeObservability.
    if observability is None:
        observability = NoOpObservabilityAdapter()

    # Core runners
    if workspaces is None:
        workspaces = WorkspaceManager(config, credentials=credentials)
    # Cast is duck-safe at runtime: the override (FakeWorkspace, if any)
    # duck-types as WorkspaceManager for downstream callers in this
    # function. They only call WorkspacePort methods (which both
    # WorkspaceManager and FakeWorkspace satisfy), so passing the Fake is
    # safe.
    #
    # WARNING — type-checker blind spot. ``cast`` is a no-op at runtime;
    # pyright then trusts it and treats ``workspaces`` as the concrete
    # ``WorkspaceManager``. If a downstream caller starts using a method
    # that lives on ``WorkspaceManager`` but NOT on ``WorkspacePort`` /
    # ``FakeWorkspace``, the type checker will *not* flag it — the bug
    # only surfaces at sandbox runtime. The mitigation is Task 1.9's full
    # widening of downstream method signatures to take
    # ``WorkspacePort`` directly, after which this cast can be removed.
    workspaces = cast(WorkspaceManager, workspaces)
    if subprocess_runner is None:
        subprocess_runner = get_docker_runner(config, credentials=credentials)
    # The self-repo's wiki lives at ``docs/wiki/`` so it is
    # git-tracked alongside the code it documents. Other managed repos'
    # wikis are runtime-cached under ``.hydraflow/repo_wiki/<owner>/<repo>/``.
    self_wiki_root = config.repo_root / "docs" / "wiki"
    if not self_wiki_root.exists():
        # Fallback for repos that haven't migrated yet: keep the legacy
        # runtime-only location so this PR's restructure stays backward
        # compatible with managed-repo deployments.
        self_wiki_root = config.data_path("repo_wiki")
    repo_wiki_store = RepoWikiStore(
        wiki_root=self_wiki_root,
        # Phase 3: per-entry tracked layout committed inside the target
        # repo. Prefer it over the legacy .hydraflow/repo_wiki/ when
        # present so agents read the same wiki that the factory writes.
        tracked_root=config.repo_root / config.repo_wiki_path,
        self_slug=config.repo,
        # Read-only: this store's roots live under the operator's main
        # checkout (repo_root). Reads (query) and gitignored caches
        # (mark_ingested) are fine, but knowledge-content writes here
        # dirty the tree and never ride a PR — the maintenance heal runs
        # in an ephemeral worktree (#9539). Runtime write paths route
        # through the worktree-isolated maintenance PR instead, via
        # wiki_maint_queue.enqueue_wiki_ingest (#9836). The flag makes any
        # missed reroute fail loudly rather than silently corrupt the tree.
        read_only=True,
    )
    from tribal_wiki import TribalWikiStore  # noqa: PLC0415
    from wiki_compiler import WikiCompiler  # noqa: PLC0415

    tribal_wiki_store = TribalWikiStore(config.data_path("tribal"))

    wiki_compiler = WikiCompiler(
        config=config,
        runner=subprocess_runner,
        credentials=credentials,
        event_bus=event_bus,
    )
    agents = AgentRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    planners = PlannerRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    researcher = ResearchRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    if prs is None:
        prs = PRManager(config, event_bus, credentials=credentials)
    # Cast is duck-safe at runtime: the override (FakeGitHub, if any)
    # duck-types as PRManager for downstream callers in this function.
    # They only call PRPort methods (which both PRManager and
    # FakeGitHub satisfy), so passing the Fake is safe.
    #
    # WARNING — type-checker blind spot. ``cast`` is a no-op at runtime;
    # pyright then trusts it and treats ``prs`` as the concrete
    # ``PRManager``. If a downstream caller starts using a method that
    # lives on ``PRManager`` but NOT on ``PRPort`` / ``FakeGitHub``, the
    # type checker will *not* flag it — the bug only surfaces at
    # sandbox runtime. The mitigation is Task 1.9's full widening of
    # downstream method signatures to take ``PRPort`` directly, after
    # which this cast can be removed.
    prs = cast(PRManager, prs)
    reviewers = ReviewRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    hitl_runner = HITLRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    triage = TriageRunner(
        config,
        event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
        tribal_wiki_store=tribal_wiki_store,
    )
    triage.set_observability(observability)
    # Sandbox override — replace the four LLM-backed runners with the
    # caller-supplied set (e.g. FakeLLM in mockworld.sandbox_main). The
    # real-runner constructions above still execute (they're cheap; we
    # don't try to skip the work) but the names are immediately rebound
    # so every downstream consumer (phases, summarizer wiring,
    # ServiceRegistry fields) sees the override.
    if runners is not None:
        triage = runners.triage_runner  # type: ignore[attr-defined]
        planners = runners.planners  # type: ignore[attr-defined]
        agents = runners.agents  # type: ignore[attr-defined]
        reviewers = runners.reviewers  # type: ignore[attr-defined]
    summarizer = TranscriptSummarizer(
        config, prs, event_bus, state, runner=subprocess_runner, credentials=credentials
    )

    # Data layer
    if fetcher is None:
        fetcher = IssueFetcher(config, credentials=credentials)
    # Cast is duck-safe at runtime: the override (FakeIssueFetcher, if
    # any) duck-types as IssueFetcher for downstream callers in this
    # function. They only call IssueFetcherPort methods (which both
    # IssueFetcher and FakeIssueFetcher satisfy), so passing the Fake is
    # safe.
    #
    # WARNING — type-checker blind spot. ``cast`` is a no-op at runtime;
    # pyright then trusts it and treats ``fetcher`` as the concrete
    # ``IssueFetcher``. If a downstream caller starts using a method that
    # lives on ``IssueFetcher`` but NOT on ``IssueFetcherPort`` /
    # ``FakeIssueFetcher``, the type checker will *not* flag it — the
    # bug only surfaces at sandbox runtime. The mitigation is Task 1.9's
    # full widening of downstream method signatures to take
    # ``IssueFetcherPort`` directly, after which this cast can be removed.
    fetcher = cast(IssueFetcher, fetcher)
    gh_cache = GitHubDataCache(config, prs, fetcher)
    if store is None:
        store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)
    # Cast is duck-safe at runtime: the override (FakeIssueStore, if any)
    # duck-types as IssueStore for downstream callers in this function.
    # They only call IssueStorePort methods (which both IssueStore and
    # FakeIssueStore satisfy), so passing the Fake is safe.
    #
    # WARNING — type-checker blind spot. ``cast`` is a no-op at runtime;
    # pyright then trusts it and treats ``store`` as the concrete
    # ``IssueStore``. If a downstream caller starts using a method that
    # lives on ``IssueStore`` but NOT on ``IssueStorePort`` /
    # ``FakeIssueStore``, the type checker will *not* flag it — the bug
    # only surfaces at sandbox runtime. The mitigation is Task 1.9's
    # full widening of downstream method signatures to take
    # ``IssueStorePort`` directly, after which this cast can be removed.
    #
    # Note: ``is_in_pipeline`` is IssueStore-only plumbing not on the Port;
    # the call sites below are gated on attribute presence so override stores
    # remain functional.
    store = cast(IssueStore, store)

    # #9842: event-driven workstream cards. Every successful
    # ``swap_pipeline_labels`` is applied to the in-memory pipeline
    # immediately, so the existing coalesced PIPELINE_SNAPSHOT push moves the
    # board within ~1s instead of at the 300s ``data_poll_interval`` label
    # re-read (which stays as the reconciling backstop). hasattr-gated:
    # sandbox fakes (FakeGitHub / FakeIssueStore) read labels live and need
    # no bridge.
    if hasattr(prs, "set_pipeline_label_listener") and hasattr(
        store, "apply_label_transition"
    ):
        prs.set_pipeline_label_listener(store.apply_label_transition)

    # Local JSONL issue cache (append-only mirror; see src/issue_cache.py and #6422)
    issue_cache = IssueCache(
        config.data_path("cache"),
        enabled=config.issue_cache_enabled,
    )

    # Optional read-through cache decorator. Wraps `store` when both
    # the cache and the decorator flag are enabled, otherwise points
    # at the raw IssueStore. Phases consume `phase_store` (the
    # IssueStorePort interface) so the wiring is unchanged whether
    # caching is enabled or not.
    phase_store: IssueStorePort = (
        CachingIssueStore(  # type: ignore[assignment]
            store,
            cache=issue_cache,
            cache_ttl_seconds=config.issue_cache_enrich_ttl_seconds,
        )
        if config.issue_cache_enabled and config.caching_issue_store_enabled
        else store
    )

    # Harness insight store (shared across phases)
    harness_insights = HarnessInsightStore(
        config.repo_memory_dir,
        sensor_enrichment_enabled=config.sensor_enrichment_enabled,
        observability=observability,
    )

    # Troubleshooting pattern store (CI timeout feedback loop)
    troubleshooting_store = TroubleshootingPatternStore(
        config.data_path("memory"),
        observability=observability,
    )

    # Epic management
    epic_checker = EpicCompletionChecker(config, prs, fetcher, state=state)
    # Inject the RAW IssueStore (not `phase_store`, the CachingIssueStore
    # decorator) so epic child execution state is worker-derived (#10299):
    # `_active`/`_in_flight`/`_queues` live on the inner object.
    epic_manager = EpicManager(
        config, state, prs, fetcher, event_bus, issue_store=store
    )

    # Per-worktree JSONL task manager (always active, no external service/CLI)
    beads_mgr = BeadsManager()

    # Phase coordinators
    # NOTE: reuse the single `issue_cache` constructed above (#8790 F1).
    # A second construction here would give the read-through CachingIssueStore
    # decorator and the phase coordinators *separate* IssueCache instances over
    # the same directory — splitting the in-memory index mirror and per-issue
    # version locks, which can corrupt versioned-write serialization.

    # Route-back coordinator + precondition gate (#6423). The coordinator
    # ties label swap + cache record + counter + escalation. The gate
    # is the consumer-side filter implement_phase / review_phase use to
    # drop issues that fail their stage preconditions.
    #
    # Escalation chain when route-backs are exhausted: diagnose first
    # (automated diagnostic agent gets one more autonomous shot at
    # triaging the failure), HITL as fallback. Matches the existing
    # PipelineEscalator pattern in src/phase_utils.py.
    #
    # Formal give-up window (#10735): when enabled, the monotonic
    # max_route_backs cap is superseded by an N-in-T restart-intensity window,
    # and exhaustion routes to a machine self-solve (ADR-0105 decompose /
    # auto-agent diagnose) via PlanRetrySelfSolver — NOT to human-required.
    # human-required is applied only if the self-solve path itself exhausts.
    give_up_tracker: GiveUpTracker | None = None
    plan_retry_window: GiveUpWindow | None = None
    plan_retry_self_solver: PlanRetrySelfSolver | None = None
    if config.giveup_window_enabled:
        # Reuse the shared epic_manager + subprocess_runner so the council's
        # LLM calls route through the same docker/host dial as every other
        # loop (mirrors AutoAgentPreflightLoop's own decomposer/council build).
        giveup_decomposer = IssueDecomposer(prs, epic_manager, state, config)
        giveup_council = DecompositionCouncil(subprocess_runner, config)
        give_up_tracker = GiveUpTracker(state)
        plan_retry_window = resolve_window(config, GiveUpClass.PLAN_RETRY)
        plan_retry_self_solver = PlanRetrySelfSolver(
            config=config,
            state=state,
            prs=prs,
            decomposer=giveup_decomposer,
            council=giveup_council,
            diagnose_label=config.diagnose_label[0],
        )
    route_back_coordinator = RouteBackCoordinator(
        cache=issue_cache,
        prs=prs,
        counter=state,  # StateTracker satisfies RouteBackCounterPort
        hitl_label=config.hitl_label[0],
        diagnose_label=config.diagnose_label[0],
        max_route_backs=2,
        give_up_tracker=give_up_tracker,
        plan_retry_window=plan_retry_window,
        self_solve=plan_retry_self_solver,
    )
    # The gate enforces stage preconditions only when BOTH the cache is
    # enabled (so records exist to check) AND the dedicated gate flag
    # is set. The gate flag defaults to False so that turning on the
    # cache doesn't automatically activate enforcement on a fresh
    # install with no historical records — operators flip the gate
    # flag separately after confirming cache coverage.
    precondition_gate = PreconditionGate(
        cache=issue_cache,
        coordinator=route_back_coordinator,
        enabled=(config.issue_cache_enabled and config.precondition_gate_enabled),
    )

    # Adversarial plan reviewer (#6421) and triage-time bug reproducer
    # (#6424). Both are read-only/scoped agent runners that produce the
    # cache records the precondition gate consumes. Subprocess wiring
    # is the next follow-up — until then, the runners' subprocess
    # shims raise NotImplementedError and the consuming phases catch
    # the failure as a best-effort skip.
    plan_reviewer = PlanReviewer(
        config=config,
        event_bus=event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
    )
    bug_reproducer = BugReproducer(
        config=config,
        event_bus=event_bus,
        runner=subprocess_runner,
        credentials=credentials,
        wiki_store=repo_wiki_store,
    )

    triager = TriagePhase(
        config,
        state,
        store,
        triage,
        prs,
        event_bus,
        stop_event,
        epic_manager=epic_manager,
        issue_cache=issue_cache,
        bug_reproducer=bug_reproducer,
    )
    # ADR-0107: Discover/Shape are no longer standalone pipeline phases.
    # Build the discover/shape ENGINES (DiscoverRunner / ShapeRunner) directly
    # and hand them to the planner, which invokes them on demand behind its
    # decision gate (plan_phase.py:_should_discover_helper / _should_shape_helper).
    # The escalation deps (issue-filing + dedup for evaluator escalation) that
    # the standalone DiscoverPhase / ShapePhase used to bind at construction are
    # bound here instead, on a single shared hitl_escalations dedup store, so
    # the planner-invoked evaluator-escalation path keeps working unchanged.
    from dedup_store import DedupStore  # noqa: PLC0415

    hitl_escalation_dedup = DedupStore(
        "hitl_escalations",
        config.data_root / "memory" / "hitl_escalations_dedup.json",
    )
    discover_runner = DiscoverRunner(config, event_bus)
    discover_runner.bind_escalation_deps(prs, hitl_escalation_dedup)
    shape_runner = ShapeRunner(config, event_bus)
    shape_runner.bind_escalation_deps(prs, hitl_escalation_dedup)

    planner_phase = PlanPhase(
        config,
        state,
        store,
        planners,
        prs,
        event_bus,
        stop_event,
        transcript_summarizer=summarizer,
        harness_insights=harness_insights,
        epic_manager=epic_manager,
        research_runner=researcher,
        beads_manager=beads_mgr,
        wiki_store=repo_wiki_store,
        wiki_compiler=wiki_compiler,
        issue_cache=issue_cache,
        plan_reviewer=plan_reviewer,
        # ADR-0107: hand the discover/shape engines (escalation deps already
        # bound above) to the planner, whose decision gates
        # (plan_phase.py:_should_discover_helper / _should_shape_helper) invoke
        # them on demand as in-process research/shaping sub-steps.
        discover_runner=discover_runner,
        shape_runner=shape_runner,
    )

    # Earlier-adversarial pipeline AgentLike wiring (ADR-0064).
    #
    # Attach a ``SubprocessAgentRunner`` adapter to every adversarial-stage
    # slot on the plan phase. The adapter is stateless (the per-call
    # ``system_prompt`` differentiates a surfacer from a council voter), so a
    # single instance is shared across all slots.
    #
    # Why one shared instance: the AgentLike contract is
    # ``run(system_prompt, user_message) -> str``. The adapter holds
    # only the SubprocessRunner + model/tool config — no per-stage state.
    # Sharing keeps the factory small; tests verify each slot is non-None.
    from adversarial_agent_runner import SubprocessAgentRunner  # noqa: PLC0415

    adversarial_agent = SubprocessAgentRunner(
        runner=subprocess_runner,
        config=config,
        tool=config.planner_tool,
        model=config.planner_model,
        credentials=credentials,
        provider=config.planner_provider,
    )

    planner_phase.attach_adversarial_agents(
        surfacer_agent=adversarial_agent,
        council_agents={
            "builder": adversarial_agent,
            "tester": adversarial_agent,
            "risk_skeptic": adversarial_agent,
        },
        spec_ac_agent=adversarial_agent,
        spec_judge_agent=adversarial_agent,
    )
    # ADR-0063 W3b: the plan touchpoint-expander shares the same
    # AgentLike contract. Wired post-construction (mirrors
    # ``attach_adversarial_agents``) so the field default stays ``None``
    # for tests that build PlanPhase directly without the factory.
    planner_phase._touchpoint_expander = PlanTouchpointExpander(
        agent=adversarial_agent,
    )

    hitl_phase = HITLPhase(
        config,
        state,
        store,
        fetcher,
        workspaces,
        hitl_runner,
        prs,
        event_bus,
        stop_event,
        active_issues_cb=active_issues_cb,
    )
    run_recorder = RunRecorder(config)

    # ADR-0063 W5: wire the spec-compliance reviewer when the kill-switch
    # is on. The adapter reuses the AgentRunner's subprocess plumbing so
    # the reviewer shares tracing/auth-retry behavior with the implementer.
    spec_reviewer = None
    if config.implement_two_stage_review_enabled:
        from implement_spec_reviewer import (  # noqa: PLC0415
            AgentSubagentRunnerAdapter,
            DefaultSpecComplianceReviewer,
        )

        spec_reviewer = DefaultSpecComplianceReviewer(
            AgentSubagentRunnerAdapter(agents, config),
            model=config.review_model,
        )

    implementer = ImplementPhase(
        config,
        state,
        workspaces,
        agents,
        prs,
        store,
        stop_event,
        run_recorder=run_recorder,
        harness_insights=harness_insights,
        beads_manager=beads_mgr,
        active_issues_cb=active_issues_cb,
        transcript_summarizer=summarizer,
        precondition_gate=precondition_gate,
        spec_reviewer=spec_reviewer,
        # #11568: the same single IssueCache (see #8790 F1 note above) sizes
        # the implement timeout from triage's complexity score.
        issue_cache=issue_cache,
    )

    from metrics_manager import MetricsManager

    metrics_manager = MetricsManager(config, state, prs, event_bus)
    from phase_utils import MemorySuggester

    conflict_resolver = MergeConflictResolver(
        config=config,
        workspaces=workspaces,
        agents=agents,
        prs=prs,
        event_bus=event_bus,
        state=state,
        summarizer=summarizer,
        suggest_memory=MemorySuggester(config),
    )
    pr_unsticker = PRUnsticker(
        config,
        state,
        event_bus,
        prs,
        agents,
        workspaces,
        fetcher,
        hitl_runner=hitl_runner,
        stop_event=stop_event,
        resolver=conflict_resolver,
        troubleshooting_store=troubleshooting_store,
        store=store,
        credentials=credentials,
    )
    retrospective_queue = RetrospectiveQueue(
        config.repo_memory_dir / "retrospective_queue.jsonl",
    )
    retrospective = RetrospectiveCollector(
        config,
        state,
        prs,
        queue=retrospective_queue,
        observability=observability,
    )
    ac_generator = AcceptanceCriteriaGenerator(
        config, prs, event_bus, runner=subprocess_runner, credentials=credentials
    )
    verification_judge = VerificationJudge(
        config, event_bus, runner=subprocess_runner, credentials=credentials
    )
    baseline_policy = BaselinePolicy(
        config=config,
        state=state,
        event_bus=event_bus,
    )
    post_merge_handler = PostMergeHandler(
        config=config,
        state=state,
        prs=prs,
        event_bus=event_bus,
        ac_generator=ac_generator,
        retrospective=retrospective,
        verification_judge=verification_judge,
        epic_checker=epic_checker,
        update_bg_worker_status=callbacks.update_status,
        epic_manager=epic_manager,
        store=store,
        wiki_store=repo_wiki_store,
        wiki_compiler=wiki_compiler,
    )
    # ReviewInsightStore shared between AgentRunner and ReviewPhase
    review_insights = ReviewInsightStore(
        config.repo_memory_dir,
        observability=observability,
    )
    # ``_insights`` is internal AgentRunner plumbing not part of any Port.
    # Sandbox runners (FakeAgentRunner) don't implement it — gate the
    # assignment on attribute presence so override runners remain functional.
    if hasattr(agents, "_insights"):
        agents._insights = review_insights

    reviewer = ReviewPhase(
        config,
        state,
        workspaces,
        reviewers,
        prs,
        stop_event,
        store,
        conflict_resolver,
        post_merge_handler,
        event_bus=event_bus,
        harness_insights=harness_insights,
        review_insights=review_insights,
        update_bg_worker_status=callbacks.update_status,
        baseline_policy=baseline_policy,
        active_issues_cb=active_issues_cb,
        transcript_summarizer=summarizer,
        wiki_store=repo_wiki_store,
        wiki_compiler=wiki_compiler,
        retrospective_queue=retrospective_queue,
        precondition_gate=precondition_gate,
        issue_cache=issue_cache,
    )

    # Background loops — shared deps bundled into a single LoopDeps object
    loop_deps = LoopDeps(
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=callbacks.update_status,
        enabled_cb=callbacks.is_enabled,
        interval_cb=callbacks.get_interval,
        timeout_cb=callbacks.get_watchdog_timeout,
    )
    pr_unsticker_loop = PRUnstickerLoop(config, pr_unsticker, prs, deps=loop_deps)
    merge_state_watcher_loop = MergeStateWatcherLoop(
        config=config, prs=prs, deps=loop_deps
    )
    report_issue_loop = ReportIssueLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
        runner=subprocess_runner,
        credentials=credentials,
    )
    epic_monitor_loop = EpicMonitorLoop(
        config=config, epic_manager=epic_manager, deps=loop_deps
    )
    epic_sweeper_loop = EpicSweeperLoop(
        config=config,
        fetcher=fetcher,
        prs=prs,
        state=state,
        deps=loop_deps,
    )
    # ``is_in_pipeline`` is internal IssueStore plumbing not part of
    # IssueStorePort. Sandbox stores (FakeIssueStore) don't implement it
    # — fall back to a never-in-pipeline lambda so loop construction
    # succeeds with override stores. Real IssueStore retains its method.
    is_in_pipeline_cb = getattr(store, "is_in_pipeline", lambda _n: False)
    workspace_gc_loop = WorkspaceGCLoop(  # noqa: F841
        config=config,
        workspaces=workspaces,
        prs=prs,
        state=state,
        deps=loop_deps,
        is_in_pipeline_cb=is_in_pipeline_cb,
        credentials=credentials,
    )
    runs_gc_loop = RunsGCLoop(config=config, run_recorder=run_recorder, deps=loop_deps)
    adr_reviewer = ADRCouncilReviewer(
        config, event_bus, subprocess_runner, credentials=credentials
    )
    adr_reviewer_loop = ADRReviewerLoop(
        config=config, adr_reviewer=adr_reviewer, deps=loop_deps
    )
    health_monitor_loop = HealthMonitorLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        prs=prs,
        retrospective_queue=retrospective_queue,
        state=state,
        observability=observability,
        credentials=credentials,
        # bg_workers is injected post-construction by the orchestrator
        # (chicken-and-egg with BGWorkerManager); see orchestrator.py.
    )
    dependabot_merge_loop = DependabotMergeLoop(  # noqa: F841
        config=config,
        cache=gh_cache,
        prs=prs,
        state=state,
        deps=loop_deps,
    )
    staging_promotion_loop = StagingPromotionLoop(  # noqa: F841
        config=config,
        prs=prs,
        deps=loop_deps,
        state=state,
    )
    staging_bisect_loop = StagingBisectLoop(  # noqa: F841
        config=config,
        prs=prs,
        deps=loop_deps,
        state=state,
    )
    stale_issue_loop = StaleIssueLoop(
        config=config,
        prs=prs,
        state=state,
        deps=loop_deps,
        observability=observability,
    )
    triage_retry_loop = TriageRetryLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
        github_cache=gh_cache,
    )
    convergence_oscillation_loop = ConvergenceOscillationLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
    )
    gh_cache_loop = GitHubCacheLoop(config, gh_cache, deps=loop_deps)  # noqa: F841
    from dedup_store import DedupStore  # noqa: PLC0415

    log_ingest_dedup = DedupStore(
        "log_ingest_filed_sighashes",
        config.data_root / "dedup" / "log_ingest_filed.json",
    )
    log_ingest_loop = LogIngestLoop(
        config=config,
        prs=prs,
        deps=loop_deps,
        dedup=log_ingest_dedup,
        state=state,
    )
    stale_issue_gc_loop = StaleIssueGCLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        state=state,
        deps=loop_deps,
    )
    gate_health_loop = GateHealthLoop(
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
    # Phase 2 (#10027) real-red dispatch reuses the SAME AutoAgentRunner
    # subprocess wrapper as SandboxFailureFixerLoop / DisturbanceDampenerLoop
    # (no new runner code; ADR-0050 envelope applies to all three).
    from preflight.auto_agent_runner import AutoAgentRunner

    pr_red_repair_runner = AutoAgentRunner(config=config, event_bus=event_bus)
    pr_red_repair_human_pr_dedup = DedupStore(
        "pr_red_repair_human_pointer",
        config.data_root / "dedup" / "pr_red_repair_human_pointer.json",
    )
    pr_red_repair_loop = PrRedRepairLoop(
        config=config,
        pr_manager=prs,
        state=state,
        deps=loop_deps,
        runner=pr_red_repair_runner,
        workspaces=workspaces,
        human_pr_dedup=pr_red_repair_human_pr_dedup,
    )
    erosion_metrics_dedup = DedupStore(
        "erosion_metrics_filed_findings",
        config.data_root / "dedup" / "erosion_metrics_filed.json",
    )
    erosion_metrics_loop = ErosionMetricsLoop(
        config=config,
        pr_manager=prs,
        state=state,
        dedup=erosion_metrics_dedup,
        deps=loop_deps,
    )
    fail_open_monitor_dedup = DedupStore(
        "fail_open_monitor_filed_breaches",
        config.data_root / "dedup" / "fail_open_monitor_filed.json",
    )
    fail_open_monitor_loop = FailOpenMonitorLoop(
        config=config,
        pr_manager=prs,
        dedup=fail_open_monitor_dedup,
        deps=loop_deps,
    )
    escape_ledger_dedup = DedupStore(
        "escape_ledger_recorded",
        config.data_root / "dedup" / "escape_ledger.json",
    )
    escape_ledger_loop = EscapeLedgerLoop(
        config=config,
        pr_manager=prs,
        state=state,
        dedup=escape_ledger_dedup,
        deps=loop_deps,
    )
    intervention_tally_dedup = DedupStore(
        "intervention_tally_recorded",
        config.data_root / "dedup" / "intervention_tally.json",
    )
    intervention_tally_loop = InterventionTallyLoop(
        config=config,
        state=state,
        dedup=intervention_tally_dedup,
        deps=loop_deps,
    )
    sampled_audit_dedup = DedupStore(
        "sampled_audit_filed_findings",
        config.data_root / "dedup" / "sampled_audit.json",
    )
    sampled_audit_loop = SampledAuditLoop(
        config=config,
        pr_manager=prs,
        state=state,
        dedup=sampled_audit_dedup,
        deps=loop_deps,
    )
    second_order_vitals_loop = SecondOrderVitalsLoop(
        config=config,
        pr_manager=prs,
        state=state,
        deps=loop_deps,
    )
    issue_refinement_dedup = DedupStore(
        "issue_refinement",
        config.data_root / "dedup" / "issue_refinement.json",
    )
    issue_refinement_loop = IssueRefinementLoop(
        config=config,
        state=state,
        pr_manager=prs,
        dedup=issue_refinement_dedup,
        deps=loop_deps,
    )
    ci_monitor_loop = CIMonitorLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
    security_patch_loop = SecurityPatchLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        state=state,
        deps=loop_deps,
    )
    repo_wiki_loop = RepoWikiLoop(
        config=config,
        wiki_store=repo_wiki_store,
        deps=loop_deps,
        wiki_compiler=wiki_compiler,
        state=state,
        credentials=credentials,
        tribal_store=tribal_wiki_store,
    )
    diagram_loop = DiagramLoop(
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
    cost_budget_watcher_loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=prs,
        state=state,
        deps=loop_deps,
    )
    pricing_refresh_loop = PricingRefreshLoop(
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )
    diagnostic_runner = DiagnosticRunner(config=config, event_bus=event_bus)
    diagnostic_loop = DiagnosticLoop(
        config=config,
        runner=diagnostic_runner,
        prs=prs,
        state=state,
        deps=loop_deps,
        workspaces=workspaces,
    )
    retrospective_loop = RetrospectiveLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        retrospective=retrospective,
        insights=review_insights,
        queue=retrospective_queue,
        prs=prs,
    )
    # PrinciplesAuditLoop runs make audit-json once per HydraFlow-self and once
    # per managed repo in a single cycle; multiple repos can push a cycle past
    # the 2-hour default watchdog. Give it the LLM bound (4 h) via timeout_cb
    # instead of setting LONG_LLM_CYCLE=True in the protected loop file (#9639).
    _principles_audit_deps = LoopDeps(
        event_bus=loop_deps.event_bus,
        stop_event=loop_deps.stop_event,
        status_cb=loop_deps.status_cb,
        enabled_cb=loop_deps.enabled_cb,
        sleep_fn=loop_deps.sleep_fn,
        interval_cb=loop_deps.interval_cb,
        timeout_cb=lambda _: config.loop_watchdog_llm_seconds,
    )
    principles_audit_loop = PrinciplesAuditLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=_principles_audit_deps,
    )
    flake_tracker_dedup = DedupStore(
        "flake_tracker",
        config.data_root / "dedup" / "flake_tracker.json",
    )
    flake_tracker_loop = FlakeTrackerLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=flake_tracker_dedup,
        deps=loop_deps,
        github_cache=gh_cache,
    )
    skill_prompt_eval_dedup = DedupStore(
        "skill_prompt_eval",
        config.data_root / "dedup" / "skill_prompt_eval.json",
    )
    skill_prompt_eval_loop = SkillPromptEvalLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=skill_prompt_eval_dedup,
        deps=loop_deps,
    )
    fake_coverage_auditor_dedup = DedupStore(
        "fake_coverage_auditor",
        config.data_root / "dedup" / "fake_coverage_auditor.json",
    )
    fake_coverage_auditor_loop = FakeCoverageAuditorLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=fake_coverage_auditor_dedup,
        deps=loop_deps,
    )

    adr_touchpoint_auditor_dedup = DedupStore(
        "adr_touchpoint_auditor",
        config.data_root / "dedup" / "adr_touchpoint_auditor.json",
    )
    adr_touchpoint_auditor_loop = AdrTouchpointAuditorLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=adr_touchpoint_auditor_dedup,
        adr_index=ADRIndex(config.repo_root / "docs" / "adr"),
        deps=loop_deps,
    )

    # AdrDriftResolverLoop (#9976) — sibling of the auditor above: reads its
    # rollup state, resolves the ~70% false-positive drift findings via one
    # TRIAGE LLM call, never touches the auditor's own detection code.
    adr_drift_resolver_dedup = DedupStore(
        "adr_drift_resolver",
        config.data_root / "dedup" / "adr_drift_resolver.json",
    )
    adr_drift_resolver_llm_client = AdrDriftResolverLLMClient(
        runner=subprocess_runner,
        config=config,
        tool=config.adr_drift_resolver_tool,
        model=config.adr_drift_resolver_model,
        timeout=config.adr_drift_resolver_timeout,
        provider=config.adr_drift_resolver_provider,
    )
    adr_drift_resolver_loop = AdrDriftResolverLoop(
        config=config,
        state=state,
        pr_manager=prs,
        dedup=adr_drift_resolver_dedup,
        adr_index=ADRIndex(config.repo_root / "docs" / "adr"),
        triage=AdrDriftTriageLLM(client=adr_drift_resolver_llm_client),
        deps=loop_deps,
    )

    adr_conformance_dedup = DedupStore(
        "adr_conformance",
        config.data_root / "dedup" / "adr_conformance.json",
    )
    adr_conformance_loop = AdrConformanceLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=adr_conformance_dedup,
        adr_index=ADRIndex(config.repo_root / "docs" / "adr"),
        runner=SubprocessConformanceRunner(),
        deps=loop_deps,
    )

    _auto_tighten_metrics = config.repo_data_root / "metrics"
    _auto_tighten_cov_jsonl = _auto_tighten_metrics / "coverage.jsonl"
    # CoverageAdapter's methods are typed over concrete `float` (the only
    # Measurement shape it deals with) rather than the full `Measurement`
    # union the RatchetAdapter Protocol declares, so pyright sees it as
    # narrower-than-the-protocol at the list-literal boundary. Runtime-safe
    # (CoverageAdapter is a real structural match; `RatchetAdapter` is
    # `@runtime_checkable`) — the cast documents this rather than papering
    # over an actual mismatch.
    _auto_tighten_adapters = cast(
        "list[RatchetAdapter]",
        [
            CoverageAdapter(
                coverage_jsonl=_auto_tighten_cov_jsonl,
                margin=config.auto_tighten_coverage_margin,
            )
        ],
    )
    auto_tighten_loop = AutoTightenLoop(  # noqa: F841
        config=config,
        state=state,
        deps=loop_deps,
        adapters=_auto_tighten_adapters,
        ingestor=CoverageIngestor(
            _auto_tighten_cov_jsonl,
            fetch_latest=make_gh_coverage_fetch(config),
        ),
        attribution=AttributionResolver(
            list_merged_prs=make_gh_merged_pr_lister(config)
        ),
        pr_author=TighteningPrAuthor(
            repo_root=config.repo_root,
            base=config.base_branch(),
            open_pr_exists=make_gh_open_pr_exists(config),
        ),
        observation_store=ObservationStore(_auto_tighten_metrics / "tighten.jsonl"),
    )

    branch_protection_auditor_dedup = DedupStore(
        "branch_protection_auditor",
        config.data_root / "dedup" / "branch_protection_auditor.json",
    )
    _bp_canonical_dir = config.repo_root / "docs" / "standards" / "branch_protection"

    async def _branch_protection_audit() -> AuditReport:
        # Offload the blocking gh calls so the event loop is not stalled.
        return await asyncio.to_thread(
            audit_repo,
            config.repo,
            _bp_canonical_dir,
            fetch_rulesets=gh_fetch_rulesets,
            fetch_legacy_protection=gh_fetch_legacy_protection,
        )

    branch_protection_auditor_loop = BranchProtectionAuditorLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        dedup=branch_protection_auditor_dedup,
        deps=loop_deps,
        auditor=_branch_protection_audit,
    )

    # Tier-2 goal supervisor (ADR-0124). ``state`` powers the read-only health
    # snapshot's per-loop heartbeat reads; ``bg_workers`` (post-registry) powers
    # the restart nudge and is injected by the orchestrator via set_bg_workers.
    goal_supervisor_loop = GoalSupervisorLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        state=state,
    )

    rails_drift_caretaker_dedup = DedupStore(
        "rails_drift_caretaker",
        config.data_root / "dedup" / "rails_drift_caretaker.json",
    )
    rails_drift_caretaker_loop = RailsDriftCaretakerLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        dedup=rails_drift_caretaker_dedup,
        deps=loop_deps,
        auditor=build_rails_auditor(config),
    )

    gate_activator_dedup = DedupStore(
        "gate_activator",
        config.data_root / "dedup" / "gate_activator.json",
    )

    async def _detect_gate_activations() -> list[ActivationProposal]:
        # Offload the contract parse + workflow/Makefile reads off the loop.
        return await asyncio.to_thread(check_gate_activation, config.repo_root)

    gate_activator_loop = GateActivatorLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        dedup=gate_activator_dedup,
        deps=loop_deps,
        detector=_detect_gate_activations,
    )

    memory_backlog_dedup = DedupStore(
        "memory_backlog",
        config.data_root / "dedup" / "memory_backlog.json",
    )
    memory_backlog_loop = MemoryBacklogLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=memory_backlog_dedup,
        deps=loop_deps,
    )

    rc_budget_dedup = DedupStore(
        "rc_budget",
        config.data_root / "dedup" / "rc_budget.json",
    )
    rc_budget_loop = RCBudgetLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=rc_budget_dedup,
        deps=loop_deps,
        github_cache=gh_cache,
    )

    wiki_rot_dedup = DedupStore(
        "wiki_rot_detector",
        config.data_root / "dedup" / "wiki_rot_detector.json",
    )
    wiki_rot_detector_loop = WikiRotDetectorLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=wiki_rot_dedup,
        wiki_store=repo_wiki_store,
        deps=loop_deps,
    )

    trust_fleet_sanity_dedup = DedupStore(
        "trust_fleet_sanity",
        config.data_root / "dedup" / "trust_fleet_sanity.json",
    )
    trust_fleet_sanity_loop = TrustFleetSanityLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=trust_fleet_sanity_dedup,
        event_bus=event_bus,
        deps=loop_deps,
        # bg_workers is injected post-construction by the orchestrator
        # (BGWorkerManager takes the loop registry, so it must be built
        # after all loops).
    )

    contract_refresh_loop = ContractRefreshLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        prs=prs,
        state=state,
    )

    # LiveCorpusReplayLoop (#8786 Phase 2). Consumes the shadow corpus,
    # diffs samples against fake-adapter outputs via registered dispatchers,
    # files hydraflow-find issues on drift, escalates to hitl-escalation
    # after ``live_corpus_max_drift_attempts`` consecutive ticks.
    _live_corpus_replay_dedup = DedupStore(
        "live_corpus_replay",
        config.data_root / "dedup" / "live_corpus_replay.json",
    )
    _live_corpus_replay_loop = LiveCorpusReplayLoop(
        config=config,
        corpus=shadow_corpus,
        pr_manager=prs,
        dedup=_live_corpus_replay_dedup,
        state=state,
        deps=loop_deps,
    )
    # Phase 5: register the Pydantic shape dispatcher for gh JSON output.
    # Validates sample.stdout against contracts.shapes models — shape
    # drift in real gh (renamed/removed/typed-differently fields, new
    # enum values) fires immediately on the next tick.
    # One coverage predicate per (adapter, command) key: when a second
    # validator is chained under ("github", "gh") — e.g. the #8699
    # gh_mutation_validator — OR-compose its args-coverage into this
    # single ``covers=`` predicate (gh_shape_covers(args) or
    # gh_mutation_covers(args)), else record-time pruning drops the
    # samples the new validator needs (#9803 guard).
    from contracts.shape_dispatchers import gh_shape_covers, gh_shape_validator

    _live_corpus_replay_loop.register(
        "github", "gh", gh_shape_validator, covers=gh_shape_covers
    )
    # #9633: drop no-opinion samples at record time so they never consume
    # per-adapter LRU budget. The corpus is constructed before the loop
    # exists, so the registry-derived predicate late-binds here. Dropping
    # is reversible — the corpus self-refreshes within one interval once
    # dispatcher coverage expands.
    if config.shadow_corpus_coverage_pruning_enabled:
        shadow_corpus.set_coverage_predicate(_live_corpus_replay_loop.covers)

    # Phase 9: thread the live dispatcher registry into the auditor so
    # the cassette retirement audit can flag baseline cassettes whose
    # shape is now dispatcher-covered.
    fake_coverage_auditor_loop.set_retirement_keys_cb(
        _live_corpus_replay_loop.registered_shapes
    )

    corpus_learning_dedup = DedupStore(
        "corpus_learning",
        config.data_root / "dedup" / "corpus_learning.json",
    )
    corpus_learning_loop = CorpusLearningLoop(  # noqa: F841
        config=config,
        prs=prs,
        dedup=corpus_learning_dedup,
        deps=loop_deps,
        state=state,
    )

    detector_calibration_loop = DetectorCalibrationLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
        github_cache=gh_cache,
    )

    gateway_coverage_loop = GatewayCoverageLoop(
        config=config,
        state=state,
        deps=loop_deps,
    )

    auto_agent_audit_store = PreflightAuditStore(config.data_root)
    auto_agent_preflight_loop = AutoAgentPreflightLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        wiki_store=repo_wiki_store,
        audit_store=auto_agent_audit_store,
        deps=loop_deps,
        workspaces=workspaces,
        # ADR-0105 decompose-to-converge: reuse the shared epic_manager
        # (register_epic writes through the same persisted state + event bus
        # as the rest of the system) and the shared subprocess_runner (so
        # the council's LLM calls route through the same docker/host dial
        # as every other loop) rather than constructing loop-local copies.
        epic_manager=epic_manager,
        runner=subprocess_runner,
    )

    # Sandbox-tier auto-fixer reuses the AutoAgentRunner subprocess wrapper
    # (no new runner code; ADR-0050 envelope applies to both loops).
    from preflight.auto_agent_runner import AutoAgentRunner

    sandbox_failure_fixer_runner = AutoAgentRunner(config=config, event_bus=event_bus)
    sandbox_failure_fixer_loop = SandboxFailureFixerLoop(  # noqa: F841
        config=config,
        state=state,
        deps=loop_deps,
        prs=prs,
        runner=sandbox_failure_fixer_runner,
        workspaces=workspaces,
    )

    # Disturbance dampener burn-down actuator (ADR-0095, Pattern A). Reuses
    # the same AutoAgentRunner subprocess wrapper as the sandbox fixer above.
    disturbance_dampener_runner = AutoAgentRunner(config=config, event_bus=event_bus)
    disturbance_dampener_dedup = DedupStore(
        "disturbance_dampener",
        config.data_root / "dedup" / "disturbance_dampener.json",
    )
    disturbance_dampener_loop = DisturbanceDampenerLoop(  # noqa: F841
        config=config,
        state=state,
        prs=prs,
        dedup=disturbance_dampener_dedup,
        deps=loop_deps,
        runner=disturbance_dampener_runner,
    )

    # Human-on-the-loop continuous steering sensor (ADR-0099 #4). Reads
    # the full-pipeline active-issue set straight off the IssueStore
    # (queued/in-flight/active — every phase from triage through HITL),
    # not just the narrower implement/review/HITL-in-flight set that
    # ``state.get_active_issue_numbers`` exposes via the orchestrator's
    # ``_sync_active_issue_numbers``. This ensures a directive posted on
    # an issue in triage/discover/shape/plan is sensed too, matching the
    # actuator's own enumeration (``store.get_active_issues()``).
    human_steering_loop = HumanSteeringLoop(
        config=config,
        state=state,
        prs=prs,
        deps=loop_deps,
        active_issues_cb=lambda: list(store.get_active_issues().keys()),
    )

    # Term-Proposer (ADR-0054). Production adapters wire the loop to:
    # - ClaudeCLIClient: shells out to `claude -p` via SubprocessRunner,
    #   mirroring `wiki_compiler.WikiCompiler._call_model`.
    # - OpenAutoPRBotPRPort: writes term files INTO an ephemeral worktree and
    #   delegates to `auto_pr.generate_and_open_pr_async` for the commit →
    #   push → `gh pr create` flow — repo_root is never mutated (#9539).
    #   `auto_merge=False` — DependabotMergeLoop handles auto-merge once the
    #   PR carries `hydraflow-ul-proposed`.
    from term_proposer_llm import TermProposerLLM  # noqa: PLC0415
    from term_proposer_loop import TermProposerLoop  # noqa: PLC0415
    from term_proposer_runtime import (  # noqa: PLC0415
        ClaudeCLIClient,
        OpenAutoPRBotPRPort,
    )

    label_drift_watcher_loop = LabelDriftWatcherLoop(  # noqa: F841
        config=config,
        pr_manager=prs,
        deps=loop_deps,
    )

    term_proposer_claude_client = ClaudeCLIClient(
        runner=subprocess_runner,
        config=config,
        tool=config.term_proposer_tool,
        model=config.term_proposer_model,
        timeout=config.term_proposer_timeout,
        provider=config.term_proposer_provider,
    )
    term_proposer_llm = TermProposerLLM(client=term_proposer_claude_client)
    term_proposer_pr_port = OpenAutoPRBotPRPort(
        repo_root=config.repo_root,
        gh_token=credentials.gh_token,
        # Route UL bot PRs to the active integration branch (staging when
        # enabled, else main) per ADR-0042. Shared by all UL loops
        # (term-proposer/-pruner, edge-proposer, entry-evidence).
        base=config.base_branch(),
    )
    term_proposer_loop = TermProposerLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        llm=term_proposer_llm,
        pr_port=term_proposer_pr_port,
        repo_root=config.repo_root,
        dedup_path=config.data_root / "dedup" / "term_proposer.json",
    )

    # Term-Pruner (ADR-0057). Reuses the proposer's PR port adapter — both loops
    # open auto-merging bot PRs via OpenAutoPRBotPRPort (stateless, shareable).
    from term_pruner_loop import TermPrunerLoop  # noqa: PLC0415

    term_pruner_loop = TermPrunerLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        pr_port=term_proposer_pr_port,
        repo_root=config.repo_root,
    )

    # Edge-Proposer (ADR-0058). Reuses the proposer's PR port adapter for the
    # same reason as the pruner: structural bot PRs share the same auto-merge
    # plumbing.
    from edge_proposer_loop import EdgeProposerLoop  # noqa: PLC0415

    edge_proposer_loop = EdgeProposerLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        pr_port=term_proposer_pr_port,
        repo_root=config.repo_root,
    )

    # Entry-Evidence (ADR-0062). Reuses the proposer's LLM client and PR port —
    # both LLM-driven term-graph maintenance jobs share the same auto-merge
    # plumbing and rate-limited Claude CLI subprocess.
    from entry_evidence_loop import EntryEvidenceLoop  # noqa: PLC0415

    entry_evidence_loop = EntryEvidenceLoop(  # noqa: F841
        config=config,
        deps=loop_deps,
        llm=term_proposer_claude_client,
        pr_port=term_proposer_pr_port,
        repo_root=config.repo_root,
        dedup_path=config.data_root / "dedup" / "entry_evidence.json",
    )

    _fitness_issue_fetcher = _make_fitness_issue_fetcher(prs)
    fitness_scorecard_loop = FitnessScorecardLoop(
        config=config,
        deps=loop_deps,
        issue_fetcher=_fitness_issue_fetcher,
        repo_root=config.repo_root,
    )

    return ServiceRegistry(
        observability=observability,
        workspaces=workspaces,
        subprocess_runner=subprocess_runner,
        agents=agents,
        planners=planners,
        prs=prs,
        reviewers=reviewers,
        hitl_runner=hitl_runner,
        triage=triage,
        summarizer=summarizer,
        fetcher=fetcher,
        store=store,
        phase_store=phase_store,
        issue_cache=issue_cache,
        triager=triager,
        discover_runner=discover_runner,
        shape_runner=shape_runner,
        planner_phase=planner_phase,
        hitl_phase=hitl_phase,
        implementer=implementer,
        reviewer=reviewer,
        run_recorder=run_recorder,
        metrics_manager=metrics_manager,
        pr_unsticker=pr_unsticker,
        retrospective=retrospective,
        ac_generator=ac_generator,
        verification_judge=verification_judge,
        epic_checker=epic_checker,
        epic_manager=epic_manager,
        pr_unsticker_loop=pr_unsticker_loop,
        merge_state_watcher_loop=merge_state_watcher_loop,
        report_issue_loop=report_issue_loop,
        epic_monitor_loop=epic_monitor_loop,
        epic_sweeper_loop=epic_sweeper_loop,
        workspace_gc_loop=workspace_gc_loop,
        runs_gc_loop=runs_gc_loop,
        adr_reviewer_loop=adr_reviewer_loop,
        health_monitor_loop=health_monitor_loop,
        dependabot_merge_loop=dependabot_merge_loop,
        staging_promotion_loop=staging_promotion_loop,
        staging_bisect_loop=staging_bisect_loop,
        stale_issue_loop=stale_issue_loop,
        github_cache=gh_cache,
        github_cache_loop=gh_cache_loop,
        log_ingest_loop=log_ingest_loop,
        stale_issue_gc_loop=stale_issue_gc_loop,
        gate_health_loop=gate_health_loop,
        pr_red_repair_loop=pr_red_repair_loop,
        erosion_metrics_loop=erosion_metrics_loop,
        fail_open_monitor_loop=fail_open_monitor_loop,
        escape_ledger_loop=escape_ledger_loop,
        intervention_tally_loop=intervention_tally_loop,
        sampled_audit_loop=sampled_audit_loop,
        second_order_vitals_loop=second_order_vitals_loop,
        issue_refinement_loop=issue_refinement_loop,
        ci_monitor_loop=ci_monitor_loop,
        branch_protection_auditor_loop=branch_protection_auditor_loop,
        goal_supervisor_loop=goal_supervisor_loop,
        rails_drift_caretaker_loop=rails_drift_caretaker_loop,
        gate_activator_loop=gate_activator_loop,
        security_patch_loop=security_patch_loop,
        repo_wiki_store=repo_wiki_store,
        repo_wiki_loop=repo_wiki_loop,
        diagnostic_loop=diagnostic_loop,
        retrospective_loop=retrospective_loop,
        retrospective_queue=retrospective_queue,
        principles_audit_loop=principles_audit_loop,
        flake_tracker_loop=flake_tracker_loop,
        skill_prompt_eval_loop=skill_prompt_eval_loop,
        fake_coverage_auditor_loop=fake_coverage_auditor_loop,
        adr_touchpoint_auditor_loop=adr_touchpoint_auditor_loop,
        adr_drift_resolver_loop=adr_drift_resolver_loop,
        adr_conformance_loop=adr_conformance_loop,
        auto_tighten_loop=auto_tighten_loop,
        memory_backlog_loop=memory_backlog_loop,
        rc_budget_loop=rc_budget_loop,
        wiki_rot_detector_loop=wiki_rot_detector_loop,
        trust_fleet_sanity_loop=trust_fleet_sanity_loop,
        label_drift_watcher_loop=label_drift_watcher_loop,
        contract_refresh_loop=contract_refresh_loop,
        corpus_learning_loop=corpus_learning_loop,
        auto_agent_preflight_loop=auto_agent_preflight_loop,
        gateway_coverage_loop=gateway_coverage_loop,
        detector_calibration_loop=detector_calibration_loop,
        sandbox_failure_fixer_loop=sandbox_failure_fixer_loop,
        disturbance_dampener_loop=disturbance_dampener_loop,
        human_steering_loop=human_steering_loop,
        diagram_loop=diagram_loop,
        cost_budget_watcher_loop=cost_budget_watcher_loop,
        pricing_refresh_loop=pricing_refresh_loop,
        term_proposer_loop=term_proposer_loop,
        term_pruner_loop=term_pruner_loop,
        edge_proposer_loop=edge_proposer_loop,
        entry_evidence_loop=entry_evidence_loop,
        live_corpus_replay_loop=_live_corpus_replay_loop,
        triage_retry_loop=triage_retry_loop,
        convergence_oscillation_loop=convergence_oscillation_loop,
        fitness_scorecard_loop=fitness_scorecard_loop,
    )
