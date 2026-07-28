"""Regression guard for #10748 — sandbox scenario number-slots must not collide.

Escape ledger context: PR #10570 added ``s88_credit_pause_auto_resume`` while
``s88_pipeline_flow_counts`` already owned the ``s88`` slot. The duplicate
``s88_`` prefix broke the RC-required sandbox suite; the staging RC dry-run
sensor (#10352) surfaced it as ``s88_pipeline_flow_counts`` broken (#10630) and
#10643 fixed it by renumbering the newcomer to ``s89``. The collision escaped
review because nothing asserted number-slot uniqueness at unit time — the RC
dry-run sensor only catches such collisions *reactively*, after they have
already broken a scenario on staging.

This guard encodes the escape as a fast, unit-level detector: the token before
the first underscore in each scenario filename (its "number slot", e.g. ``s88``,
``s09b``) must be unique. Deliberate close-variant suffixes like ``s09`` vs
``s09b`` are DISTINCT slots and remain allowed — only an exact ``sNN_`` clash is
a collision.

Ratchet: the grandfather set is now empty. It once held one pre-existing
collision — ``s50_convergence_review`` (an ADR-0094/0095 conformance anchor)
vs ``s50_disturbance_dampener_idle_poll`` — which #10770 resolved by renumbering
the non-anchor member to the free ``s90`` slot. The self-retiring ratchet
(``test_grandfathered_collisions_are_not_stale``) then forced the stale ``s50``
exception out. The set stays frozen: a NEW collision fails the test, and any
future grandfather entry that stops colliding likewise forces its own removal.
"""

from __future__ import annotations

import collections
from pathlib import Path

# Pre-existing collisions permitted only until their scoped cleanup lands.
# Do NOT add to this set — a new collision must be renumbered, not grandfathered.
# (Was ``{"s50"}``; retired by #10770 once s50_disturbance_dampener_idle_poll
# was renumbered to s90 and the slot no longer collided.)
_GRANDFATHERED_COLLISIONS: frozenset[str] = frozenset()

_SCENARIOS_DIR = (
    Path(__file__).resolve().parents[1] / "sandbox_scenarios" / "scenarios"
)


def _number_slot(stem: str) -> str:
    """The identifier before the first underscore — a scenario's number slot."""
    return stem.split("_", 1)[0]


def _colliding_slots() -> dict[str, list[str]]:
    by_slot: dict[str, list[str]] = collections.defaultdict(list)
    for path in _SCENARIOS_DIR.glob("s*.py"):
        by_slot[_number_slot(path.stem)].append(path.stem)
    return {slot: names for slot, names in by_slot.items() if len(names) > 1}


def test_no_new_scenario_number_slot_collisions() -> None:
    """No two scenarios share a number slot, apart from grandfathered ones."""
    collisions = _colliding_slots()
    new_collisions = {
        slot: names
        for slot, names in collisions.items()
        if slot not in _GRANDFATHERED_COLLISIONS
    }
    assert not new_collisions, (
        "Sandbox scenario number-slot collision(s) — renumber the newcomer to a "
        f"free slot (as #10643 did for s88): {new_collisions}"
    )


def test_grandfathered_collisions_are_not_stale() -> None:
    """Every grandfathered slot must still collide — retire it once fixed.

    Keeps the exception list honest: when a grandfathered collision is
    renumbered away (as #10770 did for s50), this fails and forces removal of
    the now-stale grandfather entry. The set is currently empty, so this is a
    no-op guard until some future collision is ever grandfathered.
    """
    still_colliding = set(_colliding_slots())
    stale = _GRANDFATHERED_COLLISIONS - still_colliding
    assert not stale, (
        "Grandfathered scenario-number collision(s) no longer collide — remove "
        f"them from _GRANDFATHERED_COLLISIONS: {sorted(stale)}"
    )
