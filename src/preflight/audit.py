"""Append-only JSONL audit store for AutoAgentPreflightLoop (spec §3.5)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from file_util import append_jsonl, file_lock


@dataclass(frozen=True)
class PreflightAuditEntry:
    ts: str  # ISO 8601
    issue: int
    sub_label: str
    attempt_n: int
    prompt_hash: str
    cost_usd: float
    wall_clock_s: float
    tokens: int
    status: str  # "resolved" | "needs_human" | "fatal" | "pr_failed" | "cost_exceeded" | "timeout"
    pr_url: str | None
    diagnosis: str
    llm_summary: str


@dataclass(frozen=True)
class AuditWindowStats:
    spend_usd: float
    attempts: int
    resolved: int
    resolution_rate: float
    p50_cost_usd: float
    p95_cost_usd: float
    p50_wall_clock_s: float
    p95_wall_clock_s: float


class PreflightAuditStore:
    """Append-only JSONL store at <data_root>/auto_agent/audit.jsonl."""

    def __init__(self, data_root: Path) -> None:
        self._path = data_root / "auto_agent" / "audit.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: PreflightAuditEntry) -> None:
        with file_lock(Path(str(self._path) + ".lock")):
            append_jsonl(self._path, json.dumps(asdict(entry)))

    def _read_all(self) -> list[PreflightAuditEntry]:
        if not self._path.exists():
            return []
        out: list[PreflightAuditEntry] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                out.append(PreflightAuditEntry(**row))
        return out

    def query_window(self, since: datetime) -> AuditWindowStats:
        entries = [
            e
            for e in self._read_all()
            if datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= since
        ]
        return _compute_window(entries)

    def query_24h(self) -> AuditWindowStats:
        return self.query_window(datetime.now(UTC) - timedelta(hours=24))

    def query_7d(self) -> AuditWindowStats:
        return self.query_window(datetime.now(UTC) - timedelta(days=7))

    def top_spend(
        self, n: int = 5, since: datetime | None = None
    ) -> list[PreflightAuditEntry]:
        entries = self._read_all()
        if since is not None:
            entries = [
                e
                for e in entries
                if datetime.fromisoformat(e.ts.replace("Z", "+00:00")) >= since
            ]
        return sorted(entries, key=lambda e: e.cost_usd, reverse=True)[:n]

    def entries_for_issue(self, issue: int) -> list[PreflightAuditEntry]:
        return [e for e in self._read_all() if e.issue == issue]


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _compute_window(entries: list[PreflightAuditEntry]) -> AuditWindowStats:
    if not entries:
        return AuditWindowStats(0.0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    costs = sorted(e.cost_usd for e in entries)
    walls = sorted(e.wall_clock_s for e in entries)
    resolved = sum(1 for e in entries if e.status == "resolved")
    return AuditWindowStats(
        spend_usd=sum(costs),
        attempts=len(entries),
        resolved=resolved,
        resolution_rate=resolved / len(entries),
        p50_cost_usd=_percentile(costs, 0.5),
        p95_cost_usd=_percentile(costs, 0.95),
        p50_wall_clock_s=_percentile(walls, 0.5),
        p95_wall_clock_s=_percentile(walls, 0.95),
    )
