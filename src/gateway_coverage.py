"""Pure spend-coverage read model for the LLM gateway.

The gateway metadata ledger is global while prompt telemetry is repo-scoped.
This module keeps the join explicit: callers provide one or more configs, the
collector reads each unique gateway ledger once, and :func:`build_coverage`
performs deterministic windowing, pricing, and aggregation over plain rows.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from agent_cli import AgentTool
from file_util import atomic_write
from hydraflow_gateway.ledger import GatewayLedgerRow
from model_pricing import ModelPricingTable, load_pricing
from prompt_telemetry import prompt_telemetry_source_complete
from runner_utils import one_shot_provider_names

logger = logging.getLogger("hydraflow.gateway_coverage")

CoverageStatus = Literal["no_data", "partial", "complete"]


class _CoverageConfig(Protocol):
    @property
    def data_root(self) -> Path: ...

    @property
    def repo_data_root(self) -> Path: ...

    @property
    def repo_slug(self) -> str: ...

    @property
    def cost_inferences_path(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class BypassFamily:
    """One direct one-shot family contributing to uncovered spend."""

    family: str
    calls: int
    spend_usd: float
    unpriced_calls: int
    providers: tuple[str, ...]
    repos: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "calls": self.calls,
            "spend_usd": self.spend_usd,
            "unpriced_calls": self.unpriced_calls,
            "providers": list(self.providers),
            "repos": list(self.repos),
        }


@dataclass(frozen=True, slots=True)
class GatewayCoverageSnapshot:
    """Coverage gauge value for one aligned observation window."""

    status: CoverageStatus
    scope: Literal["global", "repo"]
    repo_slug: str | None
    window_label: str
    window_start: str
    window_end: str
    generated_at: str
    gateway_spend_usd: float
    bypass_spend_usd: float
    known_total_spend_usd: float
    coverage_percent: float | None
    known_spend_coverage_percent: float | None
    gateway_requests: int
    bypass_requests: int
    unpriced_gateway_requests: int
    unpriced_bypass_requests: int
    bypassing_families: tuple[BypassFamily, ...]
    source_data_complete: bool = True
    ceiling_achieved: bool = False
    regression_detected: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope": self.scope,
            "repo_slug": self.repo_slug,
            "window_label": self.window_label,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "generated_at": self.generated_at,
            "gateway_spend_usd": self.gateway_spend_usd,
            "bypass_spend_usd": self.bypass_spend_usd,
            "known_total_spend_usd": self.known_total_spend_usd,
            "coverage_percent": self.coverage_percent,
            "known_spend_coverage_percent": self.known_spend_coverage_percent,
            "gateway_requests": self.gateway_requests,
            "bypass_requests": self.bypass_requests,
            "unpriced_gateway_requests": self.unpriced_gateway_requests,
            "unpriced_bypass_requests": self.unpriced_bypass_requests,
            "bypassing_families": [
                family.to_json_dict() for family in self.bypassing_families
            ],
            "source_data_complete": self.source_data_complete,
            "ceiling_achieved": self.ceiling_achieved,
            "regression_detected": self.regression_detected,
        }


@dataclass(frozen=True, slots=True)
class _JsonlReadResult:
    """Rows plus enough provenance to avoid a false-complete gauge."""

    rows: tuple[dict[str, object], ...]
    missing: bool
    complete: bool


@dataclass(frozen=True, slots=True)
class _SpendAggregate:
    """Priced and unpriced request totals for one coverage source."""

    spend_usd: float
    requests: int
    unpriced_requests: int


@dataclass(slots=True)
class _FamilyBucket:
    """Mutable accumulator scoped to one pure bypass aggregation call."""

    calls: int = 0
    spend_usd: float = 0.0
    unpriced_calls: int = 0
    providers: set[str] = field(default_factory=set)
    repos: set[str] = field(default_factory=set)

    def add(self, *, cost: float, unknown: bool, provider: str, repo: str) -> None:
        self.calls += 1
        self.spend_usd += cost
        self.unpriced_calls += int(unknown)
        self.providers.add(provider)
        if repo:
            self.repos.add(repo)


@dataclass(frozen=True, slots=True)
class _BypassAggregate:
    """Bypass totals and their diagnostic family breakdown."""

    spend: _SpendAggregate
    families: tuple[BypassFamily, ...]


@dataclass(frozen=True, slots=True)
class _CoverageCalculation:
    """Status and percentages derived from source aggregates."""

    status: CoverageStatus
    known_total_spend_usd: float
    coverage_percent: float | None
    known_spend_coverage_percent: float | None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _row_timestamp(row: Mapping[str, object]) -> datetime | None:
    for key in ("timestamp", "started_at", "completed_at", "created_at"):
        parsed = _parse_timestamp(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _nonnegative_int(row: Mapping[str, object], *keys: str) -> int:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if not isinstance(value, str | int | float):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        return max(0, parsed)
    return 0


def _nonnegative_cost(row: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if not isinstance(value, str | int | float):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed >= 0 and parsed < float("inf"):
            return parsed
    return None


def _row_cost(
    row: Mapping[str, object],
    pricing: ModelPricingTable,
    *,
    input_includes_cache: bool | None = None,
) -> tuple[float, bool]:
    input_tokens = _nonnegative_int(row, "input_tokens", "tokens_in")
    output_tokens = _nonnegative_int(row, "output_tokens", "tokens_out")
    cache_write = _nonnegative_int(
        row,
        "cache_creation_input_tokens",
        "cache_write_tokens",
        "cache_write",
    )
    cache_read = _nonnegative_int(
        row,
        "cache_read_input_tokens",
        "cache_read_tokens",
        "cache_read",
    )
    token_total = input_tokens + output_tokens + cache_write + cache_read
    model = str(
        row.get("model_served") or row.get("model_requested") or row.get("model") or ""
    ).strip()

    # Partial counts from an aborted / unfinished gateway stream are not a
    # price: leave such rows on their stored (unknown) cost.
    usage_complete = row.get("usage_complete") is not False
    if token_total > 0 and model and usage_complete:
        estimated = pricing.estimate_cost(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
            input_includes_cache=input_includes_cache,
        )
        if estimated is not None:
            return float(estimated), False

    stored = _nonnegative_cost(row, "cost_usd", "estimated_cost_usd")
    explicitly_unknown = row.get("cost_unknown") is True
    if stored is not None and not explicitly_unknown:
        return stored, False
    if explicitly_unknown or "cost_usd" in row or "estimated_cost_usd" in row:
        return 0.0, True
    if token_total == 0 and stored is None:
        return 0.0, False
    return 0.0, True


def _normalise_repo_slug(value: object) -> str:
    return str(value or "").strip().lower().replace("/", "-")


def _matches_repo(row: Mapping[str, object], repo_slug: str | None) -> bool:
    if repo_slug is None:
        return True
    return _normalise_repo_slug(row.get("repo_slug")) == _normalise_repo_slug(repo_slug)


def _in_window(row: Mapping[str, object], *, since: datetime, until: datetime) -> bool:
    timestamp = _row_timestamp(row)
    return timestamp is not None and since <= timestamp < until


def _is_gateway_emitted_telemetry(row: Mapping[str, object]) -> bool:
    if row.get("via_gateway") is True or row.get("gateway_transit") is True:
        return True
    if str(row.get("gateway_request_id") or "").strip():
        return True
    for key in ("tool", "provider", "transport"):
        if str(row.get(key) or "").strip().lower() == "gateway":
            return True
    return str(row.get("source") or "").strip().lower().startswith("gateway")


@cache
def _one_shot_telemetry_tools() -> frozenset[str]:
    """Resolve direct providers from the runner's canonical registry."""
    return one_shot_provider_names()


