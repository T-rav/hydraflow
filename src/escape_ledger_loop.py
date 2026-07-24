"""Background worker loop — EscapeLedgerLoop (#10367).

The FOUNDATION falsification instrument: a read-only ADR-0029 caretaker,
**Pattern B like ``ErosionMetricsLoop``** (sense + record, NEVER opens fix
PRs, never gates, never blocks). It answers two claims the factory's own
gates cannot check:

1. **Escape ledger.** Each tick it scans commits merged to the base branch
   since the last tick, mechanically detects post-merge defects (revert /
   hotfix / regression-pin / bug-issue-fix), attributes each back to the
   originating merge (mechanical-first; low confidence → HITL surface;
   attribution NEVER blocks), and appends one row per escape to the
   append-only ledger ``<data_root>/diagnostics/escape_ledger.jsonl``
   (``escape.models.EscapeRecord`` schema). Sentry-sourced escapes are
   attributed in the ``SentryLoop`` flow, which appends its own rows to the
   same ledger.
2. **Erosion trend surfaces** (v2 of epic #10104). The same merged-commit
   scan feeds a per-tick erosion datapoint (files touched, modules crossed,
   scatter findings, duplication density) into
   ``<data_root>/diagnostics/erosion_trends.jsonl``; the loop re-renders the
   month-over-month rollup to ``docs/arch/generated/erosion-trends.md``.

Both surfaces are generated reports written into the live repo root each tick
(gitignored, like ``loop-fitness.md``) — not ``arch-regen`` artifacts.

**Cursor + dedup design** (identical to ``ErosionMetricsLoop``):
``state.get_escape_ledger_last_processed_sha()`` persists the base-branch
HEAD SHA this loop last analyzed. A fresh install primes the cursor to the
current sha with NO back-analysis (an explicit one-time backfill command, if
provided, is separate). The cursor advances unconditionally at the end of a
successful tick (dedup by SHA — a commit range is analyzed exactly once). A
separate ``DedupStore`` guards against re-recording the same escape id, and
against re-surfacing the same finding, across retries/restarts.

**Bounded per tick.** ``escape_ledger_max_issues_per_tick`` caps how many
HITL/``hydraflow-find`` issues one tick may file for low-confidence or
aging-unencoded escapes — the finding-rate budget the spec requires (an
instrument that over-files gets rationally dismissed). Recording rows is
never capped; only issue-filing is. Attribution and recording never block.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from arch.extractors.modules import extract_module_graph
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from erosion.duplication import duplication_for_range
from erosion.models import DuplicationFinding
from erosion.scatter import DEFAULT_SCATTER_THRESHOLD, added_symbols_for_range
from erosion.scatter import compute as scatter_compute
from erosion.spread import changed_files_for_range
from erosion.spread import compute as spread_compute
from erosion.trends import (
    ChangeDatapoint,
    TrendStore,
    compute_monthly_trends,
    render_erosion_trends_markdown,
)
from escape.detect import (
    commit_committed_at,
    commits_for_range,
    count_commits_since,
    detect_escapes,
)
from escape.ledger import EscapeLedger
from escape.metrics import low_confidence, unencoded_aging
from escape.models import EscapeCandidate, EscapeRecord
from escape.report import render_escape_ledger_markdown
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.escape_ledger")

# Local, read-only git op — same bound as erosion's git adapters. Resolves HEAD.
_GIT_TIMEOUT_S = 60

_ISSUE_LABELS = ["hydraflow-find", "escape-ledger"]

# Generated-report paths (repo-root-relative), gitignored + rewritten each
# tick like docs/arch/generated/loop-fitness.md — NOT arch-regen artifacts.
_ESCAPE_REPORT_REL = Path("docs/arch/generated/escape-ledger.md")
_TRENDS_REPORT_REL = Path("docs/arch/generated/erosion-trends.md")

_LEDGER_FILENAME = "escape_ledger.jsonl"
_TRENDS_FILENAME = "erosion_trends.jsonl"

_HEX_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _current_head_sha(repo_root: Path) -> str | None:
    """Return *repo_root*'s current HEAD sha, or ``None`` on any git failure.

    Deliberately NOT cached (mirrors ``erosion_metrics_loop._current_head_sha``):
    the loop must observe HEAD advancing across ticks. Raw ``subprocess.run``
    local read — not the fleet-gated spawn the sandbox seam guard covers.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def surfacing_fingerprint(escape_id: str) -> str:
    """Stable dedup key for a filed HITL/find issue about one escape."""
    return f"surfaced:{escape_id}"


