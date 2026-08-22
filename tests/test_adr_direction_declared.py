"""ADR-0123 bidirectional enforcement: every Accepted ADR declares **Binds:**.

A governance rule that binds only the plant and not the governor is not a rule —
it is a habit the operator was silently supplying (#10849). The
``**Binds:** work | factory | both`` frontmatter makes the direction explicit;
an *unstated* direction is the defect this test forbids, because an unstated
direction is how a downward-only rule passes for a complete one.

Ratchet + grandfather: the ADRs Accepted before this field existed are
baselined in ``_GRANDFATHERED_NO_BINDS``. The set only SHRINKS — when a
grandfathered ADR gains a ``Binds:`` line, delete its number here. A *newly*
Accepted ADR (not in the baseline) must declare a valid direction from the
start, or this test fails.
"""

from __future__ import annotations

from pathlib import Path

from adr_index import scan_adr_directory

_ADR_DIR = Path(__file__).resolve().parents[1] / "docs" / "adr"

#: Accepted ADRs that predate the ADR-0123 ``Binds:`` field. SHRINK-ONLY: as
#: each gains a ``- **Binds:** ...`` line, remove its number. Never add to this
#: set — a newly Accepted ADR must declare its direction from the start.
#: An ADR also leaves the baseline by leaving the Accepted population: #11600
#: dropped 56 when ADR-0136 superseded it. Superseded ADRs are frozen history
#: and carry no direction obligation, so the debt is retired either way.
_GRANDFATHERED_NO_BINDS = frozenset(
    {
        1,
        2,
        4,
        5,
        7,
        8,
        9,
        10,
        11,
        12,
        14,
        15,
        16,
        17,
        18,
        19,
        21,
        22,
        23,
        24,
        25,
        27,
        28,
        29,
        30,
        32,
        34,
        35,
        37,
        41,
        42,
        43,
        45,
        47,
        49,
        50,
        51,
        52,
        53,
        54,
        57,
        58,
        60,
        61,
        62,
        64,
        65,
        71,
        83,
        85,
        88,
        89,
        90,
        92,
        93,
        94,
        95,
        96,
        97,
        98,
        99,
        100,
        102,
        103,
        104,
        106,
        107,
        109,
        110,
        111,
        112,
        113,
        114,
        115,
    }
)


def _accepted_adrs():
    return [a for a in scan_adr_directory(_ADR_DIR) if a.status == "Accepted"]


def test_every_accepted_adr_declares_bind_direction() -> None:
    """Every Accepted ADR outside the grandfather baseline states its direction."""
    missing = {a.number for a in _accepted_adrs() if a.binds == "unknown"}
    new_missing = sorted(missing - _GRANDFATHERED_NO_BINDS)
    assert not new_missing, (
        f"Accepted ADR(s) {new_missing} do not declare a **Binds:** direction "
        "(work | factory | both). Every rule must state which direction it binds "
        "— an unstated direction is how a downward-only rule passes for a "
        "complete one (ADR-0123). Add a `- **Binds:** work|factory|both` line to "
        "the frontmatter."
    )


def test_binds_baseline_only_shrinks() -> None:
    """A grandfathered ADR that now declares Binds must leave the baseline."""
    missing = {a.number for a in _accepted_adrs() if a.binds == "unknown"}
    healed = sorted(_GRANDFATHERED_NO_BINDS - missing)
    assert not healed, (
        f"ADR(s) {healed} now declare **Binds:** — remove them from "
        "_GRANDFATHERED_NO_BINDS. The baseline only shrinks, so the "
        "unstated-direction debt can never silently reappear."
    )


def test_introducing_adr_0123_declares_both() -> None:
    """ADR-0123 must exemplify the rule it introduces (it binds work and factory)."""
    adr = next((a for a in scan_adr_directory(_ADR_DIR) if a.number == 123), None)
    assert adr is not None, "ADR-0123 (bidirectional enforcement) not found"
    assert adr.binds == "both", (
        f"ADR-0123 introduces the Binds: field and must declare `both`, got "
        f"{adr.binds!r}"
    )
