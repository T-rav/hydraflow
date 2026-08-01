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
   (``escape.models.EscapeRecord`` schema).
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
from escape.auto_diagnose import (
    _DIAGNOSES_FILENAME,
    EscapeAutoDiagnoser,
    EscapeDiagnosis,
)
from escape.detect import (
    commit_committed_at,
    commits_for_range,
    count_commits_since,
    detect_escapes,
)
from escape.ledger import ESCAPE_LEDGER_FILENAME, EscapeLedger
from escape.metrics import low_confidence, unencoded_aging
from escape.models import EscapeCandidate, EscapeRecord
from escape.report import render_escape_ledger_markdown
from escape.surfaces import SurfacedIssue, SurfacedIssueLedger
from exception_classify import reraise_on_credit_or_bug
from git_timeouts import GIT_READONLY_TIMEOUT_S
from loop_fitness import FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.escape_ledger")

_ISSUE_LABELS = ["hydraflow-find", "escape-ledger"]

# Generated-report paths (repo-root-relative), gitignored + rewritten each
# tick like docs/arch/generated/loop-fitness.md — NOT arch-regen artifacts.
_ESCAPE_REPORT_REL = Path("docs/arch/generated/escape-ledger.md")
_TRENDS_REPORT_REL = Path("docs/arch/generated/erosion-trends.md")

_TRENDS_FILENAME = "erosion_trends.jsonl"
_SURFACES_FILENAME = "escape_surfaces.jsonl"

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
            timeout=GIT_READONLY_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


# Surfacing reasons. Each is a SEPARATE one-shot budget per escape id: a row
# surfaced once for ``low-confidence`` must still be surfacable when it later
# ages (issue #10503), so the two criteria carry distinct reason-scoped
# fingerprints (``surfaced:low-confidence:<id>`` vs ``surfaced:aging:<id>``).
SURFACE_REASON_LOW_CONFIDENCE = "low-confidence"
SURFACE_REASON_AGING = "aging"

_SURFACE_REASON_TEXT = {
    SURFACE_REASON_LOW_CONFIDENCE: "low-confidence attribution needs a human label",
    SURFACE_REASON_AGING: "unencoded escape has aged past the encoding threshold",
}

# Reason-scoped "Record the resolution" remediation blocks (#10747). Each is
# the answer to its OWN _surfacing_answered predicate: a low-confidence surface
# is answered by bumping attribution_confidence off "low" (--confidence),
# never by --encoded-as alone, so the two reasons must not share one body.
# Key-parity with _SURFACE_REASON_TEXT is enforced by
# TestRenderFinding.test_remediation_map_has_same_keys_as_reason_text_map — a
# new SURFACE_REASON_* needs an entry here too, or it silently falls back to
# the aging instructions below.
_SURFACE_REASON_REMEDIATION = {
    SURFACE_REASON_LOW_CONFIDENCE: (
        "Confirm the attribution with the operator CLI (#10574) — this "
        "appends a resolution row so the low-confidence surface stops "
        "re-firing and this issue is auto-closed on the next tick (#10577):\n\n"
        "```\n"
        'make escape-resolve ARGS="{id} --confidence '
        "<high|medium> --notes '<why>'\"\n"
        "```\n"
    ),
    SURFACE_REASON_AGING: (
        "Point at the encoding with the operator CLI (#10574) — this appends "
        "a resolution row so the aging surface stops re-firing and this "
        "issue is auto-closed on the next tick (#10577):\n\n"
        "```\n"
        'make escape-resolve ARGS="{id} --encoded-as '
        "<regression-test|stored-lesson|detector|adr> --notes '<why>'\"\n"
        "```\n"
    ),
}


def surfacing_fingerprint(escape_id: str, reason: str) -> str:
    """Stable dedup key for a filed HITL/find issue about one escape.

    Scoped to the surfacing *reason* so each eligibility criterion keeps its own
    one-shot budget (issue #10503): a row surfaced once for ``low-confidence``
    still surfaces later when it ages, because ``surfaced:aging:<id>`` is a
    distinct key from ``surfaced:low-confidence:<id>``.
    """
    return f"surfaced:{reason}:{escape_id}"


