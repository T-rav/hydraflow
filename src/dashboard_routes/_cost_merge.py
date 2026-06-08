"""Cross-repo merges for the Factory Cost rollup endpoints (Phase 3c-2).

The per-repo builders in :mod:`dashboard_routes._cost_rollups` each read one
repo's cost stores. Under ``repo=__all__`` the diagnostics router calls a
builder once per registered repo and folds the results here. The cost
dimensions (phase / loop / model) are *not* repo-specific, so the aggregate is
a straight group-by-sum; only per-issue rows carry a ``repo`` tag, since issue
numbers collide across repos and must stay distinct.

Merging a single-element list is identity-equivalent to the bare builder output
(modulo the additive ``repo`` tag on top-issue rows), so the router can route
both the single-repo and aggregate paths through these functions.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# Numeric precision used by the builders for USD amounts.
_USD_PLACES = 6


def merge_rolling_24h(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold several :func:`build_rolling_24h` payloads into one.

    Totals and the phase/loop breakdowns sum across repos; ``window_hours`` is
    constant (24) and ``generated_at`` takes the latest stamp.
    """
    total_cost = 0.0
    total_in = 0
    total_out = 0
    phase: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0}
    )
    loop: dict[str, dict[str, int]] = defaultdict(
        lambda: {"ticks": 0, "wall_clock_seconds": 0}
    )
    generated_at = ""

    for res in results:
        tot = res.get("total") or {}
        total_cost += float(tot.get("cost_usd", 0.0) or 0.0)
        total_in += int(tot.get("tokens_in", 0) or 0)
        total_out += int(tot.get("tokens_out", 0) or 0)
        for row in res.get("by_phase") or []:
            bucket = phase[str(row.get("phase"))]
            bucket["cost_usd"] = float(bucket["cost_usd"]) + float(
                row.get("cost_usd", 0.0) or 0.0
            )
            bucket["tokens_in"] = int(bucket["tokens_in"]) + int(
                row.get("tokens_in", 0) or 0
            )
            bucket["tokens_out"] = int(bucket["tokens_out"]) + int(
                row.get("tokens_out", 0) or 0
            )
        for row in res.get("by_loop") or []:
            lbucket = loop[str(row.get("loop"))]
            lbucket["ticks"] += int(row.get("ticks", 0) or 0)
            lbucket["wall_clock_seconds"] += int(row.get("wall_clock_seconds", 0) or 0)
        generated_at = max(generated_at, str(res.get("generated_at", "") or ""))

    by_phase = [
        {
            "phase": name,
            "cost_usd": round(float(b["cost_usd"]), _USD_PLACES),
            "tokens_in": int(b["tokens_in"]),
            "tokens_out": int(b["tokens_out"]),
        }
        for name, b in sorted(phase.items())
    ]
    by_loop = [
        {
            "loop": name,
            "ticks": int(b["ticks"]),
            "wall_clock_seconds": int(b["wall_clock_seconds"]),
        }
        for name, b in sorted(loop.items())
    ]
    return {
        "generated_at": generated_at,
        "window_hours": 24,
        "total": {
            "cost_usd": round(total_cost, _USD_PLACES),
            "tokens_in": total_in,
            "tokens_out": total_out,
        },
        "by_phase": by_phase,
        "by_loop": by_loop,
    }