@cache
def _agentic_telemetry_tools() -> frozenset[str]:
    """Resolve CLI tools from the command builder's canonical type registry."""
    return frozenset(get_args(AgentTool))


def _is_direct_agentic(row: Mapping[str, object]) -> bool:
    """Treat every known LLM inference without gateway transit as bypass."""
    tool = str(row.get("tool") or "").strip().lower()
    known_tools = _one_shot_telemetry_tools() | _agentic_telemetry_tools()
    return tool in known_tools and not _is_gateway_emitted_telemetry(row)


def _round_cost(value: float) -> float:
    return round(value, 6)


def _coverage_percent(gateway: float, total: float) -> float | None:
    if total <= 0:
        return None
    return round(100.0 * gateway / total, 2)


def _family_rows(
    buckets: Mapping[str, _FamilyBucket],
) -> tuple[BypassFamily, ...]:
    families = [
        BypassFamily(
            family=name,
            calls=bucket.calls,
            spend_usd=_round_cost(bucket.spend_usd),
            unpriced_calls=bucket.unpriced_calls,
            providers=tuple(sorted(bucket.providers)),
            repos=tuple(sorted(bucket.repos)),
        )
        for name, bucket in buckets.items()
    ]
    return tuple(sorted(families, key=lambda row: (-row.spend_usd, row.family)))


