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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug
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


@dataclass
class JobStats:
    """Lifetime tally for one named check across the analyzed window."""

    passes: int = 0
    failures: int = 0
    first_seen: str = ""
    last_seen: str = ""
    docs_only_failures: int = 0
    docs_only_prs: list[int] = field(default_factory=list)

    @property
    def attempts(self) -> int:
        return self.passes + self.failures


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
        if not name or conclusion in ("", "skipped", "cancelled", "neutral"):
            continue
        entry = stats.setdefault(name, JobStats())
        created = str(rec.get("created_at", ""))
        if created:
            entry.first_seen = min(entry.first_seen or created, created)
            entry.last_seen = max(entry.last_seen, created)
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
    """Stable dedup key: kind + subject (NOT counts, which grow every cycle)."""
    subject = finding.get("check") or finding.get("workflow") or finding.get("scenario")
    return f"{finding['kind']}:{subject}"


class GateHealthLoop(BaseBackgroundLoop):
    """Weekly read-only auditor of CI gate health distributions (#9974).

    Four analyses per cycle: born-broken checks, blame-correlation
    (code checks failing docs-only diffs), missing failure artifacts,
    and quarantine markers whose tracking issue is closed. Findings file
    as ``hydraflow-find`` issues with the stats table in the body and a
    consent package for anything human-gated. Deduped by finding
    fingerprint so a standing defect files once, not weekly.
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

        findings = [
            *find_born_broken(
                stats, min_attempts=self._config.gate_health_min_attempts
            ),
            *find_uncorrelated_blame(
                stats, min_occurrences=self._config.gate_health_min_attempts - 1
            ),
            *find_missing_artifacts(failed_run_artifacts),
            *await self._find_stale_quarantines(),
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
        filed = 0
        seen = self._finding_dedup.get()
        for finding in findings:
            fingerprint = finding_fingerprint(finding)
            if fingerprint in seen:
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
            filed += 1
            logger.info("Gate health: filed finding %s", fingerprint)
        return filed


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
            f"| first seen | {finding['first_seen']} |\n"
            f"| last seen | {finding['last_seen']} |\n\n"
            "A check that has NEVER passed is an instrument defect until "
            "proven otherwise (the s51 class: green-looking because its own "
            "PR ran only the fast subset).\n\n"
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
    else:  # stale_quarantine
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
    return title, body