def select_findings_to_surface(
    records: list[EscapeRecord],
    *,
    now: datetime,
    aging_threshold_hours: float,
    already_surfaced: set[str],
    max_per_tick: int,
) -> tuple[list[tuple[EscapeRecord, str]], bool]:
    """Pure finding-rate budget: which (escape, reason) pairs to surface, capped.

    Eligible = low-confidence attributions (need a human label) + ``none-yet``
    rows older than *aging_threshold_hours* (should have been encoded by now).
    Each criterion is a SEPARATE one-shot budget: a row eligible under BOTH
    criteria can surface once per reason (never collapsed by id), and a
    (record, reason) pair is skipped only when its reason-scoped fingerprint is
    already in *already_surfaced* — repeat noise from the SAME reason stays
    suppressed. Returns ``(to_file, capped)`` where ``to_file`` is at most
    *max_per_tick* ``(record, reason)`` pairs and ``capped`` is True when
    eligible exceeded the cap. This caps issue filing under a synthetic flood —
    recording rows is never capped, only filing.
    """
    eligible: list[tuple[EscapeRecord, str]] = []
    seen: set[tuple[str, str]] = set()
    aging = unencoded_aging(records, now, threshold_hours=aging_threshold_hours)
    candidates: list[tuple[EscapeRecord, str]] = [
        *((r, SURFACE_REASON_LOW_CONFIDENCE) for r in low_confidence(records)),
        *((r, SURFACE_REASON_AGING) for r in aging),
    ]
    for record, reason in candidates:
        key = (record.id, reason)
        if key in seen:
            continue
        seen.add(key)
        if surfacing_fingerprint(record.id, reason) in already_surfaced:
            continue
        eligible.append((record, reason))
    capped = len(eligible) > max_per_tick
    return eligible[:max_per_tick], capped


def _surfacing_answered(link: SurfacedIssue, record: EscapeRecord) -> bool:
    """Is the reason *link* was surfaced for now answered by *record*?

    Each surfacing reason has an independent "answered" predicate read against
    the current (collapsed) ledger row: a ``low-confidence`` surface is answered
    once a human bumps the mechanical confidence off ``low``; an ``aging``
    surface is answered once the escape terminates in an encoding
    (``encoded_as`` is no longer ``none-yet``). Any other reason string is
    treated as unanswered — the link stays open rather than closing on a guess.
    """
    if link.reason == SURFACE_REASON_LOW_CONFIDENCE:
        return record.attribution_confidence != "low"
    if link.reason == SURFACE_REASON_AGING:
        return record.encoded_as != "none-yet"
    return False


