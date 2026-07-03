"""Pure parser for continuous human-steering directives (ADR-0099 surface #4).

A directive is a comment line beginning with '/' + a known verb. Declarative
verbs (steer/pause/resume) are recomputed latest-wins each tick (idempotent);
imperative verbs (redo/abort) fire once, gated by a created_at high-water-mark.
No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from models import SteeringState

_FLOW_RUNNING = "running"
_FLOW_PAUSED = "paused"
_FLOW_ABORT = "abort"


@dataclass(frozen=True)
class SteeringDirectives:
    guidance: str | None
    flow: str
    redo_phase: str | None
    new_last_applied_ts: str | None


def _verb_and_rest(body: str) -> tuple[str, str] | None:
    line = body.strip().splitlines()[0].strip() if body.strip() else ""
    if not line.startswith("/"):
        return None
    head, _, rest = line[1:].partition(" ")
    return head.strip().lower(), rest.strip()


def parse_directives(
    comments: list[dict], last_applied_ts: str | None
) -> SteeringDirectives:
    guidance: str | None = None
    flow = _FLOW_RUNNING
    redo_phase: str | None = None
    new_mark = last_applied_ts
    saw_abort = False

    for c in comments:  # oldest-first
        parsed = _verb_and_rest(str(c.get("body", "")))
        if parsed is None:
            continue
        verb, rest = parsed
        ts = str(c.get("created_at", ""))
        if verb == "steer":
            guidance = rest or guidance
        elif verb == "pause":
            if not saw_abort:
                flow = _FLOW_PAUSED
        elif verb == "resume":
            if not saw_abort:
                flow = _FLOW_RUNNING
        elif verb == "abort":
            # imperative: fire once past the high-water-mark
            if last_applied_ts is None or ts > last_applied_ts:
                saw_abort = True
                flow = _FLOW_ABORT
                new_mark = ts if (new_mark is None or ts > new_mark) else new_mark
        elif (
            verb == "redo"
            and rest
            and (last_applied_ts is None or ts > last_applied_ts)
        ):
            redo_phase = rest.split()[0]
            new_mark = ts if (new_mark is None or ts > new_mark) else new_mark
        # unknown verbs ignored
    if saw_abort:
        redo_phase = None  # abort precedence
    return SteeringDirectives(
        guidance=guidance,
        flow=flow,
        redo_phase=redo_phase,
        new_last_applied_ts=new_mark,
    )


@dataclass(frozen=True)
class SteeringDecision:
    """Actuator decision for one issue at a phase boundary (orchestrator seam).

    Pure translation of a per-issue `SteeringState` into what the orchestrator
    should enact this cycle: skip scheduling (pause), park at the recoverable
    terminal label (abort), re-enqueue to a phase (redo), and/or fold fenced
    guidance into the next phase prompt. No I/O; the orchestrator stays thin
    by calling `apply_steering` and enacting the result verbatim.
    """

    skip: bool  # paused -> don't schedule a new phase this cycle
    park: bool  # abort -> move to recoverable terminal label
    redo_phase: str | None
    new_redo_count: int
    guidance: str | None


def apply_steering(
    state: SteeringState,
    issue: str,
    known_phases: set[str],
    max_redos: int,
) -> SteeringDecision:
    """Decide what the orchestrator should do for `issue` this phase boundary.

    Precedence (per steering-global-constraints): abort > pause > redo. Redo is
    only honored for a phase name present in `known_phases` and while
    `state.redo_count < max_redos`; otherwise it is silently ignored (dropped,
    not retried) so a stale/bogus `/redo` doesn't stall the issue forever.
    """
    if state.flow == _FLOW_ABORT:
        return SteeringDecision(
            skip=False,
            park=True,
            redo_phase=None,
            new_redo_count=state.redo_count,
            guidance=state.guidance,
        )
    if state.flow == _FLOW_PAUSED:
        return SteeringDecision(
            skip=True,
            park=False,
            redo_phase=None,
            new_redo_count=state.redo_count,
            guidance=state.guidance,
        )
    redo_phase = None
    new_redo_count = state.redo_count
    if (
        state.redo_phase
        and state.redo_phase in known_phases
        and state.redo_count < max_redos
    ):
        redo_phase = state.redo_phase
        new_redo_count = state.redo_count + 1
    return SteeringDecision(
        skip=False,
        park=False,
        redo_phase=redo_phase,
        new_redo_count=new_redo_count,
        guidance=state.guidance,
    )
