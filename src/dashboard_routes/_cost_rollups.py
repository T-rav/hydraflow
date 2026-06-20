"""Shared cross-issue cost-rollup aggregator (spec §4.11 points 4–5).

Three iterators over the same three sources the issue waterfall uses:
* ``metrics/prompt/inferences.jsonl`` — LLM inferences.
* ``traces/<issue>/<phase>/run-N/subprocess-*.json`` — subprocess traces.
* ``traces/_loops/<slug>/run-*.json`` — loop-subprocess traces.

Five builders that answer the five endpoints in ``_diagnostics_routes.py``:
* ``build_rolling_24h`` — last-24h totals + per-phase + per-loop.
* ``build_top_issues`` — N most expensive issues in window.
* ``build_by_loop``    — per-loop tick / wall-clock share.
* ``build_per_loop_cost`` — machinery-level per-loop dashboard row.
* ``build_cost_by_model`` — cross-loop per-model spend breakdown.

All cost values are re-priced on every call via
``ModelPricing.estimate_cost`` — storage is token counts only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from dashboard_routes._waterfall_builder import _phase_for_source
from model_pricing import ModelPricingTable, load_pricing
from trace_collector import _slug_for_loop
from tracing_context import source_to_phase

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus

logger = logging.getLogger("hydraflow.dashboard.cost_rollups")


_RANGE_MAP: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _utcnow() -> datetime:
    """Injectable now() for tests."""
    return datetime.now(UTC)


def _parse_range(value: str | None) -> timedelta:
    """Parse a ``range`` query-string value into a ``timedelta``.

    Default is ``7d``. Raises ``ValueError`` on unknown tokens.
    """
    if not value:
        return _RANGE_MAP["7d"]
    if value not in _RANGE_MAP:
        msg = f"unsupported range: {value!r}"
        raise ValueError(msg)
    return _RANGE_MAP[value]


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _empty_model_bucket() -> dict[str, float | int]:
    """Initial bucket shape for per-model cost/token aggregation.

    Used by ``build_per_loop_cost`` (per-loop nested) and
    ``build_cost_by_model`` (cross-loop). Keeping the shape in one
    place prevents schema drift between the two surfaces.
    """
    return {
        "cost_usd": 0.0,
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def iter_priced_inferences(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    pricing: ModelPricingTable,
) -> Iterator[dict[str, Any]]:
    """Stream inference rows in ``[since, until)`` with re-priced cost.

    Yields dicts with the raw row fields plus:
    * ``ts``: parsed ``datetime`` of ``timestamp``.
    * ``cost_usd``: ``float``; ``0.0`` when the pricing table has no entry.
    * ``phase``: canonical phase (via ``_phase_for_source``).
    """
    path = config.cost_inferences_path
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                ts = _parse_iso(rec.get("timestamp"))
                if ts is None or ts < since or ts >= until:
                    continue
                input_tok = int(rec.get("input_tokens", 0) or 0)
                output_tok = int(rec.get("output_tokens", 0) or 0)
                cost = pricing.estimate_cost(
                    str(rec.get("model", "")),
                    input_tokens=input_tok,
                    output_tokens=output_tok,
                    cache_write_tokens=int(
                        rec.get("cache_creation_input_tokens", 0) or 0
                    ),
                    cache_read_tokens=int(rec.get("cache_read_input_tokens", 0) or 0),
                )
                priced = round(cost, 6) if cost is not None else 0.0
                # Rows whose actual token usage was unavailable at record time
                # (token_source=estimated) re-price to 0 from tokens. This is
                # dominated by heavy pipeline runners (planner/researcher/
                # implementer/reviewer/...), not just the lightweight run_simple
                # path. Fall back to the stored char-based estimate so that spend
                # still counts toward the daily cost cap (WS-2.2 self-review S2).
                if priced == 0.0 and input_tok == 0 and output_tok == 0:
                    stored = rec.get("estimated_cost_usd")
                    if (
                        isinstance(stored, int | float)
                        and not isinstance(stored, bool)
                        and stored > 0
                    ):
                        priced = round(float(stored), 6)
                rec["ts"] = ts
                rec["cost_usd"] = priced
                rec["phase"] = _phase_for_source(str(rec.get("source", "")))
                yield rec
    except OSError:
        logger.warning("Failed to read inferences.jsonl for rollup", exc_info=True)


def iter_priced_inferences_for_issue(
    config: HydraFlowConfig,
    *,
    issue: int,
    pricing: ModelPricingTable,
) -> Iterator[dict[str, Any]]:
    """Stream priced inference rows for a single issue (wide time window).

    Shares the read+price path with :func:`iter_priced_inferences` so the
    waterfall builder and cross-issue rollups compute cost identically.
    """
    # Use a very wide window so we don't drop rows — the filter is by issue.
    since = datetime(1970, 1, 1, tzinfo=UTC)
    until = datetime(9999, 1, 1, tzinfo=UTC)
    for rec in iter_priced_inferences(
        config, since=since, until=until, pricing=pricing
    ):
        if rec.get("issue_number") == issue:
            yield rec


def iter_subprocess_traces(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
) -> Iterator[dict[str, Any]]:
    """Stream subprocess traces (issue-scoped) whose ``started_at`` falls in window."""
    base = config.data_root / "traces"
    if not base.is_dir():
        return
    for path in base.rglob("subprocess-*.json"):
        # Skip the _loops subtree — those are loop-scoped, handled elsewhere.
        if "_loops" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        ts = _parse_iso(data.get("started_at"))
        if ts is None or ts < since or ts >= until:
            continue
        data["ts"] = ts
        yield data


def iter_loop_traces(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
) -> Iterator[dict[str, Any]]:
    """Stream loop-subprocess traces whose ``started_at`` falls in window."""
    base = config.data_root / "traces" / "_loops"
    if not base.is_dir():
        return
    for path in base.rglob("run-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("kind") != "loop":
            continue
        ts = _parse_iso(data.get("started_at"))
        if ts is None or ts < since or ts >= until:
            continue
        data["ts"] = ts
        yield data


def build_rolling_24h(
    config: HydraFlowConfig,
    *,
    pricing: ModelPricingTable | None = None,
) -> dict[str, Any]:
    """Return last-24h totals grouped by phase and loop (§4.11 point 4)."""
    pricing = pricing or load_pricing()
    now = _utcnow()
    since = now - timedelta(hours=24)

    phase_cost: dict[str, float] = defaultdict(float)
    phase_tokens_in: dict[str, int] = defaultdict(int)
    phase_tokens_out: dict[str, int] = defaultdict(int)
    total_cost = 0.0
    total_in = 0
    total_out = 0

    for rec in iter_priced_inferences(config, since=since, until=now, pricing=pricing):
        phase = rec["phase"]
        phase_cost[phase] += rec["cost_usd"]
        phase_tokens_in[phase] += int(rec.get("input_tokens", 0) or 0)
        phase_tokens_out[phase] += int(rec.get("output_tokens", 0) or 0)
        total_cost += rec["cost_usd"]
        total_in += int(rec.get("input_tokens", 0) or 0)
        total_out += int(rec.get("output_tokens", 0) or 0)

    by_phase = [
        {
            "phase": phase,
            "cost_usd": round(phase_cost[phase], 6),
            "tokens_in": phase_tokens_in[phase],
            "tokens_out": phase_tokens_out[phase],
        }
        for phase in sorted(phase_cost.keys())
    ]

    loop_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"ticks": 0, "wall_clock_seconds": 0}
    )
    for tr in iter_loop_traces(config, since=since, until=now):
        name = str(tr.get("loop", "?"))
        loop_stats[name]["ticks"] += 1
        loop_stats[name]["wall_clock_seconds"] += (
            int(tr.get("duration_ms", 0) or 0) // 1000
        )

    by_loop = [{"loop": name, **stats} for name, stats in sorted(loop_stats.items())]

    return {
        "generated_at": now.isoformat(),
        "window_hours": 24,
        "total": {
            "cost_usd": round(total_cost, 6),
            "tokens_in": total_in,
            "tokens_out": total_out,
        },
        "by_phase": by_phase,
        "by_loop": by_loop,
    }


def build_top_issues(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    limit: int = 10,
    pricing: ModelPricingTable | None = None,
) -> list[dict[str, Any]]:
    """Return the top-N most expensive issues in the window, descending by cost."""
    pricing = pricing or load_pricing()
    per_issue_cost: dict[int, float] = defaultdict(float)
    per_issue_secs: dict[int, int] = defaultdict(int)

    for rec in iter_priced_inferences(
        config, since=since, until=until, pricing=pricing
    ):
        issue = rec.get("issue_number")
        if not isinstance(issue, int) or issue <= 0:
            continue
        per_issue_cost[issue] += rec["cost_usd"]
        per_issue_secs[issue] += int(float(rec.get("duration_seconds", 0.0) or 0.0))

    rows = [
        {
            "issue": issue,
            "cost_usd": round(per_issue_cost[issue], 6),
            "wall_clock_seconds": per_issue_secs[issue],
        }
        for issue in per_issue_cost
    ]
    rows.sort(key=lambda r: (-r["cost_usd"], r["issue"]))
    return rows[: max(1, int(limit))]


def build_by_loop(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    """Return per-loop tick count + wall-clock share over the window."""
    loop_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"ticks": 0, "wall_clock_seconds": 0}
    )
    for tr in iter_loop_traces(config, since=since, until=until):
        name = str(tr.get("loop", "?"))
        loop_stats[name]["ticks"] += 1
        loop_stats[name]["wall_clock_seconds"] += (
            int(tr.get("duration_ms", 0) or 0) // 1000
        )

    total_ticks = sum(s["ticks"] for s in loop_stats.values()) or 1
    return [
        {
            "loop": name,
            "ticks": stats["ticks"],
            "wall_clock_seconds": stats["wall_clock_seconds"],
            "share_of_ticks": round(stats["ticks"] / total_ticks, 4),
        }
        for name, stats in sorted(loop_stats.items())
    ]


def _tally_worker_events(events: list[Any]) -> dict[str, dict[str, Any]]:
    """Tally ``BACKGROUND_WORKER_STATUS`` events by worker name."""
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ticks": 0,
            "ticks_errored": 0,
            "issues_filed": 0,
            "issues_closed": 0,
            "escalations": 0,
            "last_tick_at": "",
        }
    )
    for ev in events or []:
        type_val = getattr(ev, "type", None)
        if type_val is None and isinstance(ev, dict):
            type_val = ev.get("type")
        if str(type_val) not in (
            "background_worker_status",
            "BACKGROUND_WORKER_STATUS",
        ):
            continue
        data = getattr(ev, "data", None)
        if data is None and isinstance(ev, dict):
            data = ev.get("data")
        data = data or {}
        worker = str(data.get("worker", ""))
        if not worker:
            continue
        row = out[worker]
        row["ticks"] += 1
        if str(data.get("status", "")).lower() == "error":
            row["ticks_errored"] += 1
        details = data.get("details") or {}
        if isinstance(details, dict):
            row["issues_filed"] += int(details.get("filed", 0) or 0)
            row["issues_closed"] += int(details.get("closed", 0) or 0)
            row["escalations"] += int(details.get("escalated", 0) or 0)
        last = str(data.get("last_run", "")) or str(getattr(ev, "timestamp", "") or "")
        row["last_tick_at"] = max(row["last_tick_at"], last)
    return out


def _event_timestamp(ev: Any) -> datetime | None:
    """Best-effort parse of a worker-status event's wall-clock time."""
    data = getattr(ev, "data", None)
    if data is None and isinstance(ev, dict):
        data = ev.get("data")
    data = data if isinstance(data, dict) else {}
    raw = data.get("last_run")
    if not raw:
        raw = getattr(ev, "timestamp", None)
        if raw is None and isinstance(ev, dict):
            raw = ev.get("timestamp")
    return _parse_iso(raw) if isinstance(raw, str) else None


