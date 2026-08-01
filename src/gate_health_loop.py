"""Background worker loop — treat CI reds as a DISTRIBUTION, not events (#9974).

The 2026-07-18/19 drought-breaking session found every one of its gate
defects manually: s51 sat born-broken at a 0% lifetime pass rate in the rc
gate for 17 days (its own PR ran only the fast subset); P10.3 (#9902) and
the dorny paths-filter bug (#9908) shared one statistical signature — a
check failing on PRs whose diffs could not plausibly touch it; sandbox
failure-artifact uploads had silently produced nothing for weeks.

GateHealthLoop computes those distributions on a weekly cadence from the
last N workflow runs and files evidence-rich ``hydraflow-find`` issues.
Human-gated calls ship as a "Consent package" section (evidence +
recommendation + exact command) — the digest contract for the #9957
refinement loop. STRICTLY read-only (ADR-0029 caretaker): it opens no PRs and
mutates no gates; issue filing is its only write.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug
from filing_budget import FilingBudget, file_overflow_summary, overflow_line
from loop_fitness import FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.gate_health")

# Failed runs of workflows matching these fragments are expected to upload
# failure artifacts; zero artifacts on a failed run = broken instrumentation.
_ARTIFACT_EXPECTING_FRAGMENTS = ("sandbox",)

# Diff paths matching these are "docs-only" for blame-correlation: a code
# check failing on a PR whose whole diff is docs cannot be blaming the PR.
_DOCS_ONLY_RE = re.compile(r"^docs/|\.md$|^\.github/ISSUE_TEMPLATE/")

# Checks whose domain is code — failing on a docs-only diff is uncorrelated.
_CODE_CHECK_FRAGMENTS = ("test", "quality", "lint", "type", "sandbox", "scenario")

_QUARANTINE_RE = re.compile(r'^QUARANTINED\s*=\s*["\']#(\d+)["\']', re.MULTILINE)

# A step's conclusion once it has actually finished running one way or
# another (#10010). Anything else (``None``/``"cancelled"``) at the moment
# the job dies means that step was still executing — the hang signal.
_TERMINAL_STEP_CONCLUSIONS = frozenset({"success", "failure", "skipped"})


def _duration_seconds(started_at: object, completed_at: object) -> float | None:
    """Wall-clock seconds between two ISO-8601 timestamps, or ``None``."""
    if not started_at or not completed_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - start).total_seconds()


def _find_unfinished_test_step(steps: list[dict[str, Any]]) -> str | None:
    """Name of a test-labeled step that never reached a terminal conclusion.

    A job's own ``conclusion`` becomes ``cancelled`` the instant the runner
    is killed, whether or not any given step actually finished. The signal
    that distinguishes a genuine in-flight hang from a clean/early
    cancellation is a *step* named for tests still sitting at a
    non-terminal conclusion (``None``/``"cancelled"``) when the job died.
    """
    for step in steps:
        name = str(step.get("name", ""))
        if "test" not in name.lower():
            continue
        conclusion = str(step.get("conclusion") or "").lower()
        if conclusion not in _TERMINAL_STEP_CONCLUSIONS:
            return name
    return None


def _load_workflow_job_timeouts(repo_root: Path) -> dict[str, int]:
    """Map job display name -> configured ``timeout-minutes`` (best-effort).

    Parsed directly from ``.github/workflows/*.yml`` — the GitHub Actions
    jobs API surfaces a job's actual start/end times but never its
    *configured* timeout, so the reference value has to come from the repo
    itself (same local-file-read pattern as ``_find_stale_quarantines``).
    """
    timeouts: dict[str, int] = {}
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return timeouts
    paths = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    for path in paths:
        try:
            doc = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict):
            continue
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, spec in jobs.items():
            if not isinstance(spec, dict):
                continue
            minutes = spec.get("timeout-minutes")
            if not isinstance(minutes, int) or minutes <= 0:
                continue
            display_name = str(spec.get("name") or job_id)
            timeouts[display_name] = minutes
    return timeouts


def find_suspected_hangs(
    job_records: list[dict[str, Any]],
    *,
    timeout_minutes_by_job: dict[str, int],
    tolerance_seconds: int,
) -> list[dict[str, Any]]:
    """Cancelled-at-timeout jobs with an unfinished test step (#10010).

    A job cancelled by GitHub's own timeout enforcement is invisible to
    ``tally_job_stats`` (cancelled is filtered out there) and looks nothing
    like a normal red: zero FAILED lines, conclusion CANCELLED. That
    combination — duration landing within *tolerance_seconds* of the job's
    configured ``timeout-minutes`` AND a test step that never reached a
    terminal conclusion — is the signature a blind retry burns attempt
    budget against instead of fixing (PRs #9983, #10002: a mocked ``.pid``
    fed a real ``os.killpg``, which reached the CI container's own PID 1).

    A check hitting this signature exactly once in the analyzed window is a
    ``suspected_hang`` — a distinct incident worth the killpg/mocked-``.pid``
    playbook. The same check hitting it two-plus times in one window is a
    *different* defect (#10883): the lane is chronically over its time
    budget, not wedged — that collapses to a single ``chronic_timeout``
    finding instead of one ``suspected_hang`` per run.
    """
    candidates: dict[str, list[dict[str, Any]]] = {}
    for rec in job_records:
        if str(rec.get("conclusion", "")).lower() != "cancelled":
            continue
        name = str(rec.get("name", "")).strip()
        timeout_minutes = timeout_minutes_by_job.get(name)
        if not timeout_minutes:
            continue
        duration = _duration_seconds(rec.get("started_at"), rec.get("completed_at"))
        if duration is None:
            continue
        if abs(duration - timeout_minutes * 60) > tolerance_seconds:
            continue
        unfinished_step = _find_unfinished_test_step(rec.get("steps") or [])
        if unfinished_step is None:
            continue
        candidates.setdefault(name, []).append(
            {
                "run_id": int(rec.get("run_id", 0) or 0),
                "pr_number": int(rec.get("pr_number", 0) or 0),
                "duration_seconds": round(duration),
                "timeout_minutes": timeout_minutes,
                "unfinished_step": unfinished_step,
            }
        )

    findings: list[dict[str, Any]] = []
    for name, hits in candidates.items():
        if len(hits) == 1:
            hit = hits[0]
            findings.append(
                {
                    "kind": "suspected_hang",
                    "check": name,
                    "run_id": hit["run_id"],
                    "pr_number": hit["pr_number"],
                    "duration_seconds": hit["duration_seconds"],
                    "timeout_minutes": hit["timeout_minutes"],
                    "unfinished_step": hit["unfinished_step"],
                    "tolerance_seconds": tolerance_seconds,
                }
            )
        else:
            findings.append(
                {
                    "kind": "chronic_timeout",
                    "check": name,
                    "occurrences": len(hits),
                    "run_ids": [hit["run_id"] for hit in hits],
                    "timeout_minutes": hits[-1]["timeout_minutes"],
                    "tolerance_seconds": tolerance_seconds,
                }
            )
    return findings


@dataclass
class JobStats:
    """Lifetime tally for one named check across the analyzed window."""

    passes: int = 0
    failures: int = 0
    first_seen: str = ""
    last_seen: str = ""
    docs_only_failures: int = 0
    docs_only_prs: list[int] = field(default_factory=list)
    # Runs the check was searched-but-inconclusive: skipped / cancelled / neutral
    # / empty. NOT attempts, but evidence the window holds — a gated check that is
    # mostly dormant contributes many skips and few attempts, and a "0% pass"
    # claim is only falsifiable if the reader can see them (#10898).
    skipped: int = 0

    @property
    def attempts(self) -> int:
        return self.passes + self.failures

    @property
    def runs_searched(self) -> int:
        """Every record seen for this check — attempts + inconclusive skips."""
        return self.passes + self.failures + self.skipped


def tally_job_stats(
    job_records: list[dict[str, Any]],
) -> dict[str, JobStats]:
    """Fold per-run job outcomes into per-check lifetime stats.

    *job_records*: ``{"name", "conclusion", "created_at", "docs_only": bool,
    "pr_number": int}`` — one per job occurrence, oldest or newest first
    (order only affects first/last_seen which are min/maxed).
    """
    stats: dict[str, JobStats] = {}
    for rec in job_records:
        name = str(rec.get("name", "")).strip()
        conclusion = str(rec.get("conclusion", "")).lower()
        if not name:
            continue
        entry = stats.setdefault(name, JobStats())
        created = str(rec.get("created_at", ""))
        if created:
            entry.first_seen = min(entry.first_seen or created, created)
            entry.last_seen = max(entry.last_seen, created)
        if conclusion in ("", "skipped", "cancelled", "neutral"):
            # Searched but inconclusive — counted for falsifiability, not an attempt.
            entry.skipped += 1
            continue
        if conclusion == "success":
            entry.passes += 1
        else:
            entry.failures += 1
            if rec.get("docs_only"):
                entry.docs_only_failures += 1
                pr = rec.get("pr_number")
                if isinstance(pr, int) and pr > 0:
                    entry.docs_only_prs.append(pr)
    return stats


def find_born_broken(
    stats: dict[str, JobStats], *, min_attempts: int
) -> list[dict[str, Any]]:
    """Checks that have NEVER passed in the window (the s51 class)."""
    findings = []
    for name, s in sorted(stats.items()):
        if s.passes == 0 and s.failures >= min_attempts:
            findings.append(
                {
                    "kind": "born_broken",
                    "check": name,
                    "failures": s.failures,
                    "skipped": s.skipped,
                    "runs_searched": s.runs_searched,
                    "first_seen": s.first_seen,
                    "last_seen": s.last_seen,
                }
            )
    return findings


def find_uncorrelated_blame(
    stats: dict[str, JobStats], *, min_occurrences: int
) -> list[dict[str, Any]]:
    """Code checks repeatedly failing on docs-only diffs (#9902/#9908 class)."""
    findings = []
    for name, s in sorted(stats.items()):
        lowered = name.lower()
        if not any(frag in lowered for frag in _CODE_CHECK_FRAGMENTS):
            continue
        if s.docs_only_failures >= min_occurrences:
            findings.append(
                {
                    "kind": "uncorrelated_blame",
                    "check": name,
                    "docs_only_failures": s.docs_only_failures,
                    "total_failures": s.failures,
                    "example_prs": sorted(set(s.docs_only_prs))[:5],
                }
            )
    return findings


def find_missing_artifacts(
    failed_run_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Failed artifact-expecting runs that uploaded nothing."""
    by_workflow: dict[str, list[int]] = {}
    for rec in failed_run_artifacts:
        name = str(rec.get("workflow", ""))
        if int(rec.get("artifact_count", 0)) == 0:
            by_workflow.setdefault(name, []).append(int(rec.get("run_id", 0)))
    return [
        {
            "kind": "missing_artifacts",
            "workflow": wf,
            "failed_runs_without_artifacts": len(run_ids),
            "example_runs": run_ids[:5],
        }
        for wf, run_ids in sorted(by_workflow.items())
    ]


def is_docs_only(paths: list[str]) -> bool:
    """True when every changed path is documentation."""
    return bool(paths) and all(_DOCS_ONLY_RE.search(p) for p in paths)


def finding_fingerprint(finding: dict[str, Any]) -> str:
    """Stable dedup key: kind + subject (NOT counts, which grow every cycle).

    ``suspected_hang`` also folds in the run id: unlike the structural
    findings below (one standing defect, filed once and then deduped
    forever), each hang is a distinct incident on a distinct commit/PR —
    fingerprinting on check name alone would silently swallow every hang
    after the first one on a given check.
    """
    subject = finding.get("check") or finding.get("workflow") or finding.get("scenario")
    if finding["kind"] == "suspected_hang":
        return f"{finding['kind']}:{subject}:{finding.get('run_id')}"
    return f"{finding['kind']}:{subject}"


class GateHealthLoop(BaseBackgroundLoop):
    """Weekly read-only auditor of CI gate health distributions (#9974).

    Five analyses per cycle: born-broken checks, blame-correlation
    (code checks failing docs-only diffs), missing failure artifacts,
    quarantine markers whose tracking issue is closed, and suspected CI
    hangs — a cancelled-at-timeout job with an unfinished test step
    (#10010), which further splits into a one-off ``suspected_hang`` versus
    a ``chronic_timeout`` when the same check repeats the signature within
    one analyzed window (#10883). Findings file as ``hydraflow-find`` issues
    with the stats table in the body and a consent package for anything
    human-gated. Deduped by finding fingerprint so a standing defect files
    once, not weekly (suspected-hang findings are the one exception: each is
    a distinct incident, fingerprinted per run so a second, unrelated hang
    on the same check still gets its own issue — chronic_timeout, like the
    other structural findings, fingerprints on check name alone).
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="gate_health", config=config, deps=deps)
        self._prs = pr_manager
        self._finding_dedup = DedupStore(
            "gate_health_findings",
            config.data_root / "dedup" / "gate_health_findings.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.gate_health_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only auditor: files evidence issues, owns no proposal/
        # acceptance lifecycle to score — HOUSEKEEPING per ADR-0093.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.gate_health_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        try:
            runs = await self._prs.list_workflow_runs(
                limit=self._config.gate_health_run_window
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Gate health: workflow-run listing failed", exc_info=True)
            return {"status": "runs_unavailable"}
        if not runs:
            return {"status": "no_runs", "findings": 0}

        job_records, failed_run_artifacts = await self._collect(runs)
        stats = tally_job_stats(job_records)
        timeout_minutes_by_job = _load_workflow_job_timeouts(
            Path(self._config.repo_root)
        )

        findings = [
            *find_born_broken(
                stats, min_attempts=self._config.gate_health_min_attempts
            ),
            *find_uncorrelated_blame(
                stats, min_occurrences=self._config.gate_health_min_attempts - 1
            ),
            *find_missing_artifacts(failed_run_artifacts),
            *await self._find_stale_quarantines(),
            *find_suspected_hangs(
                job_records,
                timeout_minutes_by_job=timeout_minutes_by_job,
                tolerance_seconds=self._config.gate_health_hang_tolerance_seconds,
            ),
        ]

        filed = await self._file_findings(findings)
        return {
            "runs_analyzed": len(runs),
            "checks_tracked": len(stats),
            "findings": len(findings),
            "filed": filed,
        }

    async def _collect(
        self, runs: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch per-run jobs + artifact counts; classify diffs for blame."""
        job_records: list[dict[str, Any]] = []
        failed_run_artifacts: list[dict[str, Any]] = []
        docs_only_cache: dict[int, bool] = {}

        for run in runs:
            if self._stop_event.is_set():
                break
            run_id = int(run.get("id", 0))
            conclusion = str(run.get("conclusion", "")).lower()
            pr_number = int(run.get("pr_number", 0) or 0)

            docs_only = False
            if pr_number > 0 and conclusion and conclusion != "success":
                if pr_number not in docs_only_cache:
                    try:
                        names = await self._prs.get_pr_diff_names(pr_number)
                        docs_only_cache[pr_number] = is_docs_only(names)
                    except Exception as exc:
                        reraise_on_credit_or_bug(exc)
                        docs_only_cache[pr_number] = False
                docs_only = docs_only_cache[pr_number]

            try:
                jobs = await self._prs.get_workflow_run_jobs(run_id)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Gate health: jobs unavailable for run %d — skipping",
                    run_id,
                    exc_info=True,
                )
                continue
            for job in jobs:
                job_records.append(
                    {
                        "name": job.get("name", ""),
                        "conclusion": job.get("conclusion", ""),
                        "created_at": run.get("created_at", ""),
                        "docs_only": docs_only,
                        "pr_number": pr_number,
                        # Only consumed by find_suspected_hangs (#10010);
                        # tally_job_stats ignores unknown keys.
                        "run_id": run_id,
                        "started_at": job.get("started_at", ""),
                        "completed_at": job.get("completed_at", ""),
                        "steps": job.get("steps", []),
                    }
                )

            workflow_name = str(run.get("workflow", ""))
            if conclusion == "failure" and any(
                frag in workflow_name.lower() for frag in _ARTIFACT_EXPECTING_FRAGMENTS
            ):
                try:
                    count = await self._prs.count_workflow_run_artifacts(run_id)
                except Exception as exc:
                    reraise_on_credit_or_bug(exc)
                    continue
                failed_run_artifacts.append(
                    {
                        "workflow": workflow_name,
                        "run_id": run_id,
                        "artifact_count": count,
                    }
                )
        return job_records, failed_run_artifacts

    async def _find_stale_quarantines(self) -> list[dict[str, Any]]:
        """QUARANTINED markers whose tracking issue is already closed."""
        findings: list[dict[str, Any]] = []
        scenario_dir = (
            Path(self._config.repo_root) / "tests" / "sandbox_scenarios" / "scenarios"
        )
        if not scenario_dir.is_dir():
            return findings
        for path in sorted(scenario_dir.glob("*.py")):
            try:
                match = _QUARANTINE_RE.search(path.read_text())
            except OSError:
                continue
            if match is None:
                continue
            issue_number = int(match.group(1))
            try:
                state = await self._prs.get_issue_state(issue_number)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                continue
            # get_issue_state vocabulary: OPEN / COMPLETED / NOT_PLANNED
            # ('' on error — treated as open, fail-safe: no finding).
            if state.upper() in ("COMPLETED", "NOT_PLANNED", "CLOSED"):
                findings.append(
                    {
                        "kind": "stale_quarantine",
                        "scenario": path.stem,
                        "issue": issue_number,
                        "path": str(path.relative_to(self._config.repo_root)),
                    }
                )
        return findings

    async def _file_findings(self, findings: list[dict[str, Any]]) -> int:
        # Per-tick filing cap (#10777): findings scale with distinct CI checks
        # and analyzed runs (suspected_hang is keyed per run_id), so a bad
        # window could file one issue per finding. Over the cap, findings are
        # recorded (so they are not re-filed individually) and folded into ONE
        # summary issue.
        budget = FilingBudget(cap=self._config.gate_health_max_issues_per_tick)
        seen = self._finding_dedup.get()
        for finding in findings:
            fingerprint = finding_fingerprint(finding)
            if fingerprint in seen:
                continue
            if not budget.allow():
                seen = seen | {fingerprint}
                self._finding_dedup.set_all(seen)
                budget.note_overflow(
                    overflow_line(fingerprint, str(finding.get("kind", "finding")))
                )
                continue
            title, body = _render_finding(finding)
            try:
                await self._prs.create_issue(title, body, labels=["hydraflow-find"])
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Gate health: failed to file finding %s", fingerprint, exc_info=True
                )
                continue
            seen = seen | {fingerprint}
            self._finding_dedup.set_all(seen)
            budget.note_filed()
            logger.info("Gate health: filed finding %s", fingerprint)
        summary_filed = await file_overflow_summary(
            create_issue=self._prs.create_issue,
            dedup=self._finding_dedup,
            budget=budget,
            key_prefix="gate_health",
            labels=["hydraflow-find"],
            title="Gate health: findings over per-tick filing cap",
            intro="**Automated — GateHealthLoop per-tick filing cap (#10777).**",
        )
        return budget.filed + summary_filed


def _render_finding(finding: dict[str, Any]) -> tuple[str, str]:
    """Render (title, body) for one finding, evidence table included."""
    kind = finding["kind"]
    if kind == "born_broken":
        title = f"Gate health: {finding['check']} has a 0% pass rate — born broken?"
        body = (
            f"## Evidence (GateHealthLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| check | `{finding['check']}` |\n"
            f"| failures in window | {finding['failures']} |\n"
            f"| passes in window | 0 |\n"
            f"| skipped/inconclusive in window | {finding.get('skipped', 0)} |\n"
            f"| runs searched | {finding.get('runs_searched', finding['failures'])} |\n"
            f"| first seen | {finding['first_seen']} |\n"
            f"| last seen | {finding['last_seen']} |\n\n"
            "A check that has NEVER passed is an instrument defect until "
            "proven otherwise (the s51 class: green-looking because its own "
            "PR ran only the fast subset). **Read the skip count first:** a "
            "mostly-dormant gated check (e.g. one that only runs when "
            "`should_run=true`) can show 0 passes because it rarely runs, not "
            "because it is broken — the runs-searched vs failures gap is the "
            "falsifier (#10898).\n\n"
            "## Recommended next step\n\n"
            "Trace when the check last passed on any ref; if never, treat "
            "as born-broken and fix or quarantine WITH a tracking issue.\n"
        )
    elif kind == "uncorrelated_blame":
        title = (
            f"Gate health: {finding['check']} fails on docs-only PRs — "
            "instrument, not PRs"
        )
        body = (
            f"## Evidence (GateHealthLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| check | `{finding['check']}` |\n"
            f"| docs-only-diff failures | {finding['docs_only_failures']} |\n"
            f"| total failures in window | {finding['total_failures']} |\n"
            f"| example PRs | {finding['example_prs']} |\n\n"
            "A code check failing on PRs whose entire diff is documentation "
            "cannot be blaming the PR (the #9902/#9908 signature). The "
            "instrument — path filter, baseline, or history scan — is the "
            "defect.\n"
        )
    elif kind == "missing_artifacts":
        title = f"Gate health: {finding['workflow']} failures upload zero artifacts"
        body = (
            f"## Evidence (GateHealthLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| workflow | `{finding['workflow']}` |\n"
            f"| failed runs with 0 artifacts | "
            f"{finding['failed_runs_without_artifacts']} |\n"
            f"| example run ids | {finding['example_runs']} |\n\n"
            "Failure artifacts are the only forensic trail for sandbox "
            "reds; an upload path that produces nothing on failure makes "
            "every red an archaeology session.\n"
        )
    elif kind == "stale_quarantine":
        title = (
            f"Gate health: quarantine on {finding['scenario']} references "
            f"closed #{finding['issue']}"
        )
        body = (
            f"## Evidence (GateHealthLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| scenario | `{finding['scenario']}` |\n"
            f"| marker file | `{finding['path']}` |\n"
            f"| tracking issue | #{finding['issue']} (CLOSED) |\n\n"
            "A quarantine whose tracking issue is closed is either a fixed "
            "scenario still being skipped (coverage silently lost) or a "
            "closed-without-fix issue (quarantine forever).\n\n"
            "## Consent package\n\n"
            "**Recommendation:** un-quarantine if the fix merged; reopen "
            "the issue if it did not.\n\n"
            "**Exact command (un-quarantine):**\n"
            "```bash\n"
            f"sed -i '' '/^QUARANTINED/d' {finding['path']}\n"
            "```\n"
            "Human-gated: GateHealthLoop will NOT execute this.\n"
        )
    elif kind == "suspected_hang":
        pr_number = finding.get("pr_number") or 0
        pr_note = f" (PR #{pr_number})" if pr_number else ""
        tolerance = finding.get("tolerance_seconds", 90)
        title = f"Gate health: {finding['check']} suspected CI hang, not a normal red"
        body = (
            f"## Evidence (GateHealthLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| check | `{finding['check']}` |\n"
            f"| run | {finding['run_id']}{pr_note} |\n"
            f"| conclusion | CANCELLED |\n"
            f"| duration | {finding['duration_seconds']}s |\n"
            f"| configured timeout-minutes | {finding['timeout_minutes']} |\n"
            f"| unfinished step | `{finding['unfinished_step']}` |\n\n"
            f"**This is not a normal red.** The job was CANCELLED within "
            f"~{tolerance}s of its own configured timeout, with a test "
            "step that never reached success/failure/skipped — the job "
            "was still running the test suite when GitHub Actions killed "
            "it. There are zero FAILED lines to read because nothing "
            "failed; the run just never finished.\n\n"
            "## Why this needs its own playbook — do NOT blind-retry\n\n"
            "PRs #9983 and #10002 hit exactly this signature: Tests "
            "cancelled at the workflow timeout with zero FAILED lines. "
            "Root cause both times was a real `os.killpg` reaching the "
            "CI runner's own process tree because a test mocked a "
            "subprocess's `.pid` (a `MagicMock`/default `.pid` resolves "
            "to `1`), and the code under test fed that value straight "
            'into `os.killpg`, so the "kill the child" call killed the '
            "container's own PID 1 instead. Retrying into the same "
            "wedge just re-burns the attempt budget — the fix is a code "
            "change, not a re-run.\n\n"
            "**Diagnosis REQUIRED a Linux container both times.** macOS "
            "gives a benign `EPERM` on the same `killpg` call (no "
            "permission to signal PID 1 as a non-root user), so every "
            "local run on a Mac passed clean. That divergence — clean "
            "on macOS, hangs/kills the container on Linux — IS the "
            "signal, not noise to explain away.\n\n"
            "## Recommended repro playbook\n\n"
            "1. **Bounded local repro first.** Re-run the failing test(s) "
            "locally with a hard wall-clock timeout close to the CI "
            "value above, so a real hang still shows up as a timeout "
            "instead of hanging your shell too.\n"
            "2. **If the diff touches subprocess/signal code** "
            "(`execution.py`, `runner_utils.py`, `subprocess_util.py`, "
            "`process_group.py`) and the local repro comes back clean "
            "or throws a benign `EPERM`, do NOT trust that as a pass — "
            "reproduce inside a Linux container instead (e.g. "
            '`docker run --rm -v "$PWD:/repo" -w /repo python:3.11 '
            "...`). A clean macOS run and a wedged Linux run are the "
            "same test; the platform IS the differentiator.\n"
            "3. Check for any mock standing in for a real subprocess/"
            "process-group object whose `.pid` (or similar identity "
            "attribute) could resolve to a real, sensitive PID (1, or "
            "the test runner's own PID) before it reaches a real "
            "`kill`/`killpg`/`terminate` call.\n"
        )
    else:  # chronic_timeout
        occurrences = finding.get("occurrences", 0)
        run_ids = finding.get("run_ids") or []
        tolerance = finding.get("tolerance_seconds", 90)
        title = f"Gate health: {finding['check']} chronically times out — over budget, not hung"
        body = (
            f"## Evidence (GateHealthLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| check | `{finding['check']}` |\n"
            f"| cancelled-at-timeout occurrences (window) | {occurrences} |\n"
            f"| example runs | {run_ids[:5]} |\n"
            f"| configured timeout-minutes | {finding['timeout_minutes']} |\n\n"
            f"**This is not a hang.** This check was CANCELLED within "
            f"~{tolerance}s of its own configured timeout in {occurrences} "
            "separate analyzed runs — a genuine one-off wedge shows up "
            "once, not repeatedly across the window. The repeated pattern "
            "is the lane outgrowing its time budget (a capacity problem), "
            "not a process stuck mid-test.\n\n"
            "## Recommended next step\n\n"
            "Do NOT chase the killpg/mocked-`.pid` hypothesis — that "
            "playbook is for a single `suspected_hang` incident, not a "
            "chronic pattern. Instead: parallelize or shard the lane, "
            "profile the slowest tests, or raise its `timeout-minutes` for "
            "headroom, then confirm it stops cancelling at the boundary.\n"
        )
    return title, body
