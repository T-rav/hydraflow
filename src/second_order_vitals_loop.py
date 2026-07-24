"""Background worker loop — SecondOrderVitalsLoop (#10373).

The CAPSTONE falsification instrument: a read-only ADR-0029 caretaker,
**Pattern B like ``EscapeLedgerLoop`` / ``InterventionTallyLoop`` /
``SampledAuditLoop``** (computes + reports, NEVER remediates, gates ordinary
merges, or files fix PRs). Where each of the four input instruments watches ONE
second-order dimension and files its own findings, this loop computes the JOINT
condition none of them can see: **green-while-dying** — several independent
second-order signals drifting adverse together WHILE the primary gates stay
green. In control-theory terms, residual monitoring under analytical
redundancy: the primary gates are the plant's own claim about its health, the
instruments are independent estimates, and a sustained residual between them is
the fault signal.

Each tick it reads the four instruments' own ledgers/series (IMPORTING their
metric functions — one source of truth, never a divergent re-derivation),
computes one scalar per-window observation for each of the FIVE input families,
appends it to that series' persisted history, and evaluates the divergence
condition:

* each series carries its own Shewhart individuals-chart control limit
  (baseline primed from the series' own history once it has enough windows);
* **watch** = primary health GREEN and ≥``watch_k`` (2) of 5 families above
  their limits, sustained for ``sustained_windows`` (2) consecutive windows;
* **diverging** = primary health GREEN and ≥``diverging_k`` (3) of 5 sustained.

Sustained-window + k-of-5 is the anti-flap design: single-series spikes belong
to that instrument's own finding path, not here. The one vitals verdict
(``green | watch | diverging``) is rendered to the deterministic
``docs/arch/generated/second-order-vitals.md`` (verdict explainable from its
inputs on the same page) and appended to ``<data_root>/diagnostics/vitals.jsonl``.

**Outputs by verdict (decided):** ``watch`` → dashboard state change only (no
issue; observing is the point). ``diverging`` → files exactly ONE
highest-priority ``hydraflow-find`` and escalates HITL directly (the escalation
label), ONCE per episode (until the condition clears). This is the factory's
single alarm that is NEVER batched, deduped, or cooled — by construction it can
only fire after multi-family, multi-window persistence, so a firing is
load-bearing.

**Degrade honestly.** With instruments not built / series too young for
baselines, the verdict is ``green (n-of-5 reporting)`` — partial coverage is
displayed, never silently treated as full.

**Self-modification class (#10371).** This loop and its ``src/vitals/`` engine
are registered under the judge-independence self-modification class (changes to
them require an independent verdict and fail closed): the monitor for
green-while-dying must not be quietly editable by the machinery it monitors.

Read-only: no code edits, no PRs, no gating of ordinary merges, no fusion of
first-order health, no ML — control limits and counting only, because
legibility is the feature in the instrument that has to be trusted when it fires.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from escape.detect import count_commits_since
from exception_classify import reraise_on_credit_or_bug
from factory_health import compute_summary
from loop_fitness import FitnessContext, FitnessKind, LoopFitness
from vitals.models import VitalsThresholds, VitalsVerdict
from vitals.observe import (
    PrimaryHealth,
    gather_series_readings,
    primary_health_green,
)
from vitals.report import (
    render_second_order_vitals_markdown,
    verdict_record,
)
from vitals.verdict import VERDICT_DIVERGING, evaluate_vitals

if TYPE_CHECKING:
    from collections.abc import Callable

    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.second_order_vitals")

# Generated-report path (repo-root-relative), gitignored + rewritten each tick
# like docs/arch/generated/escape-ledger.md — NOT an arch-regen artifact
# (data-bearing; a committed generated doc would drift on factory-on-stale-main).
_REPORT_REL = Path("docs/arch/generated/second-order-vitals.md")

_VITALS_FILENAME = "vitals.jsonl"

_FIND_LABELS = ["hydraflow-find", "second-order-vitals"]


class SecondOrderVitalsLoop(BaseBackgroundLoop):
    """Residual monitor over the instrument set. Read-only (Pattern B).

    Never edits code, never opens a PR, never gates ordinary merges. It reads
    the four instruments' ledgers, computes the green-while-dying verdict, and
    reports it; only a sustained multi-family divergence files a single alarm.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        state: StateTracker,
        deps: LoopDeps,
        primary_health_reader: Callable[[datetime, int], PrimaryHealth] | None = None,
    ) -> None:
        super().__init__(worker_name="second_order_vitals", config=config, deps=deps)
        self._prs = pr_manager
        self._state = state
        # Injected under test/scenario so the primary-health gate is
        # deterministic; production reads merge throughput + CI pass rate.
        self._primary_health_reader = primary_health_reader

    def _get_default_interval(self) -> int:
        return self._config.second_order_vitals_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only sensor: computes + reports a verdict, owns no proposal/
        # acceptance lifecycle to score — HOUSEKEEPING per ADR-0093, mirrors
        # escape_ledger_loop / intervention_tally_loop / sampled_audit_loop.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    # --- paths -----------------------------------------------------------

    @property
    def _vitals_path(self) -> Path:
        return self._config.diagnostics_dir / _VITALS_FILENAME

    # --- thresholds ------------------------------------------------------

    def _thresholds(self) -> VitalsThresholds:
        return VitalsThresholds(
            min_baseline_windows=int(
                self._config.second_order_vitals_min_baseline_windows
            ),
            sustained_windows=int(self._config.second_order_vitals_sustained_windows),
            watch_k=int(self._config.second_order_vitals_watch_k),
            diverging_k=int(self._config.second_order_vitals_diverging_k),
        )

    # --- main tick -------------------------------------------------------

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.second_order_vitals_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        now = datetime.now(UTC)
        window_days = int(self._config.second_order_vitals_window_days)

        histories = self._append_observations(now, window_days)
        ph = self._read_primary_health(now, window_days)
        ph_green = primary_health_green(
            ph,
            min_ci_pass_rate=float(self._config.second_order_vitals_min_ci_pass_rate),
            min_merge_throughput=int(
                self._config.second_order_vitals_min_merge_throughput
            ),
        )
        verdict = evaluate_vitals(
            histories,
            primary_health_green=ph_green,
            thresholds=self._thresholds(),
        )

        self._append_verdict(now, verdict)
        self._render_report(now, window_days, verdict)
        filed = await self._maybe_fire_alarm(verdict)

        return {
            "status": "ok",
            "verdict": verdict.verdict,
            "k": verdict.k,
            "reporting_families": verdict.reporting_families,
            "primary_health_green": ph_green,
            "filed": filed,
        }

    # --- observation history ---------------------------------------------

    def _append_observations(
        self, now: datetime, window_days: int
    ) -> dict[str, list[float]]:
        """Read the instruments, append one reading per present series, persist.

        Absent series (no ledger written yet) read ``None`` and are skipped so
        the coverage stays honest; present series get one appended observation,
        with each series' history bounded to ``history_max`` so it can never grow
        without limit.
        """
        readings = gather_series_readings(
            self._config, now=now, window_days=window_days
        )
        histories = self._state.get_second_order_vitals_series_history()
        history_max = int(self._config.second_order_vitals_history_max)
        for series, value in readings.items():
            if value is None:
                continue
            hist = list(histories.get(series, []))
            hist.append(float(value))
            histories[series] = hist[-history_max:]
        self._state.set_second_order_vitals_series_history(histories)
        return histories

    # --- primary-health gate ---------------------------------------------

    def _read_primary_health(self, now: datetime, window_days: int) -> PrimaryHealth:
        """Resolve the primary-health reading (injected fake, else real signals)."""
        if self._primary_health_reader is not None:
            return self._primary_health_reader(now, window_days)
        merges = self._merge_throughput(window_days)
        ci = self._ci_pass_rate()
        return PrimaryHealth(ci_pass_rate=ci, merge_throughput=merges)

    def _merge_throughput(self, window_days: int) -> int:
        """Merges into the base branch within the window (shared escape denominator).

        Reuses ``escape.detect.count_commits_since`` — the SAME merge-volume
        function the escape/intervention instruments use, so the primary gate's
        throughput reading cannot drift from theirs. A local git read that is
        graceful by construction (``None`` on any git failure, coerced to 0);
        never a fleet-gated spawn.
        """
        return int(count_commits_since(Path(self._config.repo_root), window_days) or 0)

    def _ci_pass_rate(self) -> float:
        """Best-effort primary CI pass rate from the factory-health summary.

        Reads the existing first-order signal (never a re-derivation) via the
        pure ``factory_health.compute_summary`` over the retrospectives store.
        Defaults to ``1.0`` (green) when the signal is absent so a missing
        telemetry file cannot permanently mute the divergence alarm — the
        monitor stays able to fire; it never manufactures a red primary state it
        cannot see. ``_load_jsonl`` absorbs any read error, and the summary is a
        pure function over lists, so no broad guard is needed here.
        """
        retro = _load_jsonl(self._config.retrospectives_path)
        if not retro:
            return 1.0
        summary = compute_summary(retro, [])
        rolling = summary.get("rolling_averages")
        series = rolling.get("first_pass_rate") if isinstance(rolling, dict) else None
        if isinstance(series, list) and series and isinstance(series[-1], dict):
            value = series[-1].get("value")
            if isinstance(value, int | float):
                return float(value)
        return 1.0

    # --- persistence + report --------------------------------------------

    def _append_verdict(self, now: datetime, verdict: VitalsVerdict) -> None:
        """Append one row to the append-only ``vitals.jsonl`` verdict history."""
        path = self._vitals_path
        path.parent.mkdir(parents=True, exist_ok=True)
        row = verdict_record(verdict, ts=now.isoformat())
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    def _render_report(
        self, now: datetime, window_days: int, verdict: VitalsVerdict
    ) -> None:
        """Rewrite second-order-vitals.md from the current verdict (deterministic)."""
        repo_root = Path(self._config.repo_root)
        _write(
            repo_root / _REPORT_REL,
            render_second_order_vitals_markdown(
                verdict, now=now, window_days=window_days
            ),
        )

    # --- the single, never-batched divergence alarm ----------------------

    async def _maybe_fire_alarm(self, verdict: VitalsVerdict) -> int:
        """File ONE find + HITL escalation on the diverging EDGE, once per episode.

        The alarm fires only when the verdict TRANSITIONS into ``diverging``
        (previous persisted verdict was not diverging) — the episode boundary —
        so a sustained diverging state files exactly one alarm and does not
        re-file every tick. When the verdict clears (back to green/watch) the
        episode closes and a later re-divergence fires again. This is the one
        alarm that is never batched, deduped, or cooled: by construction it can
        only fire after multi-family, multi-window persistence.
        """
        last = self._state.get_second_order_vitals_last_verdict()
        edge = verdict.verdict == VERDICT_DIVERGING and last != VERDICT_DIVERGING
        # Persist the verdict AFTER reading the edge, so the transition is
        # detected exactly once even across a filing failure retry next tick.
        filed = 0
        if edge:
            filed = await self._file_alarm(verdict)
            # Only mark the episode open once the alarm is actually filed, so a
            # transient create_issue failure re-attempts on the next tick.
            if filed:
                self._state.set_second_order_vitals_last_verdict(verdict.verdict)
        else:
            self._state.set_second_order_vitals_last_verdict(verdict.verdict)
        return filed

    async def _file_alarm(self, verdict: VitalsVerdict) -> int:
        """Create the single highest-priority find carrying the HITL escalation label."""
        title, body = _render_alarm(verdict)
        labels = [*_FIND_LABELS, *self._config.hitl_escalation_label]
        try:
            issue = await self._prs.create_issue(title, body, labels=labels)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "SecondOrderVitals: failed to file divergence alarm", exc_info=True
            )
            return 0
        logger.warning(
            "SecondOrderVitals: DIVERGING (%d of %d families) — filed alarm #%s, "
            "escalated HITL",
            verdict.k,
            verdict.total_families,
            issue,
        )
        return 1 if issue else 0


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file, skipping malformed lines; ``[]`` when absent/unreadable."""
    try:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _render_alarm(verdict: VitalsVerdict) -> tuple[str, str]:
    """Render (title, body) for the single diverging-episode alarm issue."""
    families = ", ".join(verdict.breaching_families) or "(none)"
    title = (
        f"Second-order vitals DIVERGING: {verdict.k} of {verdict.total_families} "
        "instrument families drifting adverse while primary health is green"
    )
    rows = "\n".join(
        f"| {fam.family} | {'yes' if fam.reporting else 'no'} "
        f"| {'YES' if fam.breaching else 'no'} |"
        for fam in verdict.families
    )
    series_rows = "\n".join(
        f"| {s.label} | {s.value:g} | {s.ucl:g} | {s.residual:+g} "
        f"| {'YES' if s.breaching else 'no'} |"
        for fam in verdict.families
        for s in fam.series
    )
    body = (
        "## Green-while-dying alarm (SecondOrderVitalsLoop, automated — #10373)\n\n"
        f"The primary gates are GREEN, yet **{verdict.k} of "
        f"{verdict.total_families}** independent second-order instrument families "
        f"({families}) have drifted above their own Shewhart control limits and "
        "stayed there across the sustained-window count. Correlated adverse drift "
        "across independent instruments is the exact failure the factory publicly "
        "stakes itself against — the gauntlet green while the codebase curdles "
        "underneath.\n\n"
        f"Coverage: **{verdict.coverage_label}**.\n\n"
        "### Families\n\n"
        "| family | reporting | above control limit (sustained) |\n"
        "|---|---|---|\n"
        f"{rows}\n\n"
        "### Contributing series (latest vs its own control limit)\n\n"
        "| series | latest | UCL | residual | breaching |\n"
        "|---|---|---|---|---|\n"
        f"{series_rows}\n\n"
        "This is the factory's ONE never-batched, never-cooled alarm: by "
        "construction it fires only after multi-family, multi-window persistence, "
        "so a firing is load-bearing. It is read-only evidence, not a gate — no "
        "merge was blocked. A human should look at the contributing series above "
        "and decide whether the instruments are seeing real erosion the primary "
        "gates cannot.\n"
    )
    return title, body
