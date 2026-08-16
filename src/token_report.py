"""Tokens-per-issue-by-phase report — the #11298 measurement layer.

Pure math over `PromptTelemetry.load_inferences()` rows. The token-efficiency
program's levers (session continuation, cache-aware prefixes, size tiering)
each claim a delta; this report is the instrument that proves or refutes
them, so it lands FIRST. No I/O here — the diagnostics route owns loading.

Cache hit rate uses the #11132 accumulator columns: a cold spawn reads zero
`cache_read_input_tokens`, so a near-zero rate per source is the smoking gun
for the cold-spawn context tax this program attacks.
"""

from __future__ import annotations

from typing import Any

# Issues below this many total tokens are ignored in the per-issue median —
# label-only touches and dedup no-ops would otherwise drag the median under
# what a real build costs.
MIN_ISSUE_TOKENS = 1_000


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tokens(row: dict[str, Any]) -> int:
    """Billable-ish token weight for a row: actual when present, else estimate."""
    total = _as_int(row.get("total_tokens"))
    if total > 0:
        return total
    return _as_int(row.get("total_est_tokens"))


def _cache_read(row: dict[str, Any]) -> int:
    return _as_int(row.get("cache_read_input_tokens"))


def _cost_usd(row: dict[str, Any]) -> float:
    value = row.get("estimated_cost_usd")
    return float(value) if isinstance(value, (int, float)) else 0.0


def build_token_report(
    rows: list[dict[str, Any]], *, recent_issues: int = 25
) -> dict[str, Any]:
    """Roll raw inference rows into the tokens-per-issue-by-phase report.

    Returns::

        {
          "issues": [  # newest-first, capped at recent_issues
            {"issue": N, "tokens": T, "cost_usd": C, "spawns": S,
             "cache_hit_rate": 0..1,
             "phases": [{"source": s, "tokens": t, "cost_usd": c,
                         "spawns": n, "cache_hit_rate": r}, ...]},  # desc tokens
            ...
          ],
          "fleet": {
            "issues_counted": N, "median_tokens_per_issue": M,
            "mean_tokens_per_issue": A, "mean_spawns_per_issue": S,
            "phase_share": [{"source": s, "tokens": t, "share": 0..1,
                             "cache_hit_rate": r}, ...],  # desc tokens
          },
        }

    ``cache_hit_rate`` = cache_read / (input + cache_read) over rows that
    report actual usage; ``None`` when no row in the bucket carries actual
    input tokens (estimate-only rows can't witness caching).
    """
    per_issue: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        issue = _as_int(row.get("issue_number"))
        if issue <= 0:
            continue
        per_issue.setdefault(issue, []).append(row)

    def _bucket_stats(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        tokens = sum(_tokens(r) for r in bucket)
        cost = sum(_cost_usd(r) for r in bucket)
        cache_read = sum(_cache_read(r) for r in bucket)
        actual_input = sum(
            _as_int(r.get("input_tokens"))
            for r in bucket
            if _as_int(r.get("input_tokens")) > 0
        )
        denominator = actual_input + cache_read
        rate = (cache_read / denominator) if denominator > 0 else None
        return {
            "tokens": tokens,
            "cost_usd": round(cost, 4),
            "spawns": len(bucket),
            "cache_hit_rate": round(rate, 3) if rate is not None else None,
        }

    issues_out: list[dict[str, Any]] = []
    # Newest-first: load_inferences returns oldest→newest, so later rows are
    # fresher; order issues by the position of their last row.
    last_seen = {
        issue: i
        for i, row in enumerate(rows)
        if (issue := _as_int(row.get("issue_number"))) > 0
    }
    for issue in sorted(per_issue, key=lambda n: last_seen.get(n, 0), reverse=True):
        bucket = per_issue[issue]
        stats = _bucket_stats(bucket)
        if stats["tokens"] < MIN_ISSUE_TOKENS:
            continue
        by_source: dict[str, list[dict[str, Any]]] = {}
        for row in bucket:
            by_source.setdefault(str(row.get("source", "?")), []).append(row)
        phases = sorted(
            (
                {"source": source, **_bucket_stats(source_rows)}
                for source, source_rows in by_source.items()
            ),
            key=lambda p: p["tokens"],
            reverse=True,
        )
        issues_out.append({"issue": issue, **stats, "phases": phases})
        if len(issues_out) >= recent_issues:
            break

    totals = [entry["tokens"] for entry in issues_out]
    fleet: dict[str, Any] = {
        "issues_counted": len(issues_out),
        "median_tokens_per_issue": sorted(totals)[len(totals) // 2] if totals else 0,
        "mean_tokens_per_issue": int(sum(totals) / len(totals)) if totals else 0,
        "mean_spawns_per_issue": (
            round(sum(e["spawns"] for e in issues_out) / len(issues_out), 1)
            if issues_out
            else 0.0
        ),
    }
    fleet_sources: dict[str, list[dict[str, Any]]] = {}
    for entry in issues_out:
        for issue_rows in (per_issue[entry["issue"]],):
            for row in issue_rows:
                fleet_sources.setdefault(str(row.get("source", "?")), []).append(row)
    grand_total = sum(_tokens(r) for rs in fleet_sources.values() for r in rs) or 1
    fleet["phase_share"] = sorted(
        (
            {
                "source": source,
                "tokens": (stats := _bucket_stats(source_rows))["tokens"],
                "share": round(stats["tokens"] / grand_total, 3),
                "cache_hit_rate": stats["cache_hit_rate"],
            }
            for source, source_rows in fleet_sources.items()
        ),
        key=lambda p: p["tokens"],
        reverse=True,
    )
    return {"issues": issues_out, "fleet": fleet}