def answered_surfacings(
    open_links: list[SurfacedIssue],
    latest_records: dict[str, EscapeRecord],
) -> list[SurfacedIssue]:
    """Pure policy: which OPEN surfacing links now have an answered ledger row.

    *latest_records* maps every escape id to the row that currently represents
    its commit (``read_latest_index`` — ``escape_by_id``), NOT the id-projected
    ``read_latest`` view: ``read_latest`` collapses by ``detection_ref`` and so
    drops the ids of siblings it folds away, which would strand a link filed
    under a folded-away id (#10731). A link whose escape id is absent from the
    map (or whose reason is not yet answered) is left open — the reconcile pass
    only closes an issue once the resolution that answers its surfacing reason
    (a human bump, or a stronger sibling for the same commit) has landed.
    """
    answered: list[SurfacedIssue] = []
    for link in open_links:
        record = latest_records.get(link.escape_id)
        if record is not None and _surfacing_answered(link, record):
            answered.append(link)
    return answered


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
        auto_diagnoser: EscapeAutoDiagnoser | None = None,
    ) -> None:
        super().__init__(worker_name="escape_ledger", config=config, deps=deps)
        self._prs = pr_manager
        self._state = state
        self._dedup = dedup
        # Injected only when escape_ledger_auto_diagnose_enabled (ADR-0115); the
        # default build leaves it None and the human surface fires as before.
        self._auto_diagnoser = auto_diagnoser

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
        return self._config.diagnostics_dir / ESCAPE_LEDGER_FILENAME

    @property
    def _trends_path(self) -> Path:
        return self._config.diagnostics_dir / _TRENDS_FILENAME

    @property
    def _surfaces_path(self) -> Path:
        return self._config.diagnostics_dir / _SURFACES_FILENAME

    @property
    def _diagnoses_path(self) -> Path:
        return self._config.diagnostics_dir / _DIAGNOSES_FILENAME

    # --- main tick -------------------------------------------------------

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.escape_ledger_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        # Reconcile BEFORE _resolve_range's early exits: a human resolution
        # almost always lands on a QUIET tick (no new commits merged), which
        # _resolve_range would short-circuit at ``no_new_commits`` before any
        # GitHub work — so a close step folded into the per-commit path would
        # never run on exactly the ticks that matter (#10577). Every status
        # dict below therefore carries the ``closed`` count.
        closed = await self._reconcile_surfaced_issues()

        resolved = self._resolve_range()
        if isinstance(resolved, dict):
            resolved["closed"] = closed
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
            "closed": closed,
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
        records = EscapeLedger(self._ledger_path).read_latest()
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
        records = EscapeLedger(self._ledger_path).read_latest()
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
        # ADR-0115: before filing a LOW-CONFIDENCE finding for a human, run the
        # machine auto-diagnose pass. A row it resolves (real+regression-encoded)
        # or dismisses (clear false positive) is dropped from the file list — the
        # human sees only the genuinely INCONCLUSIVE residue.
        to_file = await self._auto_diagnose(to_file)
        surfaces = SurfacedIssueLedger(self._surfaces_path)
        filed = 0
        for record, reason in to_file:
            title, body = _render_finding(record, reason)
            try:
                issue_number = await self._prs.create_issue(
                    title, body, labels=_ISSUE_LABELS
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "EscapeLedger: failed to surface finding %s (%s)",
                    record.id,
                    reason,
                    exc_info=True,
                )
                continue
            if not issue_number:
                # create_issue's documented 0-sentinel: the gh call failed
                # WITHOUT raising (ports.py). Leave the reason-scoped surfacing
                # fingerprint UNSPENT so the next tick retries — mirrors
                # adr_touchpoint_auditor_loop's "returned 0 → don't record"
                # guard (#10585).
                logger.warning(
                    "EscapeLedger: create_issue returned 0 (sentinel) for "
                    "finding %s (%s); leaving surfacing fingerprint unspent, "
                    "will retry next tick",
                    record.id,
                    reason,
                )
                continue
            fingerprint = surfacing_fingerprint(record.id, reason)
            seen = seen | {fingerprint}
            self._dedup.set_all(seen)
            # Persist the number create_issue just returned so a later
            # resolution can close THIS issue (#10577). The dedup fingerprint
            # is a bare string and cannot hold it; the sidecar link can.
            surfaces.append_surfaced(
                fingerprint=fingerprint,
                escape_id=record.id,
                reason=reason,
                issue_number=int(issue_number),
                filed_at=now.isoformat(),
            )
            filed += 1
            logger.info("EscapeLedger: surfaced finding %s (%s)", record.id, reason)
        if capped:
            logger.warning(
                "EscapeLedger: per-tick finding cap (%d) reached; remaining "
                "eligible escapes are not surfaced this tick (finding-rate budget)",
                max_issues,
            )
        return filed, capped

    # --- machine auto-diagnose (ADR-0115) -------------------------------

    async def _auto_diagnose(
        self, to_file: list[tuple[EscapeRecord, str]]
    ) -> list[tuple[EscapeRecord, str]]:
        """Filter *to_file*: machine-resolve/dismiss low-confidence findings.

        Only ``SURFACE_REASON_LOW_CONFIDENCE`` findings are diagnosed (the aging
        surface asks for an encoding, a different human decision). A finding the
        diagnoser resolves or dismisses is dropped; the human sees only the
        INCONCLUSIVE residue. Disabled by config → unchanged. A diagnose failure
        keeps the finding for the human (fail-safe).
        """
        if not self._config.escape_ledger_auto_diagnose_enabled:
            return to_file
        diagnoser = self._get_auto_diagnoser()
        residue: list[tuple[EscapeRecord, str]] = []
        for record, reason in to_file:
            if reason != SURFACE_REASON_LOW_CONFIDENCE:
                residue.append((record, reason))
                continue
            try:
                verdict = await diagnoser.diagnose(record)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "EscapeLedger: auto-diagnose failed for %s — filing the "
                    "human surface (fail-safe)",
                    record.id,
                    exc_info=True,
                )
                residue.append((record, reason))
                continue
            if verdict is EscapeDiagnosis.INCONCLUSIVE:
                residue.append((record, reason))
        return residue

    def _get_auto_diagnoser(self) -> EscapeAutoDiagnoser:
        """Return the injected diagnoser, or lazily build one (production path)."""
        if self._auto_diagnoser is None:
            self._auto_diagnoser = EscapeAutoDiagnoser(
                repo_root=Path(self._config.repo_root),
                prs=self._prs,
                ledger_path=self._ledger_path,
                diagnoses_path=self._diagnoses_path,
            )
        return self._auto_diagnoser

    # --- reconcile answered surfaces (close stranded HITL issues) --------

    async def _reconcile_surfaced_issues(self) -> int:
        """Comment on + close each surfaced HITL issue whose row is now answered.

        Ties an answered ledger row back to the issue ``_surface_findings``
        filed for it (#10577): for every OPEN link whose surfacing reason is now
        satisfied — ``low-confidence`` bumped off ``low``, or ``aging`` given an
        encoding — post one comment naming the resolution, close the issue, and
        append a terminal ``closed`` row so the link never re-fires. Returns the
        number of issues closed this tick.

        A failed ``close_issue`` (returns ``False`` or raises a non-credit
        error) leaves the link OPEN for a later retry rather than marking it
        closed; ``CreditExhaustedError`` propagates via ``reraise_on_credit_or_bug``.
        """
        surfaces = SurfacedIssueLedger(self._surfaces_path)
        open_links = surfaces.open_links()
        if not open_links:
            return 0
        # read_latest_index (NOT `{r.id: r for r in read_latest()}`): read_latest
        # collapses by detection_ref and drops the ids of folded-away siblings, so
        # a link filed under a low-confidence id later superseded by a stronger
        # sibling for the same commit would never reconcile (#10731). The index
        # maps every id to its detection_ref winner.
        latest = EscapeLedger(self._ledger_path).read_latest_index()
        answered = answered_surfacings(open_links, latest)
        closed = 0
        for link in answered:
            record = latest[link.escape_id]
            try:
                await self._prs.post_comment(
                    link.issue_number, _resolution_comment(record, link.reason)
                )
                ok = await self._prs.close_issue(link.issue_number, reason="completed")
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "EscapeLedger: failed to close surfaced issue #%d for "
                    "resolved escape %s (%s); leaving link open for retry",
                    link.issue_number,
                    link.escape_id,
                    link.reason,
                    exc_info=True,
                )
                continue
            if not ok:
                logger.warning(
                    "EscapeLedger: close_issue returned False for #%d (%s); "
                    "leaving link open for retry",
                    link.issue_number,
                    link.escape_id,
                )
                continue
            surfaces.append_closed(link, closed_at=datetime.now(UTC).isoformat())
            closed += 1
            logger.info(
                "EscapeLedger: closed surfaced issue #%d for resolved escape %s (%s)",
                link.issue_number,
                link.escape_id,
                link.reason,
            )
        return closed