def _split_events_on(
    events: list[Any], *, boundary: datetime
) -> tuple[list[Any], list[Any]]:
    """Partition events into ``(current, prior)`` on a timestamp boundary.

    An event strictly before ``boundary`` is prior; one at/after it — or whose
    timestamp can't be parsed (preserving the old ``load_events_since(since)``
    behavior, where every returned event was current) — is current.
    """
    current: list[Any] = []
    prior: list[Any] = []
    for ev in events:
        ts = _event_timestamp(ev)
        (prior if ts is not None and ts < boundary else current).append(ev)
    return current, prior


# Inference ``source`` values that name no loop: char-estimate token-source
# markers, the design-time onboarding agent, synchronous post-merge hooks, and
# empty sources. These never represent a background-worker/pipeline loop, so
# they are dropped from the per-loop cost view rather than surfacing a spurious
# row.
_NON_LOOP_COST_SOURCES: frozenset[str] = frozenset(
    {"", "estimated", "claude", "post_merge_hook", "threshold_check"}
)

# Background-loop sources whose telemetry ``source`` differs from the loop's
# ``worker_name``. Pipeline-runner sources (implementer→implement, …) are
# folded by ``source_to_phase``; only the genuine bg-loop mismatches live here.
_COST_SOURCE_TO_WORKER: dict[str, str] = {
    "unsticker": "pr_unsticker",  # pr_unsticker conflict-transcript label
    "wiki_compilation": "repo_wiki",  # wiki_compiler.py, driven by RepoWikiLoop
    # DiagnosticLoop's runner emits two source values — "diagnostic" (diagnose
    # stage) and "diagnostic_fix" (fix stage). Pin BOTH to the loop explicitly
    # so a future ``source_to_phase`` entry for "diagnostic" can't split the
    # diagnose-stage spend (the larger of the two) into a separate row.
    "diagnostic": "diagnostic",  # diagnostic_runner.py diagnose stage
    "diagnostic_fix": "diagnostic",  # diagnostic_runner.py fix stage
}