def select_findings_to_surface(
    records: list[EscapeRecord],
    *,
    now: datetime,
    aging_threshold_hours: float,
    already_surfaced: set[str],
    max_per_tick: int,
) -> tuple[list[EscapeRecord], bool]:
    """Pure finding-rate budget: which escapes to surface, capped per tick.

    Eligible = low-confidence attributions (need a human label) + ``none-yet``
    rows older than *aging_threshold_hours* (should have been encoded by now),
    deduped by id and excluding anything already surfaced. Returns
    ``(to_file, capped)`` where ``to_file`` is at most *max_per_tick* rows and
    ``capped`` is True when eligible exceeded the cap. This caps issue filing
    under a synthetic flood — recording rows is never capped, only filing.
    """
    eligible: list[EscapeRecord] = []
    seen: set[str] = set()
    aging = unencoded_aging(records, now, threshold_hours=aging_threshold_hours)
    for record in [*low_confidence(records), *aging]:
        if record.id in seen:
            continue
        seen.add(record.id)
        if surfacing_fingerprint(record.id) in already_surfaced:
            continue
        eligible.append(record)
    capped = len(eligible) > max_per_tick
    return eligible[:max_per_tick], capped


class EscapeLedgerLoop(BaseBackgroundLoop):
    """Records post-merge escapes + erosion trends. Read-only (Pattern B).

    Never edits code, never opens a fix PR, never gates. It senses and
    records; the escape already became work through normal triage, and the
    ledger is bookkeeping ABOUT the instruments, not one of them.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        state: StateTracker,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="escape_ledger", config=config, deps=deps)
        self._prs = pr_manager
        self._state = state
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.escape_ledger_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only sensor: files evidence issues, owns no proposal/acceptance
        # lifecycle to score — HOUSEKEEPING per ADR-0093, mirrors
        # erosion_metrics_loop.py.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    # --- paths -----------------------------------------------------------

    @property
    def _ledger_path(self) -> Path:
        return self._config.diagnostics_dir / _LEDGER_FILENAME

    @property
    def _trends_path(self) -> Path:
        return self._config.diagnostics_dir / _TRENDS_FILENAME

    # --- main tick -------------------------------------------------------

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.escape_ledger_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        resolved = self._resolve_range()
        if isinstance(resolved, dict):
            return resolved
        repo_root, commit_range, commits, current_sha = resolved

        candidates = detect_escapes(commits)
        recorded = self._record_escapes(repo_root, candidates)
        datapoint = self._record_trend_datapoint(repo_root, commit_range, commits)
        self._render_reports(repo_root)
        filed, capped = await self._surface_findings()

        # Advance the cursor unconditionally: this range has been fully
        # analyzed (dedup by SHA), independent of the per-tick filing cap.
        self._state.set_escape_ledger_last_processed_sha(current_sha)

        return {
            "status": "ok",
            "range": commit_range,
            "commits": len(commits),
            "escapes_detected": len(candidates),
            "escapes_recorded": len(recorded),
            "trend_datapoint": datapoint is not None,
            "filed": filed,
            "capped": capped,
        }

    def _resolve_range(
        self,
    ) -> tuple[Path, str, list[Any], str] | dict[str, Any]:
        """Resolve the new commit range to analyze, or an early-exit status dict.

        Primes the cursor on the first tick ever (no back-analysis); every
        other early exit leaves the cursor untouched so the next tick retries.
        """
        repo_root = Path(self._config.repo_root)
        current_sha = _current_head_sha(repo_root)
        if current_sha is None:
            return {"status": "head_sha_unavailable"}

        last_sha = self._state.get_escape_ledger_last_processed_sha()
        if not last_sha:
            self._state.set_escape_ledger_last_processed_sha(current_sha)
            return {"status": "baseline_established", "sha": current_sha}
        if current_sha == last_sha:
            return {"status": "no_new_commits", "sha": current_sha}

        commit_range = f"{last_sha}..{current_sha}"
        commits = commits_for_range(repo_root, commit_range)
        if commits is None:
            return {"status": "commits_unavailable", "range": commit_range}

        return repo_root, commit_range, commits, current_sha

    # --- escape recording ------------------------------------------------

    def _record_escapes(
        self, repo_root: Path, candidates: list[EscapeCandidate]
    ) -> list[EscapeRecord]:
        """Append one deduped ledger row per detected escape. Never blocks."""
        ledger = EscapeLedger(self._ledger_path)
        existing = ledger.existing_ids()
        seen = self._dedup.get()
        recorded: list[EscapeRecord] = []
        for candidate in candidates:
            if candidate.id in existing or candidate.id in seen:
                continue
            merge_sha, merged_at = self._resolve_attribution(repo_root, candidate)
            record = EscapeRecord.from_candidate(
                candidate,
                originating_merge_sha=merge_sha,
                merged_at=merged_at,
            )
            ledger.append(record)
            existing.add(candidate.id)
            seen = seen | {candidate.id}
            self._dedup.set_all(seen)
            recorded.append(record)
            logger.info(
                "EscapeLedger: recorded %s (%s, %s)",
                candidate.id,
                candidate.attribution_method,
                candidate.attribution_confidence,
            )
        return recorded

    def _resolve_attribution(
        self, repo_root: Path, candidate: EscapeCandidate
    ) -> tuple[str, str]:
        """Resolve (originating_merge_sha, merged_at) mechanically.

        When the detector extracted a concrete sha pointer (revert-parse,
        blame-intersect, or a sha in a regression-pin body), resolve the
        merge's committer date so ``time_to_detection_hours`` is populated.
        A ``#N`` pointer (fixes-chain) cannot be resolved to a merge sha
        without GitHub — left empty here, which keeps the row low/medium
        confidence and lets the HITL surface finish attribution. Never raises.
        """
        ref = candidate.originating_ref
        if ref and _HEX_SHA_RE.match(ref):
            merged_at = commit_committed_at(repo_root, ref) or ""
            return ref, merged_at
        return "", ""

    # --- erosion trend datapoint ----------------------------------------

    def _record_trend_datapoint(
        self, repo_root: Path, commit_range: str, commits: list[Any]
    ) -> ChangeDatapoint | None:
        """Append one erosion trend datapoint for this tick's merged batch."""
        if not commits:
            return None
        changed_files = changed_files_for_range(repo_root, commit_range) or []
        added_symbols = added_symbols_for_range(repo_root, commit_range) or {}
        module_graph = extract_module_graph(repo_root / "src")
        spread = spread_compute(changed_files, module_graph)
        scatter = scatter_compute(
            added_symbols, module_graph, threshold=DEFAULT_SCATTER_THRESHOLD
        )
        dup = duplication_for_range(repo_root, changed_files) or DuplicationFinding(
            duplicated_blocks=0, total_lines=0, block_lines=5
        )
        datapoint = ChangeDatapoint(
            month=_month_of(commits[-1].committed_at),
            files_touched=spread.files_touched,
            modules_crossed=spread.modules_crossed,
            scatter_findings=len(scatter.scattered),
            duplication_density=dup.density,
        )
        TrendStore(self._trends_path).append(datapoint)
        return datapoint

    # --- report rendering ------------------------------------------------

    def _render_reports(self, repo_root: Path) -> None:
        """Rewrite escape-ledger.md + erosion-trends.md from the current data."""
        now = datetime.now(UTC)
        records = EscapeLedger(self._ledger_path).read_all()
        merge_count = count_commits_since(repo_root, 30) or 0
        _write(
            repo_root / _ESCAPE_REPORT_REL,
            render_escape_ledger_markdown(
                records, now=now, merge_count_30d=merge_count
            ),
        )
        rows = compute_monthly_trends(TrendStore(self._trends_path).read_all())
        _write(repo_root / _TRENDS_REPORT_REL, render_erosion_trends_markdown(rows))

    # --- HITL / hydraflow-find surface (bounded) ------------------------

    async def _surface_findings(self) -> tuple[int, bool]:
        """File bounded HITL/find issues for low-confidence + aging-unencoded rows."""
        records = EscapeLedger(self._ledger_path).read_all()
        now = datetime.now(UTC)
        threshold_hours = float(self._config.escape_ledger_encoding_age_days) * 24.0
        max_issues = int(self._config.escape_ledger_max_issues_per_tick)
        seen = self._dedup.get()
        to_file, capped = select_findings_to_surface(
            records,
            now=now,
            aging_threshold_hours=threshold_hours,
            already_surfaced=seen,
            max_per_tick=max_issues,
        )
        filed = 0
        for record in to_file:
            title, body = _render_finding(record)
            try:
                await self._prs.create_issue(title, body, labels=_ISSUE_LABELS)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "EscapeLedger: failed to surface finding %s",
                    record.id,
                    exc_info=True,
                )
                continue
            seen = seen | {surfacing_fingerprint(record.id)}
            self._dedup.set_all(seen)
            filed += 1
            logger.info("EscapeLedger: surfaced finding %s", record.id)
        if capped:
            logger.warning(
                "EscapeLedger: per-tick finding cap (%d) reached; remaining "
                "eligible escapes are not surfaced this tick (finding-rate budget)",
                max_issues,
            )
        return filed, capped


