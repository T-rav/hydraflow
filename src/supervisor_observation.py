"""Tier-2 goal-supervisor data types + pure decision core (ADR-0124).

The :class:`GoalSupervisorLoop` (Tier-2 liveness) reads a read-only health
snapshot assembled from the existing Tier-1 signals, hands it to a Fable agent
under the standing goal *"keep the factory alive & healthy"*, and records a
:class:`SupervisorObservation` to an append-only thread + the event bus.

This module holds the **dependency-light** data types and the **pure** decision
core so both the loop *and* the dashboard read-endpoint
(``GET /api/diagnostics/supervisor/thread``) can import them without pulling in
the event bus, the subprocess runner, or any Tier-1 detector. The classify /
known-incident / nudge-vs-escalate / give-up-window logic is the load-bearing
safety, so it lives here as pure functions over primitives.

Operating contract (ADR-0124 — mined from how a capable operator runs the
factory). Applied *in order* for every anomaly:

1. **Classify before acting.** transient (flaky check, CDN/NodeSource 403,
   xdist contamination, stray file) → wait/re-run, spend no nudge; real → act
   or escalate. :func:`classify_action`.
2. **Tractable + reversible → self-do; blast radius → escalate.** The nudge
   allowlist (:data:`NUDGE_ALLOWLIST`) is small and explicit; everything else
   — force-push, deletes, config/gate flips (self-mod), RC→main promotion,
   repeated failed heals — is surfaced, never self-done. Mirrors
   ``docs/standards/factory_autonomy``.
3. **Root-cause first.** A nudge must carry a one-line diagnosis pulled from
   the signal; a cause-less action is noise and is dropped.
4. **Bounded retries then escalate** (give-up window, reusing #10735's
   pattern). An incident is nudged at most :data:`GIVEUP_CAP` times before it
   escalates; the attempt ledger persists across ticks. Never infinite-retry.
5. **Counter-metric self-check** (#10840). Repeat-without-improvement is
   over-reach: the give-up window *is* the counter-metric — a nudge that never
   clears its condition escalates instead of looping.
6. **Honest thread.** Each observation states the truth: transient vs real,
   verified vs pending vs escalating. Never a fabricated resolution.
7. **Known-incident knowledge first** (:func:`derive_incidents`). Recognized
   signatures (stale-boot, wedged loop, stuck credit-pause, event-loop freeze,
   diverging vitals) use the known remedy before the agent diagnoses cold.
8. **Verify the nudge + re-arm.** A nudge is *pending* until a later tick
   confirms its condition cleared; a still-present incident counts toward the
   give-up window (rule 4). The loop drives this via the attempt ledger.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Nudge allowlist — the ONLY action kinds the supervisor may self-execute.
# ---------------------------------------------------------------------------
#: Restart a genuinely stalled/wedged loop (``bg_workers.restart``) — reversible.
NUDGE_RESTART_STALLED_LOOP = "restart_stalled_loop"
#: Poke a wedged staging-promotion loop back to life (a targeted restart).
NUDGE_POKE_WEDGED_PROMOTION = "poke_wedged_promotion"
#: Re-run a flaky required check (deferred to CI auto-retry in v1 — no CI seam).
NUDGE_RERUN_FLAKY_CHECK = "rerun_flaky_check"
#: Re-arm a stuck credit-pause / failover switch-back probe so it fires again.
NUDGE_REARM_CREDIT_PROBE = "rearm_credit_probe"
#: Surface boot-SHA / commits-behind staleness (informational; no mutation).
NUDGE_FLAG_BOOT_SHA_STALENESS = "flag_boot_sha_staleness"

#: The small explicit allowlist (rule 2). A proposed action whose ``kind`` is in
#: this set MAY be self-executed; everything else escalates.
NUDGE_ALLOWLIST: frozenset[str] = frozenset(
    {
        NUDGE_RESTART_STALLED_LOOP,
        NUDGE_POKE_WEDGED_PROMOTION,
        NUDGE_RERUN_FLAKY_CHECK,
        NUDGE_REARM_CREDIT_PROBE,
        NUDGE_FLAG_BOOT_SHA_STALENESS,
    }
)

#: Blast-radius tag the agent may attach; an allowlisted ``kind`` still escalates
#: when tagged ``high`` — belt-and-suspenders on top of the allowlist (rule 2).
BLAST_HIGH = "high"

#: Signal classes (rule 1).
CLASS_TRANSIENT = "transient"
CLASS_REAL = "real"

#: Give-up window (rule 4/5): heal-type nudges get one attempt; if the incident
#: persists to the next tick the attempt count reaches the cap and it escalates.
GIVEUP_CAP = 1

#: Substrings that mark a signal as a suspected transient (rule 1 / rule 7).
#: Deliberately conservative — a false "real" is safer than a false "transient".
_TRANSIENT_SIGNATURES: tuple[str, ...] = (
    "flake",
    "flaky",
    "nodesource",
    "cdn",
    "403",
    "xdist",
    "contamination",
    "stray file",
    "stray-file",
    "transient",
    "timeout, retry",
    "network blip",
    "rerun",
    "re-run",
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from agent output (fenced or bare)."""
    match = _JSON_FENCE.search(text)
    raw = match.group(1).strip() if match else text.strip()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_ts(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing ``Z``)."""
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
class LoopHealth(BaseModel):
    """Per-loop liveness derived from its persisted heartbeat."""

    name: str
    status: str  # ok | error | disabled | stalled
    last_run: str | None = None
    age_seconds: float | None = None


class HealthSnapshot(BaseModel):
    """Read-only liveness/health snapshot assembled from Tier-1 signals.

    Never mutates anything and never detects on its own — it *reuses* signals
    that already exist (per-loop heartbeats, credit-failover state, boot-SHA
    staleness, the event-loop watchdog marker, the second-order vitals verdict).
    """

    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    stalled_loops: list[str] = Field(default_factory=list)
    error_loops: list[str] = Field(default_factory=list)
    credit_failover_active: bool = False
    credit_probe_overdue: bool = False
    zai_key_present: bool = False
    boot_sha: str | None = None
    commits_behind: int | None = None
    boot_sha_stale: bool = False
    event_loop_stalled: bool = False
    event_loop_stall_detail: dict[str, Any] | None = None
    vitals_verdict: str | None = None
    loops: list[LoopHealth] = Field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """True when no degradation signal is present (agent not consulted)."""
        return not (
            self.stalled_loops
            or self.error_loops
            or self.boot_sha_stale
            or self.event_loop_stalled
            or self.credit_probe_overdue
            or self.vitals_verdict == "diverging"
        )

    def summary(self) -> dict[str, Any]:
        """Compact dict recorded on the observation + fed to the agent prompt."""
        return {
            "healthy": self.healthy,
            "stalled_loops": self.stalled_loops,
            "error_loops": self.error_loops,
            "credit_failover_active": self.credit_failover_active,
            "credit_probe_overdue": self.credit_probe_overdue,
            "zai_key_present": self.zai_key_present,
            "boot_sha_stale": self.boot_sha_stale,
            "commits_behind": self.commits_behind,
            "event_loop_stalled": self.event_loop_stalled,
            "vitals_verdict": self.vitals_verdict,
        }


class ProposedAction(BaseModel):
    """One action the Fable agent proposes; routed by the pure decision core."""

    kind: str
    target: str | None = None
    reason: str = ""
    signal_class: str = ""  # "transient" | "real" | "" (infer)
    blast: str = "low"  # "low" | "high"


class SupervisorVerdict(BaseModel):
    """Structured verdict returned by the Fable supervisor agent."""

    assessment: str = ""
    insights: list[str] = Field(default_factory=list)
    actions: list[ProposedAction] = Field(default_factory=list)


class SupervisorObservation(BaseModel):
    """One append-only supervisor-thread record (ADR-0124).

    ``ts`` · snapshot summary · ``assessment`` · ``insights`` · ``nudges_taken``
    · ``escalations`` · ``deferred`` — the shape the operator console consumes.
    Each string carries its one-line diagnosis and verification status so the
    thread is *honest* (rule 6): a nudge reads ``pending`` until a later tick
    confirms it cleared; a give-up escalation says so.
    """

    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    snapshot: dict[str, Any] = Field(default_factory=dict)
    assessment: str = ""
    insights: list[str] = Field(default_factory=list)
    nudges_taken: list[str] = Field(default_factory=list)
    escalations: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Incident:
    """One classified anomaly + its remedy — the unit the decision core routes.

    ``key`` is a stable per-incident identity (e.g. ``stalled_loop:diagram``) so
    the attempt ledger can track give-up windows and verify across ticks.
    """

    key: str
    kind: str
    target: str | None
    classification: str  # CLASS_TRANSIENT | CLASS_REAL
    blast: str  # "low" | BLAST_HIGH
    diagnosis: str
    escalate_reason: str = ""


@dataclass
class Decisions:
    """Routed incidents for one tick (all lists are pure derivations)."""

    nudges: list[Incident] = field(default_factory=list)
    escalations: list[Incident] = field(default_factory=list)
    deferred: list[Incident] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure decision core
# ---------------------------------------------------------------------------
def build_health_snapshot(
    *,
    heartbeats: dict[str, dict[str, Any]],
    intervals: dict[str, int],
    now: datetime,
    stall_multiplier: int = 3,
    credit_failover_active: bool = False,
    credit_probe_overdue: bool = False,
    zai_key_present: bool = False,
    boot_sha: str | None = None,
    commits_behind: int | None = None,
    event_loop_stall_marker: dict[str, Any] | None = None,
    vitals_verdict: str | None = None,
) -> HealthSnapshot:
    """Assemble a :class:`HealthSnapshot` from raw Tier-1 signals. **Pure.**

    ``now`` is injected (no clock read) so replayed history scores identically.
    A loop counts as *stalled* when its heartbeat age exceeds
    ``stall_multiplier * interval`` (mirrors ``HealthMonitorLoop``'s
    ``_WORKER_STALL_MULTIPLIER`` rule); a loop counts as *errored* when its last
    heartbeat status is ``error``. ``disabled`` loops are never flagged.
    """
    loops: list[LoopHealth] = []
    stalled: list[str] = []
    errored: list[str] = []
    for name, hb in sorted(heartbeats.items()):
        status = str(hb.get("status") or "ok")
        last_run_raw = hb.get("last_run")
        last_run = last_run_raw if isinstance(last_run_raw, str) else None
        age: float | None = None
        if last_run is not None:
            parsed = _parse_ts(last_run)
            if parsed is not None:
                age = (now - parsed).total_seconds()
        interval = intervals.get(name)
        is_stalled = (
            status != "disabled"
            and age is not None
            and interval is not None
            and age > stall_multiplier * interval
        )
        if status == "error":
            errored.append(name)
        if is_stalled:
            stalled.append(name)
            if status == "ok":
                status = "stalled"
        loops.append(
            LoopHealth(name=name, status=status, last_run=last_run, age_seconds=age)
        )
    return HealthSnapshot(
        ts=now.isoformat(),
        stalled_loops=stalled,
        error_loops=errored,
        credit_failover_active=credit_failover_active,
        credit_probe_overdue=credit_probe_overdue,
        zai_key_present=zai_key_present,
        boot_sha=boot_sha,
        commits_behind=commits_behind,
        boot_sha_stale=bool(commits_behind and commits_behind > 0),
        event_loop_stalled=event_loop_stall_marker is not None,
        event_loop_stall_detail=event_loop_stall_marker,
        vitals_verdict=vitals_verdict,
        loops=loops,
    )


def classify_action(action: ProposedAction) -> str:
    """Classify a proposed action ``transient`` vs ``real`` (rule 1). **Pure.**

    An explicit ``signal_class`` from the agent wins; otherwise a conservative
    substring scan of ``kind`` + ``reason`` against :data:`_TRANSIENT_SIGNATURES`
    — defaulting to ``real`` so ambiguity is treated as actionable, not ignored.
    """
    hint = action.signal_class.strip().lower()
    if hint in (CLASS_TRANSIENT, CLASS_REAL):
        return hint
    text = f"{action.kind} {action.reason}".lower()
    if any(sig in text for sig in _TRANSIENT_SIGNATURES):
        return CLASS_TRANSIENT
    return CLASS_REAL


def derive_incidents(snapshot: HealthSnapshot) -> list[Incident]:
    """Known-incident knowledge first (rule 7): deterministic incidents from the
    snapshot, each with the known remedy. **Pure.**

    Liveness signatures resolve to reversible heals (loop restart, credit-probe
    re-arm, boot-SHA flag); a genuine event-loop freeze and diverging vitals are
    high-blast (Tier-1 restart-to-known-good / human), so they escalate.
    """
    incidents: list[Incident] = []
    for name in snapshot.stalled_loops:
        incidents.append(
            Incident(
                key=f"stalled_loop:{name}",
                kind=NUDGE_RESTART_STALLED_LOOP,
                target=name,
                classification=CLASS_REAL,
                blast="low",
                diagnosis=(f"loop '{name}' heartbeat stalled beyond 3x its interval"),
            )
        )
    for name in snapshot.error_loops:
        if f"stalled_loop:{name}" in {i.key for i in incidents}:
            continue  # already covered by the stall incident
        incidents.append(
            Incident(
                key=f"error_loop:{name}",
                kind=NUDGE_RESTART_STALLED_LOOP,
                target=name,
                classification=CLASS_REAL,
                blast="low",
                diagnosis=f"loop '{name}' last heartbeat reported status=error",
            )
        )
    if snapshot.credit_probe_overdue:
        incidents.append(
            Incident(
                key="credit_probe_overdue",
                kind=NUDGE_REARM_CREDIT_PROBE,
                target=None,
                classification=CLASS_REAL,
                blast="low",
                diagnosis="credit-failover switch-back probe is overdue (stuck)",
            )
        )
    if snapshot.boot_sha_stale:
        incidents.append(
            Incident(
                key="boot_sha_stale",
                kind=NUDGE_FLAG_BOOT_SHA_STALENESS,
                target=None,
                classification=CLASS_REAL,
                blast="low",
                diagnosis=(
                    f"boot SHA is {snapshot.commits_behind} commit(s) behind "
                    "origin/staging"
                ),
            )
        )
    if snapshot.event_loop_stalled:
        incidents.append(
            Incident(
                key="event_loop_stall",
                kind="event_loop_recovery",
                target=None,
                classification=CLASS_REAL,
                blast=BLAST_HIGH,  # restart-to-known-good is Tier-1's job
                diagnosis="event-loop watchdog recorded a freeze episode",
            )
        )
    if snapshot.vitals_verdict == "diverging":
        incidents.append(
            Incident(
                key="vitals_diverging",
                kind="investigate_divergence",
                target=None,
                classification=CLASS_REAL,
                blast=BLAST_HIGH,  # green-while-dying → human judgement
                diagnosis="second-order vitals verdict = diverging (green-while-dying)",
            )
        )
    return incidents


def _action_key(action: ProposedAction) -> str:
    return f"agent:{action.kind}:{action.target or ''}"


def decide(
    *,
    snapshot: HealthSnapshot,
    agent_actions: Iterable[ProposedAction],
    attempts: dict[str, int],
    giveup_cap: int = GIVEUP_CAP,
) -> Decisions:
    """Route every anomaly into nudge / escalate / defer. **Pure.**

    Encodes rules 1–5 + 7 as one deterministic pipeline over the snapshot's
    known incidents and the agent's proposed actions:

    * transient → **defer** (rule 1);
    * cause-less → **defer** (dropped as noise, rule 3);
    * blast-radius or not-allowlisted → **escalate** (rule 2);
    * allowlisted + within the give-up window → **nudge** (rule 2/4);
    * allowlisted + window exhausted → **escalate** (rule 4/5).

    ``attempts`` is the persisted give-up ledger keyed by ``Incident.key``.
    """
    decisions = Decisions()
    seen: set[str] = set()

    def route(inc: Incident) -> None:
        if inc.classification == CLASS_TRANSIENT:
            decisions.deferred.append(inc)
            return
        if not inc.diagnosis.strip():
            # rule 3: a nudge without a cause is noise — do not act.
            decisions.deferred.append(inc)
            return
        tractable = inc.kind in NUDGE_ALLOWLIST and inc.blast != BLAST_HIGH
        if not tractable:
            decisions.escalations.append(inc)
            return
        prior = attempts.get(inc.key, 0)
        if prior >= giveup_cap:
            # rule 4/5: repeat-without-improvement → escalate, stop nudging.
            decisions.escalations.append(
                Incident(
                    key=inc.key,
                    kind=inc.kind,
                    target=inc.target,
                    classification=inc.classification,
                    blast=inc.blast,
                    diagnosis=inc.diagnosis,
                    escalate_reason=(
                        f"give-up window exhausted after {prior} nudge(s) with "
                        "no improvement"
                    ),
                )
            )
            return
        decisions.nudges.append(inc)

    # rule 7: known-incident knowledge first (deterministic).
    for inc in derive_incidents(snapshot):
        seen.add(inc.key)
        route(inc)
    # then the agent's novel signals (skip anything already handled).
    for action in agent_actions:
        key = _action_key(action)
        if key in seen:
            continue
        seen.add(key)
        route(
            Incident(
                key=key,
                kind=action.kind,
                target=action.target,
                classification=classify_action(action),
                blast=action.blast,
                diagnosis=action.reason,
            )
        )
    return decisions


def parse_supervisor_verdict(transcript: str) -> SupervisorVerdict:
    """Extract the JSON verdict from agent output; tolerant of prose/fences."""
    data = _extract_json(transcript)
    if data is None:
        return SupervisorVerdict(assessment="(no parseable verdict)")
    try:
        return SupervisorVerdict.model_validate(data)
    except ValidationError:
        return SupervisorVerdict(assessment="(invalid verdict shape)")


# ---------------------------------------------------------------------------
# Thread + attempt-ledger persistence
# ---------------------------------------------------------------------------
def supervisor_thread_path(config: HydraFlowConfig) -> Path:
    """Single source of truth for the append-only thread location (data_root)."""
    return Path(config.data_root) / "supervisor_thread.jsonl"


def supervisor_ledger_path(config: HydraFlowConfig) -> Path:
    """Give-up-window attempt ledger (per-incident counts) under data_root."""
    return Path(config.data_root) / "supervisor_attempts.json"


def append_observation(config: HydraFlowConfig, obs: SupervisorObservation) -> None:
    """Append one observation to the thread JSONL (creates parent dirs)."""
    path = supervisor_thread_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(obs.model_dump_json() + "\n")


def read_thread(config: HydraFlowConfig, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent ``limit`` observation dicts (newest last).

    Corrupt lines are skipped, never raised — the panel must render on a
    partially-written tail.
    """
    path = supervisor_thread_path(config)
    if not path.exists():
        return []
    try:
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
    return rows[-limit:]


def load_attempts(config: HydraFlowConfig) -> dict[str, int]:
    """Load the give-up-window attempt ledger (best-effort; ``{}`` on error)."""
    path = supervisor_ledger_path(config)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int | float)}


def save_attempts(config: HydraFlowConfig, attempts: dict[str, int]) -> None:
    """Persist the give-up-window attempt ledger."""
    path = supervisor_ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attempts, sort_keys=True), encoding="utf-8")


def reconcile_ledger(
    attempts: dict[str, int], active_keys: set[str]
) -> tuple[dict[str, int], list[str]]:
    """Verify + re-arm the ledger against the current tick (rule 8). **Pure.**

    Any ledger key that is no longer an active incident *cleared* — a prior
    nudge is now verified; drop it so its give-up window resets. Returns the
    pruned ledger and the list of cleared (verified) keys.
    """
    cleared = [key for key in attempts if key not in active_keys]
    pruned = {k: v for k, v in attempts.items() if k in active_keys}
    return pruned, cleared
