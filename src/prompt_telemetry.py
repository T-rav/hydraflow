"""Prompt/inference telemetry for ROI tracking and token-efficiency analysis."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit_chain import AuditChain
from config import HydraFlowConfig
from file_util import atomic_write, file_lock
from model_pricing import ModelPricingTable, input_includes_cache_for, load_pricing

logger = logging.getLogger("hydraflow.prompt_telemetry")

_HEALTH_LOCK = threading.Lock()
_HEALTH_STATE: dict[Path, dict[str, object]] = {}


_MODEL_CHARS_PER_TOKEN: tuple[tuple[tuple[str, ...], float, str], ...] = (
    (("gpt-5", "codex"), 3.7, "medium"),
    (("claude", "sonnet", "opus"), 3.9, "medium"),
)

# Prompts smaller than this may legitimately return zero tokens (stubs,
# no-ops, cached identity responses). Above the threshold, a zero-usage
# "success" is almost always a CLI-swallowed API rejection (spend cap,
# 400 invalid_request_error, etc.) and should not contribute phantom cost.
_ZERO_USAGE_PROMPT_THRESHOLD = 500


@dataclass(frozen=True, slots=True)
class _UsageMetrics:
    """Normalized usage fields supplied by an agent runtime."""

    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    available: bool
    status: str


@dataclass(frozen=True, slots=True)
class _TokenMetrics:
    """Model-aware estimates and the effective token accounting for one call."""

    prompt_tokens: int
    transcript_tokens: int
    estimated_total_tokens: int
    effective_total_tokens: int
    source: str
    chars_per_token: float
    estimate_confidence: str


def prompt_telemetry_health_path(inferences_path: Path) -> Path:
    """Return the durable source-health marker beside an inference ledger."""

    return inferences_path.with_name(f"{inferences_path.name}.health.json")


def _read_prompt_telemetry_health(
    marker: Path,
) -> tuple[bool, dict[str, object] | None]:
    """Read a health marker without mistaking corruption for health."""

    try:
        if not marker.is_file():
            return True, None
        parsed = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None
    if not isinstance(parsed, dict):
        return False, None
    return True, parsed


def prompt_telemetry_source_complete(inferences_path: Path) -> bool:
    """Return false after an observed append failure or interrupted write."""

    key = inferences_path.absolute()
    with _HEALTH_LOCK:
        in_process = _HEALTH_STATE.get(key)
        if in_process is not None and (
            in_process.get("degraded") is True or in_process.get("writing") is True
        ):
            return False
    marker = prompt_telemetry_health_path(inferences_path)
    marker_valid, payload = _read_prompt_telemetry_health(marker)
    if not marker_valid:
        return False
    if payload is not None and payload.get("status") != "healthy":
        return False
    try:
        verification = AuditChain(inferences_path).verify()
    except (OSError, ValueError):
        return False
    if not verification.ok or verification.warnings:
        return False
    expected_head = payload.get("chain_head") if payload is not None else None
    expected_count = payload.get("record_count") if payload is not None else None
    head_matches = (
        not isinstance(expected_head, str) or verification.head == expected_head
    )
    count_matches = not isinstance(expected_count, int) or (
        not isinstance(expected_count, bool)
        and verification.total_records == expected_count
    )
    return head_matches and count_matches


def refresh_prompt_telemetry_health_after_retention(inferences_path: Path) -> bool:
    """Advance the durable count/head after a sanctioned prefix prune.

    This never clears a degraded marker: retention may acknowledge only a
    healthy chain that HydraFlow itself just pruned, not repair evidence loss.
    """

    try:
        verification = AuditChain(inferences_path).verify()
    except (OSError, ValueError):
        return False
    if not verification.ok or verification.warnings:
        return False

    marker = prompt_telemetry_health_path(inferences_path)
    marker_valid, payload = _read_prompt_telemetry_health(marker)
    if not marker_valid or (payload is not None and payload.get("status") != "healthy"):
        return False

    key = inferences_path.absolute()
    now = datetime.now(UTC).isoformat()
    with _HEALTH_LOCK:
        state = _HEALTH_STATE.get(key)
        if state is not None and (
            state.get("degraded") is True or state.get("writing") is True
        ):
            return False
        next_payload = {
            **(payload or {}),
            "status": "healthy",
            "updated_at": now,
            "dropped_writes": (payload or {}).get("dropped_writes", 0),
            "first_failure_at": (payload or {}).get("first_failure_at"),
            "chain_head": verification.head,
            "record_count": verification.total_records,
        }
        if state is not None:
            state["writing"] = False
            state["chain_head"] = verification.head
            state["record_count"] = verification.total_records
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(marker, json.dumps(next_payload, sort_keys=True) + "\n")
        except OSError:
            logger.warning(
                "Could not refresh prompt telemetry retention marker %s",
                marker,
                exc_info=True,
            )
            return False
    return True


def _estimate_tokens(chars: int, model: str) -> tuple[int, float, str]:
    """Estimate token count from character count with model-aware heuristics."""
    if chars <= 0:
        return 0, 4.0, "low"
    model_l = model.lower()
    chars_per_token = 4.0
    confidence = "low"
    for needles, ratio, label in _MODEL_CHARS_PER_TOKEN:
        if any(n in model_l for n in needles):
            chars_per_token = ratio
            confidence = label
            break
    return max(1, round(chars / chars_per_token)), chars_per_token, confidence


def _normalize_usage(stats: dict[str, object]) -> _UsageMetrics:
    """Normalize backend usage, deriving a missing total before availability."""

    input_tokens = max(0, _as_int(stats.get("input_tokens", 0)))
    output_tokens = max(0, _as_int(stats.get("output_tokens", 0)))
    total_tokens = max(0, _as_int(stats.get("total_tokens", 0)))
    # #11117: input/output without a pre-summed total is still real usage.
    if total_tokens <= 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    available = bool(stats.get("usage_available", total_tokens > 0))
    status = str(stats.get("usage_status", "")).strip().lower()
    if status not in {"available", "unavailable"}:
        status = "available" if available else "unavailable"
    return _UsageMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=max(
            0, _as_int(stats.get("cache_creation_input_tokens", 0))
        ),
        cache_read_tokens=max(0, _as_int(stats.get("cache_read_input_tokens", 0))),
        total_tokens=total_tokens,
        available=available,
        status=status,
    )


def _calculate_token_metrics(
    *,
    prompt_chars: int,
    transcript_chars: int,
    model: str,
    success: bool,
    actual_total_tokens: int,
) -> _TokenMetrics:
    """Calculate estimated and effective token values for one call."""

    prompt_tokens, chars_per_token, estimate_confidence = _estimate_tokens(
        prompt_chars, model
    )
    transcript_tokens, _, _ = _estimate_tokens(transcript_chars, model)
    estimated_total_tokens = prompt_tokens + transcript_tokens
    if not success and actual_total_tokens == 0 and transcript_chars == 0:
        estimated_total_tokens = 0
    return _TokenMetrics(
        prompt_tokens=prompt_tokens,
        transcript_tokens=transcript_tokens,
        estimated_total_tokens=estimated_total_tokens,
        effective_total_tokens=(actual_total_tokens or estimated_total_tokens),
        source="actual" if actual_total_tokens > 0 else "estimated",
        chars_per_token=chars_per_token,
        estimate_confidence=estimate_confidence,
    )


def _is_zero_usage_anomaly(usage: _UsageMetrics, prompt_chars: int) -> bool:
    """Return whether a non-trivial successful-looking call reported no usage."""

    return (
        not usage.available
        and usage.total_tokens == 0
        and prompt_chars > _ZERO_USAGE_PROMPT_THRESHOLD
    )


def _clean_section_chars(value: object) -> dict[str, int]:
    """Normalize optional prompt-section sizes for durable JSON storage."""

    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, int] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if key:
            cleaned[key] = max(0, _as_int(raw_value))
    return cleaned


def _clean_raw_usage(value: object) -> list[dict[str, object]]:
    """Keep the bounded, schema-safe subset of optional backend usage events."""

    if not isinstance(value, list):
        return []
    cleaned_events: list[dict[str, object]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        cleaned: dict[str, object] = {}
        for key in ("backend", "event_type", "path"):
            field = item.get(key)
            if isinstance(field, str):
                cleaned[key] = field
        payload = item.get("payload")
        if isinstance(payload, dict):
            cleaned["payload"] = payload
        if cleaned:
            cleaned_events.append(cleaned)
    return cleaned_events


class PromptTelemetry:
    """Writes prompt/inference metrics to filesystem-backed JSON artifacts."""

    def __init__(
        self,
        config: HydraFlowConfig,
        pricing: ModelPricingTable | None = None,
    ) -> None:
        self._config = config
        self._inferences_file = config.cost_inferences_path
        self._pr_stats_file = config.pr_stats_path
        self._dir = self._inferences_file.parent
        self._lock_file = self._dir / ".lock"
        self._pricing = pricing or load_pricing()
        # Hash-chained append path for inferences.jsonl (CH-1, #9729).
        self._chain = AuditChain(self._inferences_file)

    def _set_source_health(
        self,
        status: str,
        *,
        chain_head: str | None = None,
        record_count: int | None = None,
    ) -> None:
        """Persist append health without exposing inference or credential data."""

        key = self._inferences_file.absolute()
        marker = prompt_telemetry_health_path(self._inferences_file)
        now = datetime.now(UTC).isoformat()
        with _HEALTH_LOCK:
            state = _HEALTH_STATE.get(key)
            if state is None:
                existing: dict[str, object] = {}
                marker_present = False
                try:
                    marker_present = marker.is_file()
                    parsed = json.loads(marker.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        existing = parsed
                except (OSError, json.JSONDecodeError):
                    if marker_present:
                        existing = {"status": "degraded"}
                existing_status = existing.get("status")
                state = {
                    "degraded": existing_status in {"degraded", "writing"},
                    "writing": False,
                    "dropped_writes": max(
                        0, _as_int(existing.get("dropped_writes", 0))
                    ),
                    "first_failure_at": existing.get("first_failure_at"),
                    "chain_head": existing.get("chain_head"),
                    "record_count": existing.get("record_count", 0),
                }
                _HEALTH_STATE[key] = state

            if status == "writing":
                state["writing"] = True
            elif status == "degraded":
                state["writing"] = False
                state["degraded"] = True
                state["dropped_writes"] = _as_int(state["dropped_writes"]) + 1
                if not state.get("first_failure_at"):
                    state["first_failure_at"] = now
            elif status == "healthy":
                state["writing"] = False
                if chain_head is not None:
                    state["chain_head"] = chain_head
                if record_count is not None:
                    state["record_count"] = record_count

            effective_status = (
                "degraded"
                if state.get("degraded") is True
                else "writing"
                if state.get("writing") is True
                else "healthy"
            )
            payload = {
                "status": effective_status,
                "updated_at": now,
                "dropped_writes": state["dropped_writes"],
                "first_failure_at": state.get("first_failure_at"),
                "chain_head": state.get("chain_head"),
                "record_count": state.get("record_count", 0),
            }
            # Keep state transition and durable marker write serialized. If
            # two telemetry writers race, an older healthy payload must never
            # overwrite a newer degraded latch after the lock is released.
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(marker, json.dumps(payload, sort_keys=True) + "\n")
            except OSError:
                # The in-process signal remains authoritative until restart.
                # The pre-write "writing" marker also remains durable if this
                # final update fails after an append error.
                logger.warning(
                    "Could not write prompt telemetry health marker %s",
                    marker,
                    exc_info=True,
                )

    def _estimate_record_cost(
        self,
        *,
        model: str,
        tool: str,
        usage_shape: str | None,
        success: bool,
        zero_usage_anomaly: bool,
        usage: _UsageMetrics,
        tokens: _TokenMetrics,
        transcript_chars: int,
    ) -> float | None:
        """Return billed-or-estimated cost without inventing failed-run spend.

        Cache-inclusiveness follows the usage SHAPE the writer stamped (then
        the tool marker for unstamped rows), never the model id alone — see
        :func:`model_pricing.input_includes_cache_for`.
        """

        # An API rejection before billing, or a failed run with no reported
        # usage/output, must not contribute a prompt-character cost estimate.
        if zero_usage_anomaly or (
            not success and usage.total_tokens == 0 and transcript_chars == 0
        ):
            return 0.0
        cost = self._pricing.estimate_cost(
            model,
            input_tokens=usage.input_tokens or tokens.prompt_tokens,
            output_tokens=usage.output_tokens or tokens.transcript_tokens,
            cache_write_tokens=usage.cache_creation_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            input_includes_cache=input_includes_cache_for(usage_shape, tool),
        )
        return round(cost, 6) if cost is not None else None

    def _append_record_with_health(self, record: dict[str, object]) -> None:
        """Append one record and durably transition its source-health marker."""

        self._set_source_health("writing")
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with file_lock(self._lock_file):
                self._chain.append(record)
                self._update_pr_stats(record)
        except (OSError, ValueError):
            # ValueError covers AuditChain serialization failures (incl.
            # json.JSONDecodeError from scrub paths). record() runs unguarded
            # in BaseRunner._execute's ``finally`` — telemetry must never
            # convert a successful agent run into a hard failure.
            logger.warning(
                "Could not write prompt telemetry to %s",
                self._inferences_file,
                exc_info=True,
            )
            self._set_source_health("degraded")
            return
        self._update_health_from_chain()

    def _update_health_from_chain(self) -> None:
        """Verify the post-append chain and persist its durable head/count."""

        try:
            verification = self._chain.verify()
        except (OSError, ValueError):
            self._set_source_health("degraded")
            return
        if not verification.ok or verification.warnings:
            self._set_source_health("degraded")
            return
        self._set_source_health(
            "healthy",
            chain_head=verification.head,
            record_count=verification.total_records,
        )

    def record(
        self,
        *,
        source: str,
        tool: str,
        model: str,
        issue_number: int | None,
        pr_number: int | None,
        session_id: str | None,
        prompt_chars: int,
        transcript_chars: int,
        duration_seconds: float,
        success: bool,
        stats: dict[str, object] | None = None,
        usage_shape: str | None = None,
    ) -> None:
        """Append one inference record and update aggregate per-PR stats.

        ``usage_shape`` (``model_pricing.USAGE_SHAPE_*``) records how the
        usage counts were produced — Anthropic-shaped stream (cache excluded
        from ``input_tokens``) or OpenAI-compat one-shot response (cache
        included) — so readers price by transport rather than model id.
        ``None`` is stored for callers that cannot tell; readers then fall
        back to the tool marker.
        """
        st = stats or {}

        history_before = max(0, _as_int(st.get("history_chars_before", 0)))
        history_after = max(0, _as_int(st.get("history_chars_after", 0)))
        context_before = max(0, _as_int(st.get("context_chars_before", 0)))
        context_after = max(0, _as_int(st.get("context_chars_after", 0)))
        cache_hits = max(0, _as_int(st.get("cache_hits", 0)))
        cache_misses = max(0, _as_int(st.get("cache_misses", 0)))
        usage = _normalize_usage(st)

        history_saved = max(0, history_before - history_after)
        context_saved = max(0, context_before - context_after)
        explicit_pruned = max(0, _as_int(st.get("pruned_chars_total", 0)))
        has_explicit_pruned = "pruned_chars_total" in st

        shared_prefix_chars = max(0, _as_int(st.get("shared_prefix_chars", 0)))
        unique_suffix_chars = max(0, _as_int(st.get("unique_suffix_chars", 0)))
        prefix_total = shared_prefix_chars + unique_suffix_chars
        prefix_cache_reuse_ratio = (
            round(shared_prefix_chars / prefix_total, 3) if prefix_total > 0 else 0.0
        )

        tokens = _calculate_token_metrics(
            prompt_chars=prompt_chars,
            transcript_chars=transcript_chars,
            model=model,
            success=success,
            actual_total_tokens=usage.total_tokens,
        )

        # Zero-usage sanity guard: a "successful" CLI run that reports zero
        # tokens on a non-trivial prompt is almost always a silently-swallowed
        # API rejection. Reclassify as failed and zero the estimated cost so
        # the dashboard does not attribute phantom spend.
        zero_usage_anomaly = _is_zero_usage_anomaly(usage, prompt_chars)
        effective_success = success and not zero_usage_anomaly

        record: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "source": source,
            "tool": tool,
            "model": model,
            "issue_number": issue_number,
            "pr_number": pr_number,
            "session_id": session_id or "",
            "prompt_chars": prompt_chars,
            "prompt_est_tokens": tokens.prompt_tokens,
            "transcript_chars": transcript_chars,
            "transcript_est_tokens": tokens.transcript_tokens,
            "total_est_tokens": tokens.estimated_total_tokens,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": usage.cache_creation_tokens,
            "cache_read_input_tokens": usage.cache_read_tokens,
            "usage_shape": usage_shape,
            "total_tokens": tokens.effective_total_tokens,
            "token_source": tokens.source,
            "usage_status": usage.status,
            "usage_available": usage.available,
            "duration_seconds": round(duration_seconds, 3),
            "status": "success" if effective_success else "failed",
            "token_estimation_mode": "model-aware-chars-per-token",
            "token_estimation_chars_per_token": tokens.chars_per_token,
            "token_estimation_confidence": tokens.estimate_confidence,
            "history_chars_before": history_before,
            "history_chars_after": history_after,
            "history_chars_saved": history_saved,
            "history_prune_roi": (
                round(history_saved / history_before, 4) if history_before else 0.0
            ),
            "context_chars_before": context_before,
            "context_chars_after": context_after,
            "context_chars_saved": context_saved,
            "context_prune_roi": (
                round(context_saved / context_before, 4) if context_before else 0.0
            ),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": (
                round(cache_hits / (cache_hits + cache_misses), 4)
                if (cache_hits + cache_misses)
                else 0.0
            ),
            # Prefer explicit pruned totals from prompt builders when provided.
            # Fallback to derived before/after deltas for legacy callers.
            "pruned_chars_total": (
                explicit_pruned
                if has_explicit_pruned
                else max(0, history_saved + context_saved)
            ),
            "shared_prefix_chars": shared_prefix_chars,
            "unique_suffix_chars": unique_suffix_chars,
            "prefix_cache_reuse_ratio": prefix_cache_reuse_ratio,
        }
        record["estimated_cost_usd"] = self._estimate_record_cost(
            model=model,
            tool=tool,
            usage_shape=usage_shape,
            success=success,
            zero_usage_anomaly=zero_usage_anomaly,
            usage=usage,
            tokens=tokens,
            transcript_chars=transcript_chars,
        )
        if zero_usage_anomaly:
            record["usage_anomaly"] = "zero_usage_with_prompt"
        clean_sections = _clean_section_chars(st.get("section_chars"))
        if clean_sections:
            record["section_chars"] = clean_sections
        cleaned_raw = _clean_raw_usage(st.get("raw_usage"))
        if cleaned_raw:
            record["raw_usage"] = cleaned_raw

        self._append_record_with_health(record)

    def _update_pr_stats(self, record: dict[str, object]) -> None:
        data = self._load_pr_stats()
        lifetime = _get_or_init_dict(data, "lifetime", _new_counter())
        self._accumulate_counter(lifetime, record)

        sessions = _get_or_init_dict(data, "sessions", {})
        session_id = str(record.get("session_id", "")).strip()
        if session_id:
            sess_entry = _get_or_init_dict(sessions, session_id, _new_counter())
            self._accumulate_counter(sess_entry, record)

        prs = _get_or_init_dict(data, "prs", {})
        pr_number = record.get("pr_number")
        if isinstance(pr_number, int) and pr_number > 0:
            entry = _get_or_init_dict(prs, str(pr_number), _new_counter())
            self._accumulate_counter(entry, record)

        issues = _get_or_init_dict(data, "issues", {})
        issue_number = record.get("issue_number")
        if isinstance(issue_number, int) and issue_number > 0:
            issue_entry = _get_or_init_dict(issues, str(issue_number), _new_counter())
            self._accumulate_counter(issue_entry, record)

        sources = _get_or_init_dict(data, "sources", {})
        source = str(record.get("source", "")).strip()
        if source:
            source_entry = _get_or_init_dict(sources, source, _new_counter())
            self._accumulate_counter(source_entry, record)

        data["updated_at"] = str(record.get("timestamp", ""))

        try:
            atomic_write(
                self._pr_stats_file, json.dumps(data, indent=2, sort_keys=True)
            )
        except OSError:
            logger.warning(
                "Could not write per-PR prompt stats to %s",
                self._pr_stats_file,
                exc_info=True,
            )

    def _load_pr_stats(self) -> dict[str, object]:
        if not self._pr_stats_file.is_file():
            return {}
        try:
            raw = self._pr_stats_file.read_text()
        except OSError:
            return {}
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Per-PR stats file is corrupt, rebuilding")
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def get_mtime(self) -> float:
        """Return the modification time of the inferences file, or 0.0."""
        try:
            return (
                self._inferences_file.stat().st_mtime
                if self._inferences_file.is_file()
                else 0.0
            )
        except OSError:
            return 0.0

    def load_inferences(
        self,
        *,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Load recent inference rows from JSONL, newest last."""
        if limit <= 0:
            return []
        if not self._inferences_file.is_file():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with open(self._inferences_file) as f:
                for raw_line in f:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    try:
                        parsed = json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Skipping corrupt inference line in %s",
                            self._inferences_file,
                            exc_info=True,
                        )
                        continue
                    if isinstance(parsed, dict):
                        rows.append(parsed)
        except OSError:
            logger.warning(
                "Could not read prompt telemetry from %s",
                self._inferences_file,
                exc_info=True,
            )
            return []
        if len(rows) > limit:
            return rows[-limit:]
        return rows

    @staticmethod
    def _accumulate_counter(
        target: dict[str, object], record: dict[str, object]
    ) -> None:
        target["inference_calls"] = _as_int(target.get("inference_calls", 0)) + 1
        target["prompt_est_tokens"] = _as_int(
            target.get("prompt_est_tokens", 0)
        ) + _as_int(record.get("prompt_est_tokens", 0))
        target["total_est_tokens"] = _as_int(
            target.get("total_est_tokens", 0)
        ) + _as_int(record.get("total_est_tokens", 0))
        target["total_tokens"] = _as_int(target.get("total_tokens", 0)) + _as_int(
            record.get("total_tokens", 0)
        )
        target["history_chars_saved"] = _as_int(
            target.get("history_chars_saved", 0)
        ) + _as_int(record.get("history_chars_saved", 0))
        target["context_chars_saved"] = _as_int(
            target.get("context_chars_saved", 0)
        ) + _as_int(record.get("context_chars_saved", 0))
        target["cache_hits"] = _as_int(target.get("cache_hits", 0)) + _as_int(
            record.get("cache_hits", 0)
        )
        target["cache_misses"] = _as_int(target.get("cache_misses", 0)) + _as_int(
            record.get("cache_misses", 0)
        )
        # #11132: cache token columns were recorded per-inference but never
        # accumulated, so every aggregate (source/lifetime/session/PR/issue)
        # silently reported a cacheless world.
        target["cache_creation_input_tokens"] = _as_int(
            target.get("cache_creation_input_tokens", 0)
        ) + _as_int(record.get("cache_creation_input_tokens", 0))
        target["cache_read_input_tokens"] = _as_int(
            target.get("cache_read_input_tokens", 0)
        ) + _as_int(record.get("cache_read_input_tokens", 0))
        target["actual_usage_calls"] = _as_int(target.get("actual_usage_calls", 0))
        if record.get("token_source") == "actual":
            target["actual_usage_calls"] = _as_int(target["actual_usage_calls"]) + 1
        target["usage_unavailable_calls"] = _as_int(
            target.get("usage_unavailable_calls", 0)
        )
        if record.get("usage_status") == "unavailable":
            target["usage_unavailable_calls"] = (
                _as_int(target["usage_unavailable_calls"]) + 1
            )
        target["pruned_chars_total"] = _as_int(
            target.get("pruned_chars_total", 0)
        ) + _as_int(record.get("pruned_chars_total", 0))
        # #11280: track the most-recently-seen model per aggregate so
        # `get_source_regimes()` can tell a prompt-efficiency baseline "this
        # source was last measured under a different (provider, model)
        # regime" — a pricing-regime change (e.g. claude -> glm) must not
        # trend as a cost improvement/regression against a stale baseline.
        # `_accumulate_counter` runs in record-append order (single file lock
        # in `record()`), so the last write here is always the latest model.
        incoming_model = str(record.get("model", "")).strip()
        if incoming_model:
            target["last_model"] = incoming_model
        record_cost = record.get("estimated_cost_usd")
        if isinstance(record_cost, int | float) and record_cost > 0:
            target["estimated_cost_usd"] = round(
                _as_float(target.get("estimated_cost_usd", 0.0)) + float(record_cost),
                6,
            )
            # Int mirror of the float accumulator above (micro-USD, i.e.
            # USD * 1e6). `get_source_totals()` (and its lifetime/session/PR/
            # issue siblings) filter aggregate payloads to `isinstance(v, int)`
            # before returning them, silently dropping the float
            # `estimated_cost_usd` key — this int accumulator is what lets
            # per-source cost survive that filter for `prompt_efficiency`'s
            # scorecard math (spec §5).
            target["estimated_cost_microusd"] = _as_int(
                target.get("estimated_cost_microusd", 0)
            ) + round(float(record_cost) * 1_000_000)
            # #11117 (review find): a small-prompt zero-usage call can still
            # carry char-ESTIMATED cost. `prompt_efficiency` excludes such
            # calls from its rate denominators, so their cost must be
            # subtractable from the numerator too or window rates inflate —
            # the mirror image of the deflation bug. Same-population math
            # needs this parallel accumulator.
            if record.get("usage_status") == "unavailable":
                target["unavailable_est_cost_microusd"] = _as_int(
                    target.get("unavailable_est_cost_microusd", 0)
                ) + round(float(record_cost) * 1_000_000)
        target["last_updated"] = str(record.get("timestamp", ""))

    def get_pr_totals(self, pr_number: int) -> dict[str, int] | None:
        """Return aggregate telemetry totals for a PR, or None if missing."""
        data = self._load_pr_stats()
        prs = data.get("prs", {})
        if not isinstance(prs, dict):
            return None
        entry = prs.get(str(pr_number))
        if not isinstance(entry, dict):
            return None
        return {k: int(v) for k, v in entry.items() if isinstance(v, int)}

    def get_lifetime_totals(self) -> dict[str, int]:
        """Return aggregate telemetry totals across all sessions."""
        data = self._load_pr_stats()
        lifetime = data.get("lifetime", {})
        if not isinstance(lifetime, dict):
            return {}
        return {k: int(v) for k, v in lifetime.items() if isinstance(v, int)}

    def get_session_totals(self, session_id: str) -> dict[str, int]:
        """Return aggregate telemetry totals for a single session ID."""
        if not session_id:
            return {}
        data = self._load_pr_stats()
        sessions = data.get("sessions", {})
        if not isinstance(sessions, dict):
            return {}
        entry = sessions.get(session_id, {})
        if not isinstance(entry, dict):
            return {}
        return {k: int(v) for k, v in entry.items() if isinstance(v, int)}

    def get_issue_totals(self) -> dict[int, dict[str, int]]:
        """Return aggregate telemetry totals keyed by issue number."""
        data = self._load_pr_stats()
        issues = data.get("issues", {})
        if not isinstance(issues, dict):
            return {}
        result: dict[int, dict[str, int]] = {}
        for key, payload in issues.items():
            if not isinstance(payload, dict):
                continue
            try:
                issue_number = int(key)
            except (TypeError, ValueError):
                continue
            result[issue_number] = {
                k: int(v) for k, v in payload.items() if isinstance(v, int)
            }
        return result

    def get_source_totals(self) -> dict[str, dict[str, int]]:
        """Return aggregate telemetry totals keyed by source."""
        data = self._load_pr_stats()
        sources = data.get("sources", {})
        if not isinstance(sources, dict):
            return {}
        result: dict[str, dict[str, int]] = {}
        for key, payload in sources.items():
            source = str(key).strip()
            if not source or not isinstance(payload, dict):
                continue
            result[source] = {
                k: int(v) for k, v in payload.items() if isinstance(v, int)
            }
        return result

    def get_source_regimes(self) -> dict[str, str]:
        """Return each source's most-recently-recorded model (#11280).

        Sibling to :meth:`get_source_totals`, reading the same ``sources``
        aggregate but pulling the string ``last_model`` field the totals'
        int-only filter drops. Consumed by `prompt_efficiency.compute_skill_
        efficiency` to null a trend when the current regime doesn't match the
        baseline's — a pricing-regime change (e.g. claude -> glm) must start a
        fresh baseline, not read as a cost improvement/regression.
        """
        data = self._load_pr_stats()
        sources = data.get("sources", {})
        if not isinstance(sources, dict):
            return {}
        result: dict[str, str] = {}
        for key, payload in sources.items():
            source = str(key).strip()
            if not source or not isinstance(payload, dict):
                continue
            model = str(payload.get("last_model", "")).strip()
            if model:
                result[source] = model
        return result