def _worker_for_cost_source(source: str) -> str | None:
    """Map an inference ``source`` to the loop/worker it should bill to.

    Returns ``None`` for sources that name no loop (telemetry artifacts and
    synchronous hooks). Background-loop sources whose name differs from the
    loop's ``worker_name`` are remapped via :data:`_COST_SOURCE_TO_WORKER`;
    pipeline-runner sources fold to their canonical phase via
    :func:`source_to_phase`; everything else passes through unchanged.
    """
    normalized = (source or "").strip()
    if normalized in _NON_LOOP_COST_SOURCES:
        return None
    if normalized in _COST_SOURCE_TO_WORKER:
        return _COST_SOURCE_TO_WORKER[normalized]
    return source_to_phase(normalized)


def build_per_loop_cost(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    pricing: ModelPricingTable | None = None,
    event_bus: EventBus | None = None,
) -> list[dict[str, Any]]:
    """Return the machinery-level per-loop dashboard rows (spec §4.11 point 5).

    Per-row fields: loop, cost_usd, tokens_in, tokens_out, llm_calls,
    issues_filed, issues_closed, escalations, ticks, tick_cost_avg_usd,
    wall_clock_seconds, tick_cost_avg_usd_prev_period, model_breakdown.

    Cost / tokens / llm_calls / model_breakdown are attributed to a loop by the
    inference ``source`` field (see :func:`_worker_for_cost_source`), **not** by
    temporal overlap with a loop-trace window: the loops that emit loop traces
    are LLM-free caretaker loops (gh/git shell-outs), while the LLM-spending
    background workers emit no loop trace at all — so a trace-window join bills
    ``$0`` to every loop and, when windows do coincide, mis-attributes pipeline
    spend to whichever caretaker tick it overlapped. Tick counts and wall-clock
    still come from loop traces; filed / closed / escalation / errored-tick
    counters still come from ``BACKGROUND_WORKER_STATUS`` events.

    ``model_breakdown`` is a dict keyed by model name (or "unknown" for
    records missing the field), with nested {cost_usd, calls, input_tokens,
    output_tokens, cache_read_tokens, cache_write_tokens}.
    """
    pricing = pricing or load_pricing()

    # Tick count + wall-clock from loop traces, keyed by worker_name. (Loops
    # emit traces under ``self._worker_name``; ``_slug_for_loop`` is a no-op on
    # an already-snake-case name but normalises any legacy ClassName trace.)
    per_loop_ticks: dict[str, int] = defaultdict(int)
    per_loop_wall: dict[str, int] = defaultdict(int)
    for tr in iter_loop_traces(config, since=since, until=until):
        worker = _slug_for_loop(str(tr.get("loop", "?")))
        per_loop_ticks[worker] += 1
        per_loop_wall[worker] += int(tr.get("duration_ms", 0) or 0) // 1000

    # Cost / tokens / calls / model-breakdown attributed by inference source.
    per_loop_cost: dict[str, float] = defaultdict(float)
    per_loop_tokens_in: dict[str, int] = defaultdict(int)
    per_loop_tokens_out: dict[str, int] = defaultdict(int)
    per_loop_llm_calls: dict[str, int] = defaultdict(int)
    per_loop_model: dict[str, dict[str, dict[str, float | int]]] = defaultdict(
        lambda: defaultdict(_empty_model_bucket)
    )
    for rec in iter_priced_inferences(
        config, since=since, until=until, pricing=pricing
    ):
        worker = _worker_for_cost_source(str(rec.get("source", "")))
        if worker is None:
            continue
        per_loop_cost[worker] += rec["cost_usd"]
        per_loop_tokens_in[worker] += int(rec.get("input_tokens", 0) or 0)
        per_loop_tokens_out[worker] += int(rec.get("output_tokens", 0) or 0)
        per_loop_llm_calls[worker] += 1
        model_key = str(rec.get("model") or "").strip() or "unknown"
        bucket = per_loop_model[worker][model_key]
        bucket["cost_usd"] += float(rec["cost_usd"])
        bucket["calls"] += 1
        bucket["input_tokens"] += int(rec.get("input_tokens", 0) or 0)
        bucket["output_tokens"] += int(rec.get("output_tokens", 0) or 0)
        bucket["cache_read_tokens"] += int(rec.get("cache_read_input_tokens", 0) or 0)
        bucket["cache_write_tokens"] += int(
            rec.get("cache_creation_input_tokens", 0) or 0
        )

    # Prior-period window of equal length immediately before ``since``. Used
    # to populate ``tick_cost_avg_usd_prev_period`` so the client's >2x cost
    # spike highlight (PerLoopCostTable.isSpike, gated on prev > 0) can fire.
    prev_since = since - (until - since)

    prev_loop_cost: dict[str, float] = defaultdict(float)
    for rec in iter_priced_inferences(
        config, since=prev_since, until=since, pricing=pricing
    ):
        worker = _worker_for_cost_source(str(rec.get("source", "")))
        if worker is None:
            continue
        prev_loop_cost[worker] += rec["cost_usd"]

    prev_loop_ticks: dict[str, int] = defaultdict(int)
    for tr in iter_loop_traces(config, since=prev_since, until=since):
        prev_loop_ticks[_slug_for_loop(str(tr.get("loop", "?")))] += 1

    # Event-based counters (filed / closed / escalations / errored ticks). Load
    # across both windows so prior-period tick counts are available, then split
    # on the ``since`` boundary — the current half preserves the previous
    # ``load_events_since(since)`` semantics exactly.
    worker_stats: dict[str, dict[str, Any]] = {}
    prev_worker_stats: dict[str, dict[str, Any]] = {}
    if event_bus is not None:
        try:
            events = asyncio.run(event_bus.load_events_since(prev_since))
        except RuntimeError:
            # Called from an already-running event loop — fall back.
            logger.debug("build_per_loop_cost: nested event loop; skipping events")
            events = []
        cur_events, prev_events = _split_events_on(events or [], boundary=since)
        worker_stats = _tally_worker_events(cur_events)
        prev_worker_stats = _tally_worker_events(prev_events)

    # Union of every worker seen via traces, inferences, or events. All three
    # key spaces are worker_name, so they merge into one row per worker.
    name_set: set[str] = set(per_loop_ticks) | set(per_loop_cost) | set(worker_stats)

    rows: list[dict[str, Any]] = []
    for worker in sorted(name_set):
        stats = worker_stats.get(worker, {})
        ticks = int(stats.get("ticks", 0) or per_loop_ticks.get(worker, 0))
        cost = per_loop_cost.get(worker, 0.0)
        avg_cost = round(cost / ticks, 6) if ticks else 0.0
        prev_ticks = int(
            prev_worker_stats.get(worker, {}).get("ticks", 0)
            or prev_loop_ticks.get(worker, 0)
        )
        prev_cost = prev_loop_cost.get(worker, 0.0)
        prev_avg = round(prev_cost / prev_ticks, 6) if prev_ticks else 0.0
        breakdown_raw = per_loop_model.get(worker, {})
        model_breakdown = {
            model: {
                "cost_usd": round(float(b["cost_usd"]), 6),
                "calls": int(b["calls"]),
                "input_tokens": int(b["input_tokens"]),
                "output_tokens": int(b["output_tokens"]),
                "cache_read_tokens": int(b["cache_read_tokens"]),
                "cache_write_tokens": int(b["cache_write_tokens"]),
            }
            for model, b in breakdown_raw.items()
        }
        rows.append(
            {
                "loop": worker,
                "cost_usd": round(cost, 6),
                "tokens_in": per_loop_tokens_in.get(worker, 0),
                "tokens_out": per_loop_tokens_out.get(worker, 0),
                "llm_calls": per_loop_llm_calls.get(worker, 0),
                "issues_filed": int(stats.get("issues_filed", 0) or 0),
                "issues_closed": int(stats.get("issues_closed", 0) or 0),
                "escalations": int(stats.get("escalations", 0) or 0),
                "ticks": ticks,
                "ticks_errored": int(stats.get("ticks_errored", 0) or 0),
                "tick_cost_avg_usd": avg_cost,
                "wall_clock_seconds": per_loop_wall.get(worker, 0),
                "last_tick_at": stats.get("last_tick_at", "") or None,
                # Prior-period avg $/tick — drives the client >2x spike
                # highlight (PerLoopCostTable.isSpike, gated on prev > 0).
                "tick_cost_avg_usd_prev_period": prev_avg,
                "model_breakdown": model_breakdown,
            }
        )
    return rows