def _month_of(iso: str) -> str:
    """``YYYY-MM`` for an ISO-8601 timestamp; current month on parse failure."""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        dt = datetime.now(UTC)
    return f"{dt.year:04d}-{dt.month:02d}"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _short(sha: str) -> str:
    return sha[:7] if sha else "—"


def _render_finding(record: EscapeRecord) -> tuple[str, str]:
    """Render (title, body) for a HITL/find issue about one escape."""
    reason = (
        "low-confidence attribution needs a human label"
        if record.attribution_confidence == "low"
        else "unencoded escape has aged past the encoding threshold"
    )
    title = (
        f"Escape ledger: {record.detection_source} escape "
        f"`{record.detection_ref[:12]}` — {reason}"
    )
    body = (
        "## Evidence (EscapeLedgerLoop, automated)\n\n"
        "| field | value |\n|---|---|\n"
        f"| id | `{record.id}` |\n"
        f"| detected_at | {record.detected_at} |\n"
        f"| detection_source | {record.detection_source} |\n"
        f"| detection_ref | `{record.detection_ref}` |\n"
        f"| originating_pr | {record.originating_pr if record.originating_pr else '—'} |\n"
        f"| originating_merge_sha | {_short(record.originating_merge_sha)} |\n"
        f"| time_to_detection_hours | {record.time_to_detection_hours if record.time_to_detection_hours is not None else '—'} |\n"
        f"| attribution_method | {record.attribution_method} |\n"
        f"| attribution_confidence | {record.attribution_confidence} |\n"
        f"| encoded_as | {record.encoded_as} |\n\n"
        "This is a falsification-instrument finding (escape ledger, #10367). "
        "It is bookkeeping ABOUT the gauntlet, not a gate: the escape already "
        "became work through normal triage. Filed for a human to either "
        "confirm/complete the attribution (low confidence) or point at the "
        "encoding — regression test / stored lesson / detector / ADR — that "
        "should close it out.\n"
    )
    return title, body
