"""Background worker loop — PRUnsticker intake for settled CI reds (#10027).

PHASE 1 ONLY: infra-flake retrier. An open PR's CI settles red and, tonight
after tonight, someone has to look at it — the most-repeated operator
action across the 2026-07-19/20 overnight session, with no automated
owner. This caretaker (ADR-0029) detects a **settled-red** open PR,
classifies the failure as an infra-flake using the four signals proven
that session, and issues a bounded ``gh run rerun --failed``. Real-red
diagnosis + auto-agent dispatch is Phase 2 — explicitly out of scope here;
a run whose failure doesn't classify as an infra-flake is left untouched.

Mirrors :class:`gate_health_loop.GateHealthLoop`'s structure (closest
existing caretaker with PR/run/job read Port methods) and reuses its
``list_workflow_runs`` + ``get_workflow_run_jobs`` reads rather than adding
a new per-PR ``statusCheckRollup`` fetch: ``list_workflow_runs`` already
carries each run's ``pr_number``, and ``get_workflow_run_jobs`` now also
carries each job's ``status`` (added for #10027) alongside its
``conclusion`` — together they form the same "rollup" shape (per-check
lifecycle + outcome) the settled-red predicate needs, without a new
``gh`` call. The one genuinely new Port method is the write side,
``PRPort.rerun_workflow_failed`` (triplet: Protocol + ``PRManager`` +
``FakeGitHub`` + cassette).

Settled-red predicate (:func:`is_settled_red`) — the load-bearing one:
failures present AND nothing pending remains. The proven trap from
tonight: after a rerun, an entry can still report its OLD (pre-rerun)
``conclusion`` while its ``status`` has already flipped back to
QUEUED/IN_PROGRESS — ``status`` is checked FIRST and is authoritative
regardless of what ``conclusion`` says, so a mid-rerun PR never
double-fires. See ``tests/test_pr_red_repair_loop.py`` for the pinned
regression case.

Bounded rerun attempts are tracked via :class:`models.ConvergenceLedger`
(stage ``"pr_red_rerun"``, keyed by PR number) — the same durable,
restart-surviving substrate ``SandboxFailureFixerLoop`` uses for its
bounded-attempt pattern (see ``state/_pr_red_repair.py``). Budget
exhaustion escalates via :class:`rollup_issue_manager.RollupIssueManager`
(one open issue per PR, auto-closed once the PR is no longer settled-red
or is no longer open — #10022 discipline).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import FitnessContext, FitnessKind, LoopFitness
from rollup_issue_manager import RollupIssueManager

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.pr_red_repair")

# Repo-wide workflow-run window scanned each cycle. Generous enough to
# cover every open PR's most recent push in normal operation; mirrors
# GateHealthLoop's default ``gate_health_run_window`` order of magnitude.
_RUN_WINDOW = 100

# Check/job conclusions that count as "red" (statusCheckRollup/Jobs-API
# vocabulary, lower-cased — matches GateHealthLoop's own convention).
_FAILING_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "action_required", "stale"}
)

# Step-name patterns for the "failed setup step" infra-flake signal
# (#10027): the environment never got the chance to run user code, so a
# failure here is infrastructure, not the PR's diff.
_SETUP_STEP_PATTERNS = (
    re.compile(r"^Set up\b", re.IGNORECASE),
    re.compile(r"astral-sh/setup-", re.IGNORECASE),
    re.compile(r"actions/checkout", re.IGNORECASE),
)

REASON_CANCELLED = "cancelled_run"
REASON_ZERO_FAILED_STEPS = "zero_failed_steps"
REASON_SETUP_ACTION = "setup_action_step"
REASON_VANISHED_LOGS = "vanished_logs"

_ROLLUP_NAMESPACE = "pr_red_repair"


def is_settled_red(rollup: list[dict[str, Any]]) -> bool:
    """True when *rollup* has settled on red — nothing pending remains.

    "Settled" means every entry's ``status`` reads ``"completed"`` — the
    proven trap (#10027): after ``gh run rerun --failed``, an entry can
    keep reporting its OLD (pre-rerun) ``conclusion`` (e.g. ``"failure"``)
    while ``status`` has already flipped back to ``"queued"``/
    ``"in_progress"`` for the new attempt. Checking ``status`` FIRST and
    treating anything other than ``"completed"`` (including missing/
    unknown values) as "not settled" means a stale conclusion can never
    cause a false settled-red firing while attempt N+1 is still running.

    *rollup* entries: ``{"status": ..., "conclusion": ...}`` — the shape
    shared by ``PRPort.get_workflow_run_jobs`` records and GitHub's raw
    ``statusCheckRollup``. An empty rollup (no CI activity yet) is never
    settled-red.
    """
    if not rollup:
        return False
    has_failure = False
    for entry in rollup:
        status = str(entry.get("status") or "").strip().lower()
        if status != "completed":
            return False
        conclusion = str(entry.get("conclusion") or "").strip().lower()
        if conclusion in _FAILING_CONCLUSIONS:
            has_failure = True
    return has_failure


def _is_setup_step(name: str) -> bool:
    return any(pattern.search(name) for pattern in _SETUP_STEP_PATTERNS)


def classify_infra_flake_job(job: dict[str, Any], *, log_text: str = "") -> str | None:
    """Classify one FAILED job as an infra-flake, or ``None`` (real red).

    Pure function over one job record (``{"conclusion", "steps": [...]}``
    — the shape :func:`PRPort.get_workflow_run_jobs` returns) plus an
    optional fetched CI-log tail. Matches the four signals proven on the
    2026-07-19/20 overnight session (#10027), checked in this order:

    1. ``conclusion == "cancelled"`` — concurrency eviction / runner death.
    2. ``log_text`` contains ``"log not found"`` — vanished logs.
    3. A failed job with ZERO failed steps — the runner died before any
       step could register a failure (weird CI-infra death, not code).
    4. A failed *setup* step (``Set up …`` / ``astral-sh/setup-*`` /
       ``actions/checkout``) — the environment never ran user code.

    Returns ``None`` for anything else, including a passing job (Phase 2
    — real-red diagnosis — is explicitly out of scope for this loop).
    """
    conclusion = str(job.get("conclusion") or "").strip().lower()
    if conclusion == "cancelled":
        return REASON_CANCELLED
    if conclusion not in _FAILING_CONCLUSIONS:
        return None
    if "log not found" in log_text.lower():
        return REASON_VANISHED_LOGS
    steps = job.get("steps") or []
    failed_steps = [
        s for s in steps if str(s.get("conclusion") or "").strip().lower() == "failure"
    ]
    if not failed_steps:
        return REASON_ZERO_FAILED_STEPS
    for step in failed_steps:
        if _is_setup_step(str(step.get("name", ""))):
            return REASON_SETUP_ACTION
    return None


def classify_run_infra_flake(
    failing_jobs: list[dict[str, Any]], *, log_text: str = ""
) -> str | None:
    """Classify a whole run as infra-flake — only when EVERY failing job matches.

    ``gh run rerun --failed`` reruns every failed job in the run
    indiscriminately. If even one failing job looks like a genuine
    regression (Phase 2 territory, out of scope here), the whole run is
    left alone rather than rerun — which would re-run, and risk masking,
    the real red too. Returns the first matched reason (for logging), or
    ``None`` if *failing_jobs* is empty or any job doesn't classify.
    """
    if not failing_jobs:
        return None
    reasons = [classify_infra_flake_job(j, log_text=log_text) for j in failing_jobs]
    if any(r is None for r in reasons):
        return None
    return reasons[0]


def select_latest_runs(
    runs: list[dict[str, Any]], pr_number: int
) -> dict[str, dict[str, Any]]:
    """Latest (newest ``created_at``) run per workflow name for *pr_number*.

    ``list_workflow_runs`` is repo-wide and newest-first, but not
    PR-scoped: it can list the same workflow's PR-scoped runs more than
    once across the fetched window (successive pushes). Only the newest
    per workflow reflects the PR's CURRENT check state.
    """
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        if int(run.get("pr_number", 0) or 0) != pr_number:
            continue
        workflow = str(run.get("workflow", ""))
        existing = latest.get(workflow)
        if existing is None or str(run.get("created_at", "")) > str(
            existing.get("created_at", "")
        ):
            latest[workflow] = run
    return latest


class PrRedRepairLoop(BaseBackgroundLoop):
    """Detects settled-red open PRs and bounded-reruns infra-flake CI (#10027).

    Phase 1 only: classifies four proven infra-flake signatures (cancelled
    run, zero-failed-steps job, failed setup step, vanished logs) and
    issues ``gh run rerun --failed``, capped at
    ``pr_red_rerun_max_attempts`` per PR. Budget exhaustion files one
    rollup issue per PR (auto-closed once the PR clears or closes). A red
    that does NOT classify as an infra-flake is left untouched — real-red
    auto-agent dispatch is Phase 2, explicitly out of scope.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="pr_red_repair", config=config, deps=deps)
        self._prs = pr_manager
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.pr_red_repair_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Bounded mechanical repair (rerun failed CI jobs), no proposal/
        # acceptance lifecycle of its own to score — HOUSEKEEPING per
        # ADR-0093's fitness contract (mirrors adr_conformance_loop.py).
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    def _rollups(self) -> RollupIssueManager:
        return RollupIssueManager(
            pr=self._prs,
            state=self._state,
            namespace=_ROLLUP_NAMESPACE,
            labels=["hydraflow-find"],
        )

    async def _fetch_candidates(
        self,
    ) -> tuple[list[Any], list[dict[str, Any]]] | dict[str, Any]:
        """Fetch open PRs + the repo-wide run window, or an early-exit status dict."""
        try:
            open_prs = await self._prs.list_all_open_prs()
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("PrRedRepair: list_all_open_prs failed", exc_info=True)
            return {"status": "prs_unavailable"}
        if not open_prs:
            return {"status": "no_open_prs"}

        try:
            runs = await self._prs.list_workflow_runs(limit=_RUN_WINDOW)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("PrRedRepair: list_workflow_runs failed", exc_info=True)
            return {"status": "runs_unavailable"}

        return open_prs, runs

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.pr_red_repair_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        fetched = await self._fetch_candidates()
        if isinstance(fetched, dict):
            return fetched
        open_prs, runs = fetched

        rollup_mgr = self._rollups()
        max_attempts = int(self._config.pr_red_rerun_max_attempts)

        examined: set[str] = set()
        still_red: set[str] = set()
        reran = 0
        escalated = 0
        skipped_real_red = 0

        for pr in open_prs:
            if self._stop_event.is_set():
                break

            latest_by_workflow = select_latest_runs(runs, pr.pr)
            if not latest_by_workflow:
                continue
            examined.add(str(pr.pr))

            job_rollup: list[dict[str, Any]] = []
            jobs_by_run: dict[int, list[dict[str, Any]]] = {}
            for run in latest_by_workflow.values():
                run_id = int(run.get("id", 0) or 0)
                if run_id <= 0:
                    continue
                try:
                    jobs = await self._prs.get_workflow_run_jobs(run_id)
                except Exception as exc:
                    reraise_on_credit_or_bug(exc)
                    logger.warning(
                        "PrRedRepair: jobs unavailable for run %d — skipping",
                        run_id,
                        exc_info=True,
                    )
                    jobs = []
                jobs_by_run[run_id] = jobs
                job_rollup.extend(jobs)

            if not is_settled_red(job_rollup):
                continue
            still_red.add(str(pr.pr))

            flake_run_ids: list[int] = []
            real_red = False
            log_text: str | None = None
            for run_id, jobs in jobs_by_run.items():
                failing = [
                    j
                    for j in jobs
                    if str(j.get("conclusion") or "").strip().lower()
                    in _FAILING_CONCLUSIONS
                ]
                if not failing:
                    continue
                reason = classify_run_infra_flake(failing)
                if reason is None:
                    # Ambiguous on job/step data alone — the "vanished
                    # logs" signal needs an actual log fetch. Fetched at
                    # most once per PR per cycle (lazy, shared across runs).
                    if log_text is None:
                        log_text = await self._fetch_log_text(pr.pr)
                    reason = classify_run_infra_flake(failing, log_text=log_text)
                if reason is None:
                    real_red = True
                    continue
                flake_run_ids.append(run_id)

            if real_red:
                skipped_real_red += 1
                continue
            if not flake_run_ids:
                continue

            attempts = self._state.get_pr_red_rerun_attempts(pr.pr)
            if attempts >= max_attempts:
                await self._escalate(rollup_mgr, pr, flake_run_ids, attempts)
                escalated += 1
                continue

            self._state.bump_pr_red_rerun_attempts(pr.pr)
            for run_id in flake_run_ids:
                try:
                    ok = await self._prs.rerun_workflow_failed(run_id)
                except Exception as exc:
                    reraise_on_credit_or_bug(exc)
                    ok = False
                if ok:
                    reran += 1
                else:
                    logger.warning(
                        "PrRedRepair: rerun_workflow_failed(%d) failed for PR #%d",
                        run_id,
                        pr.pr,
                    )

        closed = await self._reconcile_rollups(
            rollup_mgr,
            open_pr_numbers={str(pr.pr) for pr in open_prs},
            examined=examined,
            still_red=still_red,
        )

        return {
            "status": "ok",
            "open_prs": len(open_prs),
            "reran": reran,
            "escalated": escalated,
            "skipped_real_red": skipped_real_red,
            "closed_rollups": closed,
        }

    async def _fetch_log_text(self, pr_number: int) -> str:
        try:
            return await self._prs.fetch_ci_failure_logs(pr_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "PrRedRepair: fetch_ci_failure_logs failed for PR #%d",
                pr_number,
                exc_info=True,
            )
            return ""

    async def _escalate(
        self,
        rollup_mgr: RollupIssueManager,
        pr: Any,
        flake_run_ids: list[int],
        attempts: int,
    ) -> None:
        """File (or refresh) the budget-exhaustion rollup issue for *pr*."""
        title = f"PR #{pr.pr}: infra-flake retrier exhausted its rerun budget"
        body = (
            "## Evidence (PrRedRepairLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| PR | #{pr.pr} |\n"
            f"| branch | `{getattr(pr, 'branch', '')}` |\n"
            f"| rerun attempts | {attempts} "
            f"(cap {self._config.pr_red_rerun_max_attempts}) |\n"
            f"| flaky run ids | {sorted(flake_run_ids)} |\n\n"
            "Every bounded ``gh run rerun --failed`` attempt has been "
            "spent and the check is STILL settling red with an "
            "infra-flake signature (cancelled run / zero failed steps / "
            "failed setup step / vanished logs). This is now a "
            "human-triage case — the flake may not actually be a flake, "
            "or the underlying CI infrastructure needs a real fix.\n\n"
            "This issue auto-closes once the PR clears CI or closes "
            "(#10022 discipline).\n"
        )
        await rollup_mgr.ensure(str(pr.pr), title=title, body=body)

    async def _reconcile_rollups(
        self,
        rollup_mgr: RollupIssueManager,
        *,
        open_pr_numbers: set[str],
        examined: set[str],
        still_red: set[str],
    ) -> int:
        """Auto-close tracked rollups only on POSITIVE evidence of resolution.

        A tracked PR closes when it is no longer open, or when it was
        examined THIS cycle and found no longer settled-red. A tracked PR
        this cycle couldn't examine (no runs in the fetch window) or that
        is still settled-red stays open — resolution is never inferred
        from silence (the mass-close hazard SecurityPatchLoop's
        docstring warns about: an empty/partial fetch must never look
        like "everything is fixed").
        """
        prefix = f"{_ROLLUP_NAMESPACE}:"
        active: set[str] = set()
        for key in self._state.get_rollup_issue_keys(_ROLLUP_NAMESPACE):
            subject = key[len(prefix) :]
            if subject not in open_pr_numbers:
                continue  # PR closed/merged — let resolve_all_except close it
            if subject not in examined or subject in still_red:
                active.add(subject)
        return await rollup_mgr.resolve_all_except(active)