def parse_command_tool_model(cmd: list[str]) -> tuple[str, str]:
    """Extract ``(tool, model)`` from an agent command list."""
    tool = cmd[0] if cmd else "unknown"
    model = ""
    for i, part in enumerate(cmd):
        if part == "--model" and i + 1 < len(cmd):
            model = cmd[i + 1]
            break
    return tool, model


def rewrite_command_model(cmd: list[str], model: str) -> list[str]:
    """Return a copy of *cmd* with its ``--model`` value set to *model*.

    The writer counterpart to :func:`parse_command_tool_model`. Credit-failover
    (#10844) uses it to force a work spawn onto the GLM model when it reroutes
    the spawn to the zai backend. If ``--model`` is absent it is appended. The
    input list is never mutated.
    """
    out = list(cmd)
    for i, part in enumerate(out):
        if part == "--model" and i + 1 < len(out):
            out[i + 1] = model
            return out
    out.extend(("--model", model))
    return out


def _new_counter() -> dict[str, object]:
    """Create a fresh aggregate counter payload."""
    return {
        "inference_calls": 0,
        "prompt_est_tokens": 0,
        "total_est_tokens": 0,
        "total_tokens": 0,
        "history_chars_saved": 0,
        "context_chars_saved": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "actual_usage_calls": 0,
        "usage_unavailable_calls": 0,
        "pruned_chars_total": 0,
        "estimated_cost_microusd": 0,
        "last_updated": "",
        "last_model": "",
    }


def _as_int(value: object) -> int:
    """Best-effort integer conversion for telemetry counters."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _as_float(value: object) -> float:
    """Best-effort float conversion for telemetry cost accumulators."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _get_or_init_dict(
    parent: dict[str, object], key: str, default: dict[str, object]
) -> dict[str, object]:
    current = parent.get(key)
    if isinstance(current, dict):
        return current
    parent[key] = default
    return default