def _resolution_comment(record: EscapeRecord, reason: str) -> str:
    """Render the close comment for a resolved escape's HITL issue (#10577).

    Names the resolution that answered the surfacing so the closed issue leaves
    an audit trail: an ``aging`` surface reports the encoding it terminated in,
    a ``low-confidence`` surface reports the confidence a human confirmed it at.
    """
    if reason == SURFACE_REASON_AGING:
        detail = f"encoded as `{record.encoded_as}`"
    else:
        detail = f"attribution confidence is now `{record.attribution_confidence}`"
    return (
        "## Resolved (EscapeLedgerLoop, automated)\n\n"
        f"Escape `{record.id}` has been answered — {detail}. Closing this "
        "escape-ledger finding so no stale HITL surface is left behind after "
        "the human resolution (#10577).\n"
    )


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


def _render_finding(record: EscapeRecord, reason: str) -> tuple[str, str]:
    """Render (title, body) for a HITL/find issue about one escape.

    *reason* is the surfacing criterion (``SURFACE_REASON_*``) that made the row
    eligible this tick; the title reflects it so an aging finding reads as aging
    even for a low-confidence row (issue #10503), rather than inferring the text
    from ``attribution_confidence``. The "Record the resolution" block is
    likewise reason-selected (#10747): a low-confidence surface is answered by
    ``--confidence``, an aging surface by ``--encoded-as`` — prescribing the
    wrong one would leave the surface's own answered-predicate unsatisfied.
    """
    reason_text = _SURFACE_REASON_TEXT.get(
        reason, "unencoded escape has aged past the encoding threshold"
    )
    remediation = _SURFACE_REASON_REMEDIATION.get(
        reason, _SURFACE_REASON_REMEDIATION[SURFACE_REASON_AGING]
    ).format(id=record.id)
    title = (
        f"Escape ledger: {record.detection_source} escape "
        f"`{record.detection_ref[:12]}` — {reason_text}"
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
        f"| encoded_as | {record.encoded_as} |\n"
        f"| notes | {record.notes or '—'} |\n\n"
        "This is a falsification-instrument finding (escape ledger, #10367). "
        "It is bookkeeping ABOUT the gauntlet, not a gate: the escape already "
        "became work through normal triage. Filed for a human to either "
        "confirm/complete the attribution (low confidence) or point at the "
        "encoding — regression test / stored lesson / detector / ADR — that "
        "should close it out.\n\n"
        "### Record the resolution\n\n" + remediation
    )
    return title, body
