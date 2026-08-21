"""Background worker loop — ErosionMetricsLoop (#10107, epic #10104).

**v1, PROVISIONAL** — cadence, thresholds, and dedup granularity are all
first-cut choices; see ``erosion.spread`` / ``erosion.scatter``'s own
"PROVISIONAL, not the final definition" docstrings, which this loop
inherits without change.

A caretaker (ADR-0029) that runs the two erosion sensors — change-spread
(#10105, ``erosion.spread``) and concept-scatter (#10106, ``erosion.scatter``)
— over commits merged to the base branch since the last tick, and files any
above-baseline finding back into triage as a ``hydraflow-find`` issue.

**Pattern B, deliberately unlike ADR-0101's Pattern A.** ADR-0101's
``DisturbanceDampenerLoop`` dispatches a coding agent to fix each violation
directly and prunes its own baseline in the same PR — its own "Alternatives
considered" section explicitly rejects filing issues instead ("Pattern B"),
reasoning that a bounded, single-file lint/mock-spec fix does not need a
human/queue-mediated hop. Erosion findings are the opposite shape: a
change-spread or concept-scatter reading is a signal about how a MERGED
refactor rippled across the codebase, not a mechanical, obviously-safe edit
an agent can apply — whether the spread was an intentional architecture
change or genuine shotgun surgery needs a human to look at the diff and
decide. So this loop takes the path ADR-0101 rejected for its own use case:
it senses and reports (the outer-loop equivalent of ``hydraflow-find``
itself), it never opens a fix PR. ADR-0104 (auto-tightening ratchet) is the
adjacent baseline-governance precedent this loop's baseline usage mirrors
(scalar norm for change-spread, per-signature ratchet for concept-scatter)
without itself being a tightening actuator — this loop only files, it does
not lock in gains.

**Whole-tree class issues (mass + suite hygiene).** Two readings are not
change-scoped — ``erosion.mass`` (god files / god classes by size) and
``erosion.suite_hygiene`` (parametrize candidates / cross-file duplicate
tests) measure the tree as it is. Each files ONE standing ``hydraflow-find``
class issue carrying the ``find_class_key`` marker and a ``## Folded sites``
roster: open + unchanged roster → nothing; open + changed roster → body
refreshed in place; closed while the reading is still non-empty → re-filed
(closing without fixing brings it back). The PR-time ratchets
(``tests/architecture/test_mass_ratchet.py``,
``test_suite_hygiene_ratchet.py``) stop NEW offenders; this loop keeps the
burn-down of the grandfathered ones on the board.

**Cursor + dedup design.** ``state.get_erosion_last_processed_sha()``
persists the base-branch HEAD SHA this loop last finished analyzing
(``state/_erosion_metrics.py``). Each tick reads the CURRENT HEAD sha of
``config.repo_root`` (a fresh, uncached local ``git rev-parse HEAD`` —
unlike ``git_revision.get_boot_sha()``, which is cached once at process
start and deliberately never re-read): if the cursor is empty (fresh
install), it is primed to the current sha with no analysis, mirroring
``LogIngestLoop``'s cursor-priming convention — a fresh install must not
back-analyze the repo's entire history. If the cursor already equals the
current sha, there is nothing new (dedup by SHA — the whole point of the
cursor is that a commit range is analyzed exactly once, never twice).
Otherwise ``last_sha..current_sha`` is the range handed to both sensors'
git adapters (``changed_files_for_range``, ``added_symbols_for_range``);
the cursor advances to ``current_sha`` unconditionally at the end of a
successful tick (even if some candidates could not be filed because of the
per-tick cap — see below), so cursor identity alone can never cause a
duplicate re-analysis of an already-seen range. A SEPARATE
``DedupStore``-backed set of filed finding-fingerprints (keyed by
commit-range + subject) guards against re-filing the same finding after a
retry within one tick or a process restart — the two mechanisms are
complementary, not redundant: the cursor prevents RE-ANALYSIS, the dedup
set prevents RE-FILING.

**Baseline thresholds.** Both sensors are gated by their own
version-controlled baseline module (mirroring ``disturbance.baseline``'s
convention, per each module's own docstring): ``erosion.baseline``'s
single scalar ``max_spread_ratio`` norm for change-spread, and
``erosion.scatter_baseline``'s per-symbol ratchet-diff for concept-scatter.
Neither baseline file is committed by this change — until an operator
snapshots ``erosion/baselines/spread.yaml`` / ``scatter.yaml`` with this
repo's actual observed norms, the sensors' own conservative fallback
defaults apply (``DEFAULT_MAX_SPREAD_RATIO = 1.0``, which is the
change-spread ratio's mathematical ceiling — a file can map to at most one
module, so ``modules_crossed <= files_touched`` always, and the finding is
only flagged on a STRICT excess — so change-spread cannot fire at all
until a human snapshots a tighter norm; and ``DEFAULT_SCATTER_THRESHOLD =
3`` distinct modules for concept-scatter, which fires on its own). This is
the "kill-switch defaults ON-but-conservative" posture called for by the
epic: the loop is live from the start, but effectively silent on the
change-spread dimension until deliberately tuned.

**Bounded per tick.** ``erosion_metrics_max_issues_per_tick`` caps how many
issues one tick may file; overflow candidates for that tick's commit range
are logged and NOT carried over (the cursor still advances) — this is a
rate limit on filing volume, not a durable backlog, matching the fleet's
other bounded-per-tick caretaker loops (e.g. ``pr_red_rerun_max_attempts``,
``disturbance_dampener_max_prs_per_tick``). In practice this should rarely
bind: a reasonably tight interval keeps each tick's commit range small.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from arch.extractors.modules import extract_module_graph
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from erosion.baseline import is_flagged as spread_is_flagged
from erosion.baseline import load_spread_baseline
from erosion.mass import collect_sources
from erosion.mass import compute as mass_compute
from erosion.mass_baseline import grown as mass_grown
from erosion.mass_baseline import load_mass_baseline
from erosion.scatter import DEFAULT_SCATTER_THRESHOLD, added_symbols_for_range
from erosion.scatter import compute as scatter_compute
from erosion.scatter_baseline import diff as scatter_diff
from erosion.scatter_baseline import load_scatter_baseline
from erosion.spread import changed_files_for_range
from erosion.spread import compute as spread_compute
from erosion.suite_hygiene import collect_tests
from erosion.suite_hygiene import compute as suite_compute
from exception_classify import reraise_on_credit_or_bug
from find_class_key import compute_class_key, render_marker
from git_timeouts import GIT_READONLY_TIMEOUT_S
from loop_fitness import FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:
    from arch._models import ModuleGraph
    from erosion.models import ScatteredSymbol
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.erosion_metrics")

_ISSUE_LABELS = ["hydraflow-find", "erosion-metrics"]

# Version-controlled baseline paths, repo-root-relative — mirror
# disturbance.registry.BASELINE_DIR's convention. Neither file is committed
# by this change (see module docstring); both loaders fall back to their
# own conservative defaults when the path doesn't exist yet.
_SPREAD_BASELINE_REL = Path("erosion") / "baselines" / "spread.yaml"
_SCATTER_BASELINE_REL = Path("erosion") / "baselines" / "scatter.yaml"


def _current_head_sha(repo_root: Path) -> str | None:
    """Return *repo_root*'s current HEAD sha, or ``None`` on any git failure.

    Deliberately NOT cached (unlike ``git_revision.get_boot_sha()``): this
    loop needs to observe HEAD advancing across ticks as new commits land,
    where the boot-sha cache exists precisely to freeze a single reading.
    Failure-tolerant like every other git adapter in this family — git
    missing, non-zero exit, timeout, or "not a repo" all return ``None``.
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


