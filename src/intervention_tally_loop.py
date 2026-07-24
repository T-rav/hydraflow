"""Background worker loop — InterventionTallyLoop (#10369).

The attention-side falsification instrument: a read-only ADR-0029 caretaker,
**Pattern B like ``EscapeLedgerLoop`` / ``ErosionMetricsLoop``** (senses +
records, NEVER gates, blocks, or files fix PRs). Cost telemetry answers "what
does the factory spend"; this answers "what does the human spend."

Each tick it senses the human touches the factory ALREADY emits — HITL
escalation resolutions + governor control actions (from the persisted event
log) and steering directives (from ``SteeringState``) — classifies each into
the fixed v1 taxonomy (mechanical mapping where the source implies the class;
a bounded cheap-LLM call only for free-text steering guidance, with
``confidence`` recorded), and appends one deduped row per touch to the
append-only ledger ``<data_root>/diagnostics/intervention_ledger.jsonl``
(``intervention.models.InterventionRecord`` schema). It then re-renders the
rate report to ``docs/arch/generated/intervention-tally.md`` (gitignored,
rewritten each tick like ``escape-ledger.md`` — NOT an ``arch-regen``
artifact).

**Cursor + dedup design** (mirrors ``EscapeLedgerLoop``, timestamp cursor
instead of a SHA because the source is an event stream, not a commit range):
``state.get_intervention_tally_last_processed_ts()`` persists the ISO
timestamp this loop last processed up to. A fresh install primes the cursor to
NOW with NO back-analysis (acceptance: "fresh install primes cursors with no
back-analysis"). The cursor advances to the tick's start time unconditionally
at the end of a successful tick (events are sensed strictly after the cursor,
so a touch is processed exactly once). A separate ``DedupStore`` guards
against re-recording the same touch id across retries/restarts.

**Bounded classification spend.** ``intervention_tally_max_classify_per_tick``
caps how many free-text steering directives one tick may send to the cheap
LLM — the budget the spec requires so "a synthetic flood of steering comments
does not produce unbounded LLM classification spend." Over budget (or with
``intervention_tally_classify_enabled=False``), free-text rows keep their raw
text at low confidence for later re-label. Classification NEVER blocks the
observed action; recording is never capped, only LLM classification is.

Read-only: no ``create_issue``, no gating, no fix PRs — the touch already
happened; this ledger is bookkeeping ABOUT the human load, not one of the
factory's actuators.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug
from execution import get_default_runner
from intervention.classify import (
    apply_verdict,
    build_classification_prompt,
    classify,
    parse_llm_verdict,
)
from intervention.ledger import InterventionLedger
from intervention.metrics import count_commits_since
from intervention.models import (
    Confidence,
    InterventionCandidate,
    InterventionClass,
    InterventionRecord,
    InterventionSignal,
)
from intervention.report import render_intervention_tally_markdown
from intervention.sources import (
    active_loop_count_from_event_log,
    signals_from_event_log,
    signals_from_steering,
)
from loop_fitness import FitnessContext, FitnessKind, LoopFitness
from runner_utils import run_lightweight_agent

if TYPE_CHECKING:
    from state import StateTracker

logger = logging.getLogger("hydraflow.intervention_tally")

# Per-classification LLM bound; the LONG_LLM_CYCLE watchdog bounds the tick.
_CLASSIFY_LLM_TIMEOUT_SECONDS = 120

# Generated-report path (repo-root-relative), gitignored + rewritten each tick
# like docs/arch/generated/escape-ledger.md — NOT an arch-regen artifact.
_REPORT_REL = Path("docs/arch/generated/intervention-tally.md")

_LEDGER_FILENAME = "intervention_ledger.jsonl"


class _ClassifierLLM(Protocol):
    """Minimal one-shot text-completion seam for free-text classification.

    Tests inject a fake; production lazily builds :class:`_CLIClassifier`.
    """

    async def complete(self, prompt: str) -> str: ...


class _CLIClassifier:
    """Production classifier client: one-shot RAW-text completion via the shared
    lightweight-agent seam (credit-aware, telemetried).

    Never exercised under test (the loop injects a fake) and never reachable in
    the air-gapped sandbox (``intervention_tally_classify_enabled`` is pinned
    OFF there — the ``config_disable`` sandbox seam).
    """

    def __init__(self, config: HydraFlowConfig, model: str) -> None:
        self._config = config
        self._model = model

    async def complete(self, prompt: str) -> str:
        result = await run_lightweight_agent(
            runner=get_default_runner(),
            config=self._config,
            tool="claude",
            model=self._model,
            prompt=prompt,
            source="intervention_tally",
            timeout=float(_CLASSIFY_LLM_TIMEOUT_SECONDS),
            issue_labels=(),
        )
        if result.returncode != 0:
            msg = f"classifier LLM failed (rc={result.returncode})"
            raise RuntimeError(msg)
        return result.stdout


class InterventionTallyLoop(BaseBackgroundLoop):
    """Records human interventions as attention-side telemetry. Read-only (Pattern B).

    Never edits code, never opens a PR, never gates. It senses the human
    touches the factory already emits and records them; the touch already
    happened, and the ledger is bookkeeping ABOUT the human load.
    """

    # Free-text steering classification spends bounded cheap-LLM calls, so the
    # loop earns the longer per-cycle watchdog bound (#9455 / #9556).
    LONG_LLM_CYCLE = True

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        dedup: DedupStore,
        deps: LoopDeps,
        classifier_llm: _ClassifierLLM | None = None,
    ) -> None:
        super().__init__(worker_name="intervention_tally", config=config, deps=deps)
        self._state = state
        self._dedup = dedup
        # Injected fake under test; production lazily builds `_CLIClassifier`.
        self._classifier_llm = classifier_llm

    def _get_default_interval(self) -> int:
        return self._config.intervention_tally_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only sensor: records evidence, owns no proposal/acceptance
        # lifecycle to score — HOUSEKEEPING per ADR-0093, mirrors
        # escape_ledger_loop.py / erosion_metrics_loop.py.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    # --- paths -----------------------------------------------------------

    @property
    def _ledger_path(self) -> Path:
        return self._config.diagnostics_dir / _LEDGER_FILENAME

    # --- main tick -------------------------------------------------------

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.intervention_tally_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        resolved = self._resolve_since()
        if isinstance(resolved, dict):
            return resolved
        since_ts, now_ts = resolved

        signals = self._collect_signals(since_ts)
        candidates = classify(signals)
        candidates, classified = await self._classify_free_text(candidates)
        recorded = self._record(candidates)
        self._render_report()

        # Advance the cursor unconditionally: everything up to now_ts has been
        # sensed (events are read strictly after the cursor, so no double-count).
        self._state.set_intervention_tally_last_processed_ts(now_ts)

        return {
            "status": "ok",
            "since": since_ts,
            "sensed": len(signals),
            "recorded": len(recorded),
            "llm_classified": classified,
        }

    def _resolve_since(self) -> tuple[str, str] | dict[str, Any]:
        """Resolve ``(since_ts, now_ts)`` to process, or an early-exit status dict.

        Primes the cursor to NOW on the first tick ever (no back-analysis);
        every other tick returns the persisted cursor + a fresh now stamp.
        """
        now_ts = datetime.now(UTC).isoformat()
        last_ts = self._state.get_intervention_tally_last_processed_ts()
        if not last_ts:
            self._state.set_intervention_tally_last_processed_ts(now_ts)
            return {"status": "baseline_established", "ts": now_ts}
        return last_ts, now_ts

    # --- sensing ---------------------------------------------------------

    def _collect_signals(self, since_ts: str) -> list[InterventionSignal]:
        """Materialize raw signals from every v1 source since the cursor."""
        signals: list[InterventionSignal] = []
        model = self._current_model()
        event_signals = signals_from_event_log(self._config.event_log_path, since_ts)
        if event_signals:
            signals.extend(event_signals)
        steering = self._state.get_all_human_steering()
        signals.extend(
            signals_from_steering(steering, since_ts, model_version_context=model)
        )
        return signals

    # --- classification (bounded cheap-LLM for free-text only) -----------

    async def _classify_free_text(
        self, candidates: list[InterventionCandidate]
    ) -> tuple[list[InterventionCandidate], int]:
        """Upgrade free-text steering rows via the bounded cheap LLM.

        Only ``needs_llm`` candidates are eligible, capped at
        ``intervention_tally_max_classify_per_tick`` per tick. Each ATTEMPT
        counts against the budget (bounds spend under a flood); over budget or
        with classification disabled, the low-confidence default stands and the
        raw text is preserved. Never blocks — a failed call keeps the default.
        """
        if not self._config.intervention_tally_classify_enabled:
            return candidates, 0
        budget = int(self._config.intervention_tally_max_classify_per_tick)
        classified = 0
        out: list[InterventionCandidate] = []
        for candidate in candidates:
            resolved = candidate
            if candidate.needs_llm and classified < budget:
                classified += 1
                verdict = await self._classify_llm(candidate.free_text)
                if verdict is not None:
                    resolved = apply_verdict(candidate, verdict)
            out.append(resolved)
        return out, classified

    async def _classify_llm(
        self, free_text: str
    ) -> tuple[InterventionClass, Confidence] | None:
        """One cheap-LLM classification; ``None`` on any failure (keeps default)."""
        if self._classifier_llm is None:
            model = (
                self._config.intervention_tally_model
                or self._config.background_model
                or "sonnet"
            )
            self._classifier_llm = _CLIClassifier(self._config, model)
        try:
            raw = await self._classifier_llm.complete(
                build_classification_prompt(free_text)
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "InterventionTally: free-text classification failed", exc_info=True
            )
            return None
        return parse_llm_verdict(raw)

    # --- recording -------------------------------------------------------

    def _record(
        self, candidates: list[InterventionCandidate]
    ) -> list[InterventionRecord]:
        """Append one deduped ledger row per candidate. Never blocks."""
        ledger = InterventionLedger(self._ledger_path)
        existing = ledger.existing_ids()
        seen = self._dedup.get()
        model = self._current_model()
        recorded: list[InterventionRecord] = []
        for candidate in candidates:
            if candidate.id in existing or candidate.id in seen:
                continue
            record = InterventionRecord.from_candidate(candidate)
            if not record.model_version_context:
                record = replace(record, model_version_context=model)
            ledger.append(record)
            existing.add(candidate.id)
            seen = seen | {candidate.id}
            self._dedup.set_all(seen)
            recorded.append(record)
            logger.info(
                "InterventionTally: recorded %s (%s, %s)",
                candidate.id,
                candidate.intervention_class,
                candidate.confidence,
            )
        return recorded

    # --- report ----------------------------------------------------------

    def _render_report(self) -> None:
        """Rewrite intervention-tally.md from the current ledger + denominator."""
        now = datetime.now(UTC)
        repo_root = Path(self._config.repo_root)
        records = InterventionLedger(self._ledger_path).read_all()
        merge_count = count_commits_since(repo_root, 30) or 0
        active = active_loop_count_from_event_log(self._config.event_log_path)
        _write(
            repo_root / _REPORT_REL,
            render_intervention_tally_markdown(
                records,
                now=now,
                merge_count_30d=merge_count,
                active_loop_count=active,
            ),
        )

    def _current_model(self) -> str:
        """The active model-version context stamped on every recorded row."""
        return (
            self._config.intervention_tally_model
            or self._config.background_model
            or "sonnet"
        )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
