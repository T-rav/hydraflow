"""Background worker loop — PRUnsticker intake for settled CI reds (#10027).

PHASE 1: infra-flake retrier. An open PR's CI settles red and, tonight
after tonight, someone has to look at it — the most-repeated operator
action across the 2026-07-19/20 overnight session, with no automated
owner. This caretaker (ADR-0029) detects a **settled-red** open PR,
classifies the failure as an infra-flake using the four signals proven
that session, and issues a bounded ``gh run rerun --failed``. A run whose
failure doesn't classify as an infra-flake (a "real red") falls through
to Phase 2.

PHASE 2: real-red auto-agent dispatch. A settled red that is NOT an
infra-flake gets the failing job's log tail (reusing the same
``fetch_ci_failure_logs`` / ``gh run view --log-failed`` surface Phase 1
already uses) plus the branch's recent commit diffs
(``PRPort.get_pr_recent_commit_diffs``, the same source
``SandboxFailureFixerLoop`` injects into its own auto-agent prompt), and
dispatches :class:`preflight.auto_agent_runner.AutoAgentRunner` — the SAME
subprocess-spawn machinery ``AutoAgentPreflightLoop`` /
``SandboxFailureFixerLoop`` use, not a reimplementation — onto the PR's own
branch to fix it and push. Two guardrails gate the dispatch:

* **Double-writer guard.** A PR already labeled ``review_label``
  (default ``hydraflow-review``) has an active reviewer worktree on it —
  the same "avoid stepping on toes" signal ``MergeStateWatcherLoop`` skips
  on for its own auto-rebase. Dispatching a competing auto-agent write
  into that same worktree would race the reviewer, so it's skipped this
  cycle (retried once the label moves on).
* **Human-PR ownership guard.** A PR NOT authored by the factory's own bot
  (``PRListItem.is_bot`` false) is someone's manual work; the factory
  posts ONE log-pointer comment (deduped via ``DedupStore``, re-posted
  only if the PR later carries new content) rather than pushing an
  uninvited commit, UNLESS the PR carries the ``auto-fix-ok`` opt-in
  label.

Dispatch attempts are bounded by ``pr_red_repair_dispatch_max_attempts``
(tracked the same way as Phase 1's rerun attempts — see below); once
exhausted, the PR is labeled ``hitl_label`` (default ``hydraflow-hitl``)
for a human, mirroring ``SandboxFailureFixerLoop``'s escalation-by-label
pattern.

Mirrors :class:`gate_health_loop.GateHealthLoop`'s structure (closest
existing caretaker with PR/run/job read Port methods) and reuses its
``list_workflow_runs`` + ``get_workflow_run_jobs`` reads rather than adding
a new per-PR ``statusCheckRollup`` fetch: ``list_workflow_runs`` already
carries each run's ``pr_number``, and ``get_workflow_run_jobs`` now also
carries each job's ``status`` (added for #10027) alongside its
``conclusion`` — together they form the same "rollup" shape (per-check
lifecycle + outcome) the settled-red predicate needs, without a new
``gh`` call. The one genuinely new Port method Phase 1 added is the write
side, ``PRPort.rerun_workflow_failed`` (triplet: Protocol + ``PRManager``
+ ``FakeGitHub`` + cassette); Phase 2 adds no new Port methods at all —
``list_prs_by_label``, ``post_pr_comment``, ``add_pr_labels``,
``get_pr_recent_commit_diffs``, and ``AutoAgentRunner`` are all reused
as-is from ``SandboxFailureFixerLoop`` / ``MergeStateWatcherLoop``.

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
or is no longer open — #10022 discipline). Phase 2's dispatch attempts
reuse the SAME ledger under a distinct stage (``"pr_red_dispatch"``) —
no new persisted state shape.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import FitnessContext, FitnessKind, LoopFitness
from package_resources import resource_path
from rollup_issue_manager import RollupIssueManager

if TYPE_CHECKING:
    from ports import PRPort, WorkspacePort
    from preflight.auto_agent_runner import AutoAgentRunner
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

# Phase 2 (#10027) — real-red auto-agent dispatch constants. The dispatch
# attempt-cap ledger's stage name lives in state/_pr_red_repair.py (the
# module that actually reads/writes it) — not duplicated here.
_AUTO_FIX_OK_LABEL = "auto-fix-ok"
_HUMAN_PR_DEDUP_NAMESPACE = "pr_red_repair_human_pointer"
_PROMPT_TEMPLATE = "pr_red_fix.md"

# Dispatch-prompt payload compression (#10860). ``gh run view --log-failed``
# stamps EVERY line with a ``job\tstep\tISO-timestamp`` prefix — ~47 chars of
# repetition per line carrying no repair signal. :func:`_compress_gh_log`
# strips it, emitting one ``[job / step]`` header per transition instead
# (section identity stays: ``fetch_ci_failure_logs`` already heads each
# failed check with ``### <name> (run <id>)``). The tail caps bound
# pathological payloads: multi-check reds concatenate one full log per
# failed check, and pytest/make print the actionable failure summary LAST,
# so the tail is the load-bearing slice; ``get_pr_recent_commit_diffs``
# orders sections oldest-first, so the diff tail keeps the newest commits —
# the likeliest culprits for a fresh red.
_GH_LOG_LINE_RE = re.compile(
    r"^(?P<job>[^\t\n]+)\t(?P<step>[^\t\n]*)\t"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?"
)
_DISPATCH_LOG_MAX_CHARS = 20_000
_DISPATCH_DIFF_MAX_CHARS = 20_000


def _compress_gh_log(log_text: str) -> str:
    """Strip per-line gh log prefixes; one ``[job / step]`` header per run."""
    out: list[str] = []
    prev: tuple[str, str] | None = None
    for line in log_text.splitlines():
        m = _GH_LOG_LINE_RE.match(line)
        if m is None:
            out.append(line)
            prev = None
            continue
        key = (m.group("job"), m.group("step"))
        if key != prev:
            out.append(f"[{key[0]} / {key[1]}]")
            prev = key
        out.append(line[m.end() :])
    return "\n".join(out)


def _tail_capped(text: str, max_chars: int) -> str:
    """Keep the last *max_chars* of *text*, with an explicit truncation note."""
    if len(text) <= max_chars:
        return text
    return (
        f"(truncated: showing the last {max_chars} of {len(text)} chars)\n"
        + text[-max_chars:]
    )


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

    Returns ``None`` for anything else, including a passing job — that's
    a real red, which Phase 2 (:func:`should_dispatch_auto_agent` onward)
    picks up.
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
    regression (a real red — Phase 2 territory), the whole run is left
    alone rather than rerun — which would re-run, and risk masking, the
    real red too. Returns the first matched reason (for logging), or
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


def should_dispatch_auto_agent(
    *, is_bot_author: bool, has_auto_fix_ok_label: bool
) -> bool:
    """True when a real (non-infra) settled red should get a CODE dispatch.

    The factory's own bot-authored PRs (``agent/issue-N`` branches it
    created itself) always get a dispatch — there's no other owner. A
    human-authored PR is someone's manual work-in-progress; the factory
    never pushes an uninvited commit to it unless the human explicitly
    opted in via the ``auto-fix-ok`` label (#10027 Phase 2 ownership
    guardrail). ``False`` routes to the log-pointer-comment path instead
    of a dispatch.
    """
    return is_bot_author or has_auto_fix_ok_label


def _build_human_pr_comment(pr: Any, *, log_text: str) -> str:
    """Render the one-time log-pointer comment for a human-authored PR."""
    if log_text and log_text.strip():
        tail = "\n".join(log_text.strip().splitlines()[-40:])
    else:
        tail = "(log unavailable — see the failing run in the Checks tab)"
    return (
        "## CI is red — human review needed\n\n"
        "PrRedRepairLoop (#10027 Phase 2) found this PR's CI settled red "
        "with a failure that does not match any known infra-flake "
        "signature (cancelled run / zero failed steps / failed setup "
        "step / vanished logs) — this looks like a real regression in "
        "the diff.\n\n"
        "Because this PR isn't authored by the factory's own bot, it "
        "will **not** push an automated fix to your branch. Add the "
        "`auto-fix-ok` label if you'd like the auto-agent to try.\n\n"
        "<details><summary>Failing job log tail</summary>\n\n"
        "```\n"
        f"{tail}\n"
        "```\n"
        "</details>\n"
    )


class PrRedRepairLoop(BaseBackgroundLoop):
    """Detects settled-red open PRs; reruns infra-flakes, dispatches real reds (#10027).

    Phase 1: classifies four proven infra-flake signatures (cancelled run,
    zero-failed-steps job, failed setup step, vanished logs) and issues
    ``gh run rerun --failed``, capped at ``pr_red_rerun_max_attempts`` per
    PR. Budget exhaustion files one rollup issue per PR (auto-closed once
    the PR clears or closes).

    Phase 2: a red that does NOT classify as an infra-flake (a real red)
    gets dispatched to :class:`preflight.auto_agent_runner.AutoAgentRunner`
    on the PR's own branch, capped at ``pr_red_repair_dispatch_max_attempts``
    — see the module docstring for the two dispatch guardrails (double-writer
    / human-PR ownership) and the give-up-to-``hydraflow-hitl`` path.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        state: StateTracker,
        deps: LoopDeps,
        *,
        runner: AutoAgentRunner | Any | None = None,
        workspaces: WorkspacePort | Any | None = None,
        human_pr_dedup: DedupStore | None = None,
    ) -> None:
        super().__init__(worker_name="pr_red_repair", config=config, deps=deps)
        self._prs = pr_manager
        self._state = state
        self._runner = runner
        self._workspaces = workspaces
        self._human_pr_dedup = human_pr_dedup or DedupStore(
            _HUMAN_PR_DEDUP_NAMESPACE,
            config.data_root / "dedup" / f"{_HUMAN_PR_DEDUP_NAMESPACE}.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.pr_red_repair_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Bounded mechanical repair (rerun failed CI jobs / dispatch a
        # fix attempt), no proposal/acceptance lifecycle of its own to
        # score — HOUSEKEEPING per ADR-0093's fitness contract (mirrors
        # adr_conformance_loop.py).
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
        # Per-cycle label-fetch cache (Phase 2) — ``list_prs_by_label`` is
        # only ever called at most once per distinct label per cycle,
        # regardless of how many PRs need a dispatch decision.
        label_cache: dict[str, set[int]] = {}

        examined: set[str] = set()
        still_red: set[str] = set()
        still_real_red: set[str] = set()
        reran = 0
        escalated = 0
        skipped_real_red = 0
        dispatched = 0
        dispatch_crashed = 0
        dispatch_escalated = 0
        commented_human_pr = 0
        skipped_external_activity = 0

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
                still_real_red.add(str(pr.pr))
                if log_text is None:
                    log_text = await self._fetch_log_text(pr.pr)
                status = await self._dispatch_real_red(
                    pr, log_text=log_text, label_cache=label_cache
                )
                if status == "dispatched":
                    dispatched += 1
                elif status == "dispatch_crashed":
                    dispatch_crashed += 1
                elif status == "dispatch_escalated":
                    dispatch_escalated += 1
                elif status == "commented":
                    commented_human_pr += 1
                elif status == "skipped_external_activity":
                    skipped_external_activity += 1
                    skipped_real_red += 1
                else:
                    # skipped_no_runner / skipped_dispatch_disabled /
                    # already_commented — no NEW action taken this cycle.
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
        self._reconcile_human_pr_dedup(examined=examined, still_real_red=still_real_red)

        return {
            "status": "ok",
            "open_prs": len(open_prs),
            "reran": reran,
            "escalated": escalated,
            "skipped_real_red": skipped_real_red,
            "dispatched": dispatched,
            "dispatch_crashed": dispatch_crashed,
            "dispatch_escalated": dispatch_escalated,
            "commented_human_pr": commented_human_pr,
            "skipped_external_activity": skipped_external_activity,
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

    # -- Phase 2 (#10027): real-red auto-agent dispatch ---------------------

    async def _prs_with_label(
        self, label: str, label_cache: dict[str, set[int]]
    ) -> set[int]:
        """Return the PR-number set carrying *label*, cached for this cycle.

        Fail-closed on fetch error: an empty set means "no PR verified to
        carry this label," which is the safe default for both callers
        (double-writer guard: nothing looks under-review; ownership guard:
        nothing looks opted in) — never dispatch on an unverifiable state.
        """
        if label in label_cache:
            return label_cache[label]
        try:
            items = await self._prs.list_prs_by_label(label)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "PrRedRepair: list_prs_by_label(%r) failed", label, exc_info=True
            )
            items = []
        numbers = {int(getattr(item, "number", 0) or 0) for item in items}
        label_cache[label] = numbers
        return numbers

    async def _guardrail_status(
        self, pr: Any, *, log_text: str, label_cache: dict[str, set[int]]
    ) -> str | None:
        """Short-circuit status for *pr*, or ``None`` to proceed to dispatch.

        Checked in order: the Phase 2 static kill-switch, the double-writer
        guardrail (active-review label), then the human-PR ownership
        guardrail (posts the one-time log-pointer comment as a side effect
        when it fires). The runner-wired check lives in
        :meth:`_dispatch_real_red` (not here) so the ``self._runner`` narrow
        to non-``None`` stays local to the one call site that needs it.
        """
        if not self._config.pr_red_repair_dispatch_enabled:
            return "skipped_dispatch_disabled"

        # Double-writer guardrail: a PR already under active review has a
        # live worktree on it elsewhere in the factory — never race it.
        review_label = (self._config.review_label or ["hydraflow-review"])[0]
        review_prs = await self._prs_with_label(review_label, label_cache)
        if int(pr.pr) in review_prs:
            logger.info(
                "PrRedRepair: PR #%d carries %s (active reviewer worktree) "
                "— skipping dispatch this cycle (double-writer guard)",
                pr.pr,
                review_label,
            )
            return "skipped_external_activity"

        # Human-PR ownership guardrail: never push an uninvited commit to
        # a human-authored PR unless it explicitly opted in.
        is_bot_author = bool(getattr(pr, "is_bot", False))
        auto_fix_ok_prs = await self._prs_with_label(_AUTO_FIX_OK_LABEL, label_cache)
        if not should_dispatch_auto_agent(
            is_bot_author=is_bot_author,
            has_auto_fix_ok_label=int(pr.pr) in auto_fix_ok_prs,
        ):
            posted = await self._comment_human_pr(pr, log_text=log_text)
            # Deduped (already commented this streak) is a distinct status
            # from a freshly posted comment — it must NOT double-count in
            # ``commented_human_pr`` on a repeat cycle.
            return "commented" if posted else "already_commented"
        return None

    async def _dispatch_real_red(
        self, pr: Any, *, log_text: str, label_cache: dict[str, set[int]]
    ) -> str:
        """Handle one real (non-infra) settled-red PR for Phase 2.

        Returns one of: ``"dispatched"``, ``"dispatch_crashed"``,
        ``"dispatch_escalated"``, ``"commented"``, ``"already_commented"``,
        ``"skipped_external_activity"``, ``"skipped_no_runner"``,
        ``"skipped_dispatch_disabled"``.
        """
        runner = self._runner
        if runner is None:
            return "skipped_no_runner"

        guard_status = await self._guardrail_status(
            pr, log_text=log_text, label_cache=label_cache
        )
        if guard_status is not None:
            return guard_status

        attempts = self._state.get_pr_red_dispatch_attempts(pr.pr)
        max_attempts = int(self._config.pr_red_repair_dispatch_max_attempts)
        if attempts >= max_attempts:
            await self._give_up(pr)
            return "dispatch_escalated"

        self._state.bump_pr_red_dispatch_attempts(pr.pr)
        worktree_path = await self._resolve_dispatch_worktree(pr)
        prompt = await self._build_dispatch_prompt(pr, log_text=log_text)
        try:
            outcome = await runner.run(
                prompt=prompt,
                worktree_path=worktree_path,
                issue_number=int(pr.pr),
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "PrRedRepair: dispatch failed for PR #%d: %s",
                pr.pr,
                exc,
                exc_info=True,
            )
            return "dispatch_crashed"

        if getattr(outcome, "crashed", False):
            return "dispatch_crashed"
        return "dispatched"

    async def _resolve_dispatch_worktree(self, pr: Any) -> str:
        """Return a filesystem worktree path for *pr* (never its branch name).

        Mirrors ``SandboxFailureFixerLoop._resolve_worktree``: reuse the
        conventional per-issue workspace if present, otherwise create one
        on the PR's branch. Falls back to ``repo_root`` when no
        ``WorkspacePort`` is wired (test fixtures / dry-run).
        """
        if self._workspaces is None:
            return str(self._config.repo_root)
        wt_path = self._config.workspace_path_for_issue(int(pr.pr))
        if wt_path.exists():
            return str(wt_path)
        branch = str(getattr(pr, "branch", "") or f"agent/issue-{pr.pr}")
        try:
            created = await self._workspaces.create(int(pr.pr), branch)
            return str(created)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "PrRedRepair: worktree creation failed for PR #%d: %s — "
                "falling back to repo_root",
                pr.pr,
                exc,
            )
            return str(self._config.repo_root)

    async def _fetch_recent_diffs(self, pr_number: int) -> str:
        try:
            return await self._prs.get_pr_recent_commit_diffs(pr_number, n=3)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "PrRedRepair: get_pr_recent_commit_diffs failed for PR #%d",
                pr_number,
                exc_info=True,
            )
            return ""

    async def _build_dispatch_prompt(self, pr: Any, *, log_text: str) -> str:
        """Render the ``pr_red_fix.md`` envelope with this PR's context."""
        envelope_path = resource_path("prompts", "auto_agent", _PROMPT_TEMPLATE)
        envelope = envelope_path.read_text()

        diffs = await self._fetch_recent_diffs(pr.pr)
        ci_failure_log = (
            _tail_capped(_compress_gh_log(log_text.strip()), _DISPATCH_LOG_MAX_CHARS)
            if log_text and log_text.strip()
            else "(no CI failure log available)"
        )
        recent_commit_diffs = (
            _tail_capped(diffs.strip(), _DISPATCH_DIFF_MAX_CHARS)
            if diffs and diffs.strip()
            else "(no recent commit diffs available)"
        )

        return (
            envelope.replace("{PR_NUMBER}", str(pr.pr))
            .replace("{PR_BRANCH}", str(getattr(pr, "branch", "")))
            .replace("{CI_FAILURE_LOG}", ci_failure_log)
            .replace("{RECENT_COMMIT_DIFFS}", recent_commit_diffs)
        )

    async def _comment_human_pr(self, pr: Any, *, log_text: str) -> bool:
        """Post the ONE log-pointer comment on a human-authored real-red PR.

        Deduped via ``DedupStore`` keyed by PR number so a repeat cycle
        (the PR is still real-red, still un-opted-in) never re-posts;
        :meth:`_reconcile_human_pr_dedup` clears the key once the PR
        resolves so a LATER, distinct real red gets a fresh comment.
        Returns ``True`` only when a NEW comment was actually posted this
        call, so the caller never double-counts an already-deduped PR.
        """
        dedup_key = str(pr.pr)
        if dedup_key in self._human_pr_dedup.get():
            return False
        body = _build_human_pr_comment(pr, log_text=log_text)
        try:
            await self._prs.post_pr_comment(pr.pr, body)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "PrRedRepair: log-pointer comment failed for PR #%d: %s",
                pr.pr,
                exc,
                exc_info=True,
            )
            return False
        self._human_pr_dedup.add(dedup_key)
        return True

    async def _give_up(self, pr: Any) -> None:
        """Label *pr* ``hitl_label`` once the dispatch attempt cap is spent."""
        hitl_label = (self._config.hitl_label or ["hydraflow-hitl"])[0]
        try:
            await self._prs.add_pr_labels(pr.pr, [hitl_label])
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "PrRedRepair: hitl label-add failed for PR #%d: %s",
                pr.pr,
                exc,
                exc_info=True,
            )

    def _reconcile_human_pr_dedup(
        self, *, examined: set[str], still_real_red: set[str]
    ) -> None:
        """Clear the log-pointer dedup key for any examined PR no longer real-red.

        Positive-evidence-only, mirroring :meth:`_reconcile_rollups`: a PR
        this cycle couldn't examine stays as-is (silence never implies
        resolution); one that WAS examined and is no longer real-red gets
        its dedup key dropped so a later, distinct real red re-comments.
        """
        for key in examined - still_real_red:
            self._human_pr_dedup.discard(key)