def merge_top_issues(
    per_repo: list[tuple[str, list[dict[str, Any]]]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fold per-repo :func:`build_top_issues` lists into a global top-N.

    Each input is ``(repo_slug, rows)``; rows are tagged with their repo (issue
    numbers collide across repos and must stay distinct), concatenated, sorted
    descending by cost, and truncated. A globally top-N issue is necessarily
    top-N within its own repo, so merging already-truncated lists is safe.
    """
    tagged: list[dict[str, Any]] = []
    for slug, rows in per_repo:
        for row in rows:
            tagged.append({**row, "repo": slug})
    tagged.sort(
        key=lambda r: (
            -float(r.get("cost_usd", 0.0) or 0.0),
            str(r.get("repo", "")),
            int(r.get("issue", 0) or 0),
        )
    )
    return tagged[: max(1, int(limit))]


def merge_by_loop(results: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Fold several :func:`build_by_loop` lists into one, recomputing shares."""
    loop: dict[str, dict[str, int]] = defaultdict(
        lambda: {"ticks": 0, "wall_clock_seconds": 0}
    )
    for rows in results:
        for row in rows:
            bucket = loop[str(row.get("loop"))]
            bucket["ticks"] += int(row.get("ticks", 0) or 0)
            bucket["wall_clock_seconds"] += int(row.get("wall_clock_seconds", 0) or 0)

    total_ticks = sum(b["ticks"] for b in loop.values()) or 1
    return [
        {
            "loop": name,
            "ticks": int(b["ticks"]),
            "wall_clock_seconds": int(b["wall_clock_seconds"]),
            "share_of_ticks": round(b["ticks"] / total_ticks, 4),
        }
        for name, b in sorted(loop.items())
    ]


def _empty_model() -> dict[str, float | int]:
    return {
        "cost_usd": 0.0,
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _add_model_bucket(dst: dict[str, float | int], src: dict[str, Any]) -> None:
    dst["cost_usd"] = float(dst["cost_usd"]) + float(src.get("cost_usd", 0.0) or 0.0)
    dst["calls"] = int(dst["calls"]) + int(src.get("calls", 0) or 0)
    dst["input_tokens"] = int(dst["input_tokens"]) + int(
        src.get("input_tokens", 0) or 0
    )
    dst["output_tokens"] = int(dst["output_tokens"]) + int(
        src.get("output_tokens", 0) or 0
    )
    dst["cache_read_tokens"] = int(dst["cache_read_tokens"]) + int(
        src.get("cache_read_tokens", 0) or 0
    )
    dst["cache_write_tokens"] = int(dst["cache_write_tokens"]) + int(
        src.get("cache_write_tokens", 0) or 0
    )


def _finalize_model_bucket(b: dict[str, float | int]) -> dict[str, float | int]:
    return {
        "cost_usd": round(float(b["cost_usd"]), _USD_PLACES),
        "calls": int(b["calls"]),
        "input_tokens": int(b["input_tokens"]),
        "output_tokens": int(b["output_tokens"]),
        "cache_read_tokens": int(b["cache_read_tokens"]),
        "cache_write_tokens": int(b["cache_write_tokens"]),
    }


def merge_cost_by_model(results: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Fold several :func:`build_cost_by_model` lists, grouping by model."""
    by_model: dict[str, dict[str, float | int]] = defaultdict(_empty_model)
    for rows in results:
        for row in rows:
            _add_model_bucket(by_model[str(row.get("model"))], row)

    merged = [
        {"model": name, **_finalize_model_bucket(b)} for name, b in by_model.items()
    ]
    merged.sort(key=lambda r: (-float(r["cost_usd"]), str(r["model"])))
    return merged


def merge_per_loop_cost(results: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Fold several :func:`build_per_loop_cost` lists, grouping by loop.

    Additive counters sum; ``tick_cost_avg_usd`` is recomputed from the merged
    cost/ticks; ``last_tick_at`` takes the latest stamp; ``model_breakdown`` is
    merged per model. (``tick_cost_avg_usd_prev_period`` is currently a 0.0
    stub upstream, so its sum stays 0.0.)
    """
    _ADDITIVE = (
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "llm_calls",
        "issues_filed",
        "issues_closed",
        "escalations",
        "ticks",
        "ticks_errored",
        "wall_clock_seconds",
        "tick_cost_avg_usd_prev_period",
    )
    acc: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, dict[str, float | int]]] = defaultdict(
        lambda: defaultdict(_empty_model)
    )
    last_tick: dict[str, str] = defaultdict(str)

    for rows in results:
        for row in rows:
            name = str(row.get("loop"))
            bucket = acc.setdefault(name, dict.fromkeys(_ADDITIVE, 0))
            for key in _ADDITIVE:
                bucket[key] = bucket[key] + (row.get(key, 0) or 0)
            for model, mb in (row.get("model_breakdown") or {}).items():
                _add_model_bucket(models[name][str(model)], mb)
            last_tick[name] = max(
                last_tick[name], str(row.get("last_tick_at", "") or "")
            )

    merged: list[dict[str, Any]] = []
    for name in sorted(acc):
        b = acc[name]
        ticks = int(b["ticks"])
        cost = float(b["cost_usd"])
        merged.append(
            {
                "loop": name,
                "cost_usd": round(cost, _USD_PLACES),
                "tokens_in": int(b["tokens_in"]),
                "tokens_out": int(b["tokens_out"]),
                "llm_calls": int(b["llm_calls"]),
                "issues_filed": int(b["issues_filed"]),
                "issues_closed": int(b["issues_closed"]),
                "escalations": int(b["escalations"]),
                "ticks": ticks,
                "ticks_errored": int(b["ticks_errored"]),
                "tick_cost_avg_usd": round(cost / ticks, _USD_PLACES) if ticks else 0.0,
                "wall_clock_seconds": int(b["wall_clock_seconds"]),
                "last_tick_at": last_tick[name] or None,
                "tick_cost_avg_usd_prev_period": round(
                    float(b["tick_cost_avg_usd_prev_period"]), _USD_PLACES
                ),
                "model_breakdown": {
                    model: _finalize_model_bucket(mb)
                    for model, mb in sorted(models[name].items())
                },
            }
        )
    return merged