def _valid_input_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    source: Literal["gateway", "inference"],
) -> tuple[tuple[Mapping[str, object], ...], bool]:
    """Return canonical rows and whether every input row was usable."""
    raw_rows = tuple(rows)
    valid_rows = tuple(row for row in raw_rows if _source_row_valid(row, source=source))
    return valid_rows, len(valid_rows) == len(raw_rows)


def _row_is_selected(
    row: Mapping[str, object],
    *,
    since: datetime,
    until: datetime,
    repo_slug: str | None,
) -> bool:
    return _in_window(row, since=since, until=until) and _matches_repo(row, repo_slug)


def _aggregate_gateway_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    since: datetime,
    until: datetime,
    repo_slug: str | None,
    pricing: ModelPricingTable,
) -> _SpendAggregate:
    """Aggregate valid gateway rows in the requested time and repo scope."""
    spend_usd = 0.0
    requests = 0
    unpriced_requests = 0
    for row in rows:
        if not _row_is_selected(row, since=since, until=until, repo_slug=repo_slug):
            continue
        # Gateway streams are Anthropic-shaped for every upstream: their
        # ``input_tokens`` EXCLUDES cache whatever the model's one-shot flag.
        cost, unknown = _row_cost(row, pricing, input_includes_cache=False)
        spend_usd += cost
        requests += 1
        unpriced_requests += int(unknown)
    return _SpendAggregate(
        spend_usd=spend_usd,
        requests=requests,
        unpriced_requests=unpriced_requests,
    )


def _aggregate_bypass_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    since: datetime,
    until: datetime,
    repo_slug: str | None,
    pricing: ModelPricingTable,
) -> _BypassAggregate:
    """Aggregate direct inference rows and their bypass-family diagnostics."""
    spend_usd = 0.0
    requests = 0
    unpriced_requests = 0
    family_buckets: dict[str, _FamilyBucket] = {}
    for row in rows:
        if not _row_is_selected(
            row, since=since, until=until, repo_slug=repo_slug
        ) or not _is_direct_agentic(row):
            continue
        family = str(row.get("loop_family") or row.get("source") or "").strip()
        family = family or "unattributed"
        provider = str(row.get("tool") or "unknown").strip().lower()
        row_repo = _normalise_repo_slug(row.get("repo_slug"))
        cost, unknown = _row_cost(row, pricing)

        spend_usd += cost
        requests += 1
        unpriced_requests += int(unknown)
        family_buckets.setdefault(family, _FamilyBucket()).add(
            cost=cost,
            unknown=unknown,
            provider=provider,
            repo=row_repo,
        )
    return _BypassAggregate(
        spend=_SpendAggregate(
            spend_usd=spend_usd,
            requests=requests,
            unpriced_requests=unpriced_requests,
        ),
        families=_family_rows(family_buckets),
    )


def _calculate_coverage(
    gateway: _SpendAggregate,
    bypass: _SpendAggregate,
    *,
    source_data_complete: bool,
) -> _CoverageCalculation:
    """Derive an honest status and visible percentages from source totals."""
    known_total = gateway.spend_usd + bypass.spend_usd
    unknown_total = gateway.unpriced_requests + bypass.unpriced_requests
    if unknown_total or not source_data_complete:
        status: CoverageStatus = "partial"
    elif known_total > 0:
        status = "complete"
    else:
        status = "no_data"
    known_percent = _coverage_percent(gateway.spend_usd, known_total)
    return _CoverageCalculation(
        status=status,
        known_total_spend_usd=known_total,
        coverage_percent=known_percent if status == "complete" else None,
        known_spend_coverage_percent=known_percent,
    )


