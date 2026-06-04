"""Background worker loop — low-noise Honeycomb SLO / burn-alert ingestion.

The inbound analog of :class:`sentry_loop.SentryLoop`, but tuned for LOW
NOISE (Sentry was too chatty). It polls the Honeycomb *Management* API for
SLO error-budget state and burn-alert state across configured datasets and
files a GitHub issue ONLY for *sustained, budget-backed* reliability
breaches — never on a first observation, never on a transient blip.

Noise controls (the entire point of this loop):

* **Sustained-across-N-polls gate.** A breach must persist for
  ``honeycomb_min_sustained_polls`` *consecutive* polls before it files.
  The observation counter resets the moment the signal clears.
* **Budget threshold.** The SLO path fires only when the remaining error
  budget percent is ``<= honeycomb_slo_budget_threshold_pct``. The
  burn-alert path additionally requires an ALERTING/TRIGGERED state
  AND budget below threshold (AND-ed).
* **Per-signal cooldown.** After filing or auto-closing, a signal is muted
  for ``honeycomb_signal_cooldown_hours``.
* **Resolution-sync auto-close.** When the SLO recovers / burn alert clears,
  the issue we filed is auto-closed with a 'recovered' comment.
* **Trigger ingestion is default-OFF** and carries the hardest sustained gate.
* **Cross-signal dedup.** A burn alert and its parent SLO breaching emit ONE
  issue, keyed on the SLO id.

Ships DEFAULT-DISABLED: ``honeycomb_ingest_loop_enabled`` is False and no
inbound mgmt key exists yet. With either unset the loop is a no-op.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug
from file_util import atomic_write
from subprocess_util import AuthenticationError, CreditExhaustedError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ports import PRPort

logger = logging.getLogger("hydraflow.honeycomb_loop")

# Burn-alert states that count as "firing". Honeycomb uses uppercase
# ``TRIGGERED`` for active alerts; we tolerate a few synonyms defensively.
_FIRING_STATES: frozenset[str] = frozenset(
    {"alerting", "triggered", "exhausted", "firing"}
)

_MARKER_PREFIX = "honeycomb"


@dataclass
class _SignalState:
    """Persisted per-signal noise-control state.

    Keyed by a stable ``signal_id`` (the SLO id, so a burn alert and its
    parent SLO share one entry — cross-signal dedup).
    """

    observations: int = 0
    issue_number: int = 0
    creation_attempts: int = 0
    last_event_at: str = ""  # ISO timestamp of the last file/close
    parked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "issue_number": self.issue_number,
            "creation_attempts": self.creation_attempts,
            "last_event_at": self.last_event_at,
            "parked": self.parked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _SignalState:
        return cls(
            observations=int(data.get("observations", 0) or 0),
            issue_number=int(data.get("issue_number", 0) or 0),
            creation_attempts=int(data.get("creation_attempts", 0) or 0),
            last_event_at=str(data.get("last_event_at", "") or ""),
            parked=bool(data.get("parked", False)),
        )


@dataclass
class _LoopState:
    """JSON-backed per-signal state, persisted alongside the dedup stores.

    Self-contained so this PR doesn't touch the ``StateData`` schema. An
    in-memory-only instance (``path=None``) is used by unit tests.
    """

    path: Path | None
    signals: dict[str, _SignalState] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> _LoopState:
        if path is None or not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text())
            signals = {
                key: _SignalState.from_dict(val)
                for key, val in raw.get("signals", {}).items()
                if isinstance(val, dict)
            }
            return cls(path=path, signals=signals)
        except (json.JSONDecodeError, TypeError, OSError):
            logger.warning("Honeycomb loop state unreadable — starting fresh")
            return cls(path=path)

    def get(self, signal_id: str) -> _SignalState:
        return self.signals.setdefault(signal_id, _SignalState())

    def drop(self, signal_id: str) -> None:
        self.signals.pop(signal_id, None)

    def save(self) -> None:
        if self.path is None:
            return
        try:
            payload = {"signals": {k: v.to_dict() for k, v in self.signals.items()}}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, json.dumps(payload, sort_keys=True))
        except OSError:
            logger.warning("Could not persist Honeycomb loop state", exc_info=True)


# A single normalized signal derived from an SLO (+ optional burn alert).
@dataclass
class _Signal:
    signal_id: str  # stable id (SLO id) — drives dedup + cross-signal collapse
    name: str
    dataset: str
    budget_remaining_pct: float
    target_pct: float | None
    burn_alert_firing: bool
    is_trigger_only: bool  # True => only a burn alert, no SLO budget context


class HoneycombIngestLoop(BaseBackgroundLoop):
    """Polls Honeycomb SLOs / burn alerts and files sustained-breach issues."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        credentials: Credentials | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
        state_path: Path | None = None,
    ) -> None:
        super().__init__(
            worker_name="honeycomb_ingest",
            config=config,
            deps=deps,
            run_on_startup=True,
        )
        self._prs = prs
        self._credentials = credentials or Credentials()
        # Injected so tests can substitute a fake transport with canned JSON.
        self._http_client_factory = http_client_factory or self._default_client
        if state_path is None:
            state_path = config.data_root / "dedup" / "honeycomb_signals.json"
        self._state = _LoopState.load(state_path)

    # ------------------------------------------------------------------ infra
    def _get_default_interval(self) -> int:
        return self._config.honeycomb_poll_interval

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30, base_url=self._config.honeycomb_api_base)

    def _headers(self) -> dict[str, str]:
        headers = {"X-Honeycomb-Team": self._credentials.honeycomb_mgmt_api_key}
        if self._config.honeycomb_environment:
            headers["X-Honeycomb-Dataset"] = self._config.honeycomb_environment
        return headers

    # ------------------------------------------------------------- main cycle
    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049 in-body kill-switch gate MUST be the first statement.
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if (
            not self._config.honeycomb_ingest_loop_enabled
            or not self._credentials.honeycomb_mgmt_api_key
        ):
            # No inbound key / flag off => no-op (the safe default-disabled state).
            return {"status": "disabled"}

        datasets = await self._resolve_datasets()
        created = 0
        closed = 0
        skipped = 0
        observed = 0
        seen_signal_ids: set[str] = set()

        for dataset in datasets:
            try:
                signals = await self._collect_signals(dataset)
            except (AuthenticationError, CreditExhaustedError):
                raise
            except httpx.HTTPError:
                # One bad dataset must not kill the whole tick.
                logger.warning("Honeycomb API error for dataset %s — skipping", dataset)
                skipped += 1
                continue
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Honeycomb dataset %s processing failed — skipping",
                    dataset,
                    exc_info=True,
                )
                skipped += 1
                continue

            for signal in signals:
                seen_signal_ids.add(signal.signal_id)
                observed += 1
                try:
                    c_made, c_closed = await self._process_signal(signal)
                except (AuthenticationError, CreditExhaustedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    reraise_on_credit_or_bug(exc)
                    logger.warning(
                        "Honeycomb signal %s failed — skipping",
                        signal.signal_id,
                        exc_info=True,
                    )
                    skipped += 1
                    continue
                created += c_made
                closed += c_closed

        # Any tracked signal NOT seen this poll has cleared: auto-close + reset.
        closed += await self._reconcile_cleared(seen_signal_ids)

        self._state.save()
        return {
            "datasets_polled": len(datasets),
            "signals_observed": observed,
            "issues_created": created,
            "issues_closed": closed,
            "skipped": skipped,
        }

    # ----------------------------------------------------------- per-signal
    async def _process_signal(self, signal: _Signal) -> tuple[int, int]:
        """Apply the noise gates to one signal. Returns (created, closed)."""
        state = self._state.get(signal.signal_id)
        breaching = self._is_breaching(signal)

        if not breaching:
            # Signal healthy: reset the sustained counter immediately, and
            # auto-close any issue we previously filed for it.
            closed = await self._maybe_auto_close(signal.signal_id, signal)
            state.observations = 0
            return 0, closed

        # Breach observed this poll — advance the sustained counter.
        state.observations += 1

        if state.issue_number:
            # Already filed and still breaching: nothing to do.
            return 0, 0

        if state.parked:
            # Exhausted creation attempts previously; stay muted.
            return 0, 0

        if self._in_cooldown(state):
            return 0, 0

        required = self._required_polls(signal)
        if state.observations < required:
            # Not sustained long enough yet — the core noise control.
            return 0, 0

        filed = await self._file_issue(signal, state)
        return (1 if filed else 0), 0

    def _is_breaching(self, signal: _Signal) -> bool:
        """Whether *signal* counts as a budget-backed reliability breach."""
        threshold = self._config.honeycomb_slo_budget_threshold_pct
        budget_breached = signal.budget_remaining_pct <= threshold
        if signal.is_trigger_only:
            # Per-trigger class: opt-in, and a firing burn alert is required.
            if not self._config.honeycomb_trigger_ingest_enabled:
                return False
            return signal.burn_alert_firing
        if signal.burn_alert_firing:
            # Burn-alert path: firing AND budget below threshold (AND-ed).
            return budget_breached
        # Pure SLO path: budget at/under the configured threshold.
        return budget_breached

    def _required_polls(self, signal: _Signal) -> int:
        if signal.is_trigger_only:
            return self._config.honeycomb_trigger_sustained_polls
        return self._config.honeycomb_min_sustained_polls

    def _in_cooldown(self, state: _SignalState) -> bool:
        if not state.last_event_at:
            return False
        try:
            last = datetime.fromisoformat(state.last_event_at)
        except ValueError:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed_h = (datetime.now(UTC) - last).total_seconds() / 3600.0
        return elapsed_h < self._config.honeycomb_signal_cooldown_hours

    # ------------------------------------------------------------ filing
    async def _file_issue(self, signal: _Signal, state: _SignalState) -> bool:
        title = f"[Honeycomb] Sustained SLO breach: {signal.name} ({signal.dataset})"
        body = self._build_body(signal)

        # GitHub-side backstop: if an open issue with our marker already
        # exists (e.g. a prior tick crashed after create), adopt it instead
        # of duplicating.
        existing = await self._find_existing_issue(signal.signal_id, title)
        if existing:
            state.issue_number = existing
            state.last_event_at = datetime.now(UTC).isoformat()
            logger.info(
                "Honeycomb signal %s already filed as #%d — adopting",
                signal.signal_id,
                existing,
            )
            return False

        label = self._config.planner_label[0] if self._config.planner_label else None
        labels = [label] if label else None
        try:
            number = await self._prs.create_issue(title, body, labels=labels)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            state.creation_attempts += 1
            if state.creation_attempts >= self._config.honeycomb_max_creation_attempts:
                state.parked = True
                logger.warning(
                    "Parking Honeycomb signal %s after %d failed creation attempts",
                    signal.signal_id,
                    state.creation_attempts,
                )
            else:
                logger.warning(
                    "Failed to file Honeycomb issue for %s (attempt %d)",
                    signal.signal_id,
                    state.creation_attempts,
                    exc_info=True,
                )
            return False

        if not number:
            state.creation_attempts += 1
            return False

        state.issue_number = number
        state.creation_attempts = 0
        state.last_event_at = datetime.now(UTC).isoformat()
        logger.info(
            "Filed Honeycomb SLO breach %s as issue #%d", signal.signal_id, number
        )
        return True

    def _build_body(self, signal: _Signal) -> str:
        target = (
            f"{signal.target_pct:.2f}%" if signal.target_pct is not None else "unknown"
        )
        firing = "yes" if signal.burn_alert_firing else "no"
        parts = [
            f"## Honeycomb reliability breach: {signal.name}",
            "",
            f"- **Dataset:** `{signal.dataset}`",
            f"- **Remaining error budget:** {signal.budget_remaining_pct:.2f}%",
            f"- **SLO target:** {target}",
            f"- **Burn alert firing:** {firing}",
            "",
            (
                "This SLO has breached its error-budget threshold for the "
                "configured number of consecutive polls. Investigate the "
                "underlying reliability regression."
            ),
            "",
            f"<!-- [{_MARKER_PREFIX}:{signal.signal_id}] -->",
        ]
        return "\n".join(parts)

    async def _find_existing_issue(self, signal_id: str, title: str) -> int:
        """Best-effort lookup of an already-open issue for this signal.

        Fail-open: any error returns 0 ("not found, proceed") so a flaky
        GitHub call doesn't block ingestion.
        """
        try:
            existing = await self._prs.find_existing_issue(title)
            return int(existing or 0)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Honeycomb existing-issue lookup failed for %s",
                signal_id,
                exc_info=True,
            )
            return 0

    # ------------------------------------------------------------ auto-close
    async def _maybe_auto_close(self, signal_id: str, signal: _Signal | None) -> int:
        """Close our filed issue when the signal recovers. Returns 1 if closed."""
        state = self._state.signals.get(signal_id)
        if state is None or not state.issue_number:
            return 0
        if not self._config.honeycomb_auto_close_enabled:
            # Still clear our tracking so we re-file cleanly on a future breach.
            self._state.drop(signal_id)
            return 0

        issue_number = state.issue_number
        name = signal.name if signal else signal_id
        try:
            await self._prs.post_comment(
                issue_number,
                (
                    f"Honeycomb signal `{name}` has recovered — the SLO error "
                    "budget is back above threshold / the burn alert cleared. "
                    "Auto-closing.\n\n"
                    f"<!-- [{_MARKER_PREFIX}:{signal_id}] -->"
                ),
            )
            await self._prs.close_issue(issue_number)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Failed to auto-close Honeycomb issue #%d for %s",
                issue_number,
                signal_id,
                exc_info=True,
            )
            return 0

        # Reset tracking but keep a cooldown stamp so we don't immediately re-file.
        self._state.drop(signal_id)
        recovered = self._state.get(signal_id)
        recovered.last_event_at = datetime.now(UTC).isoformat()
        logger.info(
            "Auto-closed Honeycomb issue #%d after %s recovered",
            issue_number,
            signal_id,
        )
        return 1

    async def _reconcile_cleared(self, seen_signal_ids: set[str]) -> int:
        """Auto-close issues for tracked signals absent from this poll.

        A signal that vanishes from the API response (SLO deleted, alert
        cleared and no longer returned) is treated as recovered.
        """
        closed = 0
        # Snapshot keys: _maybe_auto_close mutates the dict.
        for signal_id in list(self._state.signals.keys()):
            if signal_id in seen_signal_ids:
                continue
            state = self._state.signals[signal_id]
            if not state.issue_number:
                continue
            closed += await self._maybe_auto_close(signal_id, None)
        return closed

    # ------------------------------------------------------------ API polling
    async def _resolve_datasets(self) -> list[str]:
        """Configured dataset slugs, or all accessible ones when unset."""
        configured = self._config.honeycomb_datasets.strip()
        if configured:
            return [s.strip() for s in configured.split(",") if s.strip()]
        try:
            return await self._list_datasets()
        except httpx.HTTPError:
            logger.warning("Honeycomb dataset listing failed", exc_info=True)
            return []

    async def _list_datasets(self) -> list[str]:
        async with self._http_client_factory() as client:
            resp = await client.get("/1/datasets", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        slugs: list[str] = []
        for entry in data if isinstance(data, list) else []:
            slug = entry.get("slug") or entry.get("name")
            if slug:
                slugs.append(str(slug))
        return slugs

    async def _collect_signals(self, dataset: str) -> list[_Signal]:
        """Build normalized signals for *dataset* from SLOs + burn alerts.

        Cross-signal dedup happens here: burn alerts are matched to their
        parent SLO id, so the parent SLO's signal carries the firing flag
        and a burn alert without a known SLO becomes a trigger-only signal.
        """
        slos = await self._fetch_slos(dataset)
        burn_alerts = await self._fetch_burn_alerts(dataset)

        firing_slo_ids: set[str] = set()
        orphan_alerts: list[dict[str, Any]] = []
        for alert in burn_alerts:
            if not self._alert_firing(alert):
                continue
            slo_id = str(
                (alert.get("slo") or {}).get("id") or alert.get("slo_id") or ""
            )
            if slo_id:
                firing_slo_ids.add(slo_id)
            else:
                orphan_alerts.append(alert)

        signals: list[_Signal] = []
        for slo in slos:
            slo_id = str(slo.get("id") or slo.get("slug") or "")
            if not slo_id:
                continue
            signals.append(
                _Signal(
                    signal_id=slo_id,
                    name=str(slo.get("name") or slo_id),
                    dataset=dataset,
                    budget_remaining_pct=self._budget_pct(slo),
                    target_pct=self._target_pct(slo),
                    burn_alert_firing=slo_id in firing_slo_ids,
                    is_trigger_only=False,
                )
            )

        # Burn alerts with no parent SLO in our data → trigger-only signals.
        for alert in orphan_alerts:
            alert_id = str(alert.get("id") or "")
            if not alert_id:
                continue
            signals.append(
                _Signal(
                    signal_id=f"alert:{alert_id}",
                    name=str(alert.get("name") or alert_id),
                    dataset=dataset,
                    budget_remaining_pct=0.0,
                    target_pct=None,
                    burn_alert_firing=True,
                    is_trigger_only=True,
                )
            )
        return signals

    async def _fetch_slos(self, dataset: str) -> list[dict[str, Any]]:
        async with self._http_client_factory() as client:
            resp = await client.get(
                f"/1/slos/{quote(dataset, safe='')}", headers=self._headers()
            )
            resp.raise_for_status()
            data = resp.json()
        return list(data) if isinstance(data, list) else []

    async def _fetch_burn_alerts(self, dataset: str) -> list[dict[str, Any]]:
        async with self._http_client_factory() as client:
            resp = await client.get(
                f"/1/burn_alerts/{quote(dataset, safe='')}", headers=self._headers()
            )
            resp.raise_for_status()
            data = resp.json()
        return list(data) if isinstance(data, list) else []

    @staticmethod
    def _alert_firing(alert: dict[str, Any]) -> bool:
        state = str(alert.get("alert_type") or alert.get("state") or "").lower()
        return state in _FIRING_STATES

    @staticmethod
    def _budget_pct(slo: dict[str, Any]) -> float:
        """Remaining error budget as a percent (0–100).

        Honeycomb returns ``budget_remaining`` as a 0–1 fraction; some
        payloads use ``compliance``/``budget_remaining_percentage``. We
        normalize to a percent and clamp to [<=0, 100].
        """
        for key in ("budget_remaining_percentage", "budget_remaining_pct"):
            if key in slo and slo[key] is not None:
                return float(slo[key])
        raw = slo.get("budget_remaining")
        if raw is None:
            # No budget info → treat as exhausted (0%) so it can be gated by
            # threshold rather than silently ignored.
            return 0.0
        val = float(raw)
        # Fraction in [-1, 1] → percent; already-percent values pass through.
        if -1.0 <= val <= 1.0:
            return val * 100.0
        return val

    @staticmethod
    def _target_pct(slo: dict[str, Any]) -> float | None:
        for key in ("target_per_million", "target_per_million_events"):
            if key in slo and slo[key] is not None:
                return float(slo[key]) / 10_000.0
        if slo.get("target") is not None:
            val = float(slo["target"])
            return val * 100.0 if -1.0 <= val <= 1.0 else val
        return None