def spread_finding_fingerprint(commit_range: str) -> str:
    """Stable dedup key for a change-spread finding over one commit range."""
    return f"spread:{commit_range}"


def scatter_finding_fingerprint(commit_range: str, symbol: str) -> str:
    """Stable dedup key for one scattered symbol within one commit range.

    Folds in *commit_range* (not just *symbol*): a distinct incident of the
    same symbol name being scattered again in an unrelated FUTURE range is
    a new occurrence worth its own issue, mirroring GateHealthLoop's
    ``suspected_hang`` fingerprint exception (each hang is a distinct
    incident, not a standing defect deduped forever).
    """
    return f"scatter:{commit_range}:{symbol}"


# Repo-wide (not change-scoped) readings filed as ONE class issue per kind — the
# mass sensor (god files / god classes) and the suite-hygiene sensor
# (parametrize candidates / cross-file duplicate tests). Each carries the
# ``find_class_key`` marker + a ``## Folded sites`` roster so human finders and
# ``scripts/find_class_check.py`` fold into it rather than filing siblings.
_MASS_BASELINE_REL = Path("disturbance") / "baselines" / "mass.yaml"
_CLASS_SOURCE = "erosion_metrics"
_CLASS_NEEDLES: dict[str, str] = {
    "mass": "god class god file mass decomposition oversized",
    "suite_hygiene": "test suite structural redundancy parametrize duplicate tests",
}
#: Roster lines per class issue body — bounded so a body can never approach
#: GitHub's 65k limit; the counts in the evidence table stay exact.
_ROSTER_LIMIT = 60
_CLOSED_STATES = frozenset({"COMPLETED", "NOT_PLANNED"})