def build_coverage(
    gateway_rows: Iterable[Mapping[str, object]],
    inference_rows: Iterable[Mapping[str, object]],
    *,
    since: datetime,
    until: datetime,
    window_label: str,
    scope: Literal["global", "repo"] = "global",
    repo_slug: str | None = None,
    pricing: ModelPricingTable | None = None,
    source_data_complete: bool = True,
) -> GatewayCoverageSnapshot:
    """Compute one honest gateway-spend coverage snapshot over ``[since, until)``."""
    price_table = pricing or load_pricing()
    gateway_input, gateway_complete = _valid_input_rows(gateway_rows, source="gateway")
    inference_input, inference_complete = _valid_input_rows(
        inference_rows, source="inference"
    )
    sources_complete = source_data_complete and gateway_complete and inference_complete
    gateway = _aggregate_gateway_rows(
        gateway_input,
        since=since,
        until=until,
        repo_slug=repo_slug,
        pricing=price_table,
    )
    bypass = _aggregate_bypass_rows(
        inference_input,
        since=since,
        until=until,
        repo_slug=repo_slug,
        pricing=price_table,
    )
    coverage = _calculate_coverage(
        gateway,
        bypass.spend,
        source_data_complete=sources_complete,
    )

    return GatewayCoverageSnapshot(
        status=coverage.status,
        scope=scope,
        repo_slug=repo_slug if scope == "repo" else None,
        window_label=window_label,
        window_start=since.astimezone(UTC).isoformat(),
        window_end=until.astimezone(UTC).isoformat(),
        generated_at=until.astimezone(UTC).isoformat(),
        gateway_spend_usd=_round_cost(gateway.spend_usd),
        bypass_spend_usd=_round_cost(bypass.spend.spend_usd),
        known_total_spend_usd=_round_cost(coverage.known_total_spend_usd),
        coverage_percent=coverage.coverage_percent,
        known_spend_coverage_percent=coverage.known_spend_coverage_percent,
        gateway_requests=gateway.requests,
        bypass_requests=bypass.spend.requests,
        unpriced_gateway_requests=gateway.unpriced_requests,
        unpriced_bypass_requests=bypass.spend.unpriced_requests,
        bypassing_families=bypass.families,
        source_data_complete=sources_complete,
    )


def read_jsonl_rows(path: Path) -> list[dict[str, object]]:
    """Read dictionary rows from JSONL, skipping malformed/unreadable entries."""
    return list(_read_jsonl_result(path).rows)


def _read_jsonl_result(path: Path) -> _JsonlReadResult:
    """Read JSONL while retaining missing/error state for coverage honesty."""
    rows: list[dict[str, object]] = []
    try:
        if not path.is_file():
            return _JsonlReadResult(rows=(), missing=True, complete=True)
        complete = True
        with path.open(encoding="utf-8") as stream:
            for raw_line in stream:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "Skipping malformed gateway coverage row in %s", path
                    )
                    complete = False
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    complete = False
    except (OSError, UnicodeError):
        logger.warning("Could not read gateway coverage input %s", path, exc_info=True)
        return _JsonlReadResult(rows=(), missing=False, complete=False)
    return _JsonlReadResult(
        rows=tuple(rows),
        missing=False,
        complete=complete,
    )


def _has_cost_shape(row: Mapping[str, object]) -> bool:
    """Return whether a row carries priced, unknown, or repriceable usage."""

    return any(
        key in row
        for key in (
            "cost_usd",
            "estimated_cost_usd",
            "cost_unknown",
            "input_tokens",
            "output_tokens",
            "tokens_in",
            "tokens_out",
        )
    )


def _source_row_valid(
    row: Mapping[str, object], *, source: Literal["gateway", "inference"]
) -> bool:
    """Return whether a row can be classified without hiding spend."""

    if source == "gateway":
        canonical = dict(row)
        if "timestamp" not in canonical:
            parsed = _row_timestamp(row)
            if parsed is not None:
                canonical["timestamp"] = parsed.isoformat()
        for legacy_timestamp in ("started_at", "completed_at", "created_at"):
            canonical.pop(legacy_timestamp, None)
        try:
            GatewayLedgerRow.model_validate(canonical)
        except ValueError:
            classification_ok = False
        else:
            classification_ok = True
    else:
        tool = str(row.get("tool") or "").strip().lower()
        classification_ok = tool in (
            _one_shot_telemetry_tools() | _agentic_telemetry_tools() | {"gateway"}
        ) and bool(str(row.get("source") or "").strip())
    return (
        _row_timestamp(row) is not None and _has_cost_shape(row) and classification_ok
    )