def build_cost_by_model(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    pricing: ModelPricingTable | None = None,
) -> list[dict[str, Any]]:
    """Return cross-loop cost broken out by model in ``[since, until)``.

    Each row: ``{model, cost_usd, calls, input_tokens, output_tokens,
    cache_read_tokens, cache_write_tokens}``. Sorted descending by
    ``cost_usd``; ties broken alphabetically by model name for deterministic
    output. Records with empty/missing ``model`` bucket under the
    literal string ``"unknown"``. Unpriced models surface their token
    counts with ``cost_usd == 0.0``.
    """
    pricing = pricing or load_pricing()

    by_model: dict[str, dict[str, float | int]] = defaultdict(_empty_model_bucket)

    for rec in iter_priced_inferences(
        config, since=since, until=until, pricing=pricing
    ):
        model_key = str(rec.get("model") or "").strip() or "unknown"
        bucket = by_model[model_key]
        bucket["cost_usd"] += rec["cost_usd"]
        bucket["calls"] += 1
        bucket["input_tokens"] += int(rec.get("input_tokens", 0) or 0)
        bucket["output_tokens"] += int(rec.get("output_tokens", 0) or 0)
        bucket["cache_read_tokens"] += int(rec.get("cache_read_input_tokens", 0) or 0)
        bucket["cache_write_tokens"] += int(
            rec.get("cache_creation_input_tokens", 0) or 0
        )

    rows = [
        {
            "model": model,
            "cost_usd": round(float(b["cost_usd"]), 6),
            "calls": int(b["calls"]),
            "input_tokens": int(b["input_tokens"]),
            "output_tokens": int(b["output_tokens"]),
            "cache_read_tokens": int(b["cache_read_tokens"]),
            "cache_write_tokens": int(b["cache_write_tokens"]),
        }
        for model, b in by_model.items()
    ]
    rows.sort(key=lambda r: (-r["cost_usd"], r["model"]))
    return rows