def class_issue_fingerprint(kind: str, issue_number: int, digest: str) -> str:
    """Dedup entry for the one open class issue of *kind*: ``kind:class:#N:<roster digest>``."""
    return f"{kind}:class:#{issue_number}:{digest}"


def find_class_issue_entry(seen: set[str], kind: str) -> tuple[int, str] | None:
    """Return ``(issue_number, digest)`` for *kind*'s recorded class issue, or None."""
    prefix = f"{kind}:class:#"
    for entry in sorted(seen):
        if not entry.startswith(prefix):
            continue
        number, _, digest = entry[len(prefix) :].partition(":")
        if number.isdigit():
            return int(number), digest
    return None


def _roster_digest(lines: list[str]) -> str:
    """Stable 12-hex digest of a roster — changes iff the rendered roster changes."""
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()[:12]


def _site_line(title: str, site: str) -> str:
    """One ``## Folded sites`` bullet in the exact shape ``find_class_key`` parses back."""
    clean_title = " ".join(title.replace("`", "'").split())
    clean_site = " ".join(site.replace("`", "'").split())
    return f"- {clean_title} (site: `{clean_site}`)"


class ErosionMetricsLoop(BaseBackgroundLoop):
    """Files change-spread/concept-scatter drift on merged commits to triage.

    v1: analyzes ``last_processed_sha..HEAD`` as a single range per tick
    (see module docstring for the cursor/dedup/baseline design). Read +
    issue-filing only — this loop never edits code or opens a PR.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        state: StateTracker,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="erosion_metrics", config=config, deps=deps)
        self._prs = pr_manager
        self._state = state
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.erosion_metrics_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only sensor: files evidence issues, owns no proposal/
        # acceptance lifecycle to score — HOUSEKEEPING per ADR-0093,
        # mirrors gate_health_loop.py / pr_red_repair_loop.py.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.erosion_metrics_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        resolved = self._resolve_range()
        if isinstance(resolved, dict):
            return resolved
        repo_root, commit_range, changed_files, added_symbols, current_sha = resolved

        module_graph = extract_module_graph(repo_root / "src")
        candidates = self._compute_candidates(
            commit_range, changed_files, added_symbols, module_graph
        )
        class_candidates = self._repo_wide_candidates(repo_root)
        filed, capped = await self._file_findings(candidates)
        class_filed, refreshed, class_capped = await self._reconcile_class_issues(
            class_candidates, already_filed=filed
        )
        filed += class_filed
        capped = capped or class_capped

        # Advance the cursor unconditionally: this range has been fully
        # analyzed (dedup by SHA), independent of the per-tick filing cap.
        self._state.set_erosion_last_processed_sha(current_sha)

        result: dict[str, Any] = {
            "status": "ok",
            "range": commit_range,
            "changed_files": len(changed_files),
            "candidates": len(candidates) + len(class_candidates),
            "filed": filed,
            "refreshed": refreshed,
            "capped": capped,
        }
        for candidate in class_candidates:
            result[candidate["kind"]] = candidate["summary"]
        return result

    def _resolve_range(
        self,
    ) -> tuple[Path, str, list[str], dict[str, list[str]], str] | dict[str, Any]:
        """Resolve the new commit range to analyze, or an early-exit status dict.

        Returns ``(repo_root, commit_range, changed_files, added_symbols,
        current_sha)`` on success. Advances/primes the cursor itself on the
        early-exit "baseline_established" path (first tick ever); every
        other early exit leaves the cursor untouched so the next tick
        retries cleanly.
        """
        repo_root = Path(self._config.repo_root)
        current_sha = _current_head_sha(repo_root)
        if current_sha is None:
            return {"status": "head_sha_unavailable"}

        last_sha = self._state.get_erosion_last_processed_sha()
        if not last_sha:
            self._state.set_erosion_last_processed_sha(current_sha)
            return {"status": "baseline_established", "sha": current_sha}
        if current_sha == last_sha:
            return {"status": "no_new_commits", "sha": current_sha}

        commit_range = f"{last_sha}..{current_sha}"
        changed_files = changed_files_for_range(repo_root, commit_range)
        if changed_files is None:
            return {"status": "diff_unavailable", "range": commit_range}
        added_symbols = added_symbols_for_range(repo_root, commit_range)
        if added_symbols is None:
            return {"status": "diff_unavailable", "range": commit_range}

        return repo_root, commit_range, changed_files, added_symbols, current_sha

    def _compute_candidates(
        self,
        commit_range: str,
        changed_files: list[str],
        added_symbols: dict[str, list[str]],
        module_graph: ModuleGraph,
    ) -> list[dict[str, Any]]:
        """Run both sensors over one commit range; return above-baseline candidates."""
        candidates: list[dict[str, Any]] = []
        repo_root = Path(self._config.repo_root)

        spread_finding = spread_compute(changed_files, module_graph)
        spread_baseline = load_spread_baseline(repo_root / _SPREAD_BASELINE_REL)
        if spread_is_flagged(spread_finding, spread_baseline):
            candidates.append(
                {
                    "kind": "spread",
                    "fingerprint": spread_finding_fingerprint(commit_range),
                    "commit_range": commit_range,
                    "finding": spread_finding,
                    "baseline": spread_baseline,
                }
            )

        scatter_finding = scatter_compute(
            added_symbols, module_graph, threshold=DEFAULT_SCATTER_THRESHOLD
        )
        scatter_baseline_map = load_scatter_baseline(repo_root / _SCATTER_BASELINE_REL)
        ratchet = scatter_diff(scatter_finding, scatter_baseline_map)
        symbols_by_name: dict[str, ScatteredSymbol] = {
            s.symbol: s for s in scatter_finding.scattered
        }
        for symbol in sorted(ratchet.new):
            scattered = symbols_by_name.get(symbol)
            if scattered is None:
                continue  # defensive: diff() only returns names compute() saw
            candidates.append(
                {
                    "kind": "scatter",
                    "fingerprint": scatter_finding_fingerprint(commit_range, symbol),
                    "commit_range": commit_range,
                    "symbol": scattered,
                    "excess": ratchet.new[symbol],
                    "threshold": scatter_finding.threshold,
                }
            )

        return candidates

    def _repo_wide_candidates(self, repo_root: Path) -> list[dict[str, Any]]:
        """Whole-repo mass + suite-hygiene readings, one class candidate per non-empty kind.

        Not change-scoped like spread/scatter (size is a property of the tree,
        not of a diff), but tied to the same cursor so each runs at most once
        per tick that saw new commits.
        """
        candidates: list[dict[str, Any]] = []
        src_dir = repo_root / "src"
        if src_dir.is_dir():
            mass = mass_compute(collect_sources(src_dir))
            if not mass.is_empty:
                baseline = load_mass_baseline(repo_root / _MASS_BASELINE_REL)
                roster = [
                    _site_line(f"{c.key} — {c.loc} LOC, {c.methods} methods", c.key)
                    for c in mass.god_classes
                ] + [
                    _site_line(f"{g.path} — {g.loc} LOC (file)", g.path)
                    for g in mass.god_files
                ]
                candidates.append(
                    {
                        "kind": "mass",
                        "class_issue": True,
                        "finding": mass,
                        "growth": mass_grown(mass, baseline),
                        "roster": roster,
                        "digest": _roster_digest(roster),
                        "summary": {
                            "digest": _roster_digest(roster),
                            "god_classes": len(mass.god_classes),
                            "god_files": len(mass.god_files),
                        },
                    }
                )
        tests_dir = repo_root / "tests"
        if tests_dir.is_dir():
            suite = suite_compute(collect_tests(tests_dir))
            if not suite.is_empty:
                roster = [
                    _site_line(
                        f"{g.path}: {', '.join(g.names)}", f"{g.path}::{g.names[0]}"
                    )
                    for g in suite.parametrize_groups
                ] + [
                    _site_line(
                        f"{d.name} duplicated in {', '.join(d.paths)}",
                        f"{d.paths[0]}::{d.name}",
                    )
                    for d in suite.cross_file_duplicates
                ]
                candidates.append(
                    {
                        "kind": "suite_hygiene",
                        "class_issue": True,
                        "finding": suite,
                        "roster": roster,
                        "digest": _roster_digest(roster),
                        "summary": {
                            "digest": _roster_digest(roster),
                            "parametrize_copies": suite.parametrize_copies,
                            "cross_file_duplicates": len(suite.cross_file_duplicates),
                            "total_tests": suite.total_tests,
                        },
                    }
                )
        return candidates

    async def _reconcile_class_issues(
        self, candidates: list[dict[str, Any]], *, already_filed: int
    ) -> tuple[int, int, bool]:
        """File, refresh, or leave alone the one class issue per kind; return (filed, refreshed, capped).

        Three-way dedup on the recorded ``kind:class:#N:<digest>`` entry:
        OPEN with the same roster digest → nothing; OPEN with a changed
        digest → rewrite the body (roster refresh, no new issue); CLOSED while
        the reading is still non-empty → file again (closing without fixing
        brings it back next tick). An unreadable state (``""`` on a gh
        error) is a no-op for this tick — a reporter fails quiet, not loud.
        """
        max_issues = int(self._config.erosion_metrics_max_issues_per_tick)
        filed = 0
        refreshed = 0
        capped = False
        for candidate in candidates:
            kind = candidate["kind"]
            digest = candidate["digest"]
            seen = self._dedup.get()
            entry = find_class_issue_entry(seen, kind)
            title, body = _render_finding(candidate)
            if entry is not None:
                number, recorded_digest = entry
                state = await self._prs.get_issue_state(number)
                if state == "OPEN" and recorded_digest == digest:
                    continue
                if state == "OPEN":
                    try:
                        await self._prs.update_issue_body(number, body)
                    except Exception as exc:
                        reraise_on_credit_or_bug(exc)
                        logger.warning(
                            "ErosionMetrics: failed to refresh class issue #%d",
                            number,
                            exc_info=True,
                        )
                        continue
                    self._dedup.set_all(
                        (
                            seen
                            - {class_issue_fingerprint(kind, number, recorded_digest)}
                        )
                        | {class_issue_fingerprint(kind, number, digest)}
                    )
                    refreshed += 1
                    logger.info(
                        "ErosionMetrics: refreshed %s class issue #%d", kind, number
                    )
                    continue
                if state not in _CLOSED_STATES:
                    continue  # unknown / error: leave the entry, retry next tick
            if already_filed + filed >= max_issues:
                capped = True
                continue
            try:
                number = await self._prs.create_issue(title, body, labels=_ISSUE_LABELS)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "ErosionMetrics: failed to file %s class issue", kind, exc_info=True
                )
                continue
            if not number:
                # PRManager.create_issue returns 0 on failure without raising.
                # Recording "#0" would make every later tick read an unresolvable
                # issue as "open, unreadable" and never file this kind again.
                logger.warning(
                    "ErosionMetrics: create_issue returned no number for %s class "
                    "issue; retrying next tick",
                    kind,
                )
                continue
            stale = {e for e in seen if e.startswith(f"{kind}:class:#")}
            self._dedup.set_all(
                (seen - stale) | {class_issue_fingerprint(kind, number, digest)}
            )
            filed += 1
            logger.info("ErosionMetrics: filed %s class issue #%d", kind, number)
        if capped:
            logger.warning(
                "ErosionMetrics: per-tick cap (%d) reached before every class issue "
                "was filed; the rest retry next tick",
                max_issues,
            )
        return filed, refreshed, capped

    async def _file_findings(
        self, candidates: list[dict[str, Any]]
    ) -> tuple[int, bool]:
        """File deduped candidates up to the per-tick cap; return (filed, capped)."""
        max_issues = int(self._config.erosion_metrics_max_issues_per_tick)
        seen = self._dedup.get()
        filed = 0
        capped = False
        for candidate in candidates:
            fingerprint = candidate["fingerprint"]
            if fingerprint in seen:
                continue
            if filed >= max_issues:
                capped = True
                continue
            title, body = _render_finding(candidate)
            try:
                await self._prs.create_issue(title, body, labels=_ISSUE_LABELS)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "ErosionMetrics: failed to file finding %s",
                    fingerprint,
                    exc_info=True,
                )
                continue
            seen = seen | {fingerprint}
            self._dedup.set_all(seen)
            filed += 1
            logger.info("ErosionMetrics: filed finding %s", fingerprint)
        if capped:
            logger.warning(
                "ErosionMetrics: per-tick cap (%d) reached; some candidates "
                "were not filed this tick and are not carried over",
                max_issues,
            )
        return filed, capped


def _short(sha: str) -> str:
    return sha[:7]


def _render_finding(candidate: dict[str, Any]) -> tuple[str, str]:
    """Render (title, body) for one erosion finding, evidence table included."""
    if candidate["kind"] == "mass":
        return _render_mass(candidate)
    if candidate["kind"] == "suite_hygiene":
        return _render_suite_hygiene(candidate)

    commit_range = candidate["commit_range"]
    last_sha, _, current_sha = commit_range.partition("..")
    short_range = f"{_short(last_sha)}..{_short(current_sha)}"

    if candidate["kind"] == "spread":
        finding = candidate["finding"]
        baseline = candidate["baseline"]
        title = (
            f"Erosion: change-spread ratio {finding.spread_ratio:.2f} exceeds "
            f"baseline {baseline.max_spread_ratio:.2f} ({short_range})"
        )
        body = (
            "## Evidence (ErosionMetricsLoop, automated)\n\n"
            f"| metric | value |\n|---|---|\n"
            f"| commit range | `{commit_range}` |\n"
            f"| files touched | {finding.files_touched} |\n"
            f"| modules crossed | {finding.modules_crossed} |\n"
            f"| spread ratio | {finding.spread_ratio:.2f} |\n"
            f"| baseline max | {baseline.max_spread_ratio:.2f} |\n"
            f"| modules | {', '.join(finding.modules) or '(none)'} |\n\n"
            "This merged change's file/module footprint (change-spread "
            "sensor, #10105) exceeds the baselined norm — a shotgun-surgery "
            "signal: a change touching few files but spanning "
            "disproportionately many modules for that size.\n\n"
            "v1 heuristic, PROVISIONAL (epic #10104) — this is an "
            "outer-loop finding (Pattern B; see ADR-0101's Alternatives "
            "section for the deliberate contrast with its own Pattern-A "
            "fix-PR actuator). Filed for human triage: whether this spread "
            "was an intentional architecture change or genuine shotgun "
            "surgery needs a human to look at the diff.\n"
        )
        return title, body

    symbol = candidate["symbol"]
    title = (
        f"Erosion: symbol `{symbol.symbol}` scattered across "
        f"{len(symbol.modules)} modules ({short_range})"
    )
    body = (
        "## Evidence (ErosionMetricsLoop, automated)\n\n"
        f"| metric | value |\n|---|---|\n"
        f"| commit range | `{commit_range}` |\n"
        f"| symbol | `{symbol.symbol}` |\n"
        f"| modules crossed | {len(symbol.modules)} |\n"
        f"| threshold | {candidate['threshold']} |\n"
        f"| modules | {', '.join(symbol.modules) or '(none)'} |\n"
        f"| files | {', '.join(symbol.files) or '(none)'} |\n\n"
        "A single merged change independently introduced this new symbol "
        "name in multiple distinct modules — a shotgun-duplication / "
        "coupling-erosion smell (concept-scatter sensor, #10106).\n\n"
        "v1 heuristic, PROVISIONAL (epic #10104) — this is an outer-loop "
        "finding (Pattern B; see ADR-0101's Alternatives section for the "
        "deliberate contrast with its own Pattern-A fix-PR actuator). "
        "Filed for human triage: whether these should be unified into one "
        "shared definition needs a human judgment call.\n"
    )
    return title, body


def _roster_section(roster: list[str]) -> str:
    shown = roster[:_ROSTER_LIMIT]
    section = "## Folded sites\n" + "\n".join(shown) + "\n"
    if len(roster) > len(shown):
        section += (
            f"\n_… and {len(roster) - len(shown)} more (counts above are exact)._\n"
        )
    return section


def _render_mass(candidate: dict[str, Any]) -> tuple[str, str]:
    finding = candidate["finding"]
    growth = candidate["growth"]
    classes = len(finding.god_classes)
    files = len(finding.god_files)
    largest = finding.god_classes[0] if finding.god_classes else None
    largest_text = (
        f"{largest.name}, {largest.loc} LOC"
        if largest
        else f"{finding.god_files[0].path}"
    )
    title = (
        f"Erosion: {classes} god class{'' if classes == 1 else 'es'}, "
        f"{files} god file{'' if files == 1 else 's'} above the mass threshold "
        f"(largest: {largest_text})"
    )
    marker = render_marker(compute_class_key(_CLASS_SOURCE, _CLASS_NEEDLES["mass"]))
    grown_lines = "\n".join(
        f"- `{g.key}` ({g.kind}): {g.baseline_loc} → {g.loc} LOC" for g in growth
    )
    body = (
        "## Evidence (ErosionMetricsLoop, automated)\n\n"
        "| metric | value |\n|---|---|\n"
        f"| god classes (≥{finding.class_loc_threshold} LOC or "
        f"≥{finding.class_method_threshold} methods) | {classes} |\n"
        f"| god files (≥{finding.file_loc_threshold} LOC) | {files} |\n"
        f"| source files measured | {finding.total_files} |\n"
        f"| grown >10% since baseline | {len(growth)} |\n"
        f"| largest | {largest_text} |\n\n"
        f"{marker}\n\n"
        f"{_roster_section(candidate['roster'])}\n"
        + (f"## Grown since baseline\n{grown_lines}\n\n" if growth else "")
        + "## How to decompose safely (one class per PR, largest first)\n\n"
        "Extract one cohesive cluster of methods into a new module and "
        "**re-export** the moved symbols from the original file so every "
        "existing `from x import Y` keeps working — zero caller changes and "
        "ONE class identity (precedent: `pr_manager_promotion.py`, "
        "`plan_phase_wiki_ingest.py` from #10840; ADR-0030 for route "
        "packages). Move any `# noqa` with the code it annotates (the "
        "suppressions ratchet counts per file). When the class shrinks, run "
        '`python scripts/regen_mass_baseline.py --reason "decomposed <Class>"` '
        "so `tests/architecture/test_mass_ratchet.py` records the smaller "
        "size and the next growth is caught.\n\n"
        "This is a standing class issue (mass sensor, `erosion.mass`): the "
        "roster refreshes in place while it is open and the issue is re-filed "
        "if closed while the reading is still non-empty. Pattern B outer-loop "
        "finding — it reports, it never opens a fix PR.\n"
    )
    return title, body


def _render_suite_hygiene(candidate: dict[str, Any]) -> tuple[str, str]:
    finding = candidate["finding"]
    copies = finding.parametrize_copies
    dups = len(finding.cross_file_duplicates)
    title = (
        f"Erosion: test suite carries {copies} parametrize "
        f"{'copy' if copies == 1 else 'copies'} and {dups} cross-file duplicate "
        f"test{'' if dups == 1 else 's'} ({finding.total_tests} tests)"
    )
    marker = render_marker(
        compute_class_key(_CLASS_SOURCE, _CLASS_NEEDLES["suite_hygiene"])
    )
    body = (
        "## Evidence (ErosionMetricsLoop, automated)\n\n"
        "| metric | value |\n|---|---|\n"
        f"| tests | {finding.total_tests} |\n"
        f"| test files | {finding.total_files} |\n"
        f"| parametrize groups (≥3 identical bodies in one file) | "
        f"{len(finding.parametrize_groups)} |\n"
        f"| parametrize copies (tests that collapse away) | {copies} |\n"
        f"| cross-file duplicates (same name + body in ≥2 files) | {dups} |\n\n"
        f"{marker}\n\n"
        f"{_roster_section(candidate['roster'])}\n"
        "## How to prune safely\n\n"
        "For each parametrize group, keep one test and turn the variations "
        "into `@pytest.mark.parametrize` cases — the assertions stay, the "
        "copies go. For each cross-file duplicate, keep the copy that lives "
        "next to the code under test and delete the other. Bodies compare "
        "structurally (names, literals and docstrings normalized), so two "
        "listed tests can still assert different *values* — that is exactly "
        "what parametrize is for. After a pass, run "
        '`python scripts/regen_suite_hygiene_baseline.py --reason "pruned <area>"` '
        "so `tests/architecture/test_suite_hygiene_ratchet.py` locks in the "
        "lower mark.\n\n"
        "This is a standing class issue (suite-hygiene sensor, "
        "`erosion.suite_hygiene`): the roster refreshes in place while it is "
        "open and the issue is re-filed if closed while the reading is still "
        "non-empty. Pattern B outer-loop finding — it reports, it never opens "
        "a fix PR.\n"
    )
    return title, body
