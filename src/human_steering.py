"""Pure parser for continuous human-steering directives (ADR-0099 surface #4).

A directive is a comment line beginning with '/' + a known verb. Declarative
verbs (steer/pause/resume) are recomputed latest-wins each tick (idempotent);
imperative verbs (redo/abort) fire once, gated by a created_at high-water-mark.
No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

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