def _validate_source_rows(
    read: _JsonlReadResult,
    *,
    source: Literal["gateway", "inference"],
    path: Path,
) -> _JsonlReadResult:
    """Reject semantically unusable rows instead of silently dropping spend."""

    valid: list[dict[str, object]] = []
    complete = read.complete
    for row in read.rows:
        if _source_row_valid(row, source=source):
            valid.append(row)
            continue
        complete = False
        logger.warning("Skipping invalid %s coverage row in %s", source, path)
    return _JsonlReadResult(
        rows=tuple(valid),
        missing=read.missing,
        complete=complete,
    )


def gateway_ledger_path(config: _CoverageConfig) -> Path:
    """Resolve the shared gateway metadata ledger, honoring a dedicated path."""
    configured = getattr(config, "gateway_ledger_path", None)
    root = Path(getattr(config, "data_dir", None) or config.data_root)
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_absolute() else root / candidate
    return root / "gateway" / "requests.jsonl"


def gateway_coverage_snapshot_path(config: _CoverageConfig) -> Path:
    configured = getattr(config, "gateway_coverage_snapshot_path", None)
    if configured:
        candidate = Path(configured)
        return (
            candidate if candidate.is_absolute() else config.repo_data_root / candidate
        )
    return config.repo_data_root / "metrics" / "gateway_coverage.json"


def collect_rows(
    configs: Sequence[_CoverageConfig],
) -> tuple[list[dict[str, object]], list[dict[str, object]], bool]:
    """Collect global gateway rows once and repo-attributed prompt rows."""
    gateway_rows: list[dict[str, object]] = []
    inference_rows: list[dict[str, object]] = []
    reads: list[_JsonlReadResult] = []
    seen_gateway_paths: set[Path] = set()
    for config in configs:
        ledger_path = gateway_ledger_path(config).resolve()
        if ledger_path not in seen_gateway_paths:
            seen_gateway_paths.add(ledger_path)
            gateway_read = _validate_source_rows(
                _read_jsonl_result(ledger_path),
                source="gateway",
                path=ledger_path,
            )
            reads.append(gateway_read)
            gateway_rows.extend(gateway_read.rows)
        inference_read = _validate_source_rows(
            _read_jsonl_result(config.cost_inferences_path),
            source="inference",
            path=config.cost_inferences_path,
        )
        if not prompt_telemetry_source_complete(config.cost_inferences_path):
            inference_read = _JsonlReadResult(
                rows=inference_read.rows,
                missing=inference_read.missing,
                complete=False,
            )
        reads.append(inference_read)
        for row in inference_read.rows:
            attributed = dict(row)
            if not _normalise_repo_slug(attributed.get("repo_slug")):
                attributed["repo_slug"] = config.repo_slug
            inference_rows.append(attributed)
    any_rows = bool(gateway_rows or inference_rows)
    sources_complete = all(read.complete for read in reads) and not (
        any_rows and any(read.missing for read in reads)
    )
    return gateway_rows, inference_rows, sources_complete


def build_coverage_for_configs(
    configs: Sequence[_CoverageConfig],
    *,
    since: datetime,
    until: datetime,
    window_label: str,
    scope: Literal["global", "repo"],
    repo_slug: str | None,
    pricing: ModelPricingTable | None = None,
) -> GatewayCoverageSnapshot:
    gateway_rows, inference_rows, source_data_complete = collect_rows(configs)
    return build_coverage(
        gateway_rows,
        inference_rows,
        since=since,
        until=until,
        window_label=window_label,
        scope=scope,
        repo_slug=repo_slug,
        pricing=pricing,
        source_data_complete=source_data_complete,
    )


def persist_snapshot(
    config: _CoverageConfig, snapshot: GatewayCoverageSnapshot
) -> Path:
    """Atomically replace the repo-scoped latest coverage snapshot."""
    path = gateway_coverage_snapshot_path(config)
    payload = json.dumps(snapshot.to_json_dict(), indent=2, sort_keys=True) + "\n"
    atomic_write(path, payload)
    return path
